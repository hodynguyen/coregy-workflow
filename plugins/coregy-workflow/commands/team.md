---
description: View team roles and permissions (.coregy/team.yaml). Check whether the current user may use an agent or perform a workflow action.
argument-hint: "[action: 'show', 'init', 'check-agent <agent>', 'check-workflow <action>']"
---

# /coregy-workflow:team

View and check the project's team roles and permissions.

## User Instructions

$ARGUMENTS

Map the argument to an action:
- empty or `show` → **show**
- `init` → **init**
- `check-agent <name>` → **check-agent**
- `check <name>` → **check-agent** (alias)
- `check-workflow <action>` → **check-workflow** (`skip_agent` | `abort_workflow` | `modify_contract`)
- `--json` anywhere → append `--json` to the call

## Steps

### Action: show (default)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/team.py show --cwd .
```

If the output starts with `(no team.yaml -- showing built-in defaults)`, tell the user they
can run `/coregy-workflow:team init` to customise roles.

### Action: init

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/team.py init --cwd .
```

Exit 1 means the file already exists. Ask the user before re-running with `--force` —
it overwrites their role definitions.

### Action: check-agent \<agent\>

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/team.py check-agent <agent> --cwd .
```

Exit 0 = allowed, exit 1 = denied. Print the reason either way. A denial is advisory
guidance for the user, not a hard block on invoking the agent.

### Action: check-workflow \<action\>

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/team.py check-workflow <action> --cwd .
```

Same exit contract as `check-agent`.

## Output

`show`:

```
Team (.coregy/team.yaml)
Current user: hodynguyen (role: developer)
Members: 0
Roles:
  lead      agents=all  skip=yes  contracts=yes  review=no
  developer agents=5    skip=no   contracts=no   review=yes
  reviewer  agents=3    skip=no   contracts=no   review=no
  junior    agents=3    skip=no   contracts=no   review=yes
```

`check-agent` / `check-workflow`:

```
ALLOWED: Role 'developer' has access to agent 'backend'.
DENIED: Role 'developer' cannot skip agents.
```

## Notes

- Roles are advisory — coregy does not enforce them at the tool layer
- **Never chain `check-agent` / `check-workflow` under `&&` or `set -e`** — they exit 1 on
  denial, which would abort the surrounding command
- User identity: `$COREGY_USER` env var, else `git config user.name`
- With no `members:` configured (solo project) everyone is `lead`; once members are listed, unlisted users default to `developer`
- `.coregy/team.yaml` should be committed so the whole team shares the same roles
