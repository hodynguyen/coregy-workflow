"""Tests for MCP setup helper (mcp_setup.py)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "hody-workflow",
    "skills",
    "project-profile",
    "scripts",
)
sys.path.insert(0, os.path.abspath(SCRIPT_DIR))

# Never let the tests reach the real `claude` CLI / ~/.claude.json.
os.environ["HODY_MCP_MODE"] = "file"

import mcp_setup


def _read_settings(cwd):
    path = os.path.join(cwd, ".mcp.json")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def _write_profile(cwd, content):
    os.makedirs(os.path.join(cwd, ".hody"), exist_ok=True)
    with open(os.path.join(cwd, ".hody", "profile.yaml"), "w") as f:
        f.write(content)


class TestSpecs(unittest.TestCase):
    def test_jira_fields(self):
        fields = mcp_setup.describe_fields("jira")
        names = [f["name"] for f in fields]
        self.assertEqual(set(names), {"api-token", "site", "email"})

    def test_linear_fields(self):
        fields = mcp_setup.describe_fields("linear")
        self.assertEqual([f["name"] for f in fields], ["api-key"])

    def test_github_fields(self):
        fields = mcp_setup.describe_fields("github")
        self.assertEqual([f["name"] for f in fields], ["token"])

    def test_unknown_integration(self):
        with self.assertRaises(ValueError):
            mcp_setup.get_spec("slack")


class TestCollectMissing(unittest.TestCase):
    def test_all_provided(self):
        missing = mcp_setup.collect_missing(
            "jira",
            {"api-token": "X", "site": "Y", "email": "Z"},
        )
        self.assertEqual(missing, [])

    def test_some_missing(self):
        missing = mcp_setup.collect_missing("jira", {"api-token": "X"})
        names = [f["name"] for f in missing]
        self.assertEqual(set(names), {"site", "email"})

    def test_empty_value_missing(self):
        missing = mcp_setup.collect_missing(
            "jira",
            {"api-token": "X", "site": "", "email": None},
        )
        names = [f["name"] for f in missing]
        self.assertEqual(set(names), {"site", "email"})


class TestBuildServerConfig(unittest.TestCase):
    def test_jira_config(self):
        config = mcp_setup.build_server_config(
            "jira",
            {
                "api-token": "tok",
                "site": "https://acme.atlassian.net",
                "email": "u@acme.com",
            },
        )
        self.assertEqual(config["command"], "uvx")
        self.assertEqual(config["args"], ["mcp-atlassian"])
        self.assertEqual(
            config["env"],
            {
                "JIRA_API_TOKEN": "tok",
                "JIRA_URL": "https://acme.atlassian.net",
                "JIRA_USERNAME": "u@acme.com",
            },
        )

    def test_github_uses_official_remote_server(self):
        config = mcp_setup.build_server_config("github", {"token": "ghp_x"})
        self.assertEqual(config["type"], "http")
        self.assertEqual(config["headers"], {"Authorization": "Bearer ghp_x"})
        self.assertNotIn("env", config)

    def test_missing_field_raises(self):
        with self.assertRaises(ValueError):
            mcp_setup.build_server_config("jira", {"api-token": "tok"})


class TestConfigure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name
        _write_profile(self.cwd, "name: test\nintegrations:\n  jira: false\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_settings_file(self):
        mcp_setup.configure(
            self.cwd,
            "jira",
            {"api-token": "tok", "site": "S", "email": "E"},
        )
        settings = _read_settings(self.cwd)
        self.assertIn("mcpServers", settings)
        self.assertIn("jira", settings["mcpServers"])
        env = settings["mcpServers"]["jira"]["env"]
        self.assertEqual(env["JIRA_API_TOKEN"], "tok")

    def test_preserves_existing_servers(self):
        with open(os.path.join(self.cwd, ".mcp.json"), "w") as f:
            json.dump({"mcpServers": {"graphify": {"command": "python"}}}, f)

        mcp_setup.configure(
            self.cwd,
            "jira",
            {"api-token": "tok", "site": "S", "email": "E"},
        )
        settings = _read_settings(self.cwd)
        self.assertIn("graphify", settings["mcpServers"])
        self.assertIn("jira", settings["mcpServers"])

    def test_credentials_file_is_gitignored(self):
        result = mcp_setup.configure(
            self.cwd, "jira", {"api-token": "tok", "site": "S", "email": "E"})
        with open(os.path.join(self.cwd, ".gitignore")) as f:
            self.assertIn(".mcp.json", f.read().splitlines())
        self.assertIn("credentials", result["warning"])

    def test_migrates_legacy_settings_entry(self):
        os.makedirs(os.path.join(self.cwd, ".claude"))
        legacy = os.path.join(self.cwd, ".claude", "settings.json")
        with open(legacy, "w") as f:
            json.dump({"mcpServers": {"jira": {"command": "npx"}},
                       "otherKey": "preserved"}, f)
        mcp_setup.configure(
            self.cwd, "jira", {"api-token": "tok", "site": "S", "email": "E"})
        with open(legacy) as f:
            data = json.load(f)
        self.assertEqual(data, {"otherKey": "preserved"})

    def test_updates_profile_flag(self):
        mcp_setup.configure(
            self.cwd,
            "jira",
            {"api-token": "tok", "site": "S", "email": "E"},
        )
        with open(os.path.join(self.cwd, ".hody", "profile.yaml")) as f:
            content = f.read()
        self.assertIn("jira: true", content)

    def test_missing_field_raises(self):
        with self.assertRaises(ValueError):
            mcp_setup.configure(self.cwd, "jira", {"api-token": "tok"})

    def test_linear_minimal(self):
        mcp_setup.configure(self.cwd, "linear", {"api-key": "key"})
        settings = _read_settings(self.cwd)
        self.assertEqual(
            settings["mcpServers"]["linear"]["headers"],
            {"Authorization": "Bearer key"},
        )

    def test_overwrites_existing_jira(self):
        mcp_setup.configure(
            self.cwd,
            "jira",
            {"api-token": "old", "site": "S", "email": "E"},
        )
        mcp_setup.configure(
            self.cwd,
            "jira",
            {"api-token": "new", "site": "S2", "email": "E2"},
        )
        settings = _read_settings(self.cwd)
        env = settings["mcpServers"]["jira"]["env"]
        self.assertEqual(env["JIRA_API_TOKEN"], "new")
        self.assertEqual(env["JIRA_URL"], "S2")


class TestRemove(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name
        _write_profile(self.cwd, "integrations:\n  jira: true\n")
        with open(os.path.join(self.cwd, ".mcp.json"), "w") as f:
            json.dump(
                {"mcpServers": {
                    "jira": {"command": "npx"},
                    "linear": {"command": "npx"},
                }},
                f,
            )

    def tearDown(self):
        self.tmp.cleanup()

    def test_removes_only_target(self):
        result = mcp_setup.remove(self.cwd, "jira")
        self.assertTrue(result["removed"])
        settings = _read_settings(self.cwd)
        self.assertNotIn("jira", settings["mcpServers"])
        self.assertIn("linear", settings["mcpServers"])

    def test_remove_missing_returns_false(self):
        mcp_setup.remove(self.cwd, "jira")
        result = mcp_setup.remove(self.cwd, "jira")
        self.assertFalse(result["removed"])

    def test_flips_profile_flag(self):
        mcp_setup.remove(self.cwd, "jira")
        with open(os.path.join(self.cwd, ".hody", "profile.yaml")) as f:
            content = f.read()
        self.assertIn("jira: false", content)


class TestStatus(unittest.TestCase):
    def test_no_settings_no_profile(self):
        with tempfile.TemporaryDirectory() as cwd:
            result = mcp_setup.status(cwd)
            self.assertFalse(result["jira"]["configured"])
            self.assertIsNone(result["jira"]["profile_flag"])

    def test_configured_state(self):
        with tempfile.TemporaryDirectory() as cwd:
            _write_profile(cwd, "integrations:\n  jira: true\n  linear: false\n")
            mcp_setup.configure(
                cwd, "jira", {"api-token": "X", "site": "Y", "email": "Z"}
            )
            result = mcp_setup.status(cwd)
            self.assertTrue(result["jira"]["configured"])
            self.assertEqual(result["jira"]["profile_flag"], "true")
            self.assertFalse(result["linear"]["configured"])
            self.assertEqual(result["linear"]["profile_flag"], "false")


class TestUpdateProfile(unittest.TestCase):
    def test_no_profile_returns_false(self):
        with tempfile.TemporaryDirectory() as cwd:
            self.assertFalse(
                mcp_setup.update_profile_integration(cwd, "jira", True)
            )

    def test_creates_integrations_section(self):
        with tempfile.TemporaryDirectory() as cwd:
            _write_profile(cwd, "name: test\n")
            mcp_setup.update_profile_integration(cwd, "jira", True)
            with open(os.path.join(cwd, ".hody", "profile.yaml")) as f:
                content = f.read()
            self.assertIn("integrations:", content)
            self.assertIn("jira: true", content)

    def test_appends_to_existing_section(self):
        with tempfile.TemporaryDirectory() as cwd:
            _write_profile(cwd, "integrations:\n  github: true\n")
            mcp_setup.update_profile_integration(cwd, "jira", True)
            with open(os.path.join(cwd, ".hody", "profile.yaml")) as f:
                content = f.read()
            self.assertIn("github: true", content)
            self.assertIn("jira: true", content)

    def test_flips_existing_value(self):
        with tempfile.TemporaryDirectory() as cwd:
            _write_profile(cwd, "integrations:\n  jira: false\n")
            mcp_setup.update_profile_integration(cwd, "jira", True)
            with open(os.path.join(cwd, ".hody", "profile.yaml")) as f:
                content = f.read()
            self.assertIn("jira: true", content)
            self.assertNotIn("jira: false", content)


class TestCLI(unittest.TestCase):
    def _run(self, args, cwd):
        cmd = [sys.executable, os.path.join(SCRIPT_DIR, "mcp_setup.py"),
               "--cwd", cwd] + args
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10)

    def test_jira_full_args(self):
        with tempfile.TemporaryDirectory() as cwd:
            _write_profile(cwd, "integrations:\n  jira: false\n")
            result = self._run(
                ["jira", "--api-token", "T", "--site", "S", "--email", "E"],
                cwd,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            settings = _read_settings(cwd)
            self.assertIn("jira", settings["mcpServers"])

    def test_missing_field_exits_with_error(self):
        with tempfile.TemporaryDirectory() as cwd:
            _write_profile(cwd, "integrations:\n  jira: false\n")
            result = self._run(["jira", "--api-token", "T"], cwd)
            self.assertEqual(result.returncode, 2)
            self.assertIn("Missing required", result.stderr)

    def test_status(self):
        with tempfile.TemporaryDirectory() as cwd:
            result = self._run(["status"], cwd)
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertIn("jira", data)
            self.assertIn("linear", data)
            self.assertIn("github", data)

    def test_fields(self):
        with tempfile.TemporaryDirectory() as cwd:
            result = self._run(["fields", "jira"], cwd)
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            names = [f["name"] for f in data]
            self.assertEqual(set(names), {"api-token", "site", "email"})

    def test_remove(self):
        with tempfile.TemporaryDirectory() as cwd:
            _write_profile(cwd, "integrations:\n  jira: false\n")
            self._run(
                ["jira", "--api-token", "T", "--site", "S", "--email", "E"],
                cwd,
            )
            result = self._run(["remove", "jira"], cwd)
            self.assertEqual(result.returncode, 0)
            settings = _read_settings(cwd)
            self.assertNotIn("jira", settings.get("mcpServers", {}))


if __name__ == "__main__":
    unittest.main()
