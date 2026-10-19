"""
Register / unregister MCP servers where Claude Code actually reads them.

Claude Code loads MCP servers from:
  - local scope   -- private to this user + project (~/.claude.json), written
                     via `claude mcp add-json --scope local`
  - project scope -- `.mcp.json` at the project root (meant to be committed)
It does NOT read an `mcpServers` key from `.claude/settings.json`, which is
where hody wrote them before v0.13.1 -- so /connect and Graphify never loaded.

Servers are registered in local scope through the `claude` CLI when it is
available: they carry API tokens and machine-specific interpreter paths, so
they must not land in a file that gets committed. Without the CLI (or with
HODY_MCP_MODE=file, used by the tests) the server goes to `.mcp.json`, and a
`.mcp.json` holding secrets is added to .gitignore.

Every write also drops the stale entry from `.claude/settings.json`.
"""
import json
import os
import shutil
import subprocess

LEGACY_SETTINGS = os.path.join(".claude", "settings.json")
PROJECT_FILE = ".mcp.json"


def _use_cli():
    if os.environ.get("HODY_MCP_MODE") == "file":
        return False
    return shutil.which("claude") is not None


def _read_json(path):
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _drop_legacy(cwd, name):
    """Remove a server hody used to write into .claude/settings.json."""
    path = os.path.join(cwd, LEGACY_SETTINGS)
    settings = _read_json(path)
    servers = settings.get("mcpServers")
    if not isinstance(servers, dict) or name not in servers:
        return False
    del servers[name]
    if not servers:
        del settings["mcpServers"]
    _write_json(path, settings)
    return True


def _ensure_gitignored(cwd, entry):
    path = os.path.join(cwd, ".gitignore")
    content = ""
    if os.path.isfile(path):
        with open(path, "r") as f:
            content = f.read()
        if any(line.strip() in (entry, "/" + entry) for line in content.splitlines()):
            return False
    if content and not content.endswith("\n"):
        content += "\n"
    with open(path, "w") as f:
        f.write(content + entry + "\n")
    return True


def _run_claude(args, cwd):
    try:
        result = subprocess.run(
            ["claude"] + args, cwd=cwd, capture_output=True, text=True, timeout=60,
        )
        return result.returncode == 0, (result.stderr or result.stdout).strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)


def register_server(cwd, name, config):
    """Register an MCP server. Returns {"location": ..., "warning": ...}."""
    cwd = os.path.abspath(cwd)
    _drop_legacy(cwd, name)

    if _use_cli():
        _run_claude(["mcp", "remove", name, "--scope", "local"], cwd)  # replace
        ok, err = _run_claude(
            ["mcp", "add-json", name, json.dumps(config), "--scope", "local"], cwd)
        if ok:
            return {"location": "local scope (claude mcp, private to you)",
                    "warning": None}
        fallback_reason = "claude mcp add-json failed (%s)" % err
    else:
        fallback_reason = None

    path = os.path.join(cwd, PROJECT_FILE)
    data = _read_json(path)
    if not isinstance(data.get("mcpServers"), dict):
        data["mcpServers"] = {}
    data["mcpServers"][name] = config
    _write_json(path, data)

    warning = fallback_reason
    if config.get("env") or config.get("headers"):
        if _ensure_gitignored(cwd, PROJECT_FILE):
            note = ".mcp.json contains credentials -- added it to .gitignore"
        else:
            note = ".mcp.json contains credentials -- keep it out of git"
        warning = "%s; %s" % (warning, note) if warning else note
    return {"location": PROJECT_FILE, "warning": warning}


def unregister_server(cwd, name):
    """Remove a server from every place hody may have put it. True if found."""
    cwd = os.path.abspath(cwd)
    removed = _drop_legacy(cwd, name)

    path = os.path.join(cwd, PROJECT_FILE)
    data = _read_json(path)
    servers = data.get("mcpServers")
    if isinstance(servers, dict) and name in servers:
        del servers[name]
        _write_json(path, data)
        removed = True

    if _use_cli() and name in _local_scope_servers(cwd):
        ok, _ = _run_claude(["mcp", "remove", name, "--scope", "local"], cwd)
        removed = removed or ok
    return removed


def _local_scope_servers(cwd):
    """Servers stored in local scope for this project (~/.claude.json)."""
    data = _read_json(os.path.join(os.path.expanduser("~"), ".claude.json"))
    project = (data.get("projects") or {}).get(os.path.abspath(cwd)) or {}
    servers = project.get("mcpServers")
    return servers if isinstance(servers, dict) else {}


def server_location(cwd, name):
    """Where a server is configured: "local", ".mcp.json", "legacy", or None.

    "legacy" means the unread .claude/settings.json entry -- configured by an
    older hody but never loaded by Claude Code.
    """
    cwd = os.path.abspath(cwd)
    if os.environ.get("HODY_MCP_MODE") != "file" and name in _local_scope_servers(cwd):
        return "local"
    project = _read_json(os.path.join(cwd, PROJECT_FILE)).get("mcpServers") or {}
    if name in project:
        return PROJECT_FILE
    legacy = _read_json(os.path.join(cwd, LEGACY_SETTINGS)).get("mcpServers") or {}
    if name in legacy:
        return "legacy"
    return None
