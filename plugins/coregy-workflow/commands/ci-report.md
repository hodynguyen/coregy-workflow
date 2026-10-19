---
description: Generate a CI-compatible test report from test results. Supports GitHub Actions annotations, JUnit XML, and Markdown summary formats.
argument-hint: "[format: 'github' | 'junit' | 'markdown'] [optional: input file]"
---

# /coregy-workflow:ci-report

Generate a CI-compatible test report for the current project.

## User Instructions

$ARGUMENTS

If the section above contains text, apply it to the report generation:
- Format name (github, junit, markdown) → output in that format
- File path → use that file as the test results input
- "summary" → short top-level metrics only

If empty, auto-detect format from environment (GITHUB_ACTIONS env → github format) and look for common test result files.

## Steps

1. **Check initialization**: Verify `.coregy/profile.yaml` exists. If not, tell the user to run `/coregy-workflow:init` first.

2. **Read profile**: Read `.coregy/profile.yaml` to determine:
   - Testing framework (jest, vitest, pytest, go-test, cargo-test, junit, rspec, phpunit, etc.)
   - CI system (github-actions, gitlab-ci, jenkins, or none)

2b. **Probe CI**: Ask the CI provider for the real status of the current branch:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/ci_monitor.py status --json --cwd .
```

If `available` is `false` or `status` is `unknown`, no CI data exists — continue with the
local-test-run path in steps 3–6. This command always exits 0; branch on the JSON content.

3. **Detect test results**: If step 2b returned real checks, report those first; only run the
   local suite when CI data is unavailable.
   - If test result files exist (e.g., `test-results/`, `coverage/`, `junit.xml`), parse them
   - If no results exist, ask the user whether to run the test suite now

4. **Choose output format** based on CI system:

| CI System | Primary Format | Secondary Format |
|-----------|---------------|-----------------|
| GitHub Actions | GitHub annotations (stdout) | Markdown summary (`test-results/summary.md`) |
| GitLab CI | JUnit XML (`test-results/junit.xml`) | Markdown summary |
| Jenkins | JUnit XML (`test-results/junit.xml`) | — |
| None / Unknown | Markdown summary (`test-results/summary.md`) | — |

5. **Generate the report** using the `ci-report` output style template from `${CLAUDE_PLUGIN_ROOT}/output-styles/ci-report.md`:
   - Parse test output (pass/fail/skip counts, failed test details, timing)
   - Format according to the chosen template
   - Include coverage data if available

6. **Write report files**:
   - Create `test-results/` directory if needed
   - Write the report file(s) in the appropriate format
   - Display a summary to the user

7. **Record failures**: Only when step 2b reported `status: failure`, parse the failed run's
   logs and record them as tech debt:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/ci_monitor.py feedback --cwd .
```

Report `tech_debt_updated` and `suggestions` from its output. Run this at most once per
`/coregy-workflow:ci-report` invocation.

For the `CI Status:` line in the output block below, use:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/project-profile/scripts/ci_monitor.py summary --cwd .
```

## Output

Display a summary after generating:

```
CI Report Generated
━━━━━━━━━━━━━━━━━━

CI System: GitHub Actions
CI Status: failure on branch main (2 failures)
Format: GitHub Annotations + Markdown Summary

Results:
  Passed:  42
  Failed:  2
  Skipped: 3
  Total:   47

Report files:
  → test-results/summary.md (Markdown)
  → stdout annotations (copy to CI workflow)

Failed tests:
  ✗ test_login_invalid_token (tests/auth.test.ts:42)
  ✗ test_rate_limit_exceeded (tests/api.test.ts:88)
```

## Notes

- This command reads `.coregy/profile.yaml` for CI and testing config
- Report files are written to `test-results/` directory
- Add `test-results/` to `.gitignore` if you don't want to commit reports
- For GitHub Actions, copy the annotation output to your workflow's step output
- Supports all testing frameworks detected by `detect_stack.py`
- `ci_monitor.py feedback` requires the `gh` CLI and writes to `.coregy/knowledge/tech-debt.md`. It appends a new section on every run — do not loop it
- `ci_monitor.py status` and `summary` are read-only probes and always exit 0, including when `gh` is not installed
