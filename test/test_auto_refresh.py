"""Tests for auto-refresh logic in inject_project_context.py, load_existing_integrations, and Graphify hook injection."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

# Add hooks to path
HOOK_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "hody-workflow",
    "hooks",
)
sys.path.insert(0, os.path.abspath(HOOK_DIR))

# Add detect_stack to path
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

from inject_project_context import is_profile_stale, CONFIG_FILES
from detectors.integrations import load_existing_integrations


class TestIsProfileStale(unittest.TestCase):
    def _make_profile(self, tmpdir, content="project:\n  name: test\n"):
        hody_dir = os.path.join(tmpdir, ".hody")
        os.makedirs(hody_dir, exist_ok=True)
        profile_path = os.path.join(hody_dir, "profile.yaml")
        with open(profile_path, "w") as f:
            f.write(content)
        return profile_path

    def test_no_config_files_not_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = self._make_profile(tmpdir)
            self.assertFalse(is_profile_stale(tmpdir, profile_path))

    def test_older_config_not_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create config file first
            pkg_path = os.path.join(tmpdir, "package.json")
            with open(pkg_path, "w") as f:
                f.write('{"name":"test"}')

            # Wait a moment, then create profile (newer)
            time.sleep(0.05)
            profile_path = self._make_profile(tmpdir)

            self.assertFalse(is_profile_stale(tmpdir, profile_path))

    def test_newer_config_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create profile first
            profile_path = self._make_profile(tmpdir)

            # Wait a moment, then create config file (newer)
            time.sleep(0.05)
            pkg_path = os.path.join(tmpdir, "package.json")
            with open(pkg_path, "w") as f:
                f.write('{"name":"test","dependencies":{"react":"^18"}}')

            self.assertTrue(is_profile_stale(tmpdir, profile_path))

    def test_newer_gomod_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = self._make_profile(tmpdir)
            time.sleep(0.05)
            with open(os.path.join(tmpdir, "go.mod"), "w") as f:
                f.write("module example.com/app\n")
            self.assertTrue(is_profile_stale(tmpdir, profile_path))

    def test_newer_csproj_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = self._make_profile(tmpdir)
            time.sleep(0.05)
            with open(os.path.join(tmpdir, "MyApp.csproj"), "w") as f:
                f.write("<Project></Project>")
            self.assertTrue(is_profile_stale(tmpdir, profile_path))

    def test_newer_tf_file_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = self._make_profile(tmpdir)
            time.sleep(0.05)
            with open(os.path.join(tmpdir, "main.tf"), "w") as f:
                f.write('resource "aws_instance" "web" {}')
            self.assertTrue(is_profile_stale(tmpdir, profile_path))

    def test_newer_workflow_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = self._make_profile(tmpdir)
            time.sleep(0.05)
            wf_dir = os.path.join(tmpdir, ".github", "workflows")
            os.makedirs(wf_dir)
            with open(os.path.join(wf_dir, "ci.yml"), "w") as f:
                f.write("name: CI\n")
            self.assertTrue(is_profile_stale(tmpdir, profile_path))

    def test_missing_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_path = os.path.join(tmpdir, ".hody", "profile.yaml")
            self.assertFalse(is_profile_stale(tmpdir, fake_path))


class TestLoadExistingIntegrations(unittest.TestCase):
    def _make_profile(self, tmpdir, content):
        hody_dir = os.path.join(tmpdir, ".hody")
        os.makedirs(hody_dir, exist_ok=True)
        with open(os.path.join(hody_dir, "profile.yaml"), "w") as f:
            f.write(content)

    def test_no_integrations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_profile(tmpdir, "project:\n  name: test\n")
            result = load_existing_integrations(tmpdir)
            self.assertIsNone(result)

    def test_all_integrations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_profile(tmpdir, (
                "project:\n  name: test\n"
                "integrations:\n"
                "  github: true\n"
                "  linear: true\n"
                "  jira: false\n"
            ))
            result = load_existing_integrations(tmpdir)
            self.assertEqual(result["github"], True)
            self.assertEqual(result["linear"], True)
            self.assertEqual(result["jira"], False)

    def test_partial_integrations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_profile(tmpdir, (
                "project:\n  name: test\n"
                "integrations:\n"
                "  github: true\n"
                "conventions:\n"
                "  linter: eslint\n"
            ))
            result = load_existing_integrations(tmpdir)
            self.assertEqual(result["github"], True)
            self.assertNotIn("linter", result)

    def test_no_profile_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_existing_integrations(tmpdir)
            self.assertIsNone(result)


class TestGraphifyHookInjection(unittest.TestCase):
    """Test that the SessionStart hook injects Graphify summary when graph.json is present."""

    HOOK_SCRIPT = os.path.join(
        os.path.dirname(__file__),
        "..",
        "plugins",
        "hody-workflow",
        "hooks",
        "inject_project_context.py",
    )

    def _run_hook(self, cwd):
        """Run the hook script with given cwd and return parsed output."""
        input_data = json.dumps({"cwd": cwd})
        result = subprocess.run(
            [sys.executable, self.HOOK_SCRIPT],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "HODY_SKIP_REFRESH": "1"},
        )
        if result.stdout.strip():
            return json.loads(result.stdout)
        return {}

    def _setup_project(self, tmpdir):
        """Create minimal .hody/profile.yaml."""
        hody_dir = os.path.join(tmpdir, ".hody")
        os.makedirs(hody_dir, exist_ok=True)
        with open(os.path.join(hody_dir, "profile.yaml"), "w") as f:
            f.write("project:\n  name: test-graphify\n")

    def test_no_graph_no_injection(self):
        """Hook works normally without graphify-out/graph.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_project(tmpdir)
            output = self._run_hook(tmpdir)
            msg = output.get("hookSpecificOutput", {}).get("additionalContext", "")
            self.assertNotIn("Graphify", msg)

    def test_graph_present_injects_summary(self):
        """Hook injects Graphify summary when graph.json exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_project(tmpdir)
            graph_dir = os.path.join(tmpdir, "graphify-out")
            os.makedirs(graph_dir)
            graph_data = {
                "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                "links": [{"source": "a", "target": "b"}],
            }
            with open(os.path.join(graph_dir, "graph.json"), "w") as f:
                json.dump(graph_data, f)

            output = self._run_hook(tmpdir)
            msg = output.get("hookSpecificOutput", {}).get("additionalContext", "")
            self.assertIn("Graphify: 3 nodes, 1 edges", msg)
            self.assertIn("query_graph", msg)

    def test_graph_with_edges_key(self):
        """Hook handles graph.json with 'edges' key (newer NetworkX format)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_project(tmpdir)
            graph_dir = os.path.join(tmpdir, "graphify-out")
            os.makedirs(graph_dir)
            graph_data = {
                "nodes": [{"id": "x"}, {"id": "y"}],
                "edges": [{"source": "x", "target": "y"}],
            }
            with open(os.path.join(graph_dir, "graph.json"), "w") as f:
                json.dump(graph_data, f)

            output = self._run_hook(tmpdir)
            msg = output.get("hookSpecificOutput", {}).get("additionalContext", "")
            self.assertIn("Graphify: 2 nodes, 1 edges", msg)

    def test_empty_graph_no_injection(self):
        """Hook does not inject summary for empty graph (0 nodes)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_project(tmpdir)
            graph_dir = os.path.join(tmpdir, "graphify-out")
            os.makedirs(graph_dir)
            graph_data = {"nodes": [], "links": []}
            with open(os.path.join(graph_dir, "graph.json"), "w") as f:
                json.dump(graph_data, f)

            output = self._run_hook(tmpdir)
            msg = output.get("hookSpecificOutput", {}).get("additionalContext", "")
            self.assertNotIn("Graphify", msg)

    def test_corrupt_graph_no_crash(self):
        """Hook handles corrupt graph.json gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._setup_project(tmpdir)
            graph_dir = os.path.join(tmpdir, "graphify-out")
            os.makedirs(graph_dir)
            with open(os.path.join(graph_dir, "graph.json"), "w") as f:
                f.write("NOT VALID JSON{{{")

            output = self._run_hook(tmpdir)
            msg = output.get("hookSpecificOutput", {}).get("additionalContext", "")
            self.assertNotIn("Graphify", msg)
            # Should still have profile info
            self.assertIn("Hody Workflow", msg)


if __name__ == "__main__":
    unittest.main()
