#!/usr/bin/env python3
"""
UserPromptSubmit hook: detects task intent in user prompts and injects
a hint asking Claude to consider creating a tracker item.

Skipped automatically when:
  - COREGY_AUTO_TRACK=0 env var is set
  - .coregy/ directory does not exist (project not initialized)
  - .coregy/state.json shows an active workflow (start-feature handles tracking)
  - Detected confidence is "low"

Output: JSON with hookSpecificOutput.additionalContext for context injection.
Errors are swallowed silently — the hook never blocks user input.
"""
import json
import os
import sys


def load_intent_detector(plugin_root):
    """Import detect_intent from the auto_track script."""
    scripts_dir = os.path.join(
        plugin_root, "skills", "project-profile", "scripts"
    )
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from auto_track import detect_intent
    return detect_intent


def has_active_workflow(state_path):
    """Return True if .coregy/state.json shows an in-progress workflow."""
    if not os.path.isfile(state_path):
        return False
    try:
        with open(state_path) as f:
            state = json.load(f)
        return state.get("status") == "in_progress"
    except (json.JSONDecodeError, OSError):
        return False


def build_hint(result):
    """Format the additionalContext hint for Claude."""
    return (
        f"[Coregy Auto-track] Detected possible task intent in user prompt "
        f"({result['type']}/{result.get('subtype', 'general')}, "
        f"confidence: {result['confidence']}, verb: '{result['verb']}'). "
        f"If this is a substantive new task (not a one-line tweak, "
        f"clarification, or part of an ongoing discussion), briefly ask "
        f"the user whether to track it, then create via "
        f"`tracker.py create --type {result['type']} --title \"<title>\" "
        f"--tags <comma-separated>`. Skip if user is asking a question, "
        f"continuing prior work, or already inside an active workflow."
    )


def main():
    try:
        if (os.environ.get("COREGY_AUTO_TRACK") or os.environ.get("HODY_AUTO_TRACK")) == "0":
            sys.exit(0)

        input_data = json.load(sys.stdin)
        cwd = input_data.get("cwd", os.getcwd())
        prompt = input_data.get("prompt", "")

        coregy_dir = os.path.join(cwd, ".coregy")
        if not os.path.isdir(coregy_dir):
            sys.exit(0)

        if has_active_workflow(os.path.join(coregy_dir, "state.json")):
            sys.exit(0)

        hook_dir = os.path.dirname(os.path.abspath(__file__))
        plugin_root = os.path.dirname(hook_dir)
        detect_intent = load_intent_detector(plugin_root)

        result = detect_intent(prompt)
        if not result or result.get("confidence") == "low":
            sys.exit(0)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": build_hint(result),
            }
        }
        print(json.dumps(output))
        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
