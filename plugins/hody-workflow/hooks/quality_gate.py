#!/usr/bin/env python3
"""
PreToolUse hook (Bash matcher): intercepts git commit commands and runs
lightweight quality checks on staged files.

Checks (configurable via .hody/quality-rules.yaml):
  - Hardcoded secrets (API keys, tokens, passwords in code)
  - Common security patterns (SQL injection, eval usage)
  - Debug leftovers (console.log, print statements in non-test files)
  - Large files that shouldn't be committed

Output: JSON with permissionDecision "allow" or "deny" + reason.
Skip with HODY_SKIP_QUALITY_GATE=1 env var.
"""
import json
import os
import re
import shlex
import subprocess
import sys


# Try to import configurable rule engine; fall back to hardcoded behavior
_USE_QUALITY_RULES = False
try:
    _scripts_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "skills",
        "project-profile",
        "scripts",
    )
    sys.path.insert(0, os.path.abspath(_scripts_dir))
    import quality_rules
    _USE_QUALITY_RULES = True
except ImportError:
    quality_rules = None


# --- Legacy hardcoded patterns (fallback when quality_rules unavailable) ---

# Patterns that indicate hardcoded secrets
SECRET_PATTERNS = [
    (r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\'][A-Za-z0-9]{16,}["\']', "Possible hardcoded API key"),
    (r'(?i)(secret|token|password|passwd|pwd)\s*[:=]\s*["\'][^"\']{8,}["\']', "Possible hardcoded secret/password"),
    (r'(?i)-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', "Private key detected"),
    (r'AKIA[0-9A-Z]{16}', "AWS access key detected"),
    (r'(?i)sk-[a-zA-Z0-9]{20,}', "Possible API secret key"),
]

# Security anti-patterns
SECURITY_PATTERNS = [
    (r'\beval\s*\(', "eval() usage — potential code injection"),
    (r'(?i)innerHTML\s*=', "innerHTML assignment — potential XSS"),
    (r'(?i)document\.write\s*\(', "document.write() — potential XSS"),
    (r'(?i)exec\s*\(\s*["\']', "exec() with string — potential injection"),
]

# Max file size to commit (500KB)
MAX_FILE_SIZE = 500 * 1024

# Files/patterns to skip checking
SKIP_EXTENSIONS = {".lock", ".sum", ".min.js", ".min.css", ".map", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot"}
SKIP_PATHS = {"node_modules/", "vendor/", "dist/", "build/", ".next/", "__pycache__/"}


def get_staged_files(cwd):
    """Get list of staged files with their status."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-status"],
            cwd=cwd, capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return []

        files = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                status, path = parts
                if status != "D":  # Skip deleted files
                    files.append(path)
        return files
    except (subprocess.TimeoutExpired, OSError):
        return []


def should_skip(filepath):
    """Check if a file should be skipped from quality checks."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in SKIP_EXTENSIONS:
        return True
    # Check for .min.js, .min.css patterns
    basename = os.path.basename(filepath).lower()
    if ".min." in basename:
        return True
    for skip in SKIP_PATHS:
        if filepath.startswith(skip):
            return True
    return False


def check_file(cwd, filepath):
    """Run quality checks on a single staged file. Returns list of issues.

    Legacy fallback — used when quality_rules module is not available.
    """
    issues = []
    full_path = os.path.join(cwd, filepath)

    # Check file size
    try:
        size = os.path.getsize(full_path)
        if size > MAX_FILE_SIZE:
            issues.append(f"Large file ({size // 1024}KB > {MAX_FILE_SIZE // 1024}KB)")
            return issues  # Don't read large files
    except OSError:
        return issues

    # Read file content
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return issues

    lines = content.splitlines()

    # Secret patterns
    for pattern, message in SECRET_PATTERNS:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line):
                issues.append(f"L{i}: {message}")
                break  # One issue per pattern per file

    # Security patterns (skip test files)
    is_test = any(t in filepath.lower() for t in ["test", "spec", "__test__", ".test.", ".spec."])
    if not is_test:
        for pattern, message in SECURITY_PATTERNS:
            for i, line in enumerate(lines, 1):
                if re.search(pattern, line):
                    issues.append(f"L{i}: {message}")
                    break

    return issues


def _read_index_content(cwd, filepath):
    """Content of `filepath` as staged in the index, or None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "show", ":%s" % filepath],
            cwd=cwd, capture_output=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="ignore")


def check_file_v2(cwd, filepath, from_index=False):
    """Run configurable quality checks on a staged file.

    Returns (errors, warnings) tuple of lists.
    Uses quality_rules module for configurable checks.

    from_index: scan the staged blob rather than the working tree -- the
    working tree can differ from what is actually being committed.
    """
    content = _read_index_content(cwd, filepath) if from_index else None
    if content is None:
        full_path = os.path.join(cwd, filepath)
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            content = ""

    result = quality_rules.run_checks(cwd, filepath, content)
    return result.get("errors", []), result.get("warnings", [])


def run_quality_gate(cwd, pending=None):
    """Run all quality checks on staged files. Returns (passed, report).

    pending: files the same command will stage before committing (see
    analyze_commit_command). They are scanned from the working tree.
    """
    pending = set(pending or ())
    staged = get_staged_files(cwd)
    files = list(staged) + sorted(p for p in pending if p not in staged)
    if not files:
        return True, "No staged files to check."

    if _USE_QUALITY_RULES:
        return _run_quality_gate_v2(cwd, files, pending)
    else:
        return _run_quality_gate_legacy(cwd, files)


def _run_quality_gate_v2(cwd, staged, pending=frozenset()):
    """Configurable quality gate using quality_rules module."""
    all_errors = {}
    all_warnings = {}

    for filepath in staged:
        if should_skip(filepath):
            continue
        errors, warnings = check_file_v2(
            cwd, filepath, from_index=filepath not in pending)
        if errors:
            all_errors[filepath] = errors
        if warnings:
            all_warnings[filepath] = warnings

    has_errors = bool(all_errors)
    has_warnings = bool(all_warnings)

    if not has_errors and not has_warnings:
        return True, f"Quality gate passed. {len(staged)} file(s) checked."

    report_lines = []

    if has_errors:
        report_lines.append(f"Quality gate: {len(all_errors)} file(s) with errors:\n")
        for filepath, issues in all_errors.items():
            report_lines.append(f"  {filepath}:")
            for issue in issues:
                line_num = issue.get("line", 0)
                msg = issue.get("message", "")
                prefix = f"L{line_num}: " if line_num else ""
                report_lines.append(f"    - [ERROR] {prefix}{msg}")

    if has_warnings:
        report_lines.append(f"\nWarnings in {len(all_warnings)} file(s):\n")
        for filepath, issues in all_warnings.items():
            report_lines.append(f"  {filepath}:")
            for issue in issues:
                line_num = issue.get("line", 0)
                msg = issue.get("message", "")
                prefix = f"L{line_num}: " if line_num else ""
                report_lines.append(f"    - [WARN] {prefix}{msg}")

    report = "\n".join(report_lines)

    if has_errors:
        return False, report
    else:
        # Warnings only — allow commit but include report
        return True, f"Quality gate passed with warnings. {len(staged)} file(s) checked.\n\n{report}"


def _run_quality_gate_legacy(cwd, staged):
    """Legacy quality gate with hardcoded patterns."""
    all_issues = {}
    for filepath in staged:
        if should_skip(filepath):
            continue
        issues = check_file(cwd, filepath)
        if issues:
            all_issues[filepath] = issues

    if not all_issues:
        return True, f"Quality gate passed. {len(staged)} file(s) checked."

    # Build report
    report_lines = [f"Quality gate: {len(all_issues)} file(s) with issues:\n"]
    for filepath, issues in all_issues.items():
        report_lines.append(f"  {filepath}:")
        for issue in issues:
            report_lines.append(f"    - {issue}")

    return False, "\n".join(report_lines)


# --- git commit detection -------------------------------------------------
#
# A naive `^\s*git\s+commit\b` match misses every realistic invocation:
#   git add -A && git commit -m x     (chained)
#   VAR=val git commit                (env assignment prefix)
#   git -C /path commit               (global option before the subcommand)
#   foo; git commit                   (sequenced)
#   make build | tee log; git commit  (pipeline)
# while it must NOT fire on text that merely mentions a commit:
#   echo "git commit"                 (quoted string)
#   git log --grep="commit"           (different subcommand)
#   cat > f <<'EOF' ... git commit    (heredoc body -- data, not a command)
#
# A false positive is worse than a miss here: it denies a Bash call that was
# never a commit. Heredoc bodies are therefore blanked before anything else.

_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Wrappers and shell keywords that may precede the real command without
# changing what it is.
_CMD_PREFIXES = frozenset([
    "env", "command", "exec", "nohup", "builtin", "time",
    "sudo", "doas",
    "then", "else", "elif", "do", "!", "{",
])

# `<<WORD` / `<<-WORD` / `<<'WORD'` heredoc openers, but never `<<<` (here-string).
_HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

# git global options that consume a separate value token.
_GIT_VALUE_OPTS = frozenset([
    "-C", "-c", "--git-dir", "--work-tree", "--namespace",
    "--exec-path", "--super-prefix", "--config-env",
])

# Shell operators that start a new command context.
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;\n|&()]")


def _strip_heredocs(command):
    """Blank the body of every heredoc so its contents are treated as data.

    Without this, `cat > notes.md <<'EOF'` followed by a line reading
    `git commit -m x` would deny the write -- the old regex never did, so this
    would have been a fresh false positive.

    The body is only blanked when the terminator line is actually found, which
    keeps an unrelated `<<` (e.g. a shift operator inside a quoted script) from
    swallowing the rest of the command.
    """
    if "<<" not in command:
        return command

    lines = command.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for match in _HEREDOC_RE.finditer(line):
            delimiter = match.group(2)
            end = None
            for j in range(i, len(lines)):
                if lines[j].strip() == delimiter:
                    end = j
                    break
            if end is None:
                continue  # no terminator -- not a heredoc we understand
            out.extend([""] * (end - i + 1))
            i = end + 1
    return "\n".join(out)


def _strip_quoted(command):
    """Blank out quoted spans and escapes so their contents are never parsed
    as a command. Length is preserved-ish by substituting spaces, which keeps
    token boundaries intact."""
    out = []
    quote = None
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if quote is None:
            if ch == "\\":
                # Neutralize the escape and the escaped character so an
                # escaped separator is not mistaken for a real one.
                out.append("  ")
                i += 2
                continue
            if ch == "'" or ch == '"':
                quote = ch
                out.append(" ")
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        # inside a quoted span
        if quote == '"' and ch == "\\":
            out.append("  ")
            i += 2
            continue
        if ch == quote:
            quote = None
        out.append(" ")
        i += 1
    return "".join(out)


def _is_git_commit_segment(segment):
    """True if a single shell command segment invokes `git ... commit`."""
    sub, _ = _git_subcommand(segment.split())
    return sub == "commit"


def _git_subcommand(tokens):
    """Return (subcommand, args_after_it) for a tokenized `git ...` segment.

    (None, []) when the segment does not invoke git.
    """
    idx = 0
    # Skip env assignments, shell keywords and benign command wrappers --
    # plus any options belonging to a wrapper we already skipped, so
    # `env -i git commit` and `sudo -n git commit` still resolve to git.
    saw_wrapper = False
    while idx < len(tokens):
        token = tokens[idx]
        if _ENV_ASSIGN_RE.match(token) or token in _CMD_PREFIXES:
            saw_wrapper = saw_wrapper or token in _CMD_PREFIXES
            idx += 1
            continue
        if saw_wrapper and token.startswith("-"):
            idx += 1
            continue
        break
    if idx >= len(tokens):
        return None, []

    if tokens[idx].rsplit("/", 1)[-1] not in ("git", "git.exe"):
        return None, []
    idx += 1

    # The subcommand is the first non-option token after any global options.
    while idx < len(tokens):
        token = tokens[idx]
        if token.startswith("-"):
            idx += 2 if token in _GIT_VALUE_OPTS else 1
            continue
        return token, tokens[idx + 1:]
    return None, []


def _segments(command):
    """Yield (cleaned_segment, raw_segment) for every command in a shell chain.

    The cleaned text (quotes blanked) decides *what* a segment is; the raw text
    (quotes intact) is what gets tokenized for its arguments. _strip_quoted
    preserves length, so the same span indexes both strings.
    """
    raw = _strip_heredocs(command)
    cleaned = _strip_quoted(raw)
    start = 0
    for match in _SEGMENT_SPLIT_RE.finditer(cleaned):
        yield cleaned[start:match.start()], raw[start:match.start()]
        start = match.end()
    yield cleaned[start:], raw[start:]


def _tokenize(raw_segment, fallback):
    try:
        return shlex.split(raw_segment, comments=True)
    except ValueError:
        return fallback.split()


def is_git_commit_command(command):
    """True if `command` invokes `git commit` anywhere in its shell chain."""
    if not command or "commit" not in command:
        return False
    for cleaned, _raw in _segments(command):
        if _is_git_commit_segment(cleaned):
            return True
    return False


def analyze_commit_command(command):
    """Describe what a Bash command will commit.

    Returns None when the command never runs `git commit`. Otherwise a dict:
      add_args   -- argument lists of every `git add` that runs *before* the
                    commit in the same chain. PreToolUse fires before any of
                    the chain executes, so the index does not contain these
                    files yet; they must be resolved with `git add --dry-run`.
      commit_all -- True for `git commit -a` / `--all` / `-am ...`, which
                    stages every modified tracked file at commit time.
    """
    if not command or "commit" not in command:
        return None
    add_args = []
    for cleaned, raw in _segments(command):
        sub, _ = _git_subcommand(cleaned.split())
        if sub is None:
            continue
        _, args = _git_subcommand(_tokenize(raw, cleaned))
        if sub == "add":
            add_args.append(args)
        elif sub == "commit":
            commit_all = False
            for arg in args:
                if arg in ("-a", "--all"):
                    commit_all = True
                elif arg.startswith("-") and not arg.startswith("--") and "a" in arg[1:]:
                    # combined short flags such as -am; stop at a value-taking
                    # flag so `-mfoo` (message "foo") is not read as -a
                    for ch in arg[1:]:
                        if ch == "a":
                            commit_all = True
                            break
                        if ch in "mFcCt":
                            break
            return {"add_args": add_args, "commit_all": commit_all}
    return None


def _pending_files(cwd, analysis):
    """Files the command will stage before committing (not yet in the index)."""
    pending = set()
    for args in analysis.get("add_args", []):
        try:
            result = subprocess.run(
                ["git", "add", "--dry-run", "--ignore-missing"] + args,
                cwd=cwd, capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if result.returncode != 0:
            # --ignore-missing is only valid with --dry-run; retry without it
            try:
                result = subprocess.run(
                    ["git", "add", "--dry-run"] + args,
                    cwd=cwd, capture_output=True, text=True, timeout=10,
                )
            except (subprocess.TimeoutExpired, OSError):
                continue
        for line in result.stdout.splitlines():
            # "add 'path'" / "remove 'path'"
            m = re.match(r"^add '(.*)'$", line.strip())
            if m:
                pending.add(m.group(1))
    if analysis.get("commit_all"):
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=d"],
                cwd=cwd, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                pending.update(p for p in result.stdout.splitlines() if p)
        except (subprocess.TimeoutExpired, OSError):
            pass
    return pending


def main():
    try:
        input_data = json.load(sys.stdin)

        # Skip if disabled
        if os.environ.get("HODY_SKIP_QUALITY_GATE"):
            sys.exit(0)

        # Only intercept git commit commands
        tool_input = input_data.get("tool_input", {})
        command = tool_input.get("command", "")

        analysis = analyze_commit_command(command)
        if analysis is None:
            sys.exit(0)

        cwd = input_data.get("cwd", os.getcwd())

        # Check if .hody/ exists (only run for initialized projects)
        if not os.path.isdir(os.path.join(cwd, ".hody")):
            sys.exit(0)

        passed, report = run_quality_gate(cwd, _pending_files(cwd, analysis))

        if passed:
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                }
            }
            if "with warnings" in report:
                # Non-blocking: surface the warnings instead of dropping them --
                # additionalContext reaches the model, systemMessage the user.
                # No permissionDecision: "allow" would skip the user's own
                # permission prompt for the commit.
                message = "[Hody Quality Gate] " + report
                output["hookSpecificOutput"]["additionalContext"] = message
                output["systemMessage"] = message
            print(json.dumps(output))
            sys.exit(0)
        else:
            # Deny commit with reason
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"[Hody Quality Gate] {report}\n\nFix issues or skip with HODY_SKIP_QUALITY_GATE=1"
                }
            }
            print(json.dumps(output))
            sys.exit(0)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(0)  # Don't block on hook error


if __name__ == "__main__":
    main()
