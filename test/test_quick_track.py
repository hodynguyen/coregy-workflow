"""Tests for the quick track (state["quick"]) across state.py, its CLI and the SessionStart hook."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUGIN = os.path.join(ROOT, "plugins", "coregy-workflow")
SCRIPTS_DIR = os.path.join(PLUGIN, "skills", "project-profile", "scripts")
STATE_PY = os.path.join(SCRIPTS_DIR, "state.py")
HOOK = os.path.join(PLUGIN, "hooks", "inject_project_context.py")
sys.path.insert(0, SCRIPTS_DIR)

from state import init_workflow, load_state, start_agent, complete_agent, get_next_agent

QUICK_PHASES = {"BUILD": ["backend"], "VERIFY": ["code-reviewer"]}


class TempProject(unittest.TestCase):
    def setUp(self):
        self.cwd = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cwd, True)
        os.makedirs(os.path.join(self.cwd, ".coregy"))

    def cli(self, *args):
        return subprocess.run([sys.executable, STATE_PY] + list(args) + ["--cwd", self.cwd],
                              capture_output=True, text=True)


class TestQuickState(TempProject):
    def test_default_is_full(self):
        self.assertFalse(init_workflow(self.cwd, "f", "bug-fix", QUICK_PHASES)["quick"])

    def test_quick_flag_persists(self):
        init_workflow(self.cwd, "f", "bug-fix", QUICK_PHASES, quick=True)
        self.assertTrue(load_state(self.cwd)["quick"])

    def test_quick_flag_survives_the_agent_cycle(self):
        init_workflow(self.cwd, "f", "bug-fix", QUICK_PHASES, quick=True, max_fix_rounds=2)
        for agent in ("backend", "code-reviewer"):
            start_agent(self.cwd, agent)
            complete_agent(self.cwd, agent)
        state = load_state(self.cwd)
        self.assertTrue(state["quick"])
        self.assertEqual(state["max_fix_rounds"], 2)
        self.assertIsNone(get_next_agent(state))

    def test_legacy_state_without_key_reads_as_full(self):
        init_workflow(self.cwd, "f", "bug-fix", QUICK_PHASES)
        path = os.path.join(self.cwd, ".coregy", "state.json")
        with open(path) as f:
            state = json.load(f)
        del state["quick"]
        with open(path, "w") as f:
            json.dump(state, f)
        result = self.cli("show")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("(quick)", result.stdout)


class TestQuickCli(TempProject):
    def init(self, *extra):
        return self.cli("init-workflow", "--feature", "fix typo", "--type", "bug-fix",
                        "--phases", json.dumps(QUICK_PHASES), *extra)

    def test_init_quick(self):
        result = self.init("--quick", "--max-fix-rounds", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertTrue(state["quick"])
        self.assertEqual(state["max_fix_rounds"], 2)

    def test_init_without_flag(self):
        self.assertFalse(json.loads(self.init().stdout)["quick"])

    def test_show_marks_quick(self):
        self.init("--quick")
        self.assertIn("Type:     bug-fix (quick)", self.cli("show").stdout)

    def test_show_full_has_no_mark(self):
        self.init()
        self.assertIn("Type:     bug-fix   Status", self.cli("show").stdout)


class TestQuickHookContext(TempProject):
    def run_hook(self):
        with open(os.path.join(self.cwd, ".coregy", "profile.yaml"), "w") as f:
            f.write("project:\n  name: hook-test\n")
        result = subprocess.run(
            [sys.executable, HOOK], input=json.dumps({"cwd": self.cwd}),
            capture_output=True, text=True, timeout=10,
            env=dict(os.environ, COREGY_SKIP_REFRESH="1"),
        )
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_quick_track_is_announced(self):
        init_workflow(self.cwd, "fix typo", "bug-fix", QUICK_PHASES,
                      spec_confirmed=True, quick=True)
        self.assertIn("mode: guided, quick track", self.run_hook())

    def test_full_track_is_unchanged(self):
        init_workflow(self.cwd, "add auth", "new-feature", QUICK_PHASES, spec_confirmed=True)
        context = self.run_hook()
        self.assertIn("mode: guided)", context)
        self.assertNotIn("quick", context)


class TestQuickDocs(unittest.TestCase):
    """The quick sequence documented in start-feature must be valid --phases input."""

    def read(self, rel):
        with open(os.path.join(PLUGIN, rel), encoding="utf-8") as f:
            return f.read()

    def test_quick_sequence_phases_are_valid_json(self):
        text = self.read("commands/start-feature.md")
        section = text.split("### Quick sequence", 1)[1].split("**Outgrowing quick**", 1)[0]
        cells = re.findall(r"`(\{.*?\})`", section)
        self.assertGreaterEqual(len(cells), 6)
        for cell in cells:
            phases = json.loads(re.sub(r"<[^>]+>", "backend", cell))
            self.assertTrue(set(phases) <= {"THINK", "BUILD", "VERIFY", "SHIP"}, cell)

    def test_quick_agents_know_the_flag(self):
        for agent in ("backend", "frontend", "code-reviewer", "researcher"):
            self.assertIn('"quick": true', self.read("agents/%s.md" % agent), agent)


if __name__ == "__main__":
    unittest.main()
