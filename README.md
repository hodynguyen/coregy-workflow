# Coregy Workflow

> A project-aware development workflow plugin for Claude Code with 9 specialized AI agents.

**Version**: v0.15.0 — All 6 phases complete

**Documentation**: [User Guide](./docs/USER_GUIDE.md) | [Architecture](./docs/ARCHITECTURE.md) | [Proposal](./docs/PROPOSAL.md) | [Roadmap](./docs/ROADMAP.md)

---

## Features

- **Auto stack detection** — scans `package.json`, `go.mod`, `requirements.txt`, `Cargo.toml`, `pom.xml`, `.csproj`, `Gemfile`, `composer.json`, monorepo configs, and more
- **Monorepo support** — detects Nx, Turborepo, Lerna, pnpm workspaces and builds per-workspace profiles
- **Knowledge base** — 6 persistent markdown files with YAML frontmatter, `_index.json` indexing, and auto-archival
- **9 specialized agents** across 4 groups: THINK (researcher, architect), BUILD (frontend, backend), VERIFY (code-reviewer, spec-verifier, unit-tester, integration-tester), SHIP (devops)
- **Workflow state machine** — `.coregy/state.json` tracks feature progress across sessions with `/resume`
- **Fix loop** — reviewers, verifiers and testers send blocking issues back to the BUILD agents and re-check, up to 3 rounds; stops and asks you when it stalls
- **Agent contracts** — 6 typed handoff schemas for validated inter-agent communication
- **Configurable quality gate** — `.coregy/quality-rules.yaml` with custom patterns, severity levels, debug detection
- **CI feedback loop** — poll CI status, parse test failures, auto-create tech-debt entries
- **Team roles** — `.coregy/team.yaml` with role-based agent access control (lead, developer, reviewer, junior)
- **Health dashboard** — `/coregy-workflow:health` aggregates KB completeness, tech debt, workflow stats, recommendations
- **MCP integrations** — connect to GitHub, Linear, and Jira for issue tracking and project management
- **SessionStart hook** — automatically injects your project's tech stack into every Claude Code session

---

## Installation

> **Upgrading from Hody?** The plugin was renamed `hody-workflow` → `coregy-workflow` in v0.14.0. Run
> `/plugin uninstall hody-workflow@hody` and `/plugin marketplace remove hody`, then follow the steps below.
> Existing projects are migrated automatically on the next session (`.hody/` → `.coregy/`), or run
> `/coregy-workflow:migrate`. Legacy `HODY_*` env vars still work.

### 1. Add marketplace

```
/plugin marketplace add hodynguyen/coregy-workflow
```

### 2. Install plugin

```
/plugin install coregy-workflow@coregy
```

You'll be prompted to choose a scope:

| Scope | When to use |
|-------|-------------|
| **User** | Personal use — available across all your projects |
| **Project** | Team use — committed to git, teammates get it automatically |
| **Local** | Testing — only you, only this project, gitignored |

### 3. Restart Claude Code

Plugins load at startup — restart is required after install.

---

## Usage

### Initialize in any project

```bash
cd ~/projects/my-app
claude

# Inside Claude Code:
/coregy-workflow:init
```

This will:
1. Run `detect_stack.py` to scan your project files
2. Generate `.coregy/profile.yaml` with detected stack info
3. Create `.coregy/knowledge/` with 6 files (YAML frontmatter + `_index.json`)
4. Populate knowledge base with real project data (architecture, API routes, runbook commands, tech stack ADR)
5. Display a summary of detected technologies and populated knowledge

### Generated structure

```
my-app/
└── .coregy/
    ├── profile.yaml              # Tech stack (auto-generated)
    ├── state.json                # Workflow state (created by /start-feature)
    ├── quality-rules.yaml        # Quality gate config (optional)
    ├── team.yaml                 # Team roles & permissions (optional)
    └── knowledge/
        ├── architecture.md       # System overview (auto-populated)
        ├── decisions.md          # ADR-001: tech stack (auto-populated)
        ├── api-contracts.md      # Detected API endpoints (auto-populated)
        ├── business-rules.md     # Business logic (template)
        ├── tech-debt.md          # Known issues (template)
        ├── runbook.md            # Dev commands (auto-populated)
        ├── _index.json           # Tag/agent/section index (auto-generated)
        └── archive/              # Auto-archived old sections
```

> **Tip:** Commit `.coregy/` to git — it's team knowledge, not temp files.

### Commands

| Command | Description |
|---------|-------------|
| `/coregy-workflow:init` | Detect stack, create profile + populate knowledge base |
| `/coregy-workflow:start-feature` | Start guided feature development workflow |
| `/coregy-workflow:status` | View profile + KB summary + workflow progress |
| `/coregy-workflow:resume` | Resume an interrupted workflow from last checkpoint |
| `/coregy-workflow:refresh` | Re-detect stack, update profile.yaml (`--deep` for dependency analysis) |
| `/coregy-workflow:kb-search` | Search knowledge base (keyword, tag, agent, status) |
| `/coregy-workflow:connect` | Configure MCP integrations (GitHub, Linear, Jira) |
| `/coregy-workflow:ci-report` | Generate CI-compatible test reports |
| `/coregy-workflow:sync` | Sync knowledge base with team |
| `/coregy-workflow:update-kb` | Rescan codebase and refresh knowledge base |
| `/coregy-workflow:health` | Project health dashboard with metrics and recommendations |
| `/coregy-workflow:track` | Create, update, and search tracked items (tasks, investigations, questions) |
| `/coregy-workflow:history` | View interaction history across sessions |
| `/coregy-workflow:rules` | View, validate, or initialize project rules (`.coregy/rules.yaml`) |
| `/coregy-workflow:team` | View team roles and permissions; check agent/workflow access |
| `/coregy-workflow:migrate` | Migrate a project from the old Hody plugin (`.hody/` → `.coregy/`) |

### Agents

| Group | Agent | Role |
|-------|-------|------|
| THINK | researcher | Research docs, best practices, library comparison |
| THINK | architect | System design, API contracts, ADRs |
| BUILD | frontend | UI components, state management, client-side logic |
| BUILD | backend | API endpoints, business logic, database operations |
| VERIFY | code-reviewer | Code quality, security, performance review |
| VERIFY | spec-verifier | Verify code matches specs and business rules |
| VERIFY | unit-tester | Unit tests for functions and components |
| VERIFY | integration-tester | API tests, E2E tests, business flow tests |
| SHIP | devops | CI/CD, Docker, infrastructure, deployment |

### Supported stacks

| Stack | Detection source |
|-------|-----------------|
| Node.js + React/Vue/Angular/Svelte/SvelteKit/Next/Nuxt | `package.json` dependencies |
| Go + Gin/Echo/Fiber | `go.mod` |
| Python + Django/FastAPI/Flask | `requirements.txt`, `pyproject.toml` |
| Rust + Actix-web/Rocket/Axum | `Cargo.toml` |
| Java/Kotlin + Spring Boot/Quarkus/Micronaut | `pom.xml`, `build.gradle` |
| C#/.NET + ASP.NET Core/Blazor | `.csproj`, `.sln`, `global.json` |
| Ruby + Rails/Sinatra/Hanami | `Gemfile` |
| PHP + Laravel/Symfony/Magento | `composer.json` |
| Monorepo (Nx/Turborepo/Lerna/pnpm) | `nx.json`, `turbo.json`, `lerna.json`, `pnpm-workspace.yaml` |
| Docker | `Dockerfile`, `docker-compose.yml` |
| CI/CD | `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile` |
| Infrastructure | `*.tf` (Terraform), `pulumi/` |

### Updating the plugin

When a new version is released:

```
/plugin marketplace update
/plugin update coregy-workflow@coregy
# Then restart Claude Code
```

---

## Project Structure

```
coregy-workflow/
├── .claude-plugin/
│   └── marketplace.json              # Marketplace: name "coregy"
├── plugins/
│   └── coregy-workflow/
│       ├── .claude-plugin/
│       │   └── plugin.json           # Plugin metadata (v0.13.0)
│       ├── agents/                   # 9 specialized agents
│       │   ├── contracts/            # 6 agent handoff contracts (.yaml)
│       │   ├── architect.md
│       │   ├── researcher.md
│       │   ├── frontend.md
│       │   ├── backend.md
│       │   ├── code-reviewer.md
│       │   ├── spec-verifier.md
│       │   ├── unit-tester.md
│       │   ├── integration-tester.md
│       │   └── devops.md
│       ├── output-styles/            # 4 output templates
│       │   ├── review-report.md
│       │   ├── test-report.md
│       │   ├── design-doc.md
│       │   └── ci-report.md
│       ├── skills/
│       │   ├── project-profile/
│       │   │   ├── SKILL.md
│       │   │   └── scripts/
│       │   │       ├── detect_stack.py       # CLI wrapper
│       │   │       ├── state.py              # Workflow state machine
│       │   │       ├── kb_index.py           # KB index builder
│       │   │       ├── kb_archive.py         # KB auto-archival
│       │   │       ├── contracts.py          # Agent I/O contract validator
│       │   │       ├── quality_rules.py      # Configurable quality rules
│       │   │       ├── ci_monitor.py         # CI feedback loop
│       │   │       ├── team.py               # Team roles & permissions
│       │   │       ├── health.py             # Project health dashboard
│       │   │       └── detectors/            # Modular detection (20 modules)
│       │   └── knowledge-base/
│       │       ├── scripts/
│       │       │   └── kb_sync.py
│       │       └── templates/        # 6 KB template files
│       ├── hooks/
│       │   ├── hooks.json
│       │   ├── inject_project_context.py     # SessionStart + auto-refresh
│       │   └── quality_gate.py               # Pre-commit quality gate (v2)
│       └── commands/                 # 16 commands
│           ├── init.md
│           ├── start-feature.md
│           ├── status.md
│           ├── resume.md
│           ├── refresh.md
│           ├── kb-search.md
│           ├── connect.md
│           ├── ci-report.md
│           ├── sync.md
│           ├── update-kb.md
│           ├── health.md
│           ├── track.md
│           ├── history.md
│           ├── rules.md
│           ├── team.md
│           └── migrate.md
├── test/                             # 854 tests across 34 files
├── docs/
│   ├── PROPOSAL.md
│   ├── ARCHITECTURE.md
│   ├── ROADMAP.md
│   └── USER_GUIDE.md
├── CLAUDE.md
└── README.md
```

---

## Development

```bash
# Run all tests
python3 -m unittest discover -s test -v

# 802 tests covering: per-language detectors, monorepo, devops,
# serializer, quality gate, KB sync, auto-refresh, workflow state,
# KB index/archive, deep analysis, contracts, quality rules,
# CI monitor, team roles, health dashboard, tracker, graphify,
# rules, auto-track, MCP setup, git-commit detection,
# and the runtime CLI surface (real subprocess invocations)
```

---

## License

MIT
