"""Staged a-w move onto a target checkout that may hold dirty edits.

Snapshot of the target, the worktree's state as a loose commit, the overlap check, the in-memory trial
merge (``git merge-tree --write-tree``), the auto-resolve rules, the backup (``git stash create``) and the
exact land (``git apply --index``). Nothing here touches the target before the land, and the land changes
the target only after the race check and the backup.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from harness_lib.config import AutoResolve

SIDES = ("worktree", "branch")


class AttachError(RuntimeError):
    """A precondition or git step failed; ``report`` holds lines to print before the error, if any."""

    def __init__(self, message: str, report: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.report = list(report)


class Snapshot(NamedTuple):
    head: str
    dirty: FrozenSet[str]


class Change(NamedTuple):
    commit: str
    paths: Dict[str, str]


class Trial(NamedTuple):
    tree: str
    conflicts: List[str]


class Outcome(NamedTuple):
    names: List[str]
    added: List[str]
    kept: List[str]
    overwritten: List[str]
    removed: List[str]


def run_git(repo: Path, *args: str, stdin: Optional[bytes] = None,
            env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """Run git in ``repo`` and return the completed process with bytes output."""
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, env=env)


def git_bytes(repo: Path, *args: str, env: Optional[Dict[str, str]] = None,
              stdin: Optional[bytes] = None) -> bytes:
    """Raw stdout of a git command; raises ``AttachError`` on a non-zero exit."""
    done = run_git(repo, *args, env=env, stdin=stdin)
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", errors="replace").strip()
        raise AttachError(detail or f"git {' '.join(args)} failed")
    return done.stdout


def git(repo: Path, *args: str, env: Optional[Dict[str, str]] = None) -> str:
    """Stripped stdout of a git command; raises ``AttachError`` on a non-zero exit."""
    return git_bytes(repo, *args, env=env).decode("utf-8", errors="replace").strip()


def zsplit(raw: bytes) -> List[str]:
    """The NUL-separated fields of ``-z`` output, decoded, empty fields dropped."""
    return [field for field in raw.decode("utf-8", errors="replace").split("\0") if field]


def show_path(path: str) -> str:
    """``path`` for a report line: quoted only when it holds whitespace."""
    return f'"{path}"' if re.search(r"\s", path) else path


def rule_side(path: str, rules: Sequence[AutoResolve]) -> Optional[str]:
    """The side the rules give ``path``; refuses when two rules name different sides."""
    sides = {rule.in_favor_of for rule in rules if fnmatchcase(path, rule.pattern)}
    if len(sides) > 1:
        raise AttachError(f"auto-resolve rules are ambiguous for {path}: they name both the worktree and the "
                          "branch; drop or narrow one rule")
    return next(iter(sides), None)


def rule_sides(paths: Iterable[str], rules: Sequence[AutoResolve]) -> Dict[str, str]:
    """Every path a rule governs, mapped to its side."""
    found = {path: rule_side(path, rules) for path in paths}
    return {path: side for path, side in found.items() if side is not None}


def snapshot(target: Path) -> Snapshot:
    """The target's HEAD and every dirty tracked path, staged or unstaged, both sides of a rename."""
    head = git(target, "rev-parse", "HEAD")
    fields = zsplit(git_bytes(target, "status", "--porcelain=v1", "-z", "--untracked-files=no"))
    dirty, index = set(), 0
    while index < len(fields):
        entry = fields[index]
        dirty.add(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            index += 1
            dirty.add(fields[index])
        index += 1
    return Snapshot(head, frozenset(dirty))


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


def worktree_change(worktree: Path, base: str) -> Change:
    """A loose commit of the worktree's files on its HEAD, and each path it changed since ``base``.

    Staging runs against a throwaway copy of the index and no ref moves, so the worktree's index, its
    staged/unstaged split and its HEAD survive.
    """
    with tempfile.TemporaryDirectory() as scratch:
        env = scratch_index(worktree, Path(scratch))
        git(worktree, "add", "-A", env=env)
        tree = git(worktree, "write-tree", env=env)
    commit = git(worktree, "commit-tree", tree, "-p", "HEAD", "-m", "harness a-w: worktree state")
    return Change(commit, diff_paths(worktree, base, commit))


def diff_paths(repo: Path, old: str, new: str, spec: Sequence[str] = ()) -> Dict[str, str]:
    """Each path that differs between two tree-ish revisions, mapped to its status letter.

    ``diff-tree`` is plumbing, so porcelain diff settings (renames, relative, prefixes) never apply.
    """
    listing = git_bytes(repo, "diff-tree", "-r", "--no-renames", "--name-status", "-z", old, new, *spec)
    fields = zsplit(listing)
    return dict(zip(fields[1::2], fields[0::2]))


def blocked_parent(target: Path, path: str, deleted: FrozenSet[str]) -> Optional[str]:
    """The first ancestor of ``path`` that exists in the target as something other than a directory.

    An ancestor the land deletes does not count: ``git apply`` removes it before it writes ``path``.
    """
    parts = path.split("/")[:-1]
    for depth in range(1, len(parts) + 1):
        parent = "/".join(parts[:depth])
        full = target / parent
        if parent not in deleted and os.path.lexists(full) and (full.is_symlink() or not full.is_dir()):
            return parent
    return None


def folder_clears(target: Path, path: str, deleted: FrozenSet[str]) -> bool:
    """Whether ``path`` is a real folder in the target holding only tracked files the land deletes."""
    folder = target / path
    if folder.is_symlink() or not folder.is_dir():
        return False
    for root, _, files in os.walk(folder):
        for name in files:
            if (Path(root) / name).relative_to(target).as_posix() not in deleted:
                return False
    return True


def untracked_on(target: Path, touched: Dict[str, str], written: Dict[str, str],
                 governed: FrozenSet[str]) -> List[str]:
    """Files in the way of the move: untracked on a written path, or any file on a written path's parent.

    A folder on a written path is no obstacle when the land deletes every file in it. A governed path is
    never counted as deleted: the land skips it.
    """
    deleted = frozenset(path for path, status in written.items() if status == "D") - governed
    tracked = set(zsplit(git_bytes(target, "ls-files", "-z")))
    found = set()
    for path, status in touched.items():
        if status == "D":
            continue
        in_way = os.path.lexists(target / path) and path not in tracked
        if in_way and not folder_clears(target, path, deleted):
            found.add(path)
        parent = blocked_parent(target, path, deleted)
        if parent is not None:
            found.add(parent)
    return sorted(found)


def check_overlap(target: Path, touched: Dict[str, str], written: Dict[str, str], dirty: FrozenSet[str],
                  sides: Dict[str, str]) -> None:
    """Refuse a touched path dirty in the target that no rule governs, and an untracked file in the way.

    ``touched`` joins the worktree's changed paths with the paths the land writes (``written``), so a
    target-side rename that carries a worktree edit onto a dirty path is caught too.
    """
    overlap = sorted(path for path in touched if path in dirty and path not in sides)
    if overlap:
        raise AttachError("the target checkout has uncommitted edits on paths the move writes: "
                          f"{', '.join(map(show_path, overlap))}; commit or stash them in the target, or add "
                          "an --auto-resolve rule for them")
    governed = frozenset(path for path in sides if path in dirty)
    blocked = untracked_on(target, touched, written, governed)
    if blocked:
        names = ", ".join(map(show_path, blocked))
        raise AttachError("untracked file(s), or files where the move needs a folder, sit in the target on "
                          f"paths the move writes: {names}; move them aside first")


def trial_merge(worktree: Path, base: str, target_head: str, commit: str) -> Trial:
    """Merge ``commit`` into ``target_head`` in memory; the result tree and the conflicted paths."""
    done = run_git(worktree, "merge-tree", "--write-tree", "--name-only", "-z", "--no-messages",
                   f"--merge-base={base}", target_head, commit)
    if done.returncode not in (0, 1):
        detail = done.stderr.decode("utf-8", errors="replace").strip()
        raise AttachError(f"the trial merge failed (git merge-tree exited {done.returncode}): {detail}")
    fields = zsplit(done.stdout)
    return Trial(fields[0], sorted(set(fields[1:])) if done.returncode == 1 else [])


def ls_entry(repo: Path, rev: str, path: str) -> Optional[Tuple[str, str, str]]:
    """The mode, object type and object id of ``path`` in ``rev``; None when ``rev`` lacks it."""
    listing = git_bytes(repo, "--literal-pathspecs", "ls-tree", "-z", "--full-tree", rev, "--", path)
    for field in zsplit(listing):
        meta, _, name = field.partition("\t")
        if name == path:
            mode, kind, oid = meta.split(" ")
            return mode, kind, oid
    return None


def tree_entry(repo: Path, rev: str, path: str) -> Optional[Tuple[str, str]]:
    """The mode and object id of the file (or gitlink) ``path`` in ``rev``; None when absent or a folder."""
    entry = ls_entry(repo, rev, path)
    if entry is None or entry[1] == "tree":
        return None
    return entry[0], entry[2]


def is_folder(repo: Path, rev: str, path: str) -> bool:
    entry = ls_entry(repo, rev, path)
    return entry is not None and entry[1] == "tree"


def check_governed(target: Path, final: str, written: Dict[str, str], governed: Sequence[str]) -> None:
    """Refuse a rule-governed dirty file the move turns into a folder: a rule settles whole files only."""
    folders = [path for path in governed
               if is_folder(target, final, path) or any(name.startswith(path + "/") for name in written)]
    if folders:
        names = ", ".join(map(show_path, folders))
        raise AttachError(f"the move turns the dirty path(s) {names} into a folder; a rule settles whole "
                          "files only, so commit or stash them in the target first")


def settle(worktree: Path, trial: Trial, picks: Dict[str, str]) -> str:
    """The trial tree with each path in ``picks`` set to that revision's copy (or removed); its tree id."""
    folders = [path for path, rev in picks.items() if is_folder(worktree, rev, path)]
    if folders:
        raise AttachError(f"a rule picks a folder for {', '.join(map(show_path, folders))}; a rule settles "
                          "whole files only, so settle the conflict by hand")
    with tempfile.TemporaryDirectory() as scratch:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git(worktree, "read-tree", trial.tree, env=env)
        for path, rev in picks.items():
            entry = tree_entry(worktree, rev, path)
            if entry is None:
                git(worktree, "update-index", "--force-remove", "--", path, env=env)
            else:
                cacheinfo = f"{entry[0]},{entry[1]},{path}"
                git(worktree, "update-index", "--add", "--cacheinfo", cacheinfo, env=env)
        return git(worktree, "write-tree", env=env)


def final_tree(worktree: Path, base: str, target_head: str, change: Change,
               rules: Sequence[AutoResolve]) -> Trial:
    """The trial result with every ruled conflict settled; ``conflicts`` holds the paths no rule settles."""
    trial = trial_merge(worktree, base, target_head, change.commit)
    sides = rule_sides(trial.conflicts, rules)
    unruled = [path for path in trial.conflicts if path not in sides]
    if unruled:
        return Trial(trial.tree, unruled)
    picks = {path: change.commit if side == "worktree" else target_head for path, side in sides.items()}
    return Trial(settle(worktree, trial, picks) if picks else trial.tree, [])


def land_patch(target: Path, head: str, final: str, governed: Sequence[str]) -> Tuple[bytes, Dict[str, str]]:
    """The exact diff from ``head`` to ``final`` minus the ``governed`` paths, and the paths it writes.

    ``diff-tree`` ignores porcelain diff settings, and the prefixes are pinned for ``git apply``'s ``-p1``.
    """
    spec = ["--", *(f":(exclude,literal){path}" for path in governed)] if governed else []
    names = diff_paths(target, head, final, spec)
    patch = git_bytes(target, "diff-tree", "-r", "-p", "--binary", "--full-index", "--no-renames",
                      "--src-prefix=a/", "--dst-prefix=b/", head, final, *spec)
    return patch, names


def race_check(target: Path, snap: Snapshot) -> None:
    """Refuse when the target's HEAD or its dirty path set changed since the snapshot."""
    if snapshot(target) != snap:
        raise AttachError("the target checkout changed during the attach (its HEAD or its dirty paths); "
                          "nothing moved, rerun the attach")


def backup(target: Path) -> Optional[str]:
    """A ``git stash create`` commit of the target's dirty state; None for a clean target."""
    return git(target, "stash", "create") or None


def overwrite(target: Path, final: str, path: str) -> None:
    """Write and stage the final tree's copy of ``path`` in the target; remove it when the tree lacks it."""
    entry = tree_entry(target, final, path)
    if entry is None:
        git(target, "update-index", "--force-remove", "--", path)
        if os.path.lexists(target / path):
            (target / path).unlink()
        return
    git(target, "update-index", "--add", "--cacheinfo", f"{entry[0]},{entry[1]},{path}")
    git(target, "checkout-index", "-f", "-q", "--", path)


def outcome(target: Path, snap: Snapshot, final: str, sides: Dict[str, str]) -> Tuple[bytes, Outcome]:
    """The land's patch and what it does to each path: staged clean paths and ruled dirty paths."""
    governed = sorted(path for path in sides if path in snap.dirty)
    overwritten = [path for path in governed if sides[path] == "worktree"]
    removed = [path for path in overwritten if tree_entry(target, final, path) is None]
    kept = [path for path in governed if sides[path] == "branch"]
    patch, names = land_patch(target, snap.head, final, governed)
    added = sorted(path for path, status in names.items() if status == "A")
    return patch, Outcome(sorted(names), added, kept, overwritten, removed)


def write_land(target: Path, patch: bytes, final: str, overwritten: Sequence[str]) -> None:
    """Apply the patch to the target's index and files, then write each worktree-ruled dirty path."""
    if patch.strip():
        done = run_git(target, "apply", "--index", "--whitespace=nowarn", stdin=patch)
        if done.returncode != 0:
            detail = done.stderr.decode("utf-8", errors="replace").strip()
            raise AttachError(f"git apply --index failed: {detail}")
    for path in overwritten:
        overwrite(target, final, path)


def land(target: Path, branch: str, snap: Snapshot, final: str, sides: Dict[str, str]) -> List[str]:
    """Race check, backup, exact apply, then the worktree-ruled dirty paths; return the report lines.

    Any failure after the backup carries the backup and undo lines, since the target may hold part of the
    move by then.
    """
    patch, result = outcome(target, snap, final, sides)
    if not result.names and not result.overwritten:
        raise AttachError("nothing to move: every path the worktree changed is kept as the branch has it")
    race_check(target, snap)
    stash = backup(target)
    try:
        write_land(target, patch, final, result.overwritten)
    except (AttachError, OSError) as exc:
        recovery = [backup_line(stash), *undo_lines(target, result, stash, partial=True)]
        message = (f"the land failed after the backup, so the target may hold part of the move ({exc}); "
                   "the backup and undo lines on stdout restore it")
        raise AttachError(message, report=recovery) from exc
    return report(target, branch, result, stash)


def ruled_lines(result: Outcome) -> List[str]:
    """One report line per rule-governed dirty path: kept, overwritten or removed."""
    lines = [f"kept the target's dirty copy of {show_path(path)}; the worktree's change to it was dropped"
             for path in result.kept]
    for path in result.overwritten:
        shown = show_path(path)
        lines.append(f"removed dirty path {shown}, which the worktree deletes" if path in result.removed
                     else f"overwrote dirty path {shown} with the worktree's copy")
    return lines


def backup_line(stash: Optional[str]) -> str:
    if stash:
        return f"backup: {stash} (git stash create of the target's dirty state before the move)"
    return "backup: none, the target checkout was clean"


def undo_lines(target: Path, result: Outcome, stash: Optional[str], partial: bool) -> List[str]:
    """Literal path-scoped undo commands for a landed move, or, ``partial``, for one that failed midway.

    After a failure an added path may sit untracked on disk with the index never written, and
    ``git restore`` aborts on a path neither HEAD nor the index holds; added paths therefore get their own
    unstage and clean lines, which work in either state.
    """
    git_c = f"undo: git --literal-pathspecs -C {show_path(target.as_posix())}"
    restored = [path for path in result.names if not partial or path not in result.added]
    lines = []
    if restored:
        shown = " ".join(map(show_path, restored))
        lines.append(f"{git_c} restore --source=HEAD --staged --worktree -- {shown}")
    if partial and result.added:
        added = " ".join(map(show_path, result.added))
        lines += [f"{git_c} rm -q --cached --ignore-unmatch -- {added}", f"{git_c} clean -q -f -x -- {added}"]
    for path in result.overwritten:
        lines.append(f"{git_c} restore --source={stash}^2 --staged -- {show_path(path)}")
        lines.append(f"{git_c} restore --source={stash} --worktree -- {show_path(path)}")
    return lines


def report(target: Path, branch: str, result: Outcome, stash: Optional[str]) -> List[str]:
    """The staged-move report: count, backup, ruled dirty paths, literal path-scoped undo, next step."""
    count = len(result.names) + len(result.overwritten)
    return [f"staged {count} file(s) on {branch}, nothing committed", backup_line(stash),
            *ruled_lines(result), *undo_lines(target, result, stash, partial=False),
            "next: git diff --cached"]
