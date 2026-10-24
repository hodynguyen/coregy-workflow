# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **Coregy Workflow** plugin for Claude Code — a project-aware development workflow system with 9 specialized AI agents. Current version: v0.17.0. Full documentation is in `docs/` (PROPOSAL, ARCHITECTURE, ROADMAP, USER_GUIDE).

The plugin provides:
- Auto-detection of project tech stacks (generates `.coregy/profile.yaml`)
- A shared knowledge base (`.coregy/knowledge/`) that is auto-populated on init and accumulates across sessions
- 9 specialized agents across 4 groups: THINK (researcher, architect), BUILD (frontend, backend), VERIFY (code-reviewer, spec-verifier, unit-tester, integration-tester), SHIP (devops)
- 16 commands: `/coregy-workflow:init`, `/coregy-workflow:start-feature`, `/coregy-workflow:status`, `/coregy-workflow:refresh`, `/coregy-workflow:kb-search`, `/coregy-workflow:connect`, `/coregy-workflow:ci-report`, `/coregy-workflow:sync`, `/coregy-workflow:update-kb`, `/coregy-workflow:resume`, `/coregy-workflow:health`, `/coregy-workflow:track`, `/coregy-workflow:history`, `/coregy-workflow:rules`, `/coregy-workflow:team`, `/coregy-workflow:migrate`
- 4 output styles: review-report, test-report, design-doc, ci-report
- Configurable quality gate with `.coregy/quality-rules.yaml`
- Project rules (`.coregy/rules.yaml`) — user-authored coding conventions, architecture constraints, testing requirements that all agents follow
- Team roles & permissions via `.coregy/team.yaml`
- Fix loop — gate agents (reviewer, verifier, testers) send blocking issues back to BUILD via `state.py request-fixes` and re-check, capped by `max_fix_rounds`; escalates to the user when it stalls
- Real verification (`verify.py`) — resolves the project's own lint / typecheck / test commands (override `.coregy/verify.yaml`) and runs them; builders, testers, reviewers and the final workflow step gate on the exit codes
- Quick track (`/start-feature --quick`, or suggested for small changes) — builder → code-reviewer, no discovery, compact spec, lighter agents; separate from the execution mode
- Workflow state machine (`.coregy/state.json`) with spec-driven development and 3 execution modes: `auto` (full auto, no interaction), `guided` (interactive discovery, auto execution), `manual` (pause between agents)
- Interaction tracker (`tracker.py`, `.coregy/tracker.db`) with agent checkpoints for surviving context limit interruptions
- Auto-track (`auto_track.py`, `auto_track_hook.py`) — `UserPromptSubmit` hook detects task intent in user prompts (EN + VI) and hints Claude to create a tracker item when work happens outside `/start-feature`
- Graphify knowledge graph integration — AST-based code graph via MCP server, used by all 9 agents
- Structured KB with YAML frontmatter, `_index.json` indexing, and auto-archival
- `$ARGUMENTS` support in all commands for inline parameters

## Architecture

### Three-Layer Design

1. **Project Profile** (foundation) — `detect_stack.py` scans config files (package.json, go.mod, requirements.txt, Cargo.toml, pom.xml, etc.) and outputs `.coregy/profile.yaml` with detected language, framework, testing, CI/CD, and infra details
2. **Knowledge Base** (accumulative) — Markdown files in `.coregy/knowledge/` with YAML frontmatter (tags, date, author-agent, status). Auto-populated during init, then agents both read and write to accumulate context. `_index.json` enables tag/agent/status search. Auto-archival moves old sections to `archive/` when files exceed 500 lines
3. **Specialized Agents** — 9 agents with static Markdown prompts that adapt behavior by reading the profile at runtime

### Data Flow
```
User request → [SessionStart hook] injects profile → Agent loads profile.yaml + knowledge base → Agent performs work → Agent writes new knowledge → Output
```

### Plugin Structure
```
plugins/coregy-workflow/
├── .claude-plugin/plugin.json     # Plugin metadata
├── agents/                        # 9 agent prompt files (.md) + contracts/
│   └── contracts/                 # 6 handoff contract YAML files
├── output-styles/                 # 4 output templates (review-report, test-report, design-doc, ci-report)
├── skills/
│   ├── project-profile/
│   │   ├── scripts/
│   │   │   ├── detect_stack.py    # Thin CLI wrapper (backward-compatible)
│   │   │   ├── state.py           # Workflow state machine (.coregy/state.json) + CLI
│   │   │   ├── verify.py          # Lint/typecheck/test runner (.coregy/verify-last.json) + CLI
│   │   │   ├── tracker.py         # SQLite interaction tracker + agent checkpoints
│   │   │   ├── tracker_schema.py  # Tracker DB schema definitions
│   │   │   ├── tracker_awareness.py # Tracker context injection
│   │   │   ├── rules.py           # Project rules engine (.coregy/rules.yaml)
│   │   │   ├── mcp_setup.py       # Jira/Linear/GitHub MCP setup CLI
│   │   │   ├── mcp_config.py      # Registers MCP servers (claude mcp local scope / .mcp.json)
│   │   │   ├── mini_yaml.py       # Stdlib indentation-aware YAML reader
│   │   │   ├── migrate.py         # Hody -> Coregy project migration (.hody/ -> .coregy/) + CLI
│   │   │   ├── kb_index.py        # KB index builder (_index.json) + CLI
│   │   │   ├── kb_archive.py      # KB auto-archival (archive/ dir) + CLI
│   │   │   ├── contracts.py       # Agent I/O contract validator + CLI
│   │   │   ├── quality_rules.py   # Configurable quality rule engine
│   │   │   ├── ci_monitor.py      # CI feedback loop (poll, parse, tech-debt) + CLI
│   │   │   ├── team.py            # Team roles & permissions + CLI
│   │   │   ├── health.py          # Project health dashboard + CLI
│   │   │   ├── graphify_setup.py  # Graphify knowledge graph setup
│   │   │   ├── graphify_diff.py   # Graph structural diff between builds
│   │   │   ├── graphify_kb_populate.py # KB auto-populate from graph data
│   │   │   └── detectors/         # Modular detection package (20 modules)
│   │   │       ├── __init__.py    # Re-exports public API
│   │   │       ├── utils.py       # read_json, read_lines
│   │   │       ├── node.py        # Node.js/TS detection
│   │   │       ├── go.py          # Go detection
│   │   │       ├── python_lang.py # Python detection
│   │   │       ├── rust.py        # Rust detection
│   │   │       ├── java.py        # Java/Kotlin detection
│   │   │       ├── csharp.py      # C#/.NET detection
│   │   │       ├── ruby.py        # Ruby detection
│   │   │       ├── php.py         # PHP detection
│   │   │       ├── devops.py      # CI/CD, Docker, infra
│   │   │       ├── monorepo.py    # Monorepo + workspace profiles
│   │   │       ├── database.py    # Database detection
│   │   │       ├── conventions.py # Linter, formatter, PR template
│   │   │       ├── integrations.py# Preserve integrations across re-detection
│   │   │       ├── profile.py     # Orchestrator — calls all detectors
│   │   │       ├── serializer.py  # YAML output + CLI entry point
│   │   │       ├── deep_analysis.py # Deep dependency analysis (opt-in)
│   │   │       ├── versions.py    # Semver parsing, conflict detection
│   │   │       └── directories.py # Directory structure analysis
│   │   └── SKILL.md
│   └── knowledge-base/templates/  # 6 KB template files
├── hooks/
│   ├── hooks.json                 # SessionStart + PreToolUse + UserPromptSubmit hook registration
│   ├── inject_project_context.py  # Reads profile + workflow state + rules, injects into system message
│   ├── quality_gate.py            # Pre-commit quality gate (v2: configurable rules)
│   └── auto_track_hook.py         # UserPromptSubmit: detects task intent and hints tracker creation
└── commands/                      # 16 commands: init, start-feature, status, refresh, kb-search, connect, ci-report, sync, update-kb, resume, health, track, history, rules, team, migrate
```

## Development Stack

- **Agent prompts, skills, commands**: Markdown
- **Scripts** (detect_stack, hooks): Python 3 (stdlib preferred, PyYAML is the only external dependency)
- **Config**: JSON (hooks.json, plugin.json, marketplace.json), YAML (profile output)
- **No build step** — plugins are distributed as-is

## Testing

```bash
# Run all tests (960 tests across 37 test files)
python3 -m unittest discover -s test -v

# Tests cover: per-language detectors, monorepo, devops, serializer, quality gate, KB sync,
# auto-refresh, workflow state, KB index/archive, deep analysis, contracts, quality rules,
# CI monitor, team roles, health dashboard, tracker, graphify (setup/diff/kb-populate), rules,
# auto-track (intent detection), git-commit detection, and the runtime CLI surface
# Uses mock project structures (temp directories) to verify profile.yaml output correctness.
# test_cli_surface.py drives all 8 workflow CLIs as real subprocesses (sys.executable) --
# importing the library functions cannot catch a missing __main__ or a bad argparse dest,
# which is how the ${PLUGIN_ROOT} and quality-gate bugs survived 12 versions.
```

## Key Constraints

- Agent prompts are static Markdown — no dynamic templating; agents read `profile.yaml` at runtime instead
- Hook scripts must complete within 60s timeout
- Persistent state via filesystem (`.coregy/` directory) and SQLite (`tracker.db`) for interaction tracking
- Plugins only load at Claude Code startup — changes require restart
- `detect_stack.py` should only scan config files, not the full codebase (for speed). Use `--deep` for actual package manager analysis
- Agent contracts are advisory by default — produce warnings, not errors

## Development Roadmap

- **Phase 1 (MVP)**: Complete — detect_stack for top 5 stacks, 3 core agents, knowledge base templates, /coregy-workflow:init
- **Phase 2 (Full Agent Suite)**: Complete — 9 agents, 3 commands, 3 output styles, extended stack detection (Rust, Java/Kotlin, Angular, Svelte), KB auto-populate on init
- **Phase 3 (Intelligence)**: Complete — C#/Ruby/PHP stack detection, monorepo support (nx/turborepo/lerna/pnpm), auto-update profile (/refresh), KB search (/kb-search), agent collaboration patterns
- **Phase 4 (Ecosystem)**: Complete — MCP integration with GitHub/Linear/Jira (`/coregy-workflow:connect`), pre-commit quality gate (`quality_gate.py`), CI test report (`/coregy-workflow:ci-report`), team KB sync (`/coregy-workflow:sync`), agent MCP tool access, auto-profile refresh hook, KB update (`/coregy-workflow:update-kb`). Refactored `detect_stack.py` into modular `detectors/` package.
- **Phase 5 (Deep Intelligence)**: Complete — Workflow state machine (`state.py`, `/coregy-workflow:resume`). Structured KB with frontmatter, `_index.json`, auto-archival. Deep stack analysis (`--deep` flag, `deep_analysis.py`, `versions.py`). Agent I/O contracts (`agents/contracts/`, `contracts.py`).
- **Phase 6 (Enterprise Grade)**: Complete — Configurable quality gate v2 (`quality_rules.py`, `.coregy/quality-rules.yaml`). CI feedback loop (`ci_monitor.py`, auto tech-debt entries). Team roles & permissions (`team.py`, `.coregy/team.yaml`). Project health dashboard (`health.py`, `/coregy-workflow:health`).
- **v0.6.x (Interaction Tracker)**: Complete — SQLite-based tracker (`tracker.py`, `.coregy/tracker.db`) for persistent interaction tracking, agent checkpoints that survive context limit interruptions, `/coregy-workflow:track` and `/coregy-workflow:history` commands, `$ARGUMENTS` support in all 14 commands, per-feature work logs.
- **v0.7.0 (Spec-Driven Workflow)**: Complete — Discovery → Confirm → Auto-execute paradigm. Agents produce specs first, user confirms, then remaining agents auto-execute against confirmed spec.
- **v0.8.x (Graphify Integration)**: Complete — AST-based knowledge graph via tree-sitter (`graphify_setup.py`). MCP server with 7 graph query tools. All 9 agents graph-aware. Graph diff tracking between builds (`graphify_diff.py`). KB auto-populate from graph data (`graphify_kb_populate.py`). Graph metadata in KB index.
- **v0.9.0 (Project Rules)**: Complete — User-authored project rules (`.coregy/rules.yaml`) with coding conventions, architecture constraints, testing requirements, workflow preferences. All 9 agents read rules at bootstrap. `/coregy-workflow:rules` command. Hook injection of rules summary.
- **v0.10.0 (Execution Modes)**: Complete — Three workflow execution modes: `auto` (skip discovery, auto-confirm spec, run all agents), `guided` (interactive discovery, auto execution), `manual` (pause between agents). Mode persisted in state.json, respected by resume. 553 tests total.
- **v0.11.0 (Auto-Track)**: Complete — Heuristic intent detector (`auto_track.py`) classifies user prompts as task/bug-fix/investigation. New `UserPromptSubmit` hook (`auto_track_hook.py`) injects a tracking hint when a non-workflow prompt looks like a substantive task. Skipped automatically inside active workflows or via `COREGY_AUTO_TRACK=0`. Bilingual (English + Vietnamese) verb/question detection. 586 tests total.
- **v0.12.0 (MCP Auto-Setup)**: Complete — `mcp_setup.py` configures Jira/Linear/GitHub MCP servers non-interactively when all required fields are passed (e.g. `--api-token`, `--site`, `--email` for Jira). Falls back to interactive guidance listing missing fields with where-to-get instructions. Merges into `.claude/settings.json` without clobbering other servers; flips `integrations.<name>` in profile.yaml. CLI subcommands: `jira/linear/github` (configure), `remove`, `status`, `fields`. 615 tests total.
- **v0.13.0 (Runtime Wiring & Script CLIs)**: Complete — Fixed two runtime bugs: `${PLUGIN_ROOT}` -> `${CLAUDE_PLUGIN_ROOT}` across 10 commands + 9 agents (40 sites; the old variable does not exist, so every bash call in a command/agent expanded to an empty path), and the quality gate's `git commit` detector, which only matched a commit at the very start of a command and so never fired on `git add -A && git commit`. Added an argparse CLI (`coregy-cli-v1` convention: shared `--cwd` parent parser, hyphenated subcommands, `--json`, exit 0/1/2) to the 7 previously unreachable scripts -- `state.py`, `health.py`, `kb_index.py`, `kb_archive.py`, `contracts.py`, `ci_monitor.py`, `team.py` -- as a pure wrapper layer with zero library signature changes, plus a CLI-layer `_normalize_state()` that heals legacy `state.json` schemas. Rewired `/init`, `/update-kb`, `/kb-search`, `/health`, `/ci-report`, `/start-feature`, `/resume` and 5 agent contract checks from prose to real bash invocations. New `/coregy-workflow:team` command (14 -> 15). Linked the 3 orphaned output styles to their agents; removed a stray 324KB `graphify-out/` cache and guarded it in `.gitignore`.
- **v0.13.1 (Audit Fixes)**: Complete — Full code audit. Quality gate now scans files staged by the same command (`git add -A && git commit`, `commit -a`) and the staged blob, not the working tree; warnings are surfaced. New `mini_yaml.py` fixes quality-rules parsing (default config had silently disabled debug checks and custom secret patterns); `test/` ignore paths match whole segments. SessionStart context moved from `systemMessage` (user-only) to `additionalContext`. MCP servers registered where Claude Code reads them (`claude mcp` local scope, else gitignored `.mcp.json`) with real packages (`mcp-atlassian`, Linear/GitHub remote MCP). State machine handles an agent listed in two phases (refactor flow never finished). `ci_monitor` fetches failed logs by run id. `kb_sync` git-branch push rewritten with plumbing (no checkout/stash), gist mode uses valid `gh` syntax. Tracker items link to workflows and follow their status; `note` appends; `migrate` idempotent; `show` subcommand. KB: unified `created`/`author_agent` keys, section metadata comments instead of mid-file frontmatter, archival never drops undated topical sections. Health reads real deep-analysis keys, ignores template frontmatter, workflow history persisted to `state_history.json`. Contracts scoped to the active workflow with agent handoff sections. `rules init` needs `--force`; solo projects default to `lead`; framework-less projects detected as `library`.
- **v0.14.0 (Rename Hody → Coregy)**: Complete — Plugin renamed `hody-workflow@hody` → `coregy-workflow@coregy` (commands `/coregy-workflow:*`, data dir `.coregy/`, env vars `COREGY_*`, KB sync branch `coregy-knowledge`, repo `hodynguyen/coregy-workflow`). Legacy `HODY_*` env vars still read as a fallback. New `migrate.py` + `/coregy-workflow:migrate` (16 commands) moves `.hody/` → `.coregy/`, rewrites path tokens, `.gitignore` and the `enabledPlugins` key; refuses on conflict, never deletes. SessionStart hook auto-migrates and tells the model. 854 tests total.
- **v0.15.0 (Fix Loop)**: Complete — VERIFY is no longer a straight line. A gate agent (`code-reviewer`, `spec-verifier`, `unit-tester`, `integration-tester`) with blocking issues calls `state.py request-fixes <gate> --issue ...`, which reopens the BUILD fixer(s) and the gate so `next-agent` walks BUILD → gate again. Escalates (nothing reopened, `next-agent --json` → `escalation`) after `max_fix_rounds` (default 3, `init-workflow --max-fix-rounds`) or when a round has no fewer issues than the last; the user accepts (`complete-agent`), forces a round (`--force-round`) or aborts — in every mode. Re-runs tracked by `log_index` into `agent_log`, so a `complete-agent` right after `request-fixes` is a no-op. `start-agent` returns `fix_round`; rounds logged to the feature log. start-feature/resume now loop on `next-agent`. 892 tests total.
- **v0.16.0 (Real Verification)**: Complete — New `verify.py` (`detect`/`run`/`last`/`init`) resolves lint / typecheck / test commands from `.coregy/verify.yaml` > Makefile > `profile.yaml` `testing.command` > package.json / pyproject / go.mod / Cargo.toml / Maven / Gradle / .NET / Ruby / PHP (plus profile `frontend.dir`/`backend.dir`), runs them with `CI=1` and per-check timeouts, writes `.coregy/verify-last.json` (self-gitignored) with `passed`, `verified`, output tails and fix-loop-ready `issues[]`. `run --reuse` skips when the git fingerprint (excluding `.coregy/`) is unchanged. Builders must pass before completing; testers and reviewers turn failures into `request-fixes`; start-feature/resume run a final check before `complete`; `/init` shows detected commands. `request-fixes` on an already-completed gate reopens its last occurrence. 948 tests total.
- **v0.17.0 (Quick Track)**: Complete — Track (`full`/`quick`) is separate from mode. `/start-feature --quick` skips discovery in every mode, writes a compact spec, runs `BUILD: [builder] → VERIFY: [code-reviewer]` (tech-spike → researcher) with `--max-fix-rounds 2`; small changes get quick suggested (auto takes it, guided asks, manual never; `--full` opts out). `init-workflow --quick` stores `quick: true`, shown by `show` and the SessionStart hook; backend/frontend/code-reviewer/researcher read it to keep bootstrap light (relevant KB only, no contracts/checkpoints), builders add regression tests, reviewer reports blockers + ≤3 notes. Outgrowing quick → abort and restart `--full`. 960 tests total.
