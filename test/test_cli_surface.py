"""Subprocess-level tests for the runtime CLI surface (spec R1-R9).

These tests deliberately shell out with `sys.executable` instead of importing
the modules. The library functions in these 7 scripts were already covered by
unit tests, yet the plugin's runtime was broken for 12 versions because
*nothing executed the scripts the way a command file does*. Importing a
function cannot catch a missing `__main__`, a bad argparse dest, a traceback on
a legacy state file, or a `${PLUGIN_ROOT}` that expands to nothing.

Every assertion here is about the process boundary: argv in, exit code and
stdout out.
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUGIN_ROOT_DIR = os.path.join(REPO_ROOT, "plugins", "coregy-workflow")
SCRIPTS_DIR = os.path.join(
    PLUGIN_ROOT_DIR, "skills", "project-profile", "scripts"
)
CONTRACTS_DIR = os.path.join(PLUGIN_ROOT_DIR, "agents", "contracts")

# The workflow CLIs (7 wired up by R3-R9, plus verify.py), with the subcommands
# each must expose.
CLI_SCRIPTS = {
    "state.py": [
        "init-workflow", "start-agent", "complete-agent", "skip-agent",
        "request-fixes", "confirm-spec", "set-mode", "next-agent", "complete", "abort",
        "log-append", "show",
    ],
    "health.py": ["report"],
    "kb_index.py": ["build", "search"],
    "kb_archive.py": ["check", "run"],
    "contracts.py": ["validate", "list"],
    "ci_monitor.py": ["status", "summary", "feedback"],
    "team.py": ["init", "show", "check-agent", "check-workflow"],
    "verify.py": ["detect", "run", "last", "init"],
}


def script_path(name):
    return os.path.join(SCRIPTS_DIR, name)


def run_script(name, args, cwd, env=None):
    """Invoke a script exactly the way a command file's bash block does."""
    return subprocess.run(
        [sys.executable, script_path(name)] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def write(path, content):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def digest_tree(root):
    """Map of relative path -> md5, for proving a command did not mutate."""
    out = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in sorted(filenames):
            full = os.path.join(dirpath, fname)
            with open(full, "rb") as f:
                out[os.path.relpath(full, root)] = hashlib.md5(
                    f.read()
                ).hexdigest()
    return out


class CliTestCase(unittest.TestCase):
    """Temp project fixture. Never touches the repo's real .coregy/."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.coregy = os.path.join(self.tmpdir, ".coregy")
        self.kb = os.path.join(self.coregy, "knowledge")
        os.makedirs(self.kb)
        self.env = dict(os.environ)
        # Deterministic identity for team.py / anything reading git config.
        self.env["COREGY_USER"] = "tester"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_cli(self, name, *args, **kwargs):
        env = kwargs.pop("env", None) or self.env
        cwd = kwargs.pop("cwd", None) or self.tmpdir
        return run_script(name, args, cwd, env=env)

    def assertOk(self, result, msg=""):
        self.assertEqual(
            result.returncode, 0,
            "%s\nstdout: %s\nstderr: %s" % (msg, result.stdout, result.stderr),
        )

    def json_out(self, result):
        self.assertOk(result, "expected parseable JSON on a successful run")
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            self.fail("stdout is not valid JSON (%s): %r" % (exc, result.stdout))


# =====================================================================
# Contract shared by all 7 CLIs (coregy-cli-v1)
# =====================================================================


class TestCliConventions(CliTestCase):
    """R14/acceptance criterion 2: every script is executable as a program."""

    def test_help_exits_zero_and_lists_every_subcommand(self):
        for name, subcommands in CLI_SCRIPTS.items():
            result = self.run_cli(name, "--help")
            self.assertEqual(
                result.returncode, 0,
                "%s --help exited %d: %s" % (name, result.returncode, result.stderr),
            )
            self.assertIn("usage:", result.stdout)
            for sub in subcommands:
                self.assertIn(
                    sub, result.stdout,
                    "%s --help does not mention subcommand %r" % (name, sub),
                )

    def test_no_subcommand_exits_nonzero(self):
        for name in CLI_SCRIPTS:
            result = self.run_cli(name)
            self.assertNotEqual(
                result.returncode, 0,
                "%s with no subcommand should not exit 0" % name,
            )
            self.assertIn("usage:", result.stdout + result.stderr)

    def test_unknown_subcommand_is_a_usage_error(self):
        for name in CLI_SCRIPTS:
            result = self.run_cli(name, "definitely-not-a-subcommand")
            self.assertEqual(
                result.returncode, 2,
                "%s should exit 2 on an unknown subcommand" % name,
            )

    def test_cwd_works_before_the_subcommand_too(self):
        """coregy-cli-v1 point 1: the shared parent parser puts --cwd on both
        sides. Every other test passes it after the subcommand, so this covers
        the other half -- and proves the value is really used, not ignored.
        """
        # health.py: the only project signal is the .coregy/ dir in tmpdir.
        result = run_script("health.py", ["--cwd", self.tmpdir, "report"],
                            cwd=REPO_ROOT, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)

        # state.py: tmpdir has no workflow, REPO_ROOT does -- so the "no
        # workflow" exit proves --cwd was honoured over the process cwd.
        result = run_script("state.py", ["--cwd", self.tmpdir, "show"],
                            cwd=REPO_ROOT, env=self.env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("No active workflow", result.stderr)

        # kb_index.py: the index must land in tmpdir, not in REPO_ROOT.
        result = run_script("kb_index.py", ["--cwd", self.tmpdir, "build"],
                            cwd=REPO_ROOT, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.kb, "_index.json")))

        for name, args in (
            ("kb_archive.py", ["check"]),
            ("contracts.py", ["list"]),
            ("team.py", ["show"]),
        ):
            result = run_script(name, ["--cwd", self.tmpdir] + args,
                                cwd=REPO_ROOT, env=self.env)
            self.assertEqual(
                result.returncode, 0,
                "%s rejected --cwd before the subcommand: %s"
                % (name, result.stderr),
            )

    def test_import_is_side_effect_free(self):
        """R-14: adding main() must not execute anything on import."""
        for name in CLI_SCRIPTS:
            module = name[:-3]
            result = subprocess.run(
                [sys.executable, "-c",
                 "import sys; sys.path.insert(0, %r); import %s"
                 % (SCRIPTS_DIR, module)],
                cwd=self.tmpdir, capture_output=True, text=True, env=self.env,
            )
            self.assertEqual(
                result.returncode, 0,
                "importing %s failed: %s" % (name, result.stderr),
            )
            self.assertEqual(
                result.stdout.strip(), "",
                "importing %s printed to stdout" % name,
            )


# =====================================================================
# R3 -- state.py
# =====================================================================

PHASES = '{"THINK":["architect"],"BUILD":["backend"],"VERIFY":["unit-tester"]}'


class StateCliTestCase(CliTestCase):
    def state(self, *args):
        return self.run_cli("state.py", *args)

    def init(self, *extra):
        args = [
            "init-workflow",
            "--feature", "Test runtime wiring",
            "--type", "refactor",
            "--phases", PHASES,
            "--spec-file", "spec-test.md",
            "--cwd", ".",
        ]
        return self.state(*(args + list(extra)))

    def read_state(self):
        with open(os.path.join(self.coregy, "state.json")) as f:
            return json.load(f)


class TestStateInitWorkflow(StateCliTestCase):
    def test_init_writes_state_and_log(self):
        data = self.json_out(self.init())
        self.assertEqual(data["type"], "refactor")
        self.assertEqual(data["execution_mode"], "guided")
        self.assertEqual(data["spec_file"], "spec-test.md")
        self.assertEqual(data["phase_order"], ["THINK", "BUILD", "VERIFY"])
        self.assertTrue(os.path.isfile(os.path.join(self.coregy, "state.json")))
        self.assertTrue(
            os.path.isfile(os.path.join(self.kb, data["log_file"])),
            "init-workflow must create the feature log",
        )

    def test_init_honours_mode_and_spec_confirmed(self):
        data = self.json_out(self.init("--mode", "auto", "--spec-confirmed"))
        self.assertEqual(data["execution_mode"], "auto")
        self.assertTrue(data["spec_confirmed"])

    def test_init_no_log_flag(self):
        data = self.json_out(self.init("--no-log"))
        self.assertFalse(os.path.isfile(os.path.join(self.kb, data["log_file"])))

    def test_invalid_mode_is_a_usage_error(self):
        result = self.init("--mode", "turbo")
        self.assertEqual(result.returncode, 2)

    def test_invalid_phases_json_exits_one_without_traceback(self):
        """R-15: a quoting mistake must not produce a traceback."""
        result = self.state(
            "init-workflow", "--feature", "x", "--type", "refactor",
            "--phases", "{not json", "--cwd", ".",
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("not valid JSON", result.stderr)

    def test_phases_must_be_an_object(self):
        result = self.state(
            "init-workflow", "--feature", "x", "--type", "refactor",
            "--phases", '["architect"]', "--cwd", ".",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("JSON object", result.stderr)

    def test_phase_values_must_be_lists(self):
        result = self.state(
            "init-workflow", "--feature", "x", "--type", "refactor",
            "--phases", '{"THINK":"architect"}', "--cwd", ".",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("list of agent names", result.stderr)

    def test_missing_required_flag_is_a_usage_error(self):
        result = self.state("init-workflow", "--feature", "x", "--cwd", ".")
        self.assertEqual(result.returncode, 2)

    def test_refuses_to_clobber_an_in_progress_workflow(self):
        """R-10: a second /start-feature must not destroy live state."""
        first = self.json_out(self.init())
        result = self.init()
        self.assertEqual(result.returncode, 1)
        self.assertIn("in progress", result.stderr)
        self.assertIn("--force", result.stderr)
        # The original workflow survived untouched.
        self.assertEqual(self.read_state()["workflow_id"], first["workflow_id"])

    def test_force_overwrites_an_in_progress_workflow(self):
        self.init()
        result = self.state(
            "init-workflow", "--feature", "Second feature", "--type", "bug-fix",
            "--phases", '{"BUILD":["backend"]}', "--force", "--cwd", ".",
        )
        data = self.json_out(result)
        self.assertEqual(data["feature"], "Second feature")
        self.assertEqual(data["phase_order"], ["BUILD"])

    def test_completed_workflow_does_not_block_a_new_one(self):
        self.init()
        self.state("complete", "--cwd", ".")
        data = self.json_out(self.init())
        self.assertEqual(data["status"], "in_progress")


class TestStateAgentLifecycle(StateCliTestCase):
    def setUp(self):
        CliTestCase.setUp(self)
        self.assertOk(self.init())

    def test_start_agent_emits_clean_json(self):
        data = self.json_out(self.state("start-agent", "architect", "--cwd", "."))
        self.assertTrue(data["ok"])
        self.assertEqual(data["agent"], "architect")
        self.assertEqual(data["phase"], "THINK")
        self.assertEqual(data["warnings"], [])
        self.assertIsNone(data["checkpoint"])
        self.assertEqual(data["state"]["phases"]["THINK"]["active"], "architect")

    def test_start_agent_json_survives_phase_warnings(self):
        """R-1: start_agent() bare-prints warnings; they must not corrupt JSON.

        Starting a BUILD agent while THINK has no progress is exactly the
        condition that triggers those prints.
        """
        result = self.state("start-agent", "backend", "--cwd", ".")
        self.assertOk(result)
        self.assertNotIn(
            "Warning:", result.stdout.splitlines()[0],
            "a bare print() leaked ahead of the JSON payload",
        )
        data = json.loads(result.stdout)  # must parse -- the whole point
        self.assertEqual(data["phase"], "BUILD")
        self.assertTrue(
            data["warnings"],
            "the captured warning must be re-emitted under the warnings key",
        )
        self.assertIn("before THINK", data["warnings"][0])

    def test_start_unknown_agent_exits_one(self):
        result = self.state("start-agent", "nobody", "--cwd", ".")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)

    def test_complete_agent_records_summary_and_kb_files(self):
        self.state("start-agent", "architect", "--cwd", ".")
        data = self.json_out(self.state(
            "complete-agent", "architect",
            "--summary", "Designed the CLI surface",
            "--kb-files", "architecture.md, decisions.md",
            "--cwd", ".",
        ))
        self.assertIn("architect", data["phases"]["THINK"]["completed"])
        self.assertIsNone(data["phases"]["THINK"]["active"])
        entry = data["agent_log"][-1]
        self.assertEqual(entry["output_summary"], "Designed the CLI surface")
        self.assertEqual(
            entry["kb_files_modified"], ["architecture.md", "decisions.md"],
            "--kb-files must split on commas and strip whitespace",
        )

    def test_complete_agent_with_empty_kb_files(self):
        self.state("start-agent", "architect", "--cwd", ".")
        data = self.json_out(self.state(
            "complete-agent", "architect", "--kb-files", "", "--cwd", ".",
        ))
        self.assertEqual(data["agent_log"][-1]["kb_files_modified"], [])

    def test_skip_agent(self):
        data = self.json_out(self.state("skip-agent", "backend", "--cwd", "."))
        self.assertIn("backend", data["phases"]["BUILD"]["skipped"])

    def test_skip_unknown_agent_exits_one(self):
        result = self.state("skip-agent", "nobody", "--cwd", ".")
        self.assertEqual(result.returncode, 1)

    def test_confirm_spec(self):
        data = self.json_out(self.state(
            "confirm-spec", "--spec-file", "spec-other.md", "--cwd", ".",
        ))
        self.assertTrue(data["spec_confirmed"])
        self.assertEqual(data["spec_file"], "spec-other.md")

    def test_set_mode(self):
        data = self.json_out(self.state("set-mode", "manual", "--cwd", "."))
        self.assertEqual(data["execution_mode"], "manual")

    def test_set_mode_rejects_unknown_mode(self):
        result = self.state("set-mode", "yolo", "--cwd", ".")
        self.assertEqual(result.returncode, 2)

    def test_next_agent_text_and_json(self):
        text = self.state("next-agent", "--cwd", ".")
        self.assertOk(text)
        self.assertEqual(text.stdout.strip(), "THINK architect")

        data = self.json_out(self.state("next-agent", "--json", "--cwd", "."))
        self.assertEqual(data, {"phase": "THINK", "agent": "architect",
                                "escalation": None})

    def test_next_agent_advances_as_agents_complete(self):
        self.state("start-agent", "architect", "--cwd", ".")
        self.state("complete-agent", "architect", "--cwd", ".")
        data = self.json_out(self.state("next-agent", "--json", "--cwd", "."))
        self.assertEqual(data["agent"], "backend")

    def test_next_agent_is_null_when_everything_is_done(self):
        for agent in ("architect", "backend", "unit-tester"):
            self.state("complete-agent", agent, "--cwd", ".")
        data = self.json_out(self.state("next-agent", "--json", "--cwd", "."))
        self.assertEqual(data, {"phase": None, "agent": None, "escalation": None})

    def test_complete_sets_status(self):
        data = self.json_out(self.state("complete", "--cwd", "."))
        self.assertEqual(data["status"], "completed")

    def test_abort_sets_status(self):
        data = self.json_out(self.state("abort", "--cwd", "."))
        self.assertEqual(data["status"], "aborted")

    def test_show_text_view(self):
        result = self.state("show", "--cwd", ".")
        self.assertOk(result)
        out = result.stdout
        self.assertIn("Workflow:", out)
        self.assertIn("Feature:  Test runtime wiring", out)
        self.assertIn("Progress: 0/3 agents (0%)", out)
        self.assertIn("[ ] architect", out)
        self.assertTrue(
            all(ord(c) < 128 or c == "━" for c in out),
            "show output must stay ASCII (coregy-cli-v1 point 6)",
        )

    def test_show_markers_reflect_agent_status(self):
        self.state("complete-agent", "architect", "--cwd", ".")
        self.state("skip-agent", "backend", "--cwd", ".")
        self.state("start-agent", "unit-tester", "--cwd", ".")
        out = self.state("show", "--cwd", ".").stdout
        self.assertIn("[x] architect", out)
        self.assertIn("[-] backend", out)
        self.assertIn("[>] unit-tester", out)

    def test_show_json_view(self):
        data = self.json_out(self.state("show", "--json", "--cwd", "."))
        self.assertEqual(data["feature"], "Test runtime wiring")
        self.assertIn("phases", data)

    def test_log_append_writes_to_the_feature_log(self):
        result = self.state(
            "log-append", "--agent", "backend", "--phase", "BUILD",
            "--summary", "Implemented the CLI",
            "--files-created", "a.py",
            "--files-modified", "b.py,c.py",
            "--kb-updated", "api-contracts.md",
            "--decision", "Used argparse",
            "--decision", "No new deps",
            "--cwd", ".",
        )
        data = self.json_out(result)
        self.assertTrue(data["ok"])
        self.assertTrue(data["appended"])
        with open(os.path.join(self.kb, data["log_file"])) as f:
            log = f.read()
        self.assertIn("### backend (BUILD)", log)
        self.assertIn("Implemented the CLI", log)
        self.assertIn("`a.py`", log)
        self.assertIn("`b.py`, `c.py`", log)
        self.assertIn("Decision: Used argparse", log)
        self.assertIn("Decision: No new deps", log)

    def test_log_append_is_a_silent_noop_when_the_log_is_missing(self):
        os.remove(os.path.join(self.kb, self.read_state()["log_file"]))
        data = self.json_out(self.state(
            "log-append", "--agent", "backend", "--phase", "BUILD",
            "--summary", "x", "--cwd", ".",
        ))
        self.assertTrue(data["ok"])
        self.assertFalse(data["appended"])


class TestStateFixLoop(StateCliTestCase):
    """request-fixes: gate -> BUILD -> gate, escalation surfaced as JSON."""

    def setUp(self):
        CliTestCase.setUp(self)
        self.assertOk(self.init("--max-fix-rounds", "2"))
        for agent in ("architect", "backend"):
            self.state("start-agent", agent, "--cwd", ".")
            self.state("complete-agent", agent, "--summary", "ok", "--cwd", ".")
        self.state("start-agent", "unit-tester", "--cwd", ".")

    def request(self, *extra):
        return self.json_out(self.state(
            "request-fixes", "unit-tester", "--cwd", ".", *extra))

    def test_init_records_the_limit(self):
        self.assertEqual(self.read_state()["max_fix_rounds"], 2)

    def test_fix_action_points_at_the_builder(self):
        data = self.request("--issue", "a.py:1 x", "--issue", "a.py:2 y")
        self.assertEqual(data["action"], "fix")
        self.assertEqual(data["round"]["issues"], ["a.py:1 x", "a.py:2 y"])
        self.assertEqual(data["next"], {"phase": "BUILD", "agent": "backend"})

    def test_start_agent_carries_the_round(self):
        self.request("--issue", "a.py:1 x")
        data = self.json_out(self.state("start-agent", "backend", "--cwd", "."))
        self.assertEqual(data["fix_round"]["issues"], ["a.py:1 x"])

    def test_start_agent_fix_round_is_null_outside_a_loop(self):
        data = self.json_out(self.state("start-agent", "architect", "--cwd", "."))
        self.assertIsNone(data["fix_round"])

    def test_escalation_reaches_next_agent_and_force_reuses_issues(self):
        self.request("--issue", "x")
        self.state("start-agent", "backend", "--cwd", ".")
        self.state("complete-agent", "backend", "--cwd", ".")
        self.state("start-agent", "unit-tester", "--cwd", ".")
        data = self.request("--issue", "x")
        self.assertEqual(data["action"], "escalate")
        self.assertEqual(data["round"]["escalation_reason"], "no_progress")

        nxt = self.json_out(self.state("next-agent", "--json", "--cwd", "."))
        self.assertEqual(nxt["escalation"]["gate"], "unit-tester")
        self.assertIn("ESCALATED", self.state("show", "--cwd", ".").stdout)

        data = self.request("--force-round")
        self.assertEqual(data["action"], "fix")
        self.assertEqual(data["round"]["issues"], ["x"])

    def test_next_agent_escalation_is_null_normally(self):
        nxt = self.json_out(self.state("next-agent", "--json", "--cwd", "."))
        self.assertIsNone(nxt["escalation"])

    def test_missing_issue_exits_one(self):
        result = self.state("request-fixes", "unit-tester", "--cwd", ".")
        self.assertEqual(result.returncode, 1)
        self.assertIn("blocking issue", result.stderr)


class TestVerifyCli(CliTestCase):
    def verify(self, *args):
        return self.run_cli("verify.py", *args)

    def config(self, command):
        write(os.path.join(self.coregy, "verify.yaml"),
              'checks:\n  test: "%s"\n' % command.replace('"', '\\"'))

    def test_run_json_reports_failures_as_issues(self):
        self.config("%s -c \"import sys; print('x.py:1 bad'); sys.exit(1)\"" % sys.executable)
        data = self.json_out(self.verify("run", "--json", "--cwd", "."))
        self.assertFalse(data["passed"])
        self.assertEqual(len(data["issues"]), 1)
        self.assertIn("x.py:1 bad", data["issues"][0])

    def test_failure_exits_zero_unless_strict(self):
        self.config("%s -c \"raise SystemExit(1)\"" % sys.executable)
        self.assertEqual(self.verify("run", "--cwd", ".").returncode, 0)
        result = self.verify("run", "--strict", "--cwd", ".")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAILED", result.stdout)

    def test_last_before_any_run_exits_one(self):
        result = self.verify("last", "--cwd", ".")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No verification run yet", result.stderr)

    def test_last_after_run(self):
        self.config("%s -c pass" % sys.executable)
        self.verify("run", "--cwd", ".")
        self.assertEqual(self.json_out(self.verify("last", "--json", "--cwd", "."))
                         ["summary"], "test ok")

    def test_init_twice_needs_force(self):
        self.assertOk(self.verify("init", "--cwd", "."))
        self.assertEqual(self.verify("init", "--cwd", ".").returncode, 1)
        self.assertOk(self.verify("init", "--force", "--cwd", "."))

    def test_detect_json(self):
        write(os.path.join(self.tmpdir, "go.mod"), "module x\n")
        data = self.json_out(self.verify("detect", "--json", "--cwd", "."))
        self.assertEqual([c["name"] for c in data["checks"]], ["lint", "test"])


class TestStateWithoutWorkflow(StateCliTestCase):
    """R-11: how "no workflow" is signalled."""

    def test_show_exits_one(self):
        result = self.state("show", "--cwd", ".")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No active workflow", result.stderr)

    def test_show_json_error_payload(self):
        result = self.state("show", "--json", "--cwd", ".")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("No active workflow", payload["error"])

    def test_next_agent_exits_zero_and_prints_none(self):
        result = self.state("next-agent", "--cwd", ".")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "none")

    def test_next_agent_json_exits_zero(self):
        result = self.state("next-agent", "--json", "--cwd", ".")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout),
                         {"phase": None, "agent": None, "escalation": None})

    def test_mutators_exit_one_without_a_traceback(self):
        for args in (
            ["start-agent", "architect"],
            ["complete-agent", "architect"],
            ["skip-agent", "architect"],
            ["confirm-spec", "--spec-file", "s.md"],
            ["set-mode", "auto"],
            ["complete"],
            ["abort"],
            ["log-append", "--agent", "a", "--phase", "BUILD", "--summary", "s"],
        ):
            result = self.state(*(args + ["--cwd", "."]))
            self.assertEqual(
                result.returncode, 1,
                "%s should exit 1 with no workflow" % args[0],
            )
            self.assertNotIn("Traceback", result.stderr, args[0])


LEGACY_STATE = {
    # v0.6-era hand-written file: no execution_mode, spec_file, log_file,
    # spec_confirmed, workflow_id, phase_order, created_at/updated_at, and
    # phase blocks missing completed/active/skipped.
    "feature": "Legacy hand written workflow",
    "type": "refactor",
    "status": "in_progress",
    "phases": {
        "THINK": {"agents": ["architect"]},
        "BUILD": {"agents": ["backend"], "completed": []},
    },
    "agent_log": [{"agent": "architect", "phase": "THINK"}],
}


class TestStateLegacySchema(StateCliTestCase):
    """R-4/R-10: the repo's own state.json was missing half the v0.10 schema."""

    def setUp(self):
        CliTestCase.setUp(self)
        self.state_path = os.path.join(self.coregy, "state.json")
        write(self.state_path, json.dumps(LEGACY_STATE, indent=2))

    def test_show_json_fills_in_the_missing_fields(self):
        data = self.json_out(self.state("show", "--json", "--cwd", "."))
        self.assertEqual(data["execution_mode"], "guided")
        self.assertFalse(data["spec_confirmed"])
        self.assertIsNone(data["spec_file"])
        self.assertTrue(data["workflow_id"])
        self.assertTrue(data["log_file"].startswith("log-"))
        self.assertEqual(data["phase_order"], ["THINK", "BUILD"])
        for phase in ("THINK", "BUILD"):
            block = data["phases"][phase]
            self.assertEqual(block["completed"], [])
            self.assertEqual(block["skipped"], [])
            self.assertIsNone(block["active"])
        entry = data["agent_log"][0]
        self.assertIsNone(entry["completed_at"])
        self.assertEqual(entry["kb_files_modified"], [])

    def test_show_text_does_not_crash(self):
        result = self.state("show", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("Progress: 0/2 agents (0%)", result.stdout)

    def test_read_only_subcommands_do_not_write(self):
        """show/next-agent normalise in memory only."""
        before = digest_tree(self.coregy)
        self.assertOk(self.state("show", "--cwd", "."))
        self.assertOk(self.state("show", "--json", "--cwd", "."))
        self.assertOk(self.state("next-agent", "--cwd", "."))
        self.assertOk(self.state("next-agent", "--json", "--cwd", "."))
        self.assertEqual(before, digest_tree(self.coregy))

    def test_next_agent_works(self):
        data = self.json_out(self.state("next-agent", "--json", "--cwd", "."))
        self.assertEqual(data, {"phase": "THINK", "agent": "architect",
                                "escalation": None})

    def test_start_agent_heals_the_file_on_disk(self):
        data = self.json_out(self.state("start-agent", "architect", "--cwd", "."))
        self.assertEqual(data["phase"], "THINK")
        healed = self.read_state()
        self.assertIn("execution_mode", healed)
        self.assertIn("workflow_id", healed)
        self.assertIn("phase_order", healed)
        self.assertIsNotNone(healed["phases"]["THINK"]["active"])

    def test_complete_agent_works(self):
        data = self.json_out(self.state(
            "complete-agent", "architect", "--summary", "s", "--cwd", ".",
        ))
        self.assertIn("architect", data["phases"]["THINK"]["completed"])

    def test_every_mutator_survives_a_legacy_file(self):
        for args in (
            ["skip-agent", "backend"],
            ["confirm-spec", "--spec-file", "spec-legacy.md"],
            ["set-mode", "auto"],
            ["log-append", "--agent", "a", "--phase", "THINK", "--summary", "s"],
            ["complete"],
        ):
            write(self.state_path, json.dumps(LEGACY_STATE, indent=2))
            result = self.state(*(args + ["--cwd", "."]))
            self.assertOk(result, "%s crashed on a legacy state.json" % args[0])
            self.assertNotIn("Traceback", result.stderr)

    def test_abort_survives_a_legacy_file(self):
        data = self.json_out(self.state("abort", "--cwd", "."))
        self.assertEqual(data["status"], "aborted")

    def test_init_workflow_still_guards_a_legacy_in_progress_file(self):
        result = self.state(
            "init-workflow", "--feature", "New", "--type", "refactor",
            "--phases", '{"BUILD":["backend"]}', "--cwd", ".",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("in progress", result.stderr)

    def test_empty_phases_object_does_not_crash(self):
        write(self.state_path, json.dumps({"feature": "x", "phases": {}}))
        result = self.state("show", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("Progress: 0/0 agents (0%)", result.stdout)

    def test_phase_order_naming_a_missing_phase_is_pruned(self):
        write(self.state_path, json.dumps({
            "feature": "x",
            "status": "in_progress",
            "phases": {"BUILD": {"agents": ["backend"]}},
            "phase_order": ["THINK", "BUILD", "SHIP"],
        }))
        data = self.json_out(self.state("show", "--json", "--cwd", "."))
        self.assertEqual(data["phase_order"], ["BUILD"])


# =====================================================================
# R4 -- health.py
# =====================================================================


class TestHealthCli(CliTestCase):
    def setUp(self):
        CliTestCase.setUp(self)
        write(os.path.join(self.coregy, "profile.yaml"),
              "project:\n  name: fixture-project\n  type: python\n")
        write(os.path.join(self.kb, "architecture.md"),
              "---\ntags: [arch]\nauthor_agent: architect\nstatus: active\n---\n"
              "# Architecture\n\n## Overview\n\nReal content here.\nMore lines.\n")
        write(os.path.join(self.kb, "tech-debt.md"),
              "# Tech Debt\n\n## Item one\n\nPriority: high\nSomething to fix.\n")

    def test_report_text(self):
        result = self.run_cli("health.py", "report", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("Project Health", result.stdout)
        self.assertIn("Knowledge Base:", result.stdout)
        self.assertIn("Tech Debt:", result.stdout)

    def test_report_json(self):
        result = self.run_cli("health.py", "report", "--json", "--cwd", ".")
        data = self.json_out(result)
        for key in ("kb", "tech_debt", "workflows",
                    "dependencies", "recommendations"):
            self.assertIn(key, data)

    def test_report_json_section_maps_flag_to_report_key(self):
        cases = {
            "kb": "kb",
            "tech-debt": "tech_debt",
            "workflows": "workflows",
            "dependencies": "dependencies",
            "recommendations": "recommendations",
        }
        for flag, key in cases.items():
            data = self.json_out(self.run_cli(
                "health.py", "report", "--json", "--section", flag, "--cwd", ".",
            ))
            self.assertEqual(
                list(data.keys()), [key],
                "--section %s should emit only the %r key" % (flag, key),
            )

    def test_report_text_section_filters_lines(self):
        full = self.run_cli("health.py", "report", "--cwd", ".").stdout
        filtered = self.run_cli(
            "health.py", "report", "--section", "kb", "--cwd", ".",
        ).stdout
        self.assertIn("Knowledge Base:", filtered)
        self.assertNotIn("Tech Debt:", filtered)
        self.assertLess(len(filtered.splitlines()), len(full.splitlines()))

    def test_unknown_section_is_a_usage_error(self):
        result = self.run_cli(
            "health.py", "report", "--section", "bogus", "--cwd", ".",
        )
        self.assertEqual(result.returncode, 2)

    def test_missing_coregy_dir_exits_one(self):
        """R-12: /health branches on this exit code."""
        shutil.rmtree(self.coregy)
        result = self.run_cli("health.py", "report", "--cwd", ".")
        self.assertEqual(result.returncode, 1)
        self.assertIn("run /coregy-workflow:init first", result.stderr)

    def test_missing_coregy_dir_json_error_payload(self):
        shutil.rmtree(self.coregy)
        result = self.run_cli("health.py", "report", "--json", "--cwd", ".")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])


# =====================================================================
# R5 -- kb_index.py
# =====================================================================


class TestKbIndexCli(CliTestCase):
    def setUp(self):
        CliTestCase.setUp(self)
        write(os.path.join(self.kb, "architecture.md"),
              "---\ntags: [cli, wiring]\nauthor_agent: architect\n"
              "status: active\n---\n# Architecture\n\n## Overview\n\nText.\n")
        write(os.path.join(self.kb, "decisions.md"),
              "---\ntags: [adr]\nauthor_agent: backend\nstatus: archived\n---\n"
              "# Decisions\n\n## ADR-001\n\nText.\n")

    def index_path(self):
        return os.path.join(self.kb, "_index.json")

    def test_build_creates_the_index(self):
        result = self.run_cli("kb_index.py", "build", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("Indexed 2 file(s) ->", result.stdout)
        self.assertTrue(os.path.isfile(self.index_path()))

    def test_build_json(self):
        data = self.json_out(
            self.run_cli("kb_index.py", "build", "--json", "--cwd", ".")
        )
        self.assertEqual(len(data["entries"]), 2)
        files = sorted(e["file"] for e in data["entries"])
        self.assertEqual(files, ["architecture.md", "decisions.md"])

    def test_build_with_custom_kb_dir(self):
        custom = os.path.join(self.tmpdir, "docs")
        write(os.path.join(custom, "note.md"), "# Note\n\n## S\n\nText.\n")
        result = self.run_cli(
            "kb_index.py", "build", "--kb-dir", custom, "--cwd", ".",
        )
        self.assertOk(result)
        self.assertTrue(os.path.isfile(os.path.join(custom, "_index.json")))

    def test_build_on_an_empty_kb_dir_still_exits_zero(self):
        empty = os.path.join(self.tmpdir, "empty")
        os.makedirs(empty)
        data = self.json_out(self.run_cli(
            "kb_index.py", "build", "--kb-dir", empty, "--json", "--cwd", ".",
        ))
        self.assertEqual(data["entries"], [])

    def test_search_before_build_exits_one(self):
        result = self.run_cli("kb_index.py", "search", "--cwd", ".")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No index at", result.stderr)
        self.assertIn("kb_index.py build", result.stderr)

    def test_search_by_tag(self):
        self.run_cli("kb_index.py", "build", "--cwd", ".")
        data = self.json_out(self.run_cli(
            "kb_index.py", "search", "--tag", "cli", "--json", "--cwd", ".",
        ))
        self.assertEqual([e["file"] for e in data], ["architecture.md"])

    def test_search_by_agent_and_status(self):
        self.run_cli("kb_index.py", "build", "--cwd", ".")
        data = self.json_out(self.run_cli(
            "kb_index.py", "search", "--agent", "backend",
            "--status", "archived", "--json", "--cwd", ".",
        ))
        self.assertEqual([e["file"] for e in data], ["decisions.md"])

    def test_search_without_filters_lists_everything(self):
        self.run_cli("kb_index.py", "build", "--cwd", ".")
        result = self.run_cli("kb_index.py", "search", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("2 match(es).", result.stdout)
        self.assertIn("tags=[cli,wiring]", result.stdout)
        self.assertIn("agent=architect", result.stdout)

    def test_search_with_no_hits(self):
        self.run_cli("kb_index.py", "build", "--cwd", ".")
        result = self.run_cli(
            "kb_index.py", "search", "--tag", "nonexistent", "--cwd", ".",
        )
        self.assertOk(result)
        self.assertIn("0 match(es).", result.stdout)


# =====================================================================
# R6 -- kb_archive.py
# =====================================================================


def big_kb_file(sections=6, lines_per_section=6):
    parts = ["# Title\n", "\nPreamble line.\n"]
    for i in range(sections):
        parts.append("\n## Section %d\n" % i)
        for j in range(lines_per_section):
            parts.append("Body line %d-%d.\n" % (i, j))
    return "".join(parts)


class TestKbArchiveCli(CliTestCase):
    def setUp(self):
        CliTestCase.setUp(self)
        write(os.path.join(self.kb, "decisions.md"), big_kb_file())
        write(os.path.join(self.kb, "small.md"), "# Small\n\n## S\n\nText.\n")

    def test_check_reports_nothing_under_the_default_threshold(self):
        result = self.run_cli("kb_archive.py", "check", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("All KB files under threshold (500 lines).", result.stdout)

    def test_check_reports_oversized_files(self):
        result = self.run_cli(
            "kb_archive.py", "check", "--threshold", "10", "--cwd", ".",
        )
        self.assertOk(result)
        self.assertIn("1 file(s) over 10 lines:", result.stdout)
        self.assertIn("decisions.md", result.stdout)
        self.assertNotIn("small.md", result.stdout)

    def test_check_json_shape(self):
        data = self.json_out(self.run_cli(
            "kb_archive.py", "check", "--threshold", "10", "--json", "--cwd", ".",
        ))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["file"], "decisions.md")
        self.assertTrue(data[0]["needs_archival"])
        self.assertGreater(data[0]["lines"], 10)

    def test_check_never_mutates_the_knowledge_base(self):
        """R-3: check_all_kb_files() archives despite its name.

        `check` must compose a read-only sweep instead.
        """
        before = digest_tree(self.kb)
        for extra in ([], ["--json"]):
            result = self.run_cli(
                "kb_archive.py", "check", "--threshold", "1", "--cwd", ".",
                *extra
            )
            self.assertOk(result)
        self.assertEqual(
            before, digest_tree(self.kb),
            "kb_archive.py check rewrote the knowledge base",
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.kb, "archive")),
            "kb_archive.py check created an archive/ directory",
        )

    def test_run_archives_older_sections(self):
        result = self.run_cli(
            "kb_archive.py", "run", "--threshold", "10",
            "--keep-sections", "2", "--cwd", ".",
        )
        self.assertOk(result)
        self.assertIn("Archived 1 file(s):", result.stdout)
        self.assertIn("decisions.md -> archive/", result.stdout)
        self.assertIn("sections moved", result.stdout)

        archive_dir = os.path.join(self.kb, "archive")
        self.assertTrue(os.path.isdir(archive_dir))
        self.assertEqual(len(os.listdir(archive_dir)), 1)

        with open(os.path.join(self.kb, "decisions.md")) as f:
            remaining = f.read()
        self.assertIn("## Section 5", remaining)
        self.assertIn("## Section 4", remaining)
        self.assertNotIn("## Section 0", remaining)

    def test_run_json_shape(self):
        data = self.json_out(self.run_cli(
            "kb_archive.py", "run", "--threshold", "10", "--keep-sections", "2",
            "--json", "--cwd", ".",
        ))
        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertEqual(entry["source_file"], "decisions.md")
        self.assertEqual(entry["archived_sections"], 4)
        self.assertIn("archive", entry["archive_file"])
        self.assertGreater(entry["remaining_lines"], 0)

    def test_keep_sections_is_honoured(self):
        """check_all_kb_files() cannot express this -- run must not use it."""
        self.run_cli(
            "kb_archive.py", "run", "--threshold", "10", "--keep-sections", "1",
            "--cwd", ".",
        )
        with open(os.path.join(self.kb, "decisions.md")) as f:
            remaining = f.read()
        self.assertIn("## Section 5", remaining)
        self.assertNotIn("## Section 4", remaining)

    def test_run_with_nothing_to_do(self):
        result = self.run_cli("kb_archive.py", "run", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("Nothing to archive.", result.stdout)

    def test_run_is_idempotent_at_the_same_threshold(self):
        self.run_cli(
            "kb_archive.py", "run", "--threshold", "10", "--keep-sections", "2",
            "--cwd", ".",
        )
        after_first = digest_tree(self.kb)
        result = self.run_cli(
            "kb_archive.py", "run", "--threshold", "10", "--keep-sections", "2",
            "--cwd", ".",
        )
        self.assertOk(result)
        self.assertIn("Nothing to archive.", result.stdout)
        self.assertEqual(after_first, digest_tree(self.kb))

    def test_missing_kb_dir_exits_zero(self):
        shutil.rmtree(self.kb)
        result = self.run_cli("kb_archive.py", "check", "--cwd", ".")
        self.assertOk(result)


# =====================================================================
# R7 -- contracts.py
# =====================================================================


class TestContractsCli(CliTestCase):
    def test_list_text(self):
        result = self.run_cli("contracts.py", "list", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("architect -> backend", result.stdout)
        self.assertIn("architect-to-backend.yaml", result.stdout)
        self.assertIn("contract(s).", result.stdout)

    def test_list_json(self):
        data = self.json_out(
            self.run_cli("contracts.py", "list", "--json", "--cwd", ".")
        )
        self.assertTrue(data)
        pairs = {(c["from"], c["to"]) for c in data}
        self.assertIn(("architect", "backend"), pairs)
        self.assertIn(("backend", "unit-tester"), pairs)

    def test_list_uses_the_plugin_contracts_dir_by_default(self):
        """Contracts live in the plugin, not the project -- no --contracts-dir
        needed from an arbitrary cwd."""
        data = self.json_out(
            self.run_cli("contracts.py", "list", "--json", "--cwd", ".")
        )
        self.assertEqual(
            len(data),
            len([f for f in os.listdir(CONTRACTS_DIR) if f.endswith(".yaml")]),
        )

    def test_list_with_an_empty_contracts_dir(self):
        empty = os.path.join(self.tmpdir, "no-contracts")
        os.makedirs(empty)
        result = self.run_cli(
            "contracts.py", "list", "--contracts-dir", empty, "--cwd", ".",
        )
        self.assertOk(result)
        self.assertIn("0 contract(s).", result.stdout)

    def test_from_flag_maps_to_from_agent(self):
        """R-2: `from` is a Python keyword; dest must be from_agent."""
        result = self.run_cli(
            "contracts.py", "validate",
            "--from", "architect", "--to", "backend", "--cwd", ".",
        )
        self.assertOk(result)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("architect -> backend", result.stdout)

    def test_validate_exits_zero_on_advisory_warnings(self):
        """R-7: warnings must not look like a hard failure to an agent."""
        result = self.run_cli(
            "contracts.py", "validate",
            "--from", "architect", "--to", "backend", "--json", "--cwd", ".",
        )
        data = self.json_out(result)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(data["contract"], "architect-to-backend.yaml")
        self.assertTrue(
            data["warnings"],
            "an empty KB should produce advisory warnings",
        )
        self.assertFalse(data["passed"])

    def test_validate_text_output_lists_warnings(self):
        result = self.run_cli(
            "contracts.py", "validate",
            "--from", "architect", "--to", "backend", "--cwd", ".",
        )
        self.assertOk(result)
        self.assertIn("warning(s)", result.stdout)
        self.assertIn("  - ", result.stdout)

    def test_strict_exits_one_on_failure(self):
        result = self.run_cli(
            "contracts.py", "validate", "--from", "architect", "--to", "backend",
            "--strict", "--cwd", ".",
        )
        self.assertEqual(result.returncode, 1)

    def test_missing_contract_is_a_silent_pass(self):
        """R-6: an unknown pair must no-op, not fail."""
        data = self.json_out(self.run_cli(
            "contracts.py", "validate", "--from", "nobody", "--to", "nowhere",
            "--json", "--cwd", ".",
        ))
        self.assertIsNone(data["contract"])
        self.assertTrue(data["passed"])
        self.assertEqual(data["warnings"], [])

    def test_missing_contract_text_output(self):
        result = self.run_cli(
            "contracts.py", "validate", "--from", "nobody", "--to", "nowhere",
            "--cwd", ".",
        )
        self.assertOk(result)
        self.assertIn("No contract for nobody -> nowhere", result.stdout)

    def test_code_reviewer_to_builder_alias_resolves(self):
        """R-6: backend/frontend must pass `--to builder` for the re-work check."""
        data = self.json_out(self.run_cli(
            "contracts.py", "validate", "--from", "code-reviewer",
            "--to", "builder", "--json", "--cwd", ".",
        ))
        self.assertEqual(data["contract"], "code-reviewer-to-builder.yaml")

    def test_validate_requires_both_agents(self):
        result = self.run_cli(
            "contracts.py", "validate", "--from", "architect", "--cwd", ".",
        )
        self.assertEqual(result.returncode, 2)

    def test_validate_against_a_populated_kb_has_fewer_warnings(self):
        empty = self.json_out(self.run_cli(
            "contracts.py", "validate", "--from", "architect", "--to", "backend",
            "--json", "--cwd", ".",
        ))
        # Point --kb-dir at the repo's own KB, which architect really did fill in.
        populated = self.json_out(self.run_cli(
            "contracts.py", "validate", "--from", "architect", "--to", "backend",
            "--kb-dir", os.path.join(REPO_ROOT, ".coregy", "knowledge"),
            "--json", "--cwd", ".",
        ))
        self.assertLess(len(populated["warnings"]), len(empty["warnings"]))


# =====================================================================
# R8 -- ci_monitor.py
#
# Driven with a PATH that contains no `gh`, so the "CI unavailable" branch is
# deterministic and no network call is ever made.
# =====================================================================


class TestCiMonitorCli(CliTestCase):
    def setUp(self):
        CliTestCase.setUp(self)
        self.empty_bin = os.path.join(self.tmpdir, "empty-bin")
        os.makedirs(self.empty_bin)
        self.env["PATH"] = self.empty_bin
        write(os.path.join(self.kb, "tech-debt.md"), "# Tech Debt\n\nNone.\n")

    def test_status_text_when_gh_is_unavailable(self):
        result = self.run_cli("ci_monitor.py", "status", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("CI status unavailable", result.stdout)

    def test_status_json_when_gh_is_unavailable(self):
        data = self.json_out(
            self.run_cli("ci_monitor.py", "status", "--json", "--cwd", ".")
        )
        self.assertEqual(data, {
            "available": False, "status": "unknown",
            "branch": None, "checks": [],
        })

    def test_status_exits_zero_even_without_gh(self):
        """"gh not installed" is a normal state, not an error."""
        for extra in ([], ["--json"], ["--raw", "--json"]):
            result = self.run_cli(
                "ci_monitor.py", "status", "--cwd", ".", *extra
            )
            self.assertEqual(result.returncode, 0)

    def test_summary_text(self):
        result = self.run_cli("ci_monitor.py", "summary", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("CI summary: status=unknown, failures=0", result.stdout)

    def test_summary_json(self):
        data = self.json_out(
            self.run_cli("ci_monitor.py", "summary", "--json", "--cwd", ".")
        )
        self.assertEqual(data["status"], "unknown")
        self.assertEqual(data["failure_count"], 0)
        self.assertEqual(data["common_failures"], [])

    def test_feedback_text_with_nothing_to_do(self):
        result = self.run_cli("ci_monitor.py", "feedback", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("No CI failures to process.", result.stdout)

    def test_feedback_json_with_nothing_to_do(self):
        data = self.json_out(
            self.run_cli("ci_monitor.py", "feedback", "--json", "--cwd", ".")
        )
        self.assertEqual(data["failures"], [])
        self.assertFalse(data["tech_debt_updated"])

    def test_feedback_does_not_touch_tech_debt_when_there_is_nothing(self):
        """R-8: feedback appends on every run -- but only when there are
        failures to report."""
        before = digest_tree(self.kb)
        self.assertOk(self.run_cli("ci_monitor.py", "feedback", "--cwd", "."))
        self.assertEqual(before, digest_tree(self.kb))


# =====================================================================
# R9 -- team.py
# =====================================================================


class TestTeamCli(CliTestCase):
    def team_path(self):
        return os.path.join(self.coregy, "team.yaml")

    def with_members(self):
        """A team with members, so an unlisted user falls back to developer
        (with no members at all everyone is lead -- the solo-project case)."""
        write(self.team_path(), "members:\n  - name: bob\n    role: lead\n")

    def test_init_creates_team_yaml(self):
        result = self.run_cli("team.py", "init", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("Created .coregy/team.yaml", result.stdout)
        self.assertTrue(os.path.isfile(self.team_path()))
        with open(self.team_path()) as f:
            self.assertIn("roles:", f.read())

    def test_init_refuses_to_overwrite(self):
        self.run_cli("team.py", "init", "--cwd", ".")
        write(self.team_path(), "roles:\n  custom: {}\n")
        result = self.run_cli("team.py", "init", "--cwd", ".")
        self.assertEqual(result.returncode, 1)
        self.assertIn("already exists", result.stderr)
        with open(self.team_path()) as f:
            self.assertIn("custom", f.read())

    def test_init_force_overwrites(self):
        write(self.team_path(), "roles:\n  custom: {}\n")
        result = self.run_cli("team.py", "init", "--force", "--cwd", ".")
        self.assertOk(result)
        with open(self.team_path()) as f:
            self.assertNotIn("custom", f.read())

    def test_init_creates_the_coregy_dir_if_absent(self):
        shutil.rmtree(self.coregy)
        result = self.run_cli("team.py", "init", "--cwd", ".")
        self.assertOk(result)
        self.assertTrue(os.path.isfile(self.team_path()))

    def test_show_without_team_yaml_uses_defaults(self):
        result = self.run_cli("team.py", "show", "--cwd", ".")
        self.assertOk(result)
        self.assertIn("(no team.yaml -- showing built-in defaults)", result.stdout)
        self.assertIn("Roles:", result.stdout)
        self.assertIn("lead", result.stdout)

    def test_show_after_init(self):
        self.run_cli("team.py", "init", "--cwd", ".")
        result = self.run_cli("team.py", "show", "--cwd", ".")
        self.assertOk(result)
        self.assertNotIn("(no team.yaml", result.stdout)
        self.assertIn("Team (.coregy/team.yaml)", result.stdout)
        self.assertIn("Current user: tester", result.stdout)

    def test_show_json(self):
        data = self.json_out(
            self.run_cli("team.py", "show", "--json", "--cwd", ".")
        )
        self.assertFalse(data["config_exists"])
        self.assertIn("lead", data["roles"])
        self.assertIn("summary", data)
        self.assertEqual(data["members"], [])

    def test_check_agent_allowed_exits_zero(self):
        result = self.run_cli(
            "team.py", "check-agent", "backend", "--user", "alice", "--cwd", ".",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("ALLOWED:", result.stdout)

    def test_check_agent_denied_exits_one(self):
        """R-9: denial is exit 1 -- never chain this under &&."""
        self.with_members()
        result = self.run_cli(
            "team.py", "check-agent", "devops", "--user", "alice", "--cwd", ".",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("DENIED:", result.stdout)

    def test_check_agent_json_payload(self):
        self.with_members()
        result = self.run_cli(
            "team.py", "check-agent", "devops", "--user", "alice",
            "--json", "--cwd", ".",
        )
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertFalse(data["allowed"])
        self.assertEqual(data["agent"], "devops")
        self.assertEqual(data["user"], "alice")
        self.assertEqual(data["role"], "developer")
        self.assertTrue(data["reason"])

    def test_check_agent_respects_a_configured_role(self):
        write(self.team_path(),
              "roles:\n"
              "  lead:\n"
              "    agents: all\n"
              "members:\n"
              "  - name: alice\n"
              "    role: lead\n")
        result = self.run_cli(
            "team.py", "check-agent", "devops", "--user", "alice",
            "--json", "--cwd", ".",
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertTrue(data["allowed"])
        self.assertEqual(data["role"], "lead")

    def test_check_workflow_denied_for_a_developer(self):
        self.with_members()
        result = self.run_cli(
            "team.py", "check-workflow", "skip_agent", "--user", "alice",
            "--json", "--cwd", ".",
        )
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertFalse(data["allowed"])
        self.assertEqual(data["action"], "skip_agent")

    def test_check_workflow_rejects_an_unknown_action(self):
        result = self.run_cli(
            "team.py", "check-workflow", "delete_everything", "--cwd", ".",
        )
        self.assertEqual(result.returncode, 2)

    def test_check_agent_defaults_the_user_from_the_environment(self):
        data = json.loads(self.run_cli(
            "team.py", "check-agent", "backend", "--json", "--cwd", ".",
        ).stdout)
        self.assertEqual(data["user"], "tester")


# =====================================================================
# R1 -- runtime variable guard
#
# `${PLUGIN_ROOT}` does not exist in Claude Code. Every bash block using it
# expanded to an empty path and failed silently for 12 versions. This test is
# cheap insurance against it coming back.
# =====================================================================

SKIP_BINARY_EXT = {
    ".db", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pyc",
    ".woff", ".woff2", ".ttf", ".zip", ".gz",
}
CORRECT_VAR = "${CLAUDE_PLUGIN_ROOT}"
# Assembled so this test file's own text is not a false positive for a grep.
BAD_VAR = "${" + "PLUGIN_ROOT}"


def plugin_text_files():
    for dirpath, dirnames, filenames in os.walk(PLUGIN_ROOT_DIR):
        dirnames[:] = [
            d for d in dirnames
            if d not in ("__pycache__", ".git", "graphify-out")
        ]
        for fname in filenames:
            if os.path.splitext(fname)[1].lower() in SKIP_BINARY_EXT:
                continue
            yield os.path.join(dirpath, fname)


class TestPluginRootVariable(unittest.TestCase):
    def test_no_file_uses_the_nonexistent_plugin_root_variable(self):
        offenders = []
        for path in plugin_text_files():
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            for i, line in enumerate(content.splitlines(), 1):
                if BAD_VAR in line.replace(CORRECT_VAR, ""):
                    offenders.append(
                        "%s:%d" % (os.path.relpath(path, REPO_ROOT), i)
                    )
        self.assertEqual(
            offenders, [],
            "use %s -- %s is not a real Claude Code variable:\n%s"
            % (CORRECT_VAR, BAD_VAR, "\n".join(offenders)),
        )

    def test_the_correct_variable_is_actually_used(self):
        """Guard against the guard passing because nothing references it."""
        hits = 0
        for path in plugin_text_files():
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                hits += f.read().count(CORRECT_VAR)
        self.assertGreater(hits, 20, "expected many %s references" % CORRECT_VAR)

    def test_every_referenced_plugin_path_exists(self):
        """A wired command is only real if the script it names is really there."""
        import re

        pattern = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[A-Za-z0-9_./-]*)")
        missing = []
        for path in plugin_text_files():
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            for ref in pattern.findall(content):
                target = os.path.join(PLUGIN_ROOT_DIR, ref.lstrip("/"))
                if not os.path.exists(target.rstrip("/")):
                    missing.append(
                        "%s -> %s" % (os.path.relpath(path, REPO_ROOT), ref)
                    )
        self.assertEqual(sorted(set(missing)), [], "dangling plugin path refs")


# =====================================================================
# Every bash block in a command/agent file must actually parse
#
# A correct script path is not enough: `tracker.py search --after ...` and
# `mcp_setup.py jira --cwd .` both named a real script and still exited 2,
# which fails exactly as silently as ${PLUGIN_ROOT} did. This walks every
# invocation embedded in the plugin's markdown and checks the subcommand and
# every long flag against the script's own --help.
# =====================================================================

# `<...>` author placeholders that stand in for a value the LLM fills in.
_PLACEHOLDER_RE = re.compile(r"<[^>]*>")


def _iter_markdown_invocations():
    """Yield (relpath, lineno, argv_tokens) for each embedded python3 call."""
    for path in plugin_text_files():
        if not path.endswith(".md"):
            continue
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            start = i + 1
            if CORRECT_VAR in line and "python3" in line:
                buf = line
                while buf.rstrip().endswith("\\") and i + 1 < len(lines):
                    i += 1
                    buf = buf.rstrip()[:-1] + " " + lines[i]
                # Inline code spans: keep only the fragment holding the call.
                if "`" in buf:
                    spans = [s for s in buf.split("`") if "python3" in s]
                    if not spans:
                        i += 1
                        continue
                    buf = spans[0]
                buf = buf[buf.index("python3"):]
                buf = _PLACEHOLDER_RE.sub("X", buf).replace("[options]", "")
                try:
                    argv = shlex.split(buf)
                except ValueError:
                    argv = buf.split()
                yield os.path.relpath(path, REPO_ROOT), start, argv
            i += 1


_HELP_CACHE = {}


def _help_text(script, subcommand=None):
    key = (script, subcommand)
    if key not in _HELP_CACHE:
        args = ([subcommand] if subcommand else []) + ["--help"]
        _HELP_CACHE[key] = subprocess.run(
            [sys.executable, script] + args,
            capture_output=True, text=True, cwd=REPO_ROOT,
        ).stdout
    return _HELP_CACHE[key]


class TestEmbeddedInvocationsParse(unittest.TestCase):
    def test_every_documented_invocation_is_accepted_by_its_script(self):
        problems = []
        seen = 0
        for relpath, lineno, argv in _iter_markdown_invocations():
            if len(argv) < 2:
                continue
            script = argv[1].replace(CORRECT_VAR, PLUGIN_ROOT_DIR)
            if not os.path.isfile(script):
                continue  # covered by test_every_referenced_plugin_path_exists
            rest = argv[2:]
            seen += 1

            top_help = _help_text(script)
            # Subcommand names come from the `{a,b,c}` group argparse prints.
            # Matching against that set (rather than "first bare token") keeps
            # an option *value* such as the `.` in `--cwd .` from being
            # mistaken for the subcommand.
            # The trailing ` ...` distinguishes a subparser group from the
            # choices of an ordinary option such as `--mode {a,b,c}`.
            choices = set()
            for group in re.findall(r"\{([a-z0-9_,-]+)\}\s*\.\.\.", top_help):
                choices.update(group.split(","))
            subcommand = next((t for t in rest if t in choices), None)
            if choices and subcommand is None:
                problems.append(
                    "%s:%d %s has no subcommand from %s"
                    % (relpath, lineno, os.path.basename(script),
                       sorted(choices))
                )
                continue
            if subcommand is not None:
                pos = rest.index(subcommand)
                before, after = rest[:pos], rest[pos + 1:]
            else:
                before, after = rest, []

            for scope, flags in ((None, before), (subcommand, after)):
                if subcommand is None and scope is not None:
                    continue
                help_text = _help_text(script, scope)
                for token in flags:
                    if not token.startswith("--"):
                        continue
                    name = token.split("=", 1)[0]
                    if name not in help_text:
                        problems.append(
                            "%s:%d %s%s does not accept %s"
                            % (relpath, lineno, os.path.basename(script),
                               " " + scope if scope else "", name)
                        )

        self.assertGreater(seen, 50, "invocation scraper found almost nothing")
        self.assertEqual(sorted(set(problems)), [], "\n".join(sorted(set(problems))))


# =====================================================================
# Agents must record their work through state.py, not by hand
#
# Hand-written state.json is the documented root cause of the schema drift
# this workflow exists to fix, so the prose that told agents to do it must
# stay replaced.
# =====================================================================

AGENTS_DIR = os.path.join(PLUGIN_ROOT_DIR, "agents")


def agent_files():
    return sorted(
        os.path.join(AGENTS_DIR, f)
        for f in os.listdir(AGENTS_DIR)
        if f.endswith(".md")
    )


class TestCompleteAgentWithoutStartAgent(unittest.TestCase):
    """An agent invoked on its own still has to leave an audit trail.

    complete_agent() only fills in an *existing* open agent_log entry, so
    without the CLI-layer stub a standalone agent silently records nothing.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        run_script("state.py", [
            "init-workflow", "--feature", "audit trail", "--type", "refactor",
            "--phases", '{"VERIFY":["code-reviewer","spec-verifier"]}',
            "--cwd", ".",
        ], cwd=self.tmp)

    def _log(self):
        with open(os.path.join(self.tmp, ".coregy", "state.json")) as f:
            return json.load(f)["agent_log"]

    def test_completing_an_unstarted_agent_still_logs_it(self):
        result = run_script("state.py", [
            "complete-agent", "code-reviewer", "--summary", "reviewed",
            "--kb-files", "tech-debt.md", "--cwd", ".",
        ], cwd=self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)

        entries = [e for e in self._log() if e["agent"] == "code-reviewer"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["output_summary"], "reviewed")
        self.assertEqual(entries[0]["kb_files_modified"], ["tech-debt.md"])
        self.assertIsNotNone(entries[0]["completed_at"])
        self.assertEqual(entries[0]["phase"], "VERIFY")

    def test_a_second_complete_call_does_not_duplicate_the_entry(self):
        for _ in range(2):
            run_script("state.py", [
                "complete-agent", "code-reviewer", "--summary", "reviewed",
                "--cwd", ".",
            ], cwd=self.tmp)
        self.assertEqual(
            len([e for e in self._log() if e["agent"] == "code-reviewer"]), 1
        )

    def test_the_normal_start_then_complete_path_is_unchanged(self):
        run_script("state.py", ["start-agent", "code-reviewer", "--cwd", "."],
                   cwd=self.tmp)
        run_script("state.py", ["complete-agent", "code-reviewer",
                                "--summary", "reviewed", "--cwd", "."],
                   cwd=self.tmp)
        entries = [e for e in self._log() if e["agent"] == "code-reviewer"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["output_summary"], "reviewed")


class TestAgentsUseTheStateMachine(unittest.TestCase):
    def test_there_are_nine_agents(self):
        self.assertEqual(len(agent_files()), 9)

    def test_each_agent_calls_log_append_and_complete_agent(self):
        missing = []
        for path in agent_files():
            name = os.path.splitext(os.path.basename(path))[0]
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for needed in ("state.py log-append",
                           "state.py complete-agent %s" % name):
                if needed not in text:
                    missing.append("%s: %s" % (name, needed))
        self.assertEqual(missing, [], "\n".join(missing))

    def test_no_agent_still_says_to_hand_edit_state_json(self):
        offenders = []
        for path in agent_files():
            with open(path, encoding="utf-8") as f:
                if "Update `.coregy/state.json`:" in f.read():
                    offenders.append(os.path.basename(path))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
