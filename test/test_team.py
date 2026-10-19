"""Tests for team roles and permissions."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Add scripts dir to path
SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "coregy-workflow",
    "skills",
    "project-profile",
    "scripts",
)
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

from team import (
    DEFAULT_ROLES,
    ALL_AGENTS,
    _parse_team_yaml,
    load_team_config,
    get_current_user,
    get_user_role,
    get_role_permissions,
    can_use_agent,
    check_workflow_permissions,
    generate_default_team_config,
    get_team_summary,
)


class TestDefaultRoles(unittest.TestCase):
    def test_default_roles_structure(self):
        """DEFAULT_ROLES has all 4 roles with correct fields."""
        self.assertIn("lead", DEFAULT_ROLES)
        self.assertIn("developer", DEFAULT_ROLES)
        self.assertIn("reviewer", DEFAULT_ROLES)
        self.assertIn("junior", DEFAULT_ROLES)
        self.assertEqual(len(DEFAULT_ROLES), 4)

        # Lead has all agents and can skip
        lead = DEFAULT_ROLES["lead"]
        self.assertTrue(lead["can_skip_agents"])
        self.assertTrue(lead["can_modify_contracts"])
        self.assertEqual(lead["agents"], "all")
        self.assertFalse(lead["requires_review"])

        # Developer
        dev = DEFAULT_ROLES["developer"]
        self.assertFalse(dev["can_skip_agents"])
        self.assertIsInstance(dev["agents"], list)
        self.assertEqual(len(dev["agents"]), 5)

        # Reviewer
        rev = DEFAULT_ROLES["reviewer"]
        self.assertTrue(rev.get("can_approve_merge"))

        # Junior
        jun = DEFAULT_ROLES["junior"]
        self.assertTrue(jun.get("requires_architect_approval"))
        self.assertEqual(len(jun["agents"]), 3)


class TestLoadTeamConfig(unittest.TestCase):
    def test_load_team_config_no_file(self):
        """Returns default config when .coregy/team.yaml doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_team_config(tmpdir)
            self.assertIn("roles", config)
            self.assertIn("members", config)
            self.assertEqual(config["members"], [])
            self.assertIn("lead", config["roles"])
            self.assertIn("developer", config["roles"])

    def test_load_team_config_custom(self):
        """Reads .coregy/team.yaml correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            coregy_dir = os.path.join(tmpdir, ".coregy")
            os.makedirs(coregy_dir)
            with open(os.path.join(coregy_dir, "team.yaml"), "w") as f:
                f.write(
                    "roles:\n"
                    "  lead:\n"
                    "    can_skip_agents: true\n"
                    "    agents: all\n"
                    "members:\n"
                    "  - name: alice\n"
                    "    role: lead\n"
                    "  - name: bob\n"
                    "    role: developer\n"
                )
            config = load_team_config(tmpdir)
            self.assertEqual(len(config["members"]), 2)
            self.assertEqual(config["members"][0]["name"], "alice")
            self.assertEqual(config["members"][0]["role"], "lead")
            self.assertEqual(config["members"][1]["name"], "bob")
            self.assertEqual(config["members"][1]["role"], "developer")


class TestGetCurrentUser(unittest.TestCase):
    @patch.dict(os.environ, {"COREGY_USER": "testuser"})
    def test_get_current_user_from_env(self):
        """Reads COREGY_USER env var."""
        with tempfile.TemporaryDirectory() as tmpdir:
            user = get_current_user(tmpdir)
            self.assertEqual(user, "testuser")

    @patch.dict(os.environ, {}, clear=True)
    @patch("team.subprocess.run")
    def test_get_current_user_from_git(self, mock_run):
        """Reads from git config user.name."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "gituser\n"
        mock_run.return_value = mock_result

        # Ensure COREGY_USER is not set
        os.environ.pop("COREGY_USER", None)

        with tempfile.TemporaryDirectory() as tmpdir:
            user = get_current_user(tmpdir)
            self.assertEqual(user, "gituser")
            mock_run.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    @patch("team.subprocess.run", side_effect=FileNotFoundError)
    def test_get_current_user_no_git(self, mock_run):
        """Returns None gracefully when git is not available."""
        os.environ.pop("COREGY_USER", None)

        with tempfile.TemporaryDirectory() as tmpdir:
            user = get_current_user(tmpdir)
            self.assertIsNone(user)


class TestGetUserRole(unittest.TestCase):
    def setUp(self):
        self.config = {
            "roles": dict(DEFAULT_ROLES),
            "members": [
                {"name": "alice", "role": "lead"},
                {"name": "bob", "role": "junior"},
            ],
        }

    def test_get_user_role_member_found(self):
        """Returns assigned role for known member."""
        self.assertEqual(get_user_role(self.config, "alice"), "lead")
        self.assertEqual(get_user_role(self.config, "bob"), "junior")

    def test_get_user_role_default(self):
        """Returns 'developer' for unknown users."""
        self.assertEqual(get_user_role(self.config, "unknown"), "developer")
        self.assertEqual(get_user_role(self.config, None), "developer")

    def test_get_user_role_solo_project_is_lead(self):
        """No members configured: the only user must not be locked out of agents."""
        config = {"roles": dict(DEFAULT_ROLES), "members": []}
        self.assertEqual(get_user_role(config, "anyone"), "lead")
        self.assertEqual(get_user_role(config, None), "lead")


class TestGetRolePermissions(unittest.TestCase):
    def setUp(self):
        self.config = {
            "roles": dict(DEFAULT_ROLES),
            "members": [],
        }

    def test_get_role_permissions_lead(self):
        """Lead has all agents and can skip."""
        perms = get_role_permissions(self.config, "lead")
        self.assertTrue(perms["can_skip_agents"])
        self.assertTrue(perms["can_modify_contracts"])
        self.assertEqual(perms["agents"], "all")
        self.assertFalse(perms["requires_review"])

    def test_get_role_permissions_developer(self):
        """Developer has 5 agents."""
        perms = get_role_permissions(self.config, "developer")
        self.assertFalse(perms["can_skip_agents"])
        self.assertIsInstance(perms["agents"], list)
        self.assertEqual(len(perms["agents"]), 5)
        self.assertIn("frontend", perms["agents"])
        self.assertIn("backend", perms["agents"])
        self.assertNotIn("devops", perms["agents"])

    def test_get_role_permissions_reviewer(self):
        """Reviewer has review-oriented agents."""
        perms = get_role_permissions(self.config, "reviewer")
        self.assertIn("code-reviewer", perms["agents"])
        self.assertIn("spec-verifier", perms["agents"])
        self.assertIn("integration-tester", perms["agents"])
        self.assertFalse(perms["can_skip_agents"])

    def test_get_role_permissions_junior(self):
        """Junior has restricted agents."""
        perms = get_role_permissions(self.config, "junior")
        self.assertFalse(perms["can_skip_agents"])
        self.assertTrue(perms["requires_review"])
        self.assertEqual(len(perms["agents"]), 3)
        self.assertNotIn("architect", perms["agents"])
        self.assertNotIn("devops", perms["agents"])


class TestCanUseAgent(unittest.TestCase):
    def setUp(self):
        self.config = {
            "roles": dict(DEFAULT_ROLES),
            "members": [
                {"name": "alice", "role": "lead"},
                {"name": "bob", "role": "developer"},
                {"name": "charlie", "role": "junior"},
            ],
        }

    def test_can_use_agent_lead_all(self):
        """Lead can use any agent."""
        for agent in ALL_AGENTS:
            allowed, reason = can_use_agent(self.config, "alice", agent)
            self.assertTrue(allowed, f"Lead should access {agent}: {reason}")

    def test_can_use_agent_developer_allowed(self):
        """Developer can use allowed agents."""
        allowed, reason = can_use_agent(self.config, "bob", "frontend")
        self.assertTrue(allowed)
        allowed, reason = can_use_agent(self.config, "bob", "backend")
        self.assertTrue(allowed)

    def test_can_use_agent_developer_denied(self):
        """Developer can't use devops."""
        allowed, reason = can_use_agent(self.config, "bob", "devops")
        self.assertFalse(allowed)
        self.assertIn("devops", reason)

    def test_can_use_agent_junior_restricted(self):
        """Junior can't use architect."""
        allowed, reason = can_use_agent(self.config, "charlie", "architect")
        self.assertFalse(allowed)
        allowed, reason = can_use_agent(self.config, "charlie", "devops")
        self.assertFalse(allowed)
        # But can use frontend
        allowed, reason = can_use_agent(self.config, "charlie", "frontend")
        self.assertTrue(allowed)


class TestCheckWorkflowPermissions(unittest.TestCase):
    def setUp(self):
        self.config = {
            "roles": dict(DEFAULT_ROLES),
            "members": [
                {"name": "alice", "role": "lead"},
                {"name": "bob", "role": "developer"},
            ],
        }

    def test_check_workflow_skip_lead(self):
        """Lead can skip agents."""
        allowed, reason = check_workflow_permissions(
            self.config, "alice", "skip_agent"
        )
        self.assertTrue(allowed)

    def test_check_workflow_skip_developer(self):
        """Developer can't skip agents."""
        allowed, reason = check_workflow_permissions(
            self.config, "bob", "skip_agent"
        )
        self.assertFalse(allowed)


class TestGenerateDefaultConfig(unittest.TestCase):
    def test_generate_default_config(self):
        """Returns valid YAML-like content with all roles."""
        content = generate_default_team_config()
        self.assertIn("roles:", content)
        self.assertIn("lead:", content)
        self.assertIn("developer:", content)
        self.assertIn("reviewer:", content)
        self.assertIn("junior:", content)
        self.assertIn("members:", content)
        self.assertIn("can_skip_agents:", content)
        self.assertIn("agents:", content)


class TestGetTeamSummary(unittest.TestCase):
    @patch("team.get_current_user", return_value="alice")
    def test_get_team_summary(self, mock_user):
        """Returns correct structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            coregy_dir = os.path.join(tmpdir, ".coregy")
            os.makedirs(coregy_dir)
            with open(os.path.join(coregy_dir, "team.yaml"), "w") as f:
                f.write(
                    "roles:\n"
                    "  lead:\n"
                    "    can_skip_agents: true\n"
                    "    agents: all\n"
                    "members:\n"
                    "  - name: alice\n"
                    "    role: lead\n"
                )
            summary = get_team_summary(tmpdir)
            self.assertIn("roles", summary)
            self.assertIn("member_count", summary)
            self.assertIn("current_user", summary)
            self.assertIn("current_role", summary)
            self.assertEqual(summary["current_user"], "alice")
            self.assertEqual(summary["current_role"], "lead")
            self.assertEqual(summary["member_count"], 1)


class TestParseTeamYaml(unittest.TestCase):
    def test_parse_team_yaml_basic(self):
        """Parses roles and members correctly."""
        content = (
            "roles:\n"
            "  custom_role:\n"
            "    can_skip_agents: false\n"
            "    agents:\n"
            "      - frontend\n"
            "      - backend\n"
            "members:\n"
            "  - name: dave\n"
            "    role: custom_role\n"
        )
        parsed = _parse_team_yaml(content)
        self.assertIn("custom_role", parsed["roles"])
        self.assertEqual(
            parsed["roles"]["custom_role"]["agents"], ["frontend", "backend"]
        )
        self.assertFalse(parsed["roles"]["custom_role"]["can_skip_agents"])
        self.assertEqual(len(parsed["members"]), 1)
        self.assertEqual(parsed["members"][0]["name"], "dave")
        self.assertEqual(parsed["members"][0]["role"], "custom_role")


if __name__ == "__main__":
    unittest.main()
