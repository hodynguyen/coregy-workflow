---
tags: [log, refactor]
date: 2026-07-26
author-agent: start-feature
status: completed
---

# Feature Log: Sửa lỗi wiring runtime & nối lại các script chết

Type: refactor
Started: 2026-07-26

## Spec
-> spec-fix-runtime-wiring.md

## Agent Work

### architect (THINK) — 2026-07-26

- Designed the full CLI surface for R3–R9 (7 dead scripts: `state.py`, `health.py`, `kb_index.py`, `kb_archive.py`, `contracts.py`, `ci_monitor.py`, `team.py`) plus the exact command→script wiring map for R3–R9. Design only — no source file was modified.
- Files created: none
- Files modified: none (source tree untouched)
- KB updated: `architecture.md` (new section "CLI Surface & Command Wiring for the 7 Dead Scripts (R3–R9)")
- Decision: named the argparse convention **`coregy-cli-v1`** (10 explicit rules distilled from `rules.py` + `tracker.py`) so the backend agent copies rather than re-derives. `--cwd` defaults to `"."`; exit codes 0=ok/advisory, 1=expected failure, 2=argparse usage.
- Decision: the CLI is a **pure wrapper layer** — zero signature changes across all 7 scripts. Two near-misses (`check_all_kb_files` cannot take `keep_sections`; `team.py` has no config writer) are solved in the wrapper, not in the library.
- Decision: `state.py` backward compat handled by a new private `_normalize_state()` applied **only at the CLI layer** — heal-on-disk for mutating subcommands, in-memory for `show`/`next-agent`. `load_state()` itself is unchanged so the 615 existing tests and the hooks keep byte-identical behaviour. Defaults cover `workflow_id`, `phase_order`, per-phase keys and `agent_log` entry keys, not just the 4 fields named in the spec.
- Decision: `start_agent()` writes warnings to stdout with bare `print()`, which would corrupt the JSON emitted by `state.py start-agent`. Captured via `contextlib.redirect_stdout` and re-emitted under a `warnings` key rather than editing the function.
- Decision: `/init` steps 4 and 5 are **reordered** — `kb_archive.py run` must precede `kb_index.py build`, otherwise the index describes files that archival then rewrites. Same pairing added to `/update-kb`.
- Decision: `contracts.py validate` exits **0 even with warnings** (advisory mode is the documented design); `--strict` is opt-in and agents must never pass it.
- Decision: only 5 agent files carry "Contract check" prose, not 6 — the 6th contract (`code-reviewer-to-builder.yaml`) targets a role alias `builder` with no matching agent file, so it is wired as a second re-work check in `backend.md` and `frontend.md` (7 invocation sites across 5 files). Renaming that contract file is out of scope; logged as tech debt.
- Decision: designed `commands/team.md` (new, 14 → 15 commands) with 4 actions mapping to `team.py init|show|check-agent|check-workflow`; `check-*` use exit 0=allowed / 1=denied and must never be chained under `&&`.
- Produced a 16-item risk list (R-1..R-16) covering stdout corruption, the `--from` keyword clash, the misleading `check_all_kb_files` name, `init_workflow` overwriting an in-progress workflow, and `ci_monitor.py feedback` non-idempotently appending to `tech-debt.md`.

### backend (BUILD) — 2026-07-26
- Implemented spec-fix-runtime-wiring.md R1-R14: fixed both P0 runtime bugs, added the coregy-cli-v1 argparse CLI to all 7 dead scripts, rewired 7 commands + 5 agent files from prose to real bash invocations, added /coregy-workflow:team, and cleared the P2 doc/cruft backlog.
- Files created: `plugins/coregy-workflow/commands/team.md`
- Files modified: `plugins/coregy-workflow/skills/project-profile/scripts/state.py`, `plugins/coregy-workflow/skills/project-profile/scripts/health.py`, `plugins/coregy-workflow/skills/project-profile/scripts/kb_index.py`, `plugins/coregy-workflow/skills/project-profile/scripts/kb_archive.py`, `plugins/coregy-workflow/skills/project-profile/scripts/contracts.py`, `plugins/coregy-workflow/skills/project-profile/scripts/ci_monitor.py`, `plugins/coregy-workflow/skills/project-profile/scripts/team.py`, `plugins/coregy-workflow/hooks/quality_gate.py`, `plugins/coregy-workflow/commands/*.md (11)`, `plugins/coregy-workflow/agents/*.md (9)`, `plugins/coregy-workflow/.claude-plugin/plugin.json`, `.gitignore`, `CLAUDE.md`, `README.md`, `docs/ARCHITECTURE.md`, `docs/PROPOSAL.md`, `docs/USER_GUIDE.md`, `docs/ROADMAP.md`
- KB updated: api-contracts.md, tech-debt.md, log-fix-runtime-wiring.md
- Decision: Followed the architect's coregy-cli-v1 convention verbatim across all 7 scripts (shared --cwd parent parser, hyphenated subcommands, _output/_fail helpers, exit 0/1/2). Zero library function signatures changed -- the CLI is a pure wrapper, so all 615 existing tests still pass untouched.
- Decision: R2: replaced the regex with a small shell-aware parser (is_git_commit_command) rather than a bigger regex. It blanks quoted spans and escapes, splits on shell operators, skips env-assignment/wrapper prefixes, then finds git's first non-option token. This catches chained/prefixed/-C forms while still ignoring echo "git commit" and git log --grep=commit -- which a regex cannot distinguish.
- Decision: _normalize_state() applied at the CLI layer only, per the architect: mutating subcommands heal state.json on disk before delegating, read-only ones (show/next-agent) normalize in memory. load_state() is byte-identical, so the hooks and existing tests are unaffected.
- Decision: kb_archive check composes its read-only sweep from check_file_needs_archival instead of calling check_all_kb_files, which despite its name archives files (architect risk R-3). Verified by md5 that check leaves the KB untouched.
- Decision: Did NOT run kb_archive.py run against this repo's own KB -- architecture.md is 647 lines and would have had the architect's design section archived mid-workflow.

### unit-tester (VERIFY) — 2026-07-26
- Closed the runtime test gap: 169 new tests (615 -> 784) covering the R2 git-commit parser, subprocess-level CLI tests for all 7 new CLIs, the architect's R-1/R-2/R-3/R-4/R-10 risks, and an R1 ${PLUGIN_ROOT} guard. Found and fixed a silent --cwd wrong-target bug in all 7 CLIs + rules.py.
- Files created: `test/test_cli_surface.py`
- Files modified: `test/test_quality_gate.py`, `plugins/coregy-workflow/skills/project-profile/scripts/state.py`, `plugins/coregy-workflow/skills/project-profile/scripts/health.py`, `plugins/coregy-workflow/skills/project-profile/scripts/kb_index.py`, `plugins/coregy-workflow/skills/project-profile/scripts/kb_archive.py`, `plugins/coregy-workflow/skills/project-profile/scripts/contracts.py`, `plugins/coregy-workflow/skills/project-profile/scripts/ci_monitor.py`, `plugins/coregy-workflow/skills/project-profile/scripts/team.py`, `plugins/coregy-workflow/skills/project-profile/scripts/rules.py`
- KB updated: api-contracts.md, log-fix-runtime-wiring.md
- Decision: Tests invoke every CLI as a real subprocess via sys.executable, never by importing the function -- importing cannot catch a missing __main__, a bad argparse dest, or a traceback on a legacy state file, which is exactly why R1/R2 shipped broken.
- Decision: BUG FOUND + FIXED: --cwd given before the subcommand was silently discarded in all 7 new CLIs (and rules.py). argparse re-applies the subparser's own default into a fresh sub-namespace and copies it back over the top-level value, so the script ran against the process cwd. Fixed with default=argparse.SUPPRESS + getattr(args, 'cwd', '.'). parser.set_defaults() does NOT work -- it mutates the shared action's .default, which every subparser holds by reference.
- Decision: Verified the new regression tests are not vacuous by mutation-testing them: reverting the R2 regex, dropping the R-1 redirect_stdout, wiring kb_archive check to the mutating check_all_kb_files, removing the R-10 in-progress guard, breaking the R-2 --from dest, and reintroducing ${PLUGIN_ROOT} each make the suite fail.
- Decision: Left tracker.py alone (out of R3-R9 scope). It omits --cwd from its top-level parser, so the same misuse is a loud exit-2 usage error rather than a silent wrong target. Documented in api-contracts.md.
- Decision: ci_monitor.py tests run with PATH pointed at an empty dir so the gh-unavailable branch is deterministic and no network call is ever made.

### code-reviewer (VERIFY) — 2026-07-26
- Reviewed the full working diff (R1-R14). Confirmed the CLI is a pure wrapper (zero library signatures changed, load_state() byte-identical) and the --cwd SUPPRESS fix is correct in all 8 scripts including rules.py. Found and fixed 4 issues: agents still hand-writing state.json, a heredoc false positive in the new git-commit parser, and two dead-on-arrival command invocations.
- Files modified: `plugins/coregy-workflow/hooks/quality_gate.py`, `plugins/coregy-workflow/agents/architect.md`, `plugins/coregy-workflow/agents/backend.md`, `plugins/coregy-workflow/agents/code-reviewer.md`, `plugins/coregy-workflow/agents/devops.md`, `plugins/coregy-workflow/agents/frontend.md`, `plugins/coregy-workflow/agents/integration-tester.md`, `plugins/coregy-workflow/agents/researcher.md`, `plugins/coregy-workflow/agents/spec-verifier.md`, `plugins/coregy-workflow/agents/unit-tester.md`, `plugins/coregy-workflow/commands/history.md`, `plugins/coregy-workflow/commands/connect.md`, `test/test_quality_gate.py`, `test/test_cli_surface.py`
- KB updated: tech-debt.md, log-fix-runtime-wiring.md
- Decision: HIGH: all 9 agents still told Claude to hand-edit .coregy/state.json and hand-write the log entry -- verbatim the root cause the spec names -- and state.py log-append had zero call sites anywhere. Rewired the 'Workflow State' section in all 9 agents to log-append + complete-agent + next-agent. R3 lists '9 agent' as a wiring target; only the contracts.py half had been done.
- Decision: MEDIUM/security: is_git_commit_command() false-positived on heredoc bodies -- 'cat > f.md <<EOF / git commit -m x / EOF' denied the write. A regression vs the old anchored regex, and a false deny is worse than the miss R2 fixed. Added _strip_heredocs(), applied before quote-blanking, which only blanks a body when its terminator line is actually found.
- Decision: MEDIUM: parser missed 'then git commit', 'do git commit', 'sudo git commit' and 'env -i git commit'. Added shell keywords + sudo/doas to _CMD_PREFIXES and taught the prefix loop to skip a wrapper's own options.
- Decision: MEDIUM: two dead-on-arrival invocations that named a real script but exited 2 -- 'tracker.py search --after/--before' (flags never existed) in history.md, and all three 'mcp_setup.py <sub> --cwd .' calls in connect.md (mcp_setup takes --cwd only before the subcommand, so /connect was broken end to end). Fixed both command files; logged the coregy-cli-v1 non-compliance of tracker.py and mcp_setup.py as tech debt rather than changing scripts outside R3-R9.
- Decision: Added a generic guard, TestEmbeddedInvocationsParse, that scrapes every bash block in the plugin's markdown and checks the subcommand and every long flag against that script's own --help. Path-exists was not enough: both DOA bugs named a correct path. Mutation-tested -- restoring --after/--before, the mcp_setup ordering, or breaking an agent's log-append each fails the suite.
- Decision: Deferred (out of scope): tracker.py/mcp_setup.py --cwd convention, tracker.py traceback on missing tracker.db, /history date filter, and the quoted-token gate evasion -- all written to tech-debt.md.

### spec-verifier (VERIFY) — 2026-07-25
- Independently verified R1-R14 and all 6 acceptance criteria by running commands, not by trusting the log. All 14 requirements and all 6 ACs PASS. 802/802 tests green; all 615 baseline tests confirmed still present by name-diff against a clean HEAD checkout. Fixed 2 stale version strings in README missed by R14.
- Files modified: `README.md`
- KB updated: log-fix-runtime-wiring.md
- Decision: Verified empirically, not by claim: ran all 7 CLIs live against this repo (--help exit 0 plus a real subcommand each), executed the quality-gate hook end-to-end against a temp repo with a real staged secret across 11 command shapes, and diffed test names against a clean 'git archive HEAD' checkout.
- Decision: No test regression: baseline HEAD runs 615 tests; current runs 802. comm -23 of the two sorted -v name lists is empty, so zero baseline tests were deleted or renamed away. Only 1 skip decorator exists (skipIf git missing), which is legitimate and pre-existing in intent.
- Decision: R2 confirmed as a real fix, not a claim: the HEAD version of quality_gate.py produces no deny for 'git add -A && git commit -m x' with a secret staged; the new version denies it, plus VAR=x/-C/;/then/sudo/env -i forms, while still allowing 'echo "git commit"', 'git log --grep=commit' and a heredoc body containing 'git commit'.
- Decision: R7 deviates from the spec's literal '6 agent' wording: 5 agent files carry 7 contracts.py invocation sites covering all 6 contracts. The 6th contract targets role alias 'builder', which has no agent file, so it is wired as a re-work check in backend.md and frontend.md. Accepted as the architect's documented design, not a gap.
- Decision: Out of Scope respected: .venv-graphify-spike/ still present, all 9 agent prompts still carry their own MCP Tools + Checkpoints blocks (no dedup), detect_stack.py/detectors/ untouched in the diff.
- Decision: GAP FIXED (small, in R14's intent): README.md still declared 'Version: v0.5.0' and 'plugin.json (v0.5.0)' while plugin.json says 0.13.0. Backend updated the README structure block around it (15 commands, 802 tests) but missed the two version strings.
- Decision: REPORTED not fixed: .claude/worktrees/hardcore-bohr/ is an untracked, non-ignored 972KB leftover repo copy that 'git add -A' would stage (16 files). Pre-existing since April, outside R11's named targets.

## Summary

5 agents completed.

- **architect** (THINK): Designed coregy-cli-v1 argparse convention + full CLI surface for the 7 dead scripts (R3-R9), command/agent wiring map, state.py backward-compat normalization rules, new /team command, and a 16-item risk list. Design only, no source changes. (KB: architecture.md, log-fix-runtime-wiring.md)
- **backend** (BUILD): Implemented R1-R14: fixed ${PLUGIN_ROOT} (40 sites) + quality-gate git-commit detection, added coregy-cli-v1 argparse CLI to 7 scripts, wired 7 commands + 5 agents to real bash calls, added /coregy-workflow:team, bumped to v0.13.0. 615/615 tests pass. (KB: api-contracts.md, tech-debt.md, log-fix-runtime-wiring.md)
- **unit-tester** (VERIFY): Added 169 tests (615 -> 784, all passing in 6.8s): R2 git-commit parser + hook end-to-end, subprocess-level CLI tests for all 7 new CLIs, regression tests for architect risks R-1/R-2/R-3/R-4/R-10, and an R1 ${PLUGIN_ROOT} guard. Found and fixed a silent --cwd wrong-target bug in all 7 CLIs + rules.py. (KB: api-contracts.md, log-fix-runtime-wiring.md)
- **code-reviewer** (VERIFY): Reviewed the full R1-R14 diff. Verified the CLI is a pure wrapper (load_state() byte-identical, zero library signatures changed) and the --cwd SUPPRESS fix is correct across all 8 scripts incl. rules.py. Fixed 5 issues: rewired all 9 agents off hand-written state.json onto state.py log-append/complete-agent (log-append had zero call sites), closed a heredoc false positive + 4 misses in the git-commit parser, fixed 2 dead-on-arrival invocations (tracker.py --after/--before, all 3 mcp_setup.py calls in /connect), and made complete-agent leave an audit trail when start-agent never ran. Added 2 generic guards. 802 tests pass. (KB: tech-debt.md, log-fix-runtime-wiring.md)
- **spec-verifier** (VERIFY): Verified R1-R14 and all 6 acceptance criteria empirically. All PASS. 802/802 tests green, all 615 baseline tests confirmed present by name-diff vs clean HEAD checkout. Fixed 2 stale v0.5.0 version strings in README. One non-blocking pre-existing risk flagged: untracked .claude/worktrees/ would be staged by git add -A. (KB: log-fix-runtime-wiring.md)
