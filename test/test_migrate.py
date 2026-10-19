"""Tests for the Hody -> Coregy project migration (migrate.py + SessionStart hook)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PLUGIN_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "plugins", "coregy-workflow"))
SCRIPTS_DIR = os.path.join(PLUGIN_DIR, "skills", "project-profile", "scripts")
MIGRATE = os.path.join(SCRIPTS_DIR, "migrate.py")
HOOK = os.path.join(PLUGIN_DIR, "hooks", "inject_project_context.py")
sys.path.insert(0, SCRIPTS_DIR)

import migrate  # noqa: E402


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def read(path):
    with open(path) as f:
        return f.read()


class MigrateTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.legacy = os.path.join(self.tmpdir, ".hody")
        self.new = os.path.join(self.tmpdir, ".coregy")
        # The env fallback warnings depend on the caller's shell.
        self._env = {k: os.environ.pop(k) for k in migrate.LEGACY_ENV_VARS if k in os.environ}

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        os.environ.update(self._env)

    def make_legacy_project(self):
        write(os.path.join(self.legacy, "profile.yaml"), "project:\n  name: demo\n")
        write(os.path.join(self.legacy, "knowledge", "runbook.md"),
              "See .hody/knowledge/ and run /hody-workflow:init.\n"
              "Hody is the old name of this tool.\n")
        write(os.path.join(self.legacy, "tracker.db"), "\x00binary\x00")


class TestPlan(MigrateTestBase):
    def test_nothing_to_do_on_fresh_project(self):
        self.assertEqual(migrate.plan(self.tmpdir)["status"], "nothing-to-do")
        self.assertFalse(migrate.needs_migration(self.tmpdir))

    def test_plan_is_read_only(self):
        self.make_legacy_project()
        result = migrate.plan(self.tmpdir)
        self.assertEqual(result["status"], "ready")
        self.assertTrue(os.path.isdir(self.legacy))
        self.assertFalse(os.path.exists(self.new))
        files = [a.get("file") for a in result["actions"]]
        self.assertIn(os.path.join(".coregy", "knowledge", "runbook.md"), files)
        self.assertNotIn(os.path.join(".coregy", "profile.yaml"), files)

    def test_conflict_when_both_dirs_exist(self):
        self.make_legacy_project()
        os.makedirs(self.new)
        result = migrate.migrate(self.tmpdir)
        self.assertEqual(result["status"], "conflict")
        self.assertTrue(os.path.isdir(self.legacy))
        self.assertFalse(migrate.needs_migration(self.tmpdir))

    def test_legacy_env_var_reported(self):
        os.environ["HODY_USER"] = "alice"
        try:
            warnings = migrate.plan(self.tmpdir)["warnings"]
        finally:
            del os.environ["HODY_USER"]
        self.assertTrue(any("COREGY_USER" in w for w in warnings))


class TestMigrate(MigrateTestBase):
    def test_renames_dir_and_keeps_binary_data(self):
        self.make_legacy_project()
        result = migrate.migrate(self.tmpdir)
        self.assertEqual(result["status"], "migrated")
        self.assertFalse(os.path.exists(self.legacy))
        self.assertEqual(read(os.path.join(self.new, "tracker.db")), "\x00binary\x00")

    def test_rewrites_only_path_tokens(self):
        self.make_legacy_project()
        migrate.migrate(self.tmpdir)
        content = read(os.path.join(self.new, "knowledge", "runbook.md"))
        self.assertIn(".coregy/knowledge/", content)
        self.assertIn("/coregy-workflow:init", content)
        self.assertIn("Hody is the old name", content)

    def test_rewrites_gitignore(self):
        self.make_legacy_project()
        write(os.path.join(self.tmpdir, ".gitignore"),
              "node_modules/\n.hody/tracker.db\n**/.hody/cache\n.hodyrc\n")
        migrate.migrate(self.tmpdir)
        self.assertEqual(read(os.path.join(self.tmpdir, ".gitignore")),
                         "node_modules/\n.coregy/tracker.db\n**/.coregy/cache\n.hodyrc\n")

    def test_renames_enabled_plugin_key(self):
        settings = os.path.join(self.tmpdir, ".claude", "settings.json")
        write(settings, json.dumps({"enabledPlugins": {
            "a@x": True, "hody-workflow@hody": True, "b@y": False}, "other": 1}))
        result = migrate.migrate(self.tmpdir)
        self.assertEqual(result["status"], "migrated")
        data = json.loads(read(settings))
        self.assertEqual(list(data["enabledPlugins"]),
                         ["a@x", "coregy-workflow@coregy", "b@y"])
        self.assertEqual(data["other"], 1)

    def test_idempotent(self):
        self.make_legacy_project()
        migrate.migrate(self.tmpdir)
        self.assertEqual(migrate.migrate(self.tmpdir)["status"], "nothing-to-do")


class TestCli(MigrateTestBase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, MIGRATE, *args, "--cwd", self.tmpdir],
                              capture_output=True, text=True, timeout=30)

    def test_check_then_run(self):
        self.make_legacy_project()
        check = self.run_cli("check", "--json")
        self.assertEqual(check.returncode, 0)
        self.assertEqual(json.loads(check.stdout)["status"], "ready")
        self.assertTrue(os.path.isdir(self.legacy))

        run = self.run_cli("run")
        self.assertEqual(run.returncode, 0)
        self.assertIn("Migrated from Hody to Coregy", run.stdout)
        self.assertTrue(os.path.isdir(self.new))

    def test_conflict_exits_one(self):
        os.makedirs(self.legacy)
        os.makedirs(self.new)
        result = self.run_cli("run", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_no_subcommand_exits_one(self):
        self.assertEqual(self.run_cli().returncode, 1)


class TestSessionStartAutoMigrate(MigrateTestBase):
    def test_hook_migrates_and_tells_the_model(self):
        self.make_legacy_project()
        env = dict(os.environ, COREGY_SKIP_REFRESH="1")
        result = subprocess.run([sys.executable, HOOK], input=json.dumps({"cwd": self.tmpdir}),
                                capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(os.path.isdir(self.new))
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Migrated legacy .hody/", context)


if __name__ == "__main__":
    unittest.main()
