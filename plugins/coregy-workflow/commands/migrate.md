---
description: Migrate a project that used the old Hody plugin (.hody/) to Coregy (.coregy/). Moves the data dir, rewrites path references, .gitignore and the enabledPlugins key.
argument-hint: "[optional: 'check' for a dry run]"
---

# /coregy-workflow:migrate

Move a project from the legacy **Hody** naming (plugin `hody-workflow`, data in `.hody/`) to **Coregy** (`coregy-workflow`, `.coregy/`).

The SessionStart hook already does this automatically when it finds `.hody/` and no `.coregy/`. Use this command to preview the change, to re-run it, or to see why it was skipped.

## User Instructions

$ARGUMENTS

- contains `check`, `dry run` or `preview` → run **check** only
- empty or anything else → run **check**, show the plan, then **run**

## Steps

1. **Preview**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/migrate.py check --cwd .
```

- `Nothing to migrate` → tell the user the project is already on Coregy (or never used Hody) and stop.
- `Cannot migrate` (exit 1) → both `.hody/` and `.coregy/` exist. Do NOT delete either. Show the user what each contains (`ls -la .hody .coregy`) and ask which one to keep; stop here.

2. **Apply** (skip if the user asked for a dry run):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/migrate.py run --cwd .
```

3. **Report** each line of the output, then the follow-ups that the script cannot do for the user:
   - Uninstall the old plugin so its hooks stop running: `/plugin uninstall hody-workflow@hody`
   - Rename legacy env vars (`HODY_USER`, `HODY_AUTO_TRACK`, `HODY_SKIP_QUALITY_GATE`, `HODY_SKIP_REFRESH`, `HODY_MCP_MODE`) to their `COREGY_*` names in shell profiles / CI. The old names still work as a fallback.
   - If the team synced the KB with `/coregy-workflow:sync` in git-branch mode, the old branch was `hody-knowledge`; the new default is `coregy-knowledge` (or pass `--branch hody-knowledge` to keep using it).
   - If `.hody/` was committed to git, the rename shows up as a move — commit it.

## Notes

- Never deletes anything: `.hody/` is renamed, not copied, so `tracker.db` and all KB files keep their content.
- Only path-like tokens are rewritten inside `.coregy/` (`.hody/`, `/hody-workflow:`, `hody-workflow@hody`); other text in the knowledge base is left alone.
- Exit codes: 0 success / nothing to do, 1 conflict, 2 filesystem error.
