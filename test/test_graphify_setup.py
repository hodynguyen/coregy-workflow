"""Tests for graphify_setup.py — Python discovery, settings, profile, gitignore."""
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

from graphify_setup import (
    find_python,
    update_gitignore,
    update_profile_yaml,
    update_claude_settings,
)


# ---------------------------------------------------------------------------
# find_python tests
# ---------------------------------------------------------------------------


class TestFindPython(unittest.TestCase):
    """Test Python interpreter discovery logic."""

    @patch("graphify_setup._python_version", return_value=(3, 13))
    @patch("graphify_setup._which", return_value="/usr/bin/python3.13")
    def test_finds_versioned_on_path(self, mock_which, mock_ver):
        result = find_python()
        self.assertEqual(result, "/usr/bin/python3.13")
        # Should try python3.13 first (highest)
        mock_which.assert_called_with("python3.13")

    @patch("graphify_setup._python_version")
    @patch("graphify_setup._which", return_value=None)
    @patch("os.path.isfile")
    @patch("os.access")
    def test_finds_in_homebrew(self, mock_access, mock_isfile, mock_which, mock_ver):
        """Falls back to /opt/homebrew/bin when which returns nothing."""
        mock_isfile.side_effect = lambda p: p == "/opt/homebrew/bin/python3.12"
        mock_access.side_effect = lambda p, _: p == "/opt/homebrew/bin/python3.12"
        mock_ver.return_value = (3, 12)

        result = find_python()
        self.assertEqual(result, "/opt/homebrew/bin/python3.12")

    @patch("graphify_setup._python_version")
    @patch("graphify_setup._which")
    @patch("os.path.isfile", return_value=False)
    @patch("os.access", return_value=False)
    def test_fallback_to_python3(self, mock_access, mock_isfile, mock_which, mock_ver):
        """Falls back to generic python3 if versioned names not found."""
        # Versioned which calls return None, generic returns a path
        def which_side_effect(name):
            if name == "python3":
                return "/usr/bin/python3"
            return None

        mock_which.side_effect = which_side_effect
        mock_ver.return_value = (3, 11)

        result = find_python()
        self.assertEqual(result, "/usr/bin/python3")

    @patch("graphify_setup._python_version", return_value=(3, 9))
    @patch("graphify_setup._which")
    @patch("os.path.isfile", return_value=False)
    @patch("os.access", return_value=False)
    def test_returns_none_when_too_old(self, mock_access, mock_isfile, mock_which, mock_ver):
        """Returns None when only python3 exists but version < 3.10."""
        def which_side_effect(name):
            if name == "python3":
                return "/usr/bin/python3"
            return None

        mock_which.side_effect = which_side_effect

        result = find_python()
        self.assertIsNone(result)

    @patch("graphify_setup._python_version", return_value=None)
    @patch("graphify_setup._which", return_value=None)
    @patch("os.path.isfile", return_value=False)
    @patch("os.access", return_value=False)
    def test_returns_none_when_nothing_found(self, mock_access, mock_isfile, mock_which, mock_ver):
        result = find_python()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# update_gitignore tests
# ---------------------------------------------------------------------------


class TestUpdateGitignore(unittest.TestCase):
    def test_creates_gitignore_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            update_gitignore(tmp)
            path = os.path.join(tmp, ".gitignore")
            self.assertTrue(os.path.isfile(path))
            with open(path) as f:
                self.assertIn("graphify-out/", f.read())

    def test_appends_to_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".gitignore")
            with open(path, "w") as f:
                f.write("node_modules/\n")
            update_gitignore(tmp)
            with open(path) as f:
                content = f.read()
            self.assertIn("node_modules/", content)
            self.assertIn("graphify-out/", content)

    def test_appends_when_no_trailing_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".gitignore")
            with open(path, "w") as f:
                f.write("node_modules/")  # no trailing newline
            update_gitignore(tmp)
            with open(path) as f:
                content = f.read()
            # Should have newline between existing and new entry
            self.assertIn("node_modules/\ngraphify-out/", content)

    def test_skips_if_already_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".gitignore")
            with open(path, "w") as f:
                f.write("graphify-out/\nother/\n")
            update_gitignore(tmp)
            with open(path) as f:
                content = f.read()
            # Should not duplicate
            self.assertEqual(content.count("graphify-out"), 1)

    def test_skips_if_present_without_trailing_slash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".gitignore")
            with open(path, "w") as f:
                f.write("graphify-out\n")
            update_gitignore(tmp)
            with open(path) as f:
                content = f.read()
            self.assertEqual(content.count("graphify-out"), 1)

    def test_empty_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".gitignore")
            with open(path, "w") as f:
                f.write("")
            update_gitignore(tmp)
            with open(path) as f:
                content = f.read()
            self.assertIn("graphify-out/", content)


# ---------------------------------------------------------------------------
# update_profile_yaml tests
# ---------------------------------------------------------------------------


class TestUpdateProfileYaml(unittest.TestCase):
    def _make_profile(self, tmp, content):
        coregy = os.path.join(tmp, ".coregy")
        os.makedirs(coregy, exist_ok=True)
        path = os.path.join(coregy, "profile.yaml")
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_no_integrations_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_profile(tmp, "language: python\nframework: fastapi\n")
            update_profile_yaml(tmp)
            with open(path) as f:
                content = f.read()
            self.assertIn("integrations:", content)
            self.assertIn("graphify: true", content)

    def test_existing_integrations_no_graphify(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_profile(
                tmp,
                "language: python\n\nintegrations:\n  github: true\n",
            )
            update_profile_yaml(tmp)
            with open(path) as f:
                content = f.read()
            self.assertIn("graphify: true", content)
            self.assertIn("github: true", content)

    def test_graphify_already_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = "integrations:\n  graphify: true\n"
            path = self._make_profile(tmp, original)
            update_profile_yaml(tmp)
            with open(path) as f:
                content = f.read()
            # Should remain unchanged
            self.assertEqual(content, original)

    def test_graphify_false_becomes_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._make_profile(
                tmp,
                "integrations:\n  graphify: false\n  github: true\n",
            )
            update_profile_yaml(tmp)
            with open(path) as f:
                content = f.read()
            self.assertIn("graphify: true", content)
            self.assertIn("github: true", content)
            self.assertNotIn("graphify: false", content)

    def test_no_profile_file(self):
        """Should print warning and not crash when profile.yaml missing."""
        with tempfile.TemporaryDirectory() as tmp:
            # No .coregy dir at all — should not raise
            update_profile_yaml(tmp)


# ---------------------------------------------------------------------------
# update_claude_settings tests
# ---------------------------------------------------------------------------


class TestUpdateClaudeSettings(unittest.TestCase):
    def setUp(self):
        # Never let the tests touch the real `claude` CLI / ~/.claude.json.
        self._mode = os.environ.get("COREGY_MCP_MODE")
        os.environ["COREGY_MCP_MODE"] = "file"

    def tearDown(self):
        if self._mode is None:
            os.environ.pop("COREGY_MCP_MODE", None)
        else:
            os.environ["COREGY_MCP_MODE"] = self._mode

    def _mcp(self, tmp):
        with open(os.path.join(tmp, ".mcp.json")) as f:
            return json.load(f)

    def test_registers_in_mcp_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            update_claude_settings(tmp, "/usr/bin/python3.12")
            server = self._mcp(tmp)["mcpServers"]["graphify"]
            self.assertEqual(server["command"], "/usr/bin/python3.12")
            self.assertEqual(
                server["args"],
                ["-m", "graphify.serve",
                 os.path.join(os.path.abspath(tmp), "graphify-out", "graph.json")],
            )
            # never written to the file Claude Code does not read
            self.assertFalse(os.path.isfile(os.path.join(tmp, ".claude", "settings.json")))

    def test_preserves_other_mcp_servers(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, ".mcp.json"), "w") as f:
                json.dump({"mcpServers": {"github": {"command": "npx"}}}, f)
            update_claude_settings(tmp, "/opt/homebrew/bin/python3.13")
            servers = self._mcp(tmp)["mcpServers"]
            self.assertIn("github", servers)
            self.assertEqual(servers["graphify"]["command"], "/opt/homebrew/bin/python3.13")

    def test_migrates_legacy_settings_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_dir = os.path.join(tmp, ".claude")
            os.makedirs(settings_dir)
            with open(os.path.join(settings_dir, "settings.json"), "w") as f:
                json.dump({"enabledPlugins": ["coregy-workflow"],
                           "mcpServers": {"graphify": {"command": "old"}}}, f)
            update_claude_settings(tmp, "/usr/bin/python3.11")
            with open(os.path.join(settings_dir, "settings.json")) as f:
                data = json.load(f)
            self.assertEqual(data["enabledPlugins"], ["coregy-workflow"])
            self.assertNotIn("mcpServers", data)
            self.assertEqual(self._mcp(tmp)["mcpServers"]["graphify"]["command"],
                             "/usr/bin/python3.11")

    def test_handles_corrupt_legacy_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_dir = os.path.join(tmp, ".claude")
            os.makedirs(settings_dir)
            with open(os.path.join(settings_dir, "settings.json"), "w") as f:
                f.write("{corrupt json!!")
            update_claude_settings(tmp, "/usr/bin/python3.12")
            self.assertIn("graphify", self._mcp(tmp)["mcpServers"])

if __name__ == "__main__":
    unittest.main()
