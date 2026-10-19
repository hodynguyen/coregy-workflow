"""Detect monorepo structure from config files."""
import glob as glob_mod
import os

from detectors.utils import read_json, read_lines


def detect_monorepo(cwd):
    """Detect monorepo structure from config files."""
    monorepo = {}

    if os.path.isfile(os.path.join(cwd, "nx.json")):
        monorepo["tool"] = "nx"
    elif os.path.isfile(os.path.join(cwd, "turbo.json")):
        monorepo["tool"] = "turborepo"
    elif os.path.isfile(os.path.join(cwd, "lerna.json")):
        monorepo["tool"] = "lerna"
    elif os.path.isfile(os.path.join(cwd, "pnpm-workspace.yaml")):
        monorepo["tool"] = "pnpm-workspaces"

    if not monorepo:
        return None

    # Try to find workspace packages
    workspaces = []
    pkg = read_json(os.path.join(cwd, "package.json"))
    workspace_globs = []

    if pkg and "workspaces" in pkg:
        ws = pkg["workspaces"]
        if isinstance(ws, list):
            workspace_globs = ws
        elif isinstance(ws, dict) and "packages" in ws:
            workspace_globs = ws["packages"]

    # For pnpm, try to read pnpm-workspace.yaml
    if monorepo.get("tool") == "pnpm-workspaces":
        pnpm_content = read_lines(os.path.join(cwd, "pnpm-workspace.yaml"))
        # Simple parse: extract paths after "- " under "packages:"
        in_packages = False
        for line in pnpm_content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("packages:"):
                in_packages = True
                continue
            if in_packages and stripped.startswith("- "):
                path = stripped[2:].strip().strip("'\"")
                workspace_globs.append(path)
            elif in_packages and stripped and not stripped.startswith("-") and not stripped.startswith("#"):
                in_packages = False

    # Resolve workspace globs to actual directories
    for pattern in workspace_globs:
        matched = glob_mod.glob(os.path.join(cwd, pattern))
        for match_path in matched:
            if os.path.isdir(match_path):
                rel_path = os.path.relpath(match_path, cwd)
                # Quick detect what's in the workspace
                ws_profile = build_workspace_profile(match_path)
                if ws_profile:
                    ws_profile["path"] = rel_path
                    workspaces.append(ws_profile)

    if workspaces:
        monorepo["workspaces"] = workspaces

    return monorepo


def build_workspace_profile(ws_path):
    """Build a minimal profile for a workspace sub-project."""
    result = {}

    # Check for package.json
    pkg = read_json(os.path.join(ws_path, "package.json"))
    if pkg:
        deps = {}
        deps.update(pkg.get("dependencies", {}))
        dev_deps = pkg.get("devDependencies", {})
        lang = "typescript" if "typescript" in dev_deps or "typescript" in deps else "javascript"
        result["language"] = lang

        # Detect framework
        if "react" in deps or "react-dom" in deps:
            result["framework"] = "react"
        elif "vue" in deps:
            result["framework"] = "vue"
        elif "next" in deps:
            result["framework"] = "next"
        elif "@angular/core" in deps:
            result["framework"] = "angular"
        elif "express" in deps:
            result["framework"] = "express"
        elif "fastify" in deps:
            result["framework"] = "fastify"
        elif "@nestjs/core" in deps:
            result["framework"] = "nest"

        return result if result.get("framework") else (result if result.get("language") else None)

    # Check for go.mod
    gomod = read_lines(os.path.join(ws_path, "go.mod"))
    if gomod:
        result["language"] = "go"
        if "github.com/gin-gonic/gin" in gomod:
            result["framework"] = "gin"
        elif "github.com/labstack/echo" in gomod:
            result["framework"] = "echo"
        return result

    # Check for requirements.txt / pyproject.toml
    py_content = read_lines(os.path.join(ws_path, "requirements.txt"))
    py_content += read_lines(os.path.join(ws_path, "pyproject.toml"))
    if py_content:
        result["language"] = "python"
        if "django" in py_content:
            result["framework"] = "django"
        elif "fastapi" in py_content:
            result["framework"] = "fastapi"
        elif "flask" in py_content:
            result["framework"] = "flask"
        return result

    return None
