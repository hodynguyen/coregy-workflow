#!/usr/bin/env python3
"""
Compare two Graphify graph.json snapshots and report structural changes.

Detects:
  - Added / removed nodes (IDs, capped count)
  - Added / removed edge counts
  - God nodes (top N by degree) that are new since the previous build

Usage:
    python3 graphify_diff.py [--cwd <path>] [--prev PATH] [--curr PATH]
                             [--json] [--write-tech-debt]
"""
import argparse
import json
import os
import sys
from datetime import datetime


DEFAULT_TOP_N = 10


def load_graph(path):
    """Load graph.json. Return (nodes, edges) as lists of dicts."""
    with open(path, "r") as f:
        data = json.load(f)
    nodes = data.get("nodes", [])
    edges = data.get("links") or data.get("edges") or []
    return nodes, edges


def _node_ids(nodes):
    return {n.get("id") for n in nodes if n.get("id") is not None}


def _edge_key(e):
    """Return a hashable identity for an edge (source, target, type)."""
    return (
        e.get("source"),
        e.get("target"),
        e.get("type") or e.get("relation") or e.get("label"),
    )


def _degree_map(edges):
    """Count incoming edges per node id (in-degree, i.e. 'called by' count)."""
    counts = {}
    for e in edges:
        target = e.get("target")
        if target is None:
            continue
        counts[target] = counts.get(target, 0) + 1
    return counts


def _top_n_by_degree(nodes, edges, n):
    counts = _degree_map(edges)
    ids = _node_ids(nodes)
    scored = [(nid, counts.get(nid, 0)) for nid in ids]
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return [{"id": nid, "degree": deg} for nid, deg in scored[:n] if deg > 0]


def compute_diff(prev_path, curr_path, top_n=DEFAULT_TOP_N):
    """Compute a structural diff between two graph.json files.

    Returns a dict with node/edge counts, added/removed node IDs, and
    god-node deltas. Added/removed node lists are capped at 50 entries
    each to keep the output compact; full counts are always returned.
    """
    prev_nodes, prev_edges = load_graph(prev_path)
    curr_nodes, curr_edges = load_graph(curr_path)

    prev_ids = _node_ids(prev_nodes)
    curr_ids = _node_ids(curr_nodes)

    added_ids = sorted(curr_ids - prev_ids)
    removed_ids = sorted(prev_ids - curr_ids)

    prev_edge_keys = {_edge_key(e) for e in prev_edges}
    curr_edge_keys = {_edge_key(e) for e in curr_edges}

    added_edge_count = len(curr_edge_keys - prev_edge_keys)
    removed_edge_count = len(prev_edge_keys - curr_edge_keys)

    prev_gods = _top_n_by_degree(prev_nodes, prev_edges, top_n)
    curr_gods = _top_n_by_degree(curr_nodes, curr_edges, top_n)
    prev_god_ids = {g["id"] for g in prev_gods}
    new_god_entries = [g for g in curr_gods if g["id"] not in prev_god_ids]

    return {
        "prev": {
            "path": prev_path,
            "nodes": len(prev_nodes),
            "edges": len(prev_edges),
        },
        "curr": {
            "path": curr_path,
            "nodes": len(curr_nodes),
            "edges": len(curr_edges),
        },
        "nodes": {
            "added": added_ids[:50],
            "added_count": len(added_ids),
            "removed": removed_ids[:50],
            "removed_count": len(removed_ids),
        },
        "edges": {
            "added_count": added_edge_count,
            "removed_count": removed_edge_count,
        },
        "god_nodes": {
            "prev_top": prev_gods,
            "curr_top": curr_gods,
            "new_entries": new_god_entries,
        },
    }


def format_summary(diff):
    """Render a human-readable one-screen summary of a diff dict."""
    prev = diff["prev"]
    curr = diff["curr"]
    n_added = diff["nodes"]["added_count"]
    n_removed = diff["nodes"]["removed_count"]
    e_added = diff["edges"]["added_count"]
    e_removed = diff["edges"]["removed_count"]

    lines = []
    lines.append("Graphify diff")
    lines.append(
        "  prev: %d nodes, %d edges" % (prev["nodes"], prev["edges"])
    )
    lines.append(
        "  curr: %d nodes, %d edges" % (curr["nodes"], curr["edges"])
    )
    lines.append(
        "  nodes: +%d / -%d   edges: +%d / -%d"
        % (n_added, n_removed, e_added, e_removed)
    )

    new_gods = diff["god_nodes"]["new_entries"]
    if new_gods:
        lines.append("  new god nodes (top by in-degree):")
        for g in new_gods:
            lines.append("    - %s  (degree=%d)" % (g["id"], g["degree"]))
    else:
        lines.append("  no new god nodes")

    if n_added > 0:
        sample = diff["nodes"]["added"][:5]
        lines.append("  sample added: %s" % ", ".join(sample))
    if n_removed > 0:
        sample = diff["nodes"]["removed"][:5]
        lines.append("  sample removed: %s" % ", ".join(sample))

    return "\n".join(lines)


def append_tech_debt(cwd, diff):
    """Append a tech-debt entry for each newly-surfaced god node.

    Writes into .coregy/knowledge/tech-debt.md. Returns number of entries
    appended. Silent no-op if the file does not exist.
    """
    path = os.path.join(cwd, ".coregy", "knowledge", "tech-debt.md")
    new_gods = diff["god_nodes"]["new_entries"]
    if not new_gods or not os.path.isfile(path):
        return 0

    today = datetime.utcnow().strftime("%Y-%m-%d")
    lines = []
    lines.append("")
    lines.append("## New god nodes detected (%s)" % today)
    # Section metadata as a comment: a mid-file `---` block is not frontmatter
    # (Markdown renders its last line as a heading, the index ignores it).
    lines.append("<!-- author_agent: graphify_diff | created: %s | "
                 "tags: graphify, coupling, god-node -->" % today)
    lines.append("- **Priority**: medium")
    lines.append("")
    lines.append(
        "The Graphify knowledge graph flagged new high-coupling nodes "
        "since the last build. These may warrant refactoring to reduce "
        "incoming dependencies."
    )
    lines.append("")
    for g in new_gods:
        lines.append("- `%s` — in-degree %d" % (g["id"], g["degree"]))
    lines.append("")

    with open(path, "a") as f:
        f.write("\n".join(lines))

    return len(new_gods)


def main():
    parser = argparse.ArgumentParser(
        description="Diff two Graphify graph.json snapshots"
    )
    parser.add_argument("--cwd", default=".", help="Project root directory")
    parser.add_argument(
        "--prev",
        default=None,
        help="Path to previous graph.json (default: <cwd>/graphify-out/graph.prev.json)",
    )
    parser.add_argument(
        "--curr",
        default=None,
        help="Path to current graph.json (default: <cwd>/graphify-out/graph.json)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the diff as JSON instead of a human summary",
    )
    parser.add_argument(
        "--write-tech-debt",
        action="store_true",
        help="Append newly-surfaced god nodes to .coregy/knowledge/tech-debt.md",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help="How many top god nodes to consider (default: 10)",
    )
    args = parser.parse_args()

    cwd = os.path.abspath(args.cwd)
    prev = args.prev or os.path.join(cwd, "graphify-out", "graph.prev.json")
    curr = args.curr or os.path.join(cwd, "graphify-out", "graph.json")

    if not os.path.isfile(prev):
        print(
            "No previous graph snapshot found at %s — nothing to diff." % prev,
            file=sys.stderr,
        )
        sys.exit(0)
    if not os.path.isfile(curr):
        print("ERROR: Current graph not found at %s" % curr, file=sys.stderr)
        sys.exit(1)

    try:
        diff = compute_diff(prev, curr, top_n=args.top_n)
    except (json.JSONDecodeError, OSError) as exc:
        print("ERROR: Could not load graphs: %s" % exc, file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(diff, indent=2))
    else:
        print(format_summary(diff))

    if args.write_tech_debt:
        n = append_tech_debt(cwd, diff)
        if n > 0:
            print("Appended %d god-node entries to tech-debt.md" % n)


if __name__ == "__main__":
    main()
