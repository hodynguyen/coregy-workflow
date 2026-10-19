#!/usr/bin/env python3
"""
Knowledge base sync: push/pull .hody/knowledge/ to a shared location.

Sync modes:
  - git-branch: push/pull to a dedicated branch in the same repo
  - gist: sync via GitHub Gist (requires gh CLI)
  - shared-repo: push/pull to a separate shared knowledge repo

Usage:
  kb_sync.py --cwd <project> --mode <git-branch|gist|shared-repo> --action <push|pull|status>
  kb_sync.py --cwd <project> --mode git-branch --branch hody-knowledge --action push
  kb_sync.py --cwd <project> --mode gist --gist-id <id> --action pull
  kb_sync.py --cwd <project> --mode shared-repo --repo <url> --action push

Pull overwrites local KB files with the shared copy -- there is no merge.
Commit .hody/knowledge/ before pulling if it has local changes.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile


KB_DIR = ".hody/knowledge"
KB_FILES = [
    "architecture.md",
    "decisions.md",
    "api-contracts.md",
    "business-rules.md",
    "tech-debt.md",
    "runbook.md",
]


def run_cmd(args, cwd=None, capture=True):
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            args, cwd=cwd, capture_output=capture, text=True, timeout=30
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, "", str(e)


def get_kb_path(cwd):
    return os.path.join(cwd, KB_DIR)


def validate_kb(cwd):
    """Check that .hody/knowledge/ exists and has files."""
    kb_path = get_kb_path(cwd)
    if not os.path.isdir(kb_path):
        return False, f"Knowledge base not found at {kb_path}. Run /hody-workflow:init first."
    files = [f for f in os.listdir(kb_path) if f.endswith(".md")]
    if not files:
        return False, "Knowledge base is empty."
    return True, f"Found {len(files)} knowledge base files."


# --- Git Branch Mode ---

def _kb_md_files(kb_path):
    return sorted(f for f in os.listdir(kb_path)
                  if f.endswith(".md") and os.path.isfile(os.path.join(kb_path, f)))


def git_branch_push(cwd, branch):
    """Push .hody/knowledge/ to a dedicated git branch.

    Built entirely with plumbing (hash-object / mktree / commit-tree /
    update-ref): the user's checkout, index, working tree and stash are never
    touched. The previous checkout-based version ignored checkout failures,
    so a failed switch committed the KB onto the user's own branch, and
    `git rm -rf .` on the orphan branch deleted a tracked .hody/ before the
    copy step could read it.
    """
    kb_path = get_kb_path(cwd)

    rc, _, _ = run_cmd(["git", "rev-parse", "--git-dir"], cwd=cwd)
    if rc != 0:
        return False, "Not a git repository."

    files = _kb_md_files(kb_path)
    if not files:
        return False, "No knowledge base files to push."

    tree_lines = []
    for fname in files:
        rc, sha, err = run_cmd(
            ["git", "hash-object", "-w", os.path.join(kb_path, fname)], cwd=cwd)
        if rc != 0:
            return False, f"Could not hash {fname}: {err}"
        tree_lines.append(f"100644 blob {sha}\t{fname}")

    try:
        result = subprocess.run(
            ["git", "mktree"], cwd=cwd, input="\n".join(tree_lines) + "\n",
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"mktree failed: {e}"
    if result.returncode != 0:
        return False, f"mktree failed: {result.stderr.strip()}"
    tree = result.stdout.strip()

    # Parent: the local branch, else the remote one (so pushes fast-forward).
    run_cmd(["git", "fetch", "origin", branch], cwd=cwd)
    parent = None
    for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
        rc, sha, _ = run_cmd(["git", "rev-parse", "--verify", "-q", ref + "^{commit}"], cwd=cwd)
        if rc == 0 and sha:
            parent = sha
            break

    if parent:
        rc, parent_tree, _ = run_cmd(["git", "rev-parse", parent + "^{tree}"], cwd=cwd)
        if rc == 0 and parent_tree == tree:
            rc, _, err = run_cmd(["git", "push", "origin", f"{parent}:refs/heads/{branch}"], cwd=cwd)
            if rc != 0:
                return False, f"Push failed: {err}"
            return True, f"Knowledge base already up to date on branch '{branch}'."

    cmd = ["git", "commit-tree", tree, "-m", "sync: update knowledge base"]
    if parent:
        cmd[3:3] = ["-p", parent]
    rc, commit, err = run_cmd(cmd, cwd=cwd)
    if rc != 0:
        return False, f"Commit failed: {err}"

    rc, _, err = run_cmd(["git", "update-ref", f"refs/heads/{branch}", commit], cwd=cwd)
    if rc != 0:
        return False, f"Could not update branch '{branch}': {err}"

    rc, _, err = run_cmd(["git", "push", "origin", f"refs/heads/{branch}:refs/heads/{branch}"], cwd=cwd)
    if rc != 0:
        return False, f"Push failed: {err}"

    return True, f"Knowledge base pushed to branch '{branch}' ({len(files)} files)."


def git_branch_pull(cwd, branch):
    """Pull .hody/knowledge/ from a dedicated git branch."""
    kb_path = get_kb_path(cwd)

    rc, _, err = run_cmd(["git", "fetch", "origin", branch], cwd=cwd)
    if rc != 0:
        return False, f"Fetch failed: {err}. Does branch '{branch}' exist on remote?"

    # Every .md on the branch -- push sends all KB .md files (specs, logs, ...),
    # so pull must not be limited to the six template files.
    rc, listing, err = run_cmd(["git", "ls-tree", "--name-only", f"origin/{branch}"], cwd=cwd)
    if rc != 0:
        return False, f"Could not list branch '{branch}': {err}"
    names = [n for n in listing.splitlines() if n.endswith(".md")]

    os.makedirs(kb_path, exist_ok=True)
    pulled = 0
    for fname in names:
        rc, content, _ = run_cmd(["git", "show", f"origin/{branch}:{fname}"], cwd=cwd)
        if rc == 0:
            with open(os.path.join(kb_path, fname), "w") as f:
                f.write(content + "\n")
            pulled += 1

    if pulled == 0:
        return False, f"No knowledge base files found on branch '{branch}'."
    return True, f"Pulled {pulled} files from branch '{branch}' to {KB_DIR}/."


# --- Gist Mode ---

def gist_push(cwd, gist_id=None):
    """Push .hody/knowledge/ to a GitHub Gist."""
    kb_path = get_kb_path(cwd)

    rc, _, _ = run_cmd(["gh", "auth", "status"])
    if rc != 0:
        return False, "GitHub CLI not authenticated. Run 'gh auth login' first."

    files = _kb_md_files(kb_path)
    if not files:
        return False, "No knowledge base files to push."

    if not gist_id:
        # `gh gist create` takes the files as positional arguments.
        cmd = ["gh", "gist", "create", "--desc", "Hody Workflow Knowledge Base"] + files
        rc, out, err = run_cmd(cmd, cwd=kb_path)
        if rc != 0:
            return False, f"Gist creation failed: {err}"
        return True, f"Knowledge base pushed to new gist: {out}"

    # `gh gist edit` changes one file per call: replace existing files with
    # `--filename <name> <local>`, add new ones with `--add <local>`.
    rc, existing, err = run_cmd(["gh", "gist", "view", gist_id, "--files"], cwd=kb_path)
    if rc != 0:
        return False, f"Could not read gist {gist_id}: {err}"
    existing = set(existing.split())

    for fname in files:
        if fname in existing:
            cmd = ["gh", "gist", "edit", gist_id, "--filename", fname, fname]
        else:
            cmd = ["gh", "gist", "edit", gist_id, "--add", fname]
        rc, _, err = run_cmd(cmd, cwd=kb_path)
        if rc != 0:
            return False, f"Gist update failed on {fname}: {err}"
    return True, f"Knowledge base updated in gist {gist_id} ({len(files)} files)."


def gist_pull(cwd, gist_id):
    """Pull .hody/knowledge/ from a GitHub Gist."""
    if not gist_id:
        return False, "Gist ID is required for pull. Use --gist-id <id>."

    kb_path = get_kb_path(cwd)
    os.makedirs(kb_path, exist_ok=True)

    # Clone gist to temp dir
    with tempfile.TemporaryDirectory() as tmpdir:
        target = os.path.join(tmpdir, "gist")
        rc, _, err = run_cmd(["gh", "gist", "clone", gist_id, target])
        if rc != 0:
            return False, f"Gist clone failed: {err}"

        pulled = 0
        for fname in os.listdir(target):
            if fname.endswith(".md") and not fname.startswith("."):
                shutil.copy2(os.path.join(target, fname), os.path.join(kb_path, fname))
                pulled += 1

    if pulled == 0:
        return False, "No markdown files found in gist."
    return True, f"Pulled {pulled} files from gist {gist_id} to {KB_DIR}/."


# --- Shared Repo Mode ---

def shared_repo_push(cwd, repo_url):
    """Push .hody/knowledge/ to a shared knowledge repo."""
    kb_path = get_kb_path(cwd)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Clone shared repo
        rc, _, err = run_cmd(["git", "clone", "--depth", "1", repo_url, tmpdir])
        if rc != 0:
            return False, f"Clone failed: {err}"

        # Determine project subdirectory
        project_name = os.path.basename(os.path.abspath(cwd))
        dest_dir = os.path.join(tmpdir, project_name)
        os.makedirs(dest_dir, exist_ok=True)

        # Copy KB files
        for fname in os.listdir(kb_path):
            if fname.endswith(".md"):
                shutil.copy2(os.path.join(kb_path, fname), os.path.join(dest_dir, fname))

        # Commit and push
        run_cmd(["git", "add", "."], cwd=tmpdir)
        rc, _, err = run_cmd(
            ["git", "commit", "-m", f"sync: update {project_name} knowledge base"],
            cwd=tmpdir,
        )
        if rc != 0 and "nothing to commit" not in err:
            return False, f"Commit failed: {err}"

        rc, _, err = run_cmd(["git", "push"], cwd=tmpdir)
        if rc != 0:
            return False, f"Push failed: {err}"

    return True, f"Knowledge base pushed to {repo_url} under {project_name}/."


def shared_repo_pull(cwd, repo_url):
    """Pull .hody/knowledge/ from a shared knowledge repo."""
    kb_path = get_kb_path(cwd)
    project_name = os.path.basename(os.path.abspath(cwd))

    with tempfile.TemporaryDirectory() as tmpdir:
        rc, _, err = run_cmd(["git", "clone", "--depth", "1", repo_url, tmpdir])
        if rc != 0:
            return False, f"Clone failed: {err}"

        src_dir = os.path.join(tmpdir, project_name)
        if not os.path.isdir(src_dir):
            return False, f"No directory '{project_name}' found in shared repo."

        os.makedirs(kb_path, exist_ok=True)
        pulled = 0
        for fname in os.listdir(src_dir):
            if fname.endswith(".md"):
                shutil.copy2(os.path.join(src_dir, fname), os.path.join(kb_path, fname))
                pulled += 1

    if pulled == 0:
        return False, f"No knowledge base files found for '{project_name}' in shared repo."
    return True, f"Pulled {pulled} files from shared repo to {KB_DIR}/."


# --- Status ---

def sync_status(cwd):
    """Show sync status of the knowledge base."""
    kb_path = get_kb_path(cwd)
    if not os.path.isdir(kb_path):
        return "Knowledge base not found. Run /hody-workflow:init first."

    lines = ["Knowledge base files:"]
    for fname in KB_FILES:
        fpath = os.path.join(kb_path, fname)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            lines.append(f"  {fname}: {size} bytes")
        else:
            lines.append(f"  {fname}: missing")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Sync .hody/knowledge/ to shared location")
    parser.add_argument("--cwd", default=".", help="Project root directory")
    parser.add_argument("--mode", choices=["git-branch", "gist", "shared-repo"],
                        required=True, help="Sync mode")
    parser.add_argument("--action", choices=["push", "pull", "status"],
                        required=True, help="Action to perform")
    parser.add_argument("--branch", default="hody-knowledge",
                        help="Branch name for git-branch mode")
    parser.add_argument("--gist-id", default=None,
                        help="Gist ID for gist mode")
    parser.add_argument("--repo", default=None,
                        help="Repo URL for shared-repo mode")
    args = parser.parse_args()

    cwd = os.path.abspath(args.cwd)

    if args.action == "status":
        print(sync_status(cwd))
        sys.exit(0)

    # Validate KB exists for push
    if args.action == "push":
        valid, msg = validate_kb(cwd)
        if not valid:
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)

    # Dispatch
    if args.mode == "git-branch":
        if args.action == "push":
            ok, msg = git_branch_push(cwd, args.branch)
        else:
            ok, msg = git_branch_pull(cwd, args.branch)

    elif args.mode == "gist":
        if args.action == "push":
            ok, msg = gist_push(cwd, args.gist_id)
        else:
            ok, msg = gist_pull(cwd, args.gist_id)

    elif args.mode == "shared-repo":
        if not args.repo:
            print("Error: --repo is required for shared-repo mode", file=sys.stderr)
            sys.exit(1)
        if args.action == "push":
            ok, msg = shared_repo_push(cwd, args.repo)
        else:
            ok, msg = shared_repo_pull(cwd, args.repo)

    print(msg)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
