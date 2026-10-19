---
description: Re-detect project tech stack and update .coregy/profile.yaml. Use when dependencies or project structure have changed.
argument-hint: "[optional: e.g. '--deep' or 'focus on backend']"
---

# /coregy-workflow:refresh

Re-detect the project tech stack and update the existing profile.

## User Instructions

$ARGUMENTS

If the section above contains text, apply it to the refresh:
- "--deep" or "deep" → pass `--deep` flag to detect_stack.py for deep dependency analysis
- "--graph" or "graph" → rebuild the Graphify knowledge graph after profile refresh
- "focus on <area>" → emphasize that area in the output summary (backend/frontend/infra)
- "skip integrations" → preserve integrations section as-is without re-checking

If empty, run a standard refresh.

## Steps

1. **Re-detect tech stack**: Run the project-profile skill to re-scan the project and regenerate `.coregy/profile.yaml`

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/detect_stack.py --cwd .
```

If the user requests deep analysis (e.g., "refresh --deep", "deep analysis", "check dependencies"), add the `--deep` flag:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/detect_stack.py --cwd . --deep
```

The `--deep` flag runs actual package manager commands (`npm ls`, `npm audit`, `pip list`, `go list`, `cargo metadata`) to get:
- Dependency counts (direct + transitive)
- Outdated packages with breaking change detection
- Security vulnerabilities

This is slower than the default regex-only detection but provides much richer data.

2. **Rebuild knowledge graph (optional)**: If the user passes `--graph` (e.g., `/refresh --graph` or the $ARGUMENTS contain "graph"), rebuild the Graphify knowledge graph after profile detection:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/graphify_setup.py --cwd .
```

This re-runs the full Graphify setup. Graphify uses SHA256 file-content caching, so unchanged files are not re-parsed — only new or modified files are processed. After the script completes, tell the user to restart Claude Code if this is the first time building the graph (MCP server needs to be loaded).

Skip this step if the user did not request `--graph`.

3. **Show diff**: Compare the new profile with the previous one and highlight what changed

Read the current `.coregy/profile.yaml` before running detection, then compare with the new output. Show:
- New technologies detected
- Technologies no longer detected
- Framework or version changes

4. **Show summary**: Display the updated stack

## Output

After running, show the user:
- Updated project type and detected stack
- What changed since last detection (if anything)
- Graphify status: whether the knowledge graph was rebuilt (if `--graph` was used)
- Suggest running `/coregy-workflow:status` for a full overview

## Notes

- This command overwrites `.coregy/profile.yaml` with fresh detection results
- Knowledge base files are NOT modified — only the profile is updated
- Run this after adding/removing major dependencies, changing frameworks, or restructuring the project
- The profile is also regenerated when running `/coregy-workflow:init`
- Use `--deep` for dependency analysis — results are cached in profile.yaml under `deep_analysis`
- Deep analysis requires the relevant package manager CLI to be installed (npm, pip, go, cargo)
- Use `--graph` to rebuild the Graphify knowledge graph — useful after adding/removing files or restructuring modules
- `--deep` and `--graph` can be combined: `/refresh --deep --graph`
