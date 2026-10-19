"""Tests for Java detector."""
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


class TestJavaProject(unittest.TestCase):
    def test_spring_boot_maven(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "pom.xml"), "w") as f:
                f.write('<project>\n<parent>\n<artifactId>spring-boot-starter-parent</artifactId>\n</parent>\n</project>\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "backend")
            self.assertEqual(profile["backend"]["language"], "java")
            self.assertEqual(profile["backend"]["framework"], "spring-boot")
            self.assertEqual(profile["backend"]["build"], "maven")
            self.assertEqual(profile["backend"]["testing"], "junit")

    def test_spring_boot_gradle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "build.gradle"), "w") as f:
                f.write("plugins {\n  id 'org.springframework.boot' version '3.2.0'\n}\n")
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["framework"], "spring-boot")
            self.assertEqual(profile["backend"]["build"], "gradle")

    def test_kotlin_spring(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "build.gradle.kts"), "w") as f:
                f.write('plugins {\n  kotlin("jvm")\n  id("org.springframework.boot")\n}\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["language"], "kotlin")
            self.assertEqual(profile["backend"]["framework"], "spring-boot")

    def test_quarkus(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "pom.xml"), "w") as f:
                f.write('<project>\n<dependency>\n<groupId>io.quarkus</groupId>\n</dependency>\n</project>\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["framework"], "quarkus")


if __name__ == "__main__":
    unittest.main()
