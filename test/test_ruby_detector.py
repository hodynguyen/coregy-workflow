"""Tests for Ruby detector."""
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


class TestRubyProject(unittest.TestCase):
    def test_rails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "Gemfile"), "w") as f:
                f.write("source 'https://rubygems.org'\ngem 'rails', '~> 7.1'\ngem 'rspec-rails'\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "backend")
            self.assertEqual(profile["backend"]["language"], "ruby")
            self.assertEqual(profile["backend"]["framework"], "rails")
            self.assertEqual(profile["backend"]["orm"], "activerecord")
            self.assertEqual(profile["backend"]["testing"], "rspec")

    def test_sinatra(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "Gemfile"), "w") as f:
                f.write("gem 'sinatra'\ngem 'sequel'\ngem 'minitest'\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["framework"], "sinatra")
            self.assertEqual(profile["backend"]["orm"], "sequel")
            self.assertEqual(profile["backend"]["testing"], "minitest")

    def test_hanami(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "Gemfile"), "w") as f:
                f.write("gem 'hanami', '~> 2.1'\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["framework"], "hanami")


if __name__ == "__main__":
    unittest.main()
