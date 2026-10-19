"""Tests for quality_gate.py hook."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

# Add the hook to path
HOOK_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "hody-workflow",
    "hooks",
)
sys.path.insert(0, os.path.abspath(HOOK_DIR))

from quality_gate import (
    check_file,
    should_skip,
    run_quality_gate,
    is_git_commit_command,
    SECRET_PATTERNS,
    SECURITY_PATTERNS,
)


class TestShouldSkip(unittest.TestCase):
    def test_skip_lock_files(self):
        self.assertTrue(should_skip("package-lock.json.lock"))
        self.assertTrue(should_skip("yarn.lock"))
        self.assertTrue(should_skip("go.sum"))

    def test_skip_minified(self):
        self.assertTrue(should_skip("bundle.min.js"))
        self.assertTrue(should_skip("styles.min.css"))

    def test_skip_binary(self):
        self.assertTrue(should_skip("logo.png"))
        self.assertTrue(should_skip("font.woff2"))
        self.assertTrue(should_skip("icon.svg"))

    def test_skip_node_modules(self):
        self.assertTrue(should_skip("node_modules/lodash/index.js"))

    def test_skip_vendor(self):
        self.assertTrue(should_skip("vendor/autoload.php"))

    def test_skip_dist(self):
        self.assertTrue(should_skip("dist/bundle.js"))

    def test_dont_skip_source(self):
        self.assertFalse(should_skip("src/auth.ts"))
        self.assertFalse(should_skip("main.py"))
        self.assertFalse(should_skip("server/handler.go"))

    def test_skip_map_files(self):
        self.assertTrue(should_skip("bundle.js.map"))


class TestCheckFile(unittest.TestCase):
    def _write_file(self, tmpdir, filename, content):
        fpath = os.path.join(tmpdir, filename)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w") as f:
            f.write(content)
        return filename

    def test_clean_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fname = self._write_file(tmpdir, "clean.ts", "const x = 42;\nexport default x;\n")
            issues = check_file(tmpdir, fname)
            self.assertEqual(issues, [])

    def test_hardcoded_api_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fname = self._write_file(
                tmpdir, "config.ts",
                'const API_KEY = "abcdef1234567890abcdef";\n'
            )
            issues = check_file(tmpdir, fname)
            self.assertTrue(any("API key" in i for i in issues))

    def test_hardcoded_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fname = self._write_file(
                tmpdir, "db.py",
                'password = "supersecretpassword123"\n'
            )
            issues = check_file(tmpdir, fname)
            self.assertTrue(any("secret" in i.lower() or "password" in i.lower() for i in issues))

    def test_aws_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fname = self._write_file(
                tmpdir, "config.js",
                'const key = "AKIAIOSFODNN7EXAMPLE";\n'
            )
            issues = check_file(tmpdir, fname)
            self.assertTrue(any("AWS" in i for i in issues))

    def test_private_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fname = self._write_file(
                tmpdir, "key.pem",
                '-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg...\n'
            )
            issues = check_file(tmpdir, fname)
            self.assertTrue(any("Private key" in i for i in issues))

    def test_eval_usage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fname = self._write_file(
                tmpdir, "handler.js",
                'const result = eval(userInput);\n'
            )
            issues = check_file(tmpdir, fname)
            self.assertTrue(any("eval" in i for i in issues))

    def test_innerhtml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fname = self._write_file(
                tmpdir, "component.js",
                'el.innerHTML = userContent;\n'
            )
            issues = check_file(tmpdir, fname)
            self.assertTrue(any("innerHTML" in i for i in issues))

    def test_security_skipped_in_test_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fname = self._write_file(
                tmpdir, "handler.test.js",
                'const result = eval("2+2");\n'
            )
            issues = check_file(tmpdir, fname)
            # Security patterns should be skipped in test files
            self.assertFalse(any("eval" in i for i in issues))

    def test_large_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fname = self._write_file(
                tmpdir, "big.json",
                "x" * (600 * 1024)
            )
            issues = check_file(tmpdir, fname)
            self.assertTrue(any("Large file" in i for i in issues))

    def test_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            issues = check_file(tmpdir, "nonexistent.ts")
            self.assertEqual(issues, [])


class TestRunQualityGate(unittest.TestCase):
    def test_no_hody_dir_passes(self):
        """Quality gate should pass when there are no staged files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # run_quality_gate calls get_staged_files which needs git
            # Without a git repo, staged files list is empty → pass
            passed, report = run_quality_gate(tmpdir)
            self.assertTrue(passed)
            self.assertIn("No staged files", report)


# =====================================================================
# R2 — git commit detection
#
# The old `^\s*git\s+commit\b` regex never matched a realistic commit
# command, so this hook was dead for 12 versions. These tests pin down
# both directions: what MUST trip the gate and what MUST NOT.
# =====================================================================


class TestIsGitCommitCommandTrue(unittest.TestCase):
    """Commands that MUST be recognised as `git commit`."""

    def assertCommit(self, command):
        self.assertTrue(
            is_git_commit_command(command),
            "expected git-commit detection for: %r" % command,
        )

    def test_bare_commit(self):
        self.assertCommit("git commit")

    def test_commit_with_message(self):
        self.assertCommit('git commit -m "feat: add thing"')

    def test_leading_whitespace(self):
        self.assertCommit("   git commit -m x")

    def test_chained_with_and(self):
        self.assertCommit("git add -A && git commit -m x")

    def test_chained_with_or(self):
        self.assertCommit("git add -A || git commit -m x")

    def test_sequenced_with_semicolon(self):
        self.assertCommit("foo; git commit")

    def test_newline_separated_chain(self):
        self.assertCommit("git add -A\ngit commit -m x")

    def test_env_assignment_prefix(self):
        self.assertCommit("VAR=1 git commit")

    def test_multiple_env_assignments(self):
        self.assertCommit("GIT_AUTHOR_NAME=x GIT_AUTHOR_EMAIL=y git commit -m z")

    def test_env_assignment_after_chain(self):
        self.assertCommit("npm test && HUSKY=0 git commit -m x")

    def test_git_dash_capital_c(self):
        self.assertCommit("git -C /path/to/repo commit -m x")

    def test_git_dash_c_config(self):
        self.assertCommit("git -c user.name=x commit -m y")

    def test_git_dash_c_config_then_dash_capital_c(self):
        self.assertCommit("git -c core.hooksPath=/dev/null -C /tmp/r commit")

    def test_git_dir_option(self):
        self.assertCommit("git --git-dir=/tmp/r/.git commit -m x")

    def test_git_dir_option_separate_value(self):
        self.assertCommit("git --git-dir /tmp/r/.git commit -m x")

    def test_no_pager_flag(self):
        self.assertCommit("git --no-pager commit -m x")

    def test_pipeline(self):
        self.assertCommit("make build | tee log; git commit -m x")

    def test_env_wrapper(self):
        self.assertCommit("env git commit -m x")

    def test_sudo_style_command_wrapper(self):
        self.assertCommit("command git commit -m x")

    def test_absolute_git_path(self):
        self.assertCommit("/usr/bin/git commit -m x")

    def test_subshell(self):
        self.assertCommit("(cd /tmp/r && git commit -m x)")

    def test_message_containing_the_word_commit(self):
        self.assertCommit('git commit -m "commit the fix"')

    def test_commit_after_a_quoted_echo(self):
        self.assertCommit('echo "committing now" && git commit -m x')

    def test_trailing_comment(self):
        self.assertCommit("git commit -m x  # ship it")

    def test_commit_amend(self):
        self.assertCommit("git commit --amend --no-edit")

    def test_background_ampersand_separator(self):
        self.assertCommit("sleep 1 & git commit -m x")

    def test_sudo(self):
        self.assertCommit("sudo git commit -m x")

    def test_wrapper_with_its_own_option(self):
        self.assertCommit("env -i git commit -m x")

    def test_if_then_block(self):
        self.assertCommit("if [ -f f ]; then git commit -m x; fi")

    def test_while_do_block(self):
        self.assertCommit("while read f; do git commit -m x; done")

    def test_brace_group(self):
        self.assertCommit("{ git commit -m x; }")

    def test_commit_reading_its_message_from_a_heredoc(self):
        """The opener line is a real command -- only the body is data."""
        self.assertCommit("git commit -F - <<EOF\nthe message\nEOF")

    def test_commit_chained_after_a_heredoc_terminator(self):
        """Blanking a heredoc body must not swallow the rest of the script."""
        self.assertCommit(
            "cat <<EOF > /tmp/f\nhello\nEOF\ngit add -A && git commit -m x"
        )


class TestIsGitCommitCommandFalse(unittest.TestCase):
    """Commands that MUST NOT be treated as `git commit`."""

    def assertNotCommit(self, command):
        self.assertFalse(
            is_git_commit_command(command),
            "false positive git-commit detection for: %r" % command,
        )

    def test_empty(self):
        self.assertNotCommit("")

    def test_none(self):
        self.assertNotCommit(None)

    def test_echo_double_quoted(self):
        self.assertNotCommit('echo "git commit"')

    def test_echo_single_quoted(self):
        self.assertNotCommit("echo 'git commit -m x'")

    def test_git_log_grep(self):
        self.assertNotCommit('git log --grep="commit"')

    def test_git_log_grep_equals_unquoted(self):
        self.assertNotCommit("git log --grep=commit")

    def test_git_push(self):
        self.assertNotCommit("git push origin main")

    def test_git_status(self):
        self.assertNotCommit("git status")

    def test_git_rev_parse(self):
        self.assertNotCommit("git rev-parse HEAD")

    def test_git_show_commit_ref(self):
        self.assertNotCommit("git show HEAD --format=%H  # last commit")

    def test_grep_over_source(self):
        self.assertNotCommit("grep -rn 'git commit' plugins/")

    def test_leading_comment_line(self):
        self.assertNotCommit("# git commit -m x")

    def test_commented_line_in_chain(self):
        self.assertNotCommit("git status\n# git commit -m x")

    def test_word_containing_commit(self):
        self.assertNotCommit("git commit-tree-helper")

    def test_other_binary_named_like_git(self):
        self.assertNotCommit("gitk commit")

    def test_python_script_mentioning_commit(self):
        self.assertNotCommit('python3 -c "print(\'git commit\')"')

    def test_heredoc_style_message_only(self):
        self.assertNotCommit("git log -1 --pretty=%s")

    def test_git_commit_inside_a_git_config_value(self):
        self.assertNotCommit('git config alias.ci "commit -m"')

    # A false positive denies a Bash call that was never a commit, which is
    # worse than the miss this parser replaced. Writing docs that *contain* a
    # commit command is routine for these agents.

    def test_quoted_heredoc_body_is_data_not_a_command(self):
        self.assertNotCommit(
            "cat > notes.md <<'EOF'\ngit commit -m \"x\"\nEOF"
        )

    def test_unquoted_heredoc_body_is_data_not_a_command(self):
        self.assertNotCommit("cat > notes.md <<EOF\ngit commit -m x\nEOF")

    def test_indented_heredoc_body_is_data_not_a_command(self):
        self.assertNotCommit(
            'cat >> README.md <<-DOC\n  git commit -m "msg"\nDOC'
        )

    def test_here_string_is_not_treated_as_a_heredoc(self):
        self.assertNotCommit('cat <<< "git commit"')


# =====================================================================
# Hook end-to-end (stdin JSON -> stdout JSON), driven as a subprocess
# exactly the way Claude Code invokes it.
# =====================================================================

HOOK_PATH = os.path.abspath(os.path.join(HOOK_DIR, "quality_gate.py"))

AWS_KEY_LINE = 'const key = "AKIA' + "IOSFODNN7EXAMPLE" + '";\n'


def _git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True
    )


@unittest.skipIf(shutil.which("git") is None, "git not available")
class TestQualityGateHookEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, ".hody"))
        _git(["init", "-q"], self.tmpdir)
        _git(["config", "user.email", "test@example.com"], self.tmpdir)
        _git(["config", "user.name", "Test"], self.tmpdir)
        self.env = dict(os.environ)
        self.env.pop("HODY_SKIP_QUALITY_GATE", None)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _stage(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        _git(["add", name], self.tmpdir)

    def _run_hook(self, payload, env=None):
        return subprocess.run(
            [sys.executable, HOOK_PATH],
            input=payload,
            capture_output=True,
            text=True,
            env=env or self.env,
        )

    def _hook_json(self, command):
        return self._run_hook(json.dumps({
            "tool_input": {"command": command},
            "cwd": self.tmpdir,
        }))

    def test_malformed_stdin_fails_open(self):
        """Invalid JSON on stdin must never block the tool call."""
        result = self._run_hook("not json at all")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_empty_stdin_fails_open(self):
        result = self._run_hook("")
        self.assertEqual(result.returncode, 0)

    def test_non_commit_command_is_ignored(self):
        self._stage("config.js", AWS_KEY_LINE)
        result = self._hook_json("git status")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_denies_commit_when_staged_file_has_a_secret(self):
        self._stage("config.js", AWS_KEY_LINE)
        result = self._hook_json('git commit -m "add config"')
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        hook_out = payload["hookSpecificOutput"]
        self.assertEqual(hook_out["permissionDecision"], "deny")
        self.assertIn("config.js", hook_out["permissionDecisionReason"])

    def test_denies_chained_add_and_commit(self):
        """Acceptance criterion 4: `git add -A && git commit -m x` is caught."""
        self._stage("config.js", AWS_KEY_LINE)
        result = self._hook_json('git add -A && git commit -m "x"')
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_denies_commit_with_global_option(self):
        self._stage("config.js", AWS_KEY_LINE)
        result = self._hook_json('git -c user.name=bot commit -m "x"')
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_allows_clean_commit(self):
        self._stage("clean.js", "export const x = 42;\n")
        result = self._hook_json('git commit -m "clean"')
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertNotIn(
            "permissionDecision", payload["hookSpecificOutput"]
        )

    def test_skip_env_var_bypasses_the_gate(self):
        self._stage("config.js", AWS_KEY_LINE)
        env = dict(self.env)
        env["HODY_SKIP_QUALITY_GATE"] = "1"
        result = self._run_hook(
            json.dumps({
                "tool_input": {"command": "git commit -m x"},
                "cwd": self.tmpdir,
            }),
            env=env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_uninitialized_project_is_skipped(self):
        """No .hody/ dir -> the gate does not run at all."""
        shutil.rmtree(os.path.join(self.tmpdir, ".hody"))
        self._stage("config.js", AWS_KEY_LINE)
        result = self._hook_json("git commit -m x")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()


# =====================================================================
# Files staged by the same command
#
# PreToolUse fires before any part of `git add -A && git commit` runs, so the
# index does not yet hold the files being committed. v0.13.0 scanned only the
# index and let a hardcoded AWS key through on exactly that command.
# =====================================================================

HOOK = os.path.join(os.path.abspath(HOOK_DIR), "quality_gate.py")
AWS_LINE = 'const k = "AKIA' + 'ABCDEFGHIJKLMNOP";\n'  # split: keep this file clean


class TestAnalyzeCommitCommand(unittest.TestCase):
    def test_add_before_commit(self):
        from quality_gate import analyze_commit_command
        info = analyze_commit_command('git add -A && git commit -m "x"')
        self.assertEqual(info["add_args"], [["-A"]])
        self.assertFalse(info["commit_all"])

    def test_quoted_pathspec(self):
        from quality_gate import analyze_commit_command
        info = analyze_commit_command('git add "my file.js"; git commit -m x')
        self.assertEqual(info["add_args"], [["my file.js"]])

    def test_commit_all_flags(self):
        from quality_gate import analyze_commit_command
        for cmd in ("git commit -a -m x", "git commit --all", 'git commit -am "x"'):
            self.assertTrue(analyze_commit_command(cmd)["commit_all"], cmd)
        # -m's value is not a flag cluster
        self.assertFalse(analyze_commit_command("git commit -mall")["commit_all"])

    def test_add_after_commit_is_ignored(self):
        from quality_gate import analyze_commit_command
        info = analyze_commit_command("git commit -m x && git add -A")
        self.assertEqual(info["add_args"], [])

    def test_not_a_commit(self):
        from quality_gate import analyze_commit_command
        self.assertIsNone(analyze_commit_command('echo "git add -A && git commit"'))


@unittest.skipUnless(shutil.which("git"), "git not installed")
class TestGateSeesFilesStagedInSameCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name
        self.git("init", "-q")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        os.makedirs(os.path.join(self.cwd, ".hody"))
        self.git("commit", "-q", "--allow-empty", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git"] + list(args), cwd=self.cwd, check=True,
                       capture_output=True)

    def write(self, name, content):
        with open(os.path.join(self.cwd, name), "w") as f:
            f.write(content)

    def decision(self, command):
        payload = json.dumps({"tool_input": {"command": command}, "cwd": self.cwd})
        env = dict(os.environ)
        env.pop("HODY_SKIP_QUALITY_GATE", None)
        out = subprocess.run([sys.executable, HOOK], input=payload, env=env,
                             capture_output=True, text=True, timeout=30).stdout
        if not out.strip():
            return "no-op"
        return json.loads(out)["hookSpecificOutput"].get("permissionDecision", "allow")

    def test_add_all_then_commit_is_denied(self):
        self.write("leak.js", AWS_LINE)
        self.assertEqual(self.decision("git add -A && git commit -m x"), "deny")

    def test_add_specific_clean_file_is_allowed(self):
        self.write("leak.js", AWS_LINE)
        self.write("clean.txt", "ok\n")
        self.assertEqual(self.decision("git add clean.txt && git commit -m x"), "allow")

    def test_commit_all_scans_modified_tracked_files(self):
        self.write("app.js", "ok\n")
        self.git("add", "app.js")
        self.git("commit", "-q", "-m", "app")
        self.write("app.js", AWS_LINE)
        self.assertEqual(self.decision('git commit -am "x"'), "deny")
        self.assertEqual(self.decision('git commit -m "x"'), "allow")

    def test_staged_blob_is_scanned_not_working_tree(self):
        self.write("app.js", AWS_LINE)
        self.git("add", "app.js")
        self.write("app.js", "clean now, but the key is still staged\n")
        self.assertEqual(self.decision("git commit -m x"), "deny")
