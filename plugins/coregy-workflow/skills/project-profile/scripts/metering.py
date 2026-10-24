"""
Per-agent token metering for Coregy Workflow.

Claude Code writes every subagent's conversation to its own transcript,
`~/.claude/projects/<project>/<session>/subagents/agent-<id>.jsonl`, next to
an `agent-<id>.meta.json` naming the agent type. Each assistant message
carries the API `usage` block, so the tokens an agent spent are a sum over
its transcript -- no estimate, no API call. A background agent's tool result
has no usage at all, which is why the transcript, not the Agent tool result,
is the source.

Runs are recorded in `.coregy/metering.json` (per-machine, self-gitignored),
keyed by agent id, and bound to the workflow agent run they belong to
(workflow_id, phase, agent_log index, fix round) so a report can show what a
feature cost per agent and how much of it went to fix rounds.

Recording happens two ways, both idempotent:
  - the SubagentStop hook (`hooks/metering_hook.py`) records each agent as
    it finishes;
  - `collect` sweeps the project's transcript dir and records anything the
    hook missed (hook disabled, older Claude Code, plugin installed later).

Optional `.coregy/metering.yaml` with a `prices:` table adds a cost column
(see load_prices).

Usage:
    python3 metering.py collect --cwd <dir> [--json]
    python3 metering.py report --cwd <dir> [--workflow current|all|<id>]
                                [--by agent|phase|workflow|model] [--json]
    python3 metering.py record --transcript <agent-x.jsonl> --cwd <dir>
    python3 metering.py clear --cwd <dir> --force
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

try:
    from . import mini_yaml
except ImportError:
    import mini_yaml

METER_FILE = "metering.json"
TOKEN_KEYS = ("input", "cache_write", "cache_read", "output")
# Cache reads are most of an agent's context on every turn and cost a tenth
# of fresh input, so `total` overstates what a run cost; `fresh` (input +
# cache writes + output) is the column to compare agents by.
CONFIG_FILE = "metering.yaml"
CACHE_WRITE_RATIO = 1.25  # x input price, when a price entry omits it
CACHE_READ_RATIO = 0.1
GROUPINGS = ("agent", "phase", "workflow", "model")
# start-agent runs just before the Agent tool call; allow for clock skew
# between state.json's _now() and the transcript's timestamps.
START_SLACK_SECONDS = 120


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def normalize_agent(agent_type):
    """`coregy-workflow:unit-tester` -> `unit-tester`; plain names pass through."""
    if not agent_type:
        return "unknown"
    return str(agent_type).rsplit(":", 1)[-1] or "unknown"


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def parse_transcript(path):
    """Sum the usage of every assistant message in a transcript.

    Streaming writes one line per content block, each repeating the message's
    usage (output_tokens grows as it streams), so lines are de-duplicated by
    message id and the largest output count wins.

    Returns None when the file cannot be read.
    """
    try:
        f = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return None
    messages = {}
    tool_ids = set()
    models = {}
    first = last = None
    agent_id = session_id = None
    with f:
        for n, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            agent_id = agent_id or entry.get("agentId")
            session_id = session_id or entry.get("sessionId")
            ts = _parse_ts(entry.get("timestamp"))
            if ts:
                first = ts if first is None or ts < first else first
                last = ts if last is None or ts > last else last
            if entry.get("type") != "assistant":
                continue
            msg = entry.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
            key = msg.get("id") or entry.get("requestId") or "line-%d" % n
            prev = messages.get(key)
            if prev is None or (usage.get("output_tokens") or 0) >= prev["output"]:
                messages[key] = {
                    "input": usage.get("input_tokens") or 0,
                    "cache_write": usage.get("cache_creation_input_tokens") or 0,
                    "cache_read": usage.get("cache_read_input_tokens") or 0,
                    "output": usage.get("output_tokens") or 0,
                    "model": msg.get("model"),
                }
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_ids.add(block.get("id") or "%s-%d" % (key, len(tool_ids)))

    totals = {k: 0 for k in TOKEN_KEYS}
    for m in messages.values():
        for k in TOKEN_KEYS:
            totals[k] += m[k]
        if m["model"] and m["model"] != "<synthetic>":
            per = models.setdefault(m["model"], {k: 0 for k in TOKEN_KEYS})
            for k in TOKEN_KEYS:
                per[k] += m[k]
    totals["total"] = sum(totals[k] for k in TOKEN_KEYS)
    totals["fresh"] = totals["total"] - totals["cache_read"]
    totals.update({
        "turns": len(messages),
        "tool_uses": len(tool_ids),
        "models": sorted(models, key=lambda m: -sum(models[m].values())),
        "by_model": models,
        "started_at": _iso(first),
        "ended_at": _iso(last),
        "duration_s": int((last - first).total_seconds()) if first and last else None,
        "agent_id": agent_id,
        "session_id": session_id,
    })
    return totals


def read_meta(transcript_path):
    """The `agent-<id>.meta.json` written beside a subagent transcript."""
    base = transcript_path[:-len(".jsonl")] if transcript_path.endswith(".jsonl") else transcript_path
    meta = _read_json(base + ".meta.json")
    return meta if isinstance(meta, dict) else {}


# ---------------------------------------------------------------------------
# Transcript discovery
# ---------------------------------------------------------------------------

def claude_projects_dir():
    root = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(root, "projects")


def project_transcript_dir(cwd, projects_dir=None):
    """Claude Code names a project's dir after its path, non-alphanumerics -> '-'."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(cwd))
    return os.path.join(projects_dir or claude_projects_dir(), slug)


def agent_transcript_path(transcript_path, agent_id, session_id=None):
    """Locate a subagent's transcript from the parent session's transcript path."""
    if not transcript_path or not agent_id:
        return None
    base = os.path.dirname(transcript_path)
    session = session_id or os.path.splitext(os.path.basename(transcript_path))[0]
    return os.path.join(base, session, "subagents", "agent-%s.jsonl" % agent_id)


def _id_from_path(path):
    name = os.path.basename(path)
    if name.startswith("agent-") and name.endswith(".jsonl"):
        return name[len("agent-"):-len(".jsonl")]
    return None


def find_agent_transcripts(cwd, projects_dir=None):
    pattern = os.path.join(project_transcript_dir(cwd, projects_dir), "*", "subagents", "agent-*.jsonl")
    return sorted(glob.glob(pattern))


# ---------------------------------------------------------------------------
# Workflow attribution
# ---------------------------------------------------------------------------

def _workflows(cwd):
    """Current state first, then archived workflows (newest first)."""
    coregy = os.path.join(cwd, ".coregy")
    out = []
    state = _read_json(os.path.join(coregy, "state.json"))
    if isinstance(state, dict) and state.get("workflow_id"):
        out.append(state)
    history = _read_json(os.path.join(coregy, "state_history.json"))
    if isinstance(history, list):
        out.extend(h for h in reversed(history) if isinstance(h, dict) and h.get("workflow_id"))
    return out


def _fix_round_for(state, agent, log_index):
    """The fix round whose re-run this log entry is, or None for a first run."""
    found = None
    for rnd in state.get("fix_rounds") or []:
        if (rnd.get("log_index", 10 ** 9) <= log_index
                and agent in (rnd.get("reopened") or [])):
            found = rnd.get("round")
    return found


def attribute(cwd, agent, started_at=None):
    """Bind an agent run to the workflow agent_log entry it belongs to.

    Picks the last entry for this agent that started before the transcript
    did; with no timestamp, the agent's open (not yet completed) entry in the
    active workflow. Returns {} for an agent run outside any workflow.
    """
    started = _parse_ts(started_at)
    for state in _workflows(cwd):
        log = state.get("agent_log") or []
        match = None
        for idx, entry in enumerate(log):
            if entry.get("agent") != agent:
                continue
            if started is not None:
                entry_start = _parse_ts(entry.get("started_at"))
                if entry_start is None:
                    continue
                if (entry_start - started).total_seconds() > START_SLACK_SECONDS:
                    continue
                done = _parse_ts(entry.get("completed_at"))
                if done is not None and (started - done).total_seconds() > START_SLACK_SECONDS:
                    continue
                match = idx
            elif entry.get("completed_at") is None and state.get("status") == "in_progress":
                match = idx
        if match is not None:
            return {
                "workflow_id": state["workflow_id"],
                "feature": state.get("feature"),
                "phase": log[match].get("phase"),
                "log_index": match,
                "fix_round": _fix_round_for(state, agent, match),
            }
    return {}


def _auto_track_item(cwd):
    pointer = _read_json(os.path.join(cwd, ".coregy", "auto_track.json"))
    return pointer.get("item_id") if isinstance(pointer, dict) else None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def _meter_path(cwd):
    return os.path.join(cwd, ".coregy", METER_FILE)


def load_runs(cwd):
    data = _read_json(_meter_path(cwd))
    runs = data.get("runs") if isinstance(data, dict) else None
    return runs if isinstance(runs, dict) else {}


def _save_runs(cwd, runs):
    path = _meter_path(cwd)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "runs": runs}, f, indent=2)
    os.replace(tmp, path)
    _ignore_meter_file(cwd)


def _ignore_meter_file(cwd):
    """Per-machine data, like tracker.db; .coregy/ itself is committed."""
    path = os.path.join(cwd, ".coregy", ".gitignore")
    try:
        with open(path) as f:
            existing = f.read()
    except OSError:
        existing = ""
    if METER_FILE in existing.split():
        return
    with open(path, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(METER_FILE + "\n")


def _build_run(cwd, transcript_path, agent_id=None, agent_type=None, previous=None):
    usage = parse_transcript(transcript_path)
    if usage is None:
        return None
    meta = read_meta(transcript_path)
    agent_id = agent_id or usage.get("agent_id") or _id_from_path(transcript_path)
    usage.pop("agent_id", None)
    agent_type = agent_type or meta.get("agentType") or ""
    agent = normalize_agent(agent_type)
    run = dict(usage)
    run.update({
        "agent_id": agent_id,
        "agent": agent,
        "agent_type": agent_type,
        "description": meta.get("description") or "",
        "transcript": transcript_path,
        "recorded_at": _now(),
    })
    # A resumed agent's transcript grows: refresh the numbers, keep the
    # binding made when it first ran (state may have moved on since).
    if previous and previous.get("workflow_id"):
        for key in ("workflow_id", "feature", "phase", "log_index", "fix_round", "item_id"):
            run[key] = previous.get(key)
    else:
        binding = attribute(cwd, agent, usage.get("started_at"))
        run.update({key: binding.get(key) for key in
                    ("workflow_id", "feature", "phase", "log_index", "fix_round")})
        run["item_id"] = (previous or {}).get("item_id") or (
            None if binding else _auto_track_item(cwd))
    return run


def record(cwd, transcript_path, agent_id=None, agent_type=None):
    """Record (or refresh) one agent run. Returns the run dict, or None."""
    if not os.path.isdir(os.path.join(cwd, ".coregy")):
        return None
    runs = load_runs(cwd)
    agent_id = agent_id or _id_from_path(transcript_path)
    run = _build_run(cwd, transcript_path, agent_id, agent_type, previous=runs.get(agent_id))
    if run is None:
        return None
    runs[run["agent_id"]] = run
    _save_runs(cwd, runs)
    return run


def collect(cwd, projects_dir=None):
    """Record every subagent transcript of this project not yet up to date."""
    if not os.path.isdir(os.path.join(cwd, ".coregy")):
        raise FileNotFoundError(".coregy/ not found -- run /coregy-workflow:init first")
    runs = load_runs(cwd)
    added = updated = 0
    for path in find_agent_transcripts(cwd, projects_dir):
        agent_id = _id_from_path(path)
        previous = runs.get(agent_id)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
        except OSError:
            continue
        recorded = _parse_ts((previous or {}).get("recorded_at"))
        if recorded is not None and mtime <= recorded:
            continue
        run = _build_run(cwd, path, agent_id, previous=previous)
        if run is None:
            continue
        runs[agent_id] = run
        if previous:
            updated += 1
        else:
            added += 1
    if added or updated:
        _save_runs(cwd, runs)
    return {"added": added, "updated": updated, "runs": len(runs)}


def clear(cwd):
    try:
        os.remove(_meter_path(cwd))
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _current_workflow_id(cwd):
    state = _read_json(os.path.join(cwd, ".coregy", "state.json"))
    return state.get("workflow_id") if isinstance(state, dict) else None


def select_runs(cwd, workflow="current"):
    """Runs of one workflow ("current", an id) or "all". Returns (runs, workflow_id)."""
    runs = list(load_runs(cwd).values())
    if workflow == "all":
        return runs, None
    wid = _current_workflow_id(cwd) if workflow == "current" else workflow
    return [r for r in runs if wid and r.get("workflow_id") == wid], wid


def _group_key(run, by):
    if by == "agent":
        return run.get("agent") or "unknown"
    if by == "phase":
        return run.get("phase") or "(ad-hoc)"
    if by == "workflow":
        return run.get("workflow_id") or "(ad-hoc)"
    models = run.get("models") or []
    return models[0] if models else "unknown"


def load_prices(cwd):
    """`prices:` from .coregy/metering.yaml -- USD per million tokens by model prefix.

        prices:
          claude-opus:
            input: 5
            output: 25
          claude-sonnet:
            input: 3
            output: 15
            cache_read: 0.3     # optional, default 0.1 x input

    No defaults are shipped: prices change, a stale table would mislead.
    """
    try:
        with open(os.path.join(cwd, ".coregy", CONFIG_FILE), encoding="utf-8") as f:
            data = mini_yaml.loads(f.read())
    except OSError:
        return {}
    prices = data.get("prices") if isinstance(data, dict) else None
    out = {}
    for prefix, entry in (prices or {}).items() if isinstance(prices, dict) else []:
        if not isinstance(entry, dict):
            continue
        try:
            inp = float(entry.get("input", 0) or 0)
            out[str(prefix)] = {
                "input": inp,
                "output": float(entry.get("output", 0) or 0),
                "cache_write": float(entry.get("cache_write", inp * CACHE_WRITE_RATIO) or 0),
                "cache_read": float(entry.get("cache_read", inp * CACHE_READ_RATIO) or 0),
            }
        except (TypeError, ValueError):
            continue
    return out


def _price_for(prices, model):
    """Longest matching prefix wins, so `claude-opus-5-5` can override `claude-opus`."""
    best = None
    for prefix in prices:
        if model.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix
    return prices[best] if best else None


def run_cost(run, prices):
    """USD cost of a run, or None when a model it used has no price."""
    by_model = run.get("by_model") or {}
    if not prices or not by_model:
        return None
    cost = 0.0
    for model, usage in by_model.items():
        price = _price_for(prices, model)
        if price is None:
            return None
        cost += sum((usage.get(k) or 0) * price[k] for k in TOKEN_KEYS) / 1_000_000
    return cost


def summarize(runs, by="agent", prices=None):
    """Group runs and total their tokens. Rows are sorted by fresh tokens, largest first.

    `cost` is set only when every run in the group has a price.
    """
    if by not in GROUPINGS:
        raise ValueError("by must be one of %s" % (GROUPINGS,))
    groups = {}
    for run in runs:
        key = _group_key(run, by)
        g = groups.setdefault(key, dict({k: 0 for k in TOKEN_KEYS},
                                        key=key, runs=0, total=0, fresh=0, tool_uses=0,
                                        duration_s=0, fix_tokens=0, cost=0.0))
        g["runs"] += 1
        for k in TOKEN_KEYS:
            g[k] += run.get(k) or 0
        total = run.get("total") or 0
        fresh = run.get("fresh", total - (run.get("cache_read") or 0))
        g["total"] += total
        g["fresh"] += fresh
        g["tool_uses"] += run.get("tool_uses") or 0
        g["duration_s"] += run.get("duration_s") or 0
        if run.get("fix_round"):
            g["fix_tokens"] += fresh
        cost = run_cost(run, prices)
        g["cost"] = None if cost is None or g["cost"] is None else g["cost"] + cost
    rows = sorted(groups.values(), key=lambda g: (-g["fresh"], -g["total"]))
    totals = {k: sum(g[k] for g in rows) for k in
              TOKEN_KEYS + ("runs", "total", "fresh", "tool_uses", "duration_s", "fix_tokens")}
    costs = [g["cost"] for g in rows]
    totals["cost"] = sum(costs) if rows and None not in costs else None
    for g in rows:
        if g["cost"] is not None:
            g["cost"] = round(g["cost"], 4)
    if totals["cost"] is not None:
        totals["cost"] = round(totals["cost"], 4)
    return {"by": by, "rows": rows, "totals": totals}


def human(n):
    n = n or 0
    if n >= 1_000_000:
        return "%.1fM" % (n / 1_000_000)
    if n >= 10_000:
        return "%dk" % round(n / 1000)
    if n >= 1000:
        return "%.1fk" % (n / 1000)
    return str(n)


def _duration(seconds):
    seconds = seconds or 0
    if seconds >= 3600:
        return "%dh%02dm" % (seconds // 3600, seconds % 3600 // 60)
    if seconds >= 60:
        return "%dm%02ds" % (seconds // 60, seconds % 60)
    return "%ds" % seconds


def format_report(summary, title=""):
    rows, t = summary["rows"], summary["totals"]
    if not rows:
        return (title + "\n" if title else "") + "No agent runs recorded."
    width = max(10, max(len(r["key"]) for r in rows))
    priced = any(r["cost"] is not None for r in rows)
    head = "%-*s %4s %8s %8s %8s %8s %8s %8s %6s %8s" % (
        width, summary["by"], "runs", "fresh", "input", "cache-w", "output",
        "cache-r", "total", "tools", "time")
    if priced:
        head += " %9s" % "cost"
    lines = [title] if title else []
    lines += [head, "-" * len(head)]

    def line(key, g):
        text = "%-*s %4d %8s %8s %8s %8s %8s %8s %6d %8s" % (
            width, key, g["runs"], human(g["fresh"]), human(g["input"]),
            human(g["cache_write"]), human(g["output"]), human(g["cache_read"]),
            human(g["total"]), g["tool_uses"], _duration(g["duration_s"]))
        if priced:
            text += " %9s" % ("$%.2f" % g["cost"] if g["cost"] is not None else "?")
        return text

    lines += [line(r["key"], r) for r in rows]
    lines += ["-" * len(head), line("total", t)]
    lines.append("fresh = input + cache writes + output (cache reads are billed at ~0.1x)")
    if t["fix_tokens"]:
        lines.append("Fix rounds: %s fresh tokens (%d%% of fresh)" % (
            human(t["fix_tokens"]), round(100 * t["fix_tokens"] / t["fresh"]) if t["fresh"] else 0))
    return "\n".join(lines)


def brief(cwd, workflow="current"):
    """One line for status / final summaries: `Tokens: 1.2M (backend 640k, ...)`."""
    runs, _ = select_runs(cwd, workflow)
    s = summarize(runs, "agent", load_prices(cwd))
    t = s["totals"]
    if not s["rows"]:
        return "Tokens: no agent runs recorded"
    top = ", ".join("%s %s" % (r["key"], human(r["fresh"])) for r in s["rows"][:4])
    extra = ""
    if t["fix_tokens"]:
        extra += "; fix rounds %s" % human(t["fix_tokens"])
    cost = " ~$%.2f," % t["cost"] if t["cost"] is not None else ""
    return "Tokens: %s fresh +%s cache reads,%s %d agent run(s) (%s%s)" % (
        human(t["fresh"]), human(t["cache_read"]), cost, t["runs"], top, extra)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _output(data):
    print(json.dumps(data, indent=2, default=str))


def _fail(msg, json_mode=False):
    if json_mode:
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print("Error: %s" % msg, file=sys.stderr)
    sys.exit(1)


def main():
    parent = argparse.ArgumentParser(add_help=False)
    # default=SUPPRESS is load-bearing: see state.py -- a concrete default on
    # the subparser would clobber a --cwd given before the subcommand.
    parent.add_argument("--cwd", default=argparse.SUPPRESS,
                        help="Project root directory (default: .)")

    parser = argparse.ArgumentParser(
        description="Coregy Workflow per-agent token metering", parents=[parent])
    sub = parser.add_subparsers(dest="command")

    p_collect = sub.add_parser("collect", parents=[parent],
                               help="Record subagent transcripts the hook missed")
    p_collect.add_argument("--projects-dir", default=None,
                           help="Claude Code projects dir (default: ~/.claude/projects)")
    p_collect.add_argument("--json", action="store_true", dest="json_mode")

    p_report = sub.add_parser("report", parents=[parent], help="Show token usage")
    p_report.add_argument("--workflow", default="current",
                          help="current (default), all, or a workflow id")
    p_report.add_argument("--by", default="agent", choices=GROUPINGS)
    p_report.add_argument("--brief", action="store_true", help="One summary line")
    p_report.add_argument("--json", action="store_true", dest="json_mode")

    p_record = sub.add_parser("record", parents=[parent], help="Record one agent transcript")
    p_record.add_argument("--transcript", required=True)
    p_record.add_argument("--agent-id", default=None)
    p_record.add_argument("--agent-type", default=None)
    p_record.add_argument("--json", action="store_true", dest="json_mode")

    p_clear = sub.add_parser("clear", parents=[parent], help="Delete .coregy/metering.json")
    p_clear.add_argument("--force", action="store_true")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    cwd = os.path.abspath(getattr(args, "cwd", "."))
    json_mode = getattr(args, "json_mode", False)

    try:
        if args.command == "collect":
            result = collect(cwd, args.projects_dir)
            if json_mode:
                _output(dict(result, ok=True))
            else:
                print("Collected: %d new, %d updated (%d runs recorded)" % (
                    result["added"], result["updated"], result["runs"]))

        elif args.command == "report":
            runs, wid = select_runs(cwd, args.workflow)
            if args.brief:
                print(brief(cwd, args.workflow))
                return
            summary = summarize(runs, args.by, load_prices(cwd))
            if json_mode:
                _output(dict(summary, ok=True, workflow_id=wid))
            else:
                if args.workflow == "all":
                    title = "Token usage -- all recorded runs"
                elif wid:
                    title = "Token usage -- workflow %s" % wid
                else:
                    title = "Token usage -- no workflow (use --workflow all)"
                print(format_report(summary, title))

        elif args.command == "record":
            run = record(cwd, os.path.abspath(args.transcript), args.agent_id, args.agent_type)
            if run is None:
                _fail("Could not record %s (missing transcript or .coregy/)" % args.transcript,
                      json_mode)
            if json_mode:
                _output(dict(run, ok=True))
            else:
                print("Recorded %s (%s): %s tokens" % (run["agent"], run["agent_id"],
                                                       human(run["total"])))

        elif args.command == "clear":
            if not args.force:
                _fail("clear deletes all recorded runs; pass --force")
            print("Cleared." if clear(cwd) else "Nothing to clear.")

    except (FileNotFoundError, ValueError) as e:
        _fail(str(e), json_mode)


if __name__ == "__main__":
    main()
