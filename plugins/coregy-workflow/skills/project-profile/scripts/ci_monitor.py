"""
CI feedback loop for Coregy Workflow.

Polls CI status, parses test failures, creates tech-debt entries
in the knowledge base, and suggests fixes.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh_available():
    """Check if gh CLI is available."""
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_gh(args, cwd, timeout=30):
    """Run a gh CLI command and return (stdout, success)."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
        return result.stdout.strip(), result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "", False


def _get_current_branch(cwd):
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=cwd,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def get_ci_status(cwd):
    """Get CI status for the current branch using `gh` CLI.

    Returns dict with:
    - branch: current branch name
    - status: "success" | "failure" | "pending" | "unknown"
    - checks: list of {name, status, conclusion, url}
    - raw_output: the raw JSON from gh

    Returns None if gh CLI not available or not in a git repo.
    """
    if not _gh_available():
        return None

    branch = _get_current_branch(cwd)
    if not branch:
        return None

    output, ok = _run_gh(
        ["run", "list", "--branch", branch, "--limit", "5",
         "--json", "databaseId,status,conclusion,name,url,headBranch"],
        cwd=cwd,
    )
    if not ok or not output:
        return None

    try:
        runs = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return None

    checks = []
    overall_status = "unknown"
    for run in runs:
        check = {
            "id": run.get("databaseId"),
            "name": run.get("name", ""),
            "status": run.get("status", ""),
            "conclusion": run.get("conclusion", ""),
            "url": run.get("url", ""),
        }
        checks.append(check)

    if checks:
        latest = checks[0]
        status_val = latest.get("status", "").lower()
        conclusion_val = latest.get("conclusion", "").lower()
        if status_val == "completed":
            if conclusion_val == "success":
                overall_status = "success"
            elif conclusion_val in ("failure", "timed_out", "cancelled"):
                overall_status = "failure"
            else:
                overall_status = "unknown"
        elif status_val in ("queued", "in_progress", "waiting"):
            overall_status = "pending"

    return {
        "branch": branch,
        "status": overall_status,
        "checks": checks,
        "raw_output": output,
    }


def parse_test_failures(check_output):
    """Parse CI check output/logs for test failure details.

    Args:
        check_output: String output from CI logs

    Returns list of dicts:
    - test_name: name of failing test
    - file: file path if detectable
    - error: error message
    - type: "test_failure" | "build_error" | "lint_error"
    """
    if not check_output:
        return []

    failures = []

    # pytest: FAILED test_file.py::TestClass::test_method - ErrorMessage
    for m in re.finditer(
        r"FAILED\s+([\w/\\\.\-]+(?:::[\w]+)*)\s*-?\s*(.*)",
        check_output,
    ):
        full_name = m.group(1)
        error_msg = m.group(2).strip()
        # Extract file from pytest path (before first ::)
        parts = full_name.split("::")
        file_path = parts[0] if len(parts) > 1 else ""
        test_name = parts[-1] if len(parts) > 1 else full_name
        failures.append({
            "test_name": test_name,
            "file": file_path,
            "error": error_msg,
            "type": "test_failure",
        })

    # jest: FAIL src/file.test.ts
    # followed by test suite / test name lines with error
    for m in re.finditer(
        r"FAIL\s+([\w/\\\.\-]+\.(?:test|spec)\.\w+)",
        check_output,
    ):
        file_path = m.group(1)
        failures.append({
            "test_name": file_path,
            "file": file_path,
            "error": "Jest test suite failed",
            "type": "test_failure",
        })

    # go test: --- FAIL: TestName (0.00s)
    for m in re.finditer(
        r"---\s+FAIL:\s+([\w/]+)\s+\([\d\.]+s\)",
        check_output,
    ):
        test_name = m.group(1)
        failures.append({
            "test_name": test_name,
            "file": "",
            "error": "Go test failed",
            "type": "test_failure",
        })

    # Build errors: TypeScript error TS2322, SyntaxError, etc.
    for m in re.finditer(
        r"error\s+(TS\d+):\s*(.*?)(?:\n|$)",
        check_output,
    ):
        failures.append({
            "test_name": m.group(1),
            "file": "",
            "error": m.group(2).strip(),
            "type": "build_error",
        })

    # Generic build: SyntaxError or compilation error
    for m in re.finditer(
        r"(SyntaxError|CompileError|BuildError):\s*(.*?)(?:\n|$)",
        check_output,
    ):
        failures.append({
            "test_name": m.group(1),
            "file": "",
            "error": m.group(2).strip(),
            "type": "build_error",
        })

    # Lint errors: eslint
    for m in re.finditer(
        r"([\w/\\\.\-]+)\s+\d+:\d+\s+error\s+(.*?)(?:\n|$)",
        check_output,
    ):
        failures.append({
            "test_name": "lint",
            "file": m.group(1),
            "error": m.group(2).strip(),
            "type": "lint_error",
        })

    # Lint errors: flake8 style (file.py:line:col: E123 message)
    for m in re.finditer(
        r"([\w/\\\.\-]+\.py):(\d+):\d+:\s*([A-Z]\d+)\s+(.*?)(?:\n|$)",
        check_output,
    ):
        failures.append({
            "test_name": m.group(3),
            "file": m.group(1),
            "error": m.group(4).strip(),
            "type": "lint_error",
        })

    return failures


def create_tech_debt_entry(cwd, failures, ci_status):
    """Auto-create or append to tech-debt.md in knowledge base.

    Adds a new section with:
    - Date and CI run info
    - List of failures with details
    - Suggested actions

    Returns path to modified file.
    """
    kb_dir = os.path.join(cwd, ".coregy", "knowledge")
    os.makedirs(kb_dir, exist_ok=True)

    td_path = os.path.join(kb_dir, "tech-debt.md")

    if os.path.exists(td_path):
        with open(td_path, "r") as f:
            content = f.read()
    else:
        content = "# Tech Debt\n\n> To be filled as tech debt is identified during development.\n"

    # Build the new entry
    timestamp = _now()
    branch = ci_status.get("branch", "unknown") if ci_status else "unknown"
    status = ci_status.get("status", "unknown") if ci_status else "unknown"

    entry_lines = [
        "",
        f"## CI Failures ({timestamp})",
        f"- **Branch**: {branch}",
        f"- **Status**: {status}",
        f"- **Failure count**: {len(failures)}",
        "",
    ]

    for f in failures:
        test_name = f.get("test_name", "unknown")
        file_path = f.get("file", "")
        error = f.get("error", "")
        ftype = f.get("type", "unknown")
        file_info = f" in `{file_path}`" if file_path else ""
        entry_lines.append(f"### {ftype}: {test_name}")
        entry_lines.append(f"- **Location**{file_info}")
        entry_lines.append(f"- **Error**: {error}")
        entry_lines.append("")

    suggestions = suggest_fixes(failures)
    if suggestions:
        entry_lines.append("### Suggested Actions")
        for s in suggestions:
            entry_lines.append(f"- **{s['failure']}**: {s['suggestion']}")
        entry_lines.append("")

    content += "\n".join(entry_lines)

    with open(td_path, "w") as f:
        f.write(content)

    return td_path


def suggest_fixes(failures, profile=None):
    """Generate fix suggestions based on failure patterns.

    Returns list of {failure, suggestion} dicts.
    """
    if not failures:
        return []

    suggestions = []
    seen = set()

    for f in failures:
        error = f.get("error", "").lower()
        test_name = f.get("test_name", "")
        ftype = f.get("type", "")
        key = None
        suggestion = None

        if "import" in error or "modulenotfounderror" in error or "cannot find module" in error:
            key = "import_error"
            suggestion = "Check if the dependency is installed. Run the package manager install command."
        elif "type" in error and ("error" in error or ftype == "build_error"):
            key = "type_error"
            suggestion = "Check type annotations and ensure type compatibility."
        elif "timeout" in error or "timed out" in error:
            key = "timeout"
            suggestion = "Check for slow tests or increase the timeout threshold."
        elif "permission" in error or "eacces" in error:
            key = "permission"
            suggestion = "Check file permissions and ensure the CI runner has proper access."
        elif "connection refused" in error or "econnrefused" in error:
            key = "connection"
            suggestion = "Check if required services (database, API) are running in CI."
        elif "assert" in error:
            key = f"assertion_{test_name}"
            suggestion = "Review the test assertion and expected values."
        elif ftype == "lint_error":
            key = f"lint_{test_name}"
            suggestion = "Fix the lint violation or update lint configuration if the rule should be relaxed."
        elif ftype == "build_error":
            key = f"build_{test_name}"
            suggestion = "Fix the compilation/build error before running tests."

        if suggestion and key and key not in seen:
            seen.add(key)
            suggestions.append({
                "failure": test_name or ftype,
                "suggestion": suggestion,
            })

    return suggestions


def get_ci_summary(cwd):
    """Get a summary of recent CI status for the health dashboard.

    Returns dict with:
    - last_run: timestamp
    - status: success/failure
    - failure_count: number of recent failures
    - common_failures: most frequent failure patterns
    """
    ci_status = get_ci_status(cwd)
    if not ci_status:
        return {
            "last_run": None,
            "status": "unknown",
            "failure_count": 0,
            "common_failures": [],
        }

    failure_count = 0
    common_failures = []
    for check in ci_status.get("checks", []):
        conclusion = check.get("conclusion", "").lower()
        if conclusion in ("failure", "timed_out"):
            failure_count += 1
            common_failures.append(check.get("name", "unknown"))

    return {
        "last_run": _now(),
        "status": ci_status["status"],
        "failure_count": failure_count,
        "common_failures": common_failures,
    }


def run_ci_feedback(cwd):
    """Main entry point: poll CI, parse failures, create entries.

    Returns dict with:
    - status: CI status
    - failures: parsed failures
    - tech_debt_updated: bool
    - suggestions: fix suggestions
    """
    ci_status = get_ci_status(cwd)
    if not ci_status:
        return {
            "status": None,
            "failures": [],
            "tech_debt_updated": False,
            "suggestions": [],
        }

    failures = []
    tech_debt_updated = False

    if ci_status["status"] == "failure":
        # `gh run view` takes a run id -- it has no --branch flag, so the id
        # of the latest failed run comes from the `run list` probe above.
        failed_id = None
        for check in ci_status.get("checks", []):
            conclusion = (check.get("conclusion") or "").lower()
            if conclusion in ("failure", "timed_out") and check.get("id"):
                failed_id = check["id"]
                break
        if failed_id is not None:
            log_output, ok = _run_gh(
                ["run", "view", str(failed_id), "--log-failed"],
                cwd=cwd, timeout=60,
            )
            if ok and log_output:
                failures = parse_test_failures(log_output)

        if failures:
            create_tech_debt_entry(cwd, failures, ci_status)
            tech_debt_updated = True

    fix_suggestions = suggest_fixes(failures)

    return {
        "status": ci_status,
        "failures": failures,
        "tech_debt_updated": tech_debt_updated,
        "suggestions": fix_suggestions,
    }


# ---------------------------------------------------------------------------
# CLI (coregy-cli-v1)
# ---------------------------------------------------------------------------

# "gh not installed" is a normal state the command layer branches on, so every
# subcommand here exits 0. Only `feedback` mutates (it appends to tech-debt.md).
_UNAVAILABLE_STATUS = {
    "available": False,
    "status": "unknown",
    "branch": None,
    "checks": [],
}

_CHECK_MARKERS = {
    "success": "[ok]",
    "failure": "[x]",
    "timed_out": "[x]",
    "cancelled": "[x]",
}


def _output(data):
    print(json.dumps(data, indent=2, default=str))


def _fail(msg, json_mode=False):
    if json_mode:
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print("Error: %s" % msg, file=sys.stderr)
    sys.exit(1)


def _print_status_text(status):
    print("CI: %s on branch %s" % (status.get("status", "unknown"),
                                   status.get("branch", "?")))
    for check in status.get("checks", []):
        conclusion = (check.get("conclusion") or "").lower()
        marker = _CHECK_MARKERS.get(conclusion, "[~]")
        print("  %s %s  %s/%s  %s" % (
            marker,
            check.get("name", "?"),
            check.get("status", "?"),
            check.get("conclusion") or "-",
            check.get("url", ""),
        ))


def main():
    parent = argparse.ArgumentParser(add_help=False)
    # default=SUPPRESS is load-bearing: --cwd lives on both the top-level
    # parser and every subparser (parents=[parent]). With a concrete
    # default the subparser re-applies it into its own namespace and
    # silently clobbers a --cwd given *before* the subcommand, so the
    # script would quietly operate on the process cwd instead.
    parent.add_argument("--cwd", default=argparse.SUPPRESS,
                        help="Project root directory (default: .)")

    parser = argparse.ArgumentParser(
        description="Coregy Workflow CI feedback loop (requires the gh CLI)",
        parents=[parent],
    )
    sub = parser.add_subparsers(dest="command")

    p_status = sub.add_parser("status", parents=[parent],
                              help="Probe CI status for the current branch")
    p_status.add_argument("--raw", action="store_true",
                          help="Keep the raw gh output in the JSON payload")
    p_status.add_argument("--json", action="store_true", dest="json_mode")

    p_summary = sub.add_parser("summary", parents=[parent],
                               help="Condensed CI summary")
    p_summary.add_argument("--json", action="store_true", dest="json_mode")

    p_feedback = sub.add_parser(
        "feedback", parents=[parent],
        help="Parse failed run logs and append a section to tech-debt.md")
    p_feedback.add_argument("--json", action="store_true", dest="json_mode")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # getattr, not args.cwd: the shared --cwd action defaults to
    # SUPPRESS so a value given before the subcommand survives.
    cwd = os.path.abspath(getattr(args, "cwd", "."))
    json_mode = getattr(args, "json_mode", False)

    try:
        if args.command == "status":
            status = get_ci_status(cwd)
            if status is None:
                if json_mode:
                    _output(_UNAVAILABLE_STATUS)
                else:
                    print("CI status unavailable "
                          "(gh CLI missing, not a git repo, or no runs).")
                return
            if json_mode:
                payload = dict(status)
                payload["available"] = True
                if not args.raw:
                    payload.pop("raw_output", None)
                _output(payload)
            else:
                _print_status_text(status)

        elif args.command == "summary":
            summary = get_ci_summary(cwd)
            if json_mode:
                _output(summary)
            else:
                print("CI summary: status=%s, failures=%d"
                      % (summary.get("status", "unknown"),
                         summary.get("failure_count", 0)))
                common = summary.get("common_failures") or []
                if common:
                    print("Common failures: %s" % ", ".join(common))

        elif args.command == "feedback":
            result = run_ci_feedback(cwd)
            if json_mode:
                _output(result)
            else:
                failures = result.get("failures") or []
                if not failures:
                    print("No CI failures to process.")
                else:
                    print("CI feedback: %d failure(s) parsed, %s"
                          % (len(failures),
                             "tech-debt.md updated"
                             if result.get("tech_debt_updated")
                             else "tech-debt.md unchanged"))
                    suggestions = result.get("suggestions") or []
                    if suggestions:
                        print("Suggestions:")
                        for s in suggestions:
                            print("  - %s: %s" % (s.get("failure", "?"),
                                                  s.get("suggestion", "")))
    except (FileNotFoundError, ValueError, OSError) as exc:
        _fail(str(exc), json_mode)


if __name__ == "__main__":
    main()
