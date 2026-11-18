"""Resolution of an a-w move inside the worktree: state file, rebase loop, ``--continue``, ``--abort``.

A move whose trial merge leaves conflicts replays the worktree's work onto the target's HEAD with
``git rebase`` inside the worktree (staged mode squashes it into one commit first). Each stop settles the
ruled paths by taking one side's stage; anything left stops the script with exit 2 for the session agent,
which resolves the files in the worktree and reruns with ``--continue``. ``--abort`` returns the worktree to
the HEAD it had before the attach. The target checkout never sees a conflict.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import attach_merge as merge
from attach_merge import AttachError, git, run_git, show_path, zsplit
from harness_lib.config import AutoResolve

STATE_NAME = "harness-attach.json"
REBASE_DIRS = ("rebase-merge", "rebase-apply")


class StopForResolution(Exception):
    """The rebase stopped on conflicts no rule settles; ``lines`` tell the agent what to do (exit 2)."""

    def __init__(self, lines: Sequence[str]) -> None:
        super().__init__("stopped for resolution")
        self.lines = list(lines)


@dataclass(frozen=True)
class State:
    """What a stopped attach needs to resume: target, mode, the commits it measured from, the rules."""

    target_branch: str
    target_checkout: str
    mode: str
    target_head: str
    original_head: str
    patch_base: str
    cut: str
    rules: Tuple[AutoResolve, ...]


def git_path(worktree: Path, name: str) -> Path:
    """``name`` under the worktree's own git dir."""
    return worktree / git(worktree, "rev-parse", "--git-path", name)


def state_path(worktree: Path) -> Path:
    return git_path(worktree, STATE_NAME)


def write_state(worktree: Path, state: State) -> None:
    data = {**asdict(state), "rules": [asdict(rule) for rule in state.rules]}
    state_path(worktree).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_state(worktree: Path) -> Optional[State]:
    """The stopped attach's state, or None when no attach is in progress in the worktree."""
    path = state_path(worktree)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rules = tuple(AutoResolve(rule["pattern"], rule["in_favor_of"]) for rule in data.pop("rules"))
        return State(**data, rules=rules)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise AttachError(f"the attach state file {path.as_posix()} is unreadable ({exc}); remove it to "
                          "start over") from exc


def clear_state(worktree: Path) -> None:
    state_path(worktree).unlink(missing_ok=True)


def rebasing(worktree: Path) -> bool:
    """Whether a rebase is in progress in the worktree."""
    return any(git_path(worktree, name).exists() for name in REBASE_DIRS)


def unmerged(worktree: Path) -> List[str]:
    """The worktree's conflicted paths, sorted."""
    return sorted(set(zsplit(merge.git_bytes(worktree, "diff", "--name-only", "--diff-filter=U", "-z"))))


def keep_hint(worktree: Path, exc: AttachError) -> AttachError:
    """``exc`` with a note that the attach state is kept, when a stopped attach is still in progress.

    A message that already names ``--continue`` or ``--abort`` says how to go on and is left as it is.
    """
    if "--continue" in str(exc) or "--abort" in str(exc) or not state_path(worktree).is_file():
        return exc
    return AttachError(f"{exc}; the attach state is kept: rerun with --continue once that is fixed, or "
                       "--abort", report=exc.report)


def require_clean(worktree: Path, conflicts: Sequence[str]) -> None:
    """Refuse a resolution in a worktree with uncommitted or untracked changes; nothing moved."""
    if git(worktree, "status", "--porcelain", "--untracked-files=normal"):
        names = ", ".join(map(show_path, conflicts))
        raise AttachError(f"the trial merge left conflicts no rule settles in {names}; the worktree has "
                          f"uncommitted changes, so commit them in the worktree {worktree.as_posix()} first "
                          "(commits there are allowed), then rerun; nothing moved")


def rebase(worktree: Path, *args: str) -> subprocess.CompletedProcess:
    """One ``git rebase`` step in the worktree, with no editor."""
    env = {**os.environ, "GIT_EDITOR": "true"}
    return run_git(worktree, "rebase", *args, env=env)


def stop_lines(worktree: Path, paths: Sequence[str]) -> List[str]:
    """What the agent does at a stop: the paths, where to resolve them, and the two ways on."""
    wt = show_path(worktree.as_posix())
    names = " ".join(map(show_path, paths))
    return [f"stopped for resolution: conflicts no rule settles in {', '.join(map(show_path, paths))}",
            f"resolve them in the worktree {wt}: edit each file, then git -C {wt} add -- {names}",
            f"then rerun: attach_worktree.py --continue --worktree {wt}",
            f"or drop the attach: attach_worktree.py --abort --worktree {wt} (the worktree returns to its "
            "original HEAD; the target is untouched)"]


def take_side(worktree: Path, path: str, side: str) -> None:
    """Settle one conflicted path with the side's stage (3 the replayed worktree commit, 2 the target)."""
    stage = "3" if side == "worktree" else "2"
    listing = zsplit(merge.git_bytes(worktree, "--literal-pathspecs", "ls-files", "-u", "-z", "--", path))
    stages = {field.partition("\t")[0].split(" ")[2] for field in listing if field.partition("\t")[2] == path}
    if stage in stages:
        git(worktree, "checkout-index", "-f", f"--stage={stage}", "--", path)
        git(worktree, "--literal-pathspecs", "add", "--", path)
    else:
        git(worktree, "--literal-pathspecs", "rm", "-q", "-f", "--", path)


def restore(worktree: Path, state: State) -> None:
    """Stop any rebase, put the worktree back at its original HEAD and drop the state."""
    if rebasing(worktree) and run_git(worktree, "rebase", "--abort").returncode != 0:
        git(worktree, "rebase", "--quit")
    git(worktree, "reset", "-q", "--hard", state.original_head)
    clear_state(worktree)


def settle_stop(worktree: Path, state: State) -> List[str]:
    """Apply the rules to the stop's conflicts; return the paths no rule settles.

    Rules naming both sides for a conflicted path end the attach: the worktree returns to its original HEAD.
    """
    conflicts = unmerged(worktree)
    try:
        sides: Dict[str, str] = merge.rule_sides(conflicts, state.rules)
    except AttachError as exc:
        restore(worktree, state)
        raise AttachError(f"{exc}; the attach stopped and the worktree is back at "
                          f"{state.original_head[:7]}") from exc
    for path, side in sides.items():
        take_side(worktree, path, side)
    return [path for path in conflicts if path not in sides]


def stderr_of(done: subprocess.CompletedProcess) -> str:
    return done.stderr.decode("utf-8", errors="replace").strip()


def failure(done: subprocess.CompletedProcess, action: str) -> AttachError:
    return AttachError(f"git rebase {action} failed ({stderr_of(done)}); settle it in the worktree, then "
                       "rerun with --continue, or --abort")


def run_loop(worktree: Path, state: State, done: subprocess.CompletedProcess, action: str) -> None:
    """From the rebase step ``done``, settle each stop by rule and continue; exit 2 on what is left."""
    while rebasing(worktree):
        left = settle_stop(worktree, state)
        if left:
            raise StopForResolution(stop_lines(worktree, left))
        done = rebase(worktree, "--continue")
        if done.returncode != 0 and rebasing(worktree) and not unmerged(worktree):
            raise failure(done, "--continue")
    if done.returncode != 0:
        raise failure(done, action)


def unstarted(worktree: Path, state: State, done: subprocess.CompletedProcess) -> AttachError:
    """Restore the worktree after a rebase that never started; the refusal names a resolution it drops."""
    head = git(worktree, "rev-parse", "HEAD")
    wt = show_path(worktree.as_posix())
    try:
        restore(worktree, state)
    except AttachError as exc:
        return AttachError(f"git rebase could not start in the worktree ({stderr_of(done)}), and resetting "
                           f"it to {state.original_head[:7]} failed ({exc}); the worktree is left at "
                           f"{head[:7]} and the attach state is kept: run --abort once that is fixed; "
                           "nothing moved")
    lost = ""
    if head != state.original_head:
        lost = (f"; the resolved HEAD {head} is no longer checked out: recover it with git -C {wt} reset "
                f"--hard {head}")
    return AttachError(f"git rebase could not start in the worktree ({stderr_of(done)}); the attach is "
                       f"dropped and the worktree is back at {state.original_head[:7]}{lost}; nothing moved")


def refuse_foreign_rebase(worktree: Path) -> None:
    """Refuse a plain run while a rebase someone else started is in progress in the worktree."""
    if rebasing(worktree):
        wt = show_path(worktree.as_posix())
        raise AttachError(f"a rebase is already in progress in the worktree {wt}; finish it with "
                          f"git -C {wt} rebase --continue or drop it with git -C {wt} rebase --abort first; "
                          "nothing moved")


def start(worktree: Path, state: State, *rebase_args: str) -> None:
    """Record the state, then replay the worktree's work onto the target HEAD the state names.

    A rebase that never starts (a refusing hook, say) leaves no resolution to continue: the worktree goes
    back to its original HEAD and the state goes, so the refusal says nothing moved.
    """
    write_state(worktree, state)
    done = rebase(worktree, "--merge", "--no-rebase-merges", "--no-autosquash", "--no-update-refs", "--onto",
                  state.target_head, state.patch_base, *rebase_args)
    if done.returncode != 0 and not rebasing(worktree):
        raise unstarted(worktree, state, done)
    run_loop(worktree, state, done, "--onto")


def start_staged(worktree: Path, state: State, conflicts: Sequence[str]) -> None:
    """Squash the worktree's work since ``patch_base`` into one commit and rebase it onto the target."""
    require_clean(worktree, conflicts)
    squash = git(worktree, "commit-tree", "HEAD^{tree}", "-p", state.patch_base, "-m",
                 "harness a-w: worktree work, squashed")
    start(worktree, state, squash)


def continue_rebase(worktree: Path, state: State) -> None:
    """Carry on a stopped rebase once the agent has resolved and added every conflicted path."""
    left = unmerged(worktree)
    if left:
        raise StopForResolution(stop_lines(worktree, left))
    run_loop(worktree, state, rebase(worktree, "--continue"), "--continue")


def is_ancestor(worktree: Path, older: str, newer: str) -> bool:
    return run_git(worktree, "merge-base", "--is-ancestor", older, newer).returncode == 0


def check_resolved(worktree: Path, state: State) -> None:
    """Refuse to land from a worktree HEAD that is not the finished rebase onto ``target_head``.

    A finished rebase leaves HEAD on ``target_head`` and leaves out of HEAD's history every base the attach
    measured from (``patch_base``, and the first run's ``cut``) that the target lacks. An abort or a reset
    by hand breaks one of the two; landing from there would revert target commits or carry commits the
    attach excluded, so nothing lands.
    """
    off_target = not is_ancestor(worktree, state.target_head, "HEAD")
    kept_cut = any(not is_ancestor(worktree, base, state.target_head) and is_ancestor(worktree, base, "HEAD")
                   for base in {state.patch_base, state.cut})
    if off_target or kept_cut:
        raise AttachError(f"the worktree's HEAD is not the resolution rebased onto {state.target_head[:7]} "
                          "(the rebase was aborted or HEAD was reset), so the attach cannot tell the "
                          "worktree's work from the target's; nothing moved: run --abort to return the "
                          f"worktree to {state.original_head[:7]}, then rerun the attach")


def check_moves_something(worktree: Path, target: Path, state: State, head: str, final: str) -> None:
    """Drop an attach whose resolution kept the branch's copy of every path; nothing is left to land."""
    if state.mode == "committed":
        empty = head == state.target_head
    else:
        empty = not merge.diff_paths(target, state.target_head, final)
    if empty:
        clear_state(worktree)
        raise AttachError(f"the resolution kept the branch's copy of every path, so nothing moves; the "
                          f"attach is dropped and the worktree {worktree.as_posix()} is kept at {head[:7]} "
                          f"(its HEAD before the attach was {state.original_head[:7]})")


def land_resolved(worktree: Path, target: Path, state: State) -> List[str]:
    """Race check, then land the resolved worktree HEAD: staged exactly, or by fast-forward."""
    snap = merge.snapshot(target)
    if snap.head != state.target_head:
        raise AttachError(f"branch {state.target_branch} moved during the resolution (now at "
                          f"{snap.head[:7]}, resolved onto {state.target_head[:7]}); nothing moved and the "
                          "worktree keeps its resolved commits: rerun with --continue to carry them onto the "
                          "new HEAD, or --abort")
    if git(worktree, "status", "--porcelain", "--untracked-files=normal"):
        raise AttachError(f"the worktree {worktree.as_posix()} has uncommitted changes after the resolution; "
                          "commit them there, then rerun with --continue, or --abort")
    check_resolved(worktree, state)
    head = git(worktree, "rev-parse", "HEAD")
    final = git(worktree, "rev-parse", "HEAD^{tree}")
    check_moves_something(worktree, target, state, head, final)
    if state.mode == "committed":
        return merge.land_committed(worktree, target, state.target_branch, snap)
    return merge.stage_final(target, state.target_branch, snap, final, {}, state.rules)


def saved_edits(worktree: Path, wt: str) -> Optional[str]:
    """Save the worktree's uncommitted tracked edits as a stash commit (no ref); the recovery note, if any.

    ``git stash create`` refuses an index with unmerged entries (a rebase stop), so the note then says the
    edits are dropped unsaved. Untracked files survive ``reset --hard`` and need no backup.
    """
    if not git(worktree, "status", "--porcelain", "--untracked-files=no"):
        return None
    done = run_git(worktree, "stash", "create")
    stash = done.stdout.decode("utf-8", errors="replace").strip()
    if done.returncode != 0 or not stash:
        return f"the uncommitted edits could not be saved ({stderr_of(done) or 'no stash'}) and are dropped"
    return f"the uncommitted edits are saved in {stash}: recover them with git -C {wt} stash apply {stash}"


def dropped_work(worktree: Path, state: State) -> List[str]:
    """Recovery notes for what ``--abort`` drops: a HEAD past the original one and uncommitted edits."""
    wt = show_path(worktree.as_posix())
    head = git(worktree, "rev-parse", "HEAD")
    notes: List[str] = []
    if head != state.original_head:
        notes.append(f"the worktree HEAD {head} is dropped: recover it with git -C {wt} reset --hard {head}")
    edits = saved_edits(worktree, wt)
    return notes + ([edits] if edits else [])


def abort(worktree: Path, state: State) -> List[str]:
    """Drop the attach: the worktree returns to its original HEAD; the target was never touched.

    The HEAD and uncommitted edits ``reset --hard`` discards are named first, with how to recover them.
    """
    notes = dropped_work(worktree, state)
    restore(worktree, state)
    return [f"aborted the attach to {state.target_branch}: the worktree {worktree.as_posix()} is back at "
            f"{state.original_head[:7]}; the target checkout was not touched", *notes]
