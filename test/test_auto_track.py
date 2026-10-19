"""Tests for auto-track intent detector (auto_track.py)."""
import json
import os
import subprocess
import sys
import unittest

SCRIPT_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "coregy-workflow",
    "skills",
    "project-profile",
    "scripts",
)
sys.path.insert(0, os.path.abspath(SCRIPT_DIR))

from auto_track import (
    detect_intent,
    is_meta_command,
    is_question,
    find_task_verb,
    classify_subtype,
)


class TestMetaCommand(unittest.TestCase):
    def test_slash_command(self):
        self.assertTrue(is_meta_command("/help"))
        self.assertTrue(is_meta_command("/coregy-workflow:start-feature add auth"))

    def test_shell_prefix(self):
        self.assertTrue(is_meta_command("!ls"))

    def test_at_mention(self):
        self.assertTrue(is_meta_command("@agent fix this"))

    def test_empty(self):
        self.assertTrue(is_meta_command(""))
        self.assertTrue(is_meta_command("   "))

    def test_normal_prompt(self):
        self.assertFalse(is_meta_command("add a new endpoint"))


class TestIsQuestion(unittest.TestCase):
    def test_english_question_words(self):
        self.assertTrue(is_question("what does this code do"))
        self.assertTrue(is_question("how can i fix this"))
        self.assertTrue(is_question("why is this failing"))

    def test_vietnamese_question_phrases(self):
        self.assertTrue(is_question("thêm rule kiểu gì nhỉ"))
        self.assertTrue(is_question("làm như thế nào"))
        self.assertTrue(is_question("hiện tại đã có hay chưa"))
        self.assertTrue(is_question("tại sao lại fail"))

    def test_trailing_question_mark(self):
        self.assertTrue(is_question("something is wrong here?"))

    def test_statement_not_question(self):
        self.assertFalse(is_question("add a new oauth endpoint"))
        self.assertFalse(is_question("fix the login bug"))


class TestFindTaskVerb(unittest.TestCase):
    def test_english_verb_at_start(self):
        self.assertEqual(find_task_verb("add a new endpoint"), ("add", "en"))
        self.assertEqual(find_task_verb("fix the login bug"), ("fix", "en"))
        self.assertEqual(find_task_verb("refactor the auth module"), ("refactor", "en"))

    def test_vietnamese_verb_at_start(self):
        self.assertEqual(find_task_verb("thêm rule mới cho project"), ("thêm", "vi"))
        self.assertEqual(find_task_verb("sửa bug login"), ("sửa", "vi"))

    def test_no_verb(self):
        self.assertIsNone(find_task_verb("the system is slow"))
        self.assertIsNone(find_task_verb("login page broken"))

    def test_verb_only_in_leading_words(self):
        self.assertIsNone(find_task_verb(
            "i was looking and noticed maybe we could add something"
        ))


class TestClassifySubtype(unittest.TestCase):
    def test_bug_fix_indicators(self):
        self.assertEqual(classify_subtype("fix the login bug"), "bug-fix")
        self.assertEqual(classify_subtype("debug this exception"), "bug-fix")
        self.assertEqual(classify_subtype("sửa lỗi login"), "bug-fix")

    def test_investigation_indicators(self):
        self.assertEqual(
            classify_subtype("investigate the slow query"), "investigation"
        )
        self.assertEqual(
            classify_subtype("tìm hiểu cách xử lý"), "investigation"
        )

    def test_default_feature(self):
        self.assertEqual(classify_subtype("add a new endpoint"), "feature")
        self.assertEqual(classify_subtype("refactor auth"), "feature")


class TestDetectIntent(unittest.TestCase):
    def test_simple_task(self):
        result = detect_intent("add a new oauth2 login endpoint to the API")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "task")
        self.assertEqual(result["subtype"], "feature")
        self.assertEqual(result["verb"], "add")
        self.assertEqual(result["language"], "en")

    def test_vietnamese_task(self):
        result = detect_intent(
            "thêm endpoint mới cho login flow của user dashboard"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "task")
        self.assertEqual(result["language"], "vi")
        self.assertEqual(result["verb"], "thêm")

    def test_bug_fix_classified(self):
        result = detect_intent("fix the broken login bug in production")
        self.assertIsNotNone(result)
        self.assertEqual(result["subtype"], "bug-fix")

    def test_investigation_classified(self):
        result = detect_intent(
            "investigate why the database queries are slow"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "investigation")
        self.assertEqual(result["subtype"], "investigation")

    def test_question_returns_none(self):
        self.assertIsNone(detect_intent("what does this function do"))
        self.assertIsNone(detect_intent("thêm rule kiểu gì nhỉ"))
        self.assertIsNone(detect_intent("how do I add a new endpoint"))

    def test_meta_command_returns_none(self):
        self.assertIsNone(detect_intent("/coregy-workflow:status"))
        self.assertIsNone(detect_intent("!ls -la"))

    def test_empty_returns_none(self):
        self.assertIsNone(detect_intent(""))
        self.assertIsNone(detect_intent("   "))

    def test_short_prompt_returns_none(self):
        self.assertIsNone(detect_intent("add it"))
        self.assertIsNone(detect_intent("fix"))

    def test_no_verb_returns_none(self):
        self.assertIsNone(detect_intent("the production server has been down"))

    def test_confidence_levels(self):
        # Medium length
        medium = detect_intent("add new oauth2 login endpoint")
        self.assertIsNotNone(medium)
        self.assertEqual(medium["confidence"], "medium")

        # Long, detailed
        long_result = detect_intent(
            "add a new oauth2 login endpoint that integrates with Google "
            "and GitHub providers with proper token refresh logic"
        )
        self.assertIsNotNone(long_result)
        self.assertEqual(long_result["confidence"], "high")

    def test_title_hint_truncated(self):
        long_prompt = "add " + ("a very long description " * 10)
        result = detect_intent(long_prompt)
        self.assertIsNotNone(result)
        self.assertLessEqual(len(result["title_hint"]), 80)

    def test_title_hint_first_line_only(self):
        result = detect_intent(
            "add new endpoint for oauth login\n\nwith refresh token support"
        )
        self.assertIsNotNone(result)
        self.assertNotIn("\n", result["title_hint"])
        self.assertIn("oauth", result["title_hint"])


class TestCLI(unittest.TestCase):
    def _run(self, args, stdin_text=None):
        cmd = [sys.executable, os.path.join(SCRIPT_DIR, "auto_track.py")] + args
        result = subprocess.run(
            cmd,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result

    def test_cli_with_argument(self):
        result = self._run(["add a new login endpoint", "--json"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout.strip())
        self.assertEqual(data.get("type"), "task")

    def test_cli_with_stdin(self):
        result = self._run(["--json"], stdin_text="fix the broken login bug")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout.strip())
        self.assertEqual(data.get("subtype"), "bug-fix")

    def test_cli_no_intent(self):
        result = self._run(["--json"], stdin_text="what is this")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout.strip())
        self.assertEqual(data, {})

    def test_cli_human_output(self):
        result = self._run(["add a new endpoint to the API"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Detected", result.stdout)

    def test_cli_no_intent_human_output(self):
        result = self._run([], stdin_text="what is this")
        self.assertEqual(result.returncode, 0)
        self.assertIn("No task intent", result.stdout)


if __name__ == "__main__":
    unittest.main()
