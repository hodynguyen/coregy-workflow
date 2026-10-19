"""Detect project conventions."""
import os
import glob as globmod

from detectors.utils import read_json


def detect_conventions(cwd):
    """Detect project conventions."""
    conventions = {}

    if os.path.isfile(os.path.join(cwd, ".github", "PULL_REQUEST_TEMPLATE.md")):
        conventions["pr_template"] = True

    # Commit style
    commit_style = _detect_commit_style(cwd)
    if commit_style:
        conventions["commit_style"] = commit_style

    # Git branch strategy
    git_branch = _detect_git_branch(cwd, commit_style)
    if git_branch:
        conventions["git_branch"] = git_branch

    return conventions if conventions else None


def _detect_commit_style(cwd):
    """Detect commit message convention."""
    # Check for commitlint config files
    commitlint_patterns = [
        ".commitlintrc",
        ".commitlintrc.*",
        "commitlint.config.*",
    ]
    for pattern in commitlint_patterns:
        if globmod.glob(os.path.join(cwd, pattern)):
            return "conventional"

    # Check for commitizen
    if os.path.isfile(os.path.join(cwd, ".czrc")):
        return "commitizen"

    pkg = read_json(os.path.join(cwd, "package.json"))
    if pkg and ("czConfig" in pkg or "config" in pkg and isinstance(pkg.get("config"), dict) and "commitizen" in pkg["config"]):
        return "commitizen"

    return None


def _detect_git_branch(cwd, commit_style):
    """Detect git branch strategy."""
    if os.path.isfile(os.path.join(cwd, ".gitflow")):
        return "gitflow"

    if os.path.isfile(os.path.join(cwd, "trunk.yaml")):
        return "trunk-based"

    if commit_style == "conventional":
        return "feature-branch"

    return None
