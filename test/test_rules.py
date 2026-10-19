"""Tests for project rules loader (rules.py)."""
import json
import os
import subprocess
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

from rules import (
    _parse_rules_yaml,
    load_rules,
    validate_rules,
    summarize_rules,
    get_rules_for_category,
    get_rules_summary,
    generate_default_config,
    write_default_config,
)

SAMPLE_RULES = """\
version: "1"

coding:
  naming:
    - "Use camelCase for variables"
    - "Use PascalCase for components"
  forbidden:
    - "Never use any as TypeScript type"

architecture:
  boundaries:
    - "Services must not import from controllers"

testing:
  requirements:
    - "Every API endpoint needs integration tests"
  coverage:
    - "Minimum 80% coverage"

workflow:
  preferences:
    - "Always run code-reviewer before merging"

custom:
  - "All strings must support i18n"
  - "Third-party deps need approval"
"""


class TestParseRulesYaml(unittest.TestCase):
    def test_full_parse(self):
        result = _parse_rules_yaml(SAMPLE_RULES)
        self.assertEqual(result["version"], "1")
        self.assertEqual(len(result["coding"]["naming"]), 2)
        self.assertEqual(len(result["coding"]["forbidden"]), 1)
        self.assertEqual(len(result["architecture"]["boundaries"]), 1)
        self.assertEqual(len(result["testing"]["requirements"]), 1)
        self.assertEqual(len(result["testing"]["coverage"]), 1)
        self.assertEqual(len(result["workflow"]["preferences"]), 1)
        self.assertEqual(len(result["custom"]), 2)

    def test_custom_only(self):
        content = 'version: "1"\n\ncustom:\n  - "Rule A"\n  - "Rule B"\n'
        result = _parse_rules_yaml(content)
        self.assertEqual(result["custom"], ["Rule A", "Rule B"])

    def test_empty_content(self):
        result = _parse_rules_yaml("")
        self.assertEqual(result, {})

    def test_comments_and_blank_lines(self):
        content = (
            "# This is a comment\n"
            "version: \"1\"\n"
            "\n"
            "# Another comment\n"
            "custom:\n"
            "  - \"Only rule\"\n"
        )
        result = _parse_rules_yaml(content)
        self.assertEqual(result["version"], "1")
        self.assertEqual(result["custom"], ["Only rule"])

    def test_unknown_category(self):
        content = (
            'version: "1"\n'
            "security:\n"
            "  policies:\n"
            '    - "Encrypt all PII"\n'
        )
        result = _parse_rules_yaml(content)
        self.assertEqual(result["security"]["policies"], ["Encrypt all PII"])

    def test_single_quoted_values(self):
        content = "version: '1'\ncustom:\n  - 'Single quoted rule'\n"
        result = _parse_rules_yaml(content)
        self.assertEqual(result["version"], "1")
        self.assertEqual(result["custom"], ["Single quoted rule"])

    def test_unquoted_values(self):
        content = "version: 1\ncustom:\n  - Unquoted rule text\n"
        result = _parse_rules_yaml(content)
        self.assertEqual(result["version"], "1")
        self.assertEqual(result["custom"], ["Unquoted rule text"])

    def test_empty_category(self):
        content = 'version: "1"\ncoding:\narchitecture:\n'
        result = _parse_rules_yaml(content)
        self.assertEqual(result["coding"], {})
        self.assertEqual(result["architecture"], {})


class TestLoadRules(unittest.TestCase):
    def test_load_valid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            coregy = os.path.join(tmp, ".coregy")
            os.makedirs(coregy)
            with open(os.path.join(coregy, "rules.yaml"), "w") as f:
                f.write(SAMPLE_RULES)
            result = load_rules(tmp)
            self.assertIsNotNone(result)
            self.assertEqual(result["version"], "1")

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_rules(tmp))

    def test_missing_coregy_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_rules(tmp))

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            coregy = os.path.join(tmp, ".coregy")
            os.makedirs(coregy)
            with open(os.path.join(coregy, "rules.yaml"), "w") as f:
                f.write("")
            self.assertIsNone(load_rules(tmp))

    def test_comment_only_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            coregy = os.path.join(tmp, ".coregy")
            os.makedirs(coregy)
            with open(os.path.join(coregy, "rules.yaml"), "w") as f:
                f.write("# Just comments\n# Nothing else\n")
            result = load_rules(tmp)
            # Parsed as empty dict, but not None
            self.assertIsNotNone(result)
            self.assertEqual(result, {})


class TestValidateRules(unittest.TestCase):
    def test_valid_rules(self):
        parsed = _parse_rules_yaml(SAMPLE_RULES)
        valid, errors = validate_rules(parsed)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_missing_version(self):
        parsed = _parse_rules_yaml("coding:\n  naming:\n    - \"Rule\"\n")
        valid, errors = validate_rules(parsed)
        self.assertFalse(valid)
        self.assertTrue(any("version" in e for e in errors))

    def test_wrong_version(self):
        parsed = _parse_rules_yaml('version: "2"\ncustom:\n  - "Rule"\n')
        valid, errors = validate_rules(parsed)
        self.assertFalse(valid)
        self.assertTrue(any("version" in e.lower() for e in errors))

    def test_none_input(self):
        valid, errors = validate_rules(None)
        self.assertFalse(valid)

    def test_unknown_category_passes(self):
        content = 'version: "1"\nsecurity:\n  policies:\n    - "Rule"\n'
        parsed = _parse_rules_yaml(content)
        valid, errors = validate_rules(parsed)
        self.assertTrue(valid)


class TestSummarizeRules(unittest.TestCase):
    def test_full_summary(self):
        parsed = _parse_rules_yaml(SAMPLE_RULES)
        summary = summarize_rules(parsed)
        self.assertIn("[Project Rules]", summary)
        self.assertIn("coding:", summary)
        self.assertIn("2 naming", summary)
        self.assertIn("1 forbidden", summary)
        self.assertIn("2 custom", summary)
        self.assertIn(".coregy/rules.yaml", summary)

    def test_empty_categories_omitted(self):
        content = 'version: "1"\ncoding:\ncustom:\n  - "Only rule"\n'
        parsed = _parse_rules_yaml(content)
        summary = summarize_rules(parsed)
        self.assertNotIn("coding:", summary)
        self.assertIn("1 custom", summary)

    def test_none_input(self):
        self.assertEqual(summarize_rules(None), "")

    def test_no_rules_empty(self):
        parsed = _parse_rules_yaml('version: "1"\n')
        self.assertEqual(summarize_rules(parsed), "")

    def test_unknown_category_included(self):
        content = 'version: "1"\nsecurity:\n  policies:\n    - "Rule A"\n    - "Rule B"\n'
        parsed = _parse_rules_yaml(content)
        summary = summarize_rules(parsed)
        self.assertIn("security: 2 rules", summary)


class TestGetRulesForCategory(unittest.TestCase):
    def test_dict_category(self):
        parsed = _parse_rules_yaml(SAMPLE_RULES)
        rules = get_rules_for_category(parsed, "coding")
        self.assertEqual(len(rules), 3)  # 2 naming + 1 forbidden

    def test_list_category(self):
        parsed = _parse_rules_yaml(SAMPLE_RULES)
        rules = get_rules_for_category(parsed, "custom")
        self.assertEqual(len(rules), 2)

    def test_missing_category(self):
        parsed = _parse_rules_yaml(SAMPLE_RULES)
        rules = get_rules_for_category(parsed, "nonexistent")
        self.assertEqual(rules, [])

    def test_none_input(self):
        self.assertEqual(get_rules_for_category(None, "coding"), [])


class TestGetRulesSummary(unittest.TestCase):
    def test_with_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            coregy = os.path.join(tmp, ".coregy")
            os.makedirs(coregy)
            with open(os.path.join(coregy, "rules.yaml"), "w") as f:
                f.write(SAMPLE_RULES)
            summary = get_rules_summary(tmp)
            self.assertTrue(summary["exists"])
            self.assertEqual(summary["version"], "1")
            self.assertIn("coding", summary["categories"])
            self.assertEqual(summary["categories"]["coding"], 3)
            self.assertEqual(summary["categories"]["custom"], 2)
            self.assertGreater(summary["total_rules"], 0)

    def test_without_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = get_rules_summary(tmp)
            self.assertFalse(summary["exists"])

    def test_total_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            coregy = os.path.join(tmp, ".coregy")
            os.makedirs(coregy)
            with open(os.path.join(coregy, "rules.yaml"), "w") as f:
                f.write(SAMPLE_RULES)
            summary = get_rules_summary(tmp)
            # 2 naming + 1 forbidden + 1 boundary + 1 req + 1 cov + 1 pref + 2 custom = 9
            self.assertEqual(summary["total_rules"], 9)


class TestGenerateDefaultConfig(unittest.TestCase):
    def test_template_is_parseable(self):
        template = generate_default_config()
        # All lines are comments — should parse to empty (or version only)
        result = _parse_rules_yaml(template)
        # Template is all commented out except maybe version
        self.assertIsInstance(result, dict)

    def test_template_contains_all_categories(self):
        template = generate_default_config()
        for cat in ("coding", "architecture", "testing", "workflow", "custom"):
            self.assertIn(cat, template)


class TestWriteDefaultConfig(unittest.TestCase):
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_default_config(tmp)
            self.assertTrue(os.path.isfile(path))
            with open(path) as f:
                content = f.read()
            self.assertIn("version:", content)

    def test_creates_coregy_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_default_config(tmp)
            self.assertTrue(os.path.isdir(os.path.join(tmp, ".coregy")))


class TestCLI(unittest.TestCase):
    SCRIPT = os.path.join(
        os.path.dirname(__file__),
        "..",
        "plugins",
        "coregy-workflow",
        "skills",
        "project-profile",
        "scripts",
        "rules.py",
    )

    def test_init_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, self.SCRIPT, "init", "--cwd", tmp],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0)
            self.assertTrue(
                os.path.isfile(os.path.join(tmp, ".coregy", "rules.yaml"))
            )

    def test_init_never_overwrites_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".coregy", "rules.yaml")
            os.makedirs(os.path.dirname(path))
            with open(path, "w") as f:
                f.write('version: "1"\ncustom:\n  - "keep me"\n')
            result = subprocess.run(
                [sys.executable, self.SCRIPT, "init", "--cwd", tmp],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 1)
            with open(path) as f:
                self.assertIn("keep me", f.read())
            result = subprocess.run(
                [sys.executable, self.SCRIPT, "init", "--force", "--cwd", tmp],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0)
            with open(path) as f:
                self.assertNotIn("keep me", f.read())

    def test_validate_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            coregy = os.path.join(tmp, ".coregy")
            os.makedirs(coregy)
            with open(os.path.join(coregy, "rules.yaml"), "w") as f:
                f.write(SAMPLE_RULES)
            result = subprocess.run(
                [sys.executable, self.SCRIPT, "validate", "--cwd", tmp],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertTrue(data["valid"])

    def test_validate_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, self.SCRIPT, "validate", "--cwd", tmp],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 1)

    def test_summary_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            coregy = os.path.join(tmp, ".coregy")
            os.makedirs(coregy)
            with open(os.path.join(coregy, "rules.yaml"), "w") as f:
                f.write(SAMPLE_RULES)
            result = subprocess.run(
                [sys.executable, self.SCRIPT, "summary", "--cwd", tmp],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("[Project Rules]", result.stdout)


if __name__ == "__main__":
    unittest.main()
