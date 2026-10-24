#!/usr/bin/env python3
"""
SubagentStop hook: records the tokens the finished subagent spent.

Reads the subagent's own transcript (`agent_transcript_path`, or derived from
the session transcript + `agent_id`), sums its API usage and stores it in
`.coregy/metering.json`, bound to the workflow agent run it belongs to. See
`skills/project-profile/scripts/metering.py`.

Skipped when .coregy/ does not exist or COREGY_METERING=0. Never blocks the
agent and prints nothing: errors are swallowed.
"""
import json
import os
import sys


def load_metering(plugin_root):
    scripts_dir = os.path.join(plugin_root, "skills", "project-profile", "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import metering
    return metering


def metering_enabled():
    raw = (os.environ.get("COREGY_METERING")
           or os.environ.get("HODY_METERING") or "1").strip().lower()
    return raw not in ("0", "off", "false", "no")


def resolve_transcript(metering, payload):
    path = payload.get("agent_transcript_path")
    if path and os.path.isfile(path):
        return path
    path = metering.agent_transcript_path(
        payload.get("transcript_path"), payload.get("agent_id"), payload.get("session_id"))
    return path if path and os.path.isfile(path) else None


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return
    if not isinstance(payload, dict) or not metering_enabled():
        return
    cwd = payload.get("cwd") or os.getcwd()
    if not os.path.isdir(os.path.join(cwd, ".coregy")):
        return
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    metering = load_metering(plugin_root)
    transcript = resolve_transcript(metering, payload)
    if transcript:
        metering.record(cwd, transcript, payload.get("agent_id"), payload.get("agent_type"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
