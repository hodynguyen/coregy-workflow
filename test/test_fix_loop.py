"""Tests for the review -> fix -> re-review loop in state.py."""
import json
import os
import sys
import tempfile
import unittest

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
    DEFAULT_MAX_FIX_ROUNDS,
    init_workflow,
    load_state,
    start_agent,
    complete_agent,
    skip_agent,
    get_next_agent,
    get_pending_fix_round,
    request_fixes,
    create_feature_log,
)

BUG_FIX = {
    "THINK": ["architect"],
    "BUILD": ["backend"],
    "VERIFY": ["unit-tester", "code-reviewer"],
}


class FixLoopCase(unittest.TestCase):
    phases = BUG_FIX
    max_rounds = DEFAULT_MAX_FIX_ROUNDS

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name
        os.makedirs(os.path.join(self.cwd, ".coregy"), exist_ok=True)
        init_workflow(self.cwd, "Fix login", "bug-fix", self.phases,
                      max_fix_rounds=self.max_rounds)

    def tearDown(self):
        self.tmpdir.cleanup()

    def run_agent(self, agent, summary="done"):
        start_agent(self.cwd, agent)
        return complete_agent(self.cwd, agent, output_summary=summary)

    def run_until(self, gate):
        """Run every agent before `gate`, then start the gate."""
        while True:
            _, agent = get_next_agent(load_state(self.cwd))
            if agent == gate:
                start_agent(self.cwd, gate)
                return
            self.run_agent(agent)


class TestInitFields(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_defaults(self):
        state = init_workflow(self.cwd, "f", "bug-fix", BUG_FIX)
        self.assertEqual(state["max_fix_rounds"], DEFAULT_MAX_FIX_ROUNDS)
        self.assertEqual(state["fix_rounds"], [])

    def test_custom_limit(self):
        state = init_workflow(self.cwd, "f", "bug-fix", BUG_FIX, max_fix_rounds=1)
        self.assertEqual(state["max_fix_rounds"], 1)

    def test_rejects_zero_limit(self):
        with self.assertRaises(ValueError):
            init_workflow(self.cwd, "f", "bug-fix", BUG_FIX, max_fix_rounds=0)


class TestRequestFixes(FixLoopCase):
    def test_sends_work_back_to_the_builder(self):
        self.run_until("code-reviewer")
        state, rnd = request_fixes(self.cwd, "code-reviewer",
                                   ["a.py:1 injection", "a.py:9 null"])

        self.assertEqual(rnd["status"], "open")
        self.assertEqual(rnd["round"], 1)
        self.assertEqual(rnd["fixers"], ["backend"])
        self.assertNotIn("backend", state["phases"]["BUILD"]["completed"])
        self.assertNotIn("code-reviewer", state["phases"]["VERIFY"]["completed"])
        self.assertIsNone(state["phases"]["VERIFY"]["active"])
        self.assertEqual(get_next_agent(state), ("BUILD", "backend"))

    def test_closes_the_gates_run(self):
        self.run_until("code-reviewer")
        state, _ = request_fixes(self.cwd, "code-reviewer", ["x"], summary="2 blockers")
        entry = [e for e in state["agent_log"] if e["agent"] == "code-reviewer"][-1]
        self.assertIsNotNone(entry["completed_at"])
        self.assertEqual(entry["output_summary"], "2 blockers")

    def test_untouched_agents_stay_completed(self):
        self.run_until("code-reviewer")
        state, _ = request_fixes(self.cwd, "code-reviewer", ["x"])
        self.assertIn("unit-tester", state["phases"]["VERIFY"]["completed"])
        self.assertIn("architect", state["phases"]["THINK"]["completed"])

    def test_rerun_reopens_extra_agents_before_the_gate(self):
        self.run_until("code-reviewer")
        state, rnd = request_fixes(self.cwd, "code-reviewer", ["x"], rerun=["unit-tester"])
        self.assertNotIn("unit-tester", state["phases"]["VERIFY"]["completed"])
        self.assertEqual(rnd["reopened"], ["backend", "unit-tester", "code-reviewer"])
        self.run_agent("backend")
        self.assertEqual(get_next_agent(load_state(self.cwd)), ("VERIFY", "unit-tester"))

    def test_rerun_of_an_agent_that_never_ran_is_rejected(self):
        phases = dict(BUG_FIX, VERIFY=["code-reviewer", "unit-tester"])
        init_workflow(self.cwd, "f", "bug-fix", phases)
        self.run_until("code-reviewer")
        with self.assertRaises(ValueError):
            request_fixes(self.cwd, "code-reviewer", ["x"], rerun=["unit-tester"])

    def test_requires_issues(self):
        self.run_until("code-reviewer")
        for issues in ([], ["", "  "], None):
            with self.assertRaises(ValueError):
                request_fixes(self.cwd, "code-reviewer", issues)

    def test_build_agent_cannot_be_a_gate(self):
        self.run_until("code-reviewer")
        with self.assertRaises(ValueError):
            request_fixes(self.cwd, "backend", ["x"])

    def test_unknown_gate(self):
        with self.assertRaises(ValueError):
            request_fixes(self.cwd, "devops", ["x"])

    def test_unknown_fixer(self):
        self.run_until("code-reviewer")
        with self.assertRaises(ValueError):
            request_fixes(self.cwd, "code-reviewer", ["x"], fixers=["frontend"])

    def test_no_build_phase(self):
        init_workflow(self.cwd, "spike", "tech-spike",
                      {"THINK": ["researcher", "architect"]})
        with self.assertRaises(ValueError):
            request_fixes(self.cwd, "architect", ["x"])

    def test_no_state(self):
        os.remove(os.path.join(self.cwd, ".coregy", "state.json"))
        with self.assertRaises(FileNotFoundError):
            request_fixes(self.cwd, "code-reviewer", ["x"])


class TestRoundLifecycle(FixLoopCase):
    def test_gate_passing_resolves_the_round(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["x"])
        self.run_agent("backend", "fixed x")
        state = self.run_agent("code-reviewer", "clean")

        self.assertEqual(state["fix_rounds"][0]["status"], "resolved")
        self.assertIsNotNone(state["fix_rounds"][0]["closed_at"])
        self.assertIsNone(get_next_agent(state))
        self.assertIsNone(get_pending_fix_round(state))

    def test_orchestrator_complete_after_request_is_a_noop(self):
        """start-feature calls complete-agent after every agent; for a gate
        that just requested fixes that call must not mark it passed."""
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["x"])
        state = complete_agent(self.cwd, "code-reviewer", output_summary="oops")
        self.assertNotIn("code-reviewer", state["phases"]["VERIFY"]["completed"])
        self.assertEqual(state["fix_rounds"][0]["status"], "open")

    def test_fixer_second_complete_is_idempotent(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["x"])
        self.run_agent("backend")
        before = load_state(self.cwd)["agent_log"]
        complete_agent(self.cwd, "backend", output_summary="again")
        self.assertEqual(load_state(self.cwd)["agent_log"], before)

    def test_fixer_rerun_hands_over_to_the_gate(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["x"])
        state = load_state(self.cwd)
        self.assertNotIn("backend", state["phases"]["BUILD"]["completed"])
        start_agent(self.cwd, "backend")
        state = complete_agent(self.cwd, "backend")
        self.assertIn("backend", state["phases"]["BUILD"]["completed"])
        self.assertEqual(get_next_agent(state), ("VERIFY", "code-reviewer"))

    def test_second_failure_opens_round_two(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["x", "y"])
        self.run_agent("backend")
        start_agent(self.cwd, "code-reviewer")
        state, rnd = request_fixes(self.cwd, "code-reviewer", ["y"])

        self.assertEqual(rnd["round"], 2)
        self.assertEqual(rnd["status"], "open")
        self.assertEqual(state["fix_rounds"][0]["status"], "failed")
        self.assertEqual(get_next_agent(state), ("BUILD", "backend"))

    def test_start_agent_sees_the_round(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["a.py:1 x"])
        state, _ = start_agent(self.cwd, "backend")
        self.assertEqual(get_pending_fix_round(state, "backend")["issues"], ["a.py:1 x"])
        self.assertIsNone(get_pending_fix_round(state, "architect"))


class TestEscalation(FixLoopCase):
    max_rounds = 2

    def fail_round(self, issues):
        start_agent(self.cwd, "code-reviewer")
        return request_fixes(self.cwd, "code-reviewer", issues)

    def test_no_progress_escalates(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["x", "y"])
        self.run_agent("backend")
        state, rnd = self.fail_round(["x", "z"])

        self.assertEqual(rnd["status"], "escalated")
        self.assertEqual(rnd["escalation_reason"], "no_progress")
        # Nothing reopened: the builder stays done, the gate waits.
        self.assertIn("backend", state["phases"]["BUILD"]["completed"])
        self.assertEqual(get_next_agent(state), ("VERIFY", "code-reviewer"))
        self.assertEqual(get_pending_fix_round(state)["status"], "escalated")

    def test_max_rounds_escalates(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["a", "b", "c"])
        self.run_agent("backend")
        self.fail_round(["a", "b"])
        self.run_agent("backend")
        state, rnd = self.fail_round(["a"])

        self.assertEqual(rnd["escalation_reason"], "max_rounds")
        self.assertEqual(rnd["round"], 3)

    def test_accepting_completes_the_gate(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["x"])
        self.run_agent("backend")
        self.fail_round(["x"])
        state = complete_agent(self.cwd, "code-reviewer", output_summary="accepted")

        self.assertIn("code-reviewer", state["phases"]["VERIFY"]["completed"])
        self.assertEqual(state["fix_rounds"][-1]["status"], "accepted")
        self.assertIsNone(get_next_agent(state))

    def test_force_opens_another_round(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["x"])
        self.run_agent("backend")
        self.fail_round(["x"])
        state, rnd = request_fixes(self.cwd, "code-reviewer", ["x"], force=True)

        self.assertEqual(rnd["status"], "open")
        self.assertEqual(rnd["round"], 2)
        self.assertEqual(state["fix_rounds"][1]["status"], "superseded")
        self.assertEqual(get_next_agent(state), ("BUILD", "backend"))

    def test_raising_the_limit(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["a", "b", "c"])
        self.run_agent("backend")
        self.fail_round(["a", "b"])
        self.run_agent("backend")
        start_agent(self.cwd, "code-reviewer")
        state, rnd = request_fixes(self.cwd, "code-reviewer", ["a"], max_rounds=5)
        self.assertEqual(rnd["status"], "open")
        self.assertEqual(state["max_fix_rounds"], 5)

    def test_escalation_ignores_other_gates_rounds(self):
        self.run_until("code-reviewer")
        state = load_state(self.cwd)
        # unit-tester completed earlier; its rounds must not count against
        # code-reviewer's budget.
        state["fix_rounds"] = [{
            "round": 1, "gate": "unit-tester", "phase": "VERIFY",
            "fixers": ["backend"], "rerun": [], "issues": ["t"],
            "status": "resolved", "escalation_reason": None,
            "reopened": ["backend", "unit-tester"], "requested_at": None,
            "closed_at": None, "log_index": 0,
        }] * 2
        with open(os.path.join(self.cwd, ".coregy", "state.json"), "w") as f:
            json.dump(state, f)
        _, rnd = request_fixes(self.cwd, "code-reviewer", ["x"])
        self.assertEqual(rnd["status"], "open")
        self.assertEqual(rnd["round"], 1)


class TestMultiPhaseGate(FixLoopCase):
    """refactor lists code-reviewer in THINK (assess) and VERIFY (verify)."""

    phases = {
        "THINK": ["code-reviewer"],
        "BUILD": ["backend"],
        "VERIFY": ["unit-tester", "code-reviewer"],
    }

    def test_verify_occurrence_loops_back(self):
        self.run_agent("code-reviewer", "assessed")
        self.run_agent("backend")
        self.run_agent("unit-tester")
        start_agent(self.cwd, "code-reviewer")
        state, rnd = request_fixes(self.cwd, "code-reviewer", ["x"])

        self.assertEqual(rnd["phase"], "VERIFY")
        self.assertIn("code-reviewer", state["phases"]["THINK"]["completed"])
        self.run_agent("backend")
        state = self.run_agent("code-reviewer", "verified")
        self.assertIn("code-reviewer", state["phases"]["VERIFY"]["completed"])
        self.assertIsNone(get_next_agent(state))


class TestParallelBuilders(FixLoopCase):
    phases = {"BUILD": ["frontend", "backend"], "VERIFY": ["code-reviewer"]}

    def test_default_fixers_skip_skipped_builders(self):
        self.run_agent("frontend")
        skip_agent(self.cwd, "backend")
        start_agent(self.cwd, "code-reviewer")
        _, rnd = request_fixes(self.cwd, "code-reviewer", ["x"])
        self.assertEqual(rnd["fixers"], ["frontend"])

    def test_gate_waits_for_every_fixer(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["x"])
        self.run_agent("frontend")
        state = complete_agent(self.cwd, "code-reviewer")
        self.assertNotIn("code-reviewer", state["phases"]["VERIFY"]["completed"])
        self.assertEqual(get_next_agent(state), ("BUILD", "backend"))


class TestFeatureLogEntries(FixLoopCase):
    max_rounds = 1

    def test_rounds_and_escalations_are_logged(self):
        create_feature_log(self.cwd, "Fix login", "bug-fix")
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["a.py:1 injection"])
        self.run_agent("backend")
        start_agent(self.cwd, "code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["a.py:1 injection"])

        path = os.path.join(self.cwd, ".coregy", "knowledge", "log-fix-login.md")
        with open(path) as f:
            text = f.read()
        self.assertIn("### Fix round 1/1 — code-reviewer → backend", text)
        self.assertIn("  - a.py:1 injection", text)
        self.assertIn("### Fix loop escalated — code-reviewer (max_rounds)", text)

    def test_missing_log_is_silent(self):
        self.run_until("code-reviewer")
        request_fixes(self.cwd, "code-reviewer", ["x"])  # must not raise


if __name__ == "__main__":
    unittest.main()
