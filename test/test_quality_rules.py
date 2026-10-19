"""Tests for quality_rules.py configurable rule engine."""
import os
import sys
import tempfile
import unittest

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

from quality_rules import (
    get_default_rules,
    load_rules,
    matches_ignore_path,
    check_secrets,
    check_security,
    check_debug_statements,
    check_file_size,
    run_checks,
    generate_default_config,
    _parse_yaml_simple,
    _parse_value,
)

AWS_KEY_LINE = 'aws_key = "AKIA' + 'IOSFODNN7EXAMPLE"'


class TestGetDefaultRules(unittest.TestCase):
    def test_get_default_rules(self):
        rules = get_default_rules()
        self.assertIn("version", rules)
        self.assertIn("rules", rules)
        self.assertIn("secrets", rules["rules"])
        self.assertIn("security", rules["rules"])
        self.assertIn("debug_statements", rules["rules"])
        self.assertIn("file_size", rules["rules"])
        self.assertIn("coverage", rules["rules"])
        self.assertIn("dependency_audit", rules["rules"])
        self.assertTrue(rules["rules"]["secrets"]["enabled"])
        self.assertEqual(rules["rules"]["secrets"]["severity"], "error")


class TestLoadRules(unittest.TestCase):
    def test_load_rules_no_file(self):
        """Falls back to defaults when no config file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rules = load_rules(tmpdir)
            defaults = get_default_rules()
            self.assertEqual(rules["version"], defaults["version"])
            self.assertEqual(
                rules["rules"]["secrets"]["enabled"],
                defaults["rules"]["secrets"]["enabled"],
            )

    def test_load_rules_custom(self):
        """Reads custom YAML correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            coregy_dir = os.path.join(tmpdir, ".coregy")
            os.makedirs(coregy_dir)
            config = """version: "2"

rules:
  secrets:
    enabled: false
    severity: warning
  file_size:
    max_kb: 1000
"""
            with open(os.path.join(coregy_dir, "quality-rules.yaml"), "w") as f:
                f.write(config)

            rules = load_rules(tmpdir)
            self.assertEqual(rules["version"], "2")
            self.assertFalse(rules["rules"]["secrets"]["enabled"])
            self.assertEqual(rules["rules"]["secrets"]["severity"], "warning")
            self.assertEqual(rules["rules"]["file_size"]["max_kb"], 1000)
            # Other rules should still have defaults
            self.assertTrue(rules["rules"]["security"]["enabled"])


class TestCheckSecrets(unittest.TestCase):
    def test_check_secrets_api_key(self):
        content = 'const API_KEY = "abcdef1234567890abcdef";\n'
        lines = content.splitlines()
        rules = get_default_rules()
        issues = check_secrets(content, lines, rules)
        self.assertTrue(len(issues) > 0)
        self.assertTrue(any("API key" in i["message"] for i in issues))
        self.assertEqual(issues[0]["severity"], "error")

    def test_check_secrets_custom_pattern(self):
        """Detects custom patterns (e.g. STRIPE_)."""
        content = 'const key = "STRIPE_SECRET_abc123";\n'
        lines = content.splitlines()
        rules = get_default_rules()
        rules["rules"]["secrets"]["custom_patterns"] = [
            {"pattern": "STRIPE_SECRET", "message": "Stripe secret key detected"},
        ]
        issues = check_secrets(content, lines, rules)
        self.assertTrue(any("Stripe" in i["message"] for i in issues))

    def test_check_secrets_disabled(self):
        """No issues when secrets rule disabled."""
        content = 'const API_KEY = "abcdef1234567890abcdef";\n'
        lines = content.splitlines()
        rules = get_default_rules()
        rules["rules"]["secrets"]["enabled"] = False
        issues = check_secrets(content, lines, rules)
        self.assertEqual(issues, [])


class TestCheckSecurity(unittest.TestCase):
    def test_check_security_eval(self):
        content = 'const result = eval(userInput);\n'
        lines = content.splitlines()
        rules = get_default_rules()
        issues = check_security(content, lines, "handler.js", rules)
        self.assertTrue(len(issues) > 0)
        self.assertTrue(any("eval" in i["message"] for i in issues))

    def test_check_security_skip_test_file(self):
        """Skips test files based on ignore_paths."""
        content = 'const result = eval(userInput);\n'
        lines = content.splitlines()
        rules = get_default_rules()
        issues = check_security(content, lines, "handler.test.js", rules)
        self.assertEqual(issues, [])

    def test_check_security_skip_test_directory(self):
        """Skips files in test/ directory."""
        content = 'const result = eval(userInput);\n'
        lines = content.splitlines()
        rules = get_default_rules()
        issues = check_security(content, lines, "test/handler.js", rules)
        self.assertEqual(issues, [])

    def test_check_security_disabled(self):
        """No issues when disabled."""
        content = 'const result = eval(userInput);\n'
        lines = content.splitlines()
        rules = get_default_rules()
        rules["rules"]["security"]["enabled"] = False
        issues = check_security(content, lines, "handler.js", rules)
        self.assertEqual(issues, [])


class TestCheckDebugStatements(unittest.TestCase):
    def test_check_debug_console_log(self):
        content = 'console.log("debug");\nconst x = 1;\n'
        lines = content.splitlines()
        rules = get_default_rules()
        issues = check_debug_statements(content, lines, "app.js", rules)
        self.assertTrue(len(issues) > 0)
        self.assertTrue(any("console.log" in i["message"] for i in issues))
        self.assertEqual(issues[0]["severity"], "warning")

    def test_check_debug_print(self):
        """Detects breakpoint() in Python."""
        content = 'x = 1\nbreakpoint()\ny = 2\n'
        lines = content.splitlines()
        rules = get_default_rules()
        issues = check_debug_statements(content, lines, "main.py", rules)
        self.assertTrue(len(issues) > 0)
        self.assertTrue(any("breakpoint()" in i["message"] for i in issues))

    def test_check_debug_disabled(self):
        """No issues when disabled."""
        content = 'console.log("debug");\n'
        lines = content.splitlines()
        rules = get_default_rules()
        rules["rules"]["debug_statements"]["enabled"] = False
        issues = check_debug_statements(content, lines, "app.js", rules)
        self.assertEqual(issues, [])

    def test_check_debug_unknown_extension(self):
        """No issues for files with unknown extension."""
        content = 'console.log("debug");\n'
        lines = content.splitlines()
        rules = get_default_rules()
        issues = check_debug_statements(content, lines, "file.txt", rules)
        self.assertEqual(issues, [])


class TestCheckFileSize(unittest.TestCase):
    def test_check_file_size_ok(self):
        """Passes for small files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "small.txt")
            with open(fpath, "w") as f:
                f.write("hello world\n")
            rules = get_default_rules()
            issues = check_file_size(fpath, rules)
            self.assertEqual(issues, [])

    def test_check_file_size_exceeded(self):
        """Fails for large files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "big.txt")
            with open(fpath, "w") as f:
                f.write("x" * (600 * 1024))
            rules = get_default_rules()
            issues = check_file_size(fpath, rules)
            self.assertTrue(len(issues) > 0)
            self.assertIn("too large", issues[0]["message"].lower())

    def test_check_file_size_custom_limit(self):
        """Uses custom max_kb."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "medium.txt")
            with open(fpath, "w") as f:
                f.write("x" * (50 * 1024))  # 50KB file
            rules = get_default_rules()
            rules["rules"]["file_size"]["max_kb"] = 10  # 10KB limit
            issues = check_file_size(fpath, rules)
            self.assertTrue(len(issues) > 0)


class TestRunChecks(unittest.TestCase):
    def test_run_checks_clean_file(self):
        """No issues for a clean file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "clean.ts")
            with open(fpath, "w") as f:
                f.write("const x = 42;\nexport default x;\n")
            result = run_checks(tmpdir, "clean.ts", "const x = 42;\nexport default x;\n")
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["warnings"], [])

    def test_run_checks_mixed_severity(self):
        """Separates errors and warnings correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a JS file with both a secret (error) and debug statement (warning)
            content = 'const API_KEY = "abcdef1234567890abcdef";\nconsole.log("debug");\n'
            fpath = os.path.join(tmpdir, "bad.js")
            with open(fpath, "w") as f:
                f.write(content)
            result = run_checks(tmpdir, "bad.js", content)
            self.assertTrue(len(result["errors"]) > 0, "Should have errors for API key")
            self.assertTrue(len(result["warnings"]) > 0, "Should have warnings for console.log")


class TestSeverityRouting(unittest.TestCase):
    def test_severity_error_vs_warning(self):
        """Errors block, warnings don't — verify routing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Only debug statements (warning severity by default)
            content = 'console.log("test");\n'
            fpath = os.path.join(tmpdir, "debug.js")
            with open(fpath, "w") as f:
                f.write(content)
            result = run_checks(tmpdir, "debug.js", content)
            self.assertEqual(result["errors"], [])
            self.assertTrue(len(result["warnings"]) > 0)

            # Only secrets (error severity by default)
            content2 = 'const API_KEY = "abcdef1234567890abcdef";\n'
            fpath2 = os.path.join(tmpdir, "secret.ts")
            with open(fpath2, "w") as f:
                f.write(content2)
            result2 = run_checks(tmpdir, "secret.ts", content2)
            self.assertTrue(len(result2["errors"]) > 0)


class TestGenerateDefaultConfig(unittest.TestCase):
    def test_generate_default_config(self):
        """Returns valid YAML-like content."""
        config = generate_default_config()
        self.assertIn("version", config)
        self.assertIn("rules:", config)
        self.assertIn("secrets:", config)
        self.assertIn("security:", config)
        self.assertIn("debug_statements:", config)
        self.assertIn("file_size:", config)
        self.assertIn("enabled:", config)
        self.assertIn("severity:", config)


class TestYamlParser(unittest.TestCase):
    def test_yaml_parser_booleans(self):
        """Parses true/false correctly."""
        content = "rules:\n  secrets:\n    enabled: true\n  security:\n    enabled: false\n"
        result = _parse_yaml_simple(content)
        self.assertTrue(result["rules"]["secrets"]["enabled"])
        self.assertFalse(result["rules"]["security"]["enabled"])

    def test_yaml_parser_nested(self):
        """Parses nested dicts."""
        content = "rules:\n  file_size:\n    max_kb: 1000\n    severity: error\n"
        result = _parse_yaml_simple(content)
        self.assertEqual(result["rules"]["file_size"]["max_kb"], 1000)
        self.assertEqual(result["rules"]["file_size"]["severity"], "error")

    def test_yaml_parser_comments_and_empty_lines(self):
        """Ignores comments and empty lines."""
        content = "# comment\nversion: 1\n\n# another comment\nrules:\n  secrets:\n    enabled: true\n"
        result = _parse_yaml_simple(content)
        self.assertEqual(result["version"], 1)
        self.assertTrue(result["rules"]["secrets"]["enabled"])

    def test_parse_value_types(self):
        """Parses various value types correctly."""
        self.assertTrue(_parse_value("true"))
        self.assertFalse(_parse_value("false"))
        self.assertEqual(_parse_value("42"), 42)
        self.assertEqual(_parse_value('"hello"'), "hello")
        self.assertEqual(_parse_value("plain"), "plain")


class TestMatchesIgnorePath(unittest.TestCase):
    """The shared matcher behind secrets.ignore_paths and security.ignore_paths."""

    def test_directory_fragment(self):
        self.assertTrue(matches_ignore_path("test/handler.py", ["test/"]))
        self.assertTrue(matches_ignore_path("a/test/handler.py", ["test/"]))
        self.assertFalse(matches_ignore_path("src/handler.py", ["test/"]))

    def test_glob_matches_basename_only(self):
        self.assertTrue(matches_ignore_path("src/a.test.js", ["*.test.*"]))
        # The glob core must be in the basename, not anywhere in the path
        self.assertFalse(matches_ignore_path("a.test.d/handler.js", ["*.test.*"]))

    def test_plain_substring(self):
        self.assertTrue(
            matches_ignore_path("hooks/quality_gate.py", ["hooks/quality_gate.py"])
        )
        self.assertFalse(matches_ignore_path("hooks/other.py", ["hooks/quality_gate.py"]))

    def test_case_insensitive(self):
        self.assertTrue(matches_ignore_path("TEST/Handler.PY", ["test/"]))

    def test_empty_and_malformed_inputs(self):
        self.assertFalse(matches_ignore_path("src/a.py", []))
        self.assertFalse(matches_ignore_path("src/a.py", ["", "  "]))
        self.assertFalse(matches_ignore_path("", ["test/"]))
        self.assertFalse(matches_ignore_path(None, ["test/"]))
        # Not a list -> never matches, rather than crashing
        self.assertFalse(matches_ignore_path("src/a.py", "test/"))


class TestSecretsIgnorePaths(unittest.TestCase):
    """secrets.ignore_paths lets a project exempt scanner fixtures (opt-in)."""

    def _rules(self, ignore_paths):
        rules = get_default_rules()
        rules["rules"]["secrets"]["ignore_paths"] = ignore_paths
        return rules

    def test_default_is_empty_so_nothing_is_exempt(self):
        """Secrets are never exempted implicitly -- unlike security."""
        self.assertEqual(get_default_rules()["rules"]["secrets"]["ignore_paths"], [])

    def test_test_files_are_not_exempt_by_default(self):
        """A secret in test/ is still an error unless explicitly opted out."""
        lines = [AWS_KEY_LINE]
        issues = check_secrets("\n".join(lines), lines, get_default_rules(),
                               "test/test_quality_gate.py")
        self.assertTrue(any("AWS" in i["message"] for i in issues))

    def test_ignored_path_is_skipped(self):
        lines = [AWS_KEY_LINE]
        issues = check_secrets("\n".join(lines), lines,
                               self._rules(["test/test_quality_gate.py"]),
                               "test/test_quality_gate.py")
        self.assertEqual(issues, [])

    def test_non_ignored_path_still_flagged(self):
        lines = [AWS_KEY_LINE]
        issues = check_secrets("\n".join(lines), lines,
                               self._rules(["test/test_quality_gate.py"]),
                               "src/config.py")
        self.assertTrue(any("AWS" in i["message"] for i in issues))

    def test_filepath_is_optional_for_backward_compat(self):
        """Pre-existing callers pass 3 args; they must keep working."""
        lines = [AWS_KEY_LINE]
        issues = check_secrets("\n".join(lines), lines, self._rules(["src/"]))
        self.assertTrue(any("AWS" in i["message"] for i in issues))

    def test_run_checks_honours_secrets_ignore_paths(self):
        """End-to-end: the exemption reaches run_checks, not just the checker."""
        with tempfile.TemporaryDirectory() as tmp:
            coregy = os.path.join(tmp, ".coregy")
            os.makedirs(coregy)
            with open(os.path.join(coregy, "quality-rules.yaml"), "w") as f:
                f.write(
                    "version: \"1\"\n"
                    "rules:\n"
                    "  secrets:\n"
                    "    enabled: true\n"
                    "    severity: error\n"
                    "    ignore_paths:\n"
                    "      - \"test/fixtures.py\"\n"
                )
            content = AWS_KEY_LINE + "\n"

            exempt = run_checks(tmp, "test/fixtures.py", content)
            self.assertEqual(exempt["errors"], [])

            scanned = run_checks(tmp, "src/config.py", content)
            self.assertTrue(any("AWS" in e["message"] for e in scanned["errors"]))


if __name__ == "__main__":
    unittest.main()


class TestDefaultConfigRoundTrip(unittest.TestCase):
    """The plugin's own default quality-rules.yaml must parse to what it says.

    Before v0.13.1 the fixed-indent parser flattened `languages` into a list
    (disabling debug checks) and turned custom_patterns into strings.
    """

    def test_default_config_parses_to_default_rules(self):
        from quality_rules import _parse_yaml_simple, generate_default_config
        rules = _parse_yaml_simple(generate_default_config())["rules"]
        self.assertEqual(rules["debug_statements"]["languages"]["javascript"],
                         ["console.log", "debugger"])
        self.assertEqual(rules["secrets"]["custom_patterns"],
                         [{"pattern": "STRIPE_SECRET",
                           "message": "Stripe secret key detected"}])
        self.assertEqual(rules["secrets"]["ignore_paths"], [])

    def test_checks_still_fire_with_default_config_on_disk(self):
        from quality_rules import run_checks, generate_default_config
        with tempfile.TemporaryDirectory() as cwd:
            os.makedirs(os.path.join(cwd, ".coregy"))
            with open(os.path.join(cwd, ".coregy", "quality-rules.yaml"), "w") as f:
                f.write(generate_default_config())
            result = run_checks(cwd, "a.js", 'console.log(1)\nconst k = "STRIPE_SECRET"\n')
            self.assertTrue(any("console.log" in w["message"] for w in result["warnings"]))
            self.assertTrue(any("Stripe" in e["message"] for e in result["errors"]))

    def test_directory_ignore_matches_whole_segments(self):
        from quality_rules import matches_ignore_path
        self.assertTrue(matches_ignore_path("test/a.py", ["test/"]))
        self.assertTrue(matches_ignore_path("src/test/a.py", ["test/"]))
        self.assertFalse(matches_ignore_path("src/attestation/a.js", ["test/"]))
        self.assertFalse(matches_ignore_path("src/latest.js", ["test/"]))
