"""
Knowledge Base index builder for Hody Workflow.

Parses YAML frontmatter from KB markdown files and builds
`.hody/knowledge/_index.json` for fast tag/date/agent searching.

The index is a generated cache — it can always be rebuilt from the .md files.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone


def parse_frontmatter(content):
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body) tuple.
    If no frontmatter found, returns (None, content).
    """
    # Match --- delimited frontmatter at the start of content
    match = re.match(r"^---\s*\n(.*?)---\s*\n?(.*)", content, re.DOTALL)
    if not match:
        return None, content

    fm_text = match.group(1)
    body = match.group(2)

    # Simple YAML-like parsing (stdlib only, no PyYAML dependency)
    fm = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # Parse list values: [item1, item2, item3]
        if value.startswith("[") and value.endswith("]"):
            items = value[1:-1]
            fm[key] = [i.strip().strip("\"'") for i in items.split(",") if i.strip()]
        # Parse null
        elif value.lower() in ("null", "~", ""):
            fm[key] = None
        # Parse booleans
        elif value.lower() in ("true", "yes"):
            fm[key] = True
        elif value.lower() in ("false", "no"):
            fm[key] = False
        else:
            # Strip quotes
            fm[key] = value.strip("\"'")

    return fm, body


def extract_sections(content):
    """Extract ## heading sections from markdown content.

    Returns list of dicts with 'heading', 'level', 'line_number', 'line_count'.
    """
    sections = []
    lines = content.splitlines()

    for i, line in enumerate(lines):
        match = re.match(r"^(#{1,4})\s+(.+)", line)
        if match:
            sections.append({
                "heading": match.group(2).strip(),
                "level": len(match.group(1)),
                "line_number": i + 1,
            })

    # Calculate line counts
    for i, section in enumerate(sections):
        if i + 1 < len(sections):
            section["line_count"] = sections[i + 1]["line_number"] - section["line_number"]
        else:
            section["line_count"] = len(lines) - section["line_number"] + 1

    return sections


def build_file_entry(filepath):
    """Build an index entry for a single KB file.

    Returns dict with file metadata, frontmatter fields, and sections.
    """
    try:
        with open(filepath, "r") as f:
            content = f.read()
    except OSError:
        return None

    filename = os.path.basename(filepath)
    fm, body = parse_frontmatter(content)
    sections = extract_sections(body if fm else content)
    total_lines = len(content.splitlines())

    entry = {
        "file": filename,
        "total_lines": total_lines,
        "has_frontmatter": fm is not None,
        "tags": [],
        "author_agent": None,
        "created": None,
        "status": "active",
        "supersedes": None,
        "sections": [
            {"heading": s["heading"], "level": s["level"], "line": s["line_number"]}
            for s in sections
        ],
    }

    if fm:
        entry["tags"] = fm.get("tags", []) or []
        # Hyphen/`date` spellings were written by start-feature and state.py
        # before v0.13.1; accept them so existing spec/log files stay indexed.
        entry["author_agent"] = fm.get("author_agent") or fm.get("author-agent")
        entry["created"] = fm.get("created") or fm.get("date")
        entry["status"] = fm.get("status", "active")
        entry["supersedes"] = fm.get("supersedes")

    return entry


def _load_graph_metadata(cwd):
    """Load graph stats and god nodes from graphify-out/graph.json.

    Returns a dict with node_count, edge_count, modules, god_nodes,
    or None if the graph is not available.
    """
    graph_path = os.path.join(cwd, "graphify-out", "graph.json")
    if not os.path.isfile(graph_path):
        return None

    try:
        with open(graph_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    nodes = data.get("nodes", [])
    edges = data.get("links") or data.get("edges") or []
    if not nodes:
        return None

    # Module counts
    modules = {}
    for n in nodes:
        d = os.path.dirname(n.get("source_file", "")) or "."
        modules[d] = modules.get(d, 0) + 1

    # God nodes (top 10 by in-degree)
    in_deg = {}
    for e in edges:
        tgt = e.get("target")
        if tgt:
            in_deg[tgt] = in_deg.get(tgt, 0) + 1

    node_map = {n["id"]: n for n in nodes if "id" in n}
    scored = sorted(in_deg.items(), key=lambda x: -x[1])
    god_nodes = []
    for nid, deg in scored[:10]:
        if nid in node_map:
            god_nodes.append({
                "id": nid,
                "label": node_map[nid].get("label", nid),
                "in_degree": deg,
            })

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "modules": modules,
        "god_nodes": god_nodes,
    }


def build_index(kb_dir, cwd=None):
    """Build the full index from all .md files in the KB directory.

    Returns the index dict. Skips _index.json and archive/ directory.
    If *cwd* is given and graphify-out/graph.json exists, includes
    graph metadata under key ``graph_metadata``.
    """
    entries = []

    if not os.path.isdir(kb_dir):
        return {"version": 1, "built_at": _now(), "entries": []}

    for fname in sorted(os.listdir(kb_dir)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(kb_dir, fname)
        if not os.path.isfile(fpath):
            continue
        entry = build_file_entry(fpath)
        if entry:
            entries.append(entry)

    index = {
        "version": 1,
        "built_at": _now(),
        "entries": entries,
    }

    if cwd:
        gm = _load_graph_metadata(cwd)
        if gm:
            index["graph_metadata"] = gm

    return index


def write_index(kb_dir, cwd=None):
    """Build and write _index.json to the KB directory.

    If *cwd* is given, graph metadata is included. Otherwise, infers the
    project root as two directories up from *kb_dir* (i.e. .hody/knowledge/).

    Returns the index dict.
    """
    if cwd is None:
        cwd = os.path.dirname(os.path.dirname(kb_dir))
    index = build_index(kb_dir, cwd=cwd)
    index_path = os.path.join(kb_dir, "_index.json")
    os.makedirs(kb_dir, exist_ok=True)
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)
    return index


def load_index(kb_dir):
    """Load _index.json from KB directory. Returns None if not found."""
    index_path = os.path.join(kb_dir, "_index.json")
    if not os.path.isfile(index_path):
        return None
    with open(index_path, "r") as f:
        return json.load(f)


def search_index(index, tag=None, agent=None, status=None):
    """Search the index by tag, author_agent, or status.

    Returns list of matching entries.
    """
    if index is None:
        return []

    results = []
    for entry in index.get("entries", []):
        if tag and tag.lower() not in [t.lower() for t in entry.get("tags", [])]:
            continue
        if agent and entry.get("author_agent") != agent:
            continue
        if status and entry.get("status") != status:
            continue
        results.append(entry)

    return results


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _resolve_kb_dir(cwd, kb_dir):
    if kb_dir:
        return os.path.abspath(kb_dir)
    return os.path.join(cwd, ".hody", "knowledge")


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
        description="Hody Workflow knowledge base index (_index.json)",
        parents=[parent],
    )
    sub = parser.add_subparsers(dest="command")

    p_build = sub.add_parser("build", parents=[parent],
                             help="Build/rebuild .hody/knowledge/_index.json")
    p_build.add_argument("--kb-dir", default=None,
                         help="KB directory (default: <cwd>/.hody/knowledge)")
    p_build.add_argument("--json", action="store_true", dest="json_mode")

    p_search = sub.add_parser("search", parents=[parent],
                              help="Search the index by tag/agent/status")
    p_search.add_argument("--tag", default=None)
    p_search.add_argument("--agent", default=None)
    p_search.add_argument("--status", default=None)
    p_search.add_argument("--kb-dir", default=None,
                          help="KB directory (default: <cwd>/.hody/knowledge)")
    p_search.add_argument("--json", action="store_true", dest="json_mode")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # getattr, not args.cwd: the shared --cwd action defaults to
    # SUPPRESS so a value given before the subcommand survives.
    cwd = os.path.abspath(getattr(args, "cwd", "."))
    kb_dir = _resolve_kb_dir(cwd, args.kb_dir)
    json_mode = getattr(args, "json_mode", False)

    try:
        if args.command == "build":
            # cwd is passed explicitly: write_index() would otherwise infer the
            # project root two levels above kb_dir, which breaks a custom --kb-dir.
            index = write_index(kb_dir, cwd=cwd)
            if json_mode:
                _output(index)
            else:
                index_path = os.path.join(kb_dir, "_index.json")
                print("Indexed %d file(s) -> %s"
                      % (len(index.get("entries", [])), index_path))
                gm = index.get("graph_metadata")
                if gm:
                    print("Graph: %s nodes, %s edges"
                          % (gm.get("node_count", "?"), gm.get("edge_count", "?")))

        elif args.command == "search":
            index = load_index(kb_dir)
            if index is None:
                _fail(
                    "No index at %s -- run: kb_index.py build --cwd ."
                    % os.path.join(kb_dir, "_index.json"),
                    json_mode,
                )
            results = search_index(index, tag=args.tag, agent=args.agent,
                                   status=args.status)
            if json_mode:
                _output(results)
            else:
                for entry in results:
                    print("%s  tags=[%s]  agent=%s  status=%s  (%d sections)" % (
                        entry.get("file", "?"),
                        ",".join(entry.get("tags", []) or []),
                        entry.get("author_agent") or "-",
                        entry.get("status") or "-",
                        len(entry.get("sections", []) or []),
                    ))
                print("%d match(es)." % len(results))
    except (FileNotFoundError, ValueError, OSError) as exc:
        _fail(str(exc), json_mode)


if __name__ == "__main__":
    main()
