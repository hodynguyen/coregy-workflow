#!/usr/bin/env python3
"""
Migrate a project from the legacy Hody naming to Coregy.

Before v0.14.0 the plugin was called `hody-workflow` and kept its data in
`.hody/`. This script moves a project over:

  1. `.hody/` -> `.coregy/` (a plain rename, so tracker.db and everything
     else comes along untouched)
  2. path references inside `.coregy/` text files (`.hody/`,
     `/hody-workflow:`, `hody-workflow@hody`) are rewritten
  3. `.hody` entries in the project's `.gitignore` are rewritten
  4. `enabledPlugins["hody-workflow@hody"]` in `.claude/settings*.json`
     becomes `coregy-workflow@coregy`

It never deletes anything and refuses to run when both `.hody/` and
`.coregy/` exist, since merging two data dirs is a decision for the user.
Legacy `HODY_*` env vars keep working (they are read as a fallback), so they
are only reported, not changed.

Usage:
  migrate.py check [--cwd <project>] [--json]   # read-only plan
  migrate.py run   [--cwd <project>] [--json]   # apply it
"""
import argparse
import json
import os
import re
import sys

LEGACY_DIR = ".hody"
NEW_DIR = ".coregy"
LEGACY_PLUGIN_KEY = "hody-workflow@hody"
NEW_PLUGIN_KEY = "coregy-workflow@coregy"
TEXT_EXTENSIONS = (".md", ".json", ".yaml", ".yml", ".txt")
SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json")
LEGACY_ENV_VARS = ("HODY_USER", "HODY_AUTO_TRACK", "HODY_SKIP_QUALITY_GATE",
                   "HODY_SKIP_REFRESH", "HODY_MCP_MODE")

# Only path-like tokens are rewritten: free text in the KB that merely
# mentions "hody" is the user's content, not ours to change.
_CONTENT_REWRITES = (
    (re.compile(r"(?<![\w-])\.hody(?=/|\b)"), NEW_DIR),
    (re.compile(r"/hody-workflow:"), "/coregy-workflow:"),
    (re.compile(re.escape(LEGACY_PLUGIN_KEY)), NEW_PLUGIN_KEY),
)
_GITIGNORE_RE = re.compile(r"(^|/)\.hody(?=/|$|\s)", re.MULTILINE)


def _rewrite_text(text):
    for pattern, repl in _CONTENT_REWRITES:
        text = pattern.sub(repl, text)
    return text


def _iter_text_files(root):
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if fname.endswith(TEXT_EXTENSIONS):
                yield os.path.join(dirpath, fname)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _write(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def needs_migration(cwd):
    """True when the project still has a legacy `.hody/` and no `.coregy/`."""
    return (os.path.isdir(os.path.join(cwd, LEGACY_DIR))
            and not os.path.exists(os.path.join(cwd, NEW_DIR)))


def plan(cwd):
    """Describe what `migrate(cwd)` would do, without touching anything.

    Returns a dict: {status, actions: [...], warnings: [...]} where status is
    one of "nothing-to-do", "ready", "conflict".
    """
    legacy = os.path.join(cwd, LEGACY_DIR)
    new = os.path.join(cwd, NEW_DIR)
    actions, warnings = [], []

    if os.path.isdir(legacy) and os.path.exists(new):
        return {
            "status": "conflict",
            "actions": [],
            "warnings": ["both %s/ and %s/ exist -- merge or remove one manually, "
                         "then re-run" % (LEGACY_DIR, NEW_DIR)],
        }

    if os.path.isdir(legacy):
        actions.append({"action": "rename-dir", "from": LEGACY_DIR, "to": NEW_DIR})
        for path in _iter_text_files(legacy):
            content = _read(path)
            if content is not None and _rewrite_text(content) != content:
                rel = os.path.relpath(path, legacy)
                actions.append({"action": "rewrite-file",
                                "file": os.path.join(NEW_DIR, rel)})

    gitignore = os.path.join(cwd, ".gitignore")
    content = _read(gitignore) if os.path.isfile(gitignore) else None
    if content is not None and _GITIGNORE_RE.search(content):
        actions.append({"action": "rewrite-gitignore", "file": ".gitignore"})

    for rel in SETTINGS_FILES:
        data = _load_json(os.path.join(cwd, rel))
        if isinstance(data, dict) and LEGACY_PLUGIN_KEY in (data.get("enabledPlugins") or {}):
            actions.append({"action": "rename-plugin-key", "file": rel,
                            "from": LEGACY_PLUGIN_KEY, "to": NEW_PLUGIN_KEY})

    for var in LEGACY_ENV_VARS:
        if var in os.environ:
            warnings.append("%s is set -- still honored, but rename it to %s"
                            % (var, var.replace("HODY_", "COREGY_", 1)))

    return {"status": "ready" if actions else "nothing-to-do",
            "actions": actions, "warnings": warnings}


def _load_json(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _rename_plugin_key(path):
    data = _load_json(path)
    plugins = data.get("enabledPlugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict) or LEGACY_PLUGIN_KEY not in plugins:
        return False
    # Rebuild in order so the key keeps its position in the file; if the new
    # key is already present, whichever comes first in the file wins.
    renamed = {}
    for key, value in plugins.items():
        renamed.setdefault(NEW_PLUGIN_KEY if key == LEGACY_PLUGIN_KEY else key, value)
    data["enabledPlugins"] = renamed
    _write(path, json.dumps(data, indent=2) + "\n")
    return True


def migrate(cwd):
    """Apply the migration. Returns the plan dict with status "migrated"
    (or the unchanged plan when there is nothing to do / a conflict)."""
    result = plan(cwd)
    if result["status"] != "ready":
        return result

    legacy = os.path.join(cwd, LEGACY_DIR)
    new = os.path.join(cwd, NEW_DIR)
    for action in result["actions"]:
        kind = action["action"]
        if kind == "rename-dir":
            os.rename(legacy, new)
        elif kind == "rewrite-file":
            path = os.path.join(cwd, action["file"])
            content = _read(path)
            if content is not None:
                _write(path, _rewrite_text(content))
        elif kind == "rewrite-gitignore":
            path = os.path.join(cwd, ".gitignore")
            _write(path, _GITIGNORE_RE.sub(r"\1" + NEW_DIR, _read(path)))
        elif kind == "rename-plugin-key":
            _rename_plugin_key(os.path.join(cwd, action["file"]))

    result["status"] = "migrated"
    return result


# ---------------------------------------------------------------------------
# CLI (coregy-cli-v1)
# ---------------------------------------------------------------------------


def _describe(action):
    kind = action["action"]
    if kind == "rename-dir":
        return "rename %s/ -> %s/" % (action["from"], action["to"])
    if kind == "rename-plugin-key":
        return "%s: enabledPlugins %s -> %s" % (action["file"], action["from"], action["to"])
    return "rewrite references in %s" % action["file"]


def _print_human(result):
    status = result["status"]
    headline = {
        "nothing-to-do": "Nothing to migrate -- no legacy Hody data found.",
        "ready": "Migration plan (run `migrate.py run` to apply):",
        "migrated": "Migrated from Hody to Coregy:",
        "conflict": "Cannot migrate:",
    }[status]
    print(headline)
    for action in result["actions"]:
        print("  - " + _describe(action))
    for warning in result["warnings"]:
        print("  ! " + warning)


def main():
    parent = argparse.ArgumentParser(add_help=False)
    # default=SUPPRESS: see kb_archive.py -- keeps a --cwd given before the
    # subcommand from being clobbered by the subparser default.
    parent.add_argument("--cwd", default=argparse.SUPPRESS,
                        help="Project root directory (default: .)")

    parser = argparse.ArgumentParser(
        description="Migrate a project from Hody (.hody/) to Coregy (.coregy/)",
        parents=[parent],
    )
    sub = parser.add_subparsers(dest="command")
    for name, helptext in (("check", "Show what would be migrated (read-only)"),
                           ("run", "Apply the migration")):
        p = sub.add_parser(name, parents=[parent], help=helptext)
        p.add_argument("--json", action="store_true", dest="json_mode")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    cwd = os.path.abspath(getattr(args, "cwd", "."))
    json_mode = getattr(args, "json_mode", False)

    try:
        result = plan(cwd) if args.command == "check" else migrate(cwd)
    except OSError as e:
        if json_mode:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print("Error: %s" % e, file=sys.stderr)
        sys.exit(2)

    ok = result["status"] != "conflict"
    if json_mode:
        print(json.dumps(dict(result, ok=ok), indent=2))
    else:
        _print_human(result)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
