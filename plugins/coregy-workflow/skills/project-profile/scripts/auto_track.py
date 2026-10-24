"""
Detect task intent from user prompts to enable auto-tracking.

Heuristic-based classifier — looks for imperative verbs, action words,
and feature mentions. Returns intent classification or None if no task
intent is detected.

Used by the UserPromptSubmit hook to record a tracker item -- silently --
when the user starts a new task outside the /start-feature workflow
(track_prompt), and to note continuations on the item already in hand.
"""
import argparse
import json
import os
import sys
import time


# English imperative verbs that often signal task intent
EN_TASK_VERBS = {
    "add", "create", "build", "implement", "write", "generate", "make",
    "develop", "introduce", "scaffold",
    "update", "change", "modify", "refactor", "rewrite", "rework",
    "improve", "optimize", "migrate", "convert", "rename", "extend",
    "fix", "patch", "resolve", "debug", "repair",
    "remove", "delete", "drop", "clean", "deprecate",
    "integrate", "connect", "wire",
    "deploy", "release", "publish", "ship",
    "investigate", "explore", "research",
}

# Vietnamese task verbs
VI_TASK_VERBS = {
    "thêm", "tạo", "viết", "làm", "xây", "dựng",
    "sửa", "chỉnh", "đổi", "thay",
    "tối", "cải", "chuyển",
    "xóa", "bỏ", "loại",
    "triển", "tích", "kết",
}

# Bug-fix specific indicators
BUG_FIX_INDICATORS = {
    "bug", "issue", "error", "exception", "broken", "fails", "failing",
    "crash", "stacktrace", "stack trace",
    "lỗi", "không chạy", "không work", "không hoạt động",
}

# Investigation indicators
INVESTIGATION_INDICATORS = {
    "investigate", "explore", "research", "look into",
    "tìm hiểu", "khám phá", "research",
}

# Question indicators (skip — these are questions, not tasks)
QUESTION_WORDS_EN = {
    "what", "how", "why", "when", "where", "who", "which",
    "is", "are", "does", "do", "can", "could", "should", "would", "will",
    "has", "have",
}

QUESTION_PHRASES_VI = {
    "kiểu gì", "thế nào", "như thế nào", "như nào",
    "tại sao", "vì sao", "sao lại",
    "có thể", "có nên", "có cần", "có phải",
    "khi nào", "ở đâu",
    "đã có", "hay chưa", "hay không", "có hay không",
}

# Continuation markers: the prompt carries on the work already in hand
# ("ok làm tiếp đi", "continue with the tests") rather than starting a task.
CONTINUATION_WORDS = {"continue", "resume", "proceed"}
# "tiếp" is also a syllable of unrelated compounds (tiếp nhận, trực tiếp), so
# it only counts after a verb / "ok" or at the start, and not before these.
VI_TIEP_COMPOUND_NEXT = {
    "nhận", "xúc", "thị", "cận", "đón", "khách", "tân", "viện", "sức", "giáp",
    "quản", "vận", "diễn", "tế", "thu", "nối", "điện", "kiến",
}
VI_TIEP_LEAD = {"ok", "oke", "okay", "ừ", "rồi", "giờ", "thì", "vậy"}
CONTINUATION_PHRASES = (
    "tiếp tục", "làm tiếp", "tiếp đi", "keep going", "go ahead", "go on",
    "carry on", "next step", "as well", "same for",
)

# Filler stripped from the start / end of a prompt to make a title.
LEADING_FILLER = (
    "bây giờ", "giờ thì", "giúp tôi", "giúp mình", "giúp em", "cho tôi", "cho mình",
    "bạn hãy", "làm ơn", "làm tiếp", "tiếp tục", "continue with", "ok", "oke", "okay", "okie", "ừ", "uhm", "giờ", "hãy", "now",
    "please", "pls", "let's", "lets", "so", "then", "and",
)
TRAILING_FILLER = (
    "giúp mình", "giúp tôi", "đi nhé", "đi nha", "đi", "nhé", "nha", "nhá", "luôn",
    "thôi", "với", "giúp", "please", "pls", "thanks",
)
TITLE_MAX = 80

META_COMMAND_PREFIXES = ("/", "!", "@")
MIN_PROMPT_LENGTH = 15
SHORT_PROMPT_WORDS = 4


def is_meta_command(prompt):
    """Slash commands, shell prefixes, and one-token replies."""
    stripped = prompt.strip()
    if not stripped:
        return True
    return stripped.startswith(META_COMMAND_PREFIXES)


def is_question(prompt_lower):
    """Detect if the prompt is a question rather than a task."""
    head = prompt_lower[:120]

    # Vietnamese question phrases (high signal even mid-sentence)
    for phrase in QUESTION_PHRASES_VI:
        if phrase in prompt_lower:
            return True

    # English question words at start
    first_word = head.split(maxsplit=1)[0] if head else ""
    first_word = first_word.strip(",.;:!?")
    if first_word in QUESTION_WORDS_EN:
        return True

    # Trailing question mark (excluding rhetorical markers mid-sentence)
    stripped = prompt_lower.rstrip()
    if stripped.endswith("?"):
        return True

    return False


def find_task_verb(prompt_lower):
    """Locate the first task verb in the leading portion of the prompt.

    Returns (verb, language) or None.
    """
    words = prompt_lower.split()[:6]
    for word in words:
        cleaned = word.strip(",.;:!?\"'()[]{}")
        if cleaned in VI_TASK_VERBS:
            return (cleaned, "vi")
        if cleaned in EN_TASK_VERBS:
            return (cleaned, "en")
    return None


def _words(text):
    return [w.strip(",.;:!?\"'()[]{}") for w in text.split()]


def is_continuation(prompt_lower):
    """True when the prompt continues the current work instead of starting one."""
    words = _words(prompt_lower)[:6]
    if any(w in CONTINUATION_WORDS for w in words):
        return True
    for i, w in enumerate(words):
        if w != "tiếp":
            continue
        nxt = words[i + 1] if i + 1 < len(words) else ""
        prev = words[i - 1] if i else ""
        if nxt in VI_TIEP_COMPOUND_NEXT:
            continue
        if i == 0 or prev in VI_TASK_VERBS or prev in VI_TIEP_LEAD:
            return True
    head = " ".join(words)
    return any(phrase in head for phrase in CONTINUATION_PHRASES)


def _strip_phrases(text, phrases, leading):
    """Repeatedly remove whole-word phrases from one end of text."""
    changed = True
    while changed and text:
        changed = False
        lower = text.lower()
        for phrase in phrases:
            if leading and (lower == phrase or lower.startswith(phrase + " ")):
                text = text[len(phrase):].lstrip(" ,.;:-")
                changed = True
                break
            if not leading and (lower == phrase or lower.endswith(" " + phrase)):
                text = text[:len(text) - len(phrase)].rstrip(" ,.;:-")
                changed = True
                break
    return text


def clean_title(prompt):
    """A tracker title from a prompt: first line, filler removed, <= TITLE_MAX chars."""
    line = (prompt or "").strip().splitlines()[0] if (prompt or "").strip() else ""
    line = line.strip().rstrip("!.?").strip()
    title = _strip_phrases(line, LEADING_FILLER, leading=True)
    title = _strip_phrases(title, TRAILING_FILLER, leading=False).strip(" ,.;:-!")
    title = title or line
    if len(title) > TITLE_MAX:
        window = title[:TITLE_MAX + 1]
        # Prefer ending at a clause break, then at a word break.
        clause = max(window.rfind(","), window.rfind(";"), window.rfind(" - "))
        if clause >= TITLE_MAX // 2:
            cut = window[:clause]
        else:
            cut = window.rsplit(" ", 1)[0]
            if len(cut) < TITLE_MAX // 2:
                cut = title[:TITLE_MAX]
        title = cut.rstrip(" ,.;:-")
    return title[:1].upper() + title[1:]


def classify_subtype(prompt_lower):
    """Determine task subtype: bug-fix, investigation, or feature."""
    if any(ind in prompt_lower for ind in BUG_FIX_INDICATORS):
        return "bug-fix"
    if any(ind in prompt_lower for ind in INVESTIGATION_INDICATORS):
        return "investigation"
    return "feature"


def detect_intent(prompt):
    """Detect task intent from a user prompt.

    Returns dict with keys: type, subtype, verb, language, confidence,
    continuation, title, title_hint. Returns None if no task intent is
    detected.
    """
    if not prompt or not prompt.strip():
        return None

    if is_meta_command(prompt):
        return None

    if len(prompt.strip()) < MIN_PROMPT_LENGTH:
        return None

    prompt_lower = prompt.lower()

    if is_question(prompt_lower):
        return None

    verb_match = find_task_verb(prompt_lower)
    if not verb_match:
        return None

    verb, lang = verb_match
    subtype = classify_subtype(prompt_lower)
    item_type = "investigation" if subtype == "investigation" else "task"

    word_count = len(prompt.split())
    if word_count < SHORT_PROMPT_WORDS:
        confidence = "low"
    elif word_count < 12:
        confidence = "medium"
    else:
        confidence = "high"

    title_hint = prompt.strip().splitlines()[0][:80]

    return {
        "type": item_type,
        "subtype": subtype,
        "verb": verb,
        "language": lang,
        "confidence": confidence,
        "continuation": is_continuation(prompt_lower),
        "title": clean_title(prompt),
        "title_hint": title_hint,
    }


# ---------------------------------------------------------------------------
# Silent tracking
#
# The hook used to ask the model to ask the user "track this?" on every
# task-like prompt. It now records the work itself and only tells the model
# what it did, so the user is never interrupted.
# ---------------------------------------------------------------------------

POINTER_FILE = "auto_track.json"
ACTIVE_WINDOW_SECONDS = 6 * 3600  # a continuation older than this starts fresh
_OPEN_STATUSES = ("created", "started", "in_progress", "paused", "blocked")


def _pointer_path(cwd):
    return os.path.join(cwd, ".coregy", POINTER_FILE)


def _load_pointer(cwd):
    try:
        with open(_pointer_path(cwd)) as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("item_id") else None
    except (OSError, ValueError):
        return None


def _save_pointer(cwd, item, now):
    with open(_pointer_path(cwd), "w") as f:
        json.dump({"item_id": item["id"], "title": item["title"],
                   "updated_at": now}, f, indent=2)
    _ignore_pointer(cwd)


def _ignore_pointer(cwd):
    """The pointer is per-machine, like tracker.db; .coregy/ itself is committed."""
    path = os.path.join(cwd, ".coregy", ".gitignore")
    try:
        with open(path) as f:
            existing = f.read()
    except OSError:
        existing = ""
    if POINTER_FILE in existing.split():
        return
    with open(path, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(POINTER_FILE + "\n")


def _tracker():
    try:
        from . import tracker
    except ImportError:
        import tracker
    return tracker


def _open_item(tracker, cwd, pointer):
    """The pointed-at item while it is still open, else None."""
    if not pointer:
        return None
    try:
        item = tracker.get_item(cwd, pointer["item_id"])
    except Exception:
        return None
    if item and item.get("status") in _OPEN_STATUSES:
        return item
    return None


def _same_title(a, b):
    norm = lambda t: " ".join(_words((t or "").lower()))
    return norm(a) == norm(b)


def track_prompt(cwd, prompt, result, now=None):
    """Record a task-like prompt in the tracker without asking anyone.

    - A continuation ("làm tiếp", "continue") of an item touched within
      ACTIVE_WINDOW_SECONDS, or a repeat of its title, adds a note to it.
    - Anything else creates a new item tagged `auto`, moved straight to
      in_progress, and makes it the active item.

    Returns {"action": "created" | "noted", "item": dict, "previous": dict|None}
    where previous is the still-open item a new one replaced as active.
    """
    tracker = _tracker()
    now = time.time() if now is None else now
    pointer = _load_pointer(cwd)
    active = _open_item(tracker, cwd, pointer)
    recent = bool(active) and now - pointer.get("updated_at", 0) <= ACTIVE_WINDOW_SECONDS
    line = (prompt or "").strip().splitlines()[0][:200] if (prompt or "").strip() else ""

    if active and recent and (result.get("continuation")
                              or _same_title(result.get("title"), active.get("title"))):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        entry = "[%s] auto-track: %s" % (stamp, line)
        notes = (active.get("notes") or "").rstrip("\n")
        item = tracker.update_item(cwd, active["id"],
                                   notes=(notes + "\n" + entry) if notes else entry)
        _save_pointer(cwd, item, now)
        return {"action": "noted", "item": item, "previous": None}

    item = tracker.create_item(
        cwd, result.get("type", "task"), result.get("title") or line,
        description=line, tags=["auto", result.get("subtype", "feature")],
        extra={"source": "auto-track", "confidence": result.get("confidence")},
    )
    try:
        item = tracker.transition_status(cwd, item["id"], "in_progress",
                                         reason="auto-track: work started")
    except ValueError:
        pass
    _save_pointer(cwd, item, now)
    return {"action": "created", "item": item, "previous": active}


def build_tracking_note(outcome, tracker_cmd):
    """One short line of context for the model. Informs; never asks the user.

    tracker_cmd is spelled out once at the end -- repeating an absolute path
    in every suggested command tripled the size of the note on each prompt.
    """
    item = outcome["item"]
    done = "concluded" if item.get("type") == "investigation" else "completed"
    if outcome["action"] == "noted":
        head = '[Coregy Auto-track] Continuing %s %s "%s" (prompt noted)' % (
            item["type"], item["id"], item["title"])
        other = ('a different task -> `tracker.py create --type task --title "<title>" '
                 '--tags auto`')
    else:
        head = '[Coregy Auto-track] Tracked as %s %s "%s" (in_progress)' % (
            item["type"], item["id"], item["title"])
        other = 'not a task -> `tracker.py update %s --status abandoned`' % item["id"]
    note = ("%s -- do not ask the user about tracking. Done -> `tracker.py update %s "
            "--status %s`; %s." % (head, item["id"], done, other))
    prev = outcome.get("previous")
    if prev:
        note += (' Previous item %s "%s" is still %s; close it too if that work is done.'
                 % (prev["id"], prev["title"], prev["status"]))
    return note + " (`tracker.py` = `%s`, add `--cwd .`)" % tracker_cmd


def main():
    parser = argparse.ArgumentParser(description="Detect task intent in prompts")
    parser.add_argument("prompt", nargs="?", help="Prompt text (default: stdin)")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    text = args.prompt if args.prompt else sys.stdin.read()
    result = detect_intent(text)

    if args.json:
        print(json.dumps(result or {}))
        return

    if result:
        print(
            f"Detected: {result['type']} ({result['subtype']}, "
            f"{result['confidence']})"
        )
        print(f"  Verb: {result['verb']} ({result['language']})")
        print(f"  Title hint: {result['title_hint']}")
    else:
        print("No task intent detected")


if __name__ == "__main__":
    main()
