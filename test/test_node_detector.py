"""Tests for Node.js detector."""
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


class TestNodeProject(unittest.TestCase):
    def _make_package_json(self, tmpdir, deps=None, dev_deps=None):
        pkg = {"name": "test-app", "dependencies": deps or {}, "devDependencies": dev_deps or {}}
        with open(os.path.join(tmpdir, "package.json"), "w") as f:
            json.dump(pkg, f)

    def test_react_frontend(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(
                tmpdir,
                deps={"react": "^18.0.0", "react-dom": "^18.0.0"},
                dev_deps={"typescript": "^5.0.0", "vitest": "^1.0.0"},
            )
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "frontend")
            self.assertEqual(profile["frontend"]["framework"], "react")
            self.assertEqual(profile["frontend"]["language"], "typescript")
            self.assertEqual(profile["frontend"]["testing"], "vitest")

    def test_next_overrides_react(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(
                tmpdir,
                deps={"react": "^18.0.0", "next": "^14.0.0"},
            )
            profile = build_profile(tmpdir)
            self.assertEqual(profile["frontend"]["framework"], "next")

    def test_vue_frontend(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(tmpdir, deps={"vue": "^3.0.0"})
            profile = build_profile(tmpdir)
            self.assertEqual(profile["frontend"]["framework"], "vue")

    def test_express_backend(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(
                tmpdir,
                deps={"express": "^4.18.0", "@prisma/client": "^5.0.0"},
                dev_deps={"prisma": "^5.0.0"},
            )
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "backend")
            self.assertEqual(profile["backend"]["framework"], "express")
            self.assertEqual(profile["backend"]["orm"], "prisma")

    def test_fullstack(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(
                tmpdir,
                deps={"react": "^18.0.0", "fastify": "^4.0.0"},
            )
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "fullstack")
            self.assertEqual(profile["frontend"]["framework"], "react")
            self.assertEqual(profile["backend"]["framework"], "fastify")

    def test_state_management(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(tmpdir, deps={"react": "^18.0.0", "zustand": "^4.0.0"})
            profile = build_profile(tmpdir)
            self.assertEqual(profile["frontend"]["state"], "zustand")

    def test_styling_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(
                tmpdir,
                deps={"react": "^18.0.0"},
                dev_deps={"tailwindcss": "^3.0.0"},
            )
            profile = build_profile(tmpdir)
            self.assertEqual(profile["frontend"]["styling"], "tailwind")

    def test_conventions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(
                tmpdir,
                deps={"react": "^18.0.0"},
                dev_deps={"eslint": "^8.0.0", "prettier": "^3.0.0"},
            )
            profile = build_profile(tmpdir)
            self.assertEqual(profile["conventions"]["linter"], "eslint")
            self.assertEqual(profile["conventions"]["formatter"], "prettier")


class TestNodeAdditional(unittest.TestCase):
    def _make_package_json(self, tmpdir, deps=None, dev_deps=None):
        pkg = {"name": "test-app", "dependencies": deps or {}, "devDependencies": dev_deps or {}}
        with open(os.path.join(tmpdir, "package.json"), "w") as f:
            json.dump(pkg, f)

    def test_angular(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(tmpdir, deps={"@angular/core": "^17.0.0"})
            profile = build_profile(tmpdir)
            self.assertEqual(profile["frontend"]["framework"], "angular")

    def test_svelte(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(tmpdir, deps={"svelte": "^4.0.0"})
            profile = build_profile(tmpdir)
            self.assertEqual(profile["frontend"]["framework"], "svelte")

    def test_sveltekit_overrides_svelte(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(
                tmpdir,
                deps={"svelte": "^4.0.0"},
                dev_deps={"@sveltejs/kit": "^2.0.0"},
            )
            profile = build_profile(tmpdir)
            self.assertEqual(profile["frontend"]["framework"], "sveltekit")

    def test_nest_backend(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_package_json(
                tmpdir,
                deps={"@nestjs/core": "^10.0.0"},
                dev_deps={"typescript": "^5.0.0"},
            )
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "backend")
            self.assertEqual(profile["backend"]["framework"], "nest")
            self.assertEqual(profile["backend"]["language"], "typescript")


if __name__ == "__main__":
    unittest.main()
