---
description: Search the project knowledge base (.coregy/knowledge/) for specific topics, keywords, or sections. Use when you need to find information across KB files.
argument-hint: "<query> [filters: tag:x agent:y status:z file:name]"
---

# /coregy-workflow:kb-search

Search the project's knowledge base for relevant information.

## User Instructions

$ARGUMENTS

Treat the section above as the search query plus optional filters:
- Plain text → full-text search across all KB files
- `tag:<name>` → filter by frontmatter tag
- `agent:<name>` → filter by author_agent in frontmatter
- `status:<value>` → filter by status (active, archived, etc.)
- `file:<name>` → limit search to one KB file

If empty, ask the user what they want to search for.

## Steps

1. **Check KB exists**: Verify `.coregy/knowledge/` directory exists. If not, suggest running `/coregy-workflow:init` first.

2. **Get search query**: Ask the user what they want to search for, or use the query they provided.

3. **Check for structured search**: If the query uses structured filters, search the index first:

   - `tag:<tagname>` — search by tag (e.g., `tag:auth`)
   - `agent:<name>` — search by author agent (e.g., `agent:architect`)
   - `status:<status>` — filter by status (e.g., `status:active`, `status:superseded`)

   Run the indexed search, passing only the filters the user actually supplied:

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/kb_index.py search \
     --tag <t> --agent <a> --status <s> --json --cwd .
   ```

   If it exits 1 (no index), run
   `python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/kb_index.py build --cwd .`
   first, then retry the search.

   Present the matching files with their tags, author, and sections. Then continue to
   step 4 for full-text matches — the index covers metadata and headings only.

4. **Search across all KB files**: Read all `.md` files in `.coregy/knowledge/` and search for the query.

Search each file in `.coregy/knowledge/`:
- `architecture.md`
- `decisions.md`
- `api-contracts.md`
- `business-rules.md`
- `tech-debt.md`
- `runbook.md`
- Any other `.md` files in the directory

For each file, find:
- Matching section headers (## headings) that contain the keyword
- Paragraphs or list items containing the keyword
- Return surrounding context (the full section where the match was found)

5. **Present results**: Show results grouped by file, with the matching sections highlighted.

## Output Format

```
## Search results for: "<query>"

### architecture.md
> [matching section with context]

### api-contracts.md
> [matching section with context]

---
Found X matches across Y files.
```

If no matches found:
```
No matches found for "<query>" in the knowledge base.

Available KB files: architecture.md, decisions.md, api-contracts.md, business-rules.md, tech-debt.md, runbook.md
```

## Supported Search Modes

- **Keyword search**: Find all occurrences of a word/phrase across KB files
- **Tag search**: `tag:<tagname>` — find files with a specific tag in frontmatter
- **Agent search**: `agent:<name>` — find files authored by a specific agent
- **Status filter**: `status:active` or `status:superseded` — filter by entry status
- **Section listing**: When query is "list" or "sections", show all ## headings from each file
- **File filter**: When query starts with "in:<filename>", search only that file (e.g., "in:architecture API")

## Notes

- Search is case-insensitive
- Returns full sections (from ## heading to next ## heading) for context
- Does not modify any knowledge base files
- Works with any custom .md files added to .coregy/knowledge/
- Structured search (tag/agent/status) requires `_index.json` — rebuild with `/coregy-workflow:init` or `/coregy-workflow:update-kb` if missing, or directly: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/kb_index.py build --cwd .`
- KB files with YAML frontmatter (tags, author_agent, created, status) enable richer search
