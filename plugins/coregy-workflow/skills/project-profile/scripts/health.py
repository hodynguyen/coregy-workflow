"""
Project health dashboard for Coregy Workflow.

Aggregates metrics from knowledge base, workflow state, profile,
and git history into a unified health report.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

try:
    from . import mini_yaml
except ImportError:
    import mini_yaml


# All 9 agents in the workflow system
ALL_AGENTS = [
    "researcher",
    "architect",
    "frontend",
    "backend",
    "code-reviewer",
    "spec-verifier",
    "unit-tester",
    "integration-tester",
    "devops",
]

# Agent purposes for recommendation messages
AGENT_PURPOSES = {
    "researcher": "research before designing",
    "architect": "design system architecture",
    "frontend": "implement frontend features",
    "backend": "implement backend features",
    "code-reviewer": "review code quality",
    "spec-verifier": "validate implementation against specs",
    "unit-tester": "write unit tests",
    "integration-tester": "write integration tests",
    "devops": "set up CI/CD and deployment",
}

# Expected KB files
EXPECTED_KB_FILES = [
    "architecture.md",
    "decisions.md",
    "api-contracts.md",
    "business-rules.md",
    "tech-debt.md",
    "runbook.md",
]

# Template markers — lines that indicate the file is still just a template
TEMPLATE_MARKERS = [
    "YYYY-MM-DD",
    "[Issue Title]",
    "[Component Name]",
    "[Decision Title]",
    "[Endpoint Name]",
    "[Rule Name]",
    "[Service Name]",
]


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_template_only(filepath):
    """Check if a KB file contains only template content (no real data)."""
    try:
        with open(filepath, "r") as f:
            content = f.read()
    except (OSError, IOError):
        return True

    # Judge the body only: the templates ship `created: YYYY-MM-DD` in their
    # frontmatter, which would otherwise mark a fully written file "template".
    body = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)

    # Empty or very short files are template-only
    stripped = body.strip()
    if len(stripped) < 50:
        return True

    # Check for template markers
    for marker in TEMPLATE_MARKERS:
        if marker in body:
            return True

    return False


def check_kb_completeness(kb_dir):
    """Check knowledge base file completeness.

    Returns dict:
    - total_files: count of expected KB files
    - populated_files: count of files with real content (not just templates)
    - percentage: completeness percentage
    - details: list of {file, status} where status is "populated"/"template"/"missing"
    """
    details = []
    populated = 0

    for filename in EXPECTED_KB_FILES:
        filepath = os.path.join(kb_dir, filename)
        if not os.path.exists(filepath):
            details.append({"file": filename, "status": "missing"})
        elif _is_template_only(filepath):
            details.append({"file": filename, "status": "template"})
        else:
            details.append({"file": filename, "status": "populated"})
            populated += 1

    total = len(EXPECTED_KB_FILES)
    percentage = round((populated / total) * 100) if total > 0 else 0

    return {
        "total_files": total,
        "populated_files": populated,
        "percentage": percentage,
        "details": details,
    }


def count_tech_debt(kb_dir):
    """Count tech debt items from tech-debt.md.

    Returns dict:
    - total: total count
    - by_priority: {high: N, medium: N, low: N}
    - oldest_days: days since oldest open item (or None)
    - items: list of {title, priority, created}
    """
    filepath = os.path.join(kb_dir, "tech-debt.md")
    result = {
        "total": 0,
        "by_priority": {"high": 0, "medium": 0, "low": 0},
        "oldest_days": None,
        "items": [],
    }

    if not os.path.exists(filepath):
        return result

    try:
        with open(filepath, "r") as f:
            content = f.read()
    except (OSError, IOError):
        return result

    # Parse ## sections as individual tech debt items
    sections = re.split(r"^## ", content, flags=re.MULTILINE)

    now = datetime.now(timezone.utc)
    oldest_date = None

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Extract title (first line of the section)
        lines = section.split("\n")
        title = lines[0].strip()

        # Skip template placeholders and the top-level heading
        if title.startswith("# ") or title in ("[Issue Title]", "Tech Debt"):
            continue

        # Extract priority
        priority = "medium"  # default
        priority_match = re.search(
            r"\*\*Priority\*\*:\s*(high|medium|low)", section, re.IGNORECASE
        )
        if priority_match:
            priority = priority_match.group(1).lower()

        # Also check for bracket-style markers: [HIGH], [MEDIUM], [LOW]
        bracket_match = re.search(r"\[(HIGH|MEDIUM|LOW)\]", section, re.IGNORECASE)
        if bracket_match:
            priority = bracket_match.group(1).lower()

        # Extract created date
        created = None
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", section)
        if date_match:
            date_str = date_match.group(1)
            if date_str != "YYYY-MM-DD":
                try:
                    created = datetime.strptime(date_str, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                    if oldest_date is None or created < oldest_date:
                        oldest_date = created
                except ValueError:
                    pass

        result["items"].append(
            {"title": title, "priority": priority, "created": date_str if date_match and date_str != "YYYY-MM-DD" else None}
        )
        result["by_priority"][priority] = result["by_priority"].get(priority, 0) + 1

    result["total"] = len(result["items"])

    if oldest_date is not None:
        result["oldest_days"] = (now - oldest_date).days

    return result


def get_workflow_stats(state_dir):
    """Get workflow completion statistics.

    Reads .coregy/state.json (current) and .coregy/state_history.json (past) if exists.

    Returns dict:
    - total_started: count
    - total_completed: count
    - total_aborted: count
    - completion_rate: percentage
    - avg_agents_per_workflow: float
    - agent_usage: dict of {agent_name: count}
    - unused_agents: list of agents never used
    """
    result = {
        "total_started": 0,
        "total_completed": 0,
        "total_aborted": 0,
        "completion_rate": 0,
        "avg_agents_per_workflow": 0.0,
        "agent_usage": {},
        "unused_agents": list(ALL_AGENTS),
    }

    all_workflows = []

    # Read current state
    state_path = os.path.join(state_dir, "state.json")
    if os.path.exists(state_path):
        try:
            with open(state_path, "r") as f:
                state = json.load(f)
            if isinstance(state, dict) and state.get("status"):
                all_workflows.append(state)
        except (json.JSONDecodeError, OSError):
            pass

    # Read history
    history_path = os.path.join(state_dir, "state_history.json")
    if os.path.exists(history_path):
        try:
            with open(history_path, "r") as f:
                history = json.load(f)
            if isinstance(history, list):
                all_workflows.extend(history)
        except (json.JSONDecodeError, OSError):
            pass

    if not all_workflows:
        return result

    agent_usage = {}
    total_agents_used = 0

    for wf in all_workflows:
        status = wf.get("status", "")
        result["total_started"] += 1

        if status == "completed":
            result["total_completed"] += 1
        elif status == "aborted":
            result["total_aborted"] += 1

        # Count agent usage from agent_log or agents_completed
        agents_in_wf = set()
        for key in ("agent_log", "agents_completed"):
            entries = wf.get(key, [])
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        agent_name = entry.get("agent", entry.get("name", ""))
                    else:
                        agent_name = str(entry)
                    if agent_name:
                        agents_in_wf.add(agent_name)
                        agent_usage[agent_name] = agent_usage.get(agent_name, 0) + 1

        total_agents_used += len(agents_in_wf)

    result["agent_usage"] = agent_usage
    result["unused_agents"] = [a for a in ALL_AGENTS if a not in agent_usage]

    if result["total_started"] > 0:
        result["completion_rate"] = round(
            (result["total_completed"] / result["total_started"]) * 100
        )
        result["avg_agents_per_workflow"] = round(
            total_agents_used / result["total_started"], 1
        )

    return result


def get_dependency_health(profile_path):
    """Extract dependency health from profile.yaml.

    Returns dict:
    - outdated_count: number of outdated deps
    - vulnerability_count: number of known vulnerabilities
    - total_deps: total dependency count
    """
    result = {
        "outdated_count": 0,
        "vulnerability_count": 0,
        "total_deps": 0,
    }

    if not os.path.exists(profile_path):
        return result

    try:
        # stdlib reader -- the PyYAML path silently returned zeros whenever
        # PyYAML was not installed
        with open(profile_path, "r") as f:
            profile = mini_yaml.loads(f.read())
    except (OSError, IOError):
        return result

    if not isinstance(profile, dict):
        return result

    # deep_analysis as written by detectors/deep_analysis.py: `outdated` and
    # `security` are lists of entries, `dependency_count` the total.
    deep = profile.get("deep_analysis", {})
    if isinstance(deep, dict):
        outdated = deep.get("outdated")
        security = deep.get("security")
        result["outdated_count"] = len(outdated) if isinstance(outdated, list) else 0
        result["vulnerability_count"] = len(security) if isinstance(security, list) else 0
        total = deep.get("dependency_count", 0)
        result["total_deps"] = total if isinstance(total, int) else 0

    # Also check dependencies section
    deps = profile.get("dependencies", {})
    if isinstance(deps, dict):
        if result["total_deps"] == 0:
            result["total_deps"] = deps.get("total", 0)
        if result["outdated_count"] == 0:
            result["outdated_count"] = deps.get("outdated", 0)
        if result["vulnerability_count"] == 0:
            result["vulnerability_count"] = deps.get("vulnerabilities", 0)

    return result


def generate_recommendations(report):
    """Generate actionable recommendations based on health data.

    Returns list of suggestion strings.
    """
    recs = []

    # KB completeness
    kb = report.get("kb", {})
    kb_pct = kb.get("percentage", 0)
    if kb_pct < 50:
        recs.append("Run /coregy-workflow:update-kb to populate knowledge base")
    elif kb_pct < 100:
        missing = [
            d["file"]
            for d in kb.get("details", [])
            if d["status"] in ("missing", "template")
        ]
        if missing:
            recs.append(
                "Populate remaining KB files: {}".format(", ".join(missing))
            )

    # Tech debt
    td = report.get("tech_debt", {})
    high_count = td.get("by_priority", {}).get("high", 0)
    if high_count > 0:
        # Find first high-priority item title
        high_items = [
            i["title"] for i in td.get("items", []) if i.get("priority") == "high"
        ]
        if high_items:
            recs.append(
                'Address high-priority tech debt item: "{}"'.format(high_items[0])
            )
        else:
            recs.append("Address high-priority tech debt items")

    oldest = td.get("oldest_days")
    if oldest is not None and oldest > 30:
        recs.append(
            "Oldest tech debt item is {} days old -- consider reviewing".format(oldest)
        )

    # Workflows
    wf = report.get("workflows", {})
    if wf.get("total_started", 0) == 0:
        recs.append("Start a workflow with /coregy-workflow:start-feature")
    else:
        rate = wf.get("completion_rate", 0)
        if rate < 50:
            recs.append(
                "Low completion rate ({}%) -- consider using /coregy-workflow:status to track progress".format(
                    rate
                )
            )

    # Unused agents
    unused = wf.get("unused_agents", [])
    for agent in unused:
        purpose = AGENT_PURPOSES.get(agent, "")
        if purpose:
            recs.append("Try {} agent to {}".format(agent, purpose))
            break  # Only suggest one unused agent to avoid noise

    # Dependencies
    deps = report.get("dependencies", {})
    if deps.get("outdated_count", 0) > 0:
        recs.append("Run /coregy-workflow:refresh --deep to check dependencies")
    if deps.get("vulnerability_count", 0) > 0:
        recs.append(
            "Address {} known dependency vulnerabilities".format(
                deps["vulnerability_count"]
            )
        )

    return recs


def build_health_report(cwd):
    """Build complete health report.

    Returns dict:
    - kb: KB completeness data
    - tech_debt: tech debt summary
    - workflows: workflow stats
    - dependencies: dependency health
    - recommendations: list of actionable suggestions
    - generated_at: timestamp
    - project_name: project name from profile or directory
    """
    coregy_dir = os.path.join(cwd, ".coregy")
    kb_dir = os.path.join(coregy_dir, "knowledge")
    profile_path = os.path.join(coregy_dir, "profile.yaml")

    # Get project name (parse from profile.yaml without PyYAML)
    project_name = os.path.basename(cwd)
    try:
        if os.path.exists(profile_path):
            with open(profile_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("name:"):
                        val = stripped[5:].strip().strip('"').strip("'")
                        if val:
                            project_name = val
                            break
    except OSError:
        pass

    report = {
        "project_name": project_name,
        "kb": check_kb_completeness(kb_dir),
        "tech_debt": count_tech_debt(kb_dir),
        "workflows": get_workflow_stats(coregy_dir),
        "dependencies": get_dependency_health(profile_path),
        "generated_at": _now(),
    }

    report["recommendations"] = generate_recommendations(report)

    return report


def _progress_bar(percentage, width=10):
    """Build a text progress bar like: ████████░░"""
    filled = round(percentage / 100 * width)
    empty = width - filled
    return "\u2588" * filled + "\u2591" * empty


def format_health_report(report):
    """Format health report as readable text (for command output)."""
    lines = []
    name = report.get("project_name", "unknown")
    header = "Project Health -- {}".format(name)
    lines.append(header)
    lines.append("\u2501" * len(header))
    lines.append("")

    # KB completeness
    kb = report.get("kb", {})
    kb_pct = kb.get("percentage", 0)
    kb_pop = kb.get("populated_files", 0)
    kb_total = kb.get("total_files", 0)
    lines.append(
        "Knowledge Base:  {} {}% complete ({}/{} files populated)".format(
            _progress_bar(kb_pct), kb_pct, kb_pop, kb_total
        )
    )

    # Tech debt
    td = report.get("tech_debt", {})
    td_total = td.get("total", 0)
    if td_total > 0:
        high = td.get("by_priority", {}).get("high", 0)
        med = td.get("by_priority", {}).get("medium", 0)
        low = td.get("by_priority", {}).get("low", 0)
        parts = []
        if high:
            parts.append("{} high".format(high))
        if med:
            parts.append("{} medium".format(med))
        if low:
            parts.append("{} low".format(low))
        debt_str = "Tech Debt:       {} open items ({})".format(
            td_total, ", ".join(parts)
        )
        oldest = td.get("oldest_days")
        if oldest is not None:
            debt_str += " -- oldest: {} days".format(oldest)
        lines.append(debt_str)
    else:
        lines.append("Tech Debt:       No open items")

    # Dependencies
    deps = report.get("dependencies", {})
    outdated = deps.get("outdated_count", 0)
    vulns = deps.get("vulnerability_count", 0)
    lines.append(
        "Dependencies:    {} outdated, {} vulnerabilities".format(outdated, vulns)
    )

    # Workflows
    wf = report.get("workflows", {})
    started = wf.get("total_started", 0)
    completed = wf.get("total_completed", 0)
    rate = wf.get("completion_rate", 0)
    if started > 0:
        lines.append(
            "Workflows:       {} started, {} completed ({}% completion rate)".format(
                started, completed, rate
            )
        )
        # Agent usage
        usage = wf.get("agent_usage", {})
        if usage:
            sorted_agents = sorted(usage.items(), key=lambda x: x[1], reverse=True)
            usage_parts = [
                "{} ({}x)".format(name, count) for name, count in sorted_agents
            ]
            lines.append(
                "Agent Usage:     {}".format(", ".join(usage_parts))
            )
        unused = wf.get("unused_agents", [])
        if unused:
            lines.append(
                "                 Warning: {} never used".format(", ".join(unused))
            )
    else:
        lines.append("Workflows:       No workflows started yet")

    # Recommendations
    recs = report.get("recommendations", [])
    if recs:
        lines.append("")
        lines.append("Recommendations:")
        for rec in recs:
            lines.append("  -> {}".format(rec))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI (coregy-cli-v1)
# ---------------------------------------------------------------------------

SECTIONS = ["all", "kb", "tech-debt", "workflows", "dependencies", "recommendations"]

# CLI section name -> key in the report dict
_SECTION_KEYS = {
    "kb": "kb",
    "tech-debt": "tech_debt",
    "workflows": "workflows",
    "dependencies": "dependencies",
    "recommendations": "recommendations",
}

# CLI section name -> prefixes kept when filtering the formatted dashboard
_SECTION_PREFIXES = {
    "kb": ("Knowledge Base:",),
    "tech-debt": ("Tech Debt:",),
    "workflows": ("Workflows:", "Agent Usage:", " " * 17),
    "dependencies": ("Dependencies:",),
}


def _output(data):
    print(json.dumps(data, indent=2, default=str))


def _fail(msg, json_mode=False):
    if json_mode:
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print("Error: %s" % msg, file=sys.stderr)
    sys.exit(1)


def _filter_section(text, section):
    """Keep only the lines of the rendered dashboard belonging to `section`.

    Filters the real output rather than duplicating the formatting logic.
    """
    lines = text.split("\n")
    kept = lines[:3]  # title, rule, blank

    if section == "recommendations":
        in_recs = False
        for line in lines[3:]:
            if line.startswith("Recommendations:"):
                in_recs = True
                kept.append(line)
            elif in_recs and line.startswith("  ->"):
                kept.append(line)
            elif in_recs:
                break
        return "\n".join(kept)

    prefixes = _SECTION_PREFIXES[section]
    for line in lines[3:]:
        if any(line.startswith(p) for p in prefixes):
            kept.append(line)
    return "\n".join(kept)


def main():
    parent = argparse.ArgumentParser(add_help=False)
    # default=SUPPRESS is load-bearing: --cwd lives on both the top-level
    # parser and every subparser (parents=[parent]). With a concrete
    # default the subparser re-applies it into its own namespace and
    # silently clobbers a --cwd given *before* the subcommand, so the
    # script would quietly operate on the process cwd instead.
    parent.add_argument("--cwd", default=argparse.SUPPRESS,
                        help="Project root directory (default: .)")

    parser = argparse.ArgumentParser(
        description="Coregy Workflow project health dashboard", parents=[parent]
    )
    sub = parser.add_subparsers(dest="command")

    p_report = sub.add_parser("report", parents=[parent], help="Print health dashboard")
    p_report.add_argument("--section", default="all", choices=SECTIONS,
                          help="Limit output to one section (default: all)")
    p_report.add_argument("--json", action="store_true", dest="json_mode",
                          help="Emit the raw report as JSON")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # getattr, not args.cwd: the shared --cwd action defaults to
    # SUPPRESS so a value given before the subcommand survives.
    cwd = os.path.abspath(getattr(args, "cwd", "."))
    json_mode = getattr(args, "json_mode", False)

    try:
        if not os.path.isdir(os.path.join(cwd, ".coregy")):
            _fail("No .coregy/ directory -- run /coregy-workflow:init first", json_mode)

        report = build_health_report(cwd)

        if json_mode:
            if args.section == "all":
                _output(report)
            else:
                key = _SECTION_KEYS[args.section]
                _output({key: report.get(key)})
        else:
            text = format_health_report(report)
            if args.section != "all":
                text = _filter_section(text, args.section)
            print(text)
    except (FileNotFoundError, ValueError, OSError) as exc:
        _fail(str(exc), json_mode)


if __name__ == "__main__":
    main()
