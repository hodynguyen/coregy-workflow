#!/usr/bin/env python3
"""
Project rules loader for Coregy Workflow.

Reads `.coregy/rules.yaml` — user-authored project-specific rules that all
agents respect.  Separate from quality-rules.yaml (automated pre-commit
checks) and conventions in profile.yaml (auto-detected).

Schema (v1):
    version: "1"
    coding:
      naming: [list of rules]
      patterns: [list]
      forbidden: [list]
    architecture:
      boundaries: [list]
      patterns: [list]
      constraints: [list]
    testing:
      requirements: [list]
      coverage: [list]
      patterns: [list]
    workflow:
      preferences: [list]
      agent_behavior: [list]
    custom:
      - "freeform rule"

Usage:
    python3 rules.py init --cwd <dir>
    python3 rules.py validate --cwd <dir>
    python3 rules.py summary --cwd <dir>
    python3 rules.py show --cwd <dir>
"""
import argparse
import json
import os
import re
import sys

RULES_FILE = "rules.yaml"
KNOWN_CATEGORIES = {"coding", "architecture", "testing", "workflow", "custom"}

# ---------------------------------------------------------------------------
# YAML parser (stdlib only)
# ---------------------------------------------------------------------------


def _parse_rules_yaml(content):
    """Parse a rules.yaml string into a dict.

    Handles three levels:
      - Top-level scalars: ``version: "1"``
      - Top-level dicts: ``coding:`` with indented sub-keys
      - Sub-level lists: ``naming:\\n  - "rule"``
      - Top-level list: ``custom:\\n  - "rule"``

    Returns a dict. Raises ValueError on structural problems.
    """
    result = {}
    current_top = None
    current_sub = None
    lines = content.splitlines()

    for i, raw_line in enumerate(lines):
        # Strip trailing whitespace but preserve leading
        line = raw_line.rstrip()

        # Skip empty lines and comments
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(stripped)

        # List item
        if stripped.startswith("- "):
            value = _strip_quotes(stripped[2:].strip())
            if indent >= 4 and current_top and current_sub:
                result.setdefault(current_top, {})
                result[current_top].setdefault(current_sub, [])
                result[current_top][current_sub].append(value)
            elif indent >= 2 and current_top:
                # Direct list under top-level key (e.g., custom:)
                if isinstance(result.get(current_top), list):
                    result[current_top].append(value)
                elif current_top not in result or result[current_top] is None:
                    result[current_top] = [value]
                elif isinstance(result[current_top], dict) and current_sub:
                    result[current_top].setdefault(current_sub, [])
                    result[current_top][current_sub].append(value)
                else:
                    result[current_top] = [value]
            continue

        # Key-value or section header
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()

            if indent == 0:
                # Top-level key
                current_sub = None
                if val:
                    result[key] = _strip_quotes(val)
                    current_top = None
                else:
                    current_top = key
                    if key not in result:
                        result[key] = None
            elif indent >= 2 and current_top:
                # Sub-key under a category
                current_sub = key
                if val:
                    result.setdefault(current_top, {})
                    if not isinstance(result[current_top], dict):
                        result[current_top] = {}
                    result[current_top][current_sub] = _strip_quotes(val)
                else:
                    result.setdefault(current_top, {})
                    if not isinstance(result[current_top], dict):
                        result[current_top] = {}

    # Clean up None placeholders
    for k, v in list(result.items()):
        if v is None:
            result[k] = {}

    return result


def _strip_quotes(s):
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


# ---------------------------------------------------------------------------
# Load / validate / summarize
# ---------------------------------------------------------------------------


def load_rules(cwd):
    """Load .coregy/rules.yaml. Returns parsed dict or None if missing."""
    path = os.path.join(cwd, ".coregy", RULES_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as f:
            content = f.read()
        if not content.strip():
            return None
        return _parse_rules_yaml(content)
    except (OSError, ValueError):
        return None


def validate_rules(parsed):
    """Validate parsed rules structure.

    Returns (valid: bool, errors: list[str]).
    """
    errors = []
    if parsed is None:
        return False, ["Rules file could not be parsed"]

    if not isinstance(parsed, dict):
        return False, ["Rules must be a YAML mapping"]

    version = parsed.get("version")
    if version is None:
        errors.append("Missing 'version' field")
    elif str(version) != "1":
        errors.append("Unsupported version '%s' (expected '1')" % version)

    for key, value in parsed.items():
        if key == "version":
            continue

        if key == "custom":
            if not isinstance(value, list):
                errors.append("'custom' must be a list of strings")
            continue

        if isinstance(value, dict):
            for sub_key, sub_val in value.items():
                if not isinstance(sub_val, list):
                    errors.append(
                        "'%s.%s' must be a list of rules" % (key, sub_key)
                    )
        elif isinstance(value, list):
            pass  # top-level list is OK (treated like custom)
        else:
            errors.append(
                "'%s' must be a mapping of subcategories or a list" % key
            )

    return len(errors) == 0, errors


def summarize_rules(parsed):
    """Generate a one-line summary for hook injection.

    Example: "[Project Rules] coding: 3 naming, 2 forbidden | testing: 2 requirements | 3 custom. Full rules at .coregy/rules.yaml"
    """
    if not parsed or not isinstance(parsed, dict):
        return ""

    parts = []
    for cat in ("coding", "architecture", "testing", "workflow"):
        val = parsed.get(cat)
        if not isinstance(val, dict) or not val:
            continue
        sub_parts = []
        for sub_key, sub_val in val.items():
            if isinstance(sub_val, list) and sub_val:
                sub_parts.append("%d %s" % (len(sub_val), sub_key))
        if sub_parts:
            parts.append("%s: %s" % (cat, ", ".join(sub_parts)))

    custom = parsed.get("custom")
    if isinstance(custom, list) and custom:
        parts.append("%d custom" % len(custom))

    # Include unknown categories
    for key, val in parsed.items():
        if key in ("version", "coding", "architecture", "testing", "workflow", "custom"):
            continue
        if isinstance(val, dict):
            total = sum(len(v) for v in val.values() if isinstance(v, list))
            if total > 0:
                parts.append("%s: %d rules" % (key, total))
        elif isinstance(val, list) and val:
            parts.append("%s: %d rules" % (key, len(val)))

    if not parts:
        return ""

    return "[Project Rules] %s. Full rules at .coregy/rules.yaml" % " | ".join(parts)


def get_rules_for_category(parsed, category):
    """Extract all rules for a category as a flat list of strings."""
    if not parsed or not isinstance(parsed, dict):
        return []
    val = parsed.get(category)
    if isinstance(val, list):
        return list(val)
    if isinstance(val, dict):
        result = []
        for sub_val in val.values():
            if isinstance(sub_val, list):
                result.extend(sub_val)
        return result
    return []


def get_rules_summary(cwd):
    """Convenience function for status/health commands.

    Returns dict with exists, version, categories, total_rules.
    """
    parsed = load_rules(cwd)
    if parsed is None:
        return {"exists": False}

    categories = {}
    total = 0
    for key, val in parsed.items():
        if key == "version":
            continue
        if isinstance(val, dict):
            count = sum(len(v) for v in val.values() if isinstance(v, list))
        elif isinstance(val, list):
            count = len(val)
        else:
            count = 0
        if count > 0:
            categories[key] = count
            total += count

    return {
        "exists": True,
        "version": str(parsed.get("version", "?")),
        "categories": categories,
        "total_rules": total,
    }


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------

_DEFAULT_TEMPLATE = """\
# .coregy/rules.yaml — Project Rules for Coregy Workflow Agents
# User-authored rules that all agents respect during development.
#
# Structure: category → subcategory → list of rule strings.
# Uncomment and customize the rules relevant to your project.
# See: /coregy-workflow:rules for management commands.

version: "1"

# Coding conventions — followed by frontend, backend, code-reviewer agents
# coding:
#   naming:
#     - "Use camelCase for variables and functions"
#     - "Use PascalCase for classes and components"
#   patterns:
#     - "Use repository pattern for database access"
#     - "Use DTOs for API request/response types"
#   forbidden:
#     - "Never use any as a TypeScript type"
#     - "Do not use default exports — use named exports only"

# Architecture constraints — followed by architect, code-reviewer, spec-verifier
# architecture:
#   boundaries:
#     - "Services must not import directly from controllers"
#     - "Frontend components must not call database layers"
#   patterns:
#     - "All API endpoints follow REST conventions"
#   constraints:
#     - "Each module must have an index.ts barrel file"

# Testing rules — followed by unit-tester, integration-tester agents
# testing:
#   requirements:
#     - "Every new API endpoint must have integration tests"
#     - "Business logic functions require unit tests with edge cases"
#   coverage:
#     - "Minimum 80% line coverage for src/ directory"
#   patterns:
#     - "Use factory functions for test data, not raw objects"

# Workflow preferences — affect agent behavior and process
# workflow:
#   preferences:
#     - "Always run code-reviewer before merging"
#   agent_behavior:
#     - "Keep code changes under 300 lines per commit"

# Custom rules — freeform, applied to all agents
# custom:
#   - "All user-facing strings must support i18n"
#   - "Third-party dependencies require team lead approval"
"""


def generate_default_config():
    """Return the template rules.yaml content string."""
    return _DEFAULT_TEMPLATE


def write_default_config(cwd):
    """Write template rules.yaml to .coregy/rules.yaml. Returns the path."""
    coregy_dir = os.path.join(cwd, ".coregy")
    os.makedirs(coregy_dir, exist_ok=True)
    path = os.path.join(coregy_dir, RULES_FILE)
    with open(path, "w") as f:
        f.write(_DEFAULT_TEMPLATE)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parent = argparse.ArgumentParser(add_help=False)
    # default=SUPPRESS is load-bearing: --cwd lives on both the top-level
    # parser and every subparser (parents=[parent]). With a concrete
    # default the subparser re-applies it into its own namespace and
    # silently clobbers a --cwd given *before* the subcommand, so the
    # script would quietly operate on the process cwd instead.
    parent.add_argument("--cwd", default=argparse.SUPPRESS,
                        help="Project root directory (default: .)")

    parser = argparse.ArgumentParser(
        description="Coregy Workflow project rules", parents=[parent]
    )
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Create template rules.yaml", parents=[parent])
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite an existing rules.yaml (destroys its rules)")
    sub.add_parser("validate", help="Validate existing rules.yaml", parents=[parent])
    sub.add_parser("summary", help="Print condensed summary", parents=[parent])
    sub.add_parser("show", help="Pretty-print all rules", parents=[parent])

    args = parser.parse_args()
    # getattr, not args.cwd: the shared --cwd action defaults to
    # SUPPRESS so a value given before the subcommand survives.
    cwd = os.path.abspath(getattr(args, "cwd", "."))

    if args.command == "init":
        path = os.path.join(cwd, ".coregy", RULES_FILE)
        if os.path.isfile(path) and not args.force:
            # /init runs this on every re-init; overwriting would silently
            # wipe the user's rules.
            print("%s already exists -- left untouched (use --force to "
                  "overwrite)" % path, file=sys.stderr)
            sys.exit(1)
        write_default_config(cwd)
        print("Created %s" % os.path.join(cwd, ".coregy", RULES_FILE))

    elif args.command == "validate":
        parsed = load_rules(cwd)
        if parsed is None:
            print(json.dumps({"valid": False, "errors": ["File not found or empty"]}))
            sys.exit(1)
        valid, errors = validate_rules(parsed)
        print(json.dumps({"valid": valid, "errors": errors}))
        if not valid:
            sys.exit(1)

    elif args.command == "summary":
        parsed = load_rules(cwd)
        if parsed is None:
            print("")
            return
        print(summarize_rules(parsed))

    elif args.command == "show":
        parsed = load_rules(cwd)
        if parsed is None:
            print("No rules file found at %s" % os.path.join(cwd, ".coregy", RULES_FILE))
            sys.exit(0)
        print(json.dumps(parsed, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
