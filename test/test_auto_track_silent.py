"""Tests for silent auto-tracking: continuation detection, titles, track_prompt and the hook."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(ROOT, "plugins", "coregy-workflow", "skills",
                           "project-profile", "scripts")
HOOK = os.path.join(ROOT, "plugins", "coregy-workflow", "hooks", "auto_track_hook.py")
sys.path.insert(0, SCRIPTS_DIR)

import tracker
from auto_track import (
    ACTIVE_WINDOW_SECONDS,
    TITLE_MAX,
    build_tracking_note,
    clean_title,
    detect_intent,
    is_continuation,
    track_prompt,
)


class TestContinuation(unittest.TestCase):
    def test_vietnamese(self):
        for p in ("ok làm tiếp auto-track đi", "tiếp tục phần test nhé",
                  "làm tiếp chế độ quick đi"):
            self.assertTrue(is_continuation(p.lower()), p)

    def test_english(self):
        for p in ("continue with the integration tests", "go ahead and fix it",
                  "do the same for the signup form"):
            self.assertTrue(is_continuation(p.lower()), p)

    def test_new_tasks_are_not_continuations(self):
        for p in ("thêm nút logout vào header", "add rate limiting to login"):
            self.assertFalse(is_continuation(p.lower()), p)

    def test_tiep_inside_a_compound_is_not_a_continuation(self):
        for p in ("sửa lỗi tiếp nhận đơn hàng", "tiếp nhận yêu cầu hoàn tiền",
                  "thêm kết nối trực tiếp tới db"):
            self.assertFalse(is_continuation(p.lower()), p)

    def test_tiep_after_a_verb_or_at_the_start(self):
        for p in ("ok tiếp đi", "viết tiếp test cho login", "tiếp phần style nhé"):
            self.assertTrue(is_continuation(p.lower()), p)

    def test_marker_late_in_prompt_is_ignored(self):
        self.assertFalse(is_continuation(
            "add a retry button so users can continue after errors".lower()))

    def test_detect_intent_carries_flag(self):
        self.assertTrue(detect_intent("ok làm tiếp phần style cho nút đó đi")["continuation"])
        self.assertFalse(detect_intent("thêm nút logout vào header nhé")["continuation"])


class TestCleanTitle(unittest.TestCase):
    def test_strips_vietnamese_filler(self):
        self.assertEqual(clean_title("giờ sửa lỗi validate email ở form đăng ký giúp mình"),
                         "Sửa lỗi validate email ở form đăng ký")
        self.assertEqual(clean_title("thêm nút logout vào header nhé"),
                         "Thêm nút logout vào header")
        self.assertEqual(clean_title("ok làm tiếp auto-track đi"), "Auto-track")

    def test_strips_english_filler(self):
        self.assertEqual(clean_title("Please add rate limiting to the login endpoint."),
                         "Add rate limiting to the login endpoint")

    def test_filler_inside_words_is_kept(self):
        self.assertEqual(clean_title("okta login integration"), "Okta login integration")
        self.assertEqual(clean_title("add the đinh tán icon"), "Add the đinh tán icon")

    def test_first_line_only(self):
        self.assertEqual(clean_title("fix the bug\nmore detail here"), "Fix the bug")

    def test_long_title_ends_at_clause(self):
        title = clean_title("sửa lỗi crash khi upload ảnh lớn hơn 10MB trong màn hình "
                            "profile của user, đặc biệt là trên android khi mạng yếu")
        self.assertEqual(title, "Sửa lỗi crash khi upload ảnh lớn hơn 10MB trong màn hình "
                                "profile của user")

    def test_long_title_ends_at_word(self):
        title = clean_title("implement " + "very " * 30 + "long thing")
        self.assertLessEqual(len(title), TITLE_MAX)
        self.assertFalse(title.endswith(" "))
        self.assertTrue(title.endswith("very"))

    def test_only_filler_falls_back_to_the_line(self):
        self.assertEqual(clean_title("ok"), "Ok")
        self.assertEqual(clean_title(""), "")


class TrackerCase(unittest.TestCase):
    def setUp(self):
        self.cwd = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cwd, True)
        os.makedirs(os.path.join(self.cwd, ".coregy"))
        self.now = 1_800_000_000.0

    def track(self, prompt, at=0):
        return track_prompt(self.cwd, prompt, detect_intent(prompt), now=self.now + at)

    def items(self):
        return tracker.search(self.cwd, limit=50)


class TestTrackPrompt(TrackerCase):
    def test_new_task_is_created_in_progress(self):
        out = self.track("thêm nút logout vào header nhé")
        self.assertEqual(out["action"], "created")
        item = tracker.get_item(self.cwd, out["item"]["id"])
        self.assertEqual(item["status"], "in_progress")
        self.assertEqual(item["title"], "Thêm nút logout vào header")
        self.assertEqual(sorted(item["tags"]), ["auto", "feature"])
        self.assertIsNone(out["previous"])

    def test_bug_fix_tag(self):
        out = self.track("fix the crash when saving an empty profile")
        self.assertIn("bug-fix", tracker.get_item(self.cwd, out["item"]["id"])["tags"])

    def test_investigation_type(self):
        out = self.track("investigate why the nightly build got slower")
        self.assertEqual(out["item"]["type"], "investigation")
        self.assertEqual(tracker.get_item(self.cwd, out["item"]["id"])["status"],
                         "in_progress")

    def test_continuation_notes_the_active_item(self):
        first = self.track("thêm nút logout vào header nhé")
        out = self.track("ok làm tiếp phần style cho nút đó đi", at=60)
        self.assertEqual(out["action"], "noted")
        self.assertEqual(out["item"]["id"], first["item"]["id"])
        self.assertIn("phần style", tracker.get_item(self.cwd, first["item"]["id"])["notes"])
        self.assertEqual(len(self.items()), 1)

    def test_notes_accumulate(self):
        first = self.track("thêm nút logout vào header nhé")
        self.track("ok làm tiếp phần style cho nút đó đi", at=60)
        self.track("tiếp tục thêm test cho nút logout", at=120)
        notes = tracker.get_item(self.cwd, first["item"]["id"])["notes"]
        self.assertEqual(len(notes.splitlines()), 2)

    def test_repeated_title_is_a_note(self):
        self.track("fix the flaky test in test_auth.py")
        out = self.track("Fix the flaky test in test_auth.py!", at=30)
        self.assertEqual(out["action"], "noted")

    def test_new_task_replaces_active_and_reports_previous(self):
        first = self.track("thêm nút logout vào header nhé")
        out = self.track("giờ sửa lỗi validate email ở form đăng ký giúp mình", at=60)
        self.assertEqual(out["action"], "created")
        self.assertEqual(out["previous"]["id"], first["item"]["id"])
        # The previous item is left open -- only the model knows if it is done.
        self.assertEqual(tracker.get_item(self.cwd, first["item"]["id"])["status"],
                         "in_progress")

    def test_stale_continuation_starts_fresh(self):
        self.track("thêm nút logout vào header nhé")
        out = self.track("ok làm tiếp phần style cho nút đó đi",
                         at=ACTIVE_WINDOW_SECONDS + 1)
        self.assertEqual(out["action"], "created")

    def test_closed_item_is_not_continued(self):
        first = self.track("thêm nút logout vào header nhé")
        tracker.transition_status(self.cwd, first["item"]["id"], "completed")
        out = self.track("ok làm tiếp phần style cho nút đó đi", at=60)
        self.assertEqual(out["action"], "created")
        self.assertIsNone(out["previous"])

    def test_pointer_is_gitignored_once(self):
        self.track("thêm nút logout vào header nhé")
        self.track("ok làm tiếp phần style cho nút đó đi", at=60)
        with open(os.path.join(self.cwd, ".coregy", ".gitignore")) as f:
            self.assertEqual(f.read(), "auto_track.json\n")

    def test_corrupt_pointer_is_ignored(self):
        with open(os.path.join(self.cwd, ".coregy", "auto_track.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(self.track("thêm nút logout vào header nhé")["action"], "created")

    def test_pointer_to_missing_item_is_ignored(self):
        with open(os.path.join(self.cwd, ".coregy", "auto_track.json"), "w") as f:
            json.dump({"item_id": "itm_gone", "updated_at": self.now}, f)
        out = self.track("ok làm tiếp phần style cho nút đó đi")
        self.assertEqual(out["action"], "created")


class TestTrackingNote(unittest.TestCase):
    CMD = "python3 /x/tracker.py"

    def item(self, **kw):
        base = {"id": "itm_1", "type": "task", "title": "Add logout", "status": "in_progress"}
        base.update(kw)
        return base

    def test_created(self):
        note = build_tracking_note({"action": "created", "item": self.item(),
                                    "previous": None}, self.CMD)
        self.assertIn('Tracked as task itm_1 "Add logout"', note)
        self.assertIn("do not ask the user", note)
        self.assertIn("`tracker.py update itm_1 --status completed`", note)
        self.assertIn("--status abandoned", note)
        self.assertEqual(note.count(self.CMD), 1)

    def test_noted(self):
        note = build_tracking_note({"action": "noted", "item": self.item(),
                                    "previous": None}, self.CMD)
        self.assertIn("Continuing task itm_1", note)
        self.assertIn("tracker.py create", note)

    def test_investigation_closes_as_concluded(self):
        note = build_tracking_note({"action": "created",
                                    "item": self.item(type="investigation"),
                                    "previous": None}, self.CMD)
        self.assertIn("--status concluded", note)

    def test_previous(self):
        note = build_tracking_note({"action": "created", "item": self.item(),
                                    "previous": self.item(id="itm_0", title="Old")},
                                   self.CMD)
        self.assertIn('Previous item itm_0 "Old" is still in_progress', note)

    def test_never_asks(self):
        for action in ("created", "noted"):
            note = build_tracking_note({"action": action, "item": self.item(),
                                        "previous": None}, self.CMD)
            self.assertNotIn("ask the user whether", note)


class TestHook(TrackerCase):
    def hook(self, prompt, mode=None):
        env = dict(os.environ)
        env.pop("COREGY_AUTO_TRACK", None)
        env.pop("HODY_AUTO_TRACK", None)
        if mode is not None:
            env["COREGY_AUTO_TRACK"] = mode
        result = subprocess.run([sys.executable, HOOK],
                                input=json.dumps({"cwd": self.cwd, "prompt": prompt}),
                                capture_output=True, text=True, timeout=10, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return None
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_silent_by_default(self):
        context = self.hook("thêm nút logout vào header nhé")
        self.assertIn("Tracked as task", context)
        self.assertEqual(len(self.items()), 1)

    def test_ask_mode_keeps_legacy_hint_and_writes_nothing(self):
        context = self.hook("thêm nút logout vào header nhé", mode="ask")
        self.assertIn("ask the user whether to track it", context)
        self.assertFalse(os.path.exists(os.path.join(self.cwd, ".coregy", "tracker.db")))

    def test_off(self):
        for mode in ("0", "off"):
            self.assertIsNone(self.hook("thêm nút logout vào header nhé", mode=mode))

    def test_question_is_not_tracked(self):
        self.assertIsNone(self.hook("sao lại bị lỗi này?"))

    def test_active_workflow_skips(self):
        with open(os.path.join(self.cwd, ".coregy", "state.json"), "w") as f:
            json.dump({"status": "in_progress"}, f)
        self.assertIsNone(self.hook("thêm nút logout vào header nhé"))

    def test_uninitialized_project_skips(self):
        shutil.rmtree(os.path.join(self.cwd, ".coregy"))
        self.assertIsNone(self.hook("thêm nút logout vào header nhé"))
        self.assertFalse(os.path.exists(os.path.join(self.cwd, ".coregy")))

    def test_tracker_path_in_note_is_real(self):
        context = self.hook("thêm nút logout vào header nhé")
        path = context.split("`tracker.py` = `python3 ", 1)[1].split("`", 1)[0]
        self.assertTrue(os.path.isfile(path), path)


if __name__ == "__main__":
    unittest.main()
