"""Tests for KB index builder (kb_index.py) and auto-archival (kb_archive.py)."""
import json
import os
import sys
import tempfile
import unittest

# Add scripts dir to path
SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "hody-workflow",
    "skills",
    "project-profile",
    "scripts",
)
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

from kb_index import (
    parse_frontmatter,
    extract_sections,
    build_file_entry,
    build_index,
    write_index,
    load_index,
    search_index,
)
from kb_archive import (
    check_file_needs_archival,
    archive_file,
    check_all_kb_files,
)


# ---------------------------------------------------------------------------
# kb_index tests
# ---------------------------------------------------------------------------


class TestParseFrontmatter(unittest.TestCase):
    def test_with_frontmatter(self):
        content = "---\ntags: [auth, backend]\nauthor_agent: architect\ncreated: 2026-02-16\nstatus: active\nsupersedes: null\n---\n\n## My Section\nContent here.\n"
        fm, body = parse_frontmatter(content)
        self.assertIsNotNone(fm)
        self.assertEqual(fm["tags"], ["auth", "backend"])
        self.assertEqual(fm["author_agent"], "architect")
        self.assertEqual(fm["created"], "2026-02-16")
        self.assertEqual(fm["status"], "active")
        self.assertIsNone(fm["supersedes"])
        self.assertIn("## My Section", body)

    def test_without_frontmatter(self):
        content = "# Architecture\n\n## Overview\nSome text.\n"
        fm, body = parse_frontmatter(content)
        self.assertIsNone(fm)
        self.assertEqual(body, content)

    def test_empty_frontmatter(self):
        content = "---\n---\n\nBody text.\n"
        fm, body = parse_frontmatter(content)
        # Empty frontmatter still parses (just empty dict)
        self.assertIsNotNone(fm)
        self.assertEqual(fm, {})

    def test_boolean_values(self):
        content = "---\nenabled: true\ndisabled: false\n---\nBody.\n"
        fm, body = parse_frontmatter(content)
        self.assertTrue(fm["enabled"])
        self.assertFalse(fm["disabled"])

    def test_quoted_values(self):
        content = '---\ntitle: "My Title"\n---\nBody.\n'
        fm, body = parse_frontmatter(content)
        self.assertEqual(fm["title"], "My Title")


class TestExtractSections(unittest.TestCase):
    def test_multiple_sections(self):
        content = "## Overview\nLine 1\nLine 2\n\n## Details\nLine 3\nLine 4\nLine 5\n"
        sections = extract_sections(content)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["heading"], "Overview")
        self.assertEqual(sections[0]["line_number"], 1)
        self.assertEqual(sections[0]["line_count"], 4)
        self.assertEqual(sections[1]["heading"], "Details")

    def test_nested_headings(self):
        content = "## Section\n### Subsection\nText\n"
        sections = extract_sections(content)
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["level"], 2)
        self.assertEqual(sections[1]["level"], 3)

    def test_no_headings(self):
        content = "Just some plain text.\nNo headings here.\n"
        sections = extract_sections(content)
        self.assertEqual(len(sections), 0)


class TestBuildFileEntry(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_file_with_frontmatter(self):
        path = os.path.join(self.tmpdir.name, "decisions.md")
        with open(path, "w") as f:
            f.write("---\ntags: [auth, oauth2]\nauthor_agent: architect\ncreated: 2026-02-16\n---\n\n## ADR-001: OAuth2\nWe chose OAuth2.\n")

        entry = build_file_entry(path)
        self.assertEqual(entry["file"], "decisions.md")
        self.assertTrue(entry["has_frontmatter"])
        self.assertEqual(entry["tags"], ["auth", "oauth2"])
        self.assertEqual(entry["author_agent"], "architect")
        self.assertEqual(len(entry["sections"]), 1)
        self.assertEqual(entry["sections"][0]["heading"], "ADR-001: OAuth2")

    def test_file_without_frontmatter(self):
        path = os.path.join(self.tmpdir.name, "architecture.md")
        with open(path, "w") as f:
            f.write("# Architecture\n\n## Overview\nText\n\n## Components\nMore text\n")

        entry = build_file_entry(path)
        self.assertFalse(entry["has_frontmatter"])
        self.assertEqual(entry["tags"], [])
        self.assertIsNone(entry["author_agent"])
        # # heading + ## headings
        self.assertEqual(len(entry["sections"]), 3)

    def test_nonexistent_file(self):
        entry = build_file_entry("/nonexistent/file.md")
        self.assertIsNone(entry)


class TestBuildIndex(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.kb_dir = os.path.join(self.tmpdir.name, "knowledge")
        os.makedirs(self.kb_dir)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_build_index_multiple_files(self):
        for name in ["architecture.md", "decisions.md"]:
            with open(os.path.join(self.kb_dir, name), "w") as f:
                f.write(f"# {name}\n\n## Section\nContent\n")

        index = build_index(self.kb_dir)
        self.assertEqual(index["version"], 1)
        self.assertIn("built_at", index)
        self.assertEqual(len(index["entries"]), 2)

    def test_build_index_empty_dir(self):
        index = build_index(self.kb_dir)
        self.assertEqual(len(index["entries"]), 0)

    def test_build_index_nonexistent_dir(self):
        index = build_index("/nonexistent/dir")
        self.assertEqual(len(index["entries"]), 0)

    def test_skips_non_md_files(self):
        with open(os.path.join(self.kb_dir, "notes.txt"), "w") as f:
            f.write("not markdown")
        with open(os.path.join(self.kb_dir, "arch.md"), "w") as f:
            f.write("## Section\nContent\n")

        index = build_index(self.kb_dir)
        self.assertEqual(len(index["entries"]), 1)


class TestWriteAndLoadIndex(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.kb_dir = os.path.join(self.tmpdir.name, "knowledge")
        os.makedirs(self.kb_dir)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_write_and_load(self):
        with open(os.path.join(self.kb_dir, "test.md"), "w") as f:
            f.write("---\ntags: [test]\n---\n\n## Hello\nWorld\n")

        written = write_index(self.kb_dir)
        loaded = load_index(self.kb_dir)
        self.assertEqual(written["version"], loaded["version"])
        self.assertEqual(len(loaded["entries"]), 1)
        self.assertEqual(loaded["entries"][0]["tags"], ["test"])

    def test_load_nonexistent(self):
        self.assertIsNone(load_index(self.kb_dir))

    def test_rebuild_index(self):
        """Index can be rebuilt from .md files (cache, not source of truth)."""
        with open(os.path.join(self.kb_dir, "test.md"), "w") as f:
            f.write("---\ntags: [v1]\n---\n\n## First\nContent\n")
        write_index(self.kb_dir)

        # Modify the file
        with open(os.path.join(self.kb_dir, "test.md"), "w") as f:
            f.write("---\ntags: [v2, updated]\n---\n\n## First\nContent\n\n## Second\nMore\n")

        # Rebuild
        new_index = write_index(self.kb_dir)
        self.assertEqual(new_index["entries"][0]["tags"], ["v2", "updated"])
        self.assertEqual(len(new_index["entries"][0]["sections"]), 2)


class TestSearchIndex(unittest.TestCase):
    def setUp(self):
        self.index = {
            "version": 1,
            "built_at": "2026-02-16T10:00:00Z",
            "entries": [
                {
                    "file": "decisions.md",
                    "tags": ["auth", "backend"],
                    "author_agent": "architect",
                    "status": "active",
                },
                {
                    "file": "architecture.md",
                    "tags": ["frontend", "backend"],
                    "author_agent": "researcher",
                    "status": "active",
                },
                {
                    "file": "tech-debt.md",
                    "tags": ["backend"],
                    "author_agent": "code-reviewer",
                    "status": "superseded",
                },
            ],
        }

    def test_search_by_tag(self):
        results = search_index(self.index, tag="auth")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["file"], "decisions.md")

    def test_search_by_tag_multiple(self):
        results = search_index(self.index, tag="backend")
        self.assertEqual(len(results), 3)

    def test_search_by_agent(self):
        results = search_index(self.index, agent="architect")
        self.assertEqual(len(results), 1)

    def test_search_by_status(self):
        results = search_index(self.index, status="superseded")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["file"], "tech-debt.md")

    def test_search_combined(self):
        results = search_index(self.index, tag="backend", status="active")
        self.assertEqual(len(results), 2)

    def test_search_no_match(self):
        results = search_index(self.index, tag="nonexistent")
        self.assertEqual(len(results), 0)

    def test_search_none_index(self):
        results = search_index(None, tag="test")
        self.assertEqual(len(results), 0)

    def test_search_case_insensitive_tag(self):
        results = search_index(self.index, tag="Auth")
        self.assertEqual(len(results), 1)


# ---------------------------------------------------------------------------
# kb_archive tests
# ---------------------------------------------------------------------------


class TestCheckFileNeedsArchival(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_under_threshold(self):
        path = os.path.join(self.tmpdir.name, "small.md")
        with open(path, "w") as f:
            f.write("## Section\n" + "Line\n" * 10)
        needs, count = check_file_needs_archival(path, threshold=500)
        self.assertFalse(needs)

    def test_over_threshold(self):
        path = os.path.join(self.tmpdir.name, "big.md")
        with open(path, "w") as f:
            f.write("## Section\n" + "Line\n" * 600)
        needs, count = check_file_needs_archival(path, threshold=500)
        self.assertTrue(needs)
        self.assertEqual(count, 601)

    def test_nonexistent_file(self):
        needs, count = check_file_needs_archival("/nonexistent/file.md")
        self.assertFalse(needs)


class TestArchiveFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.kb_dir = os.path.join(self.tmpdir.name, "knowledge")
        os.makedirs(self.kb_dir)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_big_file(self, name, num_sections=10, lines_per_section=60):
        """Create a large KB file with multiple sections."""
        path = os.path.join(self.kb_dir, name)
        content = f"# {name}\n\nPreamble text.\n\n"
        for i in range(num_sections):
            content += f"## Section {i + 1}\n"
            content += f"Content for section {i + 1}.\n" * lines_per_section
            content += "\n"
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_archive_large_file(self):
        path = self._make_big_file("decisions.md", num_sections=10, lines_per_section=60)
        result = archive_file(path, threshold=500, keep_sections=3)

        self.assertIsNotNone(result)
        self.assertEqual(result["archived_sections"], 7)
        self.assertIn("archive", result["archive_file"])
        self.assertTrue(os.path.isfile(result["archive_file"]))

        # Main file should still exist with fewer lines
        with open(path) as f:
            remaining = f.read()
        self.assertIn("Section 10", remaining)
        self.assertIn("Section 9", remaining)
        self.assertIn("Section 8", remaining)
        self.assertNotIn("Section 1\n", remaining)

    def test_no_archive_under_threshold(self):
        path = os.path.join(self.kb_dir, "small.md")
        with open(path, "w") as f:
            f.write("## Section\nSmall content.\n")
        result = archive_file(path, threshold=500)
        self.assertIsNone(result)

    def test_no_archive_too_few_sections(self):
        path = os.path.join(self.kb_dir, "few.md")
        content = "# Title\n\n" + "## Section 1\n" + "Line\n" * 300 + "## Section 2\n" + "Line\n" * 300
        with open(path, "w") as f:
            f.write(content)
        result = archive_file(path, threshold=500, keep_sections=3)
        self.assertIsNone(result)

    def test_preamble_preserved(self):
        path = self._make_big_file("architecture.md", num_sections=8, lines_per_section=80)
        # Add preamble content
        with open(path, "r") as f:
            content = f.read()
        self.assertIn("Preamble text", content)

        archive_file(path, threshold=500, keep_sections=3)
        with open(path, "r") as f:
            remaining = f.read()
        self.assertIn("Preamble text", remaining)

    def test_archive_directory_created(self):
        path = self._make_big_file("tech-debt.md", num_sections=10, lines_per_section=60)
        archive_dir = os.path.join(self.kb_dir, "archive")
        self.assertFalse(os.path.isdir(archive_dir))

        archive_file(path, threshold=500)
        self.assertTrue(os.path.isdir(archive_dir))

    def test_topical_file_keeps_undated_sections(self):
        # architecture.md is organised by topic: "Section 1" (think "System
        # Overview") must never be archived just for being first.
        path = self._make_big_file("architecture.md", num_sections=8, lines_per_section=80)
        self.assertIsNone(archive_file(path, threshold=500, keep_sections=3))
        with open(path) as f:
            self.assertIn("## Section 1\n", f.read())

    def test_dated_sections_archived_oldest_first(self):
        path = os.path.join(self.kb_dir, "architecture.md")
        content = "# Architecture\n\n## System Overview\n" + "core\n" * 100
        for day in ("2026-03-01", "2026-01-01", "2026-02-01", "2026-04-01", "2026-05-01"):
            content += "## Update\n<!-- created: %s -->\n" % day + "x\n" * 100
        with open(path, "w") as f:
            f.write(content)
        result = archive_file(path, threshold=500, keep_sections=3)
        self.assertEqual(result["archived_sections"], 2)
        with open(path) as f:
            remaining = f.read()
        self.assertIn("## System Overview", remaining)
        self.assertNotIn("2026-01-01", remaining)
        self.assertNotIn("2026-02-01", remaining)
        self.assertIn("2026-03-01", remaining)

    def test_heading_inside_code_fence_is_not_a_section(self):
        path = os.path.join(self.kb_dir, "decisions.md")
        content = "# D\n\n## ADR-1\n```md\n## not a heading\n```\n" + "x\n" * 600
        with open(path, "w") as f:
            f.write(content)
        # one real section only -> nothing to archive
        self.assertIsNone(archive_file(path, threshold=500, keep_sections=1))


class TestCheckAllKBFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.kb_dir = os.path.join(self.tmpdir.name, "knowledge")
        os.makedirs(self.kb_dir)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_check_all_mixed(self):
        # One big file, one small file
        big_path = os.path.join(self.kb_dir, "decisions.md")
        content = "# Decisions\n\n"
        for i in range(10):
            content += f"## ADR-{i + 1}\n" + "Content\n" * 60 + "\n"
        with open(big_path, "w") as f:
            f.write(content)

        small_path = os.path.join(self.kb_dir, "runbook.md")
        with open(small_path, "w") as f:
            f.write("## Deploy\nRun deploy.\n")

        results = check_all_kb_files(self.kb_dir, threshold=500)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_file"], "decisions.md")

    def test_nonexistent_dir(self):
        results = check_all_kb_files("/nonexistent/dir")
        self.assertEqual(len(results), 0)


class TestGraphMetadataInIndex(unittest.TestCase):
    """Test that build_index / write_index includes graph metadata when available."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cwd = self.tmpdir.name
        self.kb_dir = os.path.join(self.cwd, ".hody", "knowledge")
        os.makedirs(self.kb_dir)
        with open(os.path.join(self.kb_dir, "decisions.md"), "w") as f:
            f.write("---\ntags: [test]\n---\n\n## ADR-1\nTest.\n")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _create_graph(self, nodes, edges):
        graph_dir = os.path.join(self.cwd, "graphify-out")
        os.makedirs(graph_dir, exist_ok=True)
        data = {"nodes": nodes, "links": edges}
        with open(os.path.join(graph_dir, "graph.json"), "w") as f:
            json.dump(data, f)

    def test_no_graph_no_metadata(self):
        index = build_index(self.kb_dir, cwd=self.cwd)
        self.assertNotIn("graph_metadata", index)

    def test_graph_present_includes_metadata(self):
        self._create_graph(
            [
                {"id": "a", "source_file": "src/a.py"},
                {"id": "b", "source_file": "src/b.py"},
            ],
            [{"source": "a", "target": "b"}],
        )
        index = build_index(self.kb_dir, cwd=self.cwd)
        self.assertIn("graph_metadata", index)
        gm = index["graph_metadata"]
        self.assertEqual(gm["node_count"], 2)
        self.assertEqual(gm["edge_count"], 1)
        self.assertIn("src", gm["modules"])

    def test_god_nodes_sorted_by_degree(self):
        nodes = [
            {"id": "a", "source_file": "a.py"},
            {"id": "b", "source_file": "b.py"},
            {"id": "c", "source_file": "c.py"},
        ]
        edges = [
            {"source": "a", "target": "b"},
            {"source": "c", "target": "b"},
            {"source": "a", "target": "c"},
        ]
        self._create_graph(nodes, edges)
        index = build_index(self.kb_dir, cwd=self.cwd)
        gods = index["graph_metadata"]["god_nodes"]
        self.assertEqual(gods[0]["id"], "b")
        self.assertEqual(gods[0]["in_degree"], 2)

    def test_empty_graph_no_metadata(self):
        self._create_graph([], [])
        index = build_index(self.kb_dir, cwd=self.cwd)
        self.assertNotIn("graph_metadata", index)

    def test_write_index_includes_graph(self):
        self._create_graph(
            [{"id": "x", "source_file": "x.py"}],
            [],
        )
        index = write_index(self.kb_dir, cwd=self.cwd)
        self.assertIn("graph_metadata", index)
        loaded = load_index(self.kb_dir)
        self.assertIn("graph_metadata", loaded)
        self.assertEqual(loaded["graph_metadata"]["node_count"], 1)


if __name__ == "__main__":
    unittest.main()
