"""Tests for kb_sync.py script."""
import os
import sys
import tempfile
import unittest

# Add the script to path
SCRIPT_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "coregy-workflow",
    "skills",
    "knowledge-base",
    "scripts",
)
sys.path.insert(0, os.path.abspath(SCRIPT_DIR))

from kb_sync import validate_kb, sync_status, KB_FILES


class TestValidateKB(unittest.TestCase):
    def test_no_coregy_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            valid, msg = validate_kb(tmpdir)
            self.assertFalse(valid)
            self.assertIn("not found", msg)

    def test_empty_kb(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_path = os.path.join(tmpdir, ".coregy", "knowledge")
            os.makedirs(kb_path)
            valid, msg = validate_kb(tmpdir)
            self.assertFalse(valid)
            self.assertIn("empty", msg)

    def test_valid_kb(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_path = os.path.join(tmpdir, ".coregy", "knowledge")
            os.makedirs(kb_path)
            with open(os.path.join(kb_path, "architecture.md"), "w") as f:
                f.write("# Architecture\n")
            valid, msg = validate_kb(tmpdir)
            self.assertTrue(valid)
            self.assertIn("1", msg)

    def test_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_path = os.path.join(tmpdir, ".coregy", "knowledge")
            os.makedirs(kb_path)
            for fname in KB_FILES:
                with open(os.path.join(kb_path, fname), "w") as f:
                    f.write(f"# {fname}\n")
            valid, msg = validate_kb(tmpdir)
            self.assertTrue(valid)
            self.assertIn("6", msg)


class TestSyncStatus(unittest.TestCase):
    def test_no_kb(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = sync_status(tmpdir)
            self.assertIn("not found", result)

    def test_partial_kb(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_path = os.path.join(tmpdir, ".coregy", "knowledge")
            os.makedirs(kb_path)
            with open(os.path.join(kb_path, "architecture.md"), "w") as f:
                f.write("# Architecture\n\nSystem overview here.\n")
            result = sync_status(tmpdir)
            self.assertIn("architecture.md", result)
            self.assertIn("missing", result)  # Other files missing

    def test_full_kb(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_path = os.path.join(tmpdir, ".coregy", "knowledge")
            os.makedirs(kb_path)
            for fname in KB_FILES:
                with open(os.path.join(kb_path, fname), "w") as f:
                    f.write(f"# {fname}\nContent here.\n")
            result = sync_status(tmpdir)
            for fname in KB_FILES:
                self.assertIn(fname, result)
            self.assertNotIn("missing", result)


if __name__ == "__main__":
    unittest.main()
