"""Tests for Python detector."""
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


class TestPythonProject(unittest.TestCase):
    def test_fastapi(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "requirements.txt"), "w") as f:
                f.write("fastapi==0.104.0\nsqlalchemy==2.0.0\npytest==7.4.0\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "backend")
            self.assertEqual(profile["backend"]["language"], "python")
            self.assertEqual(profile["backend"]["framework"], "fastapi")
            self.assertEqual(profile["backend"]["orm"], "sqlalchemy")
            self.assertEqual(profile["backend"]["testing"], "pytest")

    def test_django(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "requirements.txt"), "w") as f:
                f.write("django==4.2.0\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["framework"], "django")
            self.assertEqual(profile["backend"]["orm"], "django-orm")


if __name__ == "__main__":
    unittest.main()
