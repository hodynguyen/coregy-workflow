---
description: View, validate, or initialize project rules (.hody/rules.yaml). Defines coding conventions, architecture constraints, and workflow preferences for all agents.
argument-hint: "[action: 'show', 'validate', 'init', or 'add coding:forbidden \"Use camelCase for variables\"']"
---

# /hody-workflow:rules

Manage project rules that all agents follow during development.

## User Instructions

$ARGUMENTS

If the section above contains text, treat it as an action:
- "show" or empty → display current rules with summary
- "validate" → check rules.yaml structure and report errors
- "init" → create template rules.yaml
- "add <category>:<subcategory> '<rule>'" → append a rule to the file

If empty, default to "show".

## Steps

### Action: `show` (default)

1. Check if `.hody/rules.yaml` exists. If not, show:
   ```
   No project rules found.
   Run /hody-workflow:rules init to create a template.
   ```

2. Read `.hody/rules.yaml` and display a formatted summary:

   ```
   Project Rules (.hody/rules.yaml)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Version: 1

   coding (5 rules):
     naming:
       • Use camelCase for variables and functions
       • Use PascalCase for components
     forbidden:
       • Never use any as TypeScript type
       • Do not use default exports

   architecture (3 rules):
     boundaries:
       • Services must not import from controllers
     constraints:
       • Each module must have an index.ts barrel file

   testing (2 rules):
     requirements:
       • Every API endpoint needs integration tests

   custom (2 rules):
     • All user-facing strings must support i18n
     • Third-party deps need approval

   Total: 12 rules across 4 categories
   ```

3. Show which agents are affected:
   ```
   Agents affected:
     → architect: reads architecture rules
     → backend, frontend: reads coding + architecture rules
     → code-reviewer: validates all coding + architecture rules
     → unit-tester, integration-tester: reads testing rules
     → all agents: reads custom + workflow rules
   ```

### Action: `validate`

1. Run validation:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/rules.py validate --cwd .
   ```

2. Display results:
   - If valid: "✅ rules.yaml is valid (12 rules across 4 categories)"
   - If errors: show each error with line hint

### Action: `init`

1. Check if `.hody/rules.yaml` already exists. If yes, warn:
   ```
   .hody/rules.yaml already exists (12 rules).
   Overwrite with template? This will remove your current rules.
   ```
   Wait for user confirmation before overwriting.

2. Create template:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/rules.py init --cwd .
   ```

   Exit 1 means the file already exists and was left untouched. Only after the user
   confirmed the overwrite in step 1, re-run with `--force`.

3. Show the created file and guide the user:
   ```
   Created .hody/rules.yaml with commented template.
   
   Next steps:
     1. Open .hody/rules.yaml and uncomment the rules relevant to your project
     2. Add your own project-specific rules
     3. Run /hody-workflow:rules validate to check the structure
   
   Agents will automatically read these rules at the start of each session.
   ```

### Action: `add <category>:<subcategory> '<rule>'`

1. Parse the target: category, subcategory (optional), and rule text.
   Examples:
   - `/rules add coding:forbidden "Never use eval()"` → append to coding.forbidden
   - `/rules add custom "All APIs need rate limiting"` → append to custom list

2. Read `.hody/rules.yaml`, append the rule to the correct section.

3. If the category or subcategory doesn't exist, create it.

4. Run validation after adding.

5. Show confirmation: "Added rule to coding.forbidden (now 4 rules in category)"

## Notes

- Rules are **advisory** — agents follow them as best-effort behavioral guidance, not automated enforcement
- For automated code checks (pre-commit), use `.hody/quality-rules.yaml` instead
- Rules are injected into the session context at startup, so all agents know they exist
- Each agent reads the full file at bootstrap and focuses on categories relevant to its role
- Rules file should be committed to git for team sharing
- Run `/hody-workflow:rules validate` after manual edits to catch YAML issues
