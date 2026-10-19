"""
Configure MCP server entries for third-party integrations (Jira, GitHub,
Linear) in .claude/settings.json without manual JSON editing.

Each integration has a registered spec describing its required fields,
the MCP server command, and how to map fields to env vars. The CLI
accepts those fields as args, validates them, merges the resulting
server where Claude Code reads it (local scope via `claude mcp`, else
.mcp.json -- see mcp_config.py), and flips integrations.<name>: true in
.hody/profile.yaml.

Usage:
  mcp_setup.py jira --api-token X --site Y --email Z
  mcp_setup.py linear --api-key X
  mcp_setup.py github --token X
  mcp_setup.py status
  mcp_setup.py remove jira
  mcp_setup.py fields jira       # describe required fields (for guides)
"""
import argparse
import json
import os
import re
import sys

try:
    from . import mcp_config
except ImportError:
    import mcp_config


# =====================================================================
# Integration specs
# =====================================================================

INTEGRATIONS = {
    # sooperset/mcp-atlassian (PyPI `mcp-atlassian`, run with uvx). The
    # previously configured `@anthropic/mcp-server-atlassian` does not exist.
    "jira": {
        "fields": [
            {
                "name": "api-token",
                "env": "JIRA_API_TOKEN",
                "description": "Atlassian API token",
                "guide": "Create at https://id.atlassian.com/manage-profile/security/api-tokens",
            },
            {
                "name": "site",
                "env": "JIRA_URL",
                "description": "Your Jira site URL",
                "guide": "e.g. https://your-org.atlassian.net (no trailing slash)",
            },
            {
                "name": "email",
                "env": "JIRA_USERNAME",
                "description": "Atlassian account email",
                "guide": "The email you log into Atlassian with",
            },
        ],
        "server": {
            "command": "uvx",
            "args": ["mcp-atlassian"],
        },
    },
    # Linear's official hosted MCP server; an API key is sent as a bearer
    # token. `@modelcontextprotocol/server-linear` does not exist.
    "linear": {
        "fields": [
            {
                "name": "api-key",
                "header": "Authorization",
                "header_format": "Bearer {}",
                "description": "Linear API key",
                "guide": "Create at Linear → Settings → API → Personal API keys",
            },
        ],
        "server": {
            "type": "http",
            "url": "https://mcp.linear.app/mcp",
        },
    },
    # GitHub's official remote MCP server. `@modelcontextprotocol/server-github`
    # is deprecated on npm.
    "github": {
        "fields": [
            {
                "name": "token",
                "header": "Authorization",
                "header_format": "Bearer {}",
                "description": "GitHub Personal Access Token",
                "guide": "Create at https://github.com/settings/tokens (scopes: repo, read:org)",
            },
        ],
        "server": {
            "type": "http",
            "url": "https://api.githubcopilot.com/mcp/",
        },
    },
}


# =====================================================================
# Where servers are written: see mcp_config.py
# =====================================================================

# =====================================================================
# profile.yaml integration flag
# =====================================================================

def update_profile_integration(cwd, name, enabled=True):
    """Flip integrations.<name>: <enabled> in .hody/profile.yaml.

    Mirrors the regex-based approach used by graphify_setup.py to avoid a
    full YAML round-trip.
    """
    path = os.path.join(cwd, ".hody", "profile.yaml")
    if not os.path.isfile(path):
        return False

    with open(path, "r") as f:
        content = f.read()

    target_value = "true" if enabled else "false"
    line_pattern = rf"^(\s*){re.escape(name)}:\s*\S+"

    # Case 1: line already set to target
    if re.search(rf"^\s*{re.escape(name)}:\s*{target_value}\s*$",
                 content, re.MULTILINE):
        return True

    # Case 2: line exists with different value -> rewrite
    new_content, count = re.subn(
        line_pattern,
        rf"\g<1>{name}: {target_value}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if count > 0:
        with open(path, "w") as f:
            f.write(new_content)
        return True

    # Case 3: integrations section exists, missing this key
    if re.search(r"^integrations:\s*$", content, re.MULTILINE):
        new_content = re.sub(
            r"^(integrations:\s*\n)",
            rf"\1  {name}: {target_value}\n",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        with open(path, "w") as f:
            f.write(new_content)
        return True

    # Case 4: no integrations section
    addition = f"\nintegrations:\n  {name}: {target_value}\n"
    with open(path, "a") as f:
        f.write(addition)
    return True


# =====================================================================
# Setup logic
# =====================================================================

def get_spec(name):
    if name not in INTEGRATIONS:
        raise ValueError(
            f"Unknown integration: {name}. "
            f"Choose from {sorted(INTEGRATIONS)}"
        )
    return INTEGRATIONS[name]


def describe_fields(name):
    """Return list of dicts describing required fields for guides/prompts."""
    return list(get_spec(name)["fields"])


def collect_missing(name, provided):
    """Return field specs whose values are missing or empty in `provided`."""
    fields = describe_fields(name)
    missing = []
    for f in fields:
        key = f["name"]
        if not provided.get(key):
            missing.append(f)
    return missing


def build_server_config(name, values):
    """Build the MCP server JSON entry from collected field values."""
    spec = get_spec(name)
    server = {k: (list(v) if isinstance(v, list) else v)
              for k, v in spec["server"].items()}
    env = {}
    headers = {}
    for field in spec["fields"]:
        key = field["name"]
        if key not in values or values[key] in (None, ""):
            raise ValueError(f"Missing required field: --{key}")
        if "header" in field:
            headers[field["header"]] = field.get("header_format", "{}").format(values[key])
        else:
            env[field["env"]] = values[key]
    if env:
        server["env"] = env
    if headers:
        server["headers"] = headers
    return server


def configure(cwd, name, values):
    """Register the integration's MCP server + flip the profile flag."""
    spec = get_spec(name)
    missing = collect_missing(name, values)
    if missing:
        raise ValueError(
            "Missing required fields: "
            + ", ".join(f"--{f['name']}" for f in missing)
        )

    server_config = build_server_config(name, values)
    registered = mcp_config.register_server(cwd, name, server_config)
    profile_updated = update_profile_integration(cwd, name, enabled=True)

    return {
        "integration": name,
        "location": registered["location"],
        "warning": registered["warning"],
        "profile_updated": profile_updated,
        "fields_used": [f["name"] for f in spec["fields"]],
        "restart_required": True,
    }


def remove(cwd, name):
    """Remove the MCP server entry and flip profile flag back to false."""
    get_spec(name)  # validate name
    removed = mcp_config.unregister_server(cwd, name)
    profile_updated = update_profile_integration(cwd, name, enabled=False)
    return {
        "integration": name,
        "removed": removed,
        "profile_updated": profile_updated,
    }


def status(cwd):
    """Return current configuration state for all known integrations."""
    profile_path = os.path.join(cwd, ".hody", "profile.yaml")
    profile_text = ""
    if os.path.isfile(profile_path):
        with open(profile_path, "r") as f:
            profile_text = f.read()

    result = {}
    for name in INTEGRATIONS:
        location = mcp_config.server_location(cwd, name)
        match = re.search(
            rf"^\s*{re.escape(name)}:\s*(true|false)\s*$",
            profile_text,
            re.MULTILINE,
        )
        result[name] = {
            # "legacy" = the old .claude/settings.json entry Claude Code never
            # read; re-run configure to move it.
            "configured": location not in (None, "legacy"),
            "location": location,
            "profile_flag": match.group(1) if match else None,
        }
    return result


# =====================================================================
# CLI
# =====================================================================

def _add_field_args(parser, name):
    for field in describe_fields(name):
        parser.add_argument(
            f"--{field['name']}",
            dest=field["name"].replace("-", "_"),
            help=f"{field['description']} ({field['guide']})",
        )


def _values_from_namespace(ns, name):
    values = {}
    for field in describe_fields(name):
        attr = field["name"].replace("-", "_")
        values[field["name"]] = getattr(ns, attr, None)
    return values


def cmd_configure(args):
    values = _values_from_namespace(args, args.integration)
    result = configure(args.cwd, args.integration, values)
    print(json.dumps(result, indent=2))


def cmd_remove(args):
    result = remove(args.cwd, args.integration)
    print(json.dumps(result, indent=2))


def cmd_status(args):
    result = status(args.cwd)
    print(json.dumps(result, indent=2))


def cmd_fields(args):
    fields = describe_fields(args.integration)
    print(json.dumps(fields, indent=2))


def main(argv=None):
    parent = argparse.ArgumentParser(add_help=False)
    # SUPPRESS so --cwd works before or after the subcommand (hody-cli-v1).
    parent.add_argument("--cwd", default=argparse.SUPPRESS, help="Project root")
    parser = argparse.ArgumentParser(description=__doc__, parents=[parent])
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Per-integration configure subcommands
    for name in INTEGRATIONS:
        p = sub.add_parser(name, parents=[parent], help=f"Configure {name} MCP server")
        _add_field_args(p, name)
        p.set_defaults(func=cmd_configure, integration=name)

    p_remove = sub.add_parser("remove", parents=[parent], help="Remove an integration")
    p_remove.add_argument("integration", choices=list(INTEGRATIONS))
    p_remove.set_defaults(func=cmd_remove)

    p_status = sub.add_parser("status", parents=[parent], help="Show integration status")
    p_status.set_defaults(func=cmd_status)

    p_fields = sub.add_parser(
        "fields", parents=[parent], help="Describe required fields (JSON for guides)"
    )
    p_fields.add_argument("integration", choices=list(INTEGRATIONS))
    p_fields.set_defaults(func=cmd_fields)

    args = parser.parse_args(argv)
    args.cwd = os.path.abspath(getattr(args, "cwd", os.getcwd()))
    try:
        args.func(args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
