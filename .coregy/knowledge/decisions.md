# Architecture Decision Records

## ADR-001: Initial Tech Stack
- **Date**: 2025-01-18
- **Status**: accepted
- **Context**: Building a Claude Code plugin for project-aware development workflows. Need languages for scripting, config formats for plugin metadata, and a way to store project profiles.
- **Decision**:
  - Python 3 (stdlib + PyYAML) for all scripts (detect_stack.py, inject_project_context.py)
  - Markdown for agent prompts, commands, skills (Claude Code plugin format)
  - YAML for project profile output (.coregy/profile.yaml)
  - JSON for plugin config (plugin.json, hooks.json, marketplace.json)
  - unittest (stdlib) for testing
- **Alternatives**: Could have used Node.js/TypeScript for scripts, but Python is simpler for file parsing and available everywhere. Could have used JSON for profiles, but YAML is more human-readable.
- **Consequences**: No build step needed. Only external dependency is PyYAML. Scripts must work with Python 3.8+.

## ADR-002: Three-Layer Architecture
- **Date**: 2025-01-18
- **Status**: accepted
- **Context**: Agents need to be project-aware without dynamic templating (Claude Code constraint — agent prompts are static Markdown).
- **Decision**: Three layers: (1) Profile — auto-detected stack in YAML, (2) Knowledge Base — accumulative Markdown files, (3) Agents — static prompts that read profile at runtime.
- **Alternatives**: Dynamic prompt templating (not supported by Claude Code), single config file (insufficient for accumulated knowledge).
- **Consequences**: Agents must bootstrap by reading profile.yaml and knowledge files. Knowledge base grows over time across sessions.

## ADR-003: Agent Collaboration via Suggestion
- **Date**: 2025-02-12
- **Status**: accepted
- **Context**: Agents sometimes need to delegate work to other agents (e.g., code-reviewer suggests running unit-tester).
- **Decision**: Agents include a `## Collaboration` section that recommends the user invoke another agent. No auto-invocation — Claude Code doesn't support agent-to-agent calls.
- **Alternatives**: Auto-invoke via tool calls (not supported), chaining via commands (too complex).
- **Consequences**: User must manually follow agent suggestions. Workflow guidance via `/coregy-workflow:start-feature` helps orchestrate the right sequence.

## ADR-004: Phase 4 Ecosystem Strategy
- **Date**: 2025-02-14
- **Status**: accepted
- **Context**: Phase 4 aims to integrate the plugin with external tools (GitHub, issue trackers, CI) and enable team collaboration. Need to decide the integration approach and scope.
- **Decision**: Use MCP (Model Context Protocol) as the integration layer for external tools. Three pillars: (1) MCP servers for GitHub/Linear/Jira — agents gain read/write access to issues, PRs, and comments; (2) Quality gates — pre-commit hook `quality_gate.py` runs code-reviewer checks on staged files; (3) Team sync — `kb_sync.py` pushes/pulls `.coregy/knowledge/` to Git branch, Gist, or shared repo. New commands: `/coregy-workflow:connect` (configure MCP), `/coregy-workflow:ci-report` (CI-compatible test output), `/coregy-workflow:sync` (team KB sync). Auto-profile refresh enhances the SessionStart hook to detect stale profiles.
- **Alternatives**: Direct API calls instead of MCP (couples plugin to specific APIs), custom webhook system (over-engineered for current scope), no CI integration (limits value for teams).
- **Consequences**: Depends on MCP server availability for each service. Plugin remains useful without MCP — integrations are additive. New scripts (`quality_gate.py`, `kb_sync.py`) follow the same Python stdlib + PyYAML pattern. Agent prompts gain optional `## MCP Tools` sections that activate only when MCP is configured.

## ADR-005: Interaction Tracking with SQLite
- **Date**: 2026-03-21
- **Status**: proposed
- **Context**: The current `state.json` tracks only ONE active workflow at a time. Developers frequently context-switch (pause task A to fix bug B, investigate something mid-feature, ask questions). There is no historical awareness of past work across sessions, no warnings about stale/abandoned work, and no way to answer "what did we do 3 weeks ago with the auth module?". Need a system that classifies every meaningful interaction, tracks per-item state, and surfaces relevant context.
- **Decision**: Use SQLite (`sqlite3` stdlib module) as the persistence layer for a new interaction tracker (`tracker.py`). Key design choices:
  - 5 item types: task, investigation, question, discussion, maintenance — each with its own state machine
  - SQLite over JSON: enables complex queries (tag search, date ranges, joins), audit logs via `status_log` table, and handles concurrent access via WAL mode
  - `state.json` remains the workflow engine for backward compatibility; `tracker.db` wraps around it providing history, cross-references, and awareness
  - Agent-driven classification: agents follow prompt guidelines to classify and record interactions, rather than automatic per-message classification (SessionStart hook only runs once per session)
  - Awareness layer injected via SessionStart hook: shows active items, warnings about stale work, recent completions — capped at small counts to avoid information overload
  - `tracker.db` is local-only (`.gitignore`d) — not shared via git, unlike `state.json` and knowledge base
- **Alternatives considered**:
  - Extend `state.json` with arrays of items (poor query performance, no audit trail, concurrent access issues)
  - Flat JSON files per item (filesystem clutter, no relational queries)
  - Full automatic classification of every message (not feasible — SessionStart hook runs once, no per-message hook available; also creates noise)
  - Replace `state.json` entirely (breaks backward compatibility, higher risk)
- **Consequences**: New dependency on `sqlite3` (stdlib, zero-risk). `tracker.db` is optional — everything works without it. Agents need prompt updates to call tracker CLI. Two new commands (`/track`, `/history`). Migration path: init creates DB, optionally imports existing `state.json` workflow. Rollout in 3 minor versions (v0.6.0-v0.7.0).
