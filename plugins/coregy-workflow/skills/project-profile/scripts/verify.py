"""
Verification runner for Coregy Workflow.

Resolves the project's real lint / typecheck / test commands from its config
files (Makefile, package.json scripts, pyproject.toml, go.mod, Cargo.toml,
...), runs them, and records the result in `.coregy/verify-last.json`. Agents
gate on these exit codes instead of on their own claim that the work is done.

Resolution order per check: `.coregy/verify.yaml` override > Makefile target
> `testing.command` in profile.yaml > language detection. Only config files
are read -- nothing is installed.

Optional overrides, `.coregy/verify.yaml` (written by `verify.py init`):

    checks:
      lint: "npm run lint"
      test: "npm test -- --run"
      typecheck: ""          # empty string disables a check
    timeout: 300             # seconds per check

Usage:
    python3 verify.py detect --cwd <dir> [--json]
    python3 verify.py run --cwd <dir> [--only lint,test] [--reuse] [--json]
    python3 verify.py last --cwd <dir> [--json]
    python3 verify.py init --cwd <dir> [--force]
"""
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

try:
    from . import mini_yaml
except ImportError:
    import mini_yaml

CHECK_ORDER = ("lint", "typecheck", "test")  # fast checks first
DEFAULT_TIMEOUT = 300
TAIL_LINES = 60
TAIL_CHARS = 6000
CONFIG_FILE = "verify.yaml"
LAST_FILE = "verify-last.json"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_RULE_RE = re.compile(r"^[\s=\-_*~.#]*$")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _read_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _exists(cwd, *names):
    return any(os.path.exists(os.path.join(cwd, n)) for n in names)


# ---------------------------------------------------------------------------
# Command resolution
# ---------------------------------------------------------------------------

def _makefile_checks(cwd):
    text = _read(os.path.join(cwd, "Makefile")) or _read(os.path.join(cwd, "makefile"))
    if not text:
        return {}
    targets = set(re.findall(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", text, re.M))
    checks = {}
    for check, names in (("lint", ("lint",)),
                         ("typecheck", ("typecheck", "type-check", "types")),
                         ("test", ("test", "tests"))):
        for name in names:
            if name in targets:
                checks[check] = "make " + name
                break
    return checks


def _node_runner(cwd):
    """(script runner, binary runner) for the project's package manager."""
    if _exists(cwd, "pnpm-lock.yaml"):
        return "pnpm", "pnpm exec"
    if _exists(cwd, "yarn.lock"):
        return "yarn", "yarn"
    if _exists(cwd, "bun.lockb", "bun.lock"):
        return "bun run", "bunx"
    return "npm run", "npx"


def _node_checks(cwd):
    pkg = _read_json(os.path.join(cwd, "package.json"))
    if not isinstance(pkg, dict):
        return {}
    scripts = pkg.get("scripts") or {}
    run, exec_ = _node_runner(cwd)
    checks = {}
    if "lint" in scripts:
        checks["lint"] = "%s lint" % run
    for name in ("typecheck", "type-check", "check-types", "tsc", "types"):
        if name in scripts:
            checks["typecheck"] = "%s %s" % (run, name)
            break
    else:
        deps = {}
        deps.update(pkg.get("dependencies") or {})
        deps.update(pkg.get("devDependencies") or {})
        if "typescript" in deps and _exists(cwd, "tsconfig.json"):
            checks["typecheck"] = "%s tsc --noEmit" % exec_
    test = scripts.get("test", "")
    if test and "no test specified" not in test:
        checks["test"] = "npm test" if run == "npm run" else "%s test" % run
    return checks


def _python_checks(cwd):
    markers = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
               "Pipfile", "tox.ini")
    reqs = "".join(_read(p) for p in glob.glob(os.path.join(cwd, "requirements*.txt")))
    if not _exists(cwd, *markers) and not reqs:
        return {}
    pyproject = _read(os.path.join(cwd, "pyproject.toml"))
    setup_cfg = _read(os.path.join(cwd, "setup.cfg"))
    tox_ini = _read(os.path.join(cwd, "tox.ini"))
    if _exists(cwd, "uv.lock"):
        prefix = "uv run "
    elif _exists(cwd, "poetry.lock"):
        prefix = "poetry run "
    else:
        prefix = ""
    py = prefix + "python3" if not prefix else prefix + "python"
    deps = (pyproject + reqs + setup_cfg).lower()

    checks = {}
    if (_exists(cwd, "ruff.toml", ".ruff.toml") or "[tool.ruff" in pyproject
            or re.search(r"\bruff\b", deps)):
        checks["lint"] = prefix + "ruff check ."
    elif _exists(cwd, ".flake8") or "[flake8]" in setup_cfg + tox_ini:
        checks["lint"] = py + " -m flake8"
    if (_exists(cwd, "mypy.ini", ".mypy.ini") or "[tool.mypy" in pyproject
            or "[mypy" in setup_cfg):
        checks["typecheck"] = py + " -m mypy ."
    if (_exists(cwd, "pytest.ini", "conftest.py") or "[tool.pytest" in pyproject
            or "[tool:pytest]" in setup_cfg or re.search(r"\bpytest\b", deps)):
        checks["test"] = py + " -m pytest -q"
    else:
        for test_dir in ("tests", "test"):
            if os.path.isdir(os.path.join(cwd, test_dir)):
                checks["test"] = "%s -m unittest discover -s %s" % (py, test_dir)
                break
    return checks


def _go_checks(cwd):
    if not _exists(cwd, "go.mod"):
        return {}
    lint = ("golangci-lint run" if _exists(cwd, ".golangci.yml", ".golangci.yaml",
                                           ".golangci.toml")
            else "go vet ./...")
    return {"lint": lint, "test": "go test ./..."}


def _rust_checks(cwd):
    if not _exists(cwd, "Cargo.toml"):
        return {}
    return {"lint": "cargo clippy --all-targets -- -D warnings", "test": "cargo test"}


def _java_checks(cwd):
    if _exists(cwd, "pom.xml"):
        return {"test": ("./mvnw" if _exists(cwd, "mvnw") else "mvn") + " -q test"}
    if _exists(cwd, "build.gradle", "build.gradle.kts"):
        return {"test": ("./gradlew" if _exists(cwd, "gradlew") else "gradle") + " test"}
    return {}


def _dotnet_checks(cwd):
    if glob.glob(os.path.join(cwd, "*.sln")) or glob.glob(os.path.join(cwd, "*.csproj")):
        return {"test": "dotnet test"}
    return {}


def _ruby_checks(cwd):
    if not _exists(cwd, "Gemfile"):
        return {}
    checks = {}
    if _exists(cwd, ".rubocop.yml"):
        checks["lint"] = "bundle exec rubocop"
    if _exists(cwd, ".rspec", "spec"):
        checks["test"] = "bundle exec rspec"
    elif _exists(cwd, "test"):
        checks["test"] = "bundle exec rake test"
    return checks


def _php_checks(cwd):
    composer = _read_json(os.path.join(cwd, "composer.json"))
    if not isinstance(composer, dict):
        return {}
    scripts = composer.get("scripts") or {}
    checks = {}
    if "lint" in scripts:
        checks["lint"] = "composer lint"
    if "test" in scripts:
        checks["test"] = "composer test"
    elif _exists(cwd, "phpunit.xml", "phpunit.xml.dist"):
        checks["test"] = "vendor/bin/phpunit"
    return checks


def _load_profile(cwd):
    profile = mini_yaml.loads(_read(os.path.join(cwd, ".coregy", "profile.yaml")))
    return profile if isinstance(profile, dict) else {}


def _profile_checks(cwd):
    """testing.command from profile.yaml -- written by hand or by /init."""
    testing = _load_profile(cwd).get("testing")
    command = testing.get("command") if isinstance(testing, dict) else None
    if isinstance(command, str) and command.strip():
        return {"test": command.strip()}
    return {}


# Declared entry points (Makefile, profile.yaml) beat inferred ones; among languages the
# first that yields a check wins, so a Node frontend inside a Go repo root
# does not shadow `go test`.
_DETECTORS = (
    ("Makefile", _makefile_checks),
    ("profile.yaml", _profile_checks),
    ("package.json", _node_checks),
    ("python", _python_checks),
    ("go.mod", _go_checks),
    ("Cargo.toml", _rust_checks),
    ("java", _java_checks),
    ("dotnet", _dotnet_checks),
    ("Gemfile", _ruby_checks),
    ("composer.json", _php_checks),
)


def _detect_dir(cwd):
    """{check: (command, source)} for one directory."""
    found = {}
    for source, detector in _DETECTORS:
        for check, command in detector(cwd).items():
            if check not in found:
                found[check] = (command, source)
    return found


def _profile_subdirs(cwd):
    """frontend.dir / backend.dir from profile.yaml that are real subdirectories."""
    profile = _load_profile(cwd)
    dirs = []
    for section in ("frontend", "backend"):
        block = profile.get(section)
        d = block.get("dir") if isinstance(block, dict) else None
        if not isinstance(d, str):
            continue
        d = d.strip().strip("/")
        if d and d != "." and os.path.isdir(os.path.join(cwd, d)) and d not in dirs:
            dirs.append(d)
    return dirs


def load_config(cwd):
    """Parsed .coregy/verify.yaml, or {} when absent."""
    data = mini_yaml.loads(_read(os.path.join(cwd, ".coregy", CONFIG_FILE)))
    return data if isinstance(data, dict) else {}


def resolve_checks(cwd, config=None):
    """Ordered list of checks to run.

    Each check is {name, check, command, cwd, source}. `name` is the check
    kind ("test"), suffixed with the directory for a profile subdirectory
    ("test:web"). An override in verify.yaml replaces every detected command
    of that kind; an empty override disables it.
    """
    if config is None:
        config = load_config(cwd)
    overrides = config.get("checks") if isinstance(config.get("checks"), dict) else {}

    checks = []
    if overrides:
        for kind in list(CHECK_ORDER) + sorted(k for k in overrides if k not in CHECK_ORDER):
            command = overrides.get(kind)
            if isinstance(command, str) and command.strip():
                checks.append({"name": kind, "check": kind, "command": command.strip(),
                               "cwd": ".", "source": CONFIG_FILE})

    detected = [(".", _detect_dir(cwd))]
    for d in _profile_subdirs(cwd):
        detected.append((d, _detect_dir(os.path.join(cwd, d))))
    for kind in CHECK_ORDER:
        if kind in overrides:
            continue
        for rel, found in detected:
            if kind in found:
                command, source = found[kind]
                name = kind if rel == "." else "%s:%s" % (kind, rel)
                checks.append({"name": name, "check": kind, "command": command,
                               "cwd": rel, "source": source})
    return checks


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def _git(cwd, *args):
    try:
        out = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True,
                             timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def workspace_fingerprint(cwd):
    """Hash of HEAD + uncommitted changes + untracked files, ignoring .coregy/.

    None outside a git repo. Lets `run --reuse` skip a re-run when nothing
    changed since the last one -- the workflow state under .coregy/ changes
    after every agent and must not count.
    """
    head = _git(cwd, "rev-parse", "HEAD")
    if head is None:
        return None
    exclude = ":(exclude).coregy"
    h = hashlib.sha1(head)
    h.update(_git(cwd, "diff", "HEAD", "--binary", "--", ".", exclude) or b"")
    untracked = _git(cwd, "ls-files", "--others", "--exclude-standard", "-z",
                     "--", ".", exclude) or b""
    for rel in sorted(p for p in untracked.split(b"\0") if p):
        h.update(rel)
        try:
            with open(os.path.join(cwd, rel.decode("utf-8", "replace")), "rb") as f:
                h.update(hashlib.sha1(f.read()).digest())
        except OSError:
            pass
    return h.hexdigest()


def _tail(text):
    text = _ANSI_RE.sub("", text or "")
    lines = text.rstrip().splitlines()[-TAIL_LINES:]
    return "\n".join(lines)[-TAIL_CHARS:]


def _run_one(cwd, check, timeout):
    env = dict(os.environ)
    env["CI"] = "1"  # keeps vitest/jest/etc. out of watch mode
    env.setdefault("FORCE_COLOR", "0")
    # A .pyc written by the previous run is keyed on source mtime (1s) + size;
    # an agent's same-second, same-length fix (a-b -> a+b) would be served
    # stale and the check would keep failing on code that is already fixed.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.time()
    try:
        proc = subprocess.run(
            check["command"], shell=True, cwd=os.path.join(cwd, check["cwd"]),
            capture_output=True, text=True, errors="replace", timeout=timeout,
            env=env,
        )
        code = proc.returncode
        output = (proc.stdout or "") + (proc.stderr or "")
        if code == 0:
            status = "passed"
        elif code == 127 or "command not found" in output[-500:]:
            status = "missing"
        else:
            status = "failed"
    except subprocess.TimeoutExpired as exc:
        code = None
        raw = (exc.stdout or b"") + (exc.stderr or b"")
        output = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        output += "\n[coregy] timed out after %ds" % timeout
        status = "timeout"
    result = dict(check)
    result.update({
        "status": status,
        "exit_code": code,
        "duration_s": round(time.time() - started, 1),
        "output_tail": "" if status == "passed" else _tail(output),
    })
    return result


def summarize(checks):
    marks = {"passed": "ok", "failed": "FAIL", "timeout": "TIMEOUT", "missing": "missing"}
    return ", ".join("%s %s" % (c["name"], marks.get(c["status"], c["status"]))
                     for c in checks) or "no checks"


def run_checks(cwd, only=None, timeout=None, reuse=False, fail_fast=False):
    """Run the resolved checks and write .coregy/verify-last.json.

    Returns the result dict:
        passed    -- no check failed or timed out
        verified  -- at least one check actually passed (False when nothing
                     ran, or every tool was missing)
        reused    -- result came from the previous run (--reuse, same tree)
        checks    -- per-check status, exit_code, duration_s, output_tail
        warnings  -- missing tools, nothing detected
    """
    config = load_config(cwd)
    if timeout is None:
        timeout = config.get("timeout") if isinstance(config.get("timeout"), int) else DEFAULT_TIMEOUT
    checks = resolve_checks(cwd, config)
    if only:
        checks = [c for c in checks if c["check"] in only or c["name"] in only]
    names = [c["name"] for c in checks]
    fingerprint = workspace_fingerprint(cwd)

    if reuse and fingerprint:
        last = load_last(cwd)
        if (last and last.get("fingerprint") == fingerprint
                and [c["name"] for c in last.get("checks", [])] == names):
            last["reused"] = True
            return last

    results = []
    for check in checks:
        results.append(_run_one(cwd, check, timeout))
        if fail_fast and results[-1]["status"] in ("failed", "timeout"):
            break

    warnings = []
    if not checks:
        warnings.append("No lint/typecheck/test command detected -- add one to "
                        ".coregy/%s (verify.py init writes a template)" % CONFIG_FILE)
    for r in results:
        if r["status"] == "missing":
            warnings.append("%s: tool not installed (`%s`)" % (r["name"], r["command"]))

    result = {
        "ran_at": _now(),
        "passed": not any(r["status"] in ("failed", "timeout") for r in results),
        "verified": any(r["status"] == "passed" for r in results),
        "reused": False,
        "fingerprint": fingerprint,
        "summary": summarize(results),
        "checks": results,
        "warnings": warnings,
    }
    path = os.path.join(cwd, ".coregy", LAST_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    _ignore_last_file(cwd)
    return result


def _ignore_last_file(cwd):
    """Keep the per-machine result out of git: .coregy/ itself is committed."""
    path = os.path.join(cwd, ".coregy", ".gitignore")
    existing = _read(path)
    if LAST_FILE in existing.split():
        return
    with open(path, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("%s\n" % LAST_FILE)


def load_last(cwd):
    data = _read_json(os.path.join(cwd, ".coregy", LAST_FILE))
    return data if isinstance(data, dict) else None


def failure_issues(result):
    """One fix-loop issue string per failed check (for state.py request-fixes)."""
    issues = []
    for c in result.get("checks", []):
        if c["status"] not in ("failed", "timeout"):
            continue
        # Drop blank lines and separator rules (-----, =====) so the excerpt
        # keeps the assertion and the summary line, not runner decoration.
        lines = [ln.strip() for ln in c.get("output_tail", "").splitlines()
                 if not _RULE_RE.match(ln)]
        excerpt = " | ".join(lines[-5:])[-400:]
        issues.append("%s failed (`%s`, exit %s): %s"
                      % (c["name"], c["command"], c["exit_code"], excerpt))
    return issues


def write_default_config(cwd, force=False):
    path = os.path.join(cwd, ".coregy", CONFIG_FILE)
    if os.path.exists(path) and not force:
        raise FileExistsError("%s exists -- pass --force to overwrite" % path)
    root = _detect_dir(cwd)
    lines = [
        "# Coregy verification commands -- run by verify.py and gated on by agents.",
        "# Detected from this project's config files; edit to taste.",
        "# An empty string disables a check. Remove this file to go back to detection.",
        "checks:",
    ]
    for kind in CHECK_ORDER:
        command, source = root.get(kind, ("", "not detected"))
        lines.append('  %s: "%s"    # %s' % (kind, command.replace('"', '\\"'), source))
    lines.append("timeout: %d    # seconds per check" % DEFAULT_TIMEOUT)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


# ---------------------------------------------------------------------------
# CLI (coregy-cli-v1)
# ---------------------------------------------------------------------------

def _output(data):
    print(json.dumps(data, indent=2, default=str))


def _fail(msg, json_mode=False):
    if json_mode:
        print(json.dumps({"ok": False, "error": msg}))
    else:
        print("Error: %s" % msg, file=sys.stderr)
    sys.exit(1)


def _print_result(result):
    if not result["checks"]:
        state = "NOTHING RUN"
    else:
        state = "PASSED" if result["passed"] else "FAILED"
    if result.get("reused"):
        state += " (reused: no changes since %s)" % result.get("ran_at")
    print("Verify: %s -- %s" % (state, result["summary"]))
    for c in result["checks"]:
        print("  [%s] %-14s %s  (%ss)" % (
            "x" if c["status"] == "passed" else "!" if c["status"] != "missing" else "-",
            c["name"], c["command"], c.get("duration_s", "?")))
    for c in result["checks"]:
        if c["status"] in ("failed", "timeout"):
            print("\n--- %s: %s ---\n%s" % (c["name"], c["command"], c["output_tail"]))
    for w in result.get("warnings", []):
        print("Warning: %s" % w)


def main():
    parent = argparse.ArgumentParser(add_help=False)
    # default=SUPPRESS is load-bearing: see state.py -- a concrete default on
    # the subparser would clobber a --cwd given before the subcommand.
    parent.add_argument("--cwd", default=argparse.SUPPRESS,
                        help="Project root directory (default: .)")

    parser = argparse.ArgumentParser(
        description="Coregy Workflow verification runner (lint / typecheck / test)",
        parents=[parent],
    )
    sub = parser.add_subparsers(dest="command")

    p_detect = sub.add_parser("detect", parents=[parent],
                              help="Show the commands that would run")
    p_detect.add_argument("--json", action="store_true", dest="json_mode")

    p_run = sub.add_parser("run", parents=[parent], help="Run the checks")
    p_run.add_argument("--only", default="",
                       help="Comma-separated checks (lint,typecheck,test or e.g. test:web)")
    p_run.add_argument("--timeout", type=int, default=None,
                       help="Seconds per check (default: verify.yaml or %d)" % DEFAULT_TIMEOUT)
    p_run.add_argument("--reuse", action="store_true",
                       help="Return the last result if no file changed since it ran")
    p_run.add_argument("--fail-fast", action="store_true",
                       help="Stop at the first failing check")
    p_run.add_argument("--strict", action="store_true",
                       help="Exit 1 when a check fails (default: exit 0, read `passed`)")
    p_run.add_argument("--json", action="store_true", dest="json_mode")

    p_last = sub.add_parser("last", parents=[parent], help="Show the last run's result")
    p_last.add_argument("--json", action="store_true", dest="json_mode")

    p_init = sub.add_parser("init", parents=[parent],
                            help="Write .coregy/verify.yaml with the detected commands")
    p_init.add_argument("--force", action="store_true", help="Overwrite an existing file")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    cwd = os.path.abspath(getattr(args, "cwd", "."))
    json_mode = getattr(args, "json_mode", False)

    try:
        if args.command == "detect":
            checks = resolve_checks(cwd)
            if json_mode:
                _output({"ok": True, "checks": checks})
            elif not checks:
                print("No checks detected. Run `verify.py init` to write .coregy/%s."
                      % CONFIG_FILE)
            else:
                for c in checks:
                    print("%-14s %s    (%s)" % (c["name"], c["command"], c["source"]))

        elif args.command == "run":
            only = [p.strip() for p in args.only.split(",") if p.strip()] or None
            result = run_checks(cwd, only=only, timeout=args.timeout,
                                reuse=args.reuse, fail_fast=args.fail_fast)
            if json_mode:
                payload = dict(result)
                payload["ok"] = True
                payload["issues"] = failure_issues(result)
                _output(payload)
            else:
                _print_result(result)
            if args.strict and not result["passed"]:
                sys.exit(1)

        elif args.command == "last":
            result = load_last(cwd)
            if result is None:
                _fail("No verification run yet -- run `verify.py run`", json_mode)
            if json_mode:
                _output(result)
            else:
                _print_result(result)

        elif args.command == "init":
            path = write_default_config(cwd, force=args.force)
            print("Wrote %s" % path)

    except (FileExistsError, OSError, ValueError) as exc:
        _fail(str(exc), json_mode)


if __name__ == "__main__":
    main()
