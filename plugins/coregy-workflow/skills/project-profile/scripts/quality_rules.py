"""
Configurable quality rule engine for Coregy Workflow.

Reads `.coregy/quality-rules.yaml` for custom quality rules with severity levels.
Falls back to built-in defaults when no config file exists.
"""
import os
import re

try:
    from . import mini_yaml
except ImportError:
    import mini_yaml


DEFAULT_RULES = {
    "version": "1",
    "rules": {
        "secrets": {
            "enabled": True,
            "severity": "error",
            "custom_patterns": [],
            # Empty by default on purpose: secrets are the highest-severity
            # check, so nothing is exempted unless a project opts in.
            "ignore_paths": [],
        },
        "security": {
            "enabled": True,
            "severity": "error",
            "ignore_paths": ["test/", "*.test.*", "*.spec.*"],
        },
        "debug_statements": {
            "enabled": True,
            "severity": "warning",
            "languages": {
                "javascript": ["console.log", "debugger"],
                "python": ["breakpoint()"],
                "go": ["fmt.Println"],
            },
        },
        "file_size": {
            "enabled": True,
            "severity": "error",
            "max_kb": 500,
        },
        "coverage": {
            "enabled": False,
            "min_percentage": 80,
            "command": "",
        },
        "dependency_audit": {
            "enabled": False,
            "severity": "warning",
            "command": "",
            "fail_on": "high",
        },
    },
}

# Built-in secret patterns (always active when secrets rule is enabled)
BUILTIN_SECRET_PATTERNS = [
    (r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\'][A-Za-z0-9]{16,}["\']', "Possible hardcoded API key"),
    (r'(?i)(secret|token|password|passwd|pwd)\s*[:=]\s*["\'][^"\']{8,}["\']', "Possible hardcoded secret/password"),
    (r'(?i)-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', "Private key detected"),
    (r'AKIA[0-9A-Z]{16}', "AWS access key detected"),
    (r'(?i)sk-[a-zA-Z0-9]{20,}', "Possible API secret key"),
]

# Built-in security anti-patterns
BUILTIN_SECURITY_PATTERNS = [
    (r'\beval\s*\(', "eval() usage — potential code injection"),
    (r'(?i)innerHTML\s*=', "innerHTML assignment — potential XSS"),
    (r'(?i)document\.write\s*\(', "document.write() — potential XSS"),
    (r'(?i)exec\s*\(\s*["\']', "exec() with string — potential injection"),
]


def _parse_yaml_simple(content):
    """Parse quality-rules.yaml (stdlib only). Returns a dict."""
    parsed = mini_yaml.loads(content)
    return parsed if isinstance(parsed, dict) else {}


def _parse_value(val):
    """Parse a YAML scalar value."""
    if not val:
        return ""
    # Strip quotes
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    low = val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    # Try int
    try:
        return int(val)
    except ValueError:
        pass
    # Try float
    try:
        return float(val)
    except ValueError:
        pass
    return val


def get_default_rules():
    """Returns default rule config."""
    import copy
    return copy.deepcopy(DEFAULT_RULES)


def load_rules(cwd):
    """Read .coregy/quality-rules.yaml, return parsed rules.

    Falls back to DEFAULT_RULES if file doesn't exist.
    """
    import copy
    rules_path = os.path.join(cwd, ".coregy", "quality-rules.yaml")
    if not os.path.isfile(rules_path):
        return copy.deepcopy(DEFAULT_RULES)

    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            content = f.read()
        parsed = _parse_yaml_simple(content)
        # Merge parsed into defaults so missing keys get defaults
        defaults = copy.deepcopy(DEFAULT_RULES)
        if "version" in parsed:
            defaults["version"] = str(parsed["version"])
        if "rules" in parsed and isinstance(parsed["rules"], dict):
            for rule_name, rule_config in parsed["rules"].items():
                if rule_name in defaults["rules"] and isinstance(rule_config, dict):
                    defaults["rules"][rule_name].update(rule_config)
                else:
                    defaults["rules"][rule_name] = rule_config
        return defaults
    except (OSError, UnicodeDecodeError):
        return copy.deepcopy(DEFAULT_RULES)


def matches_ignore_path(filepath, ignore_paths):
    """Check whether filepath matches any entry in an ignore_paths list.

    Supported entry forms:
      - "test/"      directory fragment, matched anywhere in the path
      - "*.test.*"   simple glob, matched against the basename
      - "src/x.py"   plain substring, matched anywhere in the path
    """
    if not filepath or not isinstance(ignore_paths, list):
        return False

    lowered = filepath.lower()
    basename = os.path.basename(lowered)

    for pattern in ignore_paths:
        pattern = str(pattern).lower()
        if not pattern:
            continue
        if pattern.endswith("/"):
            # whole path segment(s) only: "test/" matches test/x.py and
            # src/test/x.py, never src/attestation/x.py or latest.js
            if ("/" + lowered).find("/" + pattern) != -1:
                return True
        elif "*" in pattern:
            # Simple glob: *.test.* -> check if ".test." is in filename
            if pattern.replace("*", "") in basename:
                return True
        else:
            if pattern in lowered:
                return True

    return False


def check_secrets(content, lines, rules, filepath=None):
    """Check for hardcoded secrets using both built-in and custom patterns.

    `filepath` is optional for backward compatibility. When given, files
    matching `secrets.ignore_paths` are skipped. That list defaults to empty
    — unlike `security.ignore_paths`, secrets are never exempted implicitly,
    so a project must opt a path out explicitly in .coregy/quality-rules.yaml.

    Returns list of {line, severity, message}.
    """
    secrets_rules = rules.get("rules", {}).get("secrets", {})
    if not secrets_rules.get("enabled", True):
        return []

    if filepath and matches_ignore_path(filepath, secrets_rules.get("ignore_paths", [])):
        return []

    severity = secrets_rules.get("severity", "error")
    issues = []

    # Built-in patterns
    for pattern, message in BUILTIN_SECRET_PATTERNS:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line):
                issues.append({"line": i, "severity": severity, "message": message})
                break  # One issue per pattern per file

    # Custom patterns
    custom = secrets_rules.get("custom_patterns", [])
    if isinstance(custom, list):
        for entry in custom:
            if isinstance(entry, dict):
                pat = entry.get("pattern", "")
                msg = entry.get("message", "Custom secret pattern match")
                if pat:
                    try:
                        compiled = re.compile(pat)
                        for i, line in enumerate(lines, 1):
                            if compiled.search(line):
                                issues.append({"line": i, "severity": severity, "message": msg})
                                break
                    except re.error:
                        pass

    return issues


def check_security(content, lines, filepath, rules):
    """Check security anti-patterns (eval, innerHTML, etc.).

    Skip test files based on rules config.
    Returns list of {line, severity, message}.
    """
    security_rules = rules.get("rules", {}).get("security", {})
    if not security_rules.get("enabled", True):
        return []

    # Check ignore paths
    ignore_paths = security_rules.get("ignore_paths", ["test/", "*.test.*", "*.spec.*"])
    if matches_ignore_path(filepath, ignore_paths):
        return []

    severity = security_rules.get("severity", "error")
    issues = []

    for pattern, message in BUILTIN_SECURITY_PATTERNS:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line):
                issues.append({"line": i, "severity": severity, "message": message})
                break

    return issues


def check_debug_statements(content, lines, filepath, rules):
    """Check for debug leftovers (console.log, print, debugger, etc.).

    Language-specific patterns from rules config.
    Returns list of {line, severity, message}.
    """
    debug_rules = rules.get("rules", {}).get("debug_statements", {})
    if not debug_rules.get("enabled", True):
        return []

    severity = debug_rules.get("severity", "warning")
    languages = debug_rules.get("languages", {})
    if not isinstance(languages, dict):
        return []

    # Determine language from file extension
    ext = os.path.splitext(filepath)[1].lower()
    ext_to_lang = {
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "javascript",
        ".tsx": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".py": "python",
        ".go": "go",
    }
    lang = ext_to_lang.get(ext, "")
    if not lang:
        return []

    patterns = languages.get(lang, [])
    if not isinstance(patterns, list):
        return []

    issues = []
    for pat in patterns:
        pat_str = str(pat)
        for i, line in enumerate(lines, 1):
            if pat_str in line:
                issues.append({
                    "line": i,
                    "severity": severity,
                    "message": f"Debug statement: {pat_str}",
                })
                break  # One issue per pattern per file

    return issues


def check_file_size(filepath, rules):
    """Check file size against configurable limit.

    Returns list of {line, severity, message}.
    """
    size_rules = rules.get("rules", {}).get("file_size", {})
    if not size_rules.get("enabled", True):
        return []

    max_kb = size_rules.get("max_kb", 500)
    if not isinstance(max_kb, (int, float)):
        try:
            max_kb = int(max_kb)
        except (ValueError, TypeError):
            max_kb = 500

    max_bytes = int(max_kb) * 1024
    severity = size_rules.get("severity", "error")

    try:
        size = os.path.getsize(filepath)
        if size > max_bytes:
            return [{
                "line": 0,
                "severity": severity,
                "message": f"File too large ({size // 1024}KB > {max_kb}KB)",
            }]
    except OSError:
        pass

    return []


def run_checks(cwd, filepath, content):
    """Run all enabled checks against a file.

    Returns {errors: [...], warnings: [...]}.
    errors = severity "error" issues
    warnings = severity "warning" issues
    """
    rules = load_rules(cwd)
    full_path = os.path.join(cwd, filepath) if not os.path.isabs(filepath) else filepath

    errors = []
    warnings = []

    # File size check (uses full path)
    for issue in check_file_size(full_path, rules):
        _route_issue(issue, filepath, errors, warnings)

    # If file is too large, skip content checks
    if errors and any("too large" in e.get("message", "").lower() for e in errors):
        return {"errors": errors, "warnings": warnings}

    lines = content.splitlines() if content else []

    # Secrets
    for issue in check_secrets(content, lines, rules, filepath):
        _route_issue(issue, filepath, errors, warnings)

    # Security
    for issue in check_security(content, lines, filepath, rules):
        _route_issue(issue, filepath, errors, warnings)

    # Debug statements
    for issue in check_debug_statements(content, lines, filepath, rules):
        _route_issue(issue, filepath, errors, warnings)

    return {"errors": errors, "warnings": warnings}


def _route_issue(issue, filepath, errors, warnings):
    """Route an issue to errors or warnings based on severity."""
    entry = {
        "file": filepath,
        "line": issue.get("line", 0),
        "message": issue.get("message", ""),
    }
    if issue.get("severity") == "error":
        errors.append(entry)
    else:
        warnings.append(entry)


def generate_default_config():
    """Return default quality-rules.yaml content as string.

    Used by /init to create a starter config.
    """
    return """# Coregy Workflow Quality Rules
# Customize quality gate behavior for your project.
# See: https://github.com/hodynguyen/coregy-workflow

version: "1"

rules:
  secrets:
    enabled: true
    severity: error
    custom_patterns:
      - pattern: "STRIPE_SECRET"
        message: "Stripe secret key detected"
    # Empty by default -- secrets are never exempted implicitly. Add a path
    # only when a file must legitimately contain secret-shaped strings, such
    # as the fixtures of a test that exercises the scanner itself.
    ignore_paths: []

  security:
    enabled: true
    severity: error
    ignore_paths:
      - "test/"
      - "*.test.*"
      - "*.spec.*"

  debug_statements:
    enabled: true
    severity: warning
    languages:
      javascript:
        - "console.log"
        - "debugger"
      python:
        - "breakpoint()"
      go:
        - "fmt.Println"

  file_size:
    enabled: true
    severity: error
    max_kb: 500

  # coverage and dependency_audit are reserved: the gate does not run them
  # yet, so enabling them has no effect.
  coverage:
    enabled: false
    min_percentage: 80
    command: ""

  dependency_audit:
    enabled: false
    severity: warning
    command: ""
    fail_on: high
"""
