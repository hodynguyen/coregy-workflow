"""Tests for agent I/O contracts (contracts.py)."""
import os
import sys
import tempfile
import unittest

# Add scripts dir to path
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

from contracts import (
    load_contract,
    find_contract,
    list_contracts,
    validate_handoff,
    get_contracts_for_agent,
    _parse_yaml_simple,
)

# Path to actual contract files
CONTRACTS_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "hody-workflow",
    "agents",
    "contracts",
)
CONTRACTS_DIR = os.path.abspath(CONTRACTS_DIR)


class TestParseYamlSimple(unittest.TestCase):
    def test_simple_keys(self):
        content = "contract: architect-to-backend\nversion: 1\n"
        result = _parse_yaml_simple(content)
        self.assertEqual(result["contract"], "architect-to-backend")
        self.assertEqual(result["version"], "1")

    def test_list_of_dicts(self):
        content = "required_sections:\n  - name: API Endpoints\n    format: table\n  - name: Data Models\n    format: entity list\n"
        result = _parse_yaml_simple(content)
        self.assertEqual(len(result["required_sections"]), 2)
        self.assertEqual(result["required_sections"][0]["name"], "API Endpoints")
        self.assertEqual(result["required_sections"][1]["format"], "entity list")

    def test_comments_ignored(self):
        content = "# This is a comment\nkey: value\n"
        result = _parse_yaml_simple(content)
        self.assertEqual(result["key"], "value")

    def test_empty_lines_ignored(self):
        content = "key1: value1\n\nkey2: value2\n"
        result = _parse_yaml_simple(content)
        self.assertEqual(result["key1"], "value1")
        self.assertEqual(result["key2"], "value2")


class TestLoadContract(unittest.TestCase):
    def test_load_existing(self):
        path = os.path.join(CONTRACTS_DIR, "architect-to-backend.yaml")
        contract = load_contract(path)
        self.assertIsNotNone(contract)
        self.assertEqual(contract["contract"], "architect-to-backend")

    def test_load_nonexistent(self):
        contract = load_contract("/nonexistent/file.yaml")
        self.assertIsNone(contract)


class TestFindContract(unittest.TestCase):
    def test_find_existing(self):
        contract = find_contract(CONTRACTS_DIR, "architect", "backend")
        self.assertIsNotNone(contract)
        self.assertEqual(contract["contract"], "architect-to-backend")

    def test_find_nonexistent(self):
        contract = find_contract(CONTRACTS_DIR, "devops", "researcher")
        self.assertIsNone(contract)


class TestListContracts(unittest.TestCase):
    def test_list_all(self):
        contracts = list_contracts(CONTRACTS_DIR)
        self.assertGreaterEqual(len(contracts), 6)
        # Check structure
        for from_agent, to_agent, contract in contracts:
            self.assertIsInstance(from_agent, str)
            self.assertIsInstance(to_agent, str)
            self.assertIsInstance(contract, dict)

    def test_list_nonexistent_dir(self):
        contracts = list_contracts("/nonexistent/dir")
        self.assertEqual(contracts, [])


class TestGetContractsForAgent(unittest.TestCase):
    def test_backend_receives_from_architect(self):
        incoming = get_contracts_for_agent(CONTRACTS_DIR, "backend")
        from_agents = [f for f, _ in incoming]
        self.assertIn("architect", from_agents)

    def test_no_contracts_for_researcher(self):
        incoming = get_contracts_for_agent(CONTRACTS_DIR, "researcher")
        self.assertEqual(len(incoming), 0)


class TestValidateHandoff(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.kb_dir = os.path.join(self.tmpdir.name, "knowledge")
        os.makedirs(self.kb_dir)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_all_satisfied(self):
        """Validation passes when KB files have content."""
        contract = {
            "validation": [
                {"check": "kb_file_modified", "file": "architecture.md",
                 "message": "Update architecture.md"},
            ],
            "required_sections": [
                {"name": "API Endpoints", "format": "table"},
            ],
        }
        # Create KB file with content
        with open(os.path.join(self.kb_dir, "architecture.md"), "w") as f:
            f.write("# Architecture\n\n## API Endpoints\nGET /api/users\nPOST /api/auth\n\nReal content here.\n")

        result = validate_handoff(contract, self.kb_dir)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["warnings"]), 0)

    def test_missing_kb_file(self):
        """Warning when required KB file doesn't exist."""
        contract = {
            "validation": [
                {"check": "kb_file_modified", "file": "api-contracts.md",
                 "message": "Define API contracts"},
            ],
            "required_sections": [],
        }
        result = validate_handoff(contract, self.kb_dir)
        self.assertFalse(result["passed"])
        self.assertGreater(len(result["warnings"]), 0)
        self.assertIn("Missing", result["warnings"][0])

    def test_template_only_file(self):
        """Warning when KB file only has template content."""
        contract = {
            "validation": [
                {"check": "kb_file_modified", "file": "business-rules.md",
                 "message": "Define business rules"},
            ],
            "required_sections": [],
        }
        with open(os.path.join(self.kb_dir, "business-rules.md"), "w") as f:
            f.write("# Business Rules\n\n<!-- Template -->\n")

        result = validate_handoff(contract, self.kb_dir)
        self.assertFalse(result["passed"])
        self.assertIn("Template only", result["warnings"][0])

    def test_missing_section(self):
        """Warning when required section heading not found in KB."""
        contract = {
            "validation": [],
            "required_sections": [
                {"name": "Data Models", "format": "entity definitions"},
            ],
        }
        with open(os.path.join(self.kb_dir, "architecture.md"), "w") as f:
            f.write("# Architecture\n\n## Overview\nSome content.\n")

        result = validate_handoff(contract, self.kb_dir)
        self.assertFalse(result["passed"])
        self.assertIn("Missing section", result["warnings"][0])
        self.assertIn("Data Models", result["warnings"][0])

    def test_none_contract(self):
        """Passes when no contract provided."""
        result = validate_handoff(None, self.kb_dir)
        self.assertTrue(result["passed"])

    def test_advisory_mode(self):
        """All issues are warnings, not errors (advisory mode)."""
        contract = {
            "validation": [
                {"check": "kb_file_modified", "file": "missing.md", "message": "Missing"},
            ],
            "required_sections": [
                {"name": "Nonexistent Section"},
            ],
        }
        result = validate_handoff(contract, self.kb_dir)
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["errors"]), 0)
        self.assertGreater(len(result["warnings"]), 0)


class TestActualContracts(unittest.TestCase):
    """Test that all shipped contract files are valid and parseable."""

    def test_all_contracts_parseable(self):
        contracts = list_contracts(CONTRACTS_DIR)
        self.assertGreaterEqual(len(contracts), 6)
        for from_agent, to_agent, contract in contracts:
            self.assertIn("contract", contract, f"Missing 'contract' key in {from_agent}-to-{to_agent}")
            self.assertIn("version", contract, f"Missing 'version' key in {from_agent}-to-{to_agent}")

    def test_architect_to_backend_has_required_sections(self):
        contract = find_contract(CONTRACTS_DIR, "architect", "backend")
        self.assertIsNotNone(contract)
        sections = contract.get("required_sections", [])
        names = [s.get("name", "") for s in sections]
        self.assertIn("API Endpoints", names)
        self.assertIn("Data Models", names)

    def test_architect_to_frontend_has_required_sections(self):
        contract = find_contract(CONTRACTS_DIR, "architect", "frontend")
        self.assertIsNotNone(contract)
        sections = contract.get("required_sections", [])
        names = [s.get("name", "") for s in sections]
        self.assertIn("Component Hierarchy", names)
        self.assertIn("State Management", names)


if __name__ == "__main__":
    unittest.main()


class TestHandoffScopedToWorkflow(unittest.TestCase):
    """During an active workflow, sections from other features must not count."""

    CONTRACT = {
        "required_sections": [{"name": "Test Strategy"}],
        "validation": [{"check": "kb_file_modified", "file": "api-contracts.md",
                        "message": "update api-contracts"}],
    }

    def _state(self, created_at="2000-01-01T00:00:00Z"):
        return {"status": "in_progress", "created_at": created_at,
                "log_file": "log-new.md", "spec_file": "spec-new.md"}

    def test_section_from_old_feature_does_not_satisfy(self):
        from contracts import validate_handoff
        with tempfile.TemporaryDirectory() as kb:
            with open(os.path.join(kb, "log-old.md"), "w") as f:
                f.write("## Handoff\n### Test Strategy\nold\n")
            with open(os.path.join(kb, "log-new.md"), "w") as f:
                f.write("# Feature Log\n")
            result = validate_handoff(self.CONTRACT, kb, state=self._state())
            self.assertTrue(any("Test Strategy" in w for w in result["warnings"]))

    def test_section_in_current_log_satisfies(self):
        from contracts import validate_handoff
        with tempfile.TemporaryDirectory() as kb:
            with open(os.path.join(kb, "log-new.md"), "w") as f:
                f.write("## Handoff: backend -> unit-tester\n### Test Strategy\nx\n")
            result = validate_handoff(self.CONTRACT, kb, state=self._state())
            self.assertFalse(any("Test Strategy" in w for w in result["warnings"]))

    def test_kb_file_not_touched_since_workflow_start(self):
        from contracts import validate_handoff
        with tempfile.TemporaryDirectory() as kb:
            with open(os.path.join(kb, "api-contracts.md"), "w") as f:
                f.write("# API\n\nline one\nline two\nline three\n")
            state = self._state(created_at="2999-01-01T00:00:00Z")
            result = validate_handoff(self.CONTRACT, kb, state=state)
            self.assertTrue(any("Not updated in this workflow" in w
                                for w in result["warnings"]))
