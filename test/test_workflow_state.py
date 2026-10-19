"""Tests for workflow state machine (state.py)."""
import json
import os
import sys
import tempfile
import unittest

# Add scripts dir to path
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

from state import (
    VALID_MODES,
    init_workflow,
    load_state,
    start_agent,
    complete_agent,
    skip_agent,
    complete_workflow,
    abort_workflow,
    get_next_agent,
    confirm_spec,
    get_execution_mode,
    set_execution_mode,
    create_feature_log,
    append_feature_log,
    finalize_feature_log,
)


class TestInitWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name
        os.makedirs(os.path.join(self.cwd, ".coregy"), exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_init_workflow(self):
        """Creates state.json with correct structure."""
        phases = {
            "THINK": ["researcher", "architect"],
            "BUILD": ["backend", "frontend"],
            "VERIFY": ["unit-tester", "code-reviewer"],
            "SHIP": ["devops"],
        }
        state = init_workflow(self.cwd, "Add user auth", "new-feature", phases)

        self.assertEqual(state["feature"], "Add user auth")
        self.assertEqual(state["type"], "new-feature")
        self.assertEqual(state["status"], "in_progress")
        self.assertFalse(state["spec_confirmed"])
        self.assertIsNone(state["spec_file"])
        self.assertEqual(state["log_file"], "log-add-user-auth.md")
        self.assertEqual(state["phase_order"], ["THINK", "BUILD", "VERIFY", "SHIP"])
        self.assertEqual(state["phases"]["THINK"]["agents"], ["researcher", "architect"])
        self.assertEqual(state["phases"]["THINK"]["completed"], [])
        self.assertIsNone(state["phases"]["THINK"]["active"])
        self.assertEqual(state["agent_log"], [])
        self.assertIn("created_at", state)
        self.assertIn("updated_at", state)

    def test_init_workflow_with_spec(self):
        """Creates state.json with spec_confirmed and spec_file."""
        phases = {"THINK": ["researcher"]}
        state = init_workflow(
            self.cwd, "OAuth2 login", "new-feature", phases,
            spec_confirmed=True, spec_file="spec-oauth2-login.md"
        )
        self.assertTrue(state["spec_confirmed"])
        self.assertEqual(state["spec_file"], "spec-oauth2-login.md")

        # Verify file was written
        path = os.path.join(self.cwd, ".coregy", "state.json")
        self.assertTrue(os.path.isfile(path))

    def test_workflow_id_generation(self):
        """ID is generated from feature + date."""
        phases = {"THINK": ["researcher"]}
        state = init_workflow(self.cwd, "Add user auth", "new-feature", phases)
        self.assertTrue(state["workflow_id"].startswith("feat-add-user-auth-"))
        # Contains date portion
        self.assertRegex(state["workflow_id"], r"feat-add-user-auth-\d{8}")

    def test_duplicate_init_overwrites(self):
        """Re-init replaces existing state."""
        phases = {"THINK": ["researcher"]}
        state1 = init_workflow(self.cwd, "Feature A", "new-feature", phases)
        state2 = init_workflow(self.cwd, "Feature B", "bug-fix", phases)
        self.assertEqual(state2["feature"], "Feature B")
        self.assertEqual(state2["type"], "bug-fix")

        loaded = load_state(self.cwd)
        self.assertEqual(loaded["feature"], "Feature B")

    def test_init_default_execution_mode(self):
        """Default execution mode is 'guided'."""
        phases = {"THINK": ["researcher"]}
        state = init_workflow(self.cwd, "Test", "new-feature", phases)
        self.assertEqual(state["execution_mode"], "guided")

    def test_init_auto_mode(self):
        """Can init with auto execution mode."""
        phases = {"THINK": ["researcher"]}
        state = init_workflow(
            self.cwd, "Test", "new-feature", phases, execution_mode="auto"
        )
        self.assertEqual(state["execution_mode"], "auto")

    def test_init_manual_mode(self):
        """Can init with manual execution mode."""
        phases = {"THINK": ["researcher"]}
        state = init_workflow(
            self.cwd, "Test", "new-feature", phases, execution_mode="manual"
        )
        self.assertEqual(state["execution_mode"], "manual")

    def test_init_invalid_mode(self):
        """Invalid execution mode raises ValueError."""
        phases = {"THINK": ["researcher"]}
        with self.assertRaises(ValueError):
            init_workflow(
                self.cwd, "Test", "new-feature", phases, execution_mode="turbo"
            )

    def test_partial_phases(self):
        """Only specified phases are included."""
        phases = {"THINK": ["researcher"], "BUILD": ["backend"]}
        state = init_workflow(self.cwd, "API endpoint", "api-endpoint", phases)
        self.assertEqual(state["phase_order"], ["THINK", "BUILD"])
        self.assertNotIn("VERIFY", state["phases"])


class TestLoadState(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_state_no_file(self):
        """Returns None when no state.json exists."""
        self.assertIsNone(load_state(self.cwd))

    def test_load_state_existing(self):
        """Reads state correctly."""
        phases = {"THINK": ["researcher"]}
        init_workflow(self.cwd, "Test feature", "new-feature", phases)
        state = load_state(self.cwd)
        self.assertIsNotNone(state)
        self.assertEqual(state["feature"], "Test feature")


class TestStartAgent(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name
        init_workflow(self.cwd, "Test", "new-feature", {
            "THINK": ["researcher", "architect"],
            "BUILD": ["backend"],
        })

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_start_agent(self):
        """Sets active agent and logs start time."""
        state, checkpoint = start_agent(self.cwd, "researcher")
        self.assertIsNone(checkpoint)
        self.assertEqual(state["phases"]["THINK"]["active"], "researcher")
        self.assertEqual(len(state["agent_log"]), 1)
        self.assertEqual(state["agent_log"][0]["agent"], "researcher")
        self.assertEqual(state["agent_log"][0]["phase"], "THINK")
        self.assertIsNotNone(state["agent_log"][0]["started_at"])
        self.assertIsNone(state["agent_log"][0]["completed_at"])

    def test_start_unknown_agent(self):
        """Raises ValueError for unknown agent."""
        with self.assertRaises(ValueError):
            start_agent(self.cwd, "nonexistent-agent")

    def test_phase_validation_warning(self):
        """Warns if BUILD starts before THINK has progress."""
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            start_agent(self.cwd, "backend")

        output = f.getvalue()
        self.assertIn("Warning", output)
        self.assertIn("THINK", output)


class TestCompleteAgent(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name
        init_workflow(self.cwd, "Test", "new-feature", {
            "THINK": ["researcher", "architect"],
            "BUILD": ["backend"],
        })
        start_agent(self.cwd, "researcher")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_complete_agent(self):
        """Marks completed and logs end time."""
        state = complete_agent(self.cwd, "researcher", "Researched OAuth2", ["decisions.md"])
        p = state["phases"]["THINK"]
        self.assertIn("researcher", p["completed"])
        self.assertIsNone(p["active"])

        log = state["agent_log"][0]
        self.assertIsNotNone(log["completed_at"])
        self.assertEqual(log["output_summary"], "Researched OAuth2")
        self.assertEqual(log["kb_files_modified"], ["decisions.md"])

    def test_complete_agent_advances_phase(self):
        """Next agent is in next phase when current phase is done."""
        complete_agent(self.cwd, "researcher")
        start_agent(self.cwd, "architect")
        state = complete_agent(self.cwd, "architect")

        # All THINK agents complete — next should be BUILD
        nxt = get_next_agent(state)
        self.assertEqual(nxt, ("BUILD", "backend"))


class TestSkipAgent(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name
        init_workflow(self.cwd, "Test", "new-feature", {
            "THINK": ["researcher", "architect"],
            "BUILD": ["backend"],
        })

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_skip_agent(self):
        """Marks agent as skipped."""
        state = skip_agent(self.cwd, "researcher")
        self.assertIn("researcher", state["phases"]["THINK"]["skipped"])
        self.assertNotIn("researcher", state["phases"]["THINK"]["completed"])


class TestGetNextAgent(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_get_next_agent_first(self):
        """Returns first agent when nothing started."""
        state = init_workflow(self.cwd, "Test", "new-feature", {
            "THINK": ["researcher", "architect"],
            "BUILD": ["backend"],
        })
        nxt = get_next_agent(state)
        self.assertEqual(nxt, ("THINK", "researcher"))

    def test_get_next_agent_mid_workflow(self):
        """Returns correct next agent mid-workflow."""
        init_workflow(self.cwd, "Test", "new-feature", {
            "THINK": ["researcher", "architect"],
            "BUILD": ["backend"],
        })
        start_agent(self.cwd, "researcher")
        state = complete_agent(self.cwd, "researcher")
        nxt = get_next_agent(state)
        self.assertEqual(nxt, ("THINK", "architect"))

    def test_get_next_agent_all_done(self):
        """Returns None when all agents are done."""
        init_workflow(self.cwd, "Test", "new-feature", {
            "THINK": ["researcher"],
        })
        start_agent(self.cwd, "researcher")
        state = complete_agent(self.cwd, "researcher")
        nxt = get_next_agent(state)
        self.assertIsNone(nxt)

    def test_get_next_agent_skipped(self):
        """Skipped agents are skipped in next calculation."""
        init_workflow(self.cwd, "Test", "new-feature", {
            "THINK": ["researcher", "architect"],
            "BUILD": ["backend"],
        })
        skip_agent(self.cwd, "researcher")
        state = load_state(self.cwd)
        nxt = get_next_agent(state)
        self.assertEqual(nxt, ("THINK", "architect"))

    def test_get_next_agent_none_state(self):
        """Returns None for None state."""
        self.assertIsNone(get_next_agent(None))


class TestWorkflowLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_complete_workflow(self):
        """Sets status to completed."""
        init_workflow(self.cwd, "Test", "new-feature", {"THINK": ["researcher"]})
        state = complete_workflow(self.cwd)
        self.assertEqual(state["status"], "completed")

    def test_abort_workflow(self):
        """Sets status to aborted."""
        init_workflow(self.cwd, "Test", "new-feature", {"THINK": ["researcher"]})
        state = abort_workflow(self.cwd)
        self.assertEqual(state["status"], "aborted")

    def test_complete_workflow_no_state(self):
        """Raises error when no state exists."""
        with self.assertRaises(FileNotFoundError):
            complete_workflow(self.cwd)

    def test_full_workflow_lifecycle(self):
        """End-to-end: init → start → complete → next → complete workflow."""
        phases = {
            "THINK": ["researcher"],
            "BUILD": ["backend"],
        }
        init_workflow(self.cwd, "Auth feature", "new-feature", phases)

        # Start and complete researcher
        start_agent(self.cwd, "researcher")
        complete_agent(self.cwd, "researcher", "Done research")

        # Start and complete backend
        start_agent(self.cwd, "backend")
        state = complete_agent(self.cwd, "backend", "Built API")

        # No more agents
        self.assertIsNone(get_next_agent(state))

        # Complete workflow
        state = complete_workflow(self.cwd)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(len(state["agent_log"]), 2)


class TestConfirmSpec(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name
        os.makedirs(os.path.join(self.cwd, ".coregy"), exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_confirm_spec(self):
        """Sets spec_confirmed and spec_file."""
        phases = {"THINK": ["researcher"], "BUILD": ["backend"]}
        init_workflow(self.cwd, "Auth feature", "new-feature", phases)

        state = confirm_spec(self.cwd, "spec-auth-feature.md")
        self.assertTrue(state["spec_confirmed"])
        self.assertEqual(state["spec_file"], "spec-auth-feature.md")

        # Persisted to disk
        loaded = load_state(self.cwd)
        self.assertTrue(loaded["spec_confirmed"])
        self.assertEqual(loaded["spec_file"], "spec-auth-feature.md")

    def test_confirm_spec_no_workflow(self):
        """Raises error when no state exists."""
        with self.assertRaises(FileNotFoundError):
            confirm_spec(self.cwd, "spec-test.md")

    def test_confirm_spec_preserves_other_fields(self):
        """Other state fields remain unchanged."""
        phases = {"THINK": ["researcher"]}
        init_workflow(self.cwd, "Test", "bug-fix", phases)
        start_agent(self.cwd, "researcher")

        state = confirm_spec(self.cwd, "spec-test.md")
        self.assertEqual(state["feature"], "Test")
        self.assertEqual(state["type"], "bug-fix")
        self.assertEqual(state["status"], "in_progress")
        self.assertEqual(state["phases"]["THINK"]["active"], "researcher")


class TestFeatureLog(unittest.TestCase):
    """Test feature log creation, appending, and finalization."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name
        os.makedirs(os.path.join(self.cwd, ".coregy", "knowledge"), exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_init_workflow_creates_log_file_field(self):
        """init_workflow auto-generates log_file from feature name."""
        phases = {"THINK": ["researcher"]}
        state = init_workflow(self.cwd, "OAuth2 Login", "new-feature", phases)
        self.assertEqual(state["log_file"], "log-oauth2-login.md")

    def test_init_workflow_custom_log_file(self):
        """init_workflow accepts custom log_file."""
        phases = {"THINK": ["researcher"]}
        state = init_workflow(self.cwd, "Test", "bug-fix", phases,
                              log_file="log-custom.md")
        self.assertEqual(state["log_file"], "log-custom.md")

    def test_create_feature_log(self):
        """Creates log file with correct structure."""
        phases = {"THINK": ["researcher"]}
        init_workflow(self.cwd, "OAuth2 Login", "new-feature", phases,
                      spec_file="spec-oauth2-login.md")
        path = create_feature_log(self.cwd, "OAuth2 Login", "new-feature",
                                  spec_file="spec-oauth2-login.md",
                                  log_file="log-oauth2-login.md")

        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            content = f.read()

        self.assertIn("# Feature Log: OAuth2 Login", content)
        self.assertIn("tags: [log, new-feature]", content)
        self.assertIn("status: in_progress", content)
        self.assertIn("## Spec", content)
        self.assertIn("spec-oauth2-login.md", content)
        self.assertIn("## Agent Work", content)

    def test_append_feature_log(self):
        """Appends structured agent entry to log."""
        phases = {"THINK": ["researcher"], "BUILD": ["backend"]}
        init_workflow(self.cwd, "Test Feature", "new-feature", phases)
        create_feature_log(self.cwd, "Test Feature", "new-feature",
                           log_file="log-test-feature.md")

        append_feature_log(
            self.cwd, "researcher", "THINK",
            summary="Researched OAuth2 providers",
            files_created=["docs/oauth2-research.md"],
            kb_updated=["decisions.md"],
            decisions=["Use Auth0 for managed auth"],
            log_file="log-test-feature.md",
        )

        path = os.path.join(self.cwd, ".coregy", "knowledge", "log-test-feature.md")
        with open(path) as f:
            content = f.read()

        self.assertIn("### researcher (THINK)", content)
        self.assertIn("Researched OAuth2 providers", content)
        self.assertIn("`docs/oauth2-research.md`", content)
        self.assertIn("decisions.md", content)
        self.assertIn("Decision: Use Auth0", content)

    def test_append_multiple_agents(self):
        """Multiple agents append in order."""
        phases = {"THINK": ["researcher", "architect"]}
        init_workflow(self.cwd, "Multi", "new-feature", phases)
        create_feature_log(self.cwd, "Multi", "new-feature",
                           log_file="log-multi.md")

        append_feature_log(self.cwd, "researcher", "THINK",
                           summary="Did research", log_file="log-multi.md")
        append_feature_log(self.cwd, "architect", "THINK",
                           summary="Designed system", log_file="log-multi.md")

        path = os.path.join(self.cwd, ".coregy", "knowledge", "log-multi.md")
        with open(path) as f:
            content = f.read()

        # researcher appears before architect
        r_pos = content.index("### researcher")
        a_pos = content.index("### architect")
        self.assertLess(r_pos, a_pos)

    def test_finalize_feature_log(self):
        """Adds summary section and updates status."""
        phases = {"THINK": ["researcher"]}
        init_workflow(self.cwd, "Final", "new-feature", phases)
        create_feature_log(self.cwd, "Final", "new-feature",
                           log_file="log-final.md")

        # Simulate agent completing
        start_agent(self.cwd, "researcher")
        complete_agent(self.cwd, "researcher", "Done research", ["decisions.md"])

        finalize_feature_log(self.cwd, "log-final.md")

        path = os.path.join(self.cwd, ".coregy", "knowledge", "log-final.md")
        with open(path) as f:
            content = f.read()

        self.assertIn("## Summary", content)
        self.assertIn("1 agents completed", content)
        self.assertIn("**researcher** (THINK): Done research", content)
        self.assertIn("status: completed", content)
        self.assertNotIn("status: in_progress", content)

    def test_complete_workflow_finalizes_log(self):
        """complete_workflow auto-finalizes the feature log."""
        phases = {"THINK": ["researcher"]}
        init_workflow(self.cwd, "Auto Final", "new-feature", phases)
        create_feature_log(self.cwd, "Auto Final", "new-feature",
                           log_file="log-auto-final.md")

        start_agent(self.cwd, "researcher")
        complete_agent(self.cwd, "researcher", "All done")
        complete_workflow(self.cwd)

        path = os.path.join(self.cwd, ".coregy", "knowledge", "log-auto-final.md")
        with open(path) as f:
            content = f.read()

        self.assertIn("## Summary", content)
        self.assertIn("status: completed", content)

    def test_append_without_log_file_silent(self):
        """append_feature_log silently skips if no log file exists."""
        phases = {"THINK": ["researcher"]}
        init_workflow(self.cwd, "No Log", "new-feature", phases)
        # Don't create log file — should not error
        append_feature_log(self.cwd, "researcher", "THINK",
                           summary="test", log_file="nonexistent.md")


class TestCheckpointIntegration(unittest.TestCase):
    """Test checkpoint integration with state.py lifecycle."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name
        os.makedirs(os.path.join(self.cwd, ".coregy"), exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _init_tracker(self):
        """Initialize tracker DB so checkpoints work."""
        import tracker_schema
        tracker_schema.init_db(self.cwd)

    def test_start_agent_returns_none_checkpoint_without_db(self):
        """start_agent returns None checkpoint when tracker.db doesn't exist."""
        init_workflow(self.cwd, "Test", "new-feature", {"THINK": ["researcher"]})
        state, checkpoint = start_agent(self.cwd, "researcher")
        self.assertIsNone(checkpoint)

    def test_start_agent_returns_existing_checkpoint(self):
        """start_agent returns checkpoint data when one exists."""
        self._init_tracker()
        import tracker as tracker_mod

        wf_state = init_workflow(self.cwd, "Test", "new-feature", {
            "THINK": ["researcher"],
            "BUILD": ["backend"],
        })
        wf_id = wf_state["workflow_id"]

        # Save a checkpoint as if backend was interrupted
        tracker_mod.save_checkpoint(
            self.cwd, wf_id, "backend", "BUILD",
            total_items=5, completed_items=3,
            resume_hint="Continue from endpoint 4",
        )

        # Start agent — should return the checkpoint
        start_agent(self.cwd, "researcher")
        complete_agent(self.cwd, "researcher")
        state, checkpoint = start_agent(self.cwd, "backend")
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint["completed_items"], 3)
        self.assertEqual(checkpoint["resume_hint"], "Continue from endpoint 4")

    def test_complete_agent_clears_checkpoint(self):
        """complete_agent clears the agent's checkpoint."""
        self._init_tracker()
        import tracker as tracker_mod

        wf_state = init_workflow(self.cwd, "Test", "new-feature", {
            "THINK": ["researcher"],
        })
        wf_id = wf_state["workflow_id"]

        tracker_mod.save_checkpoint(
            self.cwd, wf_id, "researcher", "THINK",
            total_items=3, completed_items=2,
        )

        start_agent(self.cwd, "researcher")
        complete_agent(self.cwd, "researcher", "Done")

        # Checkpoint should be gone
        loaded = tracker_mod.load_checkpoint(self.cwd, wf_id, "researcher")
        self.assertIsNone(loaded)

    def test_complete_workflow_clears_all_checkpoints(self):
        """complete_workflow clears all checkpoints for the workflow."""
        self._init_tracker()
        import tracker as tracker_mod

        wf_state = init_workflow(self.cwd, "Test", "new-feature", {
            "THINK": ["researcher"],
            "BUILD": ["backend"],
        })
        wf_id = wf_state["workflow_id"]

        tracker_mod.save_checkpoint(self.cwd, wf_id, "researcher", "THINK")
        tracker_mod.save_checkpoint(self.cwd, wf_id, "backend", "BUILD")

        complete_workflow(self.cwd)

        results = tracker_mod.load_workflow_checkpoints(self.cwd, wf_id)
        self.assertEqual(len(results), 0)

    def test_abort_workflow_clears_all_checkpoints(self):
        """abort_workflow clears all checkpoints."""
        self._init_tracker()
        import tracker as tracker_mod

        wf_state = init_workflow(self.cwd, "Test", "new-feature", {
            "THINK": ["researcher"],
        })
        wf_id = wf_state["workflow_id"]

        tracker_mod.save_checkpoint(self.cwd, wf_id, "researcher", "THINK")

        abort_workflow(self.cwd)

        results = tracker_mod.load_workflow_checkpoints(self.cwd, wf_id)
        self.assertEqual(len(results), 0)


class TestGetExecutionMode(unittest.TestCase):
    """Tests for get_execution_mode helper."""

    def test_none_state(self):
        """Returns 'guided' for None state."""
        self.assertEqual(get_execution_mode(None), "guided")

    def test_missing_key(self):
        """Returns 'guided' for legacy state without execution_mode."""
        state = {"status": "in_progress", "feature": "test"}
        self.assertEqual(get_execution_mode(state), "guided")

    def test_explicit_auto(self):
        """Returns 'auto' when set."""
        state = {"execution_mode": "auto"}
        self.assertEqual(get_execution_mode(state), "auto")

    def test_explicit_manual(self):
        """Returns 'manual' when set."""
        state = {"execution_mode": "manual"}
        self.assertEqual(get_execution_mode(state), "manual")


class TestSetExecutionMode(unittest.TestCase):
    """Tests for set_execution_mode."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name
        os.makedirs(os.path.join(self.cwd, ".coregy"), exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_set_mode(self):
        """Sets execution mode on existing workflow."""
        phases = {"THINK": ["researcher"]}
        init_workflow(self.cwd, "Test", "new-feature", phases)
        state = set_execution_mode(self.cwd, "manual")
        self.assertEqual(state["execution_mode"], "manual")

    def test_override_mode(self):
        """Overrides existing mode."""
        phases = {"THINK": ["researcher"]}
        init_workflow(self.cwd, "Test", "new-feature", phases, execution_mode="auto")
        state = set_execution_mode(self.cwd, "guided")
        self.assertEqual(state["execution_mode"], "guided")

    def test_invalid_mode(self):
        """Invalid mode raises ValueError."""
        phases = {"THINK": ["researcher"]}
        init_workflow(self.cwd, "Test", "new-feature", phases)
        with self.assertRaises(ValueError):
            set_execution_mode(self.cwd, "fast")

    def test_no_workflow(self):
        """Raises FileNotFoundError when no workflow exists."""
        with self.assertRaises(FileNotFoundError):
            set_execution_mode(self.cwd, "auto")

    def test_persists(self):
        """Mode persists after reload."""
        phases = {"THINK": ["researcher"]}
        init_workflow(self.cwd, "Test", "new-feature", phases)
        set_execution_mode(self.cwd, "auto")
        loaded = load_state(self.cwd)
        self.assertEqual(loaded["execution_mode"], "auto")

    def test_mode_survives_agent_cycle(self):
        """Mode persists through start/complete agent cycle."""
        phases = {"THINK": ["researcher"]}
        init_workflow(self.cwd, "Test", "new-feature", phases, execution_mode="manual")
        start_agent(self.cwd, "researcher")
        complete_agent(self.cwd, "researcher", "Done")
        state = load_state(self.cwd)
        self.assertEqual(state["execution_mode"], "manual")


if __name__ == "__main__":
    unittest.main()
