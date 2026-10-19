"""Tests for YAML serializer."""
import os
import sys
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

from detectors.serializer import to_yaml


class TestToYaml(unittest.TestCase):
    def test_simple_dict(self):
        result = to_yaml({"key": "value"})
        self.assertEqual(result, "key: value")

    def test_nested_dict(self):
        result = to_yaml({"parent": {"child": "value"}})
        self.assertIn("parent:", result)
        self.assertIn("  child: value", result)

    def test_boolean(self):
        result = to_yaml({"flag": True})
        self.assertEqual(result, "flag: true")

    def test_list(self):
        result = to_yaml({"items": [{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]})
        self.assertIn("items:", result)
        self.assertIn("  - name: a", result)
        self.assertIn("    value: 1", result)


if __name__ == "__main__":
    unittest.main()
