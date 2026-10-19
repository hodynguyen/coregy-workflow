---
description: View interaction history — past workflows, investigations, decisions, and status transitions. Filter by type, date range, tags, or specific items.
argument-hint: "[filters: type:x since:date tag:y limit:N]"
---

# /coregy-workflow:history

View the interaction history for this project.

## User Instructions

$ARGUMENTS

Treat the section above as filters for the history query:
- `type:<task|investigation|question|discussion|maintenance>` → filter by item type
- `since:<date>` → show items created after date (e.g. "last week", "2026-04-01")
- `tag:<name>` → filter by tag
- `limit:<N>` → max N items
- Plain text → free-text search on title/description

If empty, show the 20 most recent items of any type.

## Steps

1. **Check tracker exists**: Verify `.coregy/tracker.db` exists. If not, tell the user no history is available and suggest running `/coregy-workflow:init`.

2. **Determine query type**: Based on the user's request:

| Request | Query |
|---------|-------|
| "What did we do last week?" | Search by date range |
| "Show all completed tasks" | Search by type + status |
| "History of item X" | Item-specific audit trail |
| "What's related to auth?" | Search by tags |
| General / no filter | Show recent items (last 20) |

3. **Execute the query**:

### Recent history (default)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py search --limit 20 --cwd .
```

### By date range

`tracker.py search` has no date flags. Widen the result set, then filter the
`created_at` / `updated_at` timestamps yourself when presenting:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py search --limit 200 --cwd .
```

### By type and status

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py search \
  --type <task|investigation|question|discussion|maintenance> \
  --status <status> \
  --cwd .
```

### Item audit trail

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py history <item_id> --cwd .
```

### By tags

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py search --tags "<tag1,tag2>" --cwd .
```

## Output

### List view
```
History (last 20 items):
  2026-03-21  ✅ Task: "Interaction tracking" (completed)
  2026-03-20  ✅ Investigation: "SQLite vs JSON" (concluded)
  2026-03-18  ⏸ Task: "Payment refactor" (paused)
  2026-03-15  ✅ Task: "Auth middleware" (completed)
```

### Item detail view
```
Item: itm_a1b2c3d4e5f6
Type: task
Title: "OAuth2 login"
Status: completed
Priority: high
Tags: auth, oauth2, login
Created: 2026-03-18
Completed: 2026-03-21

Status History:
  2026-03-18 10:00  created (initial)
  2026-03-18 10:05  created → in_progress (started by backend agent)
  2026-03-20 14:00  in_progress → paused (switching to bug fix)
  2026-03-21 09:00  paused → in_progress (resumed)
  2026-03-21 15:00  in_progress → completed (all tests passing)
```

Use these icons: ✅ completed/concluded/answered/resolved, ⏸ paused/tabled/deferred, 🔄 in_progress/active, ⛔ blocked, ❌ abandoned

## Notes

- History is read-only — use `/coregy-workflow:track` to create or update items
- All data comes from `.coregy/tracker.db` (local-only)
- Date filters use ISO format (YYYY-MM-DD)
