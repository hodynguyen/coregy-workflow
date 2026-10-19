"""
Deep stack analysis — run package manager commands to get dependency trees,
version conflicts, outdated packages, and security vulnerabilities.

This is opt-in (--deep flag) because it runs shell commands and is slower
than the regex-based detection in other detector modules.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from detectors.versions import parse_semver, is_major_mismatch, is_outdated, classify_severity


def _run_cmd(cmd, cwd, timeout=30):
    """Run a shell command and return (stdout, success)."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout, result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return "", False


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _analyze_npm(cwd):
    """Analyze Node.js project with npm."""
    result = {"dependency_count": 0, "direct": 0, "transitive": 0,
              "conflicts": [], "outdated": [], "security": []}

    # npm ls --json --all for dependency tree
    stdout, ok = _run_cmd(["npm", "ls", "--json", "--all"], cwd, timeout=60)
    if ok and stdout:
        try:
            tree = json.loads(stdout)
            deps = tree.get("dependencies", {})
            result["direct"] = len(deps)
            # Count transitive
            total = _count_deps(deps)
            result["dependency_count"] = total
            result["transitive"] = total - result["direct"]
        except (json.JSONDecodeError, KeyError):
            pass

    # npm outdated --json
    stdout, _ = _run_cmd(["npm", "outdated", "--json"], cwd, timeout=30)
    if stdout:
        try:
            outdated = json.loads(stdout)
            for pkg, info in outdated.items():
                current = info.get("current", "")
                latest = info.get("latest", "")
                if current and latest:
                    out, breaking = is_outdated(current, latest)
                    if out:
                        result["outdated"].append({
                            "package": pkg,
                            "current": current,
                            "latest": latest,
                            "breaking": breaking,
                        })
        except (json.JSONDecodeError, KeyError):
            pass

    # npm audit --json
    stdout, _ = _run_cmd(["npm", "audit", "--json"], cwd, timeout=30)
    if stdout:
        try:
            audit = json.loads(stdout)
            vulns = audit.get("vulnerabilities", {})
            for pkg, info in vulns.items():
                result["security"].append({
                    "package": pkg,
                    "vulnerability": info.get("via", [{}])[0].get("url", "") if isinstance(info.get("via", [{}])[0], dict) else "",
                    "severity": classify_severity(info.get("severity", "")),
                })
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            pass

    return result


def _count_deps(deps_dict):
    """Recursively count all dependencies."""
    count = 0
    for pkg, info in deps_dict.items():
        count += 1
        if isinstance(info, dict) and "dependencies" in info:
            count += _count_deps(info["dependencies"])
    return count


def _analyze_pip(cwd):
    """Analyze Python project with pip."""
    result = {"dependency_count": 0, "direct": 0, "transitive": 0,
              "conflicts": [], "outdated": [], "security": []}

    # pip list --format=json
    stdout, ok = _run_cmd([sys.executable, "-m", "pip", "list", "--format=json"], cwd, timeout=30)
    if ok and stdout:
        try:
            pkgs = json.loads(stdout)
            result["dependency_count"] = len(pkgs)
        except json.JSONDecodeError:
            pass

    # Count direct deps from requirements.txt
    req_path = os.path.join(cwd, "requirements.txt")
    if os.path.isfile(req_path):
        with open(req_path, "r") as f:
            direct = [l.strip() for l in f if l.strip() and not l.startswith("#") and not l.startswith("-")]
        result["direct"] = len(direct)
        result["transitive"] = max(0, result["dependency_count"] - result["direct"])

    # pip list --outdated --format=json
    stdout, ok = _run_cmd(
        [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
        cwd, timeout=30
    )
    if ok and stdout:
        try:
            outdated = json.loads(stdout)
            for pkg in outdated:
                current = pkg.get("version", "")
                latest = pkg.get("latest_version", "")
                if current and latest:
                    out, breaking = is_outdated(current, latest)
                    if out:
                        result["outdated"].append({
                            "package": pkg.get("name", ""),
                            "current": current,
                            "latest": latest,
                            "breaking": breaking,
                        })
        except json.JSONDecodeError:
            pass

    # pip audit (if available)
    stdout, ok = _run_cmd([sys.executable, "-m", "pip_audit", "--format=json"], cwd, timeout=30)
    if ok and stdout:
        try:
            audit = json.loads(stdout)
            for vuln in audit.get("dependencies", []):
                for v in vuln.get("vulns", []):
                    result["security"].append({
                        "package": vuln.get("name", ""),
                        "vulnerability": v.get("id", ""),
                        "severity": classify_severity(v.get("fix_versions", [""])[0] if v.get("fix_versions") else ""),
                    })
        except (json.JSONDecodeError, KeyError):
            pass

    return result


def _analyze_go(cwd):
    """Analyze Go project."""
    result = {"dependency_count": 0, "direct": 0, "transitive": 0,
              "conflicts": [], "outdated": [], "security": []}

    # go list -m all
    stdout, ok = _run_cmd(["go", "list", "-m", "all"], cwd, timeout=30)
    if ok and stdout:
        lines = [l for l in stdout.strip().splitlines() if l.strip()]
        # First line is the module itself
        result["dependency_count"] = max(0, len(lines) - 1)

    # Count direct from go.mod
    gomod_path = os.path.join(cwd, "go.mod")
    if os.path.isfile(gomod_path):
        with open(gomod_path, "r") as f:
            content = f.read()
        # Count require lines (not indirect)
        direct = 0
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("require") and not line.startswith("require ("):
                direct += 1
            elif line and not line.startswith("//") and not line.startswith("module") \
                    and not line.startswith("go ") and not line.startswith("require") \
                    and not line in (")", "("):
                if "// indirect" not in line:
                    direct += 1
        result["direct"] = direct
        result["transitive"] = max(0, result["dependency_count"] - result["direct"])

    # govulncheck (if available)
    stdout, ok = _run_cmd(["govulncheck", "-json", "./..."], cwd, timeout=60)
    if ok and stdout:
        try:
            for line in stdout.splitlines():
                if line.strip():
                    entry = json.loads(line)
                    if "osv" in entry:
                        osv = entry["osv"]
                        result["security"].append({
                            "package": osv.get("affected", [{}])[0].get("package", {}).get("name", ""),
                            "vulnerability": osv.get("id", ""),
                            "severity": classify_severity(
                                osv.get("database_specific", {}).get("severity", "")
                            ),
                        })
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

    return result


def _analyze_cargo(cwd):
    """Analyze Rust project."""
    result = {"dependency_count": 0, "direct": 0, "transitive": 0,
              "conflicts": [], "outdated": [], "security": []}

    # cargo metadata
    stdout, ok = _run_cmd(["cargo", "metadata", "--format-version=1"], cwd, timeout=30)
    if ok and stdout:
        try:
            meta = json.loads(stdout)
            packages = meta.get("packages", [])
            result["dependency_count"] = len(packages)
            # Root package's direct deps
            resolve = meta.get("resolve", {})
            root_id = resolve.get("root")
            if root_id:
                for node in resolve.get("nodes", []):
                    if node.get("id") == root_id:
                        result["direct"] = len(node.get("deps", []))
                        break
            result["transitive"] = max(0, result["dependency_count"] - result["direct"])
        except (json.JSONDecodeError, KeyError):
            pass

    # cargo audit --json (if available)
    stdout, ok = _run_cmd(["cargo", "audit", "--json"], cwd, timeout=30)
    if ok and stdout:
        try:
            audit = json.loads(stdout)
            for vuln in audit.get("vulnerabilities", {}).get("list", []):
                advisory = vuln.get("advisory", {})
                result["security"].append({
                    "package": advisory.get("package", ""),
                    "vulnerability": advisory.get("id", ""),
                    "severity": classify_severity(advisory.get("cvss", "")),
                })
        except (json.JSONDecodeError, KeyError):
            pass

    return result


def run_deep_analysis(cwd, profile):
    """Run deep analysis based on detected stack.

    Args:
        cwd: Project root directory.
        profile: Existing profile dict (from build_profile).

    Returns:
        Dict with deep_analysis results, or None if no analyzable stack found.
    """
    result = None

    # Determine which analyzer to use
    be_lang = profile.get("backend", {}).get("language", "")
    fe_framework = profile.get("frontend", {}).get("framework", "")

    if os.path.isfile(os.path.join(cwd, "package.json")):
        result = _analyze_npm(cwd)
    elif be_lang == "python" or os.path.isfile(os.path.join(cwd, "requirements.txt")):
        result = _analyze_pip(cwd)
    elif be_lang == "go" or os.path.isfile(os.path.join(cwd, "go.mod")):
        result = _analyze_go(cwd)
    elif be_lang == "rust" or os.path.isfile(os.path.join(cwd, "Cargo.toml")):
        result = _analyze_cargo(cwd)

    if result:
        result["last_run"] = _now()

    return result
