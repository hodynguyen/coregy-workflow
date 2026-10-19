#!/usr/bin/env python3
"""
Automated Graphify setup for any project.

Finds a suitable Python >= 3.10, installs graphifyy, builds the knowledge
graph, configures the MCP server, and updates profile.yaml + .gitignore.

Usage:
    python3 graphify_setup.py [--cwd <path>]
"""
import argparse
import json
import os
import re
import subprocess
import sys


# ---------------------------------------------------------------------------
# Step 1: Find Python >= 3.10
# ---------------------------------------------------------------------------

# Candidate interpreter names, highest version first.
_CANDIDATE_NAMES = [
    "python3.13",
    "python3.12",
    "python3.11",
    "python3.10",
]

# Extra directories to search (macOS Homebrew, /usr/local).
_EXTRA_DIRS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
]


def _which(name):
    """Return absolute path if *name* is on PATH, else None."""
    try:
        result = subprocess.run(
            ["which", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _python_version(path):
    """Return (major, minor) for the interpreter at *path*, or None."""
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        text = (result.stdout + result.stderr).strip()
        m = re.search(r"(\d+)\.(\d+)\.\d+", text)
        if m:
            return (int(m.group(1)), int(m.group(2)))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def find_python(min_version=(3, 10)):
    """Return the path to the first Python interpreter >= *min_version*.

    Search order:
      1. Versioned names on PATH (python3.13 .. python3.10)
      2. Same names in common Homebrew / /usr/local dirs
      3. Fallback to ``python3`` if its version qualifies
    """
    # 1. Versioned names via which
    for name in _CANDIDATE_NAMES:
        path = _which(name)
        if path:
            ver = _python_version(path)
            if ver and ver >= min_version:
                return path

    # 2. Versioned names in extra directories
    for directory in _EXTRA_DIRS:
        for name in _CANDIDATE_NAMES:
            path = os.path.join(directory, name)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                ver = _python_version(path)
                if ver and ver >= min_version:
                    return path

    # 3. Fallback to generic python3
    path = _which("python3")
    if path:
        ver = _python_version(path)
        if ver and ver >= min_version:
            return path

    return None


# ---------------------------------------------------------------------------
# Step 2: Ensure graphifyy is installed
# ---------------------------------------------------------------------------


def ensure_graphify(python_path):
    """Make sure ``import graphify`` works under *python_path*.

    Attempts pip install if the package is missing.  Returns True on
    success, False on failure (with a message printed to stderr).
    """
    if _can_import_graphify(python_path):
        return True

    # Try normal pip install
    print("Installing graphifyy...")
    rc = _pip_install(python_path, extra_flags=[])
    if rc == 0 and _can_import_graphify(python_path):
        return True

    # PEP 668 externally-managed fallback
    rc = _pip_install(python_path, extra_flags=["--break-system-packages"])
    if rc == 0 and _can_import_graphify(python_path):
        return True

    print(
        "ERROR: Could not install graphifyy.\n"
        "Please install it manually:\n"
        "  %s -m pip install graphifyy\n" % python_path,
        file=sys.stderr,
    )
    return False


def _can_import_graphify(python_path):
    try:
        result = subprocess.run(
            [python_path, "-c", "import graphify"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _pip_install(python_path, extra_flags):
    try:
        result = subprocess.run(
            [python_path, "-m", "pip", "install", "graphifyy", "-q"]
            + extra_flags,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


# ---------------------------------------------------------------------------
# Step 3: Build the knowledge graph
# ---------------------------------------------------------------------------

_BUILD_SCRIPT = """\
import json, sys
from pathlib import Path
from graphify.detect import detect
from graphify.extract import extract
from graphify.build import build
from networkx.readwrite import json_graph

cwd = Path(sys.argv[1])
result = detect(cwd)
code_files = [Path(f) for f in result['files']['code']]
ast = extract(code_files)
G = build([ast], directed=True)
data = json_graph.node_link_data(G)
# Ensure "links" key for graphify CLI compatibility
if 'edges' in data and 'links' not in data:
    data['links'] = data.pop('edges')
out = cwd / 'graphify-out'
out.mkdir(exist_ok=True)
with open(out / 'graph.json', 'w') as f:
    json.dump(data, f)
print(json.dumps({"nodes": G.number_of_nodes(), "edges": G.number_of_edges()}))
"""


def _rotate_previous_graph(cwd):
    """Move existing graph.json to graph.prev.json before rebuilding.

    This enables /hody-workflow:status (and graphify_diff.py) to compare
    the new build against the previous snapshot. No-op if no prior graph
    exists.
    """
    graph_path = os.path.join(cwd, "graphify-out", "graph.json")
    prev_path = os.path.join(cwd, "graphify-out", "graph.prev.json")
    if os.path.isfile(graph_path):
        try:
            if os.path.isfile(prev_path):
                os.remove(prev_path)
            os.rename(graph_path, prev_path)
        except OSError:
            pass


def _restore_previous_graph(cwd):
    """Undo _rotate_previous_graph() after a failed build, so a failed rebuild
    never leaves the project without its last good graph.json."""
    graph_path = os.path.join(cwd, "graphify-out", "graph.json")
    prev_path = os.path.join(cwd, "graphify-out", "graph.prev.json")
    if not os.path.isfile(graph_path) and os.path.isfile(prev_path):
        try:
            os.rename(prev_path, graph_path)
        except OSError:
            pass


def build_graph(python_path, cwd):
    """Build the Graphify knowledge graph.  Returns (nodes, edges) or None."""
    _rotate_previous_graph(cwd)
    try:
        result = subprocess.run(
            [python_path, "-c", _BUILD_SCRIPT, cwd],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            print("ERROR: Graph build failed:\n" + result.stderr, file=sys.stderr)
            _restore_previous_graph(cwd)
            return None
        info = json.loads(result.stdout.strip())
        return info["nodes"], info["edges"]
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as exc:
        print("ERROR: Graph build failed: %s" % exc, file=sys.stderr)
        _restore_previous_graph(cwd)
        return None


# ---------------------------------------------------------------------------
# Step 4: Register the MCP server (see mcp_config.py)
# ---------------------------------------------------------------------------


def update_claude_settings(cwd, python_path):
    """Register the graphify MCP server where Claude Code reads it.

    Name kept for compatibility; before v0.13.1 this wrote `mcpServers` into
    .claude/settings.json, which Claude Code never loads.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import mcp_config

    config = {
        "command": python_path,
        # absolute path: the server must not depend on the cwd it starts in
        "args": ["-m", "graphify.serve",
                 os.path.join(os.path.abspath(cwd), "graphify-out", "graph.json")],
    }
    result = mcp_config.register_server(cwd, "graphify", config)
    print("MCP server registered: %s" % result["location"])
    if result.get("warning"):
        print("WARNING: %s" % result["warning"])
    return result


# ---------------------------------------------------------------------------
# Step 5: Update profile.yaml
# ---------------------------------------------------------------------------


def update_profile_yaml(cwd):
    """Ensure ``integrations.graphify: true`` in .hody/profile.yaml."""
    path = os.path.join(cwd, ".hody", "profile.yaml")
    if not os.path.isfile(path):
        print("WARNING: .hody/profile.yaml not found, skipping profile update.")
        return

    with open(path, "r") as f:
        content = f.read()

    # Case 1: graphify already set to true
    if re.search(r"^\s*graphify:\s*true\s*$", content, re.MULTILINE):
        print("Updated .hody/profile.yaml")
        return

    # Case 2: graphify line exists but set to false or other value
    new_content, count = re.subn(
        r"^(\s*)graphify:\s*\S+",
        r"\1graphify: true",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if count > 0:
        with open(path, "w") as f:
            f.write(new_content)
        print("Updated .hody/profile.yaml")
        return

    # Case 3: integrations section exists but no graphify line
    if re.search(r"^integrations:\s*$", content, re.MULTILINE):
        new_content = re.sub(
            r"^(integrations:\s*\n)",
            r"\1  graphify: true\n",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        with open(path, "w") as f:
            f.write(new_content)
        print("Updated .hody/profile.yaml")
        return

    # Case 4: no integrations section at all
    addition = "\nintegrations:\n  graphify: true\n"
    with open(path, "a") as f:
        f.write(addition)
    print("Updated .hody/profile.yaml")


# ---------------------------------------------------------------------------
# Step 6: Update .gitignore
# ---------------------------------------------------------------------------


def update_gitignore(cwd):
    """Ensure ``graphify-out/`` is listed in .gitignore."""
    path = os.path.join(cwd, ".gitignore")

    if os.path.isfile(path):
        with open(path, "r") as f:
            content = f.read()
        if re.search(r"(^|\n)graphify-out/?(\s|$)", content):
            print("Updated .gitignore")
            return
        # Ensure trailing newline before appending
        if content and not content.endswith("\n"):
            content += "\n"
        with open(path, "w") as f:
            f.write(content + "graphify-out/\n")
    else:
        with open(path, "w") as f:
            f.write("graphify-out/\n")

    print("Updated .gitignore")


# ---------------------------------------------------------------------------
# Step 7: Structural diff vs previous graph
# ---------------------------------------------------------------------------


def _run_diff(cwd):
    """Run graphify_diff against graph.prev.json, print summary, write
    new god-node entries to tech-debt.md. Silent no-op if no previous
    snapshot exists.
    """
    prev = os.path.join(cwd, "graphify-out", "graph.prev.json")
    if not os.path.isfile(prev):
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    try:
        from graphify_diff import compute_diff, format_summary, append_tech_debt
    except ImportError:
        # Script layout changed or diff module missing — skip silently.
        return

    curr = os.path.join(cwd, "graphify-out", "graph.json")
    try:
        diff = compute_diff(prev, curr)
    except (json.JSONDecodeError, OSError):
        return

    print("")
    print(format_summary(diff))
    n = append_tech_debt(cwd, diff)
    if n > 0:
        print("Appended %d god-node entries to tech-debt.md" % n)


# ---------------------------------------------------------------------------
# Step 8: Populate KB with graph-derived architecture
# ---------------------------------------------------------------------------


def _run_kb_populate(cwd):
    """Append graph-derived module boundaries and god nodes to
    .hody/knowledge/architecture.md. Silent no-op if KB doesn't exist.
    """
    arch_path = os.path.join(cwd, ".hody", "knowledge", "architecture.md")
    if not os.path.isfile(arch_path):
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    try:
        from graphify_kb_populate import (
            load_graph,
            generate_section,
            append_to_architecture,
        )
    except ImportError:
        return

    graph_path = os.path.join(cwd, "graphify-out", "graph.json")
    if not os.path.isfile(graph_path):
        return

    try:
        nodes, edges = load_graph(graph_path)
        if not nodes:
            return
        section = generate_section(nodes, edges, "graphify-out/graph.json")
        ok = append_to_architecture(cwd, section)
        if ok:
            print(
                "Updated architecture.md with graph-derived structure "
                "(%d nodes, %d edges)" % (len(nodes), len(edges))
            )
    except (json.JSONDecodeError, OSError):
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Automated Graphify setup")
    parser.add_argument("--cwd", default=".", help="Project root directory")
    args = parser.parse_args()

    cwd = os.path.abspath(args.cwd)
    if not os.path.isdir(cwd):
        print("ERROR: Directory does not exist: %s" % cwd, file=sys.stderr)
        sys.exit(1)

    # Step 1: Find Python >= 3.10
    print("Finding Python >= 3.10...")
    python_path = find_python()
    if not python_path:
        print(
            "ERROR: Python >= 3.10 not found.\n"
            "Install via pyenv, Homebrew (brew install python@3.13), "
            "or your system package manager.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("Using: %s" % python_path)

    # Step 2: Ensure graphifyy is installed
    if not ensure_graphify(python_path):
        sys.exit(1)

    # Step 3: Build the knowledge graph
    print("Building knowledge graph...")
    result = build_graph(python_path, cwd)
    if result is None:
        sys.exit(1)
    nodes, edges = result
    print("Graph built: %d nodes, %d edges" % (nodes, edges))

    # Step 4: Configure MCP server
    update_claude_settings(cwd, python_path)

    # Step 5: Update profile.yaml
    update_profile_yaml(cwd)

    # Step 6: Update .gitignore
    update_gitignore(cwd)

    # Step 7: Run structural diff against previous snapshot (if any)
    _run_diff(cwd)

    # Step 8: Populate KB with graph-derived architecture
    _run_kb_populate(cwd)

    # Step 9: Summary
    print("")
    print("Graphify setup complete!")
    print("  Graph: %d nodes, %d edges" % (nodes, edges))
    print("  MCP: graphify server registered")
    print("  Profile: integrations.graphify = true")
    print("")
    print("WARNING: Restart Claude Code to activate the MCP server.")


if __name__ == "__main__":
    main()
