"""Tests for the verification runner (verify.py)."""
import json
import os
import shutil
import subprocess
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

import verify
from verify import (
    failure_issues,
    load_last,
    resolve_checks,
    run_checks,
    workspace_fingerprint,
    write_default_config,
)

PY = sys.executable
HAS_GIT = shutil.which("git") is not None


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.cwd = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cwd, True)

    def write(self, rel, content=""):
        path = os.path.join(self.cwd, rel)
        os.makedirs(os.path.dirname(path) or self.cwd, exist_ok=True)
        with open(path, "w") as f:
            f.write(content if isinstance(content, str) else json.dumps(content))
        return path

    def mkdir(self, rel):
        os.makedirs(os.path.join(self.cwd, rel), exist_ok=True)

    def commands(self):
        return {c["name"]: c["command"] for c in resolve_checks(self.cwd)}

    def config(self, checks, timeout=None):
        lines = ["checks:"] + ['  %s: "%s"' % (k, v) for k, v in checks.items()]
        if timeout is not None:
            lines.append("timeout: %d" % timeout)
        self.write(".coregy/verify.yaml", "\n".join(lines) + "\n")


class TestNodeDetection(ProjectCase):
    def test_scripts_with_npm(self):
        self.write("package.json", {"scripts": {
            "lint": "eslint .", "typecheck": "tsc --noEmit", "test": "vitest"}})
        self.assertEqual(self.commands(), {
            "lint": "npm run lint", "typecheck": "npm run typecheck", "test": "npm test"})

    def test_package_manager_from_lockfile(self):
        self.write("package.json", {"scripts": {"lint": "x", "test": "y"}})
        self.write("pnpm-lock.yaml")
        self.assertEqual(self.commands(), {"lint": "pnpm lint", "test": "pnpm test"})

    def test_npm_placeholder_test_script_is_ignored(self):
        self.write("package.json", {"scripts": {
            "test": 'echo "Error: no test specified" && exit 1'}})
        self.assertEqual(self.commands(), {})

    def test_typescript_without_script_uses_tsc(self):
        self.write("package.json", {"devDependencies": {"typescript": "5.0.0"}})
        self.write("tsconfig.json", "{}")
        self.write("yarn.lock")
        self.assertEqual(self.commands(), {"typecheck": "yarn tsc --noEmit"})


class TestPythonDetection(ProjectCase):
    def test_pytest_ruff_mypy_from_pyproject(self):
        self.write("pyproject.toml",
                   "[tool.pytest.ini_options]\n[tool.ruff]\n[tool.mypy]\n")
        self.assertEqual(self.commands(), {
            "lint": "ruff check .", "typecheck": "python3 -m mypy .",
            "test": "python3 -m pytest -q"})

    def test_unittest_fallback(self):
        self.write("setup.py")
        self.mkdir("tests")
        self.assertEqual(self.commands(),
                         {"test": "python3 -m unittest discover -s tests"})

    def test_pytest_from_requirements(self):
        self.write("requirements-dev.txt", "pytest==8.0\nflake8\n")
        self.write(".flake8")
        self.assertEqual(self.commands(), {
            "lint": "python3 -m flake8", "test": "python3 -m pytest -q"})

    def test_uv_prefix(self):
        self.write("pyproject.toml", "[tool.pytest.ini_options]\n")
        self.write("uv.lock")
        self.assertEqual(self.commands(), {"test": "uv run python -m pytest -q"})

    def test_bare_directory_is_not_python(self):
        self.mkdir("tests")
        self.assertEqual(self.commands(), {})


class TestOtherStacks(ProjectCase):
    def test_go(self):
        self.write("go.mod", "module x\n")
        self.assertEqual(self.commands(), {"lint": "go vet ./...", "test": "go test ./..."})

    def test_go_with_golangci(self):
        self.write("go.mod", "module x\n")
        self.write(".golangci.yml")
        self.assertEqual(self.commands()["lint"], "golangci-lint run")

    def test_rust(self):
        self.write("Cargo.toml")
        self.assertEqual(self.commands()["test"], "cargo test")

    def test_maven_wrapper(self):
        self.write("pom.xml")
        self.write("mvnw")
        self.assertEqual(self.commands(), {"test": "./mvnw -q test"})

    def test_gradle(self):
        self.write("build.gradle.kts")
        self.assertEqual(self.commands(), {"test": "gradle test"})

    def test_dotnet(self):
        self.write("App.sln")
        self.assertEqual(self.commands(), {"test": "dotnet test"})

    def test_ruby(self):
        self.write("Gemfile")
        self.write(".rspec")
        self.write(".rubocop.yml")
        self.assertEqual(self.commands(), {
            "lint": "bundle exec rubocop", "test": "bundle exec rspec"})

    def test_php(self):
        self.write("composer.json", {"scripts": {"test": "phpunit"}})
        self.assertEqual(self.commands(), {"test": "composer test"})


class TestPrecedence(ProjectCase):
    def test_makefile_beats_language_detection(self):
        self.write("Makefile", "test:\n\tpytest -x\nlint: deps\n\truff .\nX := 1\n")
        self.write("pyproject.toml", "[tool.pytest.ini_options]\n[tool.ruff]\n")
        self.assertEqual(self.commands(), {"lint": "make lint", "test": "make test"})

    def test_makefile_variable_is_not_a_target(self):
        self.write("Makefile", "test := 1\n")
        self.assertEqual(self.commands(), {})

    def test_profile_testing_command(self):
        self.write(".coregy/profile.yaml",
                   'testing:\n  framework: unittest\n  command: "python3 -m unittest"\n')
        self.write("go.mod", "module x\n")
        self.assertEqual(self.commands(), {
            "lint": "go vet ./...", "test": "python3 -m unittest"})

    def test_override_replaces_and_disables(self):
        self.write("go.mod", "module x\n")
        self.config({"test": "go test -race ./...", "lint": ""})
        checks = resolve_checks(self.cwd)
        self.assertEqual([(c["name"], c["command"], c["source"]) for c in checks],
                         [("test", "go test -race ./...", "verify.yaml")])

    def test_override_adds_custom_check(self):
        self.config({"e2e": "npx playwright test"})
        self.assertEqual(self.commands(), {"e2e": "npx playwright test"})

    def test_lint_typecheck_test_order(self):
        self.write("pyproject.toml", "[tool.pytest.ini_options]\n[tool.ruff]\n[tool.mypy]\n")
        self.assertEqual([c["name"] for c in resolve_checks(self.cwd)],
                         ["lint", "typecheck", "test"])

    def test_profile_subdirectories(self):
        self.write("go.mod", "module x\n")
        self.write("web/package.json", {"scripts": {"test": "vitest", "lint": "eslint"}})
        self.write(".coregy/profile.yaml",
                   "frontend:\n  framework: react\n  dir: web/\nbackend:\n  dir: .\n")
        checks = resolve_checks(self.cwd)
        self.assertEqual([(c["name"], c["cwd"]) for c in checks], [
            ("lint", "."), ("lint:web", "web"), ("test", "."), ("test:web", "web")])


class TestRunChecks(ProjectCase):
    def run_cfg(self, checks, **kwargs):
        self.config(checks)
        return run_checks(self.cwd, **kwargs)

    def test_all_pass(self):
        result = self.run_cfg({"lint": "%s -c pass" % PY, "test": "%s -c pass" % PY})
        self.assertTrue(result["passed"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["summary"], "lint ok, test ok")
        self.assertEqual(result["checks"][0]["output_tail"], "")

    def test_failure_keeps_output_tail(self):
        cmd = "%s -c \"import sys; print('boom at a.py:3'); sys.exit(3)\"" % PY
        result = self.run_cfg({"test": cmd})
        self.assertFalse(result["passed"])
        check = result["checks"][0]
        self.assertEqual((check["status"], check["exit_code"]), ("failed", 3))
        self.assertIn("boom at a.py:3", check["output_tail"])

    def test_runs_every_check_unless_fail_fast(self):
        fail = "%s -c \"raise SystemExit(1)\"" % PY
        ok = "%s -c pass" % PY
        self.assertEqual(len(self.run_cfg({"lint": fail, "test": ok})["checks"]), 2)
        self.assertEqual(
            len(self.run_cfg({"lint": fail, "test": ok}, fail_fast=True)["checks"]), 1)

    def test_missing_tool_warns_but_does_not_fail(self):
        result = self.run_cfg({"lint": "definitely-not-a-real-tool-xyz",
                               "test": "%s -c pass" % PY})
        self.assertTrue(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "missing")
        self.assertTrue(any("not installed" in w for w in result["warnings"]))

    def test_only_missing_tools_is_not_verified(self):
        result = self.run_cfg({"test": "definitely-not-a-real-tool-xyz"})
        self.assertTrue(result["passed"])
        self.assertFalse(result["verified"])

    def test_timeout(self):
        result = self.run_cfg({"test": "%s -c \"import time; time.sleep(5)\"" % PY},
                              timeout=1)
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["status"], "timeout")
        self.assertIn("timed out", result["checks"][0]["output_tail"])

    def test_timeout_from_config(self):
        self.config({"test": "%s -c \"import time; time.sleep(5)\"" % PY}, timeout=1)
        self.assertEqual(run_checks(self.cwd)["checks"][0]["status"], "timeout")

    def test_ci_env_is_set(self):
        cmd = "%s -c \"import os, sys; sys.exit(0 if os.environ.get('CI') == '1' else 1)\"" % PY
        self.assertTrue(self.run_cfg({"test": cmd})["passed"])

    def test_only_filter(self):
        result = self.run_cfg({"lint": "%s -c pass" % PY, "test": "%s -c pass" % PY},
                              only=["test"])
        self.assertEqual([c["name"] for c in result["checks"]], ["test"])

    def test_nothing_detected(self):
        result = run_checks(self.cwd)
        self.assertTrue(result["passed"])
        self.assertFalse(result["verified"])
        self.assertIn("verify.yaml", result["warnings"][0])

    def test_writes_last_and_gitignore(self):
        self.run_cfg({"test": "%s -c pass" % PY})
        self.assertEqual(load_last(self.cwd)["summary"], "test ok")
        self.run_cfg({"test": "%s -c pass" % PY})
        with open(os.path.join(self.cwd, ".coregy", ".gitignore")) as f:
            self.assertEqual(f.read(), "verify-last.json\n")

    def test_gitignore_appends_to_existing(self):
        self.write(".coregy/.gitignore", "tracker.db")
        self.run_cfg({"test": "%s -c pass" % PY})
        with open(os.path.join(self.cwd, ".coregy", ".gitignore")) as f:
            self.assertEqual(f.read(), "tracker.db\nverify-last.json\n")

    def test_runs_in_check_directory(self):
        self.write("web/marker.txt", "x")
        self.write("web/package.json", {"scripts": {"test": "t"}})
        self.write(".coregy/profile.yaml", "frontend:\n  dir: web\n")
        checks = resolve_checks(self.cwd)
        checks[0]["command"] = "%s -c \"open('marker.txt')\"" % PY
        self.assertEqual(verify._run_one(self.cwd, checks[0], 30)["status"], "passed")


class TestFailureIssues(unittest.TestCase):
    def test_one_issue_per_failed_check(self):
        result = {"checks": [
            {"name": "lint", "status": "passed", "command": "l", "exit_code": 0,
             "output_tail": ""},
            {"name": "test", "status": "failed", "command": "pytest", "exit_code": 1,
             "output_tail": "a\n\nFAILED t.py::test_x\n1 failed"},
            {"name": "typecheck", "status": "timeout", "command": "mypy",
             "exit_code": None, "output_tail": "[coregy] timed out after 1s"},
        ]}
        issues = failure_issues(result)
        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0],
                         "test failed (`pytest`, exit 1): a | FAILED t.py::test_x | 1 failed")
        self.assertIn("timed out", issues[1])

    def test_separator_rules_are_dropped(self):
        tail = ("FAIL: test_add\n" + "-" * 70 + "\nAssertionError: -1 != 5\n\n"
                + "=" * 70 + "\nFAILED (failures=1)")
        result = {"checks": [{"name": "test", "status": "failed", "command": "t",
                              "exit_code": 1, "output_tail": tail}]}
        self.assertEqual(failure_issues(result)[0],
                         "test failed (`t`, exit 1): FAIL: test_add | "
                         "AssertionError: -1 != 5 | FAILED (failures=1)")

    def test_python_bytecode_is_not_written(self):
        result = {}
        with tempfile.TemporaryDirectory() as cwd:
            check = {"name": "test", "check": "test", "cwd": ".", "source": "x",
                     "command": "%s -c \"import os, sys; sys.exit(0 if "
                                "os.environ.get('PYTHONDONTWRITEBYTECODE') == '1' else 1)\"" % PY}
            result = verify._run_one(cwd, check, 30)
        self.assertEqual(result["status"], "passed")


@unittest.skipUnless(HAS_GIT, "git not installed")
class TestReuse(ProjectCase):
    def setUp(self):
        ProjectCase.setUp(self)
        for args in (["init", "-q"], ["config", "user.email", "t@t"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git"] + args, cwd=self.cwd, check=True)
        self.write("app.py", "x = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=self.cwd, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=self.cwd, check=True)
        # Each run appends a line, so a re-run is observable.
        self.counter = os.path.join(self.cwd, "..", os.path.basename(self.cwd) + ".runs")
        self.addCleanup(lambda: os.path.exists(self.counter) and os.remove(self.counter))
        self.config({"test": "%s -c \"open(r'%s', 'a').write('x')\"" % (PY, self.counter)})

    def runs(self):
        with open(self.counter) as f:
            return len(f.read())

    def test_reuse_skips_when_unchanged(self):
        run_checks(self.cwd)
        result = run_checks(self.cwd, reuse=True)
        self.assertTrue(result["reused"])
        self.assertEqual(self.runs(), 1)

    def test_coregy_changes_do_not_invalidate(self):
        run_checks(self.cwd)
        self.write(".coregy/state.json", "{}")
        self.assertTrue(run_checks(self.cwd, reuse=True)["reused"])

    def test_edit_invalidates(self):
        run_checks(self.cwd)
        self.write("app.py", "x = 2\n")
        self.assertFalse(run_checks(self.cwd, reuse=True)["reused"])
        self.assertEqual(self.runs(), 2)

    def test_new_untracked_file_invalidates(self):
        run_checks(self.cwd)
        self.write("new.py", "y = 1\n")
        self.assertFalse(run_checks(self.cwd, reuse=True)["reused"])

    def test_different_check_set_invalidates(self):
        run_checks(self.cwd, only=["lint"])
        self.assertFalse(run_checks(self.cwd, reuse=True)["reused"])

    def test_without_reuse_always_runs(self):
        run_checks(self.cwd)
        run_checks(self.cwd)
        self.assertEqual(self.runs(), 2)

    def test_fingerprint_outside_git_is_none(self):
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, True)
        self.assertIsNone(workspace_fingerprint(other))


class TestInit(ProjectCase):
    def test_writes_detected_commands(self):
        self.write("go.mod", "module x\n")
        path = write_default_config(self.cwd)
        checks = resolve_checks(self.cwd)
        self.assertTrue(os.path.isfile(path))
        # The template round-trips: detected values become explicit overrides
        # and the undetected typecheck stays disabled.
        self.assertEqual([(c["name"], c["command"], c["source"]) for c in checks], [
            ("lint", "go vet ./...", "verify.yaml"),
            ("test", "go test ./...", "verify.yaml")])

    def test_refuses_to_overwrite(self):
        write_default_config(self.cwd)
        with self.assertRaises(FileExistsError):
            write_default_config(self.cwd)
        write_default_config(self.cwd, force=True)


if __name__ == "__main__":
    unittest.main()
