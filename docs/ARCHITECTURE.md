# Coregy Workflow - Architecture

> Technical architecture for the Coregy Workflow plugin. For vision and goals, see [PROPOSAL.md](./PROPOSAL.md).

---

## Table of Contents

- [1. Architecture Overview](#1-architecture-overview)
- [2. Agent Design](#2-agent-design)
- [3. Plugin Structure](#3-plugin-structure)
- [4. Core Components Detail](#4-core-components-detail)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     COREGY WORKFLOW PLUGIN                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  LAYER 1: PROJECT PROFILE (foundation)                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ .coregy/profile.yaml                                         │ │
│  │ Auto-detect: language, framework, testing, CI/CD, infra    │ │
│  │ Runs once via /coregy-workflow:init, shared across all agents│ │
│  └────────────────────────────────────────────────────────────┘ │
│                             ↓ feeds into                        │
│  LAYER 2: KNOWLEDGE BASE (accumulative, structured)              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ .coregy/knowledge/                                           │ │
│  │ ├── architecture.md     (system design, diagrams)          │ │
│  │ ├── decisions.md        (ADRs - why we chose X over Y)     │ │
│  │ ├── api-contracts.md    (API specs between FE/BE)          │ │
│  │ ├── business-rules.md   (business logic, constraints)      │ │
│  │ ├── tech-debt.md        (known issues, TODOs)              │ │
│  │ ├── runbook.md          (deploy, debug, operate)           │ │
│  │ ├── _index.json         (tag/agent/section index — cache)  │ │
│  │ └── archive/            (auto-archived old sections)       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                             ↓ feeds into                        │
│  LAYER 3: SPECIALIZED AGENTS (9 agents, 4 groups)               │
│  ┌──────────┐ ┌──────────┐ ┌───────────────────┐ ┌───────────┐  │
│  │  THINK   │ │  BUILD   │ │     VERIFY        │ │   SHIP    │  │
│  │researcher│ │ frontend │ │ code-reviewer     │ │  devops   │  │
│  │architect │ │ backend  │ │ spec-verifier     │ │           │  │
│  │          │ │          │ │ unit-tester       │ │           │  │
│  │          │ │          │ │ integration-tester│ │           │  │
│  └──────────┘ └──────────┘ └───────────────────┘ └───────────┘  │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  SUPPORTING COMPONENTS                                          │
│  ├── Skills: project-profile (auto-detect), knowledge-base      │
│  ├── State: .coregy/state.json (workflow state machine)           │
│  ├── Hooks: inject_project_context (SessionStart + auto-refresh)│
│  │          ,quality_gate (PreCommit)                           │
│  ├── Tracker: .coregy/tracker.db (SQLite interaction tracker)      │
│  ├── Rules: .coregy/rules.yaml (user-authored project rules)      │
│  ├── Commands: /coregy-workflow:init, start-feature, status,      │
│  │             refresh, kb-search, connect, ci-report, sync,    │
│  │             update-kb, resume, health, track, history, rules  │
│  └── Output Styles: review-report, test-report, design-doc,     │
│                      ci-report                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User request
     ↓
[Hook: SessionStart] → inject project profile into system message
     ↓
Claude Code receives request → determines task type
     ↓
Loads appropriate agent (from agents/*.md)
     ↓
Agent reads:
  1. .coregy/profile.yaml (current stack)
  2. .coregy/rules.yaml (project rules, if exists)
  3. .coregy/knowledge/* (accumulated context)
  4. .coregy/state.json (workflow state + spec file, if active)
  5. Graphify MCP tools (if configured)
     ↓
Agent performs work, saves checkpoints to tracker.db
     ↓
Agent writes new knowledge (with frontmatter) to .coregy/knowledge/
Agent updates .coregy/state.json (mark self completed, log summary)
Agent appends to feature work log (.coregy/knowledge/log-*.md)
     ↓
Output to user
```

---

## 2. Agent Design

### 2.1. Agent Summary

| # | Agent | Group | Expertise | Input | Output | Scope |
|---|-------|-------|-----------|-------|--------|-------|
| 1 | researcher | THINK | External tech docs, best practices | Profile + question | Tech summary → knowledge base | READ only |
| 2 | architect | THINK | System design, BA, flows, contracts | Requirements + KB | Architecture docs, ADRs, API contracts | READ + WRITE KB |
| 3 | frontend | BUILD | UI/UX following project's FE stack | FE profile + design docs | FE code | WRITE FE code |
| 4 | backend | BUILD | API, business logic, DB | BE profile + design docs | BE code | WRITE BE code |
| 5 | code-reviewer | VERIFY | Code quality, patterns, security, perf | Code changes | Review report | READ only |
| 6 | spec-verifier | VERIFY | Logic matches specs/business rules | Code + specs from KB | Verification report | READ only |
| 7 | unit-tester | VERIFY | Unit tests, mocking, edge cases | Code + profile testing | Unit tests | WRITE tests |
| 8 | integration-tester | VERIFY | API tests, E2E, business flows | Code + API contracts + KB | Integration/E2E tests | WRITE tests |
| 9 | devops | SHIP | CI/CD, deployment, infra | DevOps profile + arch docs | Pipeline configs, IaC | WRITE configs |

### 2.2. Agent Prompt Template

Each agent `.md` follows this structure:

```markdown
---
name: agent-name
description: When this agent should be activated (for Claude Code matching)
---

# Agent: [Role Name]

## Bootstrap (must run first)
1. Read `.coregy/profile.yaml` → determine tech stack
2. If `.coregy/rules.yaml` exists, read and follow project rules
3. Read spec file if exists (from `.coregy/state.json` → `spec_file`)
4. Read `.coregy/knowledge/[relevant-files]` → understand project context
5. Check Graphify MCP tools if `integrations.graphify: true`

## Core Expertise
- [Domain-specific knowledge]
- Adapt behavior based on profile:
  - If profile.frontend.framework = "react" → apply React patterns
  - If profile.frontend.framework = "vue" → apply Vue patterns

## Responsibilities
- [What this agent specifically does]

## Constraints
- [What this agent specifically does NOT do]

## Output Format
- [Standard output format]

## Knowledge Base Update
- Include YAML frontmatter (tags, created, author_agent, status)
- After completion, write new knowledge to `.coregy/knowledge/[file]`

## MCP Tools
- Check `integrations:` in profile.yaml for available MCP tools (GitHub, Linear, Jira, Graphify)

## Workflow State
- Read/update `.coregy/state.json` if active workflow exists
- Read spec file for confirmed requirements
- Append to feature work log

## Checkpoints
- Save checkpoints via tracker.py after each unit of work
- Resume from checkpoint data if provided

## Collaboration
- Suggest next agent based on workflow state
```

### 2.3. Task-to-Agents Mapping

```
┌─────────────────────┬───────────────────────────────────────────────────────┐
│ Task Type           │ Agents (in order)                                     │
├─────────────────────┼───────────────────────────────────────────────────────┤
│ New feature         │ researcher → architect → FE + BE (parallel)           │
│                     │ → unit-tester + integration-tester                    │
│                     │ → code-reviewer + spec-verifier → devops              │
├─────────────────────┼───────────────────────────────────────────────────────┤
│ Bug fix             │ architect (understand context) → FE or BE             │
│                     │ → unit-tester → code-reviewer                         │
├─────────────────────┼───────────────────────────────────────────────────────┤
│ Refactor            │ code-reviewer (identify) → FE or BE                   │
│                     │ → unit-tester → code-reviewer (verify)                │
├─────────────────────┼───────────────────────────────────────────────────────┤
│ New API endpoint    │ architect (contract) → backend                        │
│                     │ → integration-tester → code-reviewer                  │
├─────────────────────┼───────────────────────────────────────────────────────┤
│ UI change           │ frontend → unit-tester → code-reviewer                │
├─────────────────────┼───────────────────────────────────────────────────────┤
│ Tech spike          │ researcher → architect                                │
├─────────────────────┼───────────────────────────────────────────────────────┤
│ Deployment          │ devops                                                │
├─────────────────────┼───────────────────────────────────────────────────────┤
│ Production hotfix   │ BE or FE → unit-tester → devops                       │
├─────────────────────┼───────────────────────────────────────────────────────┤
│ Performance issue   │ researcher (profiling best practices) → backend       │
│                     │ → integration-tester (benchmark) → code-reviewer      │
├─────────────────────┼───────────────────────────────────────────────────────┤
│ Security audit      │ code-reviewer (security focus)                        │
│                     │ → backend (fix) → unit-tester                         │
└─────────────────────┴───────────────────────────────────────────────────────┘
```

---

## 3. Plugin Structure

```
coregy-workflow/                          # Root = GitHub repo
├── .claude-plugin/
│   └── marketplace.json                # Marketplace registration
│
├── plugins/
│   └── coregy-workflow/                  # Main plugin
│       ├── .claude-plugin/
│       │   └── plugin.json             # Plugin metadata
│       │
│       ├── agents/                     # 9 specialized agents + contracts
│       │   ├── contracts/              # 6 agent handoff contracts (.yaml)
│       │   ├── researcher.md
│       │   ├── architect.md
│       │   ├── frontend.md
│       │   ├── backend.md
│       │   ├── code-reviewer.md
│       │   ├── spec-verifier.md
│       │   ├── unit-tester.md
│       │   ├── integration-tester.md
│       │   └── devops.md
│       │
│       ├── skills/
│       │   ├── project-profile/
│       │   │   ├── SKILL.md
│       │   │   └── scripts/
│       │   │       ├── detect_stack.py       # CLI wrapper (backward-compatible)
│       │   │       ├── state.py              # Workflow state machine
│       │   │       ├── tracker.py            # SQLite interaction tracker + checkpoints
│       │   │       ├── tracker_schema.py     # Tracker DB schema definitions
│       │   │       ├── tracker_awareness.py  # Tracker context injection
│       │   │       ├── rules.py              # Project rules engine
│       │   │       ├── kb_index.py           # KB index builder (_index.json)
│       │   │       ├── kb_archive.py         # KB auto-archival
│       │   │       ├── contracts.py          # Agent I/O contract validator
│       │   │       ├── quality_rules.py      # Configurable quality rule engine
│       │   │       ├── ci_monitor.py         # CI feedback loop
│       │   │       ├── team.py               # Team roles & permissions
│       │   │       ├── health.py             # Project health dashboard
│       │   │       ├── graphify_setup.py     # Graphify knowledge graph setup
│       │   │       ├── graphify_diff.py      # Graph structural diff
│       │   │       ├── graphify_kb_populate.py # KB auto-populate from graph
│       │   │       └── detectors/            # Modular detection package (20 modules)
│       │   │           ├── __init__.py       # Re-exports public API
│       │   │           ├── utils.py          # read_json, read_lines
│       │   │           ├── node.py           # Node.js/TS detection
│       │   │           ├── go.py             # Go detection
│       │   │           ├── python_lang.py    # Python detection
│       │   │           ├── rust.py           # Rust detection
│       │   │           ├── java.py           # Java/Kotlin detection
│       │   │           ├── csharp.py         # C#/.NET detection
│       │   │           ├── ruby.py           # Ruby detection
│       │   │           ├── php.py            # PHP detection
│       │   │           ├── devops.py         # CI/CD, Docker, infra
│       │   │           ├── monorepo.py       # Monorepo + workspace profiles
│       │   │           ├── database.py       # Database detection
│       │   │           ├── conventions.py    # Linter, formatter, PR template
│       │   │           ├── integrations.py   # Preserve integrations
│       │   │           ├── profile.py        # Orchestrator
│       │   │           ├── serializer.py     # YAML output + CLI
│       │   │           ├── deep_analysis.py  # Deep dependency analysis
│       │   │           ├── versions.py       # Semver parsing
│       │   │           └── directories.py    # Directory structure analysis
│       │   │
│       │   └── knowledge-base/
│       │       ├── scripts/
│       │       │   └── kb_sync.py            # Team KB sync logic
│       │       └── templates/
│       │           ├── architecture.md
│       │           ├── decisions.md
│       │           ├── api-contracts.md
│       │           ├── business-rules.md
│       │           ├── tech-debt.md
│       │           └── runbook.md
│       │
│       ├── hooks/
│       │   ├── hooks.json
│       │   ├── inject_project_context.py     # SessionStart + auto-refresh
│       │   └── quality_gate.py               # Pre-commit quality gate (v2: configurable)
│       │
│       ├── commands/                          # 16 commands
│       │   ├── init.md
│       │   ├── start-feature.md
│       │   ├── status.md
│       │   ├── refresh.md
│       │   ├── kb-search.md
│       │   ├── connect.md                    # MCP integrations
│       │   ├── ci-report.md                  # CI test report
│       │   ├── sync.md                       # Team KB sync
│       │   ├── update-kb.md                  # KB refresh
│       │   ├── resume.md                     # Resume interrupted workflow
│       │   ├── health.md                     # Project health dashboard
│       │   ├── track.md                      # Interaction tracking
│       │   ├── history.md                    # Interaction history
│       │   ├── rules.md                      # Project rules management
│       │   └── team.md                       # Team roles & permissions
│       │
│       ├── output-styles/
│       │   ├── review-report.md
│       │   ├── test-report.md
│       │   ├── design-doc.md
│       │   └── ci-report.md
│       │
│       └── README.md
│
├── test/                               # 802 tests across 33 files
│   ├── test_detect_stack.py            # Integration test (backward-compat)
│   ├── test_node_detector.py
│   ├── test_go_detector.py
│   ├── test_python_detector.py
│   ├── test_rust_detector.py
│   ├── test_java_detector.py
│   ├── test_csharp_detector.py
│   ├── test_ruby_detector.py
│   ├── test_php_detector.py
│   ├── test_devops.py
│   ├── test_monorepo.py
│   ├── test_serializer.py
│   ├── test_auto_refresh.py
│   ├── test_quality_gate.py
│   ├── test_kb_sync.py
│   ├── test_workflow_state.py
│   ├── test_kb_index.py
│   ├── test_conventions.py
│   ├── test_directories.py
│   ├── test_deep_analysis.py
│   ├── test_contracts.py
│   ├── test_quality_rules.py
│   ├── test_ci_monitor.py
│   ├── test_team.py
│   ├── test_health.py
│   ├── test_tracker.py
│   ├── test_graphify_setup.py
│   ├── test_graphify_diff.py
│   ├── test_graphify_kb_populate.py
│   └── test_rules.py
│
├── docs/                               # Documentation
│   ├── PROPOSAL.md                     # Vision, goals, build guide
│   ├── ARCHITECTURE.md                 # This file
│   ├── ROADMAP.md                      # All phases, task tracking
│   └── USER_GUIDE.md                   # Installation, usage, commands
│
├── .gitignore
├── LICENSE
├── CLAUDE.md                           # Claude Code instructions
└── README.md                           # Repo-level docs
```

---

## 4. Core Components Detail

### 4.1. Project Profile (`detect_stack.py` → `detectors/` package)

Modular Python package (20 modules, SRP) that auto-detects tech stack from project files. `detect_stack.py` is a thin backward-compatible CLI wrapper. Supports `--deep` flag for full dependency tree analysis.

```python
# Detection rules (each in its own module under detectors/):
#
# node.py: package.json → Node.js project
#   dependencies.react → frontend: react
#   dependencies.vue → frontend: vue
#   dependencies.next → frontend: next (SSR)
#   dependencies.@angular/core → frontend: angular
#   dependencies.svelte → frontend: svelte
#   dependencies.express → backend: express
#   dependencies.fastify → backend: fastify
#   dependencies.@nestjs/core → backend: nest
#   devDependencies.vitest → testing: vitest
#   devDependencies.jest → testing: jest
#
# go.py: go.mod → Go project
#   github.com/gin-gonic/gin → backend: gin
#   github.com/labstack/echo → backend: echo
#   github.com/gofiber/fiber → backend: fiber
#
# python_lang.py: requirements.txt / pyproject.toml → Python project
#   django → backend: django
#   fastapi → backend: fastapi
#   flask → backend: flask
#
# rust.py: Cargo.toml → Rust project
#   actix-web / rocket / axum → backend framework
#
# java.py: pom.xml / build.gradle → Java/Kotlin project
#   spring-boot / quarkus / micronaut → backend framework
#
# csharp.py: .csproj / .sln → C#/.NET project
#   ASP.NET Core / Blazor → backend framework
#
# ruby.py: Gemfile → Ruby project
#   rails / sinatra / hanami → backend framework
#
# php.py: composer.json → PHP project
#   laravel / symfony / magento → backend framework
#
# monorepo.py: nx.json / turbo.json / lerna.json / pnpm-workspace.yaml
#   Detects workspace packages and builds per-workspace profiles
#
# devops.py: Dockerfile → docker, .github/workflows/ → github-actions, *.tf → terraform
# database.py: docker-compose.yml / .env → postgresql / mysql / mongodb / redis
# conventions.py: .github/PULL_REQUEST_TEMPLATE.md
# integrations.py: Preserves user-configured integrations across re-detection
# profile.py: Orchestrator — calls all detectors, builds final profile dict
# serializer.py: YAML output + CLI argument parsing (supports --deep flag)
# deep_analysis.py: Run npm ls/audit, pip list/audit, go list, cargo metadata
# versions.py: Semver parsing, major version mismatch, outdated detection
# directories.py: Directory structure analysis (src/, lib/, test/ detection)
```

**Output:** `.coregy/profile.yaml`

```yaml
project:
  name: my-app                    # from package.json name or directory name
  type: fullstack                 # fullstack | frontend | backend | library | monorepo

frontend:
  framework: react                # react | vue | angular | svelte | next | nuxt
  language: typescript             # typescript | javascript
  state: zustand                  # redux | zustand | pinia | vuex | mobx
  styling: tailwind               # tailwind | css-modules | styled-components | scss
  testing: vitest                 # jest | vitest | cypress | playwright
  build: vite                     # vite | webpack | esbuild | turbopack
  dir: src/                       # FE source directory

backend:
  framework: fastify              # express | fastify | nest | gin | echo | django | fastapi
  language: typescript             # typescript | javascript | go | python | java | rust
  database: postgresql            # postgresql | mysql | mongodb | redis | sqlite
  orm: drizzle                    # prisma | drizzle | typeorm | gorm | sqlalchemy
  testing: vitest                 # jest | vitest | go-test | pytest
  dir: server/                    # BE source directory

devops:
  ci: github-actions              # github-actions | gitlab-ci | jenkins | circleci
  containerize: docker            # docker | podman | none
  deploy: aws-ecs                 # aws-ecs | kubernetes | vercel | netlify | fly-io
  infra: terraform                # terraform | pulumi | cdk | none
  monitoring: none                # datadog | grafana | newrelic | none

conventions:
  git_branch: feature/{description}
  commit_style: conventional      # conventional | angular | none
  pr_template: true               # detected from .github/PULL_REQUEST_TEMPLATE.md
  linter: eslint                  # eslint | biome | golangci-lint | ruff | none
  formatter: prettier             # prettier | biome | gofmt | black | none
```

### 4.2. Knowledge Base Templates

Each file in `.coregy/knowledge/` has YAML frontmatter for structured indexing, followed by markdown content:

**`architecture.md`**
```markdown
---
tags: [architecture, system-design]
created: 2026-02-16
author_agent: architect
status: active
---

# Architecture

## System Overview
<!-- High-level system description -->
```

**`decisions.md`**
```markdown
---
tags: [decisions, adr]
created: 2026-02-16
author_agent: architect
status: active
---

# Architecture Decision Records

## ADR-001: [Title]
- **Date**: YYYY-MM-DD
- **Status**: accepted | rejected | superseded
- **Context**: Problem to be solved
- **Decision**: Chosen approach
- **Alternatives**: Other options considered
- **Consequences**: Impact of the decision
```

**Frontmatter fields**:
- `tags` — list of topic tags for cross-file discovery
- `created` — date the entry was created
- `author_agent` — which agent wrote it
- `status` — `active` or `superseded`
- `supersedes` — reference to replaced entry (optional)

Frontmatter is optional — existing KB files without frontmatter still work (backward compatible). `_index.json` is a generated cache built by `kb_index.py` — can be rebuilt at any time.

**`api-contracts.md`**
```markdown
# API Contracts

## [Feature Name]

### POST /api/[endpoint]
- **Request**: { field: type }
- **Response**: { field: type }
- **Auth**: required | public
- **Notes**: Any special considerations
```

**`business-rules.md`**
```markdown
# Business Rules

## [Domain]

### Rule: [Name]
- **Description**: Rule description
- **Conditions**: When it applies
- **Actions**: What happens
- **Exceptions**: Edge cases
```

### 4.3. Hooks

**`inject_project_context.py`** — Runs at `SessionStart`:
1. Checks if config files (package.json, go.mod, etc.) are newer than `.coregy/profile.yaml` → auto-refreshes if stale
2. Reads `.coregy/profile.yaml` and injects project context into the system message
3. Reads `.coregy/state.json` if present — injects active workflow state (feature name, spec status, next agent)
4. Reads Graphify graph stats if `graphify-out/graph.json` exists — injects codebase structure summary
5. Reads `.coregy/rules.yaml` if present — injects project rules summary
6. Every agent knows the project context, workflow state, graph structure, AND project rules AS SOON AS THE SESSION STARTS

**`quality_gate.py`** (v2) — Runs at `PreCommit`:
1. Loads configurable rules from `.coregy/quality-rules.yaml` (falls back to built-in defaults)
2. Checks: secrets (API keys, tokens, custom patterns), security anti-patterns (eval, innerHTML), debug statements (console.log, breakpoint), file size
3. Severity levels: `error` blocks commit, `warning` allows but prints issues
4. Skips binary files, node_modules, vendor, lock files; test files skip security checks
5. Outputs pass/fail with categorized report

### 4.4. Commands

| Command | Description |
|---------|-------------|
| `/coregy-workflow:init` | Detect stack, create profile + populate knowledge base |
| `/coregy-workflow:start-feature` | Start feature development workflow — classify task type, suggest agents |
| `/coregy-workflow:status` | View profile + KB summary + next steps |
| `/coregy-workflow:refresh` | Re-detect stack, update profile.yaml |
| `/coregy-workflow:kb-search` | Search across knowledge base files |
| `/coregy-workflow:connect` | Configure MCP integrations (GitHub, Linear, Jira) |
| `/coregy-workflow:ci-report` | Generate CI-compatible test reports |
| `/coregy-workflow:sync` | Sync knowledge base with team |
| `/coregy-workflow:update-kb` | Rescan codebase and refresh knowledge base |
| `/coregy-workflow:resume` | Resume an interrupted workflow from last checkpoint |
| `/coregy-workflow:health` | Project health dashboard with metrics and recommendations |
| `/coregy-workflow:track` | Create, update, list tracked items (tasks, investigations, questions) |
| `/coregy-workflow:history` | View interaction history and session timeline |
| `/coregy-workflow:rules` | View, validate, or initialize project rules (.coregy/rules.yaml) |
