"""Tests for DevOps and database detection."""
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


class TestDevOps(unittest.TestCase):
    def test_docker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "Dockerfile"), "w").close()
            profile = build_profile(tmpdir)
            self.assertEqual(profile["devops"]["containerize"], "docker")

    def test_github_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".github", "workflows"))
            profile = build_profile(tmpdir)
            self.assertEqual(profile["devops"]["ci"], "github-actions")

    def test_gitlab_ci(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, ".gitlab-ci.yml"), "w").close()
            profile = build_profile(tmpdir)
            self.assertEqual(profile["devops"]["ci"], "gitlab-ci")

    def test_database_from_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, ".env.example"), "w") as f:
                f.write("DATABASE_URL=postgresql://localhost:5432/mydb\n")
            with open(os.path.join(tmpdir, "requirements.txt"), "w") as f:
                f.write("fastapi==0.104.0\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["database"], "postgresql")

    # --- Deploy detection ---
    def test_deploy_vercel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "vercel.json"), "w").close()
            profile = build_profile(tmpdir)
            self.assertEqual(profile["devops"]["deploy"], "vercel")

    def test_deploy_netlify(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "netlify.toml"), "w").close()
            profile = build_profile(tmpdir)
            self.assertEqual(profile["devops"]["deploy"], "netlify")

    def test_deploy_fly_io(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "fly.toml"), "w").close()
            profile = build_profile(tmpdir)
            self.assertEqual(profile["devops"]["deploy"], "fly-io")

    def test_deploy_heroku(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "Procfile"), "w").close()
            profile = build_profile(tmpdir)
            self.assertEqual(profile["devops"]["deploy"], "heroku")

    def test_deploy_kubernetes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "k8s"))
            profile = build_profile(tmpdir)
            self.assertEqual(profile["devops"]["deploy"], "kubernetes")

    # --- Monitoring detection ---
    def test_monitoring_datadog(self):
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "package.json"), "w") as f:
                json.dump({"name": "test", "dependencies": {"dd-trace": "^4.0.0"}}, f)
            profile = build_profile(tmpdir)
            self.assertEqual(profile["devops"]["monitoring"], "datadog")

    def test_monitoring_sentry(self):
        import json
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "package.json"), "w") as f:
                json.dump({"name": "test", "dependencies": {"@sentry/node": "^7.0.0"}}, f)
            profile = build_profile(tmpdir)
            self.assertEqual(profile["devops"]["monitoring"], "sentry")

    def test_monitoring_newrelic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "requirements.txt"), "w") as f:
                f.write("newrelic==8.0.0\nfastapi==0.104.0\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["devops"]["monitoring"], "newrelic")


if __name__ == "__main__":
    unittest.main()
