"""Tests for Rust detector."""
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


class TestRustProject(unittest.TestCase):
    def test_actix_web(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "Cargo.toml"), "w") as f:
                f.write('[dependencies]\nactix-web = "4"\nsqlx = { version = "0.7" }\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "backend")
            self.assertEqual(profile["backend"]["language"], "rust")
            self.assertEqual(profile["backend"]["framework"], "actix-web")
            self.assertEqual(profile["backend"]["orm"], "sqlx")
            self.assertEqual(profile["backend"]["testing"], "cargo-test")

    def test_axum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "Cargo.toml"), "w") as f:
                f.write('[dependencies]\naxum = "0.7"\nstatic diesel = "2"\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["framework"], "axum")
            self.assertEqual(profile["backend"]["orm"], "diesel")

    def test_rocket(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "Cargo.toml"), "w") as f:
                f.write('[dependencies]\nrocket = "0.5"\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["framework"], "rocket")


if __name__ == "__main__":
    unittest.main()
