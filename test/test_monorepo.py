"""Tests for monorepo detection."""
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


class TestMonorepoDetection(unittest.TestCase):
    def test_turborepo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "turbo.json"), "w") as f:
                f.write('{"$schema": "https://turbo.build/schema.json"}\n')
            with open(os.path.join(tmpdir, "package.json"), "w") as f:
                json.dump({"name": "monorepo", "workspaces": ["packages/*"]}, f)
            # Create a workspace package
            pkg_dir = os.path.join(tmpdir, "packages", "web")
            os.makedirs(pkg_dir)
            with open(os.path.join(pkg_dir, "package.json"), "w") as f:
                json.dump({"name": "web", "dependencies": {"react": "^18.0.0"}}, f)
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "monorepo")
            self.assertEqual(profile["monorepo"]["tool"], "turborepo")
            self.assertEqual(len(profile["monorepo"]["workspaces"]), 1)
            self.assertEqual(profile["monorepo"]["workspaces"][0]["framework"], "react")

    def test_nx(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "nx.json"), "w") as f:
                f.write("{}\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "monorepo")
            self.assertEqual(profile["monorepo"]["tool"], "nx")

    def test_lerna(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "lerna.json"), "w") as f:
                f.write('{"version": "0.0.0"}\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "monorepo")
            self.assertEqual(profile["monorepo"]["tool"], "lerna")

    def test_pnpm_workspaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "pnpm-workspace.yaml"), "w") as f:
                f.write("packages:\n  - 'apps/*'\n")
            # Create a workspace
            app_dir = os.path.join(tmpdir, "apps", "api")
            os.makedirs(app_dir)
            with open(os.path.join(app_dir, "requirements.txt"), "w") as f:
                f.write("fastapi==0.104.0\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "monorepo")
            self.assertEqual(profile["monorepo"]["tool"], "pnpm-workspaces")
            self.assertEqual(len(profile["monorepo"]["workspaces"]), 1)
            self.assertEqual(profile["monorepo"]["workspaces"][0]["language"], "python")
            self.assertEqual(profile["monorepo"]["workspaces"][0]["framework"], "fastapi")

    def test_turborepo_multiple_workspaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "turbo.json"), "w") as f:
                f.write("{}\n")
            with open(os.path.join(tmpdir, "package.json"), "w") as f:
                json.dump({"name": "mono", "workspaces": ["packages/*"]}, f)
            # Frontend workspace
            fe_dir = os.path.join(tmpdir, "packages", "frontend")
            os.makedirs(fe_dir)
            with open(os.path.join(fe_dir, "package.json"), "w") as f:
                json.dump({"name": "frontend", "dependencies": {"vue": "^3.0.0"}}, f)
            # Backend workspace
            be_dir = os.path.join(tmpdir, "packages", "api")
            os.makedirs(be_dir)
            with open(os.path.join(be_dir, "go.mod"), "w") as f:
                f.write("module api\n\nrequire github.com/gin-gonic/gin v1.9\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "monorepo")
            self.assertEqual(len(profile["monorepo"]["workspaces"]), 2)
            frameworks = {ws["framework"] for ws in profile["monorepo"]["workspaces"] if "framework" in ws}
            self.assertIn("vue", frameworks)
            self.assertIn("gin", frameworks)


if __name__ == "__main__":
    unittest.main()
