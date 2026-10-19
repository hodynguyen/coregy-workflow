"""Tests for the project health dashboard module."""
import json
import os
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "hody-workflow",
    "skills",
    "project-profile",
    "scripts",
)
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

from health import (
    check_kb_completeness,
    count_tech_debt,
    get_workflow_stats,
    get_dependency_health,
    build_health_report,
    format_health_report,
    generate_recommendations,
)


def _write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class TestCheckKBCompleteness(unittest.TestCase):
    def test_check_kb_completeness_all_populated(self):
        """All 6 files populated with real content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for filename in [
                "architecture.md",
                "decisions.md",
                "api-contracts.md",
                "business-rules.md",
                "tech-debt.md",
                "runbook.md",
            ]:
                _write_file(
                    os.path.join(tmpdir, filename),
                    "# {}\n\nThis is real content describing the system in detail with enough length to pass the threshold check.\n".format(
                        filename
                    ),
                )
            result = check_kb_completeness(tmpdir)
            self.assertEqual(result["total_files"], 6)
            self.assertEqual(result["populated_files"], 6)
            self.assertEqual(result["percentage"], 100)
            for detail in result["details"]:
                self.assertEqual(detail["status"], "populated")

    def test_check_kb_completeness_empty(self):
        """No KB directory — all files missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_dir = os.path.join(tmpdir, "nonexistent")
            result = check_kb_completeness(kb_dir)
            self.assertEqual(result["total_files"], 6)
            self.assertEqual(result["populated_files"], 0)
            self.assertEqual(result["percentage"], 0)
            for detail in result["details"]:
                self.assertEqual(detail["status"], "missing")

    def test_check_kb_completeness_partial(self):
        """Some files are template-only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Populated file
            _write_file(
                os.path.join(tmpdir, "architecture.md"),
                "# Architecture\n\nOur system uses a microservices pattern with event-driven communication between services.\n",
            )
            # Template file (contains YYYY-MM-DD marker)
            _write_file(
                os.path.join(tmpdir, "tech-debt.md"),
                "---\ntags: [tech-debt]\ncreated: YYYY-MM-DD\n---\n\n# Tech Debt\n\n## [Issue Title]\n",
            )
            result = check_kb_completeness(tmpdir)
            self.assertEqual(result["populated_files"], 1)
            # Find statuses
            statuses = {d["file"]: d["status"] for d in result["details"]}
            self.assertEqual(statuses["architecture.md"], "populated")
            self.assertEqual(statuses["tech-debt.md"], "template")
            self.assertEqual(statuses["decisions.md"], "missing")

    def test_check_kb_completeness_missing_files(self):
        """Some files exist, some do not."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_file(
                os.path.join(tmpdir, "architecture.md"),
                "# Architecture\n\nReal content here with enough length to be considered populated by the checker.\n",
            )
            _write_file(
                os.path.join(tmpdir, "runbook.md"),
                "# Runbook\n\nDeployment steps for production release including all necessary configuration details.\n",
            )
            result = check_kb_completeness(tmpdir)
            self.assertEqual(result["populated_files"], 2)
            statuses = {d["file"]: d["status"] for d in result["details"]}
            self.assertEqual(statuses["architecture.md"], "populated")
            self.assertEqual(statuses["runbook.md"], "populated")
            self.assertEqual(statuses["api-contracts.md"], "missing")


class TestCountTechDebt(unittest.TestCase):
    def test_count_tech_debt_empty(self):
        """No tech debt items in file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_file(
                os.path.join(tmpdir, "tech-debt.md"),
                "# Tech Debt\n\nNo items yet.\n",
            )
            result = count_tech_debt(tmpdir)
            self.assertEqual(result["total"], 0)
            self.assertEqual(result["items"], [])

    def test_count_tech_debt_with_items(self):
        """Parses items with priorities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_file(
                os.path.join(tmpdir, "tech-debt.md"),
                """# Tech Debt

## Migrate auth library
- **Priority**: high
- **Area**: backend
- **Description**: Current auth library is deprecated
- Created: 2025-12-01

## Refactor CSS modules
- **Priority**: medium
- **Area**: frontend
- **Description**: Inconsistent styling approach
- Created: 2026-01-15

## Update README
- **Priority**: low
- **Area**: docs
- **Description**: Outdated setup instructions
- Created: 2026-02-01
""",
            )
            result = count_tech_debt(tmpdir)
            self.assertEqual(result["total"], 3)
            self.assertEqual(result["by_priority"]["high"], 1)
            self.assertEqual(result["by_priority"]["medium"], 1)
            self.assertEqual(result["by_priority"]["low"], 1)
            self.assertIsNotNone(result["oldest_days"])
            self.assertEqual(result["items"][0]["title"], "Migrate auth library")
            self.assertEqual(result["items"][0]["priority"], "high")

    def test_count_tech_debt_no_file(self):
        """File does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = count_tech_debt(tmpdir)
            self.assertEqual(result["total"], 0)
            self.assertIsNone(result["oldest_days"])


class TestGetWorkflowStats(unittest.TestCase):
    def test_get_workflow_stats_no_state(self):
        """No state.json exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_workflow_stats(tmpdir)
            self.assertEqual(result["total_started"], 0)
            self.assertEqual(result["total_completed"], 0)
            self.assertEqual(result["completion_rate"], 0)
            self.assertEqual(len(result["unused_agents"]), 9)

    def test_get_workflow_stats_active(self):
        """Active workflow in state.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "status": "in_progress",
                "feature": "Add user auth",
                "agent_log": [
                    {"agent": "researcher"},
                    {"agent": "architect"},
                ],
            }
            _write_file(os.path.join(tmpdir, "state.json"), json.dumps(state))
            result = get_workflow_stats(tmpdir)
            self.assertEqual(result["total_started"], 1)
            self.assertEqual(result["total_completed"], 0)
            self.assertIn("researcher", result["agent_usage"])
            self.assertIn("architect", result["agent_usage"])

    def test_get_workflow_stats_completed(self):
        """Completed workflow with agent log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "status": "completed",
                "feature": "Add user auth",
                "agent_log": [
                    {"agent": "researcher"},
                    {"agent": "architect"},
                    {"agent": "backend"},
                    {"agent": "code-reviewer"},
                ],
            }
            _write_file(os.path.join(tmpdir, "state.json"), json.dumps(state))
            result = get_workflow_stats(tmpdir)
            self.assertEqual(result["total_started"], 1)
            self.assertEqual(result["total_completed"], 1)
            self.assertEqual(result["completion_rate"], 100)
            self.assertEqual(result["avg_agents_per_workflow"], 4.0)

    def test_get_workflow_stats_agent_usage(self):
        """Counts agent usage correctly across current and history."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "status": "in_progress",
                "agent_log": [{"agent": "backend"}],
            }
            history = [
                {
                    "status": "completed",
                    "agent_log": [
                        {"agent": "researcher"},
                        {"agent": "backend"},
                        {"agent": "code-reviewer"},
                    ],
                },
                {
                    "status": "completed",
                    "agent_log": [
                        {"agent": "backend"},
                        {"agent": "unit-tester"},
                    ],
                },
            ]
            _write_file(os.path.join(tmpdir, "state.json"), json.dumps(state))
            _write_file(
                os.path.join(tmpdir, "state_history.json"), json.dumps(history)
            )
            result = get_workflow_stats(tmpdir)
            self.assertEqual(result["total_started"], 3)
            self.assertEqual(result["total_completed"], 2)
            self.assertEqual(result["agent_usage"]["backend"], 3)
            self.assertEqual(result["agent_usage"]["researcher"], 1)
            self.assertEqual(result["agent_usage"]["code-reviewer"], 1)
            self.assertEqual(result["agent_usage"]["unit-tester"], 1)
            self.assertIn("frontend", result["unused_agents"])
            self.assertIn("devops", result["unused_agents"])


class TestGetDependencyHealth(unittest.TestCase):
    def test_get_dependency_health_no_profile(self):
        """No profile.yaml exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_dependency_health(os.path.join(tmpdir, "profile.yaml"))
            self.assertEqual(result["outdated_count"], 0)
            self.assertEqual(result["vulnerability_count"], 0)
            self.assertEqual(result["total_deps"], 0)

    def test_get_dependency_health_basic(self):
        """Profile without deep analysis section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_file(
                os.path.join(tmpdir, "profile.yaml"),
                "project:\n  name: test-app\n  type: fullstack\n",
            )
            result = get_dependency_health(os.path.join(tmpdir, "profile.yaml"))
            self.assertEqual(result["outdated_count"], 0)
            self.assertEqual(result["total_deps"], 0)


    def test_reads_deep_analysis_as_written_by_detector(self):
        """detect_stack --deep writes lists + dependency_count (not *_count keys)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_file(os.path.join(tmpdir, "profile.yaml"),
                        "deep_analysis:\n"
                        "  dependency_count: 42\n"
                        "  outdated:\n"
                        "    - package: a\n      current: 1.0.0\n"
                        "    - package: b\n      current: 2.0.0\n"
                        "  security:\n"
                        "    - package: c\n      severity: high\n")
            result = get_dependency_health(os.path.join(tmpdir, "profile.yaml"))
            self.assertEqual(result["total_deps"], 42)
            self.assertEqual(result["outdated_count"], 2)
            self.assertEqual(result["vulnerability_count"], 1)


class TestTemplateFrontmatter(unittest.TestCase):
    def test_populated_file_with_template_date_in_frontmatter(self):
        """`created: YYYY-MM-DD` left in frontmatter must not mark a written file as template."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_file(os.path.join(tmpdir, "architecture.md"),
                        "---\ntags: [architecture]\ncreated: YYYY-MM-DD\n---\n\n"
                        "# Architecture\n\n## System Overview\n"
                        "A real description of the service and its components.\n")
            result = check_kb_completeness(tmpdir)
            status = {d["file"]: d["status"] for d in result["details"]}
            self.assertEqual(status["architecture.md"], "populated")

class TestBuildHealthReport(unittest.TestCase):
    def test_build_health_report(self):
        """Full report structure has all expected keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hody_dir = os.path.join(tmpdir, ".hody")
            kb_dir = os.path.join(hody_dir, "knowledge")
            os.makedirs(kb_dir)
            _write_file(
                os.path.join(hody_dir, "profile.yaml"),
                "project:\n  name: test-app\n  type: fullstack\n",
            )
            _write_file(
                os.path.join(kb_dir, "architecture.md"),
                "# Architecture\n\nReal content describing the system architecture in sufficient detail.\n",
            )
            report = build_health_report(tmpdir)
            self.assertIn("kb", report)
            self.assertIn("tech_debt", report)
            self.assertIn("workflows", report)
            self.assertIn("dependencies", report)
            self.assertIn("recommendations", report)
            self.assertIn("generated_at", report)
            self.assertIn("project_name", report)
            self.assertEqual(report["project_name"], "test-app")


class TestFormatHealthReport(unittest.TestCase):
    def test_format_health_report(self):
        """Formatted output contains key sections."""
        report = {
            "project_name": "my-app",
            "kb": {
                "total_files": 6,
                "populated_files": 4,
                "percentage": 67,
                "details": [],
            },
            "tech_debt": {
                "total": 2,
                "by_priority": {"high": 1, "medium": 1, "low": 0},
                "oldest_days": 14,
                "items": [
                    {"title": "Fix auth", "priority": "high", "created": "2026-02-01"},
                ],
            },
            "workflows": {
                "total_started": 3,
                "total_completed": 2,
                "total_aborted": 0,
                "completion_rate": 67,
                "avg_agents_per_workflow": 3.0,
                "agent_usage": {"backend": 3, "code-reviewer": 2},
                "unused_agents": ["spec-verifier", "devops"],
            },
            "dependencies": {
                "outdated_count": 1,
                "vulnerability_count": 0,
                "total_deps": 50,
            },
            "recommendations": ["Try spec-verifier agent to validate implementation"],
            "generated_at": "2026-02-17T00:00:00Z",
        }
        output = format_health_report(report)
        self.assertIn("Project Health -- my-app", output)
        self.assertIn("Knowledge Base:", output)
        self.assertIn("67%", output)
        self.assertIn("Tech Debt:", output)
        self.assertIn("2 open items", output)
        self.assertIn("1 high", output)
        self.assertIn("oldest: 14 days", output)
        self.assertIn("Workflows:", output)
        self.assertIn("3 started", output)
        self.assertIn("Recommendations:", output)
        self.assertIn("spec-verifier", output)


class TestGenerateRecommendations(unittest.TestCase):
    def test_generate_recommendations_empty_kb(self):
        """Recommends update-kb when KB is less than 50%."""
        report = {
            "kb": {"percentage": 17, "details": []},
            "tech_debt": {"by_priority": {"high": 0, "medium": 0, "low": 0}, "items": [], "oldest_days": None},
            "workflows": {"total_started": 0, "unused_agents": []},
            "dependencies": {"outdated_count": 0, "vulnerability_count": 0},
        }
        recs = generate_recommendations(report)
        self.assertTrue(
            any("/hody-workflow:update-kb" in r for r in recs),
            "Should recommend update-kb for low KB completeness",
        )

    def test_generate_recommendations_high_tech_debt(self):
        """Recommends addressing high-priority tech debt."""
        report = {
            "kb": {"percentage": 100, "details": []},
            "tech_debt": {
                "by_priority": {"high": 2, "medium": 0, "low": 0},
                "items": [
                    {"title": "Fix auth", "priority": "high"},
                    {"title": "Migrate DB", "priority": "high"},
                ],
                "oldest_days": 5,
            },
            "workflows": {"total_started": 1, "total_completed": 1, "completion_rate": 100, "unused_agents": []},
            "dependencies": {"outdated_count": 0, "vulnerability_count": 0},
        }
        recs = generate_recommendations(report)
        self.assertTrue(
            any("high-priority tech debt" in r for r in recs),
            "Should recommend addressing high-priority tech debt",
        )
        self.assertTrue(
            any("Fix auth" in r for r in recs),
            "Should mention the specific item title",
        )

    def test_generate_recommendations_unused_agents(self):
        """Recommends trying unused agents."""
        report = {
            "kb": {"percentage": 100, "details": []},
            "tech_debt": {"by_priority": {"high": 0, "medium": 0, "low": 0}, "items": [], "oldest_days": None},
            "workflows": {
                "total_started": 2,
                "total_completed": 2,
                "completion_rate": 100,
                "unused_agents": ["spec-verifier", "devops"],
            },
            "dependencies": {"outdated_count": 0, "vulnerability_count": 0},
        }
        recs = generate_recommendations(report)
        self.assertTrue(
            any("spec-verifier" in r or "devops" in r for r in recs),
            "Should recommend trying an unused agent",
        )

    def test_generate_recommendations_no_workflows(self):
        """Recommends start-feature when no workflows exist."""
        report = {
            "kb": {"percentage": 100, "details": []},
            "tech_debt": {"by_priority": {"high": 0, "medium": 0, "low": 0}, "items": [], "oldest_days": None},
            "workflows": {"total_started": 0, "unused_agents": []},
            "dependencies": {"outdated_count": 0, "vulnerability_count": 0},
        }
        recs = generate_recommendations(report)
        self.assertTrue(
            any("/hody-workflow:start-feature" in r for r in recs),
            "Should recommend start-feature",
        )

    def test_generate_recommendations_all_good(self):
        """Few recommendations when project is healthy."""
        report = {
            "kb": {"percentage": 100, "details": []},
            "tech_debt": {"by_priority": {"high": 0, "medium": 0, "low": 0}, "items": [], "oldest_days": None},
            "workflows": {
                "total_started": 5,
                "total_completed": 5,
                "completion_rate": 100,
                "unused_agents": [],
            },
            "dependencies": {"outdated_count": 0, "vulnerability_count": 0},
        }
        recs = generate_recommendations(report)
        self.assertEqual(
            len(recs),
            0,
            "Healthy project should have no recommendations, got: {}".format(recs),
        )


if __name__ == "__main__":
    unittest.main()
