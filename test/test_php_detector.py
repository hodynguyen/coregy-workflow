"""Tests for PHP detector."""
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

from detectors.profile import build_profile


class TestPHPProject(unittest.TestCase):
    def test_laravel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            composer = {
                "require": {"laravel/framework": "^10.0"},
                "require-dev": {"phpunit/phpunit": "^10.0"},
            }
            with open(os.path.join(tmpdir, "composer.json"), "w") as f:
                json.dump(composer, f)
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "backend")
            self.assertEqual(profile["backend"]["language"], "php")
            self.assertEqual(profile["backend"]["framework"], "laravel")
            self.assertEqual(profile["backend"]["orm"], "eloquent")
            self.assertEqual(profile["backend"]["testing"], "phpunit")

    def test_symfony(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            composer = {
                "require": {"symfony/framework-bundle": "^6.0", "doctrine/orm": "^2.0"},
                "require-dev": {"pestphp/pest": "^2.0"},
            }
            with open(os.path.join(tmpdir, "composer.json"), "w") as f:
                json.dump(composer, f)
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["framework"], "symfony")
            self.assertEqual(profile["backend"]["orm"], "doctrine")
            self.assertEqual(profile["backend"]["testing"], "pest")

    def test_magento(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            composer = {"require": {"magento/product-community-edition": "2.4.6"}}
            with open(os.path.join(tmpdir, "composer.json"), "w") as f:
                json.dump(composer, f)
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["framework"], "magento")


if __name__ == "__main__":
    unittest.main()
