"""
SQLite schema and migration for the Interaction Tracking system.

Manages `.hody/tracker.db` — creates tables, handles migrations from
state.json, validates state machine transitions, and generates IDs.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone


# =====================================================================
# Helpers
# =====================================================================

def _now():
    """Return current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _db_path(cwd):
    return os.path.join(cwd, ".hody", "tracker.db")


# =====================================================================
# State Machine Transition Maps
# =====================================================================

TASK_TRANSITIONS = {
    "created":     ["in_progress", "abandoned"],
    "in_progress": ["completed", "paused", "blocked", "abandoned"],
    "paused":      ["in_progress", "abandoned"],
    "blocked":     ["in_progress", "abandoned"],
    "completed":   [],
    "abandoned":   [],
}

INVESTIGATION_TRANSITIONS = {
    "started":     ["in_progress", "abandoned"],
    "in_progress": ["concluded", "paused", "abandoned"],
    "paused":      ["in_progress", "abandoned"],
    "concluded":   [],
    "abandoned":   [],
}

QUESTION_TRANSITIONS = {
    "asked":    ["answered", "deferred"],
    "deferred": ["asked", "answered"],
    "answered": [],
}

DISCUSSION_TRANSITIONS = {
    "opened":   ["active", "tabled"],
    "active":   ["resolved", "tabled"],
    "tabled":   ["active"],
    "resolved": [],
}

MAINTENANCE_TRANSITIONS = {
    "planned":     ["in_progress", "deferred", "abandoned"],
    "in_progress": ["completed", "deferred", "abandoned"],
    "deferred":    ["planned", "in_progress", "abandoned"],
    "completed":   [],
    "abandoned":   [],
}

TYPE_TRANSITIONS = {
    "task":          TASK_TRANSITIONS,
    "investigation": INVESTIGATION_TRANSITIONS,
    "question":      QUESTION_TRANSITIONS,
    "discussion":    DISCUSSION_TRANSITIONS,
    "maintenance":   MAINTENANCE_TRANSITIONS,
}

INITIAL_STATUS = {
    "task":          "created",
    "investigation": "started",
    "question":      "asked",
    "discussion":    "opened",
    "maintenance":   "planned",
}


# =====================================================================
# Schema SQL
# =====================================================================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL CHECK (type IN ('task','investigation','question','discussion','maintenance')),
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    status      TEXT NOT NULL,
    priority    TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('high','medium','low')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    completed_at TEXT,
    session_id  TEXT NOT NULL,
    workflow_id TEXT,
    notes       TEXT DEFAULT '',
    extra       TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS item_tags (
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (item_id, tag)
);

CREATE TABLE IF NOT EXISTS item_files (
    item_id  TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    filepath TEXT NOT NULL,
    PRIMARY KEY (item_id, filepath)
);

CREATE TABLE IF NOT EXISTS item_relations (
    from_item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    to_item_id   TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    relation     TEXT NOT NULL CHECK (relation IN ('related','blocked_by','led_to','supersedes','parent','child')),
    created_at   TEXT NOT NULL,
    PRIMARY KEY (from_item_id, to_item_id, relation)
);

CREATE TABLE IF NOT EXISTS item_kb_refs (
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kb_ref  TEXT NOT NULL,
    PRIMARY KEY (item_id, kb_ref)
);

CREATE TABLE IF NOT EXISTS status_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status  TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    session_id TEXT NOT NULL,
    reason     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    summary    TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_items_type ON items(type);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_priority ON items(priority);
CREATE INDEX IF NOT EXISTS idx_items_created ON items(created_at);
CREATE INDEX IF NOT EXISTS idx_items_session ON items(session_id);
CREATE INDEX IF NOT EXISTS idx_items_workflow ON items(workflow_id);
CREATE INDEX IF NOT EXISTS idx_item_tags_tag ON item_tags(tag);
CREATE INDEX IF NOT EXISTS idx_status_log_item ON status_log(item_id);
CREATE INDEX IF NOT EXISTS idx_status_log_time ON status_log(changed_at);
CREATE INDEX IF NOT EXISTS idx_item_relations_to ON item_relations(to_item_id);

CREATE TABLE IF NOT EXISTS checkpoints (
    id          TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    agent       TEXT NOT NULL,
    phase       TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    total_items INTEGER DEFAULT 0,
    completed_items INTEGER DEFAULT 0,
    items_json  TEXT DEFAULT '[]',
    partial_output TEXT DEFAULT '',
    resume_hint TEXT DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_checkpoints_workflow_agent
    ON checkpoints(workflow_id, agent);
CREATE INDEX IF NOT EXISTS idx_checkpoints_workflow ON checkpoints(workflow_id);
"""


# =====================================================================
# ID Generation
# =====================================================================

def generate_item_id():
    """Generate a unique item ID: itm_<12 hex chars>."""
    return "itm_" + uuid.uuid4().hex[:12]


def generate_session_id(cwd=None):
    """Generate a session ID: ses_<YYYYMMDD>_<3-digit seq>.

    The sequence number is based on how many sessions already exist
    for the current date. If cwd is provided and tracker.db exists,
    queries the database; otherwise starts at 001.
    """
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"ses_{today}_"
    seq = 1

    if cwd:
        db_file = _db_path(cwd)
        if os.path.isfile(db_file):
            try:
                conn = sqlite3.connect(db_file)
                conn.execute("PRAGMA foreign_keys = ON")
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE id LIKE ?",
                    (f"{prefix}%",)
                )
                count = cursor.fetchone()[0]
                seq = count + 1
                conn.close()
            except Exception:
                pass  # Fall back to seq=1

    return f"{prefix}{seq:03d}"


# =====================================================================
# Database Initialization & Access
# =====================================================================

def init_db(cwd):
    """Create tracker.db with the full schema.

    Idempotent — safe to call multiple times. Uses CREATE TABLE IF NOT EXISTS
    for all tables and CREATE INDEX IF NOT EXISTS for all indexes.

    Sets PRAGMA journal_mode = WAL and PRAGMA foreign_keys = ON.
    """
    db_file = _db_path(cwd)
    os.makedirs(os.path.dirname(db_file), exist_ok=True)

    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


def get_db(cwd):
    """Open a connection to tracker.db.

    Returns a sqlite3.Connection with row_factory set to sqlite3.Row
    for dict-like access.

    Raises FileNotFoundError if the database has not been initialized.
    """
    db_file = _db_path(cwd)
    if not os.path.isfile(db_file):
        raise FileNotFoundError(
            f"Tracker database not found at {db_file}. "
            "Run init_db() or /hody-workflow:init first."
        )

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# =====================================================================
# Transition Validation
# =====================================================================

def validate_transition(item_type, from_status, to_status):
    """Check if a status transition is valid for the given item type.

    Args:
        item_type: One of 'task', 'investigation', 'question',
                   'discussion', 'maintenance'.
        from_status: Current status of the item.
        to_status: Desired new status.

    Returns:
        True if the transition is valid, False otherwise.
    """
    transitions = TYPE_TRANSITIONS.get(item_type)
    if transitions is None:
        return False

    allowed = transitions.get(from_status)
    if allowed is None:
        return False

    return to_status in allowed


# =====================================================================
# Migration from state.json
# =====================================================================

def _map_workflow_status(workflow_status):
    """Map state.json workflow status to tracker item status."""
    mapping = {
        "in_progress": "in_progress",
        "completed": "completed",
        "aborted": "abandoned",
    }
    return mapping.get(workflow_status, "created")


def _extract_agents(state):
    """Extract list of agents involved from state.json phases."""
    agents = []
    for phase in state.get("phase_order", []):
        phase_data = state.get("phases", {}).get(phase, {})
        for agent in phase_data.get("completed", []):
            if agent not in agents:
                agents.append(agent)
        active = phase_data.get("active")
        if active and active not in agents:
            agents.append(active)
    return agents


def migrate_from_state_json(cwd):
    """Import current state.json into tracker.db.

    Reads state.json using the existing state.load_state() function.
    Creates a task item with the workflow info. Imports agent_log
    entries into the status_log table.

    Returns the created item dict or None if no state.json exists.
    """
    # Import state module — handle gracefully if not available
    try:
        from . import state as state_module
    except ImportError:
        try:
            import state as state_module
        except ImportError:
            # Cannot import state module; read state.json directly
            state_path = os.path.join(cwd, ".hody", "state.json")
            if not os.path.isfile(state_path):
                return None
            with open(state_path, "r") as f:
                state_data = json.load(f)
            return _do_migrate(cwd, state_data)

    state_data = state_module.load_state(cwd)
    if state_data is None:
        return None

    return _do_migrate(cwd, state_data)


def _do_migrate(cwd, state_data):
    """Perform the actual migration from a loaded state dict."""
    # Ensure db is initialized
    init_db(cwd)

    conn = get_db(cwd)
    now = _now()

    # Idempotent: /init runs migrate on every re-init while state.json exists.
    workflow_id = state_data.get("workflow_id")
    if workflow_id:
        row = conn.execute(
            "SELECT id, type, title, status, workflow_id, session_id, created_at, extra "
            "FROM items WHERE workflow_id = ?", (workflow_id,)
        ).fetchone()
        if row is not None:
            conn.close()
            existing = dict(row)
            try:
                existing["extra"] = json.loads(existing.get("extra") or "{}")
            except (json.JSONDecodeError, TypeError):
                existing["extra"] = {}
            existing["already_migrated"] = True
            return existing

    # Generate IDs
    item_id = generate_item_id()
    session_id = generate_session_id(cwd)

    # Create session
    conn.execute(
        "INSERT OR IGNORE INTO sessions (id, started_at) VALUES (?, ?)",
        (session_id, state_data.get("created_at", now))
    )

    # Map status
    status = _map_workflow_status(state_data.get("status", "in_progress"))

    # Determine completed_at
    completed_at = None
    if status in ("completed", "abandoned"):
        completed_at = state_data.get("updated_at", now)

    # Build extra metadata
    extra = {
        "feature_type": state_data.get("type", ""),
        "agents_involved": _extract_agents(state_data),
    }

    # Insert item
    conn.execute(
        """INSERT INTO items
           (id, type, title, description, status, priority,
            created_at, updated_at, completed_at, session_id,
            workflow_id, notes, extra)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item_id,
            "task",
            state_data.get("feature", "Migrated workflow"),
            "",
            status,
            "medium",
            state_data.get("created_at", now),
            state_data.get("updated_at", now),
            completed_at,
            session_id,
            state_data.get("workflow_id"),
            "",
            json.dumps(extra),
        )
    )

    # Insert initial status log entry
    conn.execute(
        """INSERT INTO status_log
           (item_id, from_status, to_status, changed_at, session_id, reason)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (item_id, None, "created", state_data.get("created_at", now),
         session_id, "Migrated from state.json")
    )

    # Import agent_log entries as status_log records
    for log_entry in state_data.get("agent_log", []):
        if log_entry.get("completed_at"):
            reason = (
                f"Agent {log_entry.get('agent', 'unknown')} completed: "
                f"{log_entry.get('output_summary', '')}"
            )
            conn.execute(
                """INSERT INTO status_log
                   (item_id, from_status, to_status, changed_at,
                    session_id, reason)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    "in_progress",
                    "in_progress",
                    log_entry["completed_at"],
                    session_id,
                    reason,
                )
            )

    conn.commit()
    conn.close()

    # Return item as dict
    return {
        "id": item_id,
        "type": "task",
        "title": state_data.get("feature", "Migrated workflow"),
        "status": status,
        "workflow_id": state_data.get("workflow_id"),
        "session_id": session_id,
        "created_at": state_data.get("created_at", now),
        "extra": extra,
    }
