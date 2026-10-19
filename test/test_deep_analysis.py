"""Tests for deep stack analysis (versions.py + deep_analysis.py)."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Add detectors to path
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

from detectors.versions import parse_semver, is_major_mismatch, is_outdated, classify_severity
from detectors.deep_analysis import (
    run_deep_analysis,
    _count_deps,
    _analyze_npm,
    _analyze_pip,
    _analyze_go,
    _analyze_cargo,
)


# ---------------------------------------------------------------------------
# versions.py tests
# ---------------------------------------------------------------------------


class TestParseSemver(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(parse_semver("1.2.3"), (1, 2, 3))

    def test_with_v_prefix(self):
        self.assertEqual(parse_semver("v2.0.1"), (2, 0, 1))

    def test_prerelease(self):
        self.assertEqual(parse_semver("1.0.0-beta.1"), (1, 0, 0))

    def test_build_metadata(self):
        self.assertEqual(parse_semver("1.0.0+build.123"), (1, 0, 0))

    def test_invalid(self):
        self.assertIsNone(parse_semver("not-a-version"))
        self.assertIsNone(parse_semver(""))
        self.assertIsNone(parse_semver(None))

    def test_two_digits(self):
        self.assertIsNone(parse_semver("1.2"))


class TestIsMajorMismatch(unittest.TestCase):
    def test_mismatch(self):
        self.assertTrue(is_major_mismatch("17.0.2", "18.0.0"))

    def test_no_mismatch(self):
        self.assertFalse(is_major_mismatch("18.0.1", "18.2.0"))

    def test_with_caret(self):
        self.assertTrue(is_major_mismatch("4.18.2", "^5.0.0"))

    def test_invalid_version(self):
        self.assertFalse(is_major_mismatch("latest", "1.0.0"))


class TestIsOutdated(unittest.TestCase):
    def test_outdated_minor(self):
        outdated, breaking = is_outdated("1.0.0", "1.2.0")
        self.assertTrue(outdated)
        self.assertFalse(breaking)

    def test_outdated_major(self):
        outdated, breaking = is_outdated("4.18.2", "5.0.1")
        self.assertTrue(outdated)
        self.assertTrue(breaking)

    def test_not_outdated(self):
        outdated, breaking = is_outdated("2.0.0", "2.0.0")
        self.assertFalse(outdated)
        self.assertFalse(breaking)

    def test_invalid(self):
        outdated, breaking = is_outdated("invalid", "1.0.0")
        self.assertFalse(outdated)
        self.assertFalse(breaking)


class TestClassifySeverity(unittest.TestCase):
    def test_critical(self):
        self.assertEqual(classify_severity("critical"), "critical")

    def test_high(self):
        self.assertEqual(classify_severity("high"), "high")

    def test_moderate(self):
        self.assertEqual(classify_severity("moderate"), "moderate")
        self.assertEqual(classify_severity("medium"), "moderate")

    def test_low(self):
        self.assertEqual(classify_severity("low"), "low")
        self.assertEqual(classify_severity("info"), "low")

    def test_none(self):
        self.assertEqual(classify_severity(None), "low")


# ---------------------------------------------------------------------------
# deep_analysis.py tests
# ---------------------------------------------------------------------------


class TestCountDeps(unittest.TestCase):
    def test_flat(self):
        deps = {"a": {}, "b": {}, "c": {}}
        self.assertEqual(_count_deps(deps), 3)

    def test_nested(self):
        deps = {"a": {"dependencies": {"b": {}, "c": {}}}, "d": {}}
        self.assertEqual(_count_deps(deps), 4)

    def test_empty(self):
        self.assertEqual(_count_deps({}), 0)


class TestRunDeepAnalysis(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    @patch("detectors.deep_analysis._run_cmd")
    def test_npm_analysis(self, mock_cmd):
        """Detects npm project and runs analysis."""
        # Create package.json
        with open(os.path.join(self.cwd, "package.json"), "w") as f:
            json.dump({"name": "test", "dependencies": {"express": "^4.18.0"}}, f)

        # Mock npm ls
        npm_ls_result = json.dumps({
            "dependencies": {
                "express": {"dependencies": {"body-parser": {}, "cookie": {}}},
                "lodash": {},
            }
        })
        # Mock npm outdated
        npm_outdated_result = json.dumps({
            "express": {"current": "4.18.2", "wanted": "4.19.0", "latest": "5.0.1"}
        })
        # Mock npm audit (empty)
        npm_audit_result = json.dumps({"vulnerabilities": {}})

        mock_cmd.side_effect = [
            (npm_ls_result, True),    # npm ls
            (npm_outdated_result, True),  # npm outdated
            (npm_audit_result, True),     # npm audit
        ]

        profile = {"frontend": {"framework": "react"}}
        result = run_deep_analysis(self.cwd, profile)

        self.assertIsNotNone(result)
        self.assertEqual(result["direct"], 2)
        self.assertEqual(result["dependency_count"], 4)
        self.assertEqual(result["transitive"], 2)
        self.assertEqual(len(result["outdated"]), 1)
        self.assertEqual(result["outdated"][0]["package"], "express")
        self.assertTrue(result["outdated"][0]["breaking"])
        self.assertIn("last_run", result)

    @patch("detectors.deep_analysis._run_cmd")
    def test_go_analysis(self, mock_cmd):
        """Detects Go project and runs analysis."""
        # Create go.mod
        gomod = "module example.com/app\n\ngo 1.21\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n\tgithub.com/lib/pq v1.10.9\n)\n"
        with open(os.path.join(self.cwd, "go.mod"), "w") as f:
            f.write(gomod)

        mock_cmd.side_effect = [
            ("example.com/app\ngithub.com/gin-gonic/gin v1.9.1\ngithub.com/lib/pq v1.10.9\ngithub.com/some/transitive v0.1.0\n", True),
            ("", False),  # govulncheck not available
        ]

        profile = {"backend": {"language": "go"}}
        result = run_deep_analysis(self.cwd, profile)

        self.assertIsNotNone(result)
        self.assertEqual(result["dependency_count"], 3)
        self.assertEqual(result["direct"], 2)
        self.assertEqual(result["transitive"], 1)

    def test_no_analyzable_stack(self):
        """Returns None for unknown project type."""
        profile = {"project": {"type": "unknown"}}
        result = run_deep_analysis(self.cwd, profile)
        self.assertIsNone(result)

    @patch("detectors.deep_analysis._run_cmd")
    def test_command_failure_graceful(self, mock_cmd):
        """Handles command failures gracefully."""
        with open(os.path.join(self.cwd, "package.json"), "w") as f:
            json.dump({"name": "test"}, f)

        mock_cmd.return_value = ("", False)

        profile = {}
        result = run_deep_analysis(self.cwd, profile)
        self.assertIsNotNone(result)
        self.assertEqual(result["dependency_count"], 0)


class TestBuildProfileDeep(unittest.TestCase):
    """Test that --deep flag integrates with build_profile."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_build_profile_without_deep(self):
        """Default build_profile does not include deep_analysis."""
        from detectors.profile import build_profile
        profile = build_profile(self.cwd)
        self.assertNotIn("deep_analysis", profile)

    @patch("detectors.deep_analysis._run_cmd")
    def test_build_profile_with_deep(self, mock_cmd):
        """build_profile(deep=True) includes deep_analysis when stack is detected."""
        with open(os.path.join(self.cwd, "package.json"), "w") as f:
            json.dump({"name": "test", "dependencies": {"react": "^18.0.0"}}, f)

        mock_cmd.return_value = ("", False)

        from detectors.profile import build_profile
        profile = build_profile(self.cwd, deep=True)
        self.assertIn("deep_analysis", profile)


if __name__ == "__main__":
    unittest.main()
