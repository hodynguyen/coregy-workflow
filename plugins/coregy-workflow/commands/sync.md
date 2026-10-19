---
description: Sync the knowledge base (.coregy/knowledge/) with a shared location for team collaboration. Supports git branch, GitHub Gist, and shared repo modes.
argument-hint: "[mode: 'git-branch' | 'gist' | 'shared-repo'] [optional: push/pull]"
---

# /coregy-workflow:sync

Push or pull `.coregy/knowledge/` to a shared location so team members can share accumulated project knowledge.

## User Instructions

$ARGUMENTS

If the section above contains text, apply it to the sync:
- Mode name (git-branch, gist, shared-repo) → use that sync mode
- "push" → only upload local KB to shared location
- "pull" → only download from shared location
- "status" → show local KB file sizes only (`--action status`)

If empty, ask the user for the action and mode (step 2). There is no stored sync configuration and no two-way merge: each run is a one-directional push or pull.

## Steps

1. **Check initialization**: Verify `.coregy/knowledge/` exists. If not, tell the user to run `/coregy-workflow:init` first.

2. **Ask sync parameters**: Prompt the user for:
   - **Action**: `push` (upload local KB) or `pull` (download shared KB)
   - **Mode**: How to sync:

| Mode | Description | Requirements |
|------|-------------|-------------|
| `git-branch` | Push/pull to a dedicated branch in the same repo | Git repo with remote |
| `gist` | Sync via GitHub Gist | `gh` CLI authenticated |
| `shared-repo` | Push/pull to a separate shared knowledge repo | Repo URL |

3. **Run the sync script**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/knowledge-base/scripts/kb_sync.py --cwd . --mode <mode> --action <action> [options]
```

Options per mode:
- `git-branch`: `--branch <name>` (default: `coregy-knowledge`)
- `gist`: `--gist-id <id>` (required for pull; push without ID creates a new gist)
- `shared-repo`: `--repo <url>` (required)

4. **Show results**: Display what happened:

### Push result
```
KB Sync: Push Complete
━━━━━━━━━━━━━━━━━━━━━

Mode: git-branch (branch: coregy-knowledge)
Files synced: 6
  → architecture.md
  → decisions.md
  → api-contracts.md
  → business-rules.md
  → tech-debt.md
  → runbook.md

Team members can pull with:
  /coregy-workflow:sync → pull → git-branch
```

### Pull result
```
KB Sync: Pull Complete
━━━━━━━━━━━━━━━━━━━━━

Mode: gist (gist ID: abc123def456)
Files pulled: 6
  → architecture.md (updated)
  → decisions.md (updated)
  → api-contracts.md (no change)
  → business-rules.md (new)
  → tech-debt.md (no change)
  → runbook.md (updated)

Knowledge base updated at .coregy/knowledge/
```

## Sync Modes Detail

### Git Branch mode
- **Push**: Commits every `.md` in `.coregy/knowledge/` (working-copy content) onto the `coregy-knowledge` branch using git plumbing and pushes it. Your checkout, index, working tree and stash are never touched.
- **Pull**: Fetches the branch from remote and writes every `.md` on it into `.coregy/knowledge/`.
- Best for: teams using the same repo

### Gist mode
- **Push**: Creates or updates a GitHub Gist with all KB markdown files.
- **Pull**: Clones the gist and copies files to `.coregy/knowledge/`.
- Best for: sharing across repos or with external collaborators

### Shared Repo mode
- **Push**: Clones the shared repo, copies KB files into a project-named subdirectory, commits and pushes.
- **Pull**: Clones the shared repo, copies from the project-named subdirectory to `.coregy/knowledge/`.
- Best for: organizations with multiple projects sharing a central knowledge repo

## Notes

- Pull overwrites local KB files — commit your `.coregy/knowledge/` before pulling if you have local changes
- Push to git-branch never switches branches or stashes — it is safe with uncommitted work
- Gist mode requires `gh` CLI: `brew install gh && gh auth login`
- Shared repo uses the project directory name to namespace files
- Run `/coregy-workflow:sync` with action `status` to see current KB file sizes
