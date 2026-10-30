"""Move a detached worktree's work onto a target branch, then remove the worktree.

Usage: attach_worktree.py [TARGET] [--target-branch BRANCH] [--worktree PATH] [--committed]

TARGET names a branch that is checked out in one of the repository's worktrees; its checkout must have no
tracked changes. ``--target-branch`` (also ``--target_branch``) names it as a flag and wins over TARGET when
both are given. The literal ``HEAD`` stands for the branch checked out in the main checkout. ``--worktree``
defaults to the current directory, which must be a linked worktree.

Default mode stages the worktree's committed, edited and new files on the target as an uncommitted change: the
combined diff from the commit the worktree was cut from (the creation entry of its HEAD reflog) is applied
three-way. The merge base with the target replaces the cut when it already contains the cut (the worktree
took in later target commits) and when the creation entry is gone (reflog expiry) or no longer behind HEAD.
Only paths the worktree changed are touched, so commits the target gained since the cut are merged and never
reverted, and history the cut commit carried that the target lacks stays behind while the creation entry
survives. ``--committed`` instead fast-forwards the target to the worktree's commits
and keeps their structure; it refuses uncommitted worktree changes, a target that moved since the cut, and,
while the creation entry survives, a target that does not contain the cut commit.

The worktree is removed once the move succeeds. Files its ignore rules match never move and are discarded with
it. A failed move leaves the worktree's files and index as they
were and says why. A three-way conflict also leaves markers and staged files in the target checkout; the error
names the command that finishes the move and the one that undoes it.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple


class AttachError(RuntimeError):
    """A precondition or git step failed; the worktree is left in place."""


class Checkout(NamedTuple):
    path: Path
    branch: Optional[str]


def run_git(repo: Path, *args: str, stdin: Optional[bytes] = None,
            env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """Run git in ``repo`` and return the completed process with bytes output."""
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, env=env)


def git_bytes(repo: Path, *args: str, env: Optional[Dict[str, str]] = None) -> bytes:
    """Raw stdout of a git command; raises ``AttachError`` on a non-zero exit."""
    done = run_git(repo, *args, env=env)
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", errors="replace").strip()
        raise AttachError(detail or f"git {' '.join(args)} failed")
    return done.stdout


def git(repo: Path, *args: str, env: Optional[Dict[str, str]] = None) -> str:
    """Stripped stdout of a git command; raises ``AttachError`` on a non-zero exit."""
    return git_bytes(repo, *args, env=env).decode("utf-8", errors="replace").strip()


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


def resolve_branch(entries: List[Checkout], name: str) -> str:
    """The branch ``name`` stands for; the literal ``HEAD`` is the main checkout's checked-out branch."""
    if name != "HEAD":
        return name
    if entries[0].branch is None:
        raise AttachError(f"HEAD of the main checkout {entries[0].path.as_posix()} is detached; name a "
                          "target branch instead")
    return entries[0].branch


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
    cut = cut_point(worktree, head)
    if cut and not is_ancestor(worktree, cut, target_head):
        raise AttachError(f"branch {branch} does not contain the commit the worktree was cut from, so a "
                          "fast-forward would carry that commit's history onto it; run without --committed "
                          "to stage only the worktree's own changes")
    base = git(worktree, "merge-base", head, target_head)
    count = int(git(worktree, "rev-list", "--count", f"{base}..{head}"))
    if count == 0:
        raise AttachError("worktree has no commits beyond the target branch")
    if base != target_head:
        raise AttachError(f"branch {branch} moved since the worktree was cut, so its commits cannot "
                          "fast-forward; run without --committed to get them staged three-way")
    git(target, "merge", "--ff-only", head)
    return [f"attached {count} commit(s) to {branch} at {head[:7]}"]


def scratch_index(worktree: Path, scratch: Path) -> Dict[str, str]:
    """A git environment whose index is a copy of the worktree's, so staging never touches the real one."""
    real = worktree / git(worktree, "rev-parse", "--git-path", "index")
    copy = scratch / "index"
    env = {**os.environ, "GIT_INDEX_FILE": str(copy)}
    if real.is_file():
        shutil.copy2(real, copy)  # the kept mtime lets git still content-check racily clean entries
    else:
        git(worktree, "read-tree", "HEAD", env=env)
    return env


def worktree_patch(worktree: Path, base: str) -> Tuple[bytes, int]:
    """The diff from ``base`` to the worktree's files, new ones included, and the changed file count.

    Staging runs against a throwaway copy of the index, so the worktree's own staged/unstaged split survives.
    """
    with tempfile.TemporaryDirectory() as scratch:
        env = scratch_index(worktree, Path(scratch))
        git(worktree, "add", "-A", env=env)
        names = git(worktree, "diff", "--cached", "--name-only", base, env=env).splitlines()
        patch = git_bytes(worktree, "diff", "--cached", "--binary", "--full-index", "-M", base, env=env)
    return patch, len(names)


def unmerged(target: Path) -> List[str]:
    listing = git(target, "diff", "--name-only", "--diff-filter=U", "-z")
    return [path for path in listing.split("\0") if path]


def conflict_message(conflicts: List[str], worktree: Path, target: Path) -> str:
    """The conflict report: what is left where, and the commands that finish or undo the move."""
    return (f"three-way merge left conflicts in {', '.join(conflicts)}; the markers and the rest of the "
            f"patch are staged in {target.as_posix()} and the worktree is kept at {worktree.as_posix()}. "
            f"To finish, resolve the markers, then run git worktree remove --force {worktree.as_posix()}. "
            f"To undo, run git -C {target.as_posix()} reset --hard (the target had no tracked changes "
            "before the move)")


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return run_git(repo, "merge-base", "--is-ancestor", older, newer).returncode == 0


def creation_entry(worktree: Path) -> Optional[str]:
    """The commit the worktree's HEAD reflog starts at, while its creation entry (old oid all zeros) lasts.

    ``git worktree add --detach`` writes that entry; once reflog expiry drops it, the oldest surviving entry
    is a later commit of the worktree's own history, never the cut, so no commit is returned.
    """
    log = worktree / git(worktree, "rev-parse", "--git-path", "logs/HEAD")
    try:
        first = log.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0].split()
    except OSError:
        return None
    if len(first) < 2 or set(first[0]) != {"0"}:
        return None
    return first[1]


def cut_point(worktree: Path, head: str) -> Optional[str]:
    """The commit the worktree was cut from: its reflog's creation entry, while still behind HEAD."""
    cut = creation_entry(worktree)
    return cut if cut and is_ancestor(worktree, cut, head) else None


def merge_base(worktree: Path, head: str, target: Path) -> Optional[str]:
    done = run_git(worktree, "merge-base", head, git(target, "rev-parse", "HEAD"))
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", errors="replace").strip() or None


def patch_base(worktree: Path, target: Path) -> str:
    """The commit the worktree's own changes are measured from.

    The cut point when the merge base with the target does not already contain it (a cut from another branch
    or from a base since squash-merged), so the patch holds only what the worktree changed. Otherwise the
    merge base, which is the newer of the two once the worktree took in target commits after the cut. Without
    a usable reflog creation entry, the merge base.
    """
    head = git(worktree, "rev-parse", "HEAD")
    cut, shared = cut_point(worktree, head), merge_base(worktree, head, target)
    if cut and (shared is None or not is_ancestor(worktree, cut, shared)):
        return cut
    if shared is None:
        raise AttachError("the worktree shares no history with the target and its HEAD reflog no longer "
                          "names the commit it was cut from")
    return shared


def move_staged(worktree: Path, target: Path, branch: str) -> List[str]:
    """Apply the worktree's changes three-way onto ``target``'s index; return the report lines."""
    patch, count = worktree_patch(worktree, patch_base(worktree, target))
    if not patch.strip():
        raise AttachError("nothing to move: the worktree has no changes since it was cut")
    done = run_git(target, "apply", "--3way", "--whitespace=nowarn", stdin=patch)
    conflicts = unmerged(target)
    if conflicts:
        raise AttachError(conflict_message(conflicts, worktree, target))
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
    branch = resolve_branch(entries, args.target)
    target = target_checkout(entries, branch, worktree)
    if tracked_changes(target):
        raise AttachError(f"target checkout {target.as_posix()} is not clean: commit or stash its tracked "
                          "changes first")
    mover = move_committed if args.committed else move_staged
    lines = mover(worktree, target, branch)
    return [*lines, remove_worktree(worktree, main)]


def parse_args(argv: Optional[list]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target_positional", nargs="?", metavar="TARGET",
                        help="target branch, or HEAD for the main checkout's branch")
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
