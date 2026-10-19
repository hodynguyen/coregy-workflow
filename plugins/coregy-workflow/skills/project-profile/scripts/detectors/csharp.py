"""Detect C#/.NET project from .csproj, .sln, or global.json."""
import os

from detectors.utils import read_lines


def detect_csharp(cwd):
    """Detect C#/.NET project from .csproj, .sln, or global.json."""
    content = ""

    # Check for .sln files
    sln_files = [f for f in os.listdir(cwd) if f.endswith(".sln")] if os.path.isdir(cwd) else []
    # Check for .csproj files
    csproj_files = [f for f in os.listdir(cwd) if f.endswith(".csproj")] if os.path.isdir(cwd) else []

    for f in csproj_files:
        content += read_lines(os.path.join(cwd, f))

    global_json = read_lines(os.path.join(cwd, "global.json"))
    content += global_json

    if not content and not sln_files and not csproj_files:
        return None, None

    be = {"language": "csharp"}
    testing = None

    if "microsoft.aspnetcore" in content or "asp.net" in content or "webapplication" in content:
        be["framework"] = "aspnet-core"
    elif "microsoft.net.sdk.blazor" in content or "blazor" in content:
        be["framework"] = "blazor"

    if "microsoft.entityframeworkcore" in content or "entityframework" in content:
        be["orm"] = "entity-framework"
    elif "dapper" in content:
        be["orm"] = "dapper"

    if "xunit" in content:
        testing = "xunit"
    elif "nunit" in content:
        testing = "nunit"
    elif "mstest" in content:
        testing = "mstest"

    # If we found .csproj or .sln but no framework, still return as C# project
    if not be.get("framework") and (sln_files or csproj_files):
        be["framework"] = "dotnet"

    return be if be.get("framework") else None, testing
