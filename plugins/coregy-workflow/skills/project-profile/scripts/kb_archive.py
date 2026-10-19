"""
Knowledge Base auto-archival for Coregy Workflow.

When a KB file exceeds a line threshold (default 500), moves older
sections to `.coregy/knowledge/archive/`. Sections are identified by
## headings with optional frontmatter dates for ordering.
"""
import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone


DEFAULT_THRESHOLD = 500


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_into_sections(content):
    """Split markdown content into sections by ## headings.

    Returns list of (heading, text) tuples. The first tuple may have
    heading=None for content before the first ## heading (preamble).
    A `## ` line inside a fenced code block is content, not a heading.
    """
    lines = content.splitlines(keepends=True)
    sections = []
    current_heading = None
    current_lines = []
    in_fence = False

    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        match = None if in_fence else re.match(r"^##\s+(.+)", line)
        if match:
            # Save previous section
            if current_heading is not None or current_lines:
                sections.append((current_heading, "".join(current_lines)))
            current_heading = match.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Don't forget last section
    if current_heading is not None or current_lines:
        sections.append((current_heading, "".join(current_lines)))

    return sections


def _extract_date_from_section(text):
    """Try to extract a date from section content for ordering.

    Looks for frontmatter 'created:' or '**Date**:' patterns.
    Returns date string or None.
    """
    # created:/date:/**Date**: fields, including section metadata comments
    match = re.search(r"(?:created|date|\*\*Date\*\*):\s*(\d{4}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    # a date in the heading itself, e.g. "## CI Failures (2026-09-29T...)"
    first_line = text.split("\n", 1)[0]
    match = re.search(r"(\d{4}-\d{2}-\d{2})", first_line)
    if match:
        return match.group(1)
    return None


# Organised by topic, not by time: their first sections ("System Overview",
# "Deployment", ...) are the most important, so only dated sections may be
# archived from them -- never the undated topical ones.
TOPICAL_FILES = {"architecture.md", "api-contracts.md", "business-rules.md", "runbook.md"}


def check_file_needs_archival(filepath, threshold=DEFAULT_THRESHOLD):
    """Check if a KB file exceeds the line threshold.

    Returns (needs_archival, total_lines).
    """
    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
        return len(lines) > threshold, len(lines)
    except OSError:
        return False, 0


def archive_file(filepath, archive_dir=None, threshold=DEFAULT_THRESHOLD, keep_sections=3):
    """Archive older sections from a KB file that exceeds the threshold.

    Keeps the preamble (content before first ## heading) and the most recent
    `keep_sections` sections. Moves older sections to archive/.

    Args:
        filepath: Path to the KB .md file.
        archive_dir: Archive directory. Defaults to sibling archive/ dir.
        threshold: Line count threshold to trigger archival.
        keep_sections: Number of recent sections to keep in the main file.

    Returns:
        dict with 'archived_sections', 'archive_file', 'remaining_lines'
        or None if no archival was needed.
    """
    needs_archival, total_lines = check_file_needs_archival(filepath, threshold)
    if not needs_archival:
        return None

    with open(filepath, "r") as f:
        content = f.read()

    sections = _split_into_sections(content)
    if len(sections) <= keep_sections + 1:  # +1 for preamble
        return None  # Not enough sections to archive

    # Separate preamble from content sections
    preamble = None
    content_sections = []
    for heading, text in sections:
        if heading is None:
            preamble = text
        else:
            content_sections.append((heading, text))

    if len(content_sections) <= keep_sections:
        return None

    # Choose what to archive. Dated sections go oldest-first by date. Topical
    # files never lose undated sections; other (append-only) files fall back
    # to file order for undated ones, oldest at the top.
    filename = os.path.basename(filepath)
    dated = [(i, _extract_date_from_section(text))
             for i, (_h, text) in enumerate(content_sections)]
    if filename in TOPICAL_FILES or any(d for _i, d in dated):
        candidates = sorted((d, i) for i, d in dated if d)
        archive_idx = {i for _d, i in candidates[:max(0, len(candidates) - keep_sections)]}
    else:
        archive_idx = set(range(len(content_sections) - keep_sections))
    if not archive_idx:
        return None

    sections_to_archive = [s for i, s in enumerate(content_sections) if i in archive_idx]
    sections_to_keep = [s for i, s in enumerate(content_sections) if i not in archive_idx]

    # Set up archive directory
    if archive_dir is None:
        archive_dir = os.path.join(os.path.dirname(filepath), "archive")
    os.makedirs(archive_dir, exist_ok=True)

    # Write archived sections
    name_base = os.path.splitext(filename)[0]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_filename = f"{name_base}-archive-{timestamp}.md"
    archive_path = os.path.join(archive_dir, archive_filename)

    archive_content = f"# Archived sections from {filename}\n"
    archive_content += f"# Archived at: {_now()}\n\n"
    for heading, text in sections_to_archive:
        archive_content += text
        if not text.endswith("\n"):
            archive_content += "\n"

    with open(archive_path, "w") as f:
        f.write(archive_content)

    # Rewrite main file with preamble + kept sections
    new_content = ""
    if preamble:
        new_content += preamble
        if not preamble.endswith("\n"):
            new_content += "\n"

    for heading, text in sections_to_keep:
        new_content += text
        if not text.endswith("\n"):
            new_content += "\n"

    with open(filepath, "w") as f:
        f.write(new_content)

    return {
        "archived_sections": len(sections_to_archive),
        "archive_file": archive_path,
        "remaining_lines": len(new_content.splitlines()),
    }


def check_all_kb_files(kb_dir, threshold=DEFAULT_THRESHOLD):
    """Check all KB files and archive any that exceed the threshold.

    Returns list of archive results (one per file that was archived).
    """
    results = []
    if not os.path.isdir(kb_dir):
        return results

    archive_dir = os.path.join(kb_dir, "archive")

    for fname in sorted(os.listdir(kb_dir)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(kb_dir, fname)
        if not os.path.isfile(fpath):
            continue

        result = archive_file(fpath, archive_dir=archive_dir, threshold=threshold)
        if result:
            result["source_file"] = fname
            results.append(result)

    return results


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


def _kb_md_files(kb_dir):
    """Sorted list of (filename, path) for .md files directly in kb_dir."""
    if not os.path.isdir(kb_dir):
        return []
    out = []
    for fname in sorted(os.listdir(kb_dir)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(kb_dir, fname)
        if os.path.isfile(fpath):
            out.append((fname, fpath))
    return out


def _cli_check(kb_dir, threshold):
    """Read-only sweep.

    Deliberately does NOT call check_all_kb_files(): despite its name that
    function archives (mutates) every oversized file.
    """
    results = []
    for fname, fpath in _kb_md_files(kb_dir):
        needs, lines = check_file_needs_archival(fpath, threshold)
        if needs:
            results.append({"file": fname, "lines": lines, "needs_archival": True})
    return results


def _cli_run(kb_dir, threshold, keep_sections):
    """Same loop as check_all_kb_files(), but able to pass keep_sections through."""
    results = []
    archive_dir = os.path.join(kb_dir, "archive")
    for fname, fpath in _kb_md_files(kb_dir):
        result = archive_file(fpath, archive_dir=archive_dir, threshold=threshold,
                              keep_sections=keep_sections)
        if result:
            result["source_file"] = fname
            results.append(result)
    return results


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
        description="Coregy Workflow knowledge base archival", parents=[parent]
    )
    sub = parser.add_subparsers(dest="command")

    for name, helptext in (("check", "Report oversized KB files (read-only)"),
                           ("run", "Archive older sections of oversized KB files")):
        p = sub.add_parser(name, parents=[parent], help=helptext)
        p.add_argument("--kb-dir", default=None,
                       help="KB directory (default: <cwd>/.coregy/knowledge)")
        p.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                       help="Line count threshold (default: %d)" % DEFAULT_THRESHOLD)
        p.add_argument("--json", action="store_true", dest="json_mode")
        if name == "run":
            p.add_argument("--keep-sections", type=int, default=3,
                           help="Recent sections kept in the main file (default: 3)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # getattr, not args.cwd: the shared --cwd action defaults to
    # SUPPRESS so a value given before the subcommand survives.
    cwd = os.path.abspath(getattr(args, "cwd", "."))
    kb_dir = (os.path.abspath(args.kb_dir) if args.kb_dir
              else os.path.join(cwd, ".coregy", "knowledge"))
    json_mode = getattr(args, "json_mode", False)

    try:
        if args.command == "check":
            results = _cli_check(kb_dir, args.threshold)
            if json_mode:
                _output(results)
            elif results:
                print("%d file(s) over %d lines:" % (len(results), args.threshold))
                for r in results:
                    print("  %s  %d lines" % (r["file"], r["lines"]))
            else:
                print("All KB files under threshold (%d lines)." % args.threshold)

        elif args.command == "run":
            results = _cli_run(kb_dir, args.threshold, args.keep_sections)
            if json_mode:
                _output(results)
            elif results:
                print("Archived %d file(s):" % len(results))
                for r in results:
                    print("  %s -> archive/%s (%d sections moved, %d lines remaining)"
                          % (r["source_file"],
                             os.path.basename(r["archive_file"]),
                             r["archived_sections"],
                             r["remaining_lines"]))
            else:
                print("Nothing to archive.")
    except (FileNotFoundError, ValueError, OSError) as exc:
        _fail(str(exc), json_mode)


if __name__ == "__main__":
    main()
