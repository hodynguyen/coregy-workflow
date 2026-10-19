# API Contracts

No API endpoints detected — this is a Claude Code plugin project, not a web application.

The plugin exposes functionality through:

## Commands (slash commands)

| Command | Description |
|---------|-------------|
| `/coregy-workflow:init` | Detect stack, create profile + populate knowledge base |
| `/coregy-workflow:start-feature` | Start guided feature development workflow |
| `/coregy-workflow:status` | View profile + KB summary + next steps |
| `/coregy-workflow:refresh` | Re-detect stack, update profile.yaml |
| `/coregy-workflow:kb-search` | Search across knowledge base files |
| `/coregy-workflow:connect` | Configure MCP server integrations (GitHub, Linear, Jira) |
| `/coregy-workflow:ci-report` | Generate CI-compatible test report (GitHub Actions, JUnit XML, Markdown) |
| `/coregy-workflow:sync` | Sync knowledge base with shared location for team collaboration |
| `/coregy-workflow:update-kb` | Rescan codebase and update knowledge base files |

## Hooks

| Hook | Trigger | Script |
|------|---------|--------|
| SessionStart | Every new Claude Code session | `inject_project_context.py` — reads profile.yaml, injects into system message |
| PreCommit | Before git commit (quality gate) | `quality_gate.py` — runs code-reviewer checks on staged files |

## Scripts (CLI)

| Script | Usage |
|--------|-------|
| `detect_stack.py --cwd <path>` | Scan project files and generate `.coregy/profile.yaml` |
| `quality_gate.py <file1> <file2> ...` | Run quality checks on specified files |
| `kb_sync.py --mode <git\|gist\|repo> --cwd <path>` | Sync knowledge base with shared location |

---
tags: [cli, argparse, scripts, wiring, coregy-cli-v1]
created: 2026-07-26
author_agent: backend
status: active
---

## Workflow Script CLI Surface (coregy-cli-v1)

Added in v0.13.0. Seven previously library-only scripts now expose an argparse CLI so
commands and agents can invoke them instead of doing the work by hand in prose.

All live in `plugins/coregy-workflow/skills/project-profile/scripts/`. All accept `--cwd`
(default `.`) both before and after the subcommand. Exit codes: `0` success (including
advisory warnings and "nothing to do"), `1` expected failure, `2` argparse usage error.
Running a script with no subcommand prints help and exits 1.

**Implementation note (`--cwd` on both sides).** Making that true requires
`default=argparse.SUPPRESS` on the shared parent parser's `--cwd`, plus
`os.path.abspath(getattr(args, "cwd", "."))` at the call site. With a concrete
default, argparse re-applies it inside the subparser's own namespace and silently
overwrites a `--cwd` given *before* the subcommand, so the script operates on the
process cwd instead — a wrong-target bug with no error message. `parser.set_defaults`
is **not** a fix: it mutates the shared action's `.default`, which every subparser
holds by reference. Regression test:
`test_cli_surface.TestCliConventions.test_cwd_works_before_the_subcommand_too`.

`tracker.py` is the exception: it does not put `--cwd` on its top-level parser at
all, so `tracker.py --cwd X init` is a loud exit-2 usage error rather than a silent
wrong target. Always pass `--cwd` *after* the subcommand for `tracker.py`.

### `state.py` — workflow state machine

| Subcommand | Args | Notes |
|---|---|---|
| `init-workflow` | `--feature` `--type` `--phases` (all required), `--spec-file`, `--log-file`, `--mode {auto,guided,manual}`, `--spec-confirmed`, `--no-log`, `--force` | Writes `state.json` + creates the feature log. Exits 1 if an `in_progress` workflow exists and `--force` was not passed. `--phases` is a JSON object string |
| `start-agent <agent>` | — | JSON `{ok, agent, phase, warnings, checkpoint, state}`. Phase-ordering warnings are captured off stdout so the JSON stays clean |
| `complete-agent <agent>` | `--summary`, `--kb-files` (CSV) | |
| `skip-agent <agent>` | — | |
| `confirm-spec` | `--spec-file` (required) | |
| `set-mode <auto\|guided\|manual>` | — | |
| `next-agent` | `--json` | Text `PHASE agent` or `none`. **Always exits 0** so loop conditions stay simple |
| `complete` | — | Finalizes the feature log and sets status `completed` |
| `abort` | — | |
| `log-append` | `--agent` `--phase` `--summary` (required), `--files-created`, `--files-modified`, `--kb-updated` (CSV), `--decision` (repeatable), `--log-file` | Silent no-op when the log file does not exist |
| `show` | `--json` | **Exits 1 when there is no workflow** — this is the "no active workflow" signal |

Mutating subcommands heal a legacy `state.json` on disk first (missing `execution_mode`,
`spec_file`, `log_file`, `spec_confirmed`, `workflow_id`, `phase_order`, per-phase keys).
`show` and `next-agent` normalize in memory only and never write.

### `health.py`

| Subcommand | Args |
|---|---|
| `report` | `--section {all,kb,tech-debt,workflows,dependencies,recommendations}`, `--json` |

Exits 1 with `No .coregy/ directory -- run /coregy-workflow:init first` when uninitialized.

### `kb_index.py`

| Subcommand | Args | Notes |
|---|---|---|
| `build` | `--kb-dir`, `--json` | Writes `_index.json` |
| `search` | `--tag`, `--agent`, `--status`, `--kb-dir`, `--json` | Exits 1 when `_index.json` is missing. No filters = list everything |

### `kb_archive.py`

| Subcommand | Args | Notes |
|---|---|---|
| `check` | `--kb-dir`, `--threshold` (500), `--json` | **Read-only** |
| `run` | `--kb-dir`, `--threshold`, `--keep-sections` (3), `--json` | Mutates: moves old sections to `archive/` |

Always run `kb_archive.py run` **before** `kb_index.py build` — archival rewrites files.

### `contracts.py`

| Subcommand | Args | Notes |
|---|---|---|
| `validate` | `--from` `--to` (required), `--contracts-dir`, `--kb-dir`, `--strict`, `--json` | **Advisory: exits 0 even with warnings.** `--strict` (CI only) exits 1 on failure. Agents must never pass it |
| `list` | `--contracts-dir`, `--json` | |

Contracts default to the plugin's `agents/contracts/`, resolved from `__file__`.

### `ci_monitor.py` (requires the `gh` CLI)

| Subcommand | Args | Notes |
|---|---|---|
| `status` | `--raw`, `--json` | Read-only. **Always exits 0** — "gh not installed" is a normal state to branch on |
| `summary` | `--json` | Read-only |
| `feedback` | `--json` | **Side-effecting**: appends a `## CI Failures` section to `tech-debt.md`. Not idempotent — call at most once per report, gated on `status == "failure"` |

### `team.py`

| Subcommand | Args | Notes |
|---|---|---|
| `init` | `--force` | Exits 1 if `team.yaml` exists without `--force` |
| `show` | `--json` | Works without `team.yaml` (returns built-in defaults) |
| `check-agent <agent>` | `--user`, `--json` | **Exit 0 = allowed, 1 = denied** |
| `check-workflow <skip_agent\|abort_workflow\|modify_contract>` | `--user`, `--json` | Same exit contract |

Never chain `check-agent` / `check-workflow` under `&&` or `set -e` — a denial exits 1 and
would abort the surrounding command.
