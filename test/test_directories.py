"""Tests for frontend/backend directory detection."""
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


class TestDirectories(unittest.TestCase):
    def _make_nextjs_project(self, tmpdir):
        """Helper to create a Next.js project with app router."""
        with open(os.path.join(tmpdir, "package.json"), "w") as f:
            json.dump({"name": "test", "dependencies": {"next": "14.0.0", "react": "18.0.0"}}, f)
        app_dir = os.path.join(tmpdir, "app")
        os.makedirs(app_dir, exist_ok=True)
        open(os.path.join(app_dir, "page.tsx"), "w").close()
        open(os.path.join(app_dir, "layout.tsx"), "w").close()

    def test_frontend_app_dir_nextjs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_nextjs_project(tmpdir)
            profile = build_profile(tmpdir)
            self.assertEqual(profile["frontend"]["dir"], "app")

    def test_frontend_src_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "package.json"), "w") as f:
                json.dump({"name": "test", "dependencies": {"react": "18.0.0"}}, f)
            os.makedirs(os.path.join(tmpdir, "src"))
            profile = build_profile(tmpdir)
            self.assertEqual(profile["frontend"]["dir"], "src")

    def test_frontend_pages_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "package.json"), "w") as f:
                json.dump({"name": "test", "dependencies": {"react": "18.0.0"}}, f)
            os.makedirs(os.path.join(tmpdir, "pages"))
            profile = build_profile(tmpdir)
            self.assertEqual(profile["frontend"]["dir"], "pages")

    def test_backend_server_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "package.json"), "w") as f:
                json.dump({"name": "test", "dependencies": {"express": "4.0.0"}}, f)
            os.makedirs(os.path.join(tmpdir, "server"))
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["dir"], "server")

    def test_backend_api_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "requirements.txt"), "w") as f:
                f.write("fastapi==0.104.0\n")
            os.makedirs(os.path.join(tmpdir, "api"))
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["dir"], "api")

    def test_go_cmd_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "go.mod"), "w") as f:
                f.write("module example.com/myapp\n\ngo 1.21\n")
            os.makedirs(os.path.join(tmpdir, "cmd"))
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["dir"], "cmd")

    def test_no_dir_when_no_stack(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = build_profile(tmpdir)
            self.assertNotIn("frontend", profile)
            self.assertNotIn("backend", profile)


if __name__ == "__main__":
    unittest.main()
