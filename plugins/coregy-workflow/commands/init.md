---
description: Initialize coregy workflow for the current project. Detects tech stack, creates knowledge base, and populates it with project context.
argument-hint: "[optional: focus area, e.g. 'focus on backend services' or 'skip frontend KB']"
---

# /coregy-workflow:init

Initialize Coregy Workflow for the current project.

## User Instructions

$ARGUMENTS

If the section above contains text, treat it as additional user guidance for THIS init run. Apply it on top of the standard steps below — for example:
- "focus on backend microservices" → emphasize backend KB sections, skip frontend-specific scans
- "only init the email-microservice" → narrow scope to that subdirectory (but `.coregy/` still goes at the root)
- "skip KB populate" → run steps 1, 2, 4, 5, 6 but skip step 3
- "--graph" or "with graph" → also build Graphify knowledge graph (step 7)
- "verbose mode" → show detailed progress for each step

If the section is empty or just whitespace, run init normally with no special focus.

## Prerequisites — Root Directory Check

**CRITICAL**: Before doing anything, verify that `.coregy/` will be created at the **project root directory** — the directory where the user launched Claude Code (the initial working directory of the session).

**How to determine the root directory**: Use the current working directory (`.`). Do NOT `cd` into a subdirectory or microservice before running init. If the project is a monorepo or multi-service repo (e.g., contains multiple `*-microservice/` or `*-service/` directories), `.coregy/` MUST be placed at the top-level root, NOT inside any individual service.

**Validation**: Run `pwd` and confirm the output matches the project root. If the current directory is a subdirectory (e.g., `/project/24K/24k-email-microservice`), navigate back to the root (e.g., `/project/24K/`) before proceeding.

## Steps

1. **Detect tech stack**: Run the project-profile skill to scan the project and generate `.coregy/profile.yaml`

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/detect_stack.py --cwd .
```

2. **Create knowledge base**: Copy template files to `.coregy/knowledge/` if they don't already exist

Copy each template from `${CLAUDE_PLUGIN_ROOT}/skills/knowledge-base/templates/` to `.coregy/knowledge/`:
- `architecture.md`
- `decisions.md`
- `api-contracts.md`
- `business-rules.md`
- `tech-debt.md`
- `runbook.md`

Only copy files that don't already exist — never overwrite existing knowledge.

3. **Populate knowledge base**: Scan the project codebase and fill knowledge files with actual content. For each file below, read the relevant source files, then **replace the template placeholders** with real project data.

### 3a. architecture.md

Scan the project directory structure and source code to fill in:
- **System Overview**: Project type (from profile.yaml), main purpose (from README if exists), high-level description
- **Component Diagram**: List top-level directories and their roles (e.g., `src/components/` → UI components, `src/api/` → API handlers). Use a simple text diagram showing relationships
- **Data Flow**: Identify entry points (main files, route handlers, app bootstrap) and describe how a request/data flows through the system
- **Tech Stack Rationale**: From profile.yaml, document the detected stack choices (framework, language, DB, ORM, styling, testing, CI/CD)

Sources to scan: directory listing, README, main entry files, profile.yaml

### 3b. api-contracts.md

Search for existing API route definitions and document them:
- If Node.js (Express/Fastify/Nest): search for `app.get`, `app.post`, `router.`, `@Get`, `@Post` patterns
- If Python (FastAPI/Flask/Django): search for `@app.route`, `@router.`, `path(`, `urlpatterns`
- If Go (Gin/Echo/Fiber): search for `r.GET`, `r.POST`, `e.GET`, `app.Get` patterns

For each endpoint found, document: method, path, and brief description based on handler name. If no API routes are found, note "No API endpoints detected" and keep the template format for future use.

### 3c. decisions.md

Create ADR-001 documenting the initial tech stack detected from profile.yaml:
- **Title**: "Initial Tech Stack"
- **Status**: accepted
- **Context**: What was detected in the project
- **Decision**: Document each technology choice (language, framework, database, ORM, testing, CI/CD, styling)
- **Consequences**: What this means for development (e.g., "TypeScript chosen → strict typing required")

### 3d. runbook.md

Search for available commands and operational information:
- Read `scripts` section from `package.json` (if exists) → document dev, build, test, lint commands
- Check for `Makefile` → document available make targets
- Check for `docker-compose.yml` → document container start/stop commands
- Check for CI config (`.github/workflows/`) → note CI pipeline exists
- Check README for any deployment or setup instructions

Fill in: Deployment steps, common dev commands, how to run tests, how to start the project locally.

### 3e. business-rules.md and tech-debt.md

Leave these as templates — they cannot be reliably auto-detected from code. Note at the top: "To be filled by the team as business rules are defined" / "To be filled as tech debt is identified during development".

4. **Archive oversized KB files** (run BEFORE step 5):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/kb_archive.py run --cwd .
```

Files over 500 lines keep their 3 most recent sections; older sections move to `.coregy/knowledge/archive/`.

5. **Build KB index**:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/kb_index.py build --cwd .
```

Writes `.coregy/knowledge/_index.json`, enabling `tag:` / `agent:` / `status:` search in `/coregy-workflow:kb-search`.

6. **Initialize tracker database** (REQUIRED — always run this step, even if `.coregy/` already exists): Create or upgrade the interaction tracker database for persistent state tracking and agent checkpoints.

Run the tracker initialization:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py init --cwd .
```

This creates `.coregy/tracker.db` (idempotent — safe to run multiple times). The database stores:
- Interaction tracking (tasks, investigations, questions)
- Agent checkpoints (progress that survives context limit interruptions)
- Session history

The database is local-only and should be added to `.gitignore`.

If the project already has a `.coregy/state.json` from a previous workflow, also run migration (idempotent — a workflow already in the tracker is returned with `already_migrated: true`, not duplicated):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/tracker.py migrate --cwd .
```

7. **Create project rules template**: If `.coregy/rules.yaml` does not exist, create it with a commented starter template:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/rules.py init --cwd .
```

Exit 1 with "already exists" is expected on re-init — the user's rules are left untouched; do not pass `--force`.

This creates a template with all rule categories (coding, architecture, testing, workflow, custom) as commented-out examples. Users can uncomment and customize the rules relevant to their project. The file is optional — agents work normally without it.

8. **Build knowledge graph (optional)**: If the user passes `--graph` (e.g., `/init --graph` or the $ARGUMENTS contain "graph"), build the Graphify knowledge graph after profile detection:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/graphify_setup.py --cwd .
```

This runs the automated Graphify setup: finds Python >= 3.10, installs `graphifyy` if missing, builds the AST-based graph into `graphify-out/graph.json`, registers the graphify MCP server (local scope via `claude mcp add-json`, or `.mcp.json` when the `claude` CLI is unavailable), updates `integrations.graphify: true` in profile.yaml, adds `graphify-out/` to `.gitignore`, and enriches `.coregy/knowledge/architecture.md` with graph-derived module boundaries, cross-module coupling data, and god nodes.

After the script completes, tell the user to restart Claude Code to activate the Graphify MCP server.

Skip this step if the user did not request `--graph` or if `graphify-out/graph.json` already exists and the user didn't explicitly ask to rebuild.

9. **Show summary**: Display the detected stack and populated knowledge base

## Output

After running, show the user:
- Detected project type (fullstack, frontend, backend, etc.)
- Detected frameworks and languages
- Knowledge base status: which files were populated with content, which remain as templates
- Tracker database status: whether `.coregy/tracker.db` was initialized (and whether state.json was migrated)
- Project rules: whether `.coregy/rules.yaml` was created (remind user to uncomment and customize)
- Graphify status: whether the knowledge graph was built (if `--graph` was used)
- Suggest next steps: "Use `/coregy-workflow:start-feature` to begin a guided development workflow, or call agents directly (e.g., architect, code-reviewer, unit-tester)"

## Notes

- This command only needs to run once per project, but can be re-run safely
- `.coregy/profile.yaml` can be re-generated by running this command again
- Knowledge base files are never overwritten — only missing files are created
- The populate step reads source files but does not modify any project code
- **Steps 4–5 must run in that order** — indexing after archival, never before. Archival rewrites KB files, which would invalidate an index built first
- **Step 6 (tracker database) MUST always run**, even on re-init — `init_db` is idempotent and will add new tables (like `checkpoints`) if they don't exist yet. Without `tracker.db`, agent checkpoints cannot be saved and progress will be lost on interruption
- Recommend committing `.coregy/` to git for team sharing (exclude `tracker.db` — it's local-only)
