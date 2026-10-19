---
description: Show project health dashboard with KB completeness, tech debt, workflow stats, and recommendations.
argument-hint: "[optional: section focus, e.g. 'tech-debt only' or 'kb completeness']"
---

# /coregy-workflow:health

Show a comprehensive project health dashboard.

## User Instructions

$ARGUMENTS

If the section above contains text, focus the dashboard:
- "<section> only" → show only that section (kb, tech-debt, workflow, contracts)
- "recommendations" → prioritize actionable recommendations
- "summary" → short one-line-per-metric output

If empty, show the full health dashboard.

## Steps

1. **Check initialization**: Verify `.coregy/` directory exists. If not, suggest running `/coregy-workflow:init` first.

2. **Run the dashboard**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/health.py report --cwd .
```

Adjust the invocation based on `$ARGUMENTS`:
- names a section (`kb`, `tech-debt`, `workflows`, `dependencies`, `recommendations`) → append `--section <name>`
- asks for machine-readable output → append `--json`
- says "summary" → do not use `--section`; print the output as-is (the default dashboard is already one line per metric)

Exit 1 means `.coregy/` is missing — print the "run `/coregy-workflow:init` first" guidance.

3. **Present the output**, then call out the most important signal in one sentence (worst metric, or the top recommendation).

Example output of the command above:

   ```
   Project Health -- {project name}
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   Knowledge Base:  ████████░░ 80% complete (5/6 files populated)
   Tech Debt:       3 open items (1 high, 2 medium) -- oldest: 14 days
   Dependencies:    2 outdated, 0 vulnerabilities
   Workflows:       5 started, 4 completed (80% completion rate)
   Agent Usage:     code-reviewer (12x), backend (8x), unit-tester (7x)
                    Warning: spec-verifier never used

   Recommendations:
     -> Address high-priority tech debt item: "Migrate auth library"
     -> Try spec-verifier agent to validate implementation
     -> Run /coregy-workflow:refresh --deep to check dependencies
   ```

## Notes

- This command is read-only — it does not modify any files
- This command runs `health.py`; it does not compute metrics by reading files itself
- The script reads `.coregy/profile.yaml`, `.coregy/knowledge/`, and `.coregy/state.json`
- Useful as a quick health check when starting a new session or before a release
