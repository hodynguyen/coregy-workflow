"""Tests for graphify_diff.py — structural diff between two graph.json snapshots."""
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

from graphify_diff import (
    compute_diff,
    format_summary,
    append_tech_debt,
    load_graph,
    _degree_map,
    _top_n_by_degree,
)


def _write(tmpdir, name, data):
    path = os.path.join(tmpdir, name)
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def _graph(nodes, edges, edge_key="links"):
    return {"nodes": [{"id": n} for n in nodes], edge_key: edges}


class TestLoadGraph(unittest.TestCase):
    def test_links_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "g.json", _graph(["a", "b"], [{"source": "a", "target": "b"}]))
            nodes, edges = load_graph(path)
            self.assertEqual(len(nodes), 2)
            self.assertEqual(len(edges), 1)

    def test_edges_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                tmp,
                "g.json",
                _graph(["a", "b"], [{"source": "a", "target": "b"}], edge_key="edges"),
            )
            nodes, edges = load_graph(path)
            self.assertEqual(len(edges), 1)

    def test_empty_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "g.json", {"nodes": [], "links": []})
            nodes, edges = load_graph(path)
            self.assertEqual(nodes, [])
            self.assertEqual(edges, [])


class TestDegreeMap(unittest.TestCase):
    def test_in_degree_counts(self):
        edges = [
            {"source": "a", "target": "x"},
            {"source": "b", "target": "x"},
            {"source": "a", "target": "y"},
        ]
        counts = _degree_map(edges)
        self.assertEqual(counts["x"], 2)
        self.assertEqual(counts["y"], 1)
        self.assertNotIn("a", counts)

    def test_ignores_missing_target(self):
        edges = [{"source": "a"}, {"target": "b"}]
        counts = _degree_map(edges)
        self.assertEqual(counts, {"b": 1})


class TestTopN(unittest.TestCase):
    def test_sorted_by_degree_desc(self):
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        edges = [
            {"source": "z", "target": "a"},
            {"source": "z", "target": "a"},
            {"source": "z", "target": "b"},
        ]
        top = _top_n_by_degree(nodes, edges, 5)
        self.assertEqual(top[0]["id"], "a")
        self.assertEqual(top[0]["degree"], 2)
        self.assertEqual(top[1]["id"], "b")

    def test_excludes_zero_degree(self):
        nodes = [{"id": "a"}, {"id": "b"}]
        edges = [{"source": "z", "target": "a"}]
        top = _top_n_by_degree(nodes, edges, 5)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["id"], "a")


class TestComputeDiff(unittest.TestCase):
    def test_no_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev = _write(tmp, "p.json", _graph(["a", "b"], [{"source": "a", "target": "b"}]))
            curr = _write(tmp, "c.json", _graph(["a", "b"], [{"source": "a", "target": "b"}]))
            diff = compute_diff(prev, curr)
            self.assertEqual(diff["nodes"]["added_count"], 0)
            self.assertEqual(diff["nodes"]["removed_count"], 0)
            self.assertEqual(diff["edges"]["added_count"], 0)
            self.assertEqual(diff["edges"]["removed_count"], 0)

    def test_added_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev = _write(tmp, "p.json", _graph(["a"], []))
            curr = _write(tmp, "c.json", _graph(["a", "b", "c"], []))
            diff = compute_diff(prev, curr)
            self.assertEqual(diff["nodes"]["added_count"], 2)
            self.assertIn("b", diff["nodes"]["added"])
            self.assertIn("c", diff["nodes"]["added"])

    def test_removed_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev = _write(tmp, "p.json", _graph(["a", "b", "c"], []))
            curr = _write(tmp, "c.json", _graph(["a"], []))
            diff = compute_diff(prev, curr)
            self.assertEqual(diff["nodes"]["removed_count"], 2)

    def test_added_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev = _write(tmp, "p.json", _graph(["a", "b"], []))
            curr = _write(
                tmp,
                "c.json",
                _graph(["a", "b"], [{"source": "a", "target": "b", "type": "calls"}]),
            )
            diff = compute_diff(prev, curr)
            self.assertEqual(diff["edges"]["added_count"], 1)

    def test_new_god_node(self):
        """A node that is top-10 in curr but not in prev is flagged."""
        with tempfile.TemporaryDirectory() as tmp:
            # prev: a has degree 1, b has degree 0
            prev = _write(
                tmp,
                "p.json",
                _graph(["a", "b", "caller"], [{"source": "caller", "target": "a"}]),
            )
            # curr: b has degree 3 — new god node
            curr = _write(
                tmp,
                "c.json",
                _graph(
                    ["a", "b", "caller"],
                    [
                        {"source": "caller", "target": "a"},
                        {"source": "caller", "target": "b"},
                        {"source": "a", "target": "b"},
                        {"source": "caller", "target": "b", "type": "import"},
                    ],
                ),
            )
            diff = compute_diff(prev, curr)
            new_ids = [g["id"] for g in diff["god_nodes"]["new_entries"]]
            self.assertIn("b", new_ids)

    def test_node_cap_at_50(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev = _write(tmp, "p.json", _graph([], []))
            big = [f"n{i}" for i in range(100)]
            curr = _write(tmp, "c.json", _graph(big, []))
            diff = compute_diff(prev, curr)
            self.assertEqual(diff["nodes"]["added_count"], 100)
            self.assertEqual(len(diff["nodes"]["added"]), 50)


class TestFormatSummary(unittest.TestCase):
    def test_contains_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev = _write(tmp, "p.json", _graph(["a"], []))
            curr = _write(tmp, "c.json", _graph(["a", "b"], []))
            diff = compute_diff(prev, curr)
            out = format_summary(diff)
            self.assertIn("Graphify diff", out)
            self.assertIn("+1", out)
            self.assertIn("no new god nodes", out)

    def test_mentions_new_god_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev = _write(tmp, "p.json", _graph(["a", "caller"], []))
            curr = _write(
                tmp,
                "c.json",
                _graph(["a", "caller"], [{"source": "caller", "target": "a"}]),
            )
            diff = compute_diff(prev, curr)
            out = format_summary(diff)
            self.assertIn("new god nodes", out)
            self.assertIn("a", out)


class TestAppendTechDebt(unittest.TestCase):
    def test_appends_when_new_gods(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Set up .coregy/knowledge/tech-debt.md
            kb_dir = os.path.join(tmp, ".coregy", "knowledge")
            os.makedirs(kb_dir)
            debt_path = os.path.join(kb_dir, "tech-debt.md")
            with open(debt_path, "w") as f:
                f.write("# Tech Debt\n\nInitial content.\n")

            prev = _write(tmp, "p.json", _graph(["a", "caller"], []))
            curr = _write(
                tmp,
                "c.json",
                _graph(["a", "caller"], [{"source": "caller", "target": "a"}]),
            )
            diff = compute_diff(prev, curr)
            count = append_tech_debt(tmp, diff)
            self.assertEqual(count, 1)

            with open(debt_path, "r") as f:
                content = f.read()
            self.assertIn("New god nodes detected", content)
            self.assertIn("`a`", content)
            self.assertIn("graphify", content)
            # Original content preserved
            self.assertIn("Initial content.", content)

    def test_no_op_when_no_new_gods(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb_dir = os.path.join(tmp, ".coregy", "knowledge")
            os.makedirs(kb_dir)
            debt_path = os.path.join(kb_dir, "tech-debt.md")
            with open(debt_path, "w") as f:
                f.write("original")

            prev = _write(tmp, "p.json", _graph(["a"], []))
            curr = _write(tmp, "c.json", _graph(["a"], []))
            diff = compute_diff(prev, curr)
            count = append_tech_debt(tmp, diff)
            self.assertEqual(count, 0)

            with open(debt_path, "r") as f:
                self.assertEqual(f.read(), "original")

    def test_no_op_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev = _write(tmp, "p.json", _graph(["a", "caller"], []))
            curr = _write(
                tmp,
                "c.json",
                _graph(["a", "caller"], [{"source": "caller", "target": "a"}]),
            )
            diff = compute_diff(prev, curr)
            count = append_tech_debt(tmp, diff)
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
