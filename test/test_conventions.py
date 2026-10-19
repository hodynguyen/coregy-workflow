"""Tests for conventions detection (commit_style, git_branch)."""
import json
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


class TestConventions(unittest.TestCase):
    def test_commitlint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, ".commitlintrc.json"), "w").close()
            profile = build_profile(tmpdir)
            self.assertEqual(profile["conventions"]["commit_style"], "conventional")
            self.assertEqual(profile["conventions"]["git_branch"], "feature-branch")

    def test_commitlint_config_js(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "commitlint.config.js"), "w").close()
            profile = build_profile(tmpdir)
            self.assertEqual(profile["conventions"]["commit_style"], "conventional")

    def test_commitizen_czrc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, ".czrc"), "w").close()
            profile = build_profile(tmpdir)
            self.assertEqual(profile["conventions"]["commit_style"], "commitizen")

    def test_commitizen_package_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "package.json"), "w") as f:
                json.dump({"name": "test", "config": {"commitizen": {"path": "cz-conventional-changelog"}}}, f)
            profile = build_profile(tmpdir)
            self.assertEqual(profile["conventions"]["commit_style"], "commitizen")

    def test_gitflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, ".gitflow"), "w").close()
            profile = build_profile(tmpdir)
            self.assertEqual(profile["conventions"]["git_branch"], "gitflow")

    def test_trunk_based(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "trunk.yaml"), "w").close()
            profile = build_profile(tmpdir)
            self.assertEqual(profile["conventions"]["git_branch"], "trunk-based")

    def test_no_conventions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = build_profile(tmpdir)
            self.assertNotIn("conventions", profile)


if __name__ == "__main__":
    unittest.main()
