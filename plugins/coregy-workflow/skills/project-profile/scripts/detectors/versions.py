"""Semver parsing and version conflict detection."""
import re


# Semver regex: major.minor.patch with optional pre-release
_SEMVER_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9.]+))?(?:\+[a-zA-Z0-9.]+)?$"
)


def parse_semver(version_str):
    """Parse a semver string into (major, minor, patch) tuple.

    Returns None if not a valid semver.
    """
    if not version_str:
        return None
    m = _SEMVER_RE.match(version_str.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_major_mismatch(installed, required):
    """Check if two versions have different major versions.

    Args:
        installed: version string (e.g. "17.0.2")
        required: version string or range (e.g. "18.0.0", "^18.0.0")

    Returns True if major versions differ.
    """
    # Strip range prefixes
    required_clean = required.lstrip("^~>=<! ")
    v1 = parse_semver(installed)
    v2 = parse_semver(required_clean)
    if v1 is None or v2 is None:
        return False
    return v1[0] != v2[0]


def is_outdated(current, latest):
    """Check if current version is behind latest.

    Returns (is_outdated, is_breaking) tuple.
    - is_outdated: True if latest > current
    - is_breaking: True if major version changed
    """
    v_cur = parse_semver(current)
    v_lat = parse_semver(latest)
    if v_cur is None or v_lat is None:
        return False, False

    outdated = v_lat > v_cur
    breaking = v_lat[0] > v_cur[0] if outdated else False
    return outdated, breaking


def classify_severity(vuln_severity):
    """Normalize vulnerability severity to one of: critical, high, moderate, low.

    Handles npm audit, pip audit, cargo audit severity labels.
    """
    if not vuln_severity:
        return "low"
    s = vuln_severity.lower().strip()
    if s in ("critical",):
        return "critical"
    if s in ("high",):
        return "high"
    if s in ("moderate", "medium", "warning"):
        return "moderate"
    return "low"
