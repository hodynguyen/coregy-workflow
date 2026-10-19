"""
Awareness layer for the Interaction Tracking system.

Surfaces actionable information at session start: active items, warnings
about stale/blocked work, and recently completed items. Designed to be
concise — developers should not see walls of text when starting a session.

Used by the SessionStart hook (inject_project_context.py) to provide
context about ongoing work.
"""
import os
from datetime import datetime, timezone, timedelta

# Handle both package and direct imports
try:
    from . import tracker_schema as schema
    from . import tracker as tracker_mod
except ImportError:
    import tracker_schema as schema
    import tracker as tracker_mod


# =====================================================================
# Terminal states per type (mirrors tracker.TERMINAL_STATES)
# =====================================================================

TERMINAL_STATES = {
    "task":          {"completed", "abandoned"},
    "investigation": {"concluded", "abandoned"},
    "question":      {"answered"},
    "discussion":    {"resolved"},
    "maintenance":   {"completed", "abandoned"},
}


# =====================================================================
# Helpers
# =====================================================================

def _days_since(iso_date):
    """Calculate whole days since an ISO date string until now (UTC).

    Handles both 'YYYY-MM-DDTHH:MM:SSZ' and 'YYYY-MM-DD' formats.

    Args:
        iso_date: ISO 8601 date/datetime string.

    Returns:
        Number of days as an integer (0 means today).
    """
    if not iso_date:
        return 0

    # Strip trailing Z and parse
    cleaned = iso_date.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt
            return max(0, delta.days)
        except ValueError:
            continue

    return 0


def _format_age(days):
    """Format a number of days into a concise human-readable age string.

    Examples:
        0 -> "today"
        1 -> "1d"
        6 -> "6d"
        7 -> "1w"
        14 -> "2w"
        30 -> "1mo"
        60 -> "2mo"

    Args:
        days: Number of days.

    Returns:
        Short age string.
    """
    if days == 0:
        return "today"
    if days < 7:
        return f"{days}d"
    if days < 30:
        weeks = days // 7
        return f"{weeks}w"
    months = days // 30
    return f"{months}mo"


# =====================================================================
# Warning Rules
# =====================================================================

WARNING_RULES = [
    {
        "id": "stale_in_progress_task",
        "types": {"task"},
        "statuses": {"in_progress"},
        "min_days": 3,
        "severity": "warning",
        "message": "Task \"{title}\" no progress in {age} -- consider updating or pausing",
    },
    {
        "id": "long_paused_task",
        "types": {"task"},
        "statuses": {"paused"},
        "min_days": 7,
        "severity": "warning",
        "message": "Task \"{title}\" paused {age} -- resume or abandon",
    },
    {
        "id": "long_blocked_task",
        "types": {"task"},
        "statuses": {"blocked"},
        "min_days": 5,
        "severity": "error",
        "message": "Task \"{title}\" blocked {age} -- check blocker",
    },
    {
        "id": "stale_investigation",
        "types": {"investigation"},
        "statuses": {"in_progress"},
        "min_days": 14,
        "severity": "info",
        "message": "Investigation \"{title}\" in progress {age} with no conclusion",
    },
    {
        "id": "deferred_question",
        "types": {"question"},
        "statuses": {"deferred"},
        "min_days": 7,
        "severity": "info",
        "message": "Question \"{title}\" unanswered for {age}",
    },
]

# Rule 5 (too many in_progress tasks) is handled separately in
# get_warnings() since it's a count-based rule rather than per-item.

_TOO_MANY_IN_PROGRESS_THRESHOLD = 3


# =====================================================================
# Core Functions
# =====================================================================

def get_warnings(cwd):
    """Apply WARNING_RULES against current items and return warnings.

    Checks each non-terminal item against the per-item rules, and also
    checks for the count-based "too many in_progress tasks" rule.

    Args:
        cwd: Project root directory.

    Returns:
        List of warning dicts, each with 'severity' and 'message' keys.
        Maximum 3 warnings returned (highest severity first).
    """
    try:
        items = tracker_mod.get_incomplete(cwd)
    except FileNotFoundError:
        return []

    warnings = []

    # Per-item rules
    for item in items:
        item_type = item.get("type", "")
        item_status = item.get("status", "")
        updated_at = item.get("updated_at", "")
        title = item.get("title", "untitled")
        days = _days_since(updated_at)

        for rule in WARNING_RULES:
            if item_type not in rule["types"]:
                continue
            if item_status not in rule["statuses"]:
                continue
            if days < rule["min_days"]:
                continue

            age = _format_age(days)
            warnings.append({
                "severity": rule["severity"],
                "message": rule["message"].format(title=title, age=age),
            })

    # Count-based rule: too many tasks in_progress simultaneously
    in_progress_tasks = [
        it for it in items
        if it.get("type") == "task" and it.get("status") == "in_progress"
    ]
    if len(in_progress_tasks) > _TOO_MANY_IN_PROGRESS_THRESHOLD:
        count = len(in_progress_tasks)
        warnings.append({
            "severity": "warning",
            "message": (
                f"{count} tasks in_progress simultaneously "
                f"-- consider completing some before starting new ones"
            ),
        })

    # Sort by severity (error > warning > info), then truncate to 3
    severity_order = {"error": 0, "warning": 1, "info": 2}
    warnings.sort(key=lambda w: severity_order.get(w["severity"], 9))
    return warnings[:3]


def get_session_context(cwd):
    """Build context dict for SessionStart hook injection.

    Reads tracker.db to gather active items, warnings, and recently
    completed items. Returns a dict suitable for injection into the
    system message.

    Args:
        cwd: Project root directory.

    Returns:
        Dict with keys: summary, active_items, warnings, recent_completed.
        Returns a minimal dict if tracker.db does not exist.
    """
    db_path = os.path.join(cwd, ".coregy", "tracker.db")
    if not os.path.isfile(db_path):
        return {
            "summary": "No tracker database found",
            "active_items": [],
            "warnings": [],
            "recent_completed": [],
        }

    # Active items (non-terminal), max 5, sorted by priority
    try:
        active_items = tracker_mod.get_active_items(cwd, limit=5)
    except FileNotFoundError:
        active_items = []

    # Warnings
    warnings = get_warnings(cwd)

    # Recently completed (last 24h), max 3
    recent_completed = _get_recent_completed(cwd, hours=24, limit=3)

    # Build summary
    summary = _build_summary(active_items, recent_completed)

    return {
        "summary": summary,
        "active_items": active_items,
        "warnings": warnings,
        "recent_completed": recent_completed,
    }


def format_context_for_hook(context):
    """Format the context dict into a human-readable string for hook injection.

    Produces a concise multi-line string. Example output:

        [Coregy Tracker] Active: 1 task in_progress (OAuth2 login, 3d), 1 paused (Payment, 5d)
        Warnings: Task "Payment" paused 5 days -- resume or abandon
        Recent: 1 task completed today

    Args:
        context: Dict returned by get_session_context().

    Returns:
        Formatted string for system message injection, or empty string
        if there is nothing to report.
    """
    parts = []

    # Active items line
    active = context.get("active_items", [])
    if active:
        segments = []
        for item in active:
            title = item.get("title", "untitled")
            # Truncate long titles
            if len(title) > 30:
                title = title[:27] + "..."
            status = item.get("status", "unknown")
            days = _days_since(item.get("updated_at", ""))
            age = _format_age(days)
            item_type = item.get("type", "item")
            priority = item.get("priority", "medium")
            prefix = "[HIGH] " if priority == "high" else ""
            segments.append(f"{prefix}{item_type} {status} ({title}, {age})")
        parts.append("[Coregy Tracker] Active: " + "; ".join(segments))
    else:
        if not context.get("recent_completed"):
            return ""
        parts.append("[Coregy Tracker] No active items")

    # Warnings line
    warnings = context.get("warnings", [])
    if warnings:
        warning_msgs = [w["message"] for w in warnings]
        parts.append("Warnings: " + " | ".join(warning_msgs))

    # Recent completed line
    recent = context.get("recent_completed", [])
    if recent:
        count = len(recent)
        noun = "item" if count == 1 else "items"
        titles = ", ".join(r.get("title", "untitled")[:25] for r in recent)
        parts.append(f"Recent: {count} {noun} completed ({titles})")

    return "\n".join(parts)


# =====================================================================
# Internal Helpers
# =====================================================================

def _get_recent_completed(cwd, hours=24, limit=3):
    """Get items completed within the last N hours.

    Args:
        cwd: Project root directory.
        hours: Look-back window in hours.
        limit: Maximum number of items to return.

    Returns:
        List of item dicts that reached a terminal state recently.
    """
    try:
        conn = schema.get_db(cwd)
    except FileNotFoundError:
        return []

    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Get all terminal statuses
    all_terminal = set()
    for statuses in TERMINAL_STATES.values():
        all_terminal.update(statuses)

    # Exclude 'abandoned' from "recent completed" — only show positive outcomes
    positive_terminal = all_terminal - {"abandoned"}
    placeholders = ",".join("?" for _ in positive_terminal)

    rows = conn.execute(
        f"""SELECT * FROM items
            WHERE status IN ({placeholders})
              AND completed_at IS NOT NULL
              AND completed_at >= ?
            ORDER BY completed_at DESC
            LIMIT ?""",
        (*positive_terminal, cutoff, limit)
    ).fetchall()

    result = []
    for row in rows:
        result.append(tracker_mod._item_to_dict(conn, row))

    conn.close()
    return result


def _build_summary(active_items, recent_completed):
    """Build a one-line summary string from active items and recent completions.

    Args:
        active_items: List of active item dicts.
        recent_completed: List of recently completed item dicts.

    Returns:
        Summary string like "2 tasks in progress, 1 paused".
    """
    if not active_items and not recent_completed:
        return "No active items"

    # Count by status
    status_counts = {}
    for item in active_items:
        status = item.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    parts = []
    for status, count in sorted(status_counts.items()):
        label = status.replace("_", " ")
        noun = "item" if count == 1 else "items"
        parts.append(f"{count} {label}")

    summary = ", ".join(parts) if parts else "no active items"

    if recent_completed:
        count = len(recent_completed)
        noun = "item" if count == 1 else "items"
        summary += f", {count} {noun} completed recently"

    return summary
