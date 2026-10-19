"""Tests for ci_monitor.py — CI feedback loop."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

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

from ci_monitor import (
    get_ci_status,
    parse_test_failures,
    create_tech_debt_entry,
    suggest_fixes,
    get_ci_summary,
    run_ci_feedback,
)


# ---------------------------------------------------------------------------
# parse_test_failures tests
# ---------------------------------------------------------------------------


class TestParseTestFailuresPytest(unittest.TestCase):
    def test_parse_test_failures_pytest(self):
        output = (
            "===== FAILURES =====\n"
            "FAILED test_auth.py::TestLogin::test_invalid_password - AssertionError: expected 401\n"
            "FAILED test_auth.py::TestLogin::test_expired_token - TimeoutError: request timed out\n"
            "===== 2 failed =====\n"
        )
        failures = parse_test_failures(output)
        pytest_failures = [f for f in failures if f["file"] == "test_auth.py"]
        self.assertEqual(len(pytest_failures), 2)
        self.assertEqual(pytest_failures[0]["test_name"], "test_invalid_password")
        self.assertEqual(pytest_failures[0]["file"], "test_auth.py")
        self.assertIn("AssertionError", pytest_failures[0]["error"])
        self.assertEqual(pytest_failures[0]["type"], "test_failure")


class TestParseTestFailuresJest(unittest.TestCase):
    def test_parse_test_failures_jest(self):
        output = (
            "Test Suites: 1 failed\n"
            "FAIL src/components/Auth.test.tsx\n"
            "  Login component\n"
            "    x should render login form\n"
        )
        failures = parse_test_failures(output)
        jest_failures = [f for f in failures if f["type"] == "test_failure" and "test.tsx" in f.get("file", "")]
        self.assertGreaterEqual(len(jest_failures), 1)
        self.assertEqual(jest_failures[0]["file"], "src/components/Auth.test.tsx")


class TestParseTestFailuresGo(unittest.TestCase):
    def test_parse_test_failures_go(self):
        output = (
            "--- FAIL: TestCreateUser (0.02s)\n"
            "    handler_test.go:45: expected status 201, got 500\n"
            "--- FAIL: TestDeleteUser (0.01s)\n"
            "    handler_test.go:78: not found\n"
            "FAIL\n"
        )
        failures = parse_test_failures(output)
        go_failures = [f for f in failures if f["type"] == "test_failure" and "Go test" in f["error"]]
        self.assertEqual(len(go_failures), 2)
        self.assertEqual(go_failures[0]["test_name"], "TestCreateUser")
        self.assertEqual(go_failures[1]["test_name"], "TestDeleteUser")


class TestParseTestFailuresBuildError(unittest.TestCase):
    def test_parse_test_failures_build_error(self):
        output = (
            "src/index.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'.\n"
            "SyntaxError: Unexpected token }\n"
        )
        failures = parse_test_failures(output)
        build_errors = [f for f in failures if f["type"] == "build_error"]
        self.assertGreaterEqual(len(build_errors), 2)
        ts_errors = [f for f in build_errors if f["test_name"] == "TS2322"]
        self.assertEqual(len(ts_errors), 1)
        self.assertIn("Type", ts_errors[0]["error"])
        syntax_errors = [f for f in build_errors if f["test_name"] == "SyntaxError"]
        self.assertEqual(len(syntax_errors), 1)


class TestParseTestFailuresEmpty(unittest.TestCase):
    def test_parse_test_failures_empty(self):
        output = (
            "All tests passed.\n"
            "===== 42 passed in 3.21s =====\n"
        )
        failures = parse_test_failures(output)
        self.assertEqual(failures, [])

    def test_parse_test_failures_none(self):
        failures = parse_test_failures("")
        self.assertEqual(failures, [])

    def test_parse_test_failures_none_input(self):
        failures = parse_test_failures(None)
        self.assertEqual(failures, [])


class TestParseTestFailuresLint(unittest.TestCase):
    def test_parse_lint_eslint(self):
        output = (
            "src/App.tsx 12:5 error Unexpected var, use let or const no-var\n"
            "src/utils.ts 3:1 error Missing return type on function @typescript-eslint/explicit-function-return-type\n"
        )
        failures = parse_test_failures(output)
        lint_errors = [f for f in failures if f["type"] == "lint_error"]
        self.assertGreaterEqual(len(lint_errors), 2)

    def test_parse_lint_flake8(self):
        output = (
            "app/views.py:15:1: E302 expected 2 blank lines, got 1\n"
            "app/models.py:42:80: E501 line too long (95 > 79 characters)\n"
        )
        failures = parse_test_failures(output)
        flake8_errors = [f for f in failures if f["type"] == "lint_error" and f["file"].endswith(".py")]
        self.assertEqual(len(flake8_errors), 2)
        self.assertEqual(flake8_errors[0]["test_name"], "E302")
        self.assertEqual(flake8_errors[0]["file"], "app/views.py")


# ---------------------------------------------------------------------------
# create_tech_debt_entry tests
# ---------------------------------------------------------------------------


class TestCreateTechDebtEntry(unittest.TestCase):
    def test_create_tech_debt_entry_new(self):
        """Creates entry when tech-debt.md is empty or template."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_dir = os.path.join(tmpdir, ".coregy", "knowledge")
            os.makedirs(kb_dir)
            td_path = os.path.join(kb_dir, "tech-debt.md")
            with open(td_path, "w") as f:
                f.write("# Tech Debt\n\n> To be filled.\n")

            failures = [
                {"test_name": "test_login", "file": "test_auth.py", "error": "AssertionError", "type": "test_failure"},
            ]
            ci_status = {"branch": "feature-x", "status": "failure"}

            result = create_tech_debt_entry(tmpdir, failures, ci_status)
            self.assertEqual(result, td_path)
            with open(td_path) as f:
                content = f.read()
            self.assertIn("CI Failures", content)
            self.assertIn("feature-x", content)
            self.assertIn("test_login", content)

    def test_create_tech_debt_entry_append(self):
        """Appends to existing tech-debt entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_dir = os.path.join(tmpdir, ".coregy", "knowledge")
            os.makedirs(kb_dir)
            td_path = os.path.join(kb_dir, "tech-debt.md")
            with open(td_path, "w") as f:
                f.write("# Tech Debt\n\n## Existing Issue\n- Some old debt\n")

            failures = [
                {"test_name": "test_api", "file": "test_api.py", "error": "ConnectionError", "type": "test_failure"},
            ]
            ci_status = {"branch": "main", "status": "failure"}

            create_tech_debt_entry(tmpdir, failures, ci_status)
            with open(td_path) as f:
                content = f.read()
            # Old content preserved
            self.assertIn("Existing Issue", content)
            self.assertIn("Some old debt", content)
            # New content appended
            self.assertIn("CI Failures", content)
            self.assertIn("test_api", content)

    def test_create_tech_debt_entry_no_kb(self):
        """Creates kb dir if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # No .coregy/knowledge dir exists
            failures = [
                {"test_name": "test_x", "file": "", "error": "fail", "type": "test_failure"},
            ]
            ci_status = {"branch": "dev", "status": "failure"}

            result = create_tech_debt_entry(tmpdir, failures, ci_status)
            self.assertTrue(os.path.exists(result))
            with open(result) as f:
                content = f.read()
            self.assertIn("CI Failures", content)
            self.assertIn("test_x", content)


# ---------------------------------------------------------------------------
# suggest_fixes tests
# ---------------------------------------------------------------------------


class TestSuggestFixes(unittest.TestCase):
    def test_suggest_fixes_import_error(self):
        failures = [
            {"test_name": "test_x", "file": "test.py", "error": "ModuleNotFoundError: No module named 'flask'", "type": "test_failure"},
        ]
        suggestions = suggest_fixes(failures)
        self.assertGreaterEqual(len(suggestions), 1)
        self.assertIn("dependency", suggestions[0]["suggestion"].lower())

    def test_suggest_fixes_type_error(self):
        failures = [
            {"test_name": "TS2322", "file": "", "error": "Type 'string' is not assignable to type error", "type": "build_error"},
        ]
        suggestions = suggest_fixes(failures)
        self.assertGreaterEqual(len(suggestions), 1)
        self.assertIn("type", suggestions[0]["suggestion"].lower())

    def test_suggest_fixes_timeout(self):
        failures = [
            {"test_name": "test_slow", "file": "test.py", "error": "test timed out after 30s", "type": "test_failure"},
        ]
        suggestions = suggest_fixes(failures)
        self.assertGreaterEqual(len(suggestions), 1)
        self.assertIn("timeout", suggestions[0]["suggestion"].lower())

    def test_suggest_fixes_empty(self):
        suggestions = suggest_fixes([])
        self.assertEqual(suggestions, [])

    def test_suggest_fixes_permission(self):
        failures = [
            {"test_name": "test_write", "file": "test.py", "error": "Permission denied: /etc/config", "type": "test_failure"},
        ]
        suggestions = suggest_fixes(failures)
        self.assertGreaterEqual(len(suggestions), 1)
        self.assertIn("permission", suggestions[0]["suggestion"].lower())

    def test_suggest_fixes_connection(self):
        failures = [
            {"test_name": "test_db", "file": "test.py", "error": "Connection refused on port 5432", "type": "test_failure"},
        ]
        suggestions = suggest_fixes(failures)
        self.assertGreaterEqual(len(suggestions), 1)
        self.assertIn("service", suggestions[0]["suggestion"].lower())


# ---------------------------------------------------------------------------
# get_ci_status tests
# ---------------------------------------------------------------------------


class TestGetCiStatus(unittest.TestCase):
    @patch("ci_monitor._gh_available", return_value=False)
    def test_get_ci_status_no_gh(self, mock_gh):
        result = get_ci_status("/tmp")
        self.assertIsNone(result)

    @patch("ci_monitor._run_gh")
    @patch("ci_monitor._get_current_branch", return_value="main")
    @patch("ci_monitor._gh_available", return_value=True)
    def test_get_ci_status_success(self, mock_avail, mock_branch, mock_run):
        runs = [
            {"name": "CI", "status": "completed", "conclusion": "success", "url": "https://example.com/1", "headBranch": "main"},
        ]
        mock_run.return_value = (json.dumps(runs), True)

        result = get_ci_status("/tmp")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["branch"], "main")
        self.assertEqual(len(result["checks"]), 1)

    @patch("ci_monitor._run_gh")
    @patch("ci_monitor._get_current_branch", return_value="feature-x")
    @patch("ci_monitor._gh_available", return_value=True)
    def test_get_ci_status_failure(self, mock_avail, mock_branch, mock_run):
        runs = [
            {"name": "CI", "status": "completed", "conclusion": "failure", "url": "https://example.com/2", "headBranch": "feature-x"},
        ]
        mock_run.return_value = (json.dumps(runs), True)

        result = get_ci_status("/tmp")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "failure")

    @patch("ci_monitor._get_current_branch", return_value=None)
    @patch("ci_monitor._gh_available", return_value=True)
    def test_get_ci_status_no_branch(self, mock_avail, mock_branch):
        """Returns None when not in a git repo."""
        result = get_ci_status("/tmp")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# get_ci_summary tests
# ---------------------------------------------------------------------------


class TestGetCiSummary(unittest.TestCase):
    @patch("ci_monitor.get_ci_status")
    def test_get_ci_summary(self, mock_status):
        mock_status.return_value = {
            "branch": "main",
            "status": "failure",
            "checks": [
                {"name": "CI Build", "status": "completed", "conclusion": "failure", "url": ""},
                {"name": "Lint", "status": "completed", "conclusion": "success", "url": ""},
                {"name": "Tests", "status": "completed", "conclusion": "timed_out", "url": ""},
            ],
            "raw_output": "{}",
        }
        summary = get_ci_summary("/tmp")
        self.assertEqual(summary["status"], "failure")
        self.assertEqual(summary["failure_count"], 2)
        self.assertIn("CI Build", summary["common_failures"])
        self.assertIn("Tests", summary["common_failures"])
        self.assertIsNotNone(summary["last_run"])

    @patch("ci_monitor.get_ci_status", return_value=None)
    def test_get_ci_summary_no_gh(self, mock_status):
        summary = get_ci_summary("/tmp")
        self.assertEqual(summary["status"], "unknown")
        self.assertEqual(summary["failure_count"], 0)
        self.assertIsNone(summary["last_run"])


# ---------------------------------------------------------------------------
# run_ci_feedback tests
# ---------------------------------------------------------------------------


class TestRunCiFeedback(unittest.TestCase):
    @patch("ci_monitor.get_ci_status", return_value=None)
    def test_run_ci_feedback_no_gh(self, mock_status):
        result = run_ci_feedback("/tmp")
        self.assertIsNone(result["status"])
        self.assertEqual(result["failures"], [])
        self.assertFalse(result["tech_debt_updated"])
        self.assertEqual(result["suggestions"], [])

    @patch("ci_monitor.get_ci_status")
    def test_run_ci_feedback_success(self, mock_status):
        """No tech-debt entries on success."""
        mock_status.return_value = {
            "branch": "main",
            "status": "success",
            "checks": [{"name": "CI", "status": "completed", "conclusion": "success", "url": ""}],
            "raw_output": "{}",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_ci_feedback(tmpdir)
            self.assertEqual(result["status"]["status"], "success")
            self.assertEqual(result["failures"], [])
            self.assertFalse(result["tech_debt_updated"])
            # No tech-debt.md created
            td_path = os.path.join(tmpdir, ".coregy", "knowledge", "tech-debt.md")
            self.assertFalse(os.path.exists(td_path))

    @patch("ci_monitor._run_gh")
    @patch("ci_monitor.get_ci_status")
    def test_run_ci_feedback_failure(self, mock_status, mock_run_gh):
        """Creates tech-debt entries on failure."""
        mock_status.return_value = {
            "branch": "feature-x",
            "status": "failure",
            "checks": [{"id": 4242, "name": "CI", "status": "completed", "conclusion": "failure", "url": ""}],
            "raw_output": "{}",
        }
        # Mock gh run view <id> --log-failed
        log_output = (
            "FAILED test_auth.py::TestLogin::test_password - AssertionError: wrong password\n"
            "--- FAIL: TestCreateUser (0.01s)\n"
        )
        mock_run_gh.return_value = (log_output, True)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_ci_feedback(tmpdir)
            self.assertEqual(result["status"]["status"], "failure")
            self.assertGreater(len(result["failures"]), 0)
            self.assertTrue(result["tech_debt_updated"])
            # tech-debt.md was created
            td_path = os.path.join(tmpdir, ".coregy", "knowledge", "tech-debt.md")
            self.assertTrue(os.path.exists(td_path))
            with open(td_path) as f:
                content = f.read()
            self.assertIn("CI Failures", content)
            self.assertIn("feature-x", content)
        # `gh run view` takes the run id; it has no --branch flag
        mock_run_gh.assert_called_with(
            ["run", "view", "4242", "--log-failed"], cwd=tmpdir, timeout=60)


if __name__ == "__main__":
    unittest.main()
