# Architecture

## System Overview

Coregy Workflow is a Claude Code plugin that provides project-aware development workflows with 9 specialized AI agents. It auto-detects tech stacks, maintains a persistent knowledge base, and guides developers through THINK → BUILD → VERIFY → SHIP phases.

## Component Diagram

```
claude-workflow/
├── .claude-plugin/marketplace.json     → Marketplace registration (name: "coregy")
├── plugins/coregy-workflow/
│   ├── .claude-plugin/plugin.json      → Plugin metadata (version, author)
│   ├── agents/                         → 9 agent prompt files (.md)
│   │   ├── THINK: researcher, architect
│   │   ├── BUILD: frontend, backend
│   │   ├── VERIFY: code-reviewer, spec-verifier, unit-tester, integration-tester
│   │   └── SHIP: devops
│   ├── commands/                       → 9 slash commands
│   │   ├── init.md, start-feature.md, status.md, refresh.md, kb-search.md
│   │   ├── connect.md, ci-report.md, sync.md, update-kb.md
│   ├── output-styles/                  → 4 output templates
│   │   ├── review-report.md, test-report.md, design-doc.md, ci-report.md
│   ├── skills/
│   │   ├── project-profile/
│   │   │   ├── SKILL.md
│   │   │   └── scripts/
│   │   │       ├── detect_stack.py     → Thin CLI wrapper (backward-compatible)
│   │   │       └── detectors/          → Modular detection package (20 modules)
│   │   │           ├── __init__.py, utils.py, profile.py, serializer.py
│   │   │           ├── node.py, go.py, python_lang.py, rust.py
│   │   │           ├── java.py, csharp.py, ruby.py, php.py
│   │   │           ├── devops.py, monorepo.py, database.py
│   │   │           ├── conventions.py, integrations.py, directories.py
│   │   └── knowledge-base/
│   │       ├── scripts/kb_sync.py      → Team KB sync script
│   │       └── templates/              → 6 KB template files
│   └── hooks/
│       ├── hooks.json                  → SessionStart hook config
│       ├── inject_project_context.py   → Injects profile into system message
│       └── quality_gate.py             → Pre-commit quality gate
└── test/                               → 110 unit tests across 17 test files
    ├── test_detect_stack.py            → Core detection tests
    ├── test_node_detector.py, test_go_detector.py, test_python_detector.py
    ├── test_rust_detector.py, test_java_detector.py, test_csharp_detector.py
    ├── test_ruby_detector.py, test_php_detector.py
    ├── test_monorepo.py, test_devops.py, test_conventions.py
    ├── test_directories.py, test_serializer.py
    ├── test_quality_gate.py, test_kb_sync.py, test_auto_refresh.py
```

## Three-Layer Design

```
Layer 1: PROJECT PROFILE (foundation)
  .coregy/profile.yaml — auto-detected tech stack
       ↓
Layer 2: KNOWLEDGE BASE (accumulative)
  .coregy/knowledge/*.md — 6 files that grow over time
       ↓
Layer 3: SPECIALIZED AGENTS (9 agents, 4 groups)
  Static Markdown prompts that adapt via profile.yaml at runtime
```

## Data Flow

```
Session starts
  → [SessionStart hook] reads .coregy/profile.yaml → injects into system message
  → User request → Claude Code determines task type
  → Loads appropriate agent (agents/*.md)
  → Agent reads profile.yaml + knowledge base
  → Agent performs work
  → Agent writes new knowledge to .coregy/knowledge/
  → Output to user
```

## Tech Stack Rationale

- **Markdown**: Claude Code plugin format for agents, commands, skills — no compilation needed
- **Python 3 (stdlib)**: Scripts for stack detection and hook injection — portable, no build step
- **PyYAML**: Only external dependency — needed to parse/write profile.yaml
- **YAML for profile**: Human-readable, easy to edit manually if detection is wrong
- **JSON for config**: Required by Claude Code plugin format (hooks.json, plugin.json)
- **No build step**: Plugins distributed as-is, loaded by Claude Code at startup


---
tags: [cli, argparse, wiring, refactor, commands, agents, state-machine, design]
created: 2026-07-26
author_agent: architect
status: active
---

# CLI Surface & Command Wiring for the 7 Dead Scripts (R3–R9)

Design for `spec-fix-runtime-wiring.md` requirements R3–R9. Scope: add an argparse CLI
to 7 scripts and replace prose blocks in commands/agents with real bash invocations.
**The CLI is a pure wrapper layer** — no existing function signature in these 7 scripts
changes, and no new business logic is introduced.

All paths below are relative to `plugins/coregy-workflow/`.
Script dir shorthand: `SCRIPTS = ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts`.

---

## 1. The `coregy-cli-v1` convention

Named so the backend agent can copy it verbatim. Derived from the two existing CLIs
(`rules.py`, `tracker.py`). Every new `main()` MUST follow all 10 points.

1. **Shared parent parser.** One `argparse.ArgumentParser(add_help=False)` holding
   `--cwd`, passed to the top-level parser *and* to every subparser via `parents=[...]`,
   so `--cwd` works both before and after the subcommand name:

   ```python
   parent = argparse.ArgumentParser(add_help=False)
   parent.add_argument("--cwd", default=".", help="Project root directory")
   parser = argparse.ArgumentParser(description="...", parents=[parent])
   sub = parser.add_subparsers(dest="command")
   sub.add_parser("build", parents=[parent], help="...")
   ```

   `--cwd` default is the string `"."` (as in `rules.py`), **not** `None` (as in
   `tracker.py`). `tracker.py` is not changed; new scripts standardise on `"."`.

2. **cwd resolution.** Always `cwd = os.path.abspath(args.cwd)` immediately after
   `parse_args()`. Never call `os.getcwd()` elsewhere.

3. **Subcommand naming.** Lowercase, hyphen-separated verbs
   (`build`, `check-agent`, `init-workflow`). Multi-word → hyphen, never underscore.
   Flags are `--kebab-case`; argparse maps them to `args.kebab_case` automatically.

4. **Positional vs flag.** The single primary noun of a subcommand is positional
   (`start-agent architect`, `check-agent backend`), mirroring `tracker.py`'s
   `update <id>`. Everything else is an optional flag with an explicit default.
   Required-but-not-primary values use `required=True`.

5. **JSON output.** Exactly `tracker.py`'s helper, copied into each script:

   ```python
   def _output(data):
       print(json.dumps(data, indent=2, default=str))
   ```

   Scripts that are inherently machine-facing (`state.py` mutators, `contracts.py`)
   print JSON unconditionally. Scripts with a human view expose `--json` to switch;
   default is text.

6. **Text output.** ASCII only — no emoji, no box-drawing except the `━` /
   `█░` already used by `health.format_health_report`. Use `->` for arrows and
   `--` for dashes, matching `health.py`.

7. **Exit codes.**
   | Code | Meaning |
   |------|---------|
   | `0` | Success, **including** "advisory warnings found" and "nothing to do" |
   | `1` | Expected failure: no workflow, file missing, invalid input, permission denied, validation failed under `--strict` |
   | `2` | argparse usage error (built-in, do not override) |

   Never raise an uncaught traceback for an expected condition.

8. **No subcommand.** `if args.command is None: parser.print_help(); sys.exit(1)`
   (as in `tracker.py`).

9. **Error handling.** One wrapper around the dispatch block:

   ```python
   def _fail(msg, json_mode=False):
       if json_mode:
           print(json.dumps({"ok": False, "error": msg}))
       else:
           print("Error: %s" % msg, file=sys.stderr)
       sys.exit(1)
   ```

   Dispatch is wrapped in `try: ... except (FileNotFoundError, ValueError, OSError,
   json.JSONDecodeError) as e: _fail(str(e), json_mode)`. Nothing else is caught —
   a genuine bug should still traceback.

10. **Module guard.** `main()` plus `if __name__ == "__main__": main()` at the bottom.
    Importing the module must stay side-effect free (all 7 have library-level tests).
    New imports allowed: `argparse`, `sys`, `json`, `io`, `contextlib`. Python 3.8
    compatible — no walrus in new code, no `dict | dict`, no `list[str]` annotations.

---

## 2. Per-script CLI surface

### R3 — `state.py` (11 subcommands)

New imports: `argparse`, `sys`, `io`, `contextlib`. All output is JSON except
`show` and `next-agent` without `--json`.

| Subcommand | Args | Wraps | Success output | Exit |
|---|---|---|---|---|
| `init-workflow` | `--feature TEXT` (req), `--type TEXT` (req), `--phases JSON` (req), `--spec-file NAME`, `--log-file NAME`, `--mode {auto,guided,manual}` (def `guided`), `--spec-confirmed` (flag), `--no-log` (flag), `--force` (flag) | `init_workflow()` then `create_feature_log()` | full state dict as JSON | 0; 1 if `--phases` is not a JSON object, if mode invalid, or if an `in_progress` state.json already exists without `--force` |
| `start-agent` | `agent` (pos) | `start_agent()` | `{"ok":true,"agent":..,"phase":..,"warnings":[..],"checkpoint":<obj or null>,"state":{..}}` | 0; 1 if agent not in any phase |
| `complete-agent` | `agent` (pos), `--summary TEXT` (def `""`), `--kb-files CSV` (def `""`) | `complete_agent()` | full state dict | 0; 1 if agent unknown |
| `skip-agent` | `agent` (pos) | `skip_agent()` | full state dict | 0; 1 if agent unknown |
| `confirm-spec` | `--spec-file NAME` (req) | `confirm_spec()` | full state dict | 0; 1 if no state.json |
| `set-mode` | `mode` (pos, `choices=VALID_MODES`) | `set_execution_mode()` | full state dict | 0; 1 if no state.json |
| `next-agent` | `--json` | `get_next_agent(load_state(cwd))` | text `THINK architect`, or `none`; JSON `{"phase":..,"agent":..}` / `{"phase":null,"agent":null}` | **always 0** (callers branch on content, not status) |
| `complete` | — | `complete_workflow()` | full state dict | 0; 1 if no state.json |
| `abort` | — | `abort_workflow()` | full state dict | 0; 1 if no state.json |
| `log-append` | `--agent` (req), `--phase` (req), `--summary` (req), `--files-created CSV`, `--files-modified CSV`, `--kb-updated CSV`, `--decision TEXT` (`action="append"`, repeatable), `--log-file NAME` | `append_feature_log()` | `{"ok":true,"log_file":<name>,"appended":true|false}` | 0 (silent no-op when the log file does not exist — matches the function's own contract) |
| `show` | `--json` | `load_state()` + normalise | text progress view (below); JSON = full normalised state | 0; **1 if state.json missing** (this is how `/resume` and `/status` detect "no workflow") |

`--phases` value shape: a JSON object string, e.g.
`'{"THINK":["architect"],"BUILD":["backend"],"VERIFY":["unit-tester","code-reviewer"]}'`.
`init_workflow` already derives `phase_order` from the canonical
`["THINK","BUILD","VERIFY","SHIP"]` order, so key order in the JSON does not matter.

CSV flags split on `,` and strip whitespace; empty string → `[]`.

`show` text format (ASCII markers, no emoji):

```
Workflow: feat-fix-runtime-wiring-20260726
Feature:  Sua loi wiring runtime & noi lai cac script chet
Type:     refactor   Status: in_progress   Mode: guided
Spec:     spec-fix-runtime-wiring.md (confirmed)
Log:      log-fix-runtime-wiring.md
Progress: 1/5 agents (20%)

  THINK   [x] architect
  BUILD   [ ] backend
  VERIFY  [ ] unit-tester  [ ] code-reviewer  [ ] spec-verifier
```

Markers: `[x]` completed, `[>]` active, `[-]` skipped, `[ ]` pending.

**`start-agent` stdout hazard (mandatory).** `start_agent()` calls bare `print(w)` for
its phase-ordering warnings (state.py:227-229). Emitting those into the JSON stream
corrupts it. The CLI must capture them without touching the function:

```python
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    updated_state, checkpoint = start_agent(cwd, args.agent)
warnings = [l for l in buf.getvalue().splitlines() if l.strip()]
```

and surface them under the `"warnings"` key.

### R4 — `health.py` (1 subcommand)

| Subcommand | Args | Wraps | Output | Exit |
|---|---|---|---|---|
| `report` | `--section {all,kb,tech-debt,workflows,dependencies,recommendations}` (def `all`), `--json` | `build_health_report()`, `format_health_report()` | text dashboard, or JSON report dict | 0; **1 if `<cwd>/.coregy/` does not exist** with message `No .coregy/ directory -- run /coregy-workflow:init first` |

- `--json` + `--section all` → `_output(build_health_report(cwd))`.
- `--json` + `--section X` → `_output({key: report[key]})` where the flag name maps to the
  report key: `kb`→`kb`, `tech-debt`→`tech_debt`, `workflows`→`workflows`,
  `dependencies`→`dependencies`, `recommendations`→`recommendations`.
- text + `--section X` → render `format_health_report(report)` in full, then **filter its
  lines** (do not duplicate formatting logic). Keep the first 3 lines (title, rule, blank)
  always, then keep lines by prefix:

  | section | kept line prefixes |
  |---|---|
  | `kb` | `Knowledge Base:` |
  | `tech-debt` | `Tech Debt:` |
  | `workflows` | `Workflows:`, `Agent Usage:`, and any line starting with 17 spaces (the `Warning: ... never used` continuation) |
  | `dependencies` | `Dependencies:` |
  | `recommendations` | the `Recommendations:` line and every following line starting with `  ->` |

### R5 — `kb_index.py` (2 subcommands)

Default `--kb-dir` = `<cwd>/.coregy/knowledge` for both.

| Subcommand | Args | Wraps | Output | Exit |
|---|---|---|---|---|
| `build` | `--kb-dir PATH`, `--json` | `write_index(kb_dir, cwd=cwd)` | text: `Indexed 8 file(s) -> .coregy/knowledge/_index.json` + optional `Graph: 412 nodes, 980 edges` when `graph_metadata` present; JSON = the full index dict | 0 (an empty/absent KB dir yields `entries: []`, still 0) |
| `search` | `--tag NAME`, `--agent NAME`, `--status NAME`, `--kb-dir PATH`, `--json` | `load_index()` + `search_index()` | text: one line per hit `architecture.md  tags=[cli,wiring]  agent=architect  status=active  (12 sections)`, then `N match(es).`; JSON = list of entry dicts | 0; **1 if `_index.json` is missing**, message `No index at <path> -- run: kb_index.py build --cwd .` |

`build` always passes `cwd=cwd` explicitly so graph metadata is looked up at
`<cwd>/graphify-out/graph.json` even when `--kb-dir` is non-standard (relying on
`write_index`'s two-levels-up inference would break for a custom `--kb-dir`).
With no filters, `search` returns all entries (that is the "list everything" mode).

### R6 — `kb_archive.py` (2 subcommands)

Default `--kb-dir` = `<cwd>/.coregy/knowledge`.

| Subcommand | Args | Wraps | Output | Exit |
|---|---|---|---|---|
| `check` | `--kb-dir PATH`, `--threshold INT` (def `DEFAULT_THRESHOLD`=500), `--json` | `check_file_needs_archival()` per `*.md` | text: `2 file(s) over 500 lines:` + `  architecture.md  612 lines`, or `All KB files under threshold (500 lines).`; JSON = `[{"file":..,"lines":..,"needs_archival":true}, ...]` | 0 always — **read-only** |
| `run` | `--kb-dir PATH`, `--threshold INT` (def 500), `--keep-sections INT` (def 3), `--json` | `archive_file()` per `*.md` | text: `Archived 1 file(s):` + `  architecture.md -> archive/architecture-archive-20260726-120000.md (4 sections moved, 180 lines remaining)`, or `Nothing to archive.`; JSON = list of the `archive_file` result dicts, each with `source_file` added | 0 |

**Do not call `check_all_kb_files()` for `check`** — despite the name it *mutates*
(it calls `archive_file` internally). `check` composes the read-only sweep from
`check_file_needs_archival`. `run` reimplements the same loop `check_all_kb_files`
does (sorted `*.md`, `archive_dir = <kb_dir>/archive`, add `source_file` to each
result) but passes `keep_sections` through, which `check_all_kb_files` cannot accept.
`check_all_kb_files` stays untouched for its existing tests.

### R7 — `contracts.py` (2 subcommands)

Defaults resolved from `__file__`, since contracts live in the plugin, not the project:

```python
_DEFAULT_CONTRACTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "agents", "contracts"))
```
(`scripts/` -> `project-profile/` -> `skills/` -> `coregy-workflow/agents/contracts`.)
`--kb-dir` default = `<cwd>/.coregy/knowledge`.

| Subcommand | Args | Wraps | Output | Exit |
|---|---|---|---|---|
| `validate` | `--from AGENT` (req, **`dest="from_agent"`**), `--to AGENT` (req), `--contracts-dir PATH`, `--kb-dir PATH`, `--strict` (flag), `--json` | `find_contract()` + `validate_handoff()` | text: `Contract architect -> backend: PASS` **or** `Contract architect -> backend: 2 warning(s)` + `  - [Missing section] 'Data Model' not found in KB`; when no contract file exists: `No contract for architect -> backend (nothing to check)`. JSON = `{"contract": "<name or null>", "passed": bool, "warnings": [..], "errors": [..]}` | **0 by default even with warnings** (advisory mode is the documented design); 1 only when `--strict` **and** `passed` is false |
| `list` | `--contracts-dir PATH`, `--json` | `list_contracts()` | text: one line per contract `architect -> backend    (architect-to-backend.yaml)` + `6 contract(s).`; JSON = `[{"from":..,"to":..,"contract":{..}}]` | 0 |

`validate` loads workflow state opportunistically to pass as `validate_handoff`'s
`state=` argument, using the same import dance already in `state.py`:

```python
try:
    from . import state as state_module
except ImportError:
    try:
        import state as state_module
    except ImportError:
        state_module = None
wf_state = state_module.load_state(cwd) if state_module else None
```

Agents MUST NOT pass `--strict`.

### R8 — `ci_monitor.py` (3 subcommands)

| Subcommand | Args | Wraps | Output | Exit |
|---|---|---|---|---|
| `status` | `--raw` (flag), `--json` | `get_ci_status()` | text: `CI: failure on branch main` + per-check `  [x] tests  completed/failure  <url>` (`[x]` fail, `[ok]` pass, `[~]` pending); when `None`: `CI status unavailable (gh CLI missing, not a git repo, or no runs).` JSON = the status dict with `raw_output` **stripped unless `--raw`**, or `{"available": false, "status": "unknown", "branch": null, "checks": []}` | **always 0** — "gh not installed" is a normal state the command layer branches on, not an error |
| `summary` | `--json` | `get_ci_summary()` | text: `CI summary: status=unknown, failures=0` (+ `Common failures: a, b` when non-empty); JSON = the summary dict | 0 |
| `feedback` | `--json` | `run_ci_feedback()` | text: `CI feedback: 3 failure(s) parsed, tech-debt.md updated` + `Suggestions:` + `  - <failure>: <suggestion>`; when nothing to do: `No CI failures to process.` JSON = the full result dict | 0 |

`feedback` is the only **side-effecting** subcommand — it appends a
`## CI Failures (<ts>)` section to `.coregy/knowledge/tech-debt.md`. `status` and
`summary` are read-only probes.

### R9 — `team.py` (4 subcommands)

| Subcommand | Args | Wraps | Output | Exit |
|---|---|---|---|---|
| `init` | `--force` (flag) | `generate_default_team_config()` + write | `Created .coregy/team.yaml` | 0; **1 if the file exists and `--force` was not given** (`team.yaml already exists (use --force to overwrite)`) |
| `show` | `--json` | `get_team_summary()` + `load_team_config()` | text block (below); JSON = `{"config_exists": bool, "summary": {..}, "roles": {..}, "members": [..]}` | 0 even without `team.yaml` (defaults are returned) |
| `check-agent` | `agent` (pos), `--user NAME`, `--json` | `get_current_user()` + `load_team_config()` + `can_use_agent()` | text `ALLOWED: Role 'lead' has access to all agents.` / `DENIED: ...`; JSON `{"allowed": bool, "reason": str, "user": str|null, "role": str, "agent": str}` | **0 allowed / 1 denied** |
| `check-workflow` | `action` (pos, `choices=["skip_agent","abort_workflow","modify_contract"]`), `--user NAME`, `--json` | `check_workflow_permissions()` | same shape as `check-agent` with `"action"` in place of `"agent"` | **0 allowed / 1 denied** |

`init` writes the file itself (`os.makedirs(<cwd>/.coregy, exist_ok=True)` then write
`generate_default_team_config()`) because `team.py` — unlike `rules.py` — has no
`write_default_team_config()` helper. This is wiring, not new business logic; do **not**
add such a helper.

`show` text:

```
Team (.coregy/team.yaml)
Current user: hodynguyen (role: developer)
Members: 0
Roles:
  lead       agents=all  skip=yes  contracts=yes  review=no
  developer  agents=5    skip=no   contracts=no   review=yes
  reviewer   agents=3    skip=no   contracts=no   review=no
  junior     agents=3    skip=no   contracts=no   review=yes
```

When `.coregy/team.yaml` is absent, prefix with `(no team.yaml -- showing built-in defaults)`.
`config_exists` is computed with `os.path.isfile`, since `load_team_config` silently
returns defaults for a missing file.

---

## 3. `state.py` backward-compatibility rules

The repo's own `state.json` was hand-written against the v0.6 template and, in the
general case, legacy files can be missing `execution_mode`, `spec_file`, `log_file`,
`spec_confirmed`, `workflow_id`, `phase_order`, or per-phase keys. Several existing
functions index those with `[]` and would raise `KeyError`:
`_find_agent_phase` / `_current_phase` / `get_next_agent` (`state["phase_order"]`,
`state["phases"][p]["agents"]`), `start_agent` / `complete_agent`
(`state["workflow_id"]`, `p["completed"]`, `p["active"]`, `entry["completed_at"]`).

Add **one new module-level helper** (a new private function is not a signature change):

```python
def _normalize_state(state):   # returns (state, changed: bool)
```

applying, in order:

1. `None` in → `(None, False)` out.
2. `state.setdefault` for: `status` → `"in_progress"`, `execution_mode` → `"guided"`,
   `spec_confirmed` → `False`, `spec_file` → `None`, `feature` → `""`,
   `type` → `"unknown"`, `created_at` / `updated_at` → `_now()`, `agent_log` → `[]`,
   `phases` → `{}`, `phase_order` → `[]`.
3. `execution_mode` not in `VALID_MODES` → coerce to `"guided"` (mirrors the existing
   `get_execution_mode()` default; never raise here).
4. `workflow_id` missing/empty → `_make_workflow_id(state["feature"])`, or the literal
   `"unknown-workflow"` when `feature` is empty. Required because `start_agent` /
   `complete_agent` / `complete` / `abort` all read `state["workflow_id"]` for
   checkpoint clearing.
5. `log_file` missing/`None` → `"log-%s.md" % _make_slug(state["feature"])`, matching
   `init_workflow`'s own default. Safe even if that file does not exist:
   `append_feature_log` and `finalize_feature_log` already `return` silently on a
   missing path.
6. `phase_order` empty → derive from `phases.keys()` sorted by the canonical
   `["THINK","BUILD","VERIFY","SHIP"]`, then any remaining keys in insertion order.
   Then drop any entry of `phase_order` that has no matching key in `phases`.
7. Per phase block: `setdefault("agents", [])`, `("completed", [])`, `("skipped", [])`,
   `("active", None)`; coerce any of the three list fields to `[]` if not a `list`.
8. Per `agent_log` entry (skip non-dicts): `setdefault` `agent` `""`, `phase` `""`,
   `started_at` `None`, `completed_at` `None`, `output_summary` `""`,
   `kb_files_modified` `[]`.

**Where it is applied — CLI layer only.** `load_state()` itself is NOT changed, so
library callers and existing tests see byte-identical behaviour.

- **Mutating subcommands** (`start-agent`, `complete-agent`, `skip-agent`,
  `confirm-spec`, `set-mode`, `complete`, `abort`, `log-append`) call a new CLI helper
  `_cli_load_and_repair(cwd)`: `load_state` → `_normalize_state` → if `changed`,
  `_write_state(cwd, state)` **before** delegating to the real function. The real
  function then re-reads a healed file through its own `load_state()`. This is a
  heal-once-on-disk strategy; it bumps `updated_at`, which is correct.
- **Read-only subcommands** (`show`, `next-agent`) normalise **in memory only** and
  never write, preserving read-only semantics.
- `init-workflow` does not normalise — it writes a fresh v0.10 schema.

Absent state.json: mutating subcommands exit 1 with the existing message
`No active workflow -- .coregy/state.json not found`; `show` exits 1; `next-agent`
exits 0 printing `none`.

---

## 4. Command → script wiring map

Every invocation uses `${CLAUDE_PLUGIN_ROOT}` (R1), never `${PLUGIN_ROOT}`.

### 4.1 `commands/init.md`

Steps 4 and 5 are **reordered** — archival must run *before* indexing, otherwise the
index built in step 4 is invalidated by the file rewrites in step 5.

| Location | Replace | With |
|---|---|---|
| lines 96–101 (old step 4 "Build KB index" prose) | whole block | new **step 4 — Archive oversized KB files**: `python3 $SCRIPTS/kb_archive.py run --cwd .` + one sentence: "Files over 500 lines keep their 3 most recent sections; older sections move to `.coregy/knowledge/archive/`." |
| line 103 (old step 5 "Check KB file sizes" prose) | whole block | new **step 5 — Build KB index**: `python3 $SCRIPTS/kb_index.py build --cwd .` + one sentence: "Writes `.coregy/knowledge/_index.json`, enabling `tag:` / `agent:` / `status:` search in `/coregy-workflow:kb-search`." |

Notes section (line ~163) gains: "Steps 4–5 must run in that order — indexing after
archival, never before."

### 4.2 `commands/update-kb.md`

Insert a new **Step 6 — Reindex** before the current Step 6 (renumber Summary to
Step 7), after all KB files have been rewritten by steps 2–5:

```bash
python3 $SCRIPTS/kb_archive.py run --cwd .
python3 $SCRIPTS/kb_index.py build --cwd .
```

Same ordering rule. The Step 7 summary block gains a line
`_index.json: rebuilt (N files indexed)`.

### 4.3 `commands/kb-search.md`

| Location | Replace | With |
|---|---|---|
| lines 29–37 (step 3, "Check for structured search") | the "If `_index.json` exists, read it and filter entries…" prose | `python3 $SCRIPTS/kb_index.py search --tag <t> --agent <a> --status <s> --json --cwd .` (pass only the filters the user supplied). "If it exits 1 (no index), run `python3 $SCRIPTS/kb_index.py build --cwd .` first, then retry the search." |
| line 94 (Notes) | "rebuild with `/coregy-workflow:init` or `/coregy-workflow:update-kb`" | add "or directly: `kb_index.py build --cwd .`" |

Step 4 (keyword/full-text search) stays prose — `kb_index.py` indexes metadata and
headings only, it has no full-text search.

### 4.4 `commands/health.md`

Replace **steps 2, 3 and 4 entirely** (lines 25–50) with a single invocation. Step 1
(init check) is kept as prose but is now also enforced by the script's exit 1.

```bash
python3 $SCRIPTS/health.py report --cwd .
```

- `$ARGUMENTS` names a section (`kb`, `tech-debt`, `workflows`, `dependencies`,
  `recommendations`) → append `--section <name>`.
- `$ARGUMENTS` asks for machine-readable output → append `--json`.
- `$ARGUMENTS` says "summary" → `--section` is not used; print the command output as-is
  (the default dashboard is already one line per metric).

The existing sample dashboard (lines 33–48) is kept, relabelled
"Example output of the command above" — it is documentation, not an instruction to
render by hand. The Notes gain: "This command runs `health.py`; it does not compute
metrics by reading files itself."

### 4.5 `commands/ci-report.md`

| Location | Change |
|---|---|
| after step 2 (Read profile) | new **step 2b — Probe CI**: `python3 $SCRIPTS/ci_monitor.py status --json --cwd .`. If `available` is `false` or `status` is `unknown`, continue with the existing local-test-run path (steps 3–6). |
| step 3 | prepend: "If step 2b returned real checks, report those first; only run the local suite when CI data is unavailable." |
| after step 6 | new **step 7 — Record failures**: when step 2b reported `status: failure`, run `python3 $SCRIPTS/ci_monitor.py feedback --cwd .` to parse the failed run's logs and append a `## CI Failures` section to `tech-debt.md`. Report `tech_debt_updated` and `suggestions` from its JSON. |
| Output block | add a `CI Status:` line sourced from `ci_monitor.py summary`. |
| Notes | add: "`ci_monitor.py feedback` requires the `gh` CLI and writes to `.coregy/knowledge/tech-debt.md`. It appends a new section on every run — do not loop it." |

### 4.6 `commands/start-feature.md`

| Location | Replace | With |
|---|---|---|
| step 10, lines 181–204 (hand-written `state.json` JSON template) **and** lines 206–225 (hand-written log-file markdown template) | both blocks | one call: `python3 $SCRIPTS/state.py init-workflow --feature "<description>" --type "<type>" --phases '{"THINK":["architect"],"BUILD":["backend"],...}' --spec-file "spec-<slug>.md" --mode <auto|guided|manual> --spec-confirmed --cwd .` — "This writes `.coregy/state.json` in the current schema and creates `.coregy/knowledge/log-<slug>.md` with the correct frontmatter. Do **not** hand-write either file." |
| step 10, lines 233–242 (tracker create) | keep as-is | only fix `${PLUGIN_ROOT}` → `${CLAUDE_PLUGIN_ROOT}` (R1) |
| step 11, line 245 ("Set it as `active` in state.json, add `agent_log` entry") | prose | `python3 $SCRIPTS/state.py start-agent <agent> --cwd .` — "If the JSON contains a non-null `checkpoint`, pass its `partial_output` / `resume_hint` / items to the agent." |
| step 11, line 248 ("Update state.json (completed, output_summary, kb_files_modified)") | prose | `python3 $SCRIPTS/state.py complete-agent <agent> --summary "<one line>" --kb-files "architecture.md,decisions.md" --cwd .` |
| step 11, line 249 ("Agent appends its work record to the log file") | prose | note that the agent does this itself via `state.py log-append` (see §4.8) |
| step 12, lines 270–271 ("Finalize the feature log", "Set workflow status to `completed`") | both bullets | `python3 $SCRIPTS/state.py complete --cwd .` — "This finalizes the feature log (Summary section + `status: completed` frontmatter) and sets the workflow status in one call." |

Step 8 (`auto` mode auto-confirm) needs no call — `init-workflow --spec-confirmed`
already covers it. `confirm-spec` exists for the `/resume` discovery branch.

### 4.7 `commands/resume.md`

Step 5 (lines 87–123) is rewritten around the CLI:

| Sub-step | Bash |
|---|---|
| read state (replaces "Read `.coregy/state.json`" in step 1 and the step 5 branch test) | `python3 $SCRIPTS/state.py show --json --cwd .` — exit 1 means "no active workflow"; branch on `spec_confirmed` |
| step 2 progress display | `python3 $SCRIPTS/state.py show --cwd .` (text view) |
| discovery branch, after user confirms | `python3 $SCRIPTS/state.py confirm-spec --spec-file "spec-<slug>.md" --cwd .` |
| 5a mode override | `python3 $SCRIPTS/state.py set-mode <auto|guided|manual> --cwd .` |
| `$ARGUMENTS` = `skip <agent>` | `python3 $SCRIPTS/state.py skip-agent <agent> --cwd .` |
| 5c identify remaining agents | loop on `python3 $SCRIPTS/state.py next-agent --json --cwd .` until `agent` is `null` |
| 5d per agent | `state.py start-agent <a> --cwd .` … `state.py complete-agent <a> --summary "…" --kb-files "…" --cwd .` (identical to start-feature step 11) |
| 5e complete workflow | `python3 $SCRIPTS/state.py complete --cwd .` |
| "restart `<agent>`" | existing `tracker.py checkpoint-clear --workflow-id <id> --agent <a>` (fix `${PLUGIN_ROOT}` only) |

### 4.8 Agents — prose "contract check" → `contracts.py validate`

Only 5 agent files carry the prose (grep `Contract check`). The 6th contract file,
`code-reviewer-to-builder.yaml`, is a re-work handoff consumed by **both** builders,
giving 7 invocation sites.

| File | Line | `--from` | `--to` | When |
|---|---|---|---|---|
| `agents/backend.md` | 16 (step 8) | `architect` | `backend` | bootstrap |
| `agents/frontend.md` | 15 (step 7) | `architect` | `frontend` | bootstrap |
| `agents/unit-tester.md` | 15 (step 7) | `backend` | `unit-tester` | bootstrap |
| `agents/integration-tester.md` | 15 (step 7) | `unit-tester` | `integration-tester` | bootstrap |
| `agents/code-reviewer.md` | 15 (step 7) | `spec-verifier` | `code-reviewer` | bootstrap |
| `agents/backend.md` | new sub-bullet under step 8 | `code-reviewer` | `builder` | only when re-working review findings |
| `agents/frontend.md` | new sub-bullet under step 7 | `code-reviewer` | `builder` | only when re-working review findings |

Replacement text (identical shape in all files, substituting the agent pair):

```bash
python3 $SCRIPTS/contracts.py validate --from architect --to backend --cwd .
```

followed by one sentence: "Advisory — exit code is always 0. If `warnings` is
non-empty, report them to the user and continue. Never pass `--strict`."

### 4.9 NEW `commands/team.md`

```markdown
---
description: View team roles and permissions (.coregy/team.yaml). Check whether the current user may use an agent or perform a workflow action.
argument-hint: "[action: 'show', 'init', 'check-agent <agent>', 'check-workflow <action>']"
---

# /coregy-workflow:team

## User Instructions
$ARGUMENTS
- empty or "show"            -> show
- "init"                     -> init
- "check-agent <name>"       -> check-agent
- "check <name>"             -> check-agent (alias)
- "check-workflow <action>"  -> check-workflow (skip_agent|abort_workflow|modify_contract)
- "--json" anywhere          -> append --json to the call

## Steps

### Action: show (default)
python3 $SCRIPTS/team.py show --cwd .
If it reports "(no team.yaml -- showing built-in defaults)", tell the user they can
run `/coregy-workflow:team init` to customise roles.

### Action: init
python3 $SCRIPTS/team.py init --cwd .
Exit 1 means the file already exists. Ask the user before re-running with `--force`,
because it overwrites their role definitions.

### Action: check-agent <agent>
python3 $SCRIPTS/team.py check-agent <agent> --cwd .
Exit 0 = allowed, exit 1 = denied. Print the `reason` either way. A denial is advisory
guidance for the user, not a hard block on invoking the agent.

### Action: check-workflow <action>
python3 $SCRIPTS/team.py check-workflow <action> --cwd .
Same exit contract.

## Output
(sample `show` block, sample ALLOWED/DENIED lines)

## Notes
- Roles are advisory; coregy does not enforce them at the tool layer.
- User identity: `$COREGY_USER` env var, else `git config user.name`.
- Unlisted users default to the `developer` role.
- `.coregy/team.yaml` should be committed for team sharing.
```

This raises the command count 14 -> 15. R10/R14 doc updates must include:
`CLAUDE.md` (two places: overview list and plugin-structure `commands/` line),
`README.md`, `docs/ARCHITECTURE.md`, `docs/PROPOSAL.md`, `docs/USER_GUIDE.md`.

---

## 5. Risk list

| # | Risk | Mitigation |
|---|---|---|
| R-1 | `start_agent()` writes warnings to stdout with bare `print()` (state.py:227-229), corrupting the JSON that `start-agent` emits. | Wrap the call in `contextlib.redirect_stdout(io.StringIO())`, re-emit the captured lines under the JSON `warnings` key. Do **not** change `start_agent`. |
| R-2 | `--from` is a Python keyword; `args.from` is a `SyntaxError`. | `add_argument("--from", dest="from_agent", required=True)`. |
| R-3 | `check_all_kb_files()` reads as a checker but **archives** files. Wiring it to `check` would silently rewrite the KB on a read-only command. | `check` composes the read-only sweep from `check_file_needs_archival`; only `run` mutates. Leave `check_all_kb_files` untouched (`test_kb_index.py`/archive tests depend on it). |
| R-4 | Legacy `state.json` (missing `workflow_id`, `phase_order`, per-phase keys, `agent_log` entry keys) raises `KeyError` inside `start_agent`/`complete_agent`/`get_next_agent`. | `_normalize_state` + heal-on-disk in the CLI mutators, in-memory only for readers. `load_state` itself unchanged. |
| R-5 | Archiving after indexing leaves `_index.json` describing rewritten files (wrong `total_lines`, stale sections). | Fixed order everywhere: `kb_archive.py run` **then** `kb_index.py build`. Encoded in init step 4/5 reorder and in the update-kb step 6 pair. |
| R-6 | `code-reviewer-to-builder.yaml` names a `to` agent (`builder`) that no agent file uses, so `find_contract(dir, "code-reviewer", "backend")` returns `None` and the check silently no-ops. | Wire backend/frontend to `--to builder` explicitly and document the alias. Renaming the file into two (`code-reviewer-to-backend.yaml` / `-to-frontend.yaml`) is the cleaner fix but is a behaviour change — **out of scope for this spec**; log it in `tech-debt.md` alongside R13. |
| R-7 | If `--strict` is wired into agent bootstraps, `validate_handoff` marks `passed=False` on *any* warning, so nearly every agent run would exit 1 and look like a hard failure. | Advisory is the default (exit 0). Agent prose says explicitly "never pass `--strict`". `--strict` exists for CI use only. |
| R-8 | `ci_monitor.py feedback` appends a new `## CI Failures` section to `tech-debt.md` on **every** invocation — not idempotent. | Only call it from `/ci-report` step 7, gated on `status == "failure"`. Never from a hook or a poll loop. Documented in the command Notes. |
| R-9 | `team.py check-agent` / `check-workflow` exit 1 on denial; under `set -e` or a chained `&&` this aborts the whole command. | Always invoke standalone, never chained. Documented in `commands/team.md`. |
| R-10 | `state.py init-workflow` maps to `init_workflow()`, which unconditionally overwrites `state.json` — a second `/start-feature` would destroy an in-progress workflow. | CLI-level guard: if `state.json` exists with `status == "in_progress"`, exit 1 with `Active workflow <id> in progress -- use --force to overwrite or /coregy-workflow:resume`. Guard lives in the CLI, `init_workflow` is unchanged. |
| R-11 | `state.py show` exits 1 when there is no workflow. Any command that chains it will look broken. | Documented as the intended "no workflow" signal; `/resume` and `/status` branch on it explicitly. `next-agent` deliberately exits 0 so loop conditions stay simple. |
| R-12 | `health.py report` exits 1 when `.coregy/` is missing, but `/health` step 1 already checks. | Both are kept; the command handles exit 1 by printing the "run /coregy-workflow:init first" guidance. |
| R-13 | `write_index(kb_dir, cwd=None)` infers the project root as two dirs above `kb_dir` — wrong for a custom `--kb-dir`, producing a bogus `graphify-out/` lookup. | CLI always passes `cwd=cwd` explicitly. |
| R-14 | Adding `main()` to modules that currently have none could execute on import and break the 615 existing tests. | Strict `if __name__ == "__main__":` guard; no module-level work beyond constant definitions. Subprocess-level tests (spec's Test section) verify `--help` exits 0 for all 7. |
| R-15 | `--phases` JSON is quoting-sensitive inside a bash tool call. | Single-quote the JSON, no interior single quotes; a `json.JSONDecodeError` is caught and reported as exit 1 with the offending text, not a traceback. Precedent: `tracker.py --items-json`. |
| R-16 | Text output that adds emoji or non-ASCII would break Windows consoles (cp1252). | ASCII-only per convention point 6, except the block characters already shipped in `health.format_health_report`. |

### Signature-change flags (none required)

No function in the 7 scripts needs its signature changed. Two near-misses, both solved
in the wrapper:

- `check_all_kb_files(kb_dir, threshold)` cannot express `--keep-sections`. Solved by
  having the CLI loop over `archive_file(fpath, archive_dir, threshold, keep_sections)`
  directly, exactly as `check_all_kb_files` does internally.
- `team.py` has `generate_default_team_config()` but no writer (unlike
  `rules.write_default_config`). Solved by writing the file in the CLI.
