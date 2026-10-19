#!/usr/bin/env python3
"""
SessionStart hook: reads .hody/profile.yaml and injects project context
into the system message so all agents know the current tech stack.

Auto-refresh: if any config file is newer than profile.yaml, re-runs
detect_stack.py before injecting context.
"""
import json
import subprocess
import sys
import os


# Config files that trigger a profile refresh when modified
CONFIG_FILES = [
    "package.json",
    "go.mod",
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "setup.py",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
    "composer.json",
    "nx.json",
    "turbo.json",
    "lerna.json",
    "pnpm-workspace.yaml",
    "global.json",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".gitlab-ci.yml",
    "Jenkinsfile",
]


def is_profile_stale(cwd, profile_path):
    """Check if any config file is newer than profile.yaml."""
    try:
        profile_mtime = os.path.getmtime(profile_path)
    except OSError:
        return False

    for fname in CONFIG_FILES:
        fpath = os.path.join(cwd, fname)
        try:
            if os.path.getmtime(fpath) > profile_mtime:
                return True
        except OSError:
            continue

    # Check for .csproj and .sln files (glob pattern)
    try:
        for f in os.listdir(cwd):
            if f.endswith((".csproj", ".sln", ".tf")):
                if os.path.getmtime(os.path.join(cwd, f)) > profile_mtime:
                    return True
    except OSError:
        pass

    # Check .github/workflows/ directory
    workflows_dir = os.path.join(cwd, ".github", "workflows")
    try:
        if os.path.isdir(workflows_dir):
            for f in os.listdir(workflows_dir):
                fpath = os.path.join(workflows_dir, f)
                if os.path.getmtime(fpath) > profile_mtime:
                    return True
    except OSError:
        pass

    return False


def refresh_profile(cwd):
    """Re-run detect_stack.py to update profile.yaml."""
    # Derive detect_stack.py path from this script's location
    hook_dir = os.path.dirname(os.path.abspath(__file__))
    plugin_root = os.path.dirname(hook_dir)
    detect_script = os.path.join(
        plugin_root, "skills", "project-profile", "scripts", "detect_stack.py"
    )

    if not os.path.isfile(detect_script):
        return False

    try:
        subprocess.run(
            [sys.executable, detect_script, "--cwd", cwd],
            timeout=15,
            capture_output=True,
        )
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False


def main():
    try:
        input_data = json.load(sys.stdin)
        cwd = input_data.get("cwd", os.getcwd())

        profile_path = os.path.join(cwd, ".hody", "profile.yaml")
        if not os.path.isfile(profile_path):
            print("{}")
            sys.exit(0)

        # Auto-refresh if config files changed (skip with HODY_SKIP_REFRESH=1)
        if not os.environ.get("HODY_SKIP_REFRESH"):
            if is_profile_stale(cwd, profile_path):
                refresh_profile(cwd)

        with open(profile_path, "r") as f:
            profile_content = f.read()

        # Extract key info for a concise summary
        lines = profile_content.strip().splitlines()
        summary_parts = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("name:"):
                summary_parts.append(stripped)
            elif stripped.startswith("framework:"):
                summary_parts.append(stripped)
            elif stripped.startswith("language:"):
                summary_parts.append(stripped)
            elif stripped.startswith("database:"):
                summary_parts.append(stripped)
            elif stripped.startswith("ci:"):
                summary_parts.append(stripped)

        summary = " | ".join(summary_parts) if summary_parts else "profile loaded"

        system_msg = f"[Hody Workflow] Project: {summary}. Full profile at .hody/profile.yaml"

        # Inject active workflow state if present
        state_path = os.path.join(cwd, ".hody", "state.json")
        if os.path.isfile(state_path):
            try:
                with open(state_path, "r") as sf:
                    state = json.load(sf)
                if state.get("status") == "in_progress":
                    feature = state.get("feature", "unknown")
                    spec_confirmed = state.get("spec_confirmed", False)
                    spec_status = "spec confirmed" if spec_confirmed else "spec pending"
                    exec_mode = state.get("execution_mode", "guided")

                    # Find next agent
                    next_info = None
                    for phase in state.get("phase_order", []):
                        p = state.get("phases", {}).get(phase, {})
                        for agent in p.get("agents", []):
                            if (agent not in p.get("completed", [])
                                    and agent not in p.get("skipped", [])):
                                next_info = (phase, agent)
                                break
                        if next_info:
                            break

                    if not spec_confirmed:
                        system_msg += (
                            f" | Active workflow: '{feature}'"
                            f" — {spec_status}, discovery incomplete"
                            f" (mode: {exec_mode})"
                            f". Use /hody-workflow:resume to continue discovery."
                        )
                    elif next_info:
                        resume_hint = (
                            "will pause between agents"
                            if exec_mode == "manual"
                            else "auto-run remaining agents"
                        )
                        system_msg += (
                            f" | Active workflow: '{feature}'"
                            f" — {spec_status}, next: {next_info[1]}"
                            f" ({next_info[0]} phase, mode: {exec_mode})"
                            f". Use /hody-workflow:resume to {resume_hint}."
                        )
                    else:
                        system_msg += (
                            f" | Active workflow: '{feature}'"
                            f" — all agents done, ready to complete."
                        )
            except (json.JSONDecodeError, KeyError):
                pass  # Don't block on corrupt state file

        # Inject tracker context if tracker.db exists
        tracker_db = os.path.join(cwd, ".hody", "tracker.db")
        if os.path.isfile(tracker_db):
            try:
                hook_dir = os.path.dirname(os.path.abspath(__file__))
                plugin_root = os.path.dirname(hook_dir)
                scripts_dir = os.path.join(
                    plugin_root, "skills", "project-profile", "scripts"
                )
                sys.path.insert(0, scripts_dir)
                from tracker_awareness import get_session_context, format_context_for_hook

                context = get_session_context(cwd)
                tracker_msg = format_context_for_hook(context)
                if tracker_msg:
                    system_msg += " | " + tracker_msg
            except Exception:
                pass  # Don't block session on tracker error

        # Inject Graphify knowledge graph summary if available
        graph_path = os.path.join(cwd, "graphify-out", "graph.json")
        if os.path.isfile(graph_path):
            try:
                graph_size = os.path.getsize(graph_path)
                if graph_size <= 10 * 1024 * 1024:  # Skip if > 10 MB
                    with open(graph_path, "r") as gf:
                        graph_data = json.load(gf)
                    node_count = len(graph_data.get("nodes", []))
                    link_key = "links" if "links" in graph_data else "edges"
                    edge_count = len(graph_data.get(link_key, []))
                    if node_count > 0:
                        system_msg += (
                            f" | Graphify: {node_count} nodes, {edge_count} edges"
                            f" in graphify-out/graph.json."
                            f" Use Graphify MCP tools (query_graph, get_neighbors,"
                            f" god_nodes, shortest_path) for structural code queries."
                        )
            except (json.JSONDecodeError, OSError, KeyError):
                pass  # Don't block session on graph read error

        # Inject project rules summary if rules.yaml exists
        rules_path = os.path.join(cwd, ".hody", "rules.yaml")
        if os.path.isfile(rules_path):
            try:
                hook_dir = os.path.dirname(os.path.abspath(__file__))
                plugin_root = os.path.dirname(hook_dir)
                scripts_dir = os.path.join(
                    plugin_root, "skills", "project-profile", "scripts"
                )
                if scripts_dir not in sys.path:
                    sys.path.insert(0, scripts_dir)
                from rules import load_rules, summarize_rules

                parsed = load_rules(cwd)
                if parsed:
                    rules_summary = summarize_rules(parsed)
                    if rules_summary:
                        system_msg += " | " + rules_summary
            except Exception:
                pass  # Don't block session on rules error

        # additionalContext is what reaches the model; a top-level
        # systemMessage is only a notice shown to the user, so emitting the
        # context there (as this hook did before v0.13.1) never informed any
        # agent of the stack, workflow, tracker or rules.
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": system_msg,
            }
        }
        print(json.dumps(output))
        sys.exit(0)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(0)  # Don't block session on hook error


if __name__ == "__main__":
    main()
