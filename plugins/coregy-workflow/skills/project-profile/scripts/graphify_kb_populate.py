#!/usr/bin/env python3
"""
Populate knowledge base with structural data from Graphify graph.json.

Reads graphify-out/graph.json, derives module boundaries, cross-module
coupling, and god nodes, then appends a "Graph-Derived Architecture" section
to .coregy/knowledge/architecture.md.

Usage:
    python3 graphify_kb_populate.py [--cwd <path>] [--dry-run]
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime


def load_graph(path):
    """Load graph.json. Return (nodes, edges) as lists of dicts."""
    with open(path, "r") as f:
        data = json.load(f)
    nodes = data.get("nodes", [])
    edges = data.get("links") or data.get("edges") or []
    return nodes, edges


def _module_for(source_file):
    """Map a source_file path to a module name (its directory)."""
    d = os.path.dirname(source_file) if source_file else ""
    return d or "."


def compute_modules(nodes):
    """Group nodes by module (source_file directory).

    Returns dict mapping module_name → list of node dicts.
    """
    modules = {}
    for n in nodes:
        mod = _module_for(n.get("source_file", ""))
        modules.setdefault(mod, []).append(n)
    return modules


def compute_coupling(edges, nodes):
    """Compute cross-module edge counts (calls relations only).

    Returns list of (source_module, target_module, count) sorted by count desc.
    """
    node_module = {}
    for n in nodes:
        node_module[n.get("id")] = _module_for(n.get("source_file", ""))

    pair_counts = Counter()
    for e in edges:
        if e.get("relation") != "calls":
            continue
        src_mod = node_module.get(e.get("source"), "")
        tgt_mod = node_module.get(e.get("target"), "")
        if src_mod and tgt_mod and src_mod != tgt_mod:
            pair_counts[(src_mod, tgt_mod)] += 1

    result = [(s, t, c) for (s, t), c in pair_counts.items()]
    result.sort(key=lambda x: -x[2])
    return result


def compute_god_nodes(nodes, edges, top_n=10):
    """Find top-N nodes by incoming-edge count (all relation types).

    Returns list of dicts with id, label, source_file, in_degree.
    """
    in_degree = Counter()
    for e in edges:
        tgt = e.get("target")
        if tgt:
            in_degree[tgt] += 1

    node_map = {n["id"]: n for n in nodes if "id" in n}
    scored = [(nid, deg) for nid, deg in in_degree.items() if nid in node_map]
    scored.sort(key=lambda x: (-x[1], x[0]))

    result = []
    for nid, deg in scored[:top_n]:
        n = node_map[nid]
        result.append({
            "id": nid,
            "label": n.get("label", nid),
            "source_file": n.get("source_file", ""),
            "in_degree": deg,
        })
    return result


def generate_section(nodes, edges, graph_path):
    """Generate the markdown section string for architecture.md."""
    modules = compute_modules(nodes)
    coupling = compute_coupling(edges, nodes)
    gods = compute_god_nodes(nodes, edges, top_n=10)
    today = datetime.utcnow().strftime("%Y-%m-%d")

    lines = []
    lines.append("")
    lines.append("## Graph-Derived Architecture")
    lines.append("<!-- author_agent: graphify_kb_populate | created: %s | "
                 "tags: graphify, architecture, auto-generated -->" % today)
    lines.append("")
    lines.append(
        "> Auto-generated from `%s` (%d nodes, %d edges). "
        "Re-run `/init --graph` or `/refresh --graph` to update."
        % (graph_path, len(nodes), len(edges))
    )
    lines.append("")

    # Module boundaries
    lines.append("### Module Boundaries")
    lines.append("")
    mod_sizes = [(mod, len(ns)) for mod, ns in modules.items()]
    mod_sizes.sort(key=lambda x: -x[1])
    lines.append("| Module | Nodes | Description |")
    lines.append("|--------|-------|-------------|")
    for mod, count in mod_sizes:
        lines.append("| `%s` | %d | |" % (mod, count))
    lines.append("")

    # Cross-module coupling
    if coupling:
        lines.append("### Cross-Module Coupling (calls)")
        lines.append("")
        lines.append("| From | To | Call count |")
        lines.append("|------|-----|-----------|")
        for src, tgt, cnt in coupling[:15]:
            lines.append("| `%s` | `%s` | %d |" % (src, tgt, cnt))
        lines.append("")

    # God nodes
    if gods:
        lines.append("### High-Coupling Nodes (God Nodes)")
        lines.append("")
        lines.append("| Node | Label | File | In-degree |")
        lines.append("|------|-------|------|-----------|")
        for g in gods:
            lines.append(
                "| `%s` | %s | `%s` | %d |"
                % (g["id"], g["label"], g["source_file"], g["in_degree"])
            )
        lines.append("")

    # Relation type summary
    rel_counts = Counter()
    for e in edges:
        rel_counts[e.get("relation", "unknown")] += 1
    lines.append("### Edge Relation Summary")
    lines.append("")
    for rel, cnt in rel_counts.most_common():
        lines.append("- **%s**: %d edges" % (rel, cnt))
    lines.append("")

    return "\n".join(lines)


def append_to_architecture(cwd, section_text):
    """Append the generated section to .coregy/knowledge/architecture.md.

    If the file already contains a '## Graph-Derived Architecture' section,
    replace it (everything from that heading to the next ## heading or EOF).
    Otherwise, append at the end.

    Returns True if the file was written.
    """
    path = os.path.join(cwd, ".coregy", "knowledge", "architecture.md")
    if not os.path.isfile(path):
        return False

    with open(path, "r") as f:
        content = f.read()

    marker = "## Graph-Derived Architecture"
    if marker in content:
        # Find the section start and end
        start = content.index(marker)
        # Versions before v0.13.1 wrote a `---` metadata block right above
        # the heading; drop it on rewrite. Match only that exact block -- a
        # bare rfind("---") could hit the closing line of the file's real
        # frontmatter and delete it.
        legacy = re.search(
            r"\n---\ntags: \[graphify, architecture, auto-generated\]\n"
            r"(?:[^\n]*\n){0,4}?---\n\s*$",
            content[:start],
        )
        if legacy:
            start = legacy.start()

        # Find next ## heading after the marker
        rest = content[content.index(marker) + len(marker):]
        next_heading = re.search(r"\n## ", rest)
        if next_heading:
            end = content.index(marker) + len(marker) + next_heading.start()
        else:
            end = len(content)

        new_content = content[:start].rstrip("\n") + section_text + "\n" + content[end:]
    else:
        new_content = content.rstrip("\n") + "\n" + section_text

    with open(path, "w") as f:
        f.write(new_content)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Populate KB from Graphify knowledge graph"
    )
    parser.add_argument("--cwd", default=".", help="Project root directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated section without writing",
    )
    args = parser.parse_args()

    cwd = os.path.abspath(args.cwd)
    graph_path = os.path.join(cwd, "graphify-out", "graph.json")

    if not os.path.isfile(graph_path):
        print("No graph found at %s — nothing to populate." % graph_path)
        sys.exit(0)

    nodes, edges = load_graph(graph_path)
    if not nodes:
        print("Graph is empty — nothing to populate.")
        sys.exit(0)

    section = generate_section(nodes, edges, "graphify-out/graph.json")

    if args.dry_run:
        print(section)
        return

    ok = append_to_architecture(cwd, section)
    if ok:
        print(
            "Updated .coregy/knowledge/architecture.md with graph-derived "
            "architecture (%d nodes, %d edges)." % (len(nodes), len(edges))
        )
    else:
        print(
            "WARNING: .coregy/knowledge/architecture.md not found — "
            "run /coregy-workflow:init first.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
