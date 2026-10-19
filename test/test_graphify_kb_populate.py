"""Tests for graphify_kb_populate.py — KB enrichment from graph data."""
import json
import os
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "coregy-workflow",
    "skills",
    "project-profile",
    "scripts",
)
sys.path.insert(0, os.path.abspath(SCRIPT_DIR))

from graphify_kb_populate import (
    compute_modules,
    compute_coupling,
    compute_god_nodes,
    generate_section,
    append_to_architecture,
    load_graph,
)


def _node(id_, label=None, source_file=""):
    return {
        "id": id_,
        "label": label or id_,
        "file_type": "code",
        "source_file": source_file,
        "source_location": "L1",
    }


def _edge(src, tgt, relation="calls"):
    return {"source": src, "target": tgt, "relation": relation}


SAMPLE_NODES = [
    _node("mod_a_foo", "foo()", "src/mod_a/foo.py"),
    _node("mod_a_bar", "bar()", "src/mod_a/bar.py"),
    _node("mod_b_baz", "baz()", "src/mod_b/baz.py"),
    _node("mod_b_qux", "qux()", "src/mod_b/qux.py"),
    _node("root_main", "main()", "main.py"),
]

SAMPLE_EDGES = [
    _edge("root_main", "mod_a_foo"),       # cross-module call
    _edge("root_main", "mod_b_baz"),       # cross-module call
    _edge("mod_a_foo", "mod_a_bar"),       # intra-module call
    _edge("mod_a_foo", "mod_b_baz"),       # cross-module call
    _edge("mod_b_baz", "mod_b_qux", "contains"),  # not a call
]


class TestComputeModules(unittest.TestCase):
    def test_groups_by_directory(self):
        modules = compute_modules(SAMPLE_NODES)
        self.assertEqual(len(modules["src/mod_a"]), 2)
        self.assertEqual(len(modules["src/mod_b"]), 2)
        self.assertEqual(len(modules["."]), 1)

    def test_empty(self):
        self.assertEqual(compute_modules([]), {})


class TestComputeCoupling(unittest.TestCase):
    def test_cross_module_calls_only(self):
        coupling = compute_coupling(SAMPLE_EDGES, SAMPLE_NODES)
        # Should find cross-module calls, not intra-module or non-call edges
        pairs = {(s, t) for s, t, c in coupling}
        self.assertIn((".", "src/mod_a"), pairs)
        self.assertIn((".", "src/mod_b"), pairs)
        self.assertIn(("src/mod_a", "src/mod_b"), pairs)
        # Intra-module should NOT appear
        self.assertNotIn(("src/mod_a", "src/mod_a"), pairs)

    def test_ignores_non_call_relations(self):
        # mod_b_baz → mod_b_qux is "contains", not "calls" — excluded
        coupling = compute_coupling(SAMPLE_EDGES, SAMPLE_NODES)
        for s, t, c in coupling:
            self.assertNotEqual(
                (s, t), ("src/mod_b", "src/mod_b"),
                "Intra-module contains edge should not appear"
            )

    def test_sorted_by_count_desc(self):
        coupling = compute_coupling(SAMPLE_EDGES, SAMPLE_NODES)
        counts = [c for _, _, c in coupling]
        self.assertEqual(counts, sorted(counts, reverse=True))


class TestComputeGodNodes(unittest.TestCase):
    def test_ranks_by_in_degree(self):
        gods = compute_god_nodes(SAMPLE_NODES, SAMPLE_EDGES, top_n=3)
        # mod_b_baz has 2 incoming (from root_main and mod_a_foo)
        self.assertEqual(gods[0]["id"], "mod_b_baz")
        self.assertEqual(gods[0]["in_degree"], 2)

    def test_respects_top_n(self):
        gods = compute_god_nodes(SAMPLE_NODES, SAMPLE_EDGES, top_n=1)
        self.assertEqual(len(gods), 1)

    def test_empty_graph(self):
        self.assertEqual(compute_god_nodes([], [], top_n=5), [])


class TestGenerateSection(unittest.TestCase):
    def test_contains_all_subsections(self):
        section = generate_section(SAMPLE_NODES, SAMPLE_EDGES, "graph.json")
        self.assertIn("## Graph-Derived Architecture", section)
        self.assertIn("### Module Boundaries", section)
        self.assertIn("### Cross-Module Coupling", section)
        self.assertIn("### High-Coupling Nodes", section)
        self.assertIn("### Edge Relation Summary", section)

    def test_contains_section_metadata_comment(self):
        section = generate_section(SAMPLE_NODES, SAMPLE_EDGES, "graph.json")
        self.assertIn("author_agent: graphify_kb_populate", section)
        self.assertIn("tags: graphify, architecture, auto-generated -->", section)
        # a mid-file `---` block is not frontmatter -- must not be emitted
        self.assertNotIn("\n---\n", section)

    def test_rewrite_keeps_real_frontmatter(self):
        with tempfile.TemporaryDirectory() as cwd:
            kb = os.path.join(cwd, ".coregy", "knowledge")
            os.makedirs(kb)
            path = os.path.join(kb, "architecture.md")
            with open(path, "w") as f:
                f.write("---\ntags: [architecture]\nstatus: active\n---\n\n")
            section = generate_section(SAMPLE_NODES, SAMPLE_EDGES, "graph.json")
            append_to_architecture(cwd, section)
            append_to_architecture(cwd, section)  # replace path
            with open(path) as f:
                content = f.read()
            self.assertTrue(content.startswith("---\ntags: [architecture]\nstatus: active\n---\n"))
            self.assertEqual(content.count("## Graph-Derived Architecture"), 1)

    def test_contains_node_counts(self):
        section = generate_section(SAMPLE_NODES, SAMPLE_EDGES, "graph.json")
        self.assertIn("5 nodes", section)
        self.assertIn("5 edges", section)

    def test_empty_graph(self):
        section = generate_section([], [], "graph.json")
        self.assertIn("0 nodes", section)


class TestAppendToArchitecture(unittest.TestCase):
    def _setup_kb(self, tmpdir, content="# Architecture\n\nExisting content.\n"):
        kb_dir = os.path.join(tmpdir, ".coregy", "knowledge")
        os.makedirs(kb_dir)
        path = os.path.join(kb_dir, "architecture.md")
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_append_new_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._setup_kb(tmp)
            section = generate_section(SAMPLE_NODES, SAMPLE_EDGES, "g.json")
            ok = append_to_architecture(tmp, section)
            self.assertTrue(ok)
            with open(path) as f:
                content = f.read()
            self.assertIn("Existing content.", content)
            self.assertIn("## Graph-Derived Architecture", content)
            self.assertIn("mod_b_baz", content)

    def test_replace_existing_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            initial = (
                "# Architecture\n\nExisting.\n\n"
                "## Graph-Derived Architecture\n\nOLD DATA\n\n"
                "## Other Section\n\nKeep this.\n"
            )
            path = self._setup_kb(tmp, initial)
            section = generate_section(SAMPLE_NODES, SAMPLE_EDGES, "g.json")
            append_to_architecture(tmp, section)
            with open(path) as f:
                content = f.read()
            # Old data replaced
            self.assertNotIn("OLD DATA", content)
            # New data present
            self.assertIn("mod_b_baz", content)
            # Other section preserved
            self.assertIn("## Other Section", content)
            self.assertIn("Keep this.", content)

    def test_no_file_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = append_to_architecture(tmp, "anything")
            self.assertFalse(ok)


class TestLoadGraph(unittest.TestCase):
    def test_links_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "g.json")
            with open(path, "w") as f:
                json.dump({"nodes": [{"id": "a"}], "links": [{"source": "a", "target": "a"}]}, f)
            nodes, edges = load_graph(path)
            self.assertEqual(len(nodes), 1)
            self.assertEqual(len(edges), 1)

    def test_edges_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "g.json")
            with open(path, "w") as f:
                json.dump({"nodes": [{"id": "a"}], "edges": [{"source": "a", "target": "a"}]}, f)
            nodes, edges = load_graph(path)
            self.assertEqual(len(edges), 1)


if __name__ == "__main__":
    unittest.main()
