"""Integration test for detect_stack.py — verifies backward-compatible imports and end-to-end build_profile."""
import os
import sys
import tempfile
import unittest

# Add the script to path
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

from detect_stack import build_profile, to_yaml


class TestEmptyProject(unittest.TestCase):
    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "unknown")
            self.assertNotIn("frontend", profile)
            self.assertNotIn("backend", profile)


class TestFrameworklessProject(unittest.TestCase):
    """A language with no recognised framework is a library, not "unknown"."""

    def test_python_library(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "pyproject.toml"), "w") as f:
                f.write('[project]\nname = "tool"\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "library")
            self.assertEqual(profile["project"]["language"], "python")

    def test_typescript_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "package.json"), "w") as f:
                f.write('{"name": "lib", "devDependencies": {"typescript": "5"}}')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "library")
            self.assertEqual(profile["project"]["language"], "typescript")


class TestBackwardCompatibleImports(unittest.TestCase):
    def test_build_profile_importable(self):
        self.assertTrue(callable(build_profile))

    def test_to_yaml_importable(self):
        self.assertTrue(callable(to_yaml))

    def test_load_existing_integrations_importable(self):
        from detect_stack import load_existing_integrations
        self.assertTrue(callable(load_existing_integrations))


if __name__ == "__main__":
    unittest.main()
