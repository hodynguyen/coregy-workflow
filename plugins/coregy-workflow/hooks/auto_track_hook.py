#!/usr/bin/env python3
"""
UserPromptSubmit hook: detects task intent in user prompts and tracks it.

Default (silent): records the work in the tracker itself -- a new item for a
new task, a note on the active item for a continuation -- and tells Claude
which item it is and how to close it. The user is never asked.

COREGY_AUTO_TRACK:
  - unset / "1" / "silent": silent tracking (default)
  - "ask": legacy behaviour -- hint Claude to ask the user before tracking
  - "0" / "off": disabled

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


def _scripts_dir(plugin_root):
    return os.path.join(plugin_root, "skills", "project-profile", "scripts")


def load_auto_track(plugin_root):
    """Import the auto_track module from the plugin's scripts dir."""
    scripts_dir = _scripts_dir(plugin_root)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import auto_track
    return auto_track


def load_intent_detector(plugin_root):
    """Import detect_intent from the auto_track script."""
    return load_auto_track(plugin_root).detect_intent


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


def tracking_mode():
    raw = (os.environ.get("COREGY_AUTO_TRACK")
           or os.environ.get("HODY_AUTO_TRACK") or "silent").strip().lower()
    if raw in ("0", "off", "false", "no"):
        return "off"
    return "ask" if raw == "ask" else "silent"


def build_hint(result):
    """Format the legacy (COREGY_AUTO_TRACK=ask) hint for Claude."""
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
        mode = tracking_mode()
        if mode == "off":
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
        auto_track = load_auto_track(plugin_root)

        result = auto_track.detect_intent(prompt)
        if not result or result.get("confidence") == "low":
            sys.exit(0)

        if mode == "ask":
            context = build_hint(result)
        else:
            outcome = auto_track.track_prompt(cwd, prompt, result)
            tracker_cmd = "python3 %s" % os.path.join(
                _scripts_dir(plugin_root), "tracker.py")
            context = auto_track.build_tracking_note(outcome, tracker_cmd)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }
        print(json.dumps(output))
        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
