"""
Workflow state machine for Hody Workflow.

Manages `.hody/state.json` — tracks active workflows with phases,
agents, timestamps, and an audit log.
"""
import argparse
import contextlib
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

VALID_MODES = ("auto", "guided", "manual")

CANONICAL_PHASE_ORDER = ["THINK", "BUILD", "VERIFY", "SHIP"]


def _now():
    """Return current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_path(cwd):
    return os.path.join(cwd, ".hody", "state.json")


def _write_state(cwd, state):
    state["updated_at"] = _now()
    path = _state_path(cwd)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
    return state


def _make_workflow_id(feature):
    """Generate workflow ID from feature description + date."""
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"feat-{_make_slug(feature)}-{date}"


def _make_slug(text):
    """Convert text to a URL-friendly slug."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def init_workflow(cwd, feature, feature_type, phases, spec_confirmed=False,
                  spec_file=None, log_file=None, execution_mode="guided"):
    """Create .hody/state.json with initial workflow state.

    Args:
        cwd: Project root directory.
        feature: Feature description string.
        feature_type: One of the feature types (new-feature, bug-fix, etc.).
        phases: Dict mapping phase names to agent lists, e.g.
                {"THINK": ["researcher", "architect"], "BUILD": ["backend"]}.
        spec_confirmed: Whether spec has been confirmed by the user.
        spec_file: KB filename for the confirmed spec (e.g. "spec-oauth2-login.md").
        log_file: KB filename for the feature log (auto-generated if None).
        execution_mode: One of "auto", "guided", "manual".

    Returns:
        The created state dict.
    """
    if execution_mode not in VALID_MODES:
        raise ValueError(
            f"Invalid execution_mode: {execution_mode}. Must be one of {VALID_MODES}"
        )
    unknown = [p for p in phases if p not in CANONICAL_PHASE_ORDER]
    if unknown:
        raise ValueError(
            f"Unknown phase(s) {unknown}; use {CANONICAL_PHASE_ORDER}"
        )
    phase_order = [p for p in CANONICAL_PHASE_ORDER if p in phases]
    slug = _make_slug(feature)

    _archive_previous_state(cwd)

    if log_file is None:
        log_file = f"log-{slug}.md"

    state = {
        "workflow_id": _make_workflow_id(feature),
        "feature": feature,
        "type": feature_type,
        "status": "in_progress",
        "execution_mode": execution_mode,
        "spec_confirmed": spec_confirmed,
        "spec_file": spec_file,
        "log_file": log_file,
        "created_at": _now(),
        "updated_at": _now(),
        "phases": {},
        "phase_order": phase_order,
        "agent_log": [],
    }

    for phase in phase_order:
        state["phases"][phase] = {
            "agents": list(phases[phase]),
            "completed": [],
            "active": None,
            "skipped": [],
        }

    return _write_state(cwd, state)


def _archive_previous_state(cwd):
    """Append the workflow about to be replaced to .hody/state_history.json.

    Without this, starting a new workflow erased the previous one, and the
    health dashboard's completion stats (which read state_history.json)
    only ever saw a single workflow.
    """
    previous = load_state(cwd) if os.path.isfile(_state_path(cwd)) else None
    if not previous:
        return
    history_path = os.path.join(cwd, ".hody", "state_history.json")
    history = []
    if os.path.isfile(history_path):
        try:
            with open(history_path, "r") as f:
                history = json.load(f)
        except (json.JSONDecodeError, OSError):
            history = []
    if not isinstance(history, list):
        history = []
    if any(h.get("workflow_id") == previous.get("workflow_id")
           and h.get("updated_at") == previous.get("updated_at")
           for h in history if isinstance(h, dict)):
        return
    history.append(previous)
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)


def load_state(cwd):
    """Read .hody/state.json, return None if doesn't exist."""
    path = _state_path(cwd)
    if not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def get_execution_mode(state):
    """Return execution mode, defaulting to 'guided' for legacy state files."""
    if state is None:
        return "guided"
    return state.get("execution_mode", "guided")


def set_execution_mode(cwd, mode):
    """Override execution mode for current workflow."""
    if mode not in VALID_MODES:
        raise ValueError(
            f"Invalid mode: {mode}. Must be one of {VALID_MODES}"
        )
    state = load_state(cwd)
    if state is None:
        raise FileNotFoundError("No active workflow — .hody/state.json not found")
    state["execution_mode"] = mode
    return _write_state(cwd, state)


def confirm_spec(cwd, spec_file):
    """Mark the spec as confirmed, enabling auto-execution.

    Args:
        cwd: Project root directory.
        spec_file: KB filename for the confirmed spec.

    Returns:
        The updated state dict.
    """
    state = load_state(cwd)
    if state is None:
        raise FileNotFoundError("No active workflow — .hody/state.json not found")

    state["spec_confirmed"] = True
    state["spec_file"] = spec_file
    return _write_state(cwd, state)


def _find_agent_phase(state, agent_name):
    """Find which phase an agent occurrence refers to.

    An agent may appear in more than one phase (the refactor sequence runs
    code-reviewer to assess in THINK and again to verify in VERIFY), so the
    lookup prefers, in order: the phase where it is active, the first phase
    where it is still pending, then the first phase that lists it at all.
    """
    listed = [p for p in state["phase_order"]
              if agent_name in state["phases"][p]["agents"]]
    if not listed:
        return None
    for phase in listed:
        if state["phases"][phase].get("active") == agent_name:
            return phase
    for phase in listed:
        p = state["phases"][phase]
        if agent_name not in p["completed"] and agent_name not in p["skipped"]:
            return phase
    return listed[0]


def _already_completed(state, agent_name):
    """True when the agent is active nowhere and its last run is closed.

    Makes complete_agent() idempotent for agents listed in several phases:
    the orchestrator's second complete-agent call must not tick off the
    agent's *next* occurrence.
    """
    for phase in state["phase_order"]:
        if state["phases"][phase].get("active") == agent_name:
            return False
    entries = [e for e in state.get("agent_log", []) if e.get("agent") == agent_name]
    return bool(entries) and entries[-1].get("completed_at") is not None


def _current_phase(state):
    """Return the current (first non-complete) phase name, or None."""
    for phase in state["phase_order"]:
        p = state["phases"][phase]
        remaining = set(p["agents"]) - set(p["completed"]) - set(p["skipped"])
        if remaining:
            return phase
    return None


def _phase_has_progress(state, phase):
    """Check if a phase has at least one completed or skipped agent."""
    p = state["phases"][phase]
    return len(p["completed"]) > 0 or len(p["skipped"]) == len(p["agents"])


def _load_checkpoint(cwd, workflow_id, agent_name):
    """Try to load a checkpoint for this agent. Returns dict or None."""
    try:
        from . import tracker as tracker_module
    except ImportError:
        try:
            import tracker as tracker_module
        except ImportError:
            return None
    try:
        return tracker_module.load_checkpoint(cwd, workflow_id, agent_name)
    except Exception:
        return None


def _clear_checkpoint(cwd, workflow_id, agent_name):
    """Try to clear the checkpoint for a completed agent."""
    try:
        from . import tracker as tracker_module
    except ImportError:
        try:
            import tracker as tracker_module
        except ImportError:
            return
    try:
        tracker_module.clear_checkpoint(cwd, workflow_id, agent_name)
    except Exception:
        pass


def start_agent(cwd, agent_name):
    """Set agent as active, log start time.

    Returns (updated_state, checkpoint_or_none). If a checkpoint exists
    for this agent, it is returned so the caller can resume from where
    the agent left off.
    """
    state = load_state(cwd)
    if state is None:
        raise FileNotFoundError("No active workflow — .hody/state.json not found")

    phase = _find_agent_phase(state, agent_name)
    if phase is None:
        raise ValueError(f"Agent '{agent_name}' not found in any workflow phase")

    # Advisory check: warn if earlier phases haven't started
    phase_idx = state["phase_order"].index(phase)
    warnings = []
    for earlier_phase in state["phase_order"][:phase_idx]:
        if not _phase_has_progress(state, earlier_phase):
            warnings.append(
                f"Warning: Starting '{agent_name}' in {phase} "
                f"before {earlier_phase} phase has any progress"
            )

    if warnings:
        for w in warnings:
            print(w)

    # Set active
    state["phases"][phase]["active"] = agent_name

    # Add log entry
    state["agent_log"].append({
        "agent": agent_name,
        "phase": phase,
        "started_at": _now(),
        "completed_at": None,
        "output_summary": "",
        "kb_files_modified": [],
    })

    updated_state = _write_state(cwd, state)
    _sync_tracker(cwd, updated_state)  # linked tracker item: created -> in_progress

    # Check for existing checkpoint (agent was interrupted before)
    checkpoint = _load_checkpoint(cwd, state["workflow_id"], agent_name)

    return updated_state, checkpoint


def complete_agent(cwd, agent_name, output_summary="", kb_files_modified=None):
    """Mark agent as completed, log end time + summary.

    Clears the agent's checkpoint since work is done.
    """
    state = load_state(cwd)
    if state is None:
        raise FileNotFoundError("No active workflow — .hody/state.json not found")

    phase = _find_agent_phase(state, agent_name)
    if phase is None:
        raise ValueError(f"Agent '{agent_name}' not found in any workflow phase")

    if _already_completed(state, agent_name):
        return state  # repeated call for a run that is already recorded

    p = state["phases"][phase]

    # Mark completed
    if agent_name not in p["completed"]:
        p["completed"].append(agent_name)

    # Clear active if this agent was active
    if p["active"] == agent_name:
        p["active"] = None

    # Update log entry
    for entry in reversed(state["agent_log"]):
        if entry["agent"] == agent_name and entry["completed_at"] is None:
            entry["completed_at"] = _now()
            entry["output_summary"] = output_summary
            entry["kb_files_modified"] = kb_files_modified or []
            break

    # Clear checkpoint — agent is done, no need to keep it
    _clear_checkpoint(cwd, state["workflow_id"], agent_name)

    return _write_state(cwd, state)


def skip_agent(cwd, agent_name):
    """Mark agent as skipped."""
    state = load_state(cwd)
    if state is None:
        raise FileNotFoundError("No active workflow — .hody/state.json not found")

    phase = _find_agent_phase(state, agent_name)
    if phase is None:
        raise ValueError(f"Agent '{agent_name}' not found in any workflow phase")

    p = state["phases"][phase]
    if agent_name not in p["skipped"]:
        p["skipped"].append(agent_name)

    # Clear active if this agent was active
    if p["active"] == agent_name:
        p["active"] = None

    return _write_state(cwd, state)


def _clear_all_checkpoints(cwd, workflow_id):
    """Clear all checkpoints for a workflow."""
    try:
        from . import tracker as tracker_module
    except ImportError:
        try:
            import tracker as tracker_module
        except ImportError:
            return
    try:
        tracker_module.clear_workflow_checkpoints(cwd, workflow_id)
    except Exception:
        pass


def _sync_tracker(cwd, state):
    """Best-effort: mirror the workflow status onto its tracker item."""
    try:
        from . import tracker as tracker_module
    except ImportError:
        try:
            import tracker as tracker_module
        except ImportError:
            return
    try:
        tracker_module.sync_workflow_status(cwd, state)
    except Exception:
        pass


def complete_workflow(cwd):
    """Set status = 'completed', record end time.

    Clears all checkpoints and finalizes the feature log.
    """
    state = load_state(cwd)
    if state is None:
        raise FileNotFoundError("No active workflow — .hody/state.json not found")

    # Finalize log before changing status
    finalize_feature_log(cwd, state.get("log_file"))

    state["status"] = "completed"
    _clear_all_checkpoints(cwd, state["workflow_id"])
    state = _write_state(cwd, state)
    _sync_tracker(cwd, state)
    return state


def abort_workflow(cwd):
    """Set status = 'aborted'. Clears all checkpoints."""
    state = load_state(cwd)
    if state is None:
        raise FileNotFoundError("No active workflow — .hody/state.json not found")

    state["status"] = "aborted"
    _clear_all_checkpoints(cwd, state["workflow_id"])
    state = _write_state(cwd, state)
    _sync_tracker(cwd, state)
    return state


def _log_path(cwd, log_file):
    """Return absolute path to the feature log file in KB."""
    return os.path.join(cwd, ".hody", "knowledge", log_file)


def create_feature_log(cwd, feature, feature_type, spec_file=None, log_file=None):
    """Create the initial feature log file in the knowledge base.

    Args:
        cwd: Project root directory.
        feature: Feature description.
        feature_type: Classified feature type.
        spec_file: Spec filename if available.
        log_file: Log filename (reads from state.json if None).

    Returns:
        The log file path.
    """
    if log_file is None:
        state = load_state(cwd)
        if state is None:
            raise FileNotFoundError("No active workflow")
        log_file = state.get("log_file", f"log-{_make_slug(feature)}.md")

    path = _log_path(cwd, log_file)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    spec_ref = f"\n\n## Spec\n-> {spec_file}" if spec_file else ""

    content = (
        f"---\n"
        f"tags: [log, {feature_type}]\n"
        f"created: {today}\n"
        f"author_agent: start-feature\n"
        f"status: in_progress\n"
        f"---\n\n"
        f"# Feature Log: {feature}\n"
        f"\n"
        f"Type: {feature_type}\n"
        f"Started: {today}"
        f"{spec_ref}\n\n"
        f"## Agent Work\n"
    )

    with open(path, "w") as f:
        f.write(content)

    return path


def append_feature_log(cwd, agent_name, phase, summary,
                       files_created=None, files_modified=None,
                       kb_updated=None, decisions=None, log_file=None):
    """Append a structured agent entry to the feature log.

    Args:
        cwd: Project root directory.
        agent_name: Name of the agent (e.g. "backend").
        phase: Workflow phase (e.g. "BUILD").
        summary: Brief description of what the agent did.
        files_created: List of files the agent created.
        files_modified: List of files the agent modified.
        kb_updated: List of KB files updated.
        decisions: List of key decisions made.
        log_file: Log filename (reads from state.json if None).
    """
    if log_file is None:
        state = load_state(cwd)
        if state is None:
            return  # No workflow, skip silently
        log_file = state.get("log_file")
        if not log_file:
            return

    path = _log_path(cwd, log_file)
    if not os.path.isfile(path):
        return  # Log not created yet, skip silently

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"\n### {agent_name} ({phase}) — {today}\n"]
    lines.append(f"- {summary}\n")

    if files_created:
        lines.append("- Files created: " + ", ".join(f"`{f}`" for f in files_created) + "\n")
    if files_modified:
        lines.append("- Files modified: " + ", ".join(f"`{f}`" for f in files_modified) + "\n")
    if kb_updated:
        lines.append("- KB updated: " + ", ".join(kb_updated) + "\n")
    if decisions:
        for d in decisions:
            lines.append(f"- Decision: {d}\n")

    with open(path, "a") as f:
        f.writelines(lines)


def finalize_feature_log(cwd, log_file=None):
    """Append a final summary section to the feature log.

    Reads agent_log from state.json to build the summary.
    """
    state = load_state(cwd)
    if state is None:
        return

    if log_file is None:
        log_file = state.get("log_file")
    if not log_file:
        return

    path = _log_path(cwd, log_file)
    if not os.path.isfile(path):
        return

    with open(path, "r") as f:
        if "\n## Summary\n" in f.read():
            return  # already finalized -- don't append a second summary

    # Build summary from agent_log
    lines = ["\n## Summary\n"]
    completed_count = 0
    for entry in state.get("agent_log", []):
        if entry.get("completed_at"):
            completed_count += 1
            agent = entry["agent"]
            phase = entry["phase"]
            summary = entry.get("output_summary", "")
            kb = entry.get("kb_files_modified", [])
            kb_str = f" (KB: {', '.join(kb)})" if kb else ""
            lines.append(f"- **{agent}** ({phase}): {summary}{kb_str}\n")

    lines.insert(1, f"\n{completed_count} agents completed.\n\n")

    # Update frontmatter status
    with open(path, "r") as f:
        content = f.read()

    content = content.replace("status: in_progress", "status: completed", 1)

    with open(path, "w") as f:
        f.write(content)

    with open(path, "a") as f:
        f.writelines(lines)


def get_next_agent(state):
    """Returns (phase, agent) for next unfinished agent, or None if done."""
    if state is None or state.get("status") != "in_progress":
        return None

    for phase in state["phase_order"]:
        p = state["phases"][phase]
        for agent in p["agents"]:
            if agent not in p["completed"] and agent not in p["skipped"]:
                return (phase, agent)

    return None


# ---------------------------------------------------------------------------
# CLI (hody-cli-v1)
#
# Pure wrapper layer: no function above this line changes behaviour. The
# backward-compatibility normalization below lives at the CLI layer only, so
# load_state() and every library caller keep byte-identical semantics.
# ---------------------------------------------------------------------------

NO_WORKFLOW_MSG = "No active workflow -- .hody/state.json not found"


def _output(data):
    print(json.dumps(data, indent=2, default=str))


def _fail(msg, json_mode=False):
    if json_mode:
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print("Error: %s" % msg, file=sys.stderr)
    sys.exit(1)


def _csv(value):
    """Split a comma-separated flag value into a clean list."""
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _normalize_state(state):
    """Heal a legacy/partial state dict in place.

    Returns (state, changed). Legacy files written against the v0.6 template
    are missing execution_mode / spec_file / log_file / spec_confirmed, and in
    the general case can also be missing workflow_id, phase_order or per-phase
    keys — all of which existing functions index with [] and would KeyError on.
    """
    if state is None:
        return None, False

    before = json.dumps(state, sort_keys=True, default=str)

    defaults = [
        ("status", "in_progress"),
        ("execution_mode", "guided"),
        ("spec_confirmed", False),
        ("spec_file", None),
        ("feature", ""),
        ("type", "unknown"),
        ("created_at", _now()),
        ("updated_at", _now()),
        ("agent_log", []),
        ("phases", {}),
        ("phase_order", []),
    ]
    for key, default in defaults:
        state.setdefault(key, default)

    if state.get("execution_mode") not in VALID_MODES:
        state["execution_mode"] = "guided"

    if not state.get("workflow_id"):
        feature = state.get("feature") or ""
        state["workflow_id"] = (
            _make_workflow_id(feature) if feature else "unknown-workflow"
        )

    if not state.get("log_file"):
        state["log_file"] = "log-%s.md" % _make_slug(state.get("feature") or "")

    if not isinstance(state.get("phases"), dict):
        state["phases"] = {}

    if not state.get("phase_order"):
        keys = list(state["phases"].keys())
        ordered = [p for p in CANONICAL_PHASE_ORDER if p in keys]
        ordered += [p for p in keys if p not in ordered]
        state["phase_order"] = ordered
    else:
        state["phase_order"] = [
            p for p in state["phase_order"] if p in state["phases"]
        ]

    for phase in state["phase_order"]:
        block = state["phases"][phase]
        if not isinstance(block, dict):
            block = {}
            state["phases"][phase] = block
        block.setdefault("agents", [])
        block.setdefault("completed", [])
        block.setdefault("skipped", [])
        block.setdefault("active", None)
        for list_key in ("agents", "completed", "skipped"):
            if not isinstance(block[list_key], list):
                block[list_key] = []

    if not isinstance(state.get("agent_log"), list):
        state["agent_log"] = []
    for entry in state["agent_log"]:
        if not isinstance(entry, dict):
            continue
        entry.setdefault("agent", "")
        entry.setdefault("phase", "")
        entry.setdefault("started_at", None)
        entry.setdefault("completed_at", None)
        entry.setdefault("output_summary", "")
        entry.setdefault("kb_files_modified", [])

    after = json.dumps(state, sort_keys=True, default=str)
    return state, before != after


def _cli_load_and_repair(cwd):
    """Load state for a mutating subcommand, healing legacy schema on disk.

    The wrapped function then re-reads the healed file through its own
    load_state(), so it never sees a shape it cannot handle.
    """
    state = load_state(cwd)
    if state is None:
        _fail(NO_WORKFLOW_MSG)
    state, changed = _normalize_state(state)
    if changed:
        _write_state(cwd, state)
    return state


def _cli_load_readonly(cwd):
    """Load and normalize in memory only -- never writes."""
    state = load_state(cwd)
    if state is None:
        return None
    state, _ = _normalize_state(state)
    return state


def _ensure_open_log_entry(cwd, state, agent):
    """Give `complete-agent` an agent_log entry to fill in when there is none.

    complete_agent() only updates an existing entry whose completed_at is None,
    so completing an agent that was never started through start-agent leaves no
    audit trail at all -- silently. That happens whenever an agent is invoked
    on its own rather than driven by /start-feature or /resume, and the agent
    prompts now tell every agent to call complete-agent itself.

    Wrapper-layer fix, mirroring _normalize_state(): complete_agent() itself is
    untouched. Skipped when the agent is already completed, so a second call
    (the orchestrator's) stays a no-op rather than appending a duplicate.
    """
    phase = _find_agent_phase(state, agent)
    if phase is None:
        return False
    if agent in state["phases"][phase].get("completed", []):
        return False
    if _already_completed(state, agent):
        # Its last run is recorded and it is not active: this is a repeated
        # complete-agent call, not a new run of the agent's next occurrence.
        return False
    for entry in state.get("agent_log", []):
        if entry.get("agent") == agent and entry.get("completed_at") is None:
            return False

    state.setdefault("agent_log", []).append({
        "agent": agent,
        "phase": phase,
        "started_at": _now(),
        "completed_at": None,
        "output_summary": "",
        "kb_files_modified": [],
    })
    _write_state(cwd, state)
    return True


def _format_state_text(state):
    """Human-readable progress view for `show`. ASCII only."""
    lines = []
    lines.append("Workflow: %s" % state.get("workflow_id", ""))
    lines.append("Feature:  %s" % state.get("feature", ""))
    lines.append(
        "Type:     %s   Status: %s   Mode: %s"
        % (
            state.get("type", "unknown"),
            state.get("status", "unknown"),
            state.get("execution_mode", "guided"),
        )
    )
    spec_file = state.get("spec_file")
    if spec_file:
        confirmed = "confirmed" if state.get("spec_confirmed") else "not confirmed"
        lines.append("Spec:     %s (%s)" % (spec_file, confirmed))
    else:
        lines.append("Spec:     (none)")
    lines.append("Log:      %s" % (state.get("log_file") or "(none)"))

    total = 0
    done = 0
    phase_lines = []
    width = max([len(p) for p in state["phase_order"]] or [6])
    for phase in state["phase_order"]:
        block = state["phases"][phase]
        marks = []
        for agent in block["agents"]:
            total += 1
            if agent in block["completed"]:
                done += 1
                marker = "[x]"
            elif agent in block["skipped"]:
                done += 1
                marker = "[-]"
            elif block.get("active") == agent:
                marker = "[>]"
            else:
                marker = "[ ]"
            marks.append("%s %s" % (marker, agent))
        phase_lines.append("  %-*s %s" % (width, phase, "  ".join(marks)))

    pct = int(round(done * 100.0 / total)) if total else 0
    lines.append("Progress: %d/%d agents (%d%%)" % (done, total, pct))
    lines.append("")
    lines.extend(phase_lines)
    return "\n".join(lines)


def _build_parser():
    parent = argparse.ArgumentParser(add_help=False)
    # default=SUPPRESS is load-bearing: --cwd lives on both the top-level
    # parser and every subparser (parents=[parent]). With a concrete
    # default the subparser re-applies it into its own namespace and
    # silently clobbers a --cwd given *before* the subcommand, so the
    # script would quietly operate on the process cwd instead.
    parent.add_argument("--cwd", default=argparse.SUPPRESS,
                        help="Project root directory (default: .)")

    parser = argparse.ArgumentParser(
        description="Hody Workflow state machine (.hody/state.json)",
        parents=[parent],
    )
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser(
        "init-workflow", parents=[parent], help="Create a new workflow state file"
    )
    p_init.add_argument("--feature", required=True, help="Feature description")
    p_init.add_argument("--type", required=True, dest="feature_type",
                        help="Feature type (new-feature, bug-fix, refactor, ...)")
    p_init.add_argument("--phases", required=True,
                        help='JSON object, e.g. \'{"THINK":["architect"]}\'')
    p_init.add_argument("--spec-file", default=None, help="Spec KB filename")
    p_init.add_argument("--log-file", default=None, help="Feature log KB filename")
    p_init.add_argument("--mode", default="guided", choices=list(VALID_MODES),
                        help="Execution mode (default: guided)")
    p_init.add_argument("--spec-confirmed", action="store_true",
                        help="Mark the spec as already confirmed")
    p_init.add_argument("--no-log", action="store_true",
                        help="Do not create the feature log file")
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite an in-progress workflow")

    p_start = sub.add_parser("start-agent", parents=[parent],
                             help="Mark an agent active and load its checkpoint")
    p_start.add_argument("agent", help="Agent name")

    p_done = sub.add_parser("complete-agent", parents=[parent],
                            help="Mark an agent completed")
    p_done.add_argument("agent", help="Agent name")
    p_done.add_argument("--summary", default="", help="One-line output summary")
    p_done.add_argument("--kb-files", default="", help="Comma-separated KB files")

    p_skip = sub.add_parser("skip-agent", parents=[parent], help="Mark an agent skipped")
    p_skip.add_argument("agent", help="Agent name")

    p_confirm = sub.add_parser("confirm-spec", parents=[parent],
                               help="Mark the spec confirmed")
    p_confirm.add_argument("--spec-file", required=True, help="Spec KB filename")

    p_mode = sub.add_parser("set-mode", parents=[parent], help="Override execution mode")
    p_mode.add_argument("mode", choices=list(VALID_MODES))

    p_next = sub.add_parser("next-agent", parents=[parent],
                            help="Print the next unfinished agent")
    p_next.add_argument("--json", action="store_true", dest="json_mode")

    sub.add_parser("complete", parents=[parent],
                   help="Finalize the feature log and complete the workflow")
    sub.add_parser("abort", parents=[parent], help="Abort the workflow")

    p_log = sub.add_parser("log-append", parents=[parent],
                           help="Append an agent work record to the feature log")
    p_log.add_argument("--agent", required=True)
    p_log.add_argument("--phase", required=True)
    p_log.add_argument("--summary", required=True)
    p_log.add_argument("--files-created", default="")
    p_log.add_argument("--files-modified", default="")
    p_log.add_argument("--kb-updated", default="")
    p_log.add_argument("--decision", action="append", default=None,
                       help="Key decision (repeatable)")
    p_log.add_argument("--log-file", default=None)

    p_show = sub.add_parser("show", parents=[parent], help="Show workflow progress")
    p_show.add_argument("--json", action="store_true", dest="json_mode")

    return parser


def _dispatch(args, cwd, json_mode):
    cmd = args.command

    if cmd == "init-workflow":
        existing = load_state(cwd)
        if (existing and existing.get("status") == "in_progress"
                and not args.force):
            _fail(
                "Active workflow %s in progress -- use --force to overwrite "
                "or /hody-workflow:resume" % existing.get("workflow_id", "?"),
                json_mode,
            )
        try:
            phases = json.loads(args.phases)
        except ValueError as exc:
            _fail("--phases is not valid JSON (%s): %s" % (exc, args.phases), json_mode)
        if not isinstance(phases, dict):
            _fail("--phases must be a JSON object of phase -> [agents]", json_mode)
        for key, value in phases.items():
            if not isinstance(value, list):
                _fail("--phases['%s'] must be a list of agent names" % key, json_mode)

        state = init_workflow(
            cwd,
            feature=args.feature,
            feature_type=args.feature_type,
            phases=phases,
            spec_confirmed=args.spec_confirmed,
            spec_file=args.spec_file,
            log_file=args.log_file,
            execution_mode=args.mode,
        )
        if not args.no_log:
            create_feature_log(cwd, args.feature, args.feature_type,
                               spec_file=args.spec_file,
                               log_file=state["log_file"])
        _output(state)

    elif cmd == "start-agent":
        _cli_load_and_repair(cwd)
        # start_agent() prints its phase-ordering warnings to stdout with bare
        # print(); capturing them keeps this command's JSON stream clean.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            updated_state, checkpoint = start_agent(cwd, args.agent)
        warnings = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        phase = _find_agent_phase(updated_state, args.agent)
        _output({
            "ok": True,
            "agent": args.agent,
            "phase": phase,
            "warnings": warnings,
            "checkpoint": checkpoint,
            "state": updated_state,
        })

    elif cmd == "complete-agent":
        state = _cli_load_and_repair(cwd)
        _ensure_open_log_entry(cwd, state, args.agent)
        _output(complete_agent(cwd, args.agent, output_summary=args.summary,
                               kb_files_modified=_csv(args.kb_files)))

    elif cmd == "skip-agent":
        _cli_load_and_repair(cwd)
        _output(skip_agent(cwd, args.agent))

    elif cmd == "confirm-spec":
        _cli_load_and_repair(cwd)
        _output(confirm_spec(cwd, args.spec_file))

    elif cmd == "set-mode":
        _cli_load_and_repair(cwd)
        _output(set_execution_mode(cwd, args.mode))

    elif cmd == "next-agent":
        # Always exits 0 -- callers branch on the content, not the status.
        result = get_next_agent(_cli_load_readonly(cwd))
        if args.json_mode:
            if result is None:
                _output({"phase": None, "agent": None})
            else:
                _output({"phase": result[0], "agent": result[1]})
        else:
            print("none" if result is None else "%s %s" % result)

    elif cmd == "complete":
        _cli_load_and_repair(cwd)
        _output(complete_workflow(cwd))

    elif cmd == "abort":
        _cli_load_and_repair(cwd)
        _output(abort_workflow(cwd))

    elif cmd == "log-append":
        state = _cli_load_and_repair(cwd)
        log_file = args.log_file or state.get("log_file")
        appended = bool(log_file) and os.path.isfile(_log_path(cwd, log_file))
        append_feature_log(
            cwd, args.agent, args.phase, args.summary,
            files_created=_csv(args.files_created),
            files_modified=_csv(args.files_modified),
            kb_updated=_csv(args.kb_updated),
            decisions=args.decision or [],
            log_file=args.log_file,
        )
        _output({"ok": True, "log_file": log_file, "appended": appended})

    elif cmd == "show":
        state = _cli_load_readonly(cwd)
        if state is None:
            _fail(NO_WORKFLOW_MSG, json_mode)
        if args.json_mode:
            _output(state)
        else:
            print(_format_state_text(state))


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # getattr, not args.cwd: the shared --cwd action defaults to
    # SUPPRESS so a value given before the subcommand survives.
    cwd = os.path.abspath(getattr(args, "cwd", "."))
    json_mode = getattr(args, "json_mode", False)

    try:
        _dispatch(args, cwd, json_mode)
    except (FileNotFoundError, ValueError, OSError) as exc:
        _fail(str(exc), json_mode)


if __name__ == "__main__":
    main()
