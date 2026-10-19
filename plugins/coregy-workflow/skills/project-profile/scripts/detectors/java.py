"""Detect Java project from pom.xml or build.gradle."""
import os

from detectors.utils import read_lines


def detect_java(cwd):
    """Detect Java project from pom.xml or build.gradle."""
    content = ""
    build_tool = None

    pom_content = read_lines(os.path.join(cwd, "pom.xml"))
    if pom_content:
        content = pom_content
        build_tool = "maven"

    gradle_content = read_lines(os.path.join(cwd, "build.gradle"))
    if not gradle_content:
        gradle_content = read_lines(os.path.join(cwd, "build.gradle.kts"))
    if gradle_content:
        content += gradle_content
        build_tool = "gradle"

    if not content:
        return None, None

    be = {"language": "java", "build": build_tool}

    if "spring-boot" in content or "org.springframework.boot" in content:
        be["framework"] = "spring-boot"
    elif "quarkus" in content or "io.quarkus" in content:
        be["framework"] = "quarkus"
    elif "micronaut" in content or "io.micronaut" in content:
        be["framework"] = "micronaut"

    if "kotlin" in content:
        be["language"] = "kotlin"

    return be if be.get("framework") else None, "junit"
