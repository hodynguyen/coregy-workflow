"""
Agent contract validator for Hody Workflow.

Reads contract YAML files from agents/contracts/ and validates
that the required KB files have been modified and required sections
exist in the agent's output or KB.

Validation is advisory by default — produces warnings, not errors.
"""
import argparse
import calendar
import json
import os
import re
import sys
import time


# Contracts live in the plugin, not the project:
# scripts/ -> project-profile/ -> skills/ -> hody-workflow/agents/contracts
_DEFAULT_CONTRACTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "agents", "contracts"))


def _parse_yaml_simple(content):
    """Simple YAML parser for contract files (stdlib only).

    Handles top-level keys, string values, and lists of dicts.
    """
    result = {}
    current_key = None
    current_list = None

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        # Top-level key
        if indent == 0 and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value:
                result[key] = value
            else:
                result[key] = []
                current_key = key
                current_list = result[key]
            continue

        # List item under current key
        if current_key and stripped.startswith("- "):
            item_content = stripped[2:].strip()
            if ":" in item_content:
                # Dict item: parse key: value pairs
                item = {}
                k, _, v = item_content.partition(":")
                item[k.strip()] = v.strip().strip('"')
                current_list.append(item)
            else:
                current_list.append(item_content.strip('"'))
            continue

        # Continuation of dict item (indented under a list item)
        if current_list and indent >= 4 and ":" in stripped:
            k, _, v = stripped.partition(":")
            v = v.strip().strip('"')
            if current_list and isinstance(current_list[-1], dict):
                current_list[-1][k.strip()] = v

    return result


def load_contract(contract_path):
    """Load a contract YAML file.

    Returns parsed contract dict, or None if file doesn't exist.
    """
    if not os.path.isfile(contract_path):
        return None
    with open(contract_path, "r") as f:
        return _parse_yaml_simple(f.read())


def find_contract(contracts_dir, from_agent, to_agent):
    """Find a contract file for a given agent pair.

    Looks for: from-to.yaml, e.g. architect-to-backend.yaml
    """
    filename = f"{from_agent}-to-{to_agent}.yaml"
    path = os.path.join(contracts_dir, filename)
    if os.path.isfile(path):
        return load_contract(path)
    return None


def list_contracts(contracts_dir):
    """List all available contracts.

    Returns list of (from_agent, to_agent, contract) tuples.
    """
    contracts = []
    if not os.path.isdir(contracts_dir):
        return contracts

    for fname in sorted(os.listdir(contracts_dir)):
        if not fname.endswith(".yaml"):
            continue
        # Parse "from-to-to.yaml" pattern
        name = fname[:-5]  # strip .yaml
        match = re.match(r"^(.+?)-to-(.+)$", name)
        if match:
            from_agent = match.group(1)
            to_agent = match.group(2)
            contract = load_contract(os.path.join(contracts_dir, fname))
            if contract:
                contracts.append((from_agent, to_agent, contract))

    return contracts


def _workflow_started_epoch(state):
    """created_at of an in-progress workflow as a UNIX timestamp, or None."""
    if not isinstance(state, dict) or state.get("status") != "in_progress":
        return None
    created = state.get("created_at")
    if not created:
        return None
    try:
        return calendar.timegm(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return None


def _handoff_files(kb_dir, state):
    """KB files to search for required handoff sections.

    During an active workflow only its own feature log and spec count --
    otherwise a section written for some earlier feature satisfies the
    handoff forever. Without a workflow, every KB file is searched.

    Returns (paths, scoped_to_workflow).
    """
    if isinstance(state, dict) and state.get("status") == "in_progress":
        names = [state.get("log_file"), state.get("spec_file")]
        paths = [os.path.join(kb_dir, n) for n in names if n]
        paths = [p for p in paths if os.path.isfile(p)]
        if paths:
            return paths, True
    if not os.path.isdir(kb_dir):
        return [], False
    return [os.path.join(kb_dir, f) for f in sorted(os.listdir(kb_dir))
            if f.endswith(".md")], False


def validate_handoff(contract, kb_dir, state=None):
    """Validate a contract against the current KB state.

    Checks:
    1. Required KB files exist, have real content, and -- during an active
       workflow -- were modified after that workflow started
    2. Required sections exist as headings (any level ## to ######): in the
       workflow's feature log/spec when a workflow is active, else anywhere
       in the KB

    Args:
        contract: Parsed contract dict.
        kb_dir: Path to .hody/knowledge/ directory.
        state: Optional workflow state dict (scopes both checks to it).

    Returns:
        dict with 'passed', 'warnings', 'errors' keys.
        In advisory mode (default), all issues are warnings.
    """
    result = {"passed": True, "warnings": [], "errors": []}

    if not contract:
        return result

    started = _workflow_started_epoch(state)

    # Check validation rules
    for rule in contract.get("validation", []):
        check_type = rule.get("check", "")
        message = rule.get("message", "Validation check failed")

        if check_type == "kb_file_modified":
            kb_file = rule.get("file", "")
            kb_path = os.path.join(kb_dir, kb_file)

            if not os.path.isfile(kb_path):
                result["warnings"].append(f"[Missing] {kb_file}: {message}")
                continue

            # Check if file has content beyond template
            with open(kb_path, "r") as f:
                content = f.read()

            # A file with only template markers (<!-- -->) or very short content
            # is considered unmodified
            lines = [l for l in content.splitlines()
                     if l.strip() and not l.strip().startswith("<!--")
                     and not l.strip().startswith("#")
                     and not l.strip().startswith("---")]
            if len(lines) < 3:
                result["warnings"].append(f"[Template only] {kb_file}: {message}")
            elif started is not None and os.path.getmtime(kb_path) < started:
                result["warnings"].append(
                    f"[Not updated in this workflow] {kb_file}: {message}")

    # Check required sections (advisory -- check if KB mentions them)
    files, scoped = _handoff_files(kb_dir, state)
    contents = []
    for fpath in files:
        try:
            with open(fpath, "r") as f:
                contents.append(f.read())
        except OSError:
            continue

    for section in contract.get("required_sections", []):
        section_name = section.get("name", "")
        if not section_name:
            continue

        pattern = rf"^#{{2,6}}\s+.*{re.escape(section_name)}"
        found = any(re.search(pattern, c, re.IGNORECASE | re.MULTILINE)
                    for c in contents)

        if not found:
            fmt = section.get("format", "")
            where = "workflow log/spec" if scoped else "KB"
            result["warnings"].append(
                f"[Missing section] '{section_name}' not found in {where}"
                + (f" (expected: {fmt})" if fmt else "")
            )

    if result["warnings"] or result["errors"]:
        result["passed"] = False

    return result


def get_contracts_for_agent(contracts_dir, agent_name):
    """Get all contracts where agent_name is the 'to' agent (receiving handoff).

    Returns list of (from_agent, contract) tuples.
    """
    incoming = []
    for from_agent, to_agent, contract in list_contracts(contracts_dir):
        if to_agent == agent_name:
            incoming.append((from_agent, contract))
    return incoming


# ---------------------------------------------------------------------------
# CLI (hody-cli-v1)
# ---------------------------------------------------------------------------


def _output(data):
    print(json.dumps(data, indent=2, default=str))


def _fail(msg, json_mode=False):
    if json_mode:
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print("Error: %s" % msg, file=sys.stderr)
    sys.exit(1)


def _load_workflow_state(cwd):
    """Best-effort load of .hody/state.json to pass to validate_handoff()."""
    try:
        from . import state as state_module
    except ImportError:
        try:
            import state as state_module
        except ImportError:
            return None
    try:
        return state_module.load_state(cwd)
    except Exception:
        return None


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
        description="Hody Workflow agent handoff contracts (advisory)",
        parents=[parent],
    )
    sub = parser.add_subparsers(dest="command")

    p_val = sub.add_parser("validate", parents=[parent],
                           help="Validate a from->to handoff against the KB")
    # "from" is a Python keyword, so args.from would be a SyntaxError.
    p_val.add_argument("--from", dest="from_agent", required=True,
                       help="Producing agent")
    p_val.add_argument("--to", dest="to_agent", required=True,
                       help="Consuming agent")
    p_val.add_argument("--contracts-dir", default=None)
    p_val.add_argument("--kb-dir", default=None,
                       help="KB directory (default: <cwd>/.hody/knowledge)")
    p_val.add_argument("--strict", action="store_true",
                       help="Exit 1 when validation fails (CI only -- agents must not use this)")
    p_val.add_argument("--json", action="store_true", dest="json_mode")

    p_list = sub.add_parser("list", parents=[parent], help="List available contracts")
    p_list.add_argument("--contracts-dir", default=None)
    p_list.add_argument("--json", action="store_true", dest="json_mode")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # getattr, not args.cwd: the shared --cwd action defaults to
    # SUPPRESS so a value given before the subcommand survives.
    cwd = os.path.abspath(getattr(args, "cwd", "."))
    contracts_dir = (os.path.abspath(args.contracts_dir) if args.contracts_dir
                     else _DEFAULT_CONTRACTS_DIR)
    json_mode = getattr(args, "json_mode", False)

    try:
        if args.command == "validate":
            kb_dir = (os.path.abspath(args.kb_dir) if args.kb_dir
                      else os.path.join(cwd, ".hody", "knowledge"))
            contract = find_contract(contracts_dir, args.from_agent, args.to_agent)
            pair = "%s -> %s" % (args.from_agent, args.to_agent)

            if contract is None:
                if json_mode:
                    _output({"contract": None, "passed": True,
                             "warnings": [], "errors": []})
                else:
                    print("No contract for %s (nothing to check)" % pair)
                return

            result = validate_handoff(contract, kb_dir,
                                      state=_load_workflow_state(cwd))
            name = "%s-to-%s.yaml" % (args.from_agent, args.to_agent)

            if json_mode:
                _output({
                    "contract": name,
                    "passed": result["passed"],
                    "warnings": result["warnings"],
                    "errors": result["errors"],
                })
            else:
                issues = result["warnings"] + result["errors"]
                if not issues:
                    print("Contract %s: PASS" % pair)
                else:
                    print("Contract %s: %d warning(s)" % (pair, len(issues)))
                    for issue in issues:
                        print("  - %s" % issue)

            # Advisory by default -- exit 0 even with warnings.
            if args.strict and not result["passed"]:
                sys.exit(1)

        elif args.command == "list":
            contracts = list_contracts(contracts_dir)
            if json_mode:
                _output([{"from": f, "to": t, "contract": c}
                         for f, t, c in contracts])
            else:
                for from_agent, to_agent, _c in contracts:
                    print("%-24s (%s-to-%s.yaml)"
                          % ("%s -> %s" % (from_agent, to_agent),
                             from_agent, to_agent))
                print("%d contract(s)." % len(contracts))
    except (FileNotFoundError, ValueError, OSError) as exc:
        _fail(str(exc), json_mode)


if __name__ == "__main__":
    main()
