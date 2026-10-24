"""Move a detached worktree's work onto a target branch, then remove the worktree.

Usage: attach_worktree.py TARGET [--worktree PATH] [--committed]

TARGET names a branch that is checked out in one of the repository's worktrees; its checkout must have no
tracked changes. ``--worktree`` defaults to the current directory, which must be a linked worktree.

Default mode stages the worktree's committed, edited and new files on the target as an uncommitted change: the
combined diff from the merge base is applied three-way, so commits the target gained since the worktree was
cut are merged and never reverted. ``--committed`` instead fast-forwards the target to the worktree's commits
and keeps their structure; it refuses uncommitted worktree changes and a target that moved since the cut.

The worktree is removed once the move succeeds. A failed move leaves the worktree and says why.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple


class AttachError(RuntimeError):
    """A precondition or git step failed; the worktree is left in place."""


class Checkout(NamedTuple):
    path: Path
    branch: Optional[str]


def run_git(repo: Path, *args: str, stdin: Optional[bytes] = None) -> subprocess.CompletedProcess:
    """Run git in ``repo`` and return the completed process with bytes output."""
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True)


def git(repo: Path, *args: str) -> str:
    """Stripped stdout of a git command; raises ``AttachError`` on a non-zero exit."""
    done = run_git(repo, *args)
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", errors="replace").strip()
        raise AttachError(detail or f"git {' '.join(args)} failed")
    return done.stdout.decode("utf-8", errors="replace").strip()


def checkouts(repo: Path) -> List[Checkout]:
    """Every worktree of the repository, the main checkout first, with its checked-out branch."""
    found: List[Checkout] = []
    for block in git(repo, "worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        if "worktree" not in fields:
            continue
        branch = fields.get("branch", "").removeprefix("refs/heads/") or None
        found.append(Checkout(Path(fields["worktree"]).resolve(), branch))
    return found


def worktree_path(arg: Optional[Path]) -> Path:
    """The worktree's top level: ``--worktree``, else the current directory."""
    return Path(git(arg or Path.cwd(), "rev-parse", "--show-toplevel")).resolve()


def target_checkout(entries: List[Checkout], branch: str, worktree: Path) -> Path:
    """The checkout that has ``branch`` checked out; never the worktree being attached."""
    for entry in entries:
        if entry.branch == branch:
            if entry.path == worktree:
                raise AttachError(f"branch {branch} is checked out in the worktree itself")
            return entry.path
    raise AttachError(f"branch {branch} is not checked out in any worktree; check it out in the main "
                      "checkout first")


def tracked_changes(repo: Path) -> bool:
    return bool(git(repo, "status", "--porcelain", "--untracked-files=no"))


def move_committed(worktree: Path, target: Path, branch: str) -> List[str]:
    """Fast-forward ``target`` to the worktree's commits; return the report lines."""
    if git(worktree, "status", "--porcelain"):
        raise AttachError("worktree has uncommitted changes; commit them or drop --committed")
    head = git(worktree, "rev-parse", "HEAD")
    target_head = git(target, "rev-parse", "HEAD")
    base = git(worktree, "merge-base", head, target_head)
    count = int(git(worktree, "rev-list", "--count", f"{base}..{head}"))
    if count == 0:
        raise AttachError("worktree has no commits beyond the target branch")
    if base != target_head:
        raise AttachError(f"branch {branch} moved since the worktree was cut, so its commits cannot "
                          "fast-forward; run without --committed to get them staged three-way")
    git(target, "merge", "--ff-only", head)
    return [f"attached {count} commit(s) to {branch} at {head[:7]}"]


def worktree_patch(worktree: Path, base: str) -> Tuple[bytes, int]:
    """The diff from ``base`` to the worktree's files, new ones included, and the changed file count."""
    git(worktree, "add", "-A")
    try:
        names = git(worktree, "diff", "--cached", "--name-only", base).splitlines()
        patch = run_git(worktree, "diff", "--cached", "--binary", "--full-index", "-M", base).stdout
    finally:
        git(worktree, "reset", "-q")
    return patch, len(names)


def unmerged(target: Path) -> List[str]:
    listing = git(target, "diff", "--name-only", "--diff-filter=U", "-z")
    return [path for path in listing.split("\0") if path]


def move_staged(worktree: Path, target: Path, branch: str) -> List[str]:
    """Apply the worktree's changes three-way onto ``target``'s index; return the report lines."""
    base = git(worktree, "merge-base", git(worktree, "rev-parse", "HEAD"), git(target, "rev-parse", "HEAD"))
    patch, count = worktree_patch(worktree, base)
    if not patch.strip():
        raise AttachError("nothing to move: the worktree matches the target branch")
    done = run_git(target, "apply", "--3way", "--whitespace=nowarn", stdin=patch)
    conflicts = unmerged(target)
    if conflicts:
        raise AttachError(f"three-way merge left conflicts in {', '.join(conflicts)}; the worktree is kept "
                          f"at {worktree.as_posix()}")
    if done.returncode != 0:
        raise AttachError("git apply failed: " + done.stderr.decode("utf-8", errors="replace").strip())
    return [f"staged {count} file(s) on {branch}, nothing committed", "next: git diff --cached"]


def remove_worktree(worktree: Path, main: Path) -> str:
    """Remove the worktree; the process leaves it first, since a held directory blocks removal on Windows."""
    os.chdir(main)
    done = run_git(main, "worktree", "remove", "--force", str(worktree))
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", errors="replace").strip()
        raise AttachError(f"the move succeeded but removing the worktree failed ({detail}); remove it with "
                          f"git worktree remove --force {worktree.as_posix()}")
    return f"removed worktree {worktree.as_posix()}"


def attach(args: argparse.Namespace) -> List[str]:
    """Move the worktree's work onto the target branch, remove the worktree, return the report lines."""
    worktree = worktree_path(args.worktree)
    entries = checkouts(worktree)
    main = entries[0].path
    if worktree == main:
        raise AttachError(f"{worktree.as_posix()} is the main checkout, not a linked worktree")
    target = target_checkout(entries, args.target, worktree)
    if tracked_changes(target):
        raise AttachError(f"target checkout {target.as_posix()} is not clean: commit or stash its tracked "
                          "changes first")
    mover = move_committed if args.committed else move_staged
    lines = mover(worktree, target, args.target)
    return [*lines, remove_worktree(worktree, main)]


def parse_args(argv: Optional[list]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target_positional", nargs="?", metavar="TARGET", help="target branch")
    parser.add_argument("--target-branch", "--target_branch", dest="target_flag", metavar="BRANCH",
                        help="target branch, as a flag")
    parser.add_argument("--worktree", type=Path, help="worktree to attach (default: the current directory)")
    parser.add_argument("--committed", action="store_true",
                        help="fast-forward the target to the worktree's commits instead of staging")
    args = parser.parse_args(argv)
    args.target = args.target_flag or args.target_positional
    if not args.target:
        parser.error("a target branch is required, as TARGET or --target-branch")
    return args


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    try:
        lines = attach(args)
    except AttachError as exc:
        print(f"attach_worktree: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
