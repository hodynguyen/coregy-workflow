# CI Report

> Used by: **unit-tester**, **integration-tester**
> Use this template when generating test reports for CI pipelines (GitHub Actions, GitLab CI, Jenkins).

---

## Format Options

### Option 1: GitHub Actions Annotations

Use `::error`, `::warning`, and `::notice` syntax so test results appear as inline annotations on the PR.

```
::notice title=Test Suite::Running [test framework] tests for [module]

::error file=src/auth.ts,line=42,title=Test Failed::test_login_invalid_token — Expected 401, got 500
::warning file=src/utils.ts,line=15,title=Uncovered::Function parseDate has no test coverage
::notice title=Test Summary::Passed: X | Failed: X | Skipped: X | Duration: Xs
```

### Option 2: JUnit XML

Standard JUnit XML format consumed by most CI systems.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="[project-name]" tests="[total]" failures="[count]" errors="[count]" time="[seconds]">
  <testsuite name="[module-name]" tests="[count]" failures="[count]" errors="[count]" time="[seconds]">
    <testcase classname="[file.path]" name="[test name]" time="[seconds]" />
    <testcase classname="[file.path]" name="[test name]" time="[seconds]">
      <failure message="[error message]" type="[AssertionError]">
        [stack trace or details]
      </failure>
    </testcase>
    <testcase classname="[file.path]" name="[test name]" time="[seconds]">
      <skipped message="[reason]" />
    </testcase>
  </testsuite>
</testsuites>
```

### Option 3: Markdown Summary (for PR comments)

```markdown
## Test Results

| Status | Count |
|--------|-------|
| Passed | X |
| Failed | X |
| Skipped | X |
| **Total** | **X** |

### Failed Tests

| Test | File | Error |
|------|------|-------|
| `test_login_invalid_token` | `tests/auth.test.ts:42` | Expected 401, got 500 |

### Coverage

| File | Statements | Branches | Functions | Lines |
|------|-----------|----------|-----------|-------|
| `src/auth.ts` | 85% | 72% | 90% | 83% |
| **Total** | **88%** | **75%** | **91%** | **86%** |
```

## Usage Guide

1. **Read `.coregy/profile.yaml`** to determine the testing framework and CI system
2. **Choose the output format** based on the CI system:
   - GitHub Actions → Option 1 (annotations) + Option 3 (PR comment)
   - GitLab CI / Jenkins → Option 2 (JUnit XML)
   - General / unknown → Option 3 (Markdown summary)
3. **Run the test command** from the project's testing framework
4. **Capture results** and format according to the chosen template
5. **Write the report** to the output location:
   - JUnit XML → `test-results/junit.xml`
   - Markdown → `test-results/summary.md`
   - GitHub annotations → print to stdout

## CI System Detection

Read from `.coregy/profile.yaml`:

```yaml
devops:
  ci: github-actions    # → Use GitHub annotations + markdown
  ci: gitlab-ci         # → Use JUnit XML
  ci: jenkins           # → Use JUnit XML
```

If no CI detected, default to Markdown summary.
