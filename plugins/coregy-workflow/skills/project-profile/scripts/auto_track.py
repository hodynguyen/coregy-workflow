"""
Detect task intent from user prompts to enable auto-tracking.

Heuristic-based classifier — looks for imperative verbs, action words,
and feature mentions. Returns intent classification or None if no task
intent is detected.

Used by the UserPromptSubmit hook to suggest tracker item creation
when the user starts a new task outside the /start-feature workflow.
"""
import argparse
import json
import sys


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
    title_hint. Returns None if no task intent is detected.
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
        "title_hint": title_hint,
    }


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
