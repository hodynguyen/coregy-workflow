---
description: Create, update, and search tracked items (tasks, investigations, questions, discussions, maintenance). Use to manage interaction history across sessions.
argument-hint: "<subcommand> [args]  e.g. 'create task \"Fix login bug\"' or 'update itm_abc123 status:completed'"
---

# /hody-workflow:track

Manage tracked items in the interaction tracker.

## User Instructions

$ARGUMENTS

Parse the section above as a tracker subcommand:
- `create <type> "<title>" [tags:...]` → create a new item
- `update <item_id> [status:x notes:y]` → update existing item
- `search <query> [type:x tag:y]` → search items
- `show <item_id>` → show full item details + history
- `close <item_id>` → transition to terminal state (completed/resolved/answered) — items still in their initial state need two `update` calls (e.g. task `created` → `in_progress` → `completed`)

If empty, show available subcommands and ask the user what they want to do.

## Steps

1. **Check tracker exists**: Verify `.hody/tracker.db` exists. If not, suggest running `/hody-workflow:init` first.

2. **Parse the user's intent**: Determine what operation the user wants:

| Intent | Action |
|--------|--------|
| Create a new item | `create` |
| Update status | `transition` |
| Add a note | `note` |
| Search items | `search` |
| List active items | `list` |

3. **Execute the operation**:

### Create

Classify the user's request into one of 5 types:
- `task` — Something to build/fix/deploy
- `investigation` — Exploring/understanding code, no changes
- `question` — A question to answer
- `discussion` — Architecture/trade-off discussion
- `maintenance` — Dependency updates, cleanup

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py create \
  --type <type> \
  --title "<title>" \
  --tags "<comma-separated tags>" \
  --priority <high|medium|low> \
  --cwd .
```

### Update status

Valid transitions per type:
- **task**: created → in_progress → completed/paused/blocked/abandoned
- **investigation**: started → in_progress → concluded/paused/abandoned
- **question**: asked → answered/deferred
- **discussion**: opened → active → resolved/tabled
- **maintenance**: planned → in_progress → completed/deferred/abandoned

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py update <item_id> \
  --status <new_status> \
  --reason "<reason>" \
  --cwd .
```

### Add a note

Notes are appended with a timestamp; earlier notes are kept.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py note <item_id> "<note text>" --cwd .
```

### Search

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py search \
  --type <type> \
  --status <status> \
  --tags "<tags>" \
  --cwd .
```

### Show one item (details + status history)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py show <item_id> --cwd .
```

### List active

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py list --active --cwd .
```

## Output

Display results in a readable format:

```
Tracked Items:
  [HIGH] itm_a1b2c3d4e5f6  Task: "OAuth2 login" (in_progress, 3d)
  [MED]  itm_f6e5d4c3b2a1  Investigation: "Auth module" (concluded, 1w)
```

## Notes

- Items are stored in `.hody/tracker.db` (local-only, not committed to git)
- The tracker is independent of workflow state — it persists across sessions
- Use `/hody-workflow:history` for detailed item history and audit trail
