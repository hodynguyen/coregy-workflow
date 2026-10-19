"""Tests for Go detector."""
import os
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "coregy-workflow",
    "skills",
    "project-profile",
    "scripts",
)
sys.path.insert(0, os.path.abspath(SCRIPT_DIR))

from detectors.profile import build_profile


class TestGoProject(unittest.TestCase):
    def test_gin_backend(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "go.mod"), "w") as f:
                f.write("module github.com/test/api\n\nrequire github.com/gin-gonic/gin v1.9.1\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "backend")
            self.assertEqual(profile["backend"]["language"], "go")
            self.assertEqual(profile["backend"]["framework"], "gin")
            self.assertEqual(profile["backend"]["testing"], "go-test")

    def test_echo_with_gorm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "go.mod"), "w") as f:
                f.write("module test\n\nrequire (\n  github.com/labstack/echo v4\n  gorm.io/gorm v1.25\n)\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["framework"], "echo")
            self.assertEqual(profile["backend"]["orm"], "gorm")


if __name__ == "__main__":
    unittest.main()
