# Tech Debt

> To be filled as tech debt is identified during development.

## detect_stack.py detects "unknown" for plugin projects
- **Priority**: low
- **Area**: scripts
- **Description**: Running `detect_stack.py` on this repo itself returns `type: unknown` because there's no detection rule for Claude Code plugin projects
- **Impact**: Minor — this repo is the plugin source, not a target project. The detector is designed for app projects (React, Go, Python, etc.)
- **Suggested Fix**: Could add a detection rule for `.claude-plugin/plugin.json` → type: claude-code-plugin, but low value since this is an edge case

## No integration tests
- **Priority**: medium
- **Area**: testing
- **Description**: 110 unit tests exist across 17 test files covering individual detectors, quality gate, KB sync, and auto-refresh. However, no integration tests verify the full init flow (detect → create KB → populate)
- **Impact**: Changes to the init command or KB population logic are not automatically tested
- **Suggested Fix**: Add integration tests that run `/coregy-workflow:init` on mock projects and verify the full output

## Agent prompts duplicate ~35 lines across all 9 files
- **Priority**: medium
- **Area**: agents
- **Description**: Every file in `plugins/coregy-workflow/agents/` carries a near-identical "## MCP Tools" block (GitHub/Linear/Jira + the 8-tool Graphify list) and "## Checkpoints" block. That is roughly 35 duplicated lines x 9 files. Any change to the Graphify tool list or the `tracker.py checkpoint-save` flag set has to be applied nine times, and the current files have already drifted (the Graphify wording differs slightly between `architect.md` and `backend.md`)
- **Impact**: Every edit to shared agent guidance is a 9-file change with a real chance of missing one. Drift is silent — nothing tests agent prompt content
- **Suggested Fix**: Extract the shared blocks into a single include (e.g. `agents/_common/mcp-tools.md`, `agents/_common/checkpoints.md`) once the plugin format supports prompt composition; until then, add a test that asserts the blocks are byte-identical across the 9 files
- **Deferred from**: spec-fix-runtime-wiring.md R13 (explicitly out of scope for that spec)

## Contract file `code-reviewer-to-builder.yaml` targets a non-existent agent
- **Priority**: low
- **Area**: agents/contracts
- **Description**: `find_contract()` resolves `<from>-to-<to>.yaml`, so this contract can only be found by asking for the `to` agent `builder`. No agent is named `builder` — the real consumers are `backend` and `frontend`. Before this was wired explicitly, `contracts.py validate --from code-reviewer --to backend` returned `None` and the check silently passed with nothing validated
- **Impact**: The re-work handoff check is a no-op unless callers know to use the `builder` alias. It is currently wired that way in `agents/backend.md` and `agents/frontend.md`, which works but is non-obvious
- **Suggested Fix**: Split the file into `code-reviewer-to-backend.yaml` and `code-reviewer-to-frontend.yaml` and drop the alias. This is a behaviour change (it alters which contracts `list_contracts()` reports), so it needs its own spec
- **Flagged by**: architect, risk R-6 of the `coregy-cli-v1` design

---
tags: [cli, tracker, mcp, conventions, code-review]
created: 2026-07-26
author_agent: code-reviewer
status: active
---

## `tracker.py` and `mcp_setup.py` do not follow `coregy-cli-v1`
- **Priority**: medium
- **Area**: scripts
- **Description**: The 7 scripts wired by spec-fix-runtime-wiring R3–R9 (plus `rules.py`) put `--cwd` on a shared parent parser with `default=argparse.SUPPRESS`, so `--cwd` is accepted on either side of the subcommand. `tracker.py` accepts it only *after* the subcommand; `mcp_setup.py` accepts it only *before*. `commands/connect.md` documented all three `mcp_setup.py` invocations in the wrong order, so `/coregy-workflow:connect` exited 2 for every path — the same silent runtime failure as `${PLUGIN_ROOT}`. The command file has been corrected, but the inconsistency remains a trap for the next command author
- **Impact**: Every new command or agent that calls these two scripts must remember a per-script argument order that contradicts the documented convention
- **Suggested Fix**: Apply the `parents=[parent]` + `default=argparse.SUPPRESS` + `getattr(args, "cwd", ".")` pattern to `tracker.py` and `mcp_setup.py`. Both are outside R3–R9, so this needs its own spec. `test_cli_surface.TestEmbeddedInvocationsParse` now guards the markdown side either way
- **Found by**: code-reviewer, reviewing spec-fix-runtime-wiring

## `tracker.py` raises an unhandled traceback when `tracker.db` is missing
- **Priority**: low
- **Area**: scripts
- **Description**: `tracker_schema.get_db()` raises `FileNotFoundError` and `tracker.py main()` does not catch it, so `/coregy-workflow:track`, `/coregy-workflow:history` and every agent `checkpoint-save` print a full Python traceback in any project initialised before v0.6 (or where `/coregy-workflow:init` never ran). The message itself is actionable; the traceback around it is not
- **Impact**: A recoverable "run /coregy-workflow:init first" surfaces to the user as a crash
- **Suggested Fix**: Wrap `tracker.py main()`'s dispatch in the same `except (FileNotFoundError, ValueError, OSError)` → `_fail()` handler the 7 R3–R9 CLIs use. Out of scope for spec-fix-runtime-wiring (`tracker.py` is not in R3–R9)
- **Found by**: code-reviewer, reviewing spec-fix-runtime-wiring

## `/history` has no date-range filter
- **Priority**: low
- **Area**: commands
- **Description**: `commands/history.md` documented `tracker.py search --after/--before`, flags that never existed — the command exited 2. The doc now tells the LLM to widen `--limit` and filter `created_at`/`updated_at` itself, which works but scans more rows than needed
- **Impact**: Date filtering happens in the model's context instead of in SQL; on a large `tracker.db` the 200-row window can miss older matches
- **Suggested Fix**: Add `--after` / `--before` to `tracker.py search` and push the predicate into the query, then restore the direct invocation in `history.md`
- **Found by**: code-reviewer, reviewing spec-fix-runtime-wiring

## Quality gate can be evaded by quoting the `commit` token
- **Priority**: low
- **Area**: hooks
- **Description**: `is_git_commit_command()` blanks quoted spans before tokenising, so `git "commit" -m x` and `git c"o"mmit -m x` are not recognised and the secret scan never runs. Un-blanking quotes is not an option — it is what keeps `echo "git commit"` and `grep -rn "git commit"` from being denied
- **Impact**: None against accidental commits, which is what this gate is for. It is only reachable by deliberately obfuscating the command, and the gate already has a documented opt-out (`COREGY_SKIP_QUALITY_GATE=1`)
- **Suggested Fix**: None recommended. Word-splitting faithfully enough to close this needs a real shell parser, which is a much larger dependency than the risk justifies. Recorded so it is a known limit rather than an oversight
- **Found by**: code-reviewer, reviewing spec-fix-runtime-wiring

## Feature log entries are stamped with the UTC date, not the local date
- **Priority**: low
- **Area**: scripts
- **Description**: `append_feature_log()` and `create_feature_log()` in `state.py` build their date with `datetime.now(timezone.utc)`. For a UTC+07 author working in the evening, `state.py log-append` writes yesterday's date. This was invisible while agents hand-wrote their log entries with the local date; now that all 9 agents call `log-append`, every entry flips to UTC and no longer matches the `date:` frontmatter the spec/log were created with. The first entry written this way (`### code-reviewer (VERIFY)`) had to be corrected by hand
- **Impact**: Log entries can be off by one day and disagree with the frontmatter and with each other, which makes the chronology in a feature log misleading
- **Suggested Fix**: Either stamp headings with the local date (`datetime.now().strftime(...)`) or make every date in the KB — frontmatter included — UTC, so the two agree. Changing `state.py`'s date semantics touches library functions rather than the CLI wrapper, so it is outside spec-fix-runtime-wiring's "zero signature changes" mandate
- **Found by**: code-reviewer, while dogfooding `state.py log-append`
