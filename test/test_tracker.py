"""Tests for the interaction tracking system modules:
tracker_schema.py, tracker.py, and tracker_awareness.py."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "coregy-workflow",
    "skills",
    "project-profile",
    "scripts",
)
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

import tracker_schema as schema
import tracker as tracker_mod
import tracker_awareness as awareness


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


# =====================================================================
# tracker_schema.py tests
# =====================================================================


class TestInitDB(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_init_db_creates_file(self):
        """init_db creates tracker.db inside .coregy directory."""
        schema.init_db(self.tmpdir)
        db_path = os.path.join(self.tmpdir, ".coregy", "tracker.db")
        self.assertTrue(os.path.isfile(db_path))

    def test_init_db_idempotent(self):
        """Calling init_db twice does not raise an error."""
        schema.init_db(self.tmpdir)
        schema.init_db(self.tmpdir)
        db_path = os.path.join(self.tmpdir, ".coregy", "tracker.db")
        self.assertTrue(os.path.isfile(db_path))

    def test_init_db_creates_all_tables(self):
        """init_db creates all expected tables."""
        schema.init_db(self.tmpdir)
        conn = sqlite3.connect(os.path.join(self.tmpdir, ".coregy", "tracker.db"))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        expected = {
            "items", "item_tags", "item_files", "item_relations",
            "item_kb_refs", "status_log", "sessions",
        }
        self.assertTrue(expected.issubset(tables), f"Missing tables: {expected - tables}")


class TestGetDB(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_get_db_returns_connection_with_row_factory(self):
        """get_db returns a connection with sqlite3.Row factory."""
        schema.init_db(self.tmpdir)
        conn = schema.get_db(self.tmpdir)
        self.assertEqual(conn.row_factory, sqlite3.Row)
        conn.close()

    def test_get_db_raises_when_no_db(self):
        """get_db raises FileNotFoundError when tracker.db does not exist."""
        with self.assertRaises(FileNotFoundError):
            schema.get_db(self.tmpdir)


class TestGenerateItemId(unittest.TestCase):
    def test_format(self):
        """generate_item_id returns itm_ followed by 12 hex chars."""
        item_id = schema.generate_item_id()
        self.assertTrue(item_id.startswith("itm_"))
        self.assertEqual(len(item_id), 16)  # 4 + 12
        self.assertRegex(item_id[4:], r'^[0-9a-f]{12}$')

    def test_uniqueness(self):
        """Two generated IDs should differ."""
        id1 = schema.generate_item_id()
        id2 = schema.generate_item_id()
        self.assertNotEqual(id1, id2)


class TestGenerateSessionId(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_format_without_cwd(self):
        """generate_session_id without cwd returns ses_YYYYMMDD_001."""
        sid = schema.generate_session_id()
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.assertEqual(sid, f"ses_{today}_001")

    def test_format_with_cwd_no_db(self):
        """generate_session_id with cwd but no db returns ses_YYYYMMDD_001."""
        sid = schema.generate_session_id(self.tmpdir)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.assertEqual(sid, f"ses_{today}_001")

    def test_increments_sequence(self):
        """generate_session_id increments sequence based on existing sessions."""
        schema.init_db(self.tmpdir)
        conn = schema.get_db(self.tmpdir)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        # Insert two sessions for today
        conn.execute(
            "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
            (f"ses_{today}_001", "2026-01-01T00:00:00Z")
        )
        conn.execute(
            "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
            (f"ses_{today}_002", "2026-01-01T00:00:00Z")
        )
        conn.commit()
        conn.close()

        sid = schema.generate_session_id(self.tmpdir)
        self.assertEqual(sid, f"ses_{today}_003")


class TestValidateTransition(unittest.TestCase):
    def test_valid_task_transitions(self):
        """Valid task transitions return True."""
        self.assertTrue(schema.validate_transition("task", "created", "in_progress"))
        self.assertTrue(schema.validate_transition("task", "in_progress", "completed"))
        self.assertTrue(schema.validate_transition("task", "in_progress", "paused"))
        self.assertTrue(schema.validate_transition("task", "paused", "in_progress"))

    def test_invalid_task_transitions(self):
        """Invalid task transitions return False."""
        self.assertFalse(schema.validate_transition("task", "created", "completed"))
        self.assertFalse(schema.validate_transition("task", "completed", "in_progress"))
        self.assertFalse(schema.validate_transition("task", "paused", "completed"))

    def test_valid_investigation_transition(self):
        """Valid investigation transition returns True."""
        self.assertTrue(schema.validate_transition("investigation", "started", "in_progress"))
        self.assertTrue(schema.validate_transition("investigation", "in_progress", "concluded"))

    def test_valid_question_transition(self):
        """Valid question transition returns True."""
        self.assertTrue(schema.validate_transition("question", "asked", "answered"))
        self.assertTrue(schema.validate_transition("question", "asked", "deferred"))

    def test_valid_discussion_transition(self):
        """Valid discussion transition returns True."""
        self.assertTrue(schema.validate_transition("discussion", "opened", "active"))
        self.assertTrue(schema.validate_transition("discussion", "active", "resolved"))

    def test_valid_maintenance_transition(self):
        """Valid maintenance transition returns True."""
        self.assertTrue(schema.validate_transition("maintenance", "planned", "in_progress"))
        self.assertTrue(schema.validate_transition("maintenance", "in_progress", "completed"))

    def test_unknown_type_returns_false(self):
        """Unknown item type returns False."""
        self.assertFalse(schema.validate_transition("unknown_type", "foo", "bar"))

    def test_unknown_from_status_returns_false(self):
        """Unknown from_status returns False."""
        self.assertFalse(schema.validate_transition("task", "nonexistent", "completed"))

    def test_terminal_states_have_empty_transitions(self):
        """Terminal states have empty allowed-transitions lists."""
        self.assertEqual(schema.TASK_TRANSITIONS["completed"], [])
        self.assertEqual(schema.TASK_TRANSITIONS["abandoned"], [])
        self.assertEqual(schema.INVESTIGATION_TRANSITIONS["concluded"], [])
        self.assertEqual(schema.INVESTIGATION_TRANSITIONS["abandoned"], [])
        self.assertEqual(schema.QUESTION_TRANSITIONS["answered"], [])
        self.assertEqual(schema.DISCUSSION_TRANSITIONS["resolved"], [])
        self.assertEqual(schema.MAINTENANCE_TRANSITIONS["completed"], [])
        self.assertEqual(schema.MAINTENANCE_TRANSITIONS["abandoned"], [])


class TestInitialStatus(unittest.TestCase):
    def test_all_types_have_initial_status(self):
        """All 5 item types have correct INITIAL_STATUS entries."""
        self.assertEqual(schema.INITIAL_STATUS["task"], "created")
        self.assertEqual(schema.INITIAL_STATUS["investigation"], "started")
        self.assertEqual(schema.INITIAL_STATUS["question"], "asked")
        self.assertEqual(schema.INITIAL_STATUS["discussion"], "opened")
        self.assertEqual(schema.INITIAL_STATUS["maintenance"], "planned")
        self.assertEqual(len(schema.INITIAL_STATUS), 5)


class TestMigrateFromStateJson(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_migrate_no_state_json(self):
        """Returns None when state.json does not exist."""
        result = schema.migrate_from_state_json(self.tmpdir)
        self.assertIsNone(result)

    def test_migrate_imports_state_json(self):
        """Imports state.json into tracker.db correctly."""
        state_data = {
            "workflow_id": "wf_test123",
            "feature": "Add OAuth2",
            "type": "feature",
            "status": "in_progress",
            "created_at": "2026-01-15T10:00:00Z",
            "updated_at": "2026-01-16T14:00:00Z",
            "phase_order": ["think", "build"],
            "phases": {
                "think": {"completed": ["researcher"], "active": None},
                "build": {"completed": [], "active": "backend"},
            },
            "agent_log": [
                {
                    "agent": "researcher",
                    "completed_at": "2026-01-15T12:00:00Z",
                    "output_summary": "Research done",
                },
            ],
        }
        state_path = os.path.join(self.tmpdir, ".coregy", "state.json")
        _write_file(state_path, json.dumps(state_data))

        result = schema.migrate_from_state_json(self.tmpdir)
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "task")
        self.assertEqual(result["title"], "Add OAuth2")
        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(result["workflow_id"], "wf_test123")
        self.assertIn("researcher", result["extra"]["agents_involved"])
        self.assertIn("backend", result["extra"]["agents_involved"])

    def test_migrate_completed_workflow(self):
        """Migrating a completed workflow sets status to completed."""
        state_data = {
            "workflow_id": "wf_done",
            "feature": "Done Feature",
            "status": "completed",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "phase_order": [],
            "phases": {},
            "agent_log": [],
        }
        state_path = os.path.join(self.tmpdir, ".coregy", "state.json")
        _write_file(state_path, json.dumps(state_data))

        result = schema.migrate_from_state_json(self.tmpdir)
        self.assertEqual(result["status"], "completed")

    def test_migrate_creates_status_log_entries(self):
        """Migration creates status_log entries for agent_log items."""
        state_data = {
            "workflow_id": "wf_log",
            "feature": "Log Test",
            "status": "in_progress",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "phase_order": [],
            "phases": {},
            "agent_log": [
                {
                    "agent": "backend",
                    "completed_at": "2026-01-01T12:00:00Z",
                    "output_summary": "Implemented API",
                },
                {
                    "agent": "frontend",
                    "completed_at": "2026-01-01T14:00:00Z",
                    "output_summary": "Built UI",
                },
            ],
        }
        state_path = os.path.join(self.tmpdir, ".coregy", "state.json")
        _write_file(state_path, json.dumps(state_data))

        result = schema.migrate_from_state_json(self.tmpdir)

        conn = schema.get_db(self.tmpdir)
        logs = conn.execute(
            "SELECT * FROM status_log WHERE item_id = ? ORDER BY changed_at",
            (result["id"],)
        ).fetchall()
        conn.close()
        # 1 initial + 2 agent_log entries = 3
        self.assertEqual(len(logs), 3)
        self.assertIn("Migrated from state.json", logs[0]["reason"])
        self.assertIn("backend", logs[1]["reason"])
        self.assertIn("frontend", logs[2]["reason"])


# =====================================================================
# tracker.py tests
# =====================================================================


class TestEnsureSession(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_creates_new_session(self):
        """ensure_session creates a new session and returns its ID."""
        sid = tracker_mod.ensure_session(self.tmpdir)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.assertTrue(sid.startswith(f"ses_{today}_"))

    def test_reuses_open_session_same_day(self):
        """Calling ensure_session twice returns the same session ID."""
        sid1 = tracker_mod.ensure_session(self.tmpdir)
        sid2 = tracker_mod.ensure_session(self.tmpdir)
        self.assertEqual(sid1, sid2)


class TestEndSession(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_end_session_sets_ended_at(self):
        """end_session sets the ended_at timestamp."""
        sid = tracker_mod.ensure_session(self.tmpdir)
        tracker_mod.end_session(self.tmpdir, sid, summary="Done for today")

        conn = schema.get_db(self.tmpdir)
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        conn.close()
        self.assertIsNotNone(row["ended_at"])
        self.assertEqual(row["summary"], "Done for today")


class TestCreateItem(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_create_task(self):
        """Creating a task sets initial status to 'created'."""
        item = tracker_mod.create_item(self.tmpdir, type="task", title="Fix bug")
        self.assertEqual(item["type"], "task")
        self.assertEqual(item["status"], "created")
        self.assertEqual(item["title"], "Fix bug")
        self.assertTrue(item["id"].startswith("itm_"))

    def test_create_investigation(self):
        """Creating an investigation sets initial status to 'started'."""
        item = tracker_mod.create_item(self.tmpdir, type="investigation", title="Research")
        self.assertEqual(item["status"], "started")

    def test_create_question(self):
        """Creating a question sets initial status to 'asked'."""
        item = tracker_mod.create_item(self.tmpdir, type="question", title="Why?")
        self.assertEqual(item["status"], "asked")

    def test_create_discussion(self):
        """Creating a discussion sets initial status to 'opened'."""
        item = tracker_mod.create_item(self.tmpdir, type="discussion", title="Design review")
        self.assertEqual(item["status"], "opened")

    def test_create_maintenance(self):
        """Creating a maintenance item sets initial status to 'planned'."""
        item = tracker_mod.create_item(self.tmpdir, type="maintenance", title="Upgrade deps")
        self.assertEqual(item["status"], "planned")

    def test_create_with_tags(self):
        """Creating an item with tags stores them correctly."""
        item = tracker_mod.create_item(
            self.tmpdir, type="task", title="Tagged",
            tags=["auth", "backend"]
        )
        self.assertIn("auth", item["tags"])
        self.assertIn("backend", item["tags"])

    def test_create_with_files(self):
        """Creating an item with related_files stores them correctly."""
        item = tracker_mod.create_item(
            self.tmpdir, type="task", title="Files",
            related_files=["src/main.py", "src/utils.py"]
        )
        self.assertIn("src/main.py", item["related_files"])
        self.assertIn("src/utils.py", item["related_files"])

    def test_create_with_extra(self):
        """Creating an item with extra metadata stores it correctly."""
        item = tracker_mod.create_item(
            self.tmpdir, type="task", title="Extra",
            extra={"complexity": "high", "estimated_hours": 4}
        )
        self.assertEqual(item["extra"]["complexity"], "high")
        self.assertEqual(item["extra"]["estimated_hours"], 4)

    def test_create_invalid_type_raises(self):
        """Creating an item with invalid type raises ValueError."""
        with self.assertRaises(ValueError):
            tracker_mod.create_item(self.tmpdir, type="invalid", title="Bad")


class TestGetItem(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_get_existing_item(self):
        """get_item returns full dict with tags, files, kb_refs."""
        item = tracker_mod.create_item(
            self.tmpdir, type="task", title="Test",
            tags=["tag1"], related_files=["file1.py"]
        )
        tracker_mod.add_kb_ref(self.tmpdir, item["id"], "architecture.md")

        fetched = tracker_mod.get_item(self.tmpdir, item["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["title"], "Test")
        self.assertIn("tag1", fetched["tags"])
        self.assertIn("file1.py", fetched["related_files"])
        self.assertIn("architecture.md", fetched["kb_refs"])

    def test_get_nonexistent_item_returns_none(self):
        """get_item returns None for non-existent ID."""
        schema.init_db(self.tmpdir)
        result = tracker_mod.get_item(self.tmpdir, "itm_doesnotexist")
        self.assertIsNone(result)


class TestUpdateItem(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_partial_update_title(self):
        """update_item with only title updates title, keeps others."""
        item = tracker_mod.create_item(self.tmpdir, type="task", title="Old Title")
        updated = tracker_mod.update_item(self.tmpdir, item["id"], title="New Title")
        self.assertEqual(updated["title"], "New Title")
        self.assertEqual(updated["type"], "task")

    def test_extra_merge_not_replace(self):
        """update_item merges extra dict rather than replacing."""
        item = tracker_mod.create_item(
            self.tmpdir, type="task", title="Merge Test",
            extra={"key1": "value1", "key2": "value2"}
        )
        updated = tracker_mod.update_item(
            self.tmpdir, item["id"],
            extra={"key2": "updated", "key3": "new"}
        )
        self.assertEqual(updated["extra"]["key1"], "value1")
        self.assertEqual(updated["extra"]["key2"], "updated")
        self.assertEqual(updated["extra"]["key3"], "new")

    def test_update_nonexistent_raises(self):
        """update_item raises ValueError for nonexistent item."""
        schema.init_db(self.tmpdir)
        with self.assertRaises(ValueError):
            tracker_mod.update_item(self.tmpdir, "itm_doesnotexist", title="X")


class TestTransitionStatus(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_valid_transition(self):
        """Valid transition updates status correctly."""
        item = tracker_mod.create_item(self.tmpdir, type="task", title="Trans Test")
        updated = tracker_mod.transition_status(
            self.tmpdir, item["id"], "in_progress", reason="Starting work"
        )
        self.assertEqual(updated["status"], "in_progress")

    def test_invalid_transition_raises(self):
        """Invalid transition raises ValueError."""
        item = tracker_mod.create_item(self.tmpdir, type="task", title="Bad Trans")
        with self.assertRaises(ValueError) as ctx:
            tracker_mod.transition_status(self.tmpdir, item["id"], "completed")
        self.assertIn("Invalid transition", str(ctx.exception))

    def test_terminal_state_sets_completed_at(self):
        """Transitioning to terminal state sets completed_at."""
        item = tracker_mod.create_item(self.tmpdir, type="task", title="Complete")
        tracker_mod.transition_status(self.tmpdir, item["id"], "in_progress")
        updated = tracker_mod.transition_status(self.tmpdir, item["id"], "completed")
        self.assertIsNotNone(updated["completed_at"])

    def test_non_terminal_state_no_completed_at(self):
        """Transitioning to non-terminal state does not set completed_at."""
        item = tracker_mod.create_item(self.tmpdir, type="task", title="Pause")
        tracker_mod.transition_status(self.tmpdir, item["id"], "in_progress")
        updated = tracker_mod.transition_status(self.tmpdir, item["id"], "paused")
        self.assertIsNone(updated["completed_at"])

    def test_transition_logs_to_status_log(self):
        """Transition creates an entry in status_log."""
        item = tracker_mod.create_item(self.tmpdir, type="task", title="Log Test")
        tracker_mod.transition_status(
            self.tmpdir, item["id"], "in_progress", reason="Starting"
        )
        history = tracker_mod.get_item_history(self.tmpdir, item["id"])
        # 1 from creation + 1 from transition
        self.assertEqual(len(history), 2)
        last = history[-1]
        self.assertEqual(last["from_status"], "created")
        self.assertEqual(last["to_status"], "in_progress")
        self.assertEqual(last["reason"], "Starting")

    def test_transition_nonexistent_item_raises(self):
        """Transitioning nonexistent item raises ValueError."""
        schema.init_db(self.tmpdir)
        with self.assertRaises(ValueError):
            tracker_mod.transition_status(self.tmpdir, "itm_nope", "in_progress")


class TestAddRelation(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_add_relation(self):
        """add_relation creates a relationship between two items."""
        item1 = tracker_mod.create_item(self.tmpdir, type="task", title="Task A")
        item2 = tracker_mod.create_item(self.tmpdir, type="task", title="Task B")
        tracker_mod.add_relation(self.tmpdir, item1["id"], item2["id"], "related")

        conn = schema.get_db(self.tmpdir)
        rows = conn.execute(
            "SELECT * FROM item_relations WHERE from_item_id = ?",
            (item1["id"],)
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["to_item_id"], item2["id"])
        self.assertEqual(rows[0]["relation"], "related")


class TestAddTags(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_add_tags(self):
        """add_tags adds tags to an existing item."""
        item = tracker_mod.create_item(self.tmpdir, type="task", title="Tag Test")
        tracker_mod.add_tags(self.tmpdir, item["id"], ["new_tag", "another"])
        fetched = tracker_mod.get_item(self.tmpdir, item["id"])
        self.assertIn("new_tag", fetched["tags"])
        self.assertIn("another", fetched["tags"])

    def test_add_tags_idempotent(self):
        """Adding the same tag twice does not duplicate it."""
        item = tracker_mod.create_item(
            self.tmpdir, type="task", title="Idem", tags=["existing"]
        )
        tracker_mod.add_tags(self.tmpdir, item["id"], ["existing", "new"])
        fetched = tracker_mod.get_item(self.tmpdir, item["id"])
        existing_count = fetched["tags"].count("existing")
        self.assertEqual(existing_count, 1)


class TestAddRelatedFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_add_related_files(self):
        """add_related_files adds file paths to an item."""
        item = tracker_mod.create_item(self.tmpdir, type="task", title="Files Test")
        tracker_mod.add_related_files(self.tmpdir, item["id"], ["a.py", "b.py"])
        fetched = tracker_mod.get_item(self.tmpdir, item["id"])
        self.assertIn("a.py", fetched["related_files"])
        self.assertIn("b.py", fetched["related_files"])


class TestAddKBRef(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_add_kb_ref(self):
        """add_kb_ref adds a KB reference to an item."""
        item = tracker_mod.create_item(self.tmpdir, type="task", title="KB Test")
        tracker_mod.add_kb_ref(self.tmpdir, item["id"], "decisions.md#section1")
        fetched = tracker_mod.get_item(self.tmpdir, item["id"])
        self.assertIn("decisions.md#section1", fetched["kb_refs"])


class TestGetActiveItems(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_filters_out_terminal_states(self):
        """get_active_items excludes completed/abandoned items."""
        item1 = tracker_mod.create_item(self.tmpdir, type="task", title="Active")
        item2 = tracker_mod.create_item(self.tmpdir, type="task", title="Done")
        tracker_mod.transition_status(self.tmpdir, item2["id"], "in_progress")
        tracker_mod.transition_status(self.tmpdir, item2["id"], "completed")

        active = tracker_mod.get_active_items(self.tmpdir)
        active_ids = [i["id"] for i in active]
        self.assertIn(item1["id"], active_ids)
        self.assertNotIn(item2["id"], active_ids)

    def test_respects_limit(self):
        """get_active_items respects the limit parameter."""
        for i in range(5):
            tracker_mod.create_item(self.tmpdir, type="task", title=f"Task {i}")
        active = tracker_mod.get_active_items(self.tmpdir, limit=2)
        self.assertEqual(len(active), 2)

    def test_sorted_by_priority_then_updated_at(self):
        """get_active_items sorts by priority DESC, then updated_at DESC."""
        low = tracker_mod.create_item(
            self.tmpdir, type="task", title="Low", priority="low"
        )
        high = tracker_mod.create_item(
            self.tmpdir, type="task", title="High", priority="high"
        )
        medium = tracker_mod.create_item(
            self.tmpdir, type="task", title="Medium", priority="medium"
        )
        active = tracker_mod.get_active_items(self.tmpdir)
        self.assertEqual(active[0]["id"], high["id"])


class TestGetIncomplete(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_returns_non_terminal(self):
        """get_incomplete returns only non-terminal items."""
        item1 = tracker_mod.create_item(self.tmpdir, type="task", title="Open")
        item2 = tracker_mod.create_item(self.tmpdir, type="question", title="Answered")
        tracker_mod.transition_status(self.tmpdir, item2["id"], "answered")

        incomplete = tracker_mod.get_incomplete(self.tmpdir)
        ids = [i["id"] for i in incomplete]
        self.assertIn(item1["id"], ids)
        self.assertNotIn(item2["id"], ids)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create some items for searching
        self.task = tracker_mod.create_item(
            self.tmpdir, type="task", title="Auth login fix",
            tags=["auth", "backend"], related_files=["auth.py"]
        )
        self.question = tracker_mod.create_item(
            self.tmpdir, type="question", title="API design question",
            tags=["api"]
        )
        self.maint = tracker_mod.create_item(
            self.tmpdir, type="maintenance", title="Upgrade dependencies",
            tags=["deps"]
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_search_by_type(self):
        """Search by type returns only that type."""
        results = tracker_mod.search(self.tmpdir, type="task")
        for r in results:
            self.assertEqual(r["type"], "task")
        self.assertTrue(len(results) >= 1)

    def test_search_by_status(self):
        """Search by status returns only items with that status."""
        results = tracker_mod.search(self.tmpdir, status="created")
        for r in results:
            self.assertEqual(r["status"], "created")

    def test_search_by_tags(self):
        """Search by tags returns items having all specified tags."""
        results = tracker_mod.search(self.tmpdir, tags=["auth"])
        ids = [r["id"] for r in results]
        self.assertIn(self.task["id"], ids)
        self.assertNotIn(self.question["id"], ids)

    def test_search_by_text_query(self):
        """Search by query does LIKE on title."""
        results = tracker_mod.search(self.tmpdir, query="login")
        ids = [r["id"] for r in results]
        self.assertIn(self.task["id"], ids)
        self.assertNotIn(self.maint["id"], ids)

    def test_search_by_date_range(self):
        """Search by after/before date range."""
        # All items were just created, so after yesterday should include all
        yesterday = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        results = tracker_mod.search(self.tmpdir, after=yesterday)
        self.assertEqual(len(results), 3)

        # Before yesterday should include none
        two_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=2)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        results = tracker_mod.search(self.tmpdir, before=two_days_ago)
        self.assertEqual(len(results), 0)

    def test_search_multi_criteria(self):
        """Search with multiple criteria uses AND logic."""
        results = tracker_mod.search(
            self.tmpdir, type="task", tags=["auth"], query="login"
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.task["id"])


class TestGetItemHistory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_returns_status_log_entries(self):
        """get_item_history returns all status transitions in order."""
        item = tracker_mod.create_item(self.tmpdir, type="task", title="History")
        tracker_mod.transition_status(self.tmpdir, item["id"], "in_progress")
        tracker_mod.transition_status(self.tmpdir, item["id"], "paused")

        history = tracker_mod.get_item_history(self.tmpdir, item["id"])
        self.assertEqual(len(history), 3)  # creation + 2 transitions
        self.assertIsNone(history[0]["from_status"])
        self.assertEqual(history[0]["to_status"], "created")
        self.assertEqual(history[1]["to_status"], "in_progress")
        self.assertEqual(history[2]["to_status"], "paused")


class TestSyncWorkflowStatus(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_sync_from_state_dict(self):
        """sync_workflow_status updates tracker item from state dict."""
        # First create an item with a workflow_id
        item = tracker_mod.create_item(
            self.tmpdir, type="task", title="Sync Test",
            workflow_id="wf_sync1"
        )
        # Transition to in_progress (required before completed)
        tracker_mod.transition_status(self.tmpdir, item["id"], "in_progress")

        # Now sync with a completed state
        state = {
            "workflow_id": "wf_sync1",
            "status": "completed",
        }
        tracker_mod.sync_workflow_status(self.tmpdir, state=state)

        # Verify the item was updated
        updated = tracker_mod.get_item(self.tmpdir, item["id"])
        self.assertEqual(updated["status"], "completed")
        self.assertIsNotNone(updated["completed_at"])

    def test_sync_no_workflow_id_returns_none(self):
        """sync_workflow_status does nothing when state has no workflow_id."""
        schema.init_db(self.tmpdir)
        state = {"status": "completed"}
        # Should not raise
        tracker_mod.sync_workflow_status(self.tmpdir, state=state)

    def test_sync_same_status_no_op(self):
        """sync_workflow_status does nothing when status already matches."""
        item = tracker_mod.create_item(
            self.tmpdir, type="task", title="NoChange",
            workflow_id="wf_noop"
        )
        state = {
            "workflow_id": "wf_noop",
            "status": "in_progress",  # maps to created->in_progress? No, maps to "in_progress"
        }
        # Item is "created", state maps to "in_progress" which is different
        # But for same status, let's use a direct test
        # Create item already in matching status
        tracker_mod.transition_status(self.tmpdir, item["id"], "in_progress")
        state = {"workflow_id": "wf_noop", "status": "in_progress"}
        # This should be a no-op since status matches
        tracker_mod.sync_workflow_status(self.tmpdir, state=state)
        fetched = tracker_mod.get_item(self.tmpdir, item["id"])
        self.assertEqual(fetched["status"], "in_progress")


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker_script = os.path.join(
            os.path.abspath(SCRIPTS_DIR), "tracker.py"
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _run_cli(self, args):
        """Run tracker.py CLI and return parsed JSON output."""
        result = subprocess.run(
            [sys.executable, self.tracker_script] + args,
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        return result

    def test_cli_init(self):
        """CLI init subcommand creates database and returns session_id."""
        result = self._run_cli(["init"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["session_id"].startswith("ses_"))

    def test_cli_create(self):
        """CLI create subcommand creates an item."""
        self._run_cli(["init"])
        result = self._run_cli([
            "create", "--type", "task", "--title", "CLI Task",
            "--priority", "high", "--tags", "cli,test"
        ])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["type"], "task")
        self.assertEqual(data["title"], "CLI Task")
        self.assertEqual(data["priority"], "high")
        self.assertIn("cli", data["tags"])
        self.assertIn("test", data["tags"])

    def test_cli_list_active(self):
        """CLI list --active shows only non-terminal items."""
        self._run_cli(["init"])
        self._run_cli(["create", "--type", "task", "--title", "Active Task"])
        result = self._run_cli(["list", "--active"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) >= 1)
        self.assertEqual(data[0]["title"], "Active Task")

    def test_cli_context(self):
        """CLI context subcommand returns session context from tracker_awareness."""
        self._run_cli(["init"])
        self._run_cli(["create", "--type", "task", "--title", "Context Test Task"])
        result = self._run_cli(["context"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("summary", data)
        self.assertIn("active_items", data)
        self.assertIn("warnings", data)
        self.assertIn("recent_completed", data)
        # Should have at least the task we just created
        self.assertTrue(len(data["active_items"]) >= 1)

    def test_cli_context_empty_db(self):
        """CLI context subcommand works with empty database."""
        self._run_cli(["init"])
        result = self._run_cli(["context"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("summary", data)
        self.assertEqual(data["active_items"], [])

    def test_cli_context_no_db(self):
        """CLI context subcommand returns valid JSON even when no DB exists."""
        result = self._run_cli(["context"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        # Should return consistent shape regardless of DB state
        self.assertIn("summary", data)
        self.assertIn("active_items", data)
        self.assertIn("warnings", data)
        self.assertIn("recent_completed", data)


# =====================================================================
# tracker_awareness.py tests
# =====================================================================


class TestGetSessionContext(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_returns_correct_structure(self):
        """get_session_context returns dict with expected keys."""
        schema.init_db(self.tmpdir)
        tracker_mod.create_item(self.tmpdir, type="task", title="Active Task")

        ctx = awareness.get_session_context(self.tmpdir)
        self.assertIn("summary", ctx)
        self.assertIn("active_items", ctx)
        self.assertIn("warnings", ctx)
        self.assertIn("recent_completed", ctx)

    def test_handles_empty_db(self):
        """get_session_context with no items returns valid structure."""
        schema.init_db(self.tmpdir)
        ctx = awareness.get_session_context(self.tmpdir)
        self.assertEqual(ctx["active_items"], [])
        self.assertEqual(ctx["warnings"], [])
        self.assertEqual(ctx["recent_completed"], [])

    def test_handles_no_db(self):
        """get_session_context with no tracker.db returns minimal dict."""
        ctx = awareness.get_session_context(self.tmpdir)
        self.assertEqual(ctx["summary"], "No tracker database found")
        self.assertEqual(ctx["active_items"], [])


class TestGetWarnings(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _create_stale_item(self, type, title, status, days_ago):
        """Helper: create an item and backdate its updated_at."""
        item = tracker_mod.create_item(self.tmpdir, type=type, title=title)
        # Transition to desired status if needed
        if type == "task" and status == "in_progress":
            tracker_mod.transition_status(self.tmpdir, item["id"], "in_progress")
        elif type == "task" and status == "paused":
            tracker_mod.transition_status(self.tmpdir, item["id"], "in_progress")
            tracker_mod.transition_status(self.tmpdir, item["id"], "paused")
        elif type == "task" and status == "blocked":
            tracker_mod.transition_status(self.tmpdir, item["id"], "in_progress")
            tracker_mod.transition_status(self.tmpdir, item["id"], "blocked")

        # Backdate updated_at
        old_date = (
            datetime.now(timezone.utc) - timedelta(days=days_ago)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = schema.get_db(self.tmpdir)
        conn.execute(
            "UPDATE items SET updated_at = ? WHERE id = ?",
            (old_date, item["id"])
        )
        conn.commit()
        conn.close()
        return item

    def test_stale_in_progress_warning(self):
        """Task in_progress > 3 days triggers stale warning."""
        self._create_stale_item("task", "Stale Task", "in_progress", 5)
        warnings = awareness.get_warnings(self.tmpdir)
        messages = [w["message"] for w in warnings]
        self.assertTrue(any("Stale Task" in m and "no progress" in m for m in messages))

    def test_long_paused_warning(self):
        """Task paused > 7 days triggers warning."""
        self._create_stale_item("task", "Paused Task", "paused", 10)
        warnings = awareness.get_warnings(self.tmpdir)
        messages = [w["message"] for w in warnings]
        self.assertTrue(any("Paused Task" in m and "paused" in m for m in messages))

    def test_long_blocked_warning(self):
        """Task blocked > 5 days triggers error-severity warning."""
        self._create_stale_item("task", "Blocked Task", "blocked", 7)
        warnings = awareness.get_warnings(self.tmpdir)
        blocked_warnings = [w for w in warnings if "Blocked Task" in w["message"]]
        self.assertTrue(len(blocked_warnings) >= 1)
        self.assertEqual(blocked_warnings[0]["severity"], "error")

    def test_too_many_concurrent_tasks(self):
        """More than 3 tasks in_progress triggers count warning."""
        for i in range(4):
            item = tracker_mod.create_item(
                self.tmpdir, type="task", title=f"Concurrent {i}"
            )
            tracker_mod.transition_status(self.tmpdir, item["id"], "in_progress")

        warnings = awareness.get_warnings(self.tmpdir)
        messages = [w["message"] for w in warnings]
        self.assertTrue(any("4 tasks in_progress simultaneously" in m for m in messages))

    def test_no_warnings_healthy_state(self):
        """No warnings when all items are fresh and few."""
        tracker_mod.create_item(self.tmpdir, type="task", title="Fresh Task")
        warnings = awareness.get_warnings(self.tmpdir)
        self.assertEqual(len(warnings), 0)

    def test_max_3_warnings(self):
        """get_warnings returns at most 3 warnings."""
        # Create many stale items to trigger multiple warnings
        for i in range(6):
            self._create_stale_item("task", f"Stale {i}", "in_progress", 10)
        warnings = awareness.get_warnings(self.tmpdir)
        self.assertLessEqual(len(warnings), 3)

    def test_no_db_returns_empty(self):
        """get_warnings returns empty list when no db exists."""
        warnings = awareness.get_warnings(self.tmpdir)
        self.assertEqual(warnings, [])


class TestFormatContextForHook(unittest.TestCase):
    def test_formats_correctly_with_active_items(self):
        """format_context_for_hook includes active items line."""
        context = {
            "summary": "1 in progress",
            "active_items": [
                {
                    "type": "task",
                    "title": "OAuth login",
                    "status": "in_progress",
                    "priority": "high",
                    "updated_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                }
            ],
            "warnings": [
                {"severity": "warning", "message": "Task stale for 3d"},
            ],
            "recent_completed": [
                {"title": "Setup CI"},
            ],
        }
        output = awareness.format_context_for_hook(context)
        self.assertIn("[Coregy Tracker] Active:", output)
        self.assertIn("[HIGH]", output)
        self.assertIn("OAuth login", output)
        self.assertIn("Warnings:", output)
        self.assertIn("Task stale for 3d", output)
        self.assertIn("Recent:", output)
        self.assertIn("Setup CI", output)

    def test_empty_context_returns_empty_string(self):
        """format_context_for_hook returns empty string when nothing to report."""
        context = {
            "summary": "No active items",
            "active_items": [],
            "warnings": [],
            "recent_completed": [],
        }
        output = awareness.format_context_for_hook(context)
        self.assertEqual(output, "")

    def test_no_active_but_recent_completed(self):
        """format_context_for_hook shows 'No active items' when only recent exists."""
        context = {
            "summary": "no active items, 1 item completed recently",
            "active_items": [],
            "warnings": [],
            "recent_completed": [{"title": "Done thing"}],
        }
        output = awareness.format_context_for_hook(context)
        self.assertIn("[Coregy Tracker] No active items", output)
        self.assertIn("Recent:", output)


class TestDaysSince(unittest.TestCase):
    def test_correct_calculation(self):
        """_days_since returns correct number of days."""
        three_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=3)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = awareness._days_since(three_days_ago)
        self.assertEqual(result, 3)

    def test_today_returns_zero(self):
        """_days_since for now returns 0."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = awareness._days_since(now)
        self.assertEqual(result, 0)

    def test_empty_string_returns_zero(self):
        """_days_since for empty string returns 0."""
        result = awareness._days_since("")
        self.assertEqual(result, 0)

    def test_date_only_format(self):
        """_days_since handles YYYY-MM-DD format."""
        two_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=2)
        ).strftime("%Y-%m-%d")
        result = awareness._days_since(two_days_ago)
        self.assertEqual(result, 2)


class TestFormatAge(unittest.TestCase):
    def test_today(self):
        """_format_age(0) returns 'today'."""
        self.assertEqual(awareness._format_age(0), "today")

    def test_days(self):
        """_format_age for 1-6 days returns 'Nd'."""
        self.assertEqual(awareness._format_age(1), "1d")
        self.assertEqual(awareness._format_age(6), "6d")

    def test_weeks(self):
        """_format_age for 7-29 days returns 'Nw'."""
        self.assertEqual(awareness._format_age(7), "1w")
        self.assertEqual(awareness._format_age(14), "2w")
        self.assertEqual(awareness._format_age(20), "2w")

    def test_months(self):
        """_format_age for 30+ days returns 'Nmo'."""
        self.assertEqual(awareness._format_age(30), "1mo")
        self.assertEqual(awareness._format_age(60), "2mo")
        self.assertEqual(awareness._format_age(90), "3mo")


# =====================================================================
# Checkpoint tests
# =====================================================================


class TestCheckpointSchema(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_checkpoints_table_created(self):
        """init_db creates the checkpoints table."""
        schema.init_db(self.tmpdir)
        db = os.path.join(self.tmpdir, ".coregy", "tracker.db")
        conn = sqlite3.connect(db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
        )
        self.assertIsNotNone(cursor.fetchone())
        conn.close()

    def test_checkpoints_unique_index(self):
        """Unique index on (workflow_id, agent) prevents duplicates."""
        schema.init_db(self.tmpdir)
        db = os.path.join(self.tmpdir, ".coregy", "tracker.db")
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO checkpoints (id, workflow_id, agent, phase, updated_at) "
            "VALUES ('c1', 'wf1', 'backend', 'BUILD', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO checkpoints (id, workflow_id, agent, phase, updated_at) "
                "VALUES ('c2', 'wf1', 'backend', 'BUILD', '2026-01-01T00:00:00Z')"
            )
        conn.close()


class TestSaveCheckpoint(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_save_checkpoint_basic(self):
        """save_checkpoint creates a checkpoint record."""
        result = tracker_mod.save_checkpoint(
            self.tmpdir,
            workflow_id="feat-auth-20260411",
            agent="code-reviewer",
            phase="VERIFY",
            total_items=10,
            completed_items=6,
            items=[{"id": "auth.py", "status": "done", "summary": "OK"}],
            partial_output="Reviewed 6 files",
            resume_hint="Continue from models/order.py",
        )
        self.assertEqual(result["workflow_id"], "feat-auth-20260411")
        self.assertEqual(result["agent"], "code-reviewer")
        self.assertEqual(result["total_items"], 10)
        self.assertEqual(result["completed_items"], 6)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["resume_hint"], "Continue from models/order.py")

    def test_save_checkpoint_upsert(self):
        """save_checkpoint updates existing checkpoint for same agent."""
        tracker_mod.save_checkpoint(
            self.tmpdir, "wf1", "backend", "BUILD",
            total_items=5, completed_items=2,
            resume_hint="item 3",
        )
        result = tracker_mod.save_checkpoint(
            self.tmpdir, "wf1", "backend", "BUILD",
            total_items=5, completed_items=4,
            resume_hint="item 5",
        )
        self.assertEqual(result["completed_items"], 4)
        self.assertEqual(result["resume_hint"], "item 5")

        # Verify only one record exists
        loaded = tracker_mod.load_checkpoint(self.tmpdir, "wf1", "backend")
        self.assertEqual(loaded["completed_items"], 4)


class TestLoadCheckpoint(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_load_nonexistent(self):
        """load_checkpoint returns None when no checkpoint exists."""
        result = tracker_mod.load_checkpoint(self.tmpdir, "wf1", "backend")
        self.assertIsNone(result)

    def test_load_existing(self):
        """load_checkpoint returns saved checkpoint data."""
        items = [
            {"id": "file1.py", "status": "done", "summary": "OK"},
            {"id": "file2.py", "status": "pending", "summary": ""},
        ]
        tracker_mod.save_checkpoint(
            self.tmpdir, "wf1", "code-reviewer", "VERIFY",
            total_items=2, completed_items=1,
            items=items,
            partial_output="## Review\n- file1.py: OK",
            resume_hint="Review file2.py next",
        )
        loaded = tracker_mod.load_checkpoint(self.tmpdir, "wf1", "code-reviewer")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["total_items"], 2)
        self.assertEqual(loaded["completed_items"], 1)
        self.assertEqual(len(loaded["items"]), 2)
        self.assertEqual(loaded["items"][0]["status"], "done")
        self.assertEqual(loaded["partial_output"], "## Review\n- file1.py: OK")
        self.assertEqual(loaded["resume_hint"], "Review file2.py next")

    def test_load_no_db(self):
        """load_checkpoint returns None when tracker.db doesn't exist."""
        empty_dir = tempfile.mkdtemp()
        result = tracker_mod.load_checkpoint(empty_dir, "wf1", "backend")
        self.assertIsNone(result)
        shutil.rmtree(empty_dir)


class TestLoadWorkflowCheckpoints(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_load_multiple(self):
        """load_workflow_checkpoints returns all checkpoints for a workflow."""
        tracker_mod.save_checkpoint(self.tmpdir, "wf1", "backend", "BUILD")
        tracker_mod.save_checkpoint(self.tmpdir, "wf1", "frontend", "BUILD")
        tracker_mod.save_checkpoint(self.tmpdir, "wf2", "backend", "BUILD")

        results = tracker_mod.load_workflow_checkpoints(self.tmpdir, "wf1")
        self.assertEqual(len(results), 2)
        agents = {r["agent"] for r in results}
        self.assertEqual(agents, {"backend", "frontend"})

    def test_empty_workflow(self):
        """load_workflow_checkpoints returns empty list for unknown workflow."""
        schema.init_db(self.tmpdir)
        results = tracker_mod.load_workflow_checkpoints(self.tmpdir, "nonexistent")
        self.assertEqual(results, [])


class TestClearCheckpoint(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_clear_existing(self):
        """clear_checkpoint removes the checkpoint and returns True."""
        tracker_mod.save_checkpoint(self.tmpdir, "wf1", "backend", "BUILD")
        result = tracker_mod.clear_checkpoint(self.tmpdir, "wf1", "backend")
        self.assertTrue(result)

        loaded = tracker_mod.load_checkpoint(self.tmpdir, "wf1", "backend")
        self.assertIsNone(loaded)

    def test_clear_nonexistent(self):
        """clear_checkpoint returns False when no checkpoint exists."""
        schema.init_db(self.tmpdir)
        result = tracker_mod.clear_checkpoint(self.tmpdir, "wf1", "backend")
        self.assertFalse(result)

    def test_clear_workflow_checkpoints(self):
        """clear_workflow_checkpoints removes all checkpoints for a workflow."""
        tracker_mod.save_checkpoint(self.tmpdir, "wf1", "backend", "BUILD")
        tracker_mod.save_checkpoint(self.tmpdir, "wf1", "frontend", "BUILD")
        tracker_mod.save_checkpoint(self.tmpdir, "wf2", "backend", "BUILD")

        count = tracker_mod.clear_workflow_checkpoints(self.tmpdir, "wf1")
        self.assertEqual(count, 2)

        # wf1 checkpoints gone
        self.assertEqual(tracker_mod.load_workflow_checkpoints(self.tmpdir, "wf1"), [])
        # wf2 still exists
        self.assertEqual(len(tracker_mod.load_workflow_checkpoints(self.tmpdir, "wf2")), 1)


class TestCheckpointCLI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, ".coregy"), exist_ok=True)
        schema.init_db(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _run_cli(self, *args):
        tracker_py = os.path.join(SCRIPTS_DIR, "tracker.py")
        result = subprocess.run(
            [sys.executable, tracker_py] + list(args),
            capture_output=True, text=True, cwd=self.tmpdir
        )
        return result

    def test_checkpoint_save_and_load(self):
        """CLI checkpoint-save and checkpoint-load round-trip."""
        result = self._run_cli(
            "checkpoint-save",
            "--workflow-id", "wf-test",
            "--agent", "backend",
            "--phase", "BUILD",
            "--total-items", "5",
            "--completed-items", "3",
            "--resume-hint", "Continue from item 4",
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["agent"], "backend")
        self.assertEqual(data["completed_items"], 3)

        result = self._run_cli(
            "checkpoint-load",
            "--workflow-id", "wf-test",
            "--agent", "backend",
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["resume_hint"], "Continue from item 4")

    def test_checkpoint_load_nonexistent(self):
        """CLI checkpoint-load returns no_checkpoint message."""
        result = self._run_cli(
            "checkpoint-load",
            "--workflow-id", "wf-test",
            "--agent", "nonexistent",
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "no_checkpoint")

    def test_checkpoint_list(self):
        """CLI checkpoint-list shows all checkpoints for a workflow."""
        self._run_cli("checkpoint-save", "--workflow-id", "wf1",
                       "--agent", "a1", "--phase", "BUILD")
        self._run_cli("checkpoint-save", "--workflow-id", "wf1",
                       "--agent", "a2", "--phase", "VERIFY")
        result = self._run_cli("checkpoint-list", "--workflow-id", "wf1")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(len(data), 2)

    def test_checkpoint_clear_single(self):
        """CLI checkpoint-clear with --agent clears one checkpoint."""
        self._run_cli("checkpoint-save", "--workflow-id", "wf1",
                       "--agent", "backend", "--phase", "BUILD")
        result = self._run_cli("checkpoint-clear", "--workflow-id", "wf1",
                                "--agent", "backend")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertTrue(data["deleted"])

    def test_checkpoint_clear_all(self):
        """CLI checkpoint-clear without --agent clears all."""
        self._run_cli("checkpoint-save", "--workflow-id", "wf1",
                       "--agent", "a1", "--phase", "BUILD")
        self._run_cli("checkpoint-save", "--workflow-id", "wf1",
                       "--agent", "a2", "--phase", "VERIFY")
        result = self._run_cli("checkpoint-clear", "--workflow-id", "wf1")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["deleted_count"], 2)


if __name__ == "__main__":
    unittest.main()
