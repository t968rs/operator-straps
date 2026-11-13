"""Move a detached worktree's work onto a target branch, then remove the worktree.

Usage: attach_worktree.py [TARGET] [--target-branch BRANCH] [--worktree PATH] [--committed]
                          [--auto-resolve PATTERN=SIDE ...] [--continue | --abort]

Exit codes: 0 moved (or aborted), 1 refused, 2 stopped for resolution in the worktree.

TARGET names a branch that is checked out in one of the repository's worktrees. ``--target-branch`` (also
``--target_branch``) names it as a flag and wins over TARGET when both are given. The literal ``HEAD`` stands
for the branch checked out in the main checkout. ``--worktree`` defaults to the current directory, which must
be a linked worktree.

The target checkout may hold uncommitted edits: a path the move writes must not be dirty there unless an
auto-resolve rule governs it (staged mode only; ``--committed`` refuses every dirty path it writes). A
``branch`` rule keeps the dirty copy, a ``worktree`` rule overwrites it after a ``git stash create`` backup.
Rules come from ``attach.auto_resolve`` in the project's ``.claude/harness.json``, then each
``--auto-resolve PATTERN=SIDE`` (SIDE ``worktree`` or ``branch``); two rules naming different sides for one
path refuse as ambiguous.

Default mode stages the worktree's committed, edited and new files on the target as an uncommitted change,
measured from the commit the worktree was cut from (or the merge base with the target once that contains
the cut). An in-memory trial merge (``git merge-tree``) runs first; ruled conflicts take their side's whole
file, and the exact result lands with ``git apply --index`` after a race check and the backup.
``--committed`` instead fast-forwards the target to the worktree's commits, rebasing them onto the target's
HEAD inside the worktree when the target moved or lacks the cut; it refuses uncommitted worktree changes.

Conflicts no rule settles are resolved in the worktree, never in the target, which receives no conflict at
all. With a clean worktree the script rebases its work onto the target (staged mode squashes it into one
commit first), settles ruled paths at each stop, and exits 2 naming the paths left. The agent edits and
``git add``s them in the worktree, then reruns with ``--continue``; ``--abort`` returns the worktree to its
original HEAD. Both read the state file (``harness-attach.json`` in the worktree's git dir) and take no
target or mode that differs from it; a plain run while it exists refuses. The land carries whatever the
worktree's HEAD holds over the target HEAD the resolution rebased onto: an agent that rebases or merges by
hand during a stop owns what that brings in.

The worktree is removed once the move succeeds. Files its ignore rules match never move and are discarded
with it. A refusal changes nothing in the target and says why; a successful move prints the backup and an
undo that matches the mode (path-scoped for a staged move, ``reset --keep`` for ``--committed``).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, NamedTuple, NoReturn, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

import attach_merge as merge  # noqa: E402
import attach_resolve as resolve  # noqa: E402
from attach_merge import SIDES, AttachError, git, run_git  # noqa: E402
from attach_resolve import State, StopForResolution  # noqa: E402
from harness_lib.config import (  # noqa: E402
    CONFIG_REL, AutoResolve, ConfigError, activate, active, load_config)
from harness_lib.project import main_worktree, project_root  # noqa: E402

MIN_GIT = (2, 40)


class Checkout(NamedTuple):
    path: Path
    branch: Optional[str]


def check_git_version(version_output: str) -> None:
    """Refuse a git older than 2.40, which lacks ``merge-tree --write-tree --merge-base``."""
    found = re.search(r"(\d+)\.(\d+)", version_output)
    if found is None or (int(found.group(1)), int(found.group(2))) < MIN_GIT:
        shown = version_output.strip() or "no version reported"
        raise AttachError(f"a-w needs git 2.40 or later for git merge-tree --write-tree --merge-base; "
                          f"found {shown}")


def git_version() -> str:
    """The output of ``git --version``."""
    done = subprocess.run(["git", "--version"], capture_output=True)
    return done.stdout.decode("utf-8", errors="replace")


def config_root(target: Path) -> Path:
    """The checkout whose ``.claude/harness.json`` supplies the rules: the target's, else the main one."""
    root = project_root(target)
    return root if (root / CONFIG_REL).is_file() else main_worktree(target)


def load_rules(target: Path, flags: Sequence[AutoResolve]) -> Tuple[AutoResolve, ...]:
    """The project's ``attach.auto_resolve`` rules, then the ``--auto-resolve`` flags."""
    try:
        activate(load_config(config_root(target)))
    except ConfigError as exc:
        raise AttachError(f"harness config: {exc}") from exc
    return (*active().attach.auto_resolve, *flags)


def parse_rule(value: str) -> AutoResolve:
    """One ``--auto-resolve PATTERN=SIDE`` value; argparse turns a bad one into a usage error."""
    pattern, sep, side = value.rpartition("=")
    if not sep or not pattern or side not in SIDES:
        raise argparse.ArgumentTypeError(f"expected PATTERN=SIDE with SIDE worktree or branch, got {value!r}")
    return AutoResolve(pattern, side)


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


def check_linear(worktree: Path, base: str, head: str) -> None:
    """Refuse to rebase commits that include a merge: flattening it would drop merge-only changes."""
    merges = git(worktree, "rev-list", "--merges", f"{base}..{head}").split()
    if merges:
        raise AttachError(f"the worktree's commits since {base[:7]} include merge commit(s) "
                          f"{', '.join(sha[:7] for sha in merges)}, and --committed would have to rebase "
                          "them onto the moved target, flattening the merge; run without --committed to "
                          "stage the work instead; nothing moved")


def new_state(worktree: Path, target: Path, branch: str, mode: str, target_head: str, base: str,
              rules: Sequence[AutoResolve], prior: Optional[State]) -> State:
    """The state of a resolution about to start; a restart keeps the prior original HEAD and cut."""
    original = prior.original_head if prior else git(worktree, "rev-parse", "HEAD")
    return State(target_branch=branch, target_checkout=target.as_posix(), mode=mode, target_head=target_head,
                 original_head=original, patch_base=base, cut=prior.cut if prior else base,
                 rules=tuple(rules))


def no_commits(base: str, prior: Optional[State]) -> AttachError:
    """The refusal for a committed move with nothing to land; a restart names only ``--abort``."""
    if prior:
        return AttachError(f"nothing to move: the worktree's HEAD holds no commits beyond {base[:7]}, the "
                           "target HEAD the resolution rebased onto; run --abort to drop the attach")
    return AttachError("worktree has no commits beyond the target branch")


def move_committed(worktree: Path, target: Path, branch: str, rules: Sequence[AutoResolve],
                   prior: Optional[State] = None) -> List[str]:
    """Fast-forward ``target`` to the worktree's commits, rebased onto it first when needed; report lines.

    ``prior`` is the state a ``--continue`` restart resumes: its work is measured from the target HEAD the
    finished rebase went onto, and its original HEAD and cut carry over.
    """
    if git(worktree, "status", "--porcelain", "--untracked-files=normal"):
        raise AttachError("worktree has uncommitted changes; commit them or drop --committed")
    head = git(worktree, "rev-parse", "HEAD")
    snap = merge.snapshot(target)
    base = prior.target_head if prior else patch_base(worktree, target)
    if git(worktree, "rev-list", "--count", f"{base}..{head}") == "0":
        raise no_commits(base, prior)
    changed = merge.diff_paths(worktree, base, head)
    merge.rule_sides(changed, rules)
    if base == snap.head:
        return merge.land_committed(worktree, target, branch, snap)
    check_linear(worktree, base, head)
    trial = merge.trial_merge(worktree, base, snap.head, head)
    merge.rule_sides(trial.conflicts, rules)
    touched = {**changed, **merge.diff_paths(worktree, snap.head, trial.tree)}
    merge.check_overlap(target, touched, touched, snap.dirty, {}, fast_forward=True)
    state = new_state(worktree, target, branch, "committed", snap.head, base, rules, prior)
    resolve.start(worktree, state)
    return resolve.land_resolved(worktree, target, state)


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
    return cut if cut and resolve.is_ancestor(worktree, cut, head) else None


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
    if cut and (shared is None or not resolve.is_ancestor(worktree, cut, shared)):
        return cut
    if shared is None:
        raise AttachError("the worktree shares no history with the target and its HEAD reflog no longer "
                          "names the commit it was cut from")
    return shared


def no_change(base: str, prior: Optional[State]) -> AttachError:
    if prior:
        return AttachError(f"nothing to move: the worktree's HEAD holds no changes over {base[:7]}, the "
                           "target HEAD the resolution rebased onto; run --abort to drop the attach")
    return AttachError("nothing to move: the worktree has no changes since it was cut")


def move_staged(worktree: Path, target: Path, branch: str, rules: Sequence[AutoResolve],
                prior: Optional[State] = None) -> List[str]:
    """Trial-merge the worktree's changes onto the target, then stage them there exactly; report lines.

    Conflicts no rule settles go to resolution in the worktree. ``prior`` as for ``move_committed``.
    """
    snap = merge.snapshot(target)
    base = prior.target_head if prior else patch_base(worktree, target)
    change = merge.worktree_change(worktree, base)
    if not change.paths:
        raise no_change(base, prior)
    sides = merge.rule_sides(change.paths, rules)
    final = merge.final_tree(worktree, base, snap.head, change, rules)
    if not final.conflicts:
        return merge.stage_final(target, branch, snap, final.tree, change.paths, rules)
    resolve.require_clean(worktree, final.conflicts)
    merge.check_overlap(target, change.paths, change.paths, snap.dirty, sides)
    state = new_state(worktree, target, branch, "staged", snap.head, base, rules, prior)
    resolve.start_staged(worktree, state, final.conflicts)
    return resolve.land_resolved(worktree, target, state)


def finish(lines: List[str], worktree: Path, main: Path) -> List[str]:
    """The move's report plus the removal line; a failed removal still carries the report."""
    try:
        return [*lines, remove_worktree(worktree, main)]
    except (AttachError, OSError) as exc:
        message = str(exc)
        if not isinstance(exc, AttachError):
            message = (f"the move succeeded but removing the worktree failed: {message}; remove it with "
                       f"git worktree remove --force {worktree.as_posix()}")
        raise AttachError(message, report=lines) from exc


def remove_worktree(worktree: Path, main: Path) -> str:
    """Remove the worktree; the process leaves it first, since a held directory blocks removal on Windows."""
    os.chdir(main)
    done = run_git(main, "worktree", "remove", "--force", str(worktree))
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", errors="replace").strip()
        raise AttachError(f"the move succeeded but removing the worktree failed ({detail}); remove it with "
                          f"git worktree remove --force {worktree.as_posix()}")
    return f"removed worktree {worktree.as_posix()}"


def check_resume(args: argparse.Namespace, state: Optional[State], entries: List[Checkout],
                 worktree: Path) -> State:
    """The state ``--continue`` or ``--abort`` resumes; refuses arguments that differ from it."""
    if args.resume and args.abort:
        raise AttachError("--continue and --abort exclude each other; pass one")
    if state is None:
        raise AttachError(f"no attach is stopped in the worktree {worktree.as_posix()}; nothing to continue "
                          "or abort")
    if args.target and resolve_branch(entries, args.target) != state.target_branch:
        raise AttachError(f"the stopped attach targets {state.target_branch}, not {args.target}; pass "
                          "--continue or --abort without a target")
    if args.committed and state.mode != "committed":
        raise AttachError("the stopped attach is a staged move, so --committed does not apply; pass "
                          "--continue or --abort without a mode")
    extra = [rule.pattern for rule in args.auto_resolve if rule not in state.rules]
    if extra and args.resume:
        raise AttachError(f"the stopped attach was started without the rule(s) for {', '.join(extra)}; "
                          "--continue keeps the rules it started with, so --abort and rerun to change them")
    return state


def resume(worktree: Path, entries: List[Checkout], state: State) -> List[str]:
    """``--continue``: finish a stopped rebase and land, or restart the flow from the resolved HEAD."""
    target = target_checkout(entries, state.target_branch, worktree)
    if resolve.rebasing(worktree):
        resolve.continue_rebase(worktree, state)
        return resolve.land_resolved(worktree, target, state)
    resolve.check_resolved(worktree, state)
    move = move_committed if state.mode == "committed" else move_staged
    return move(worktree, target, state.target_branch, state.rules, prior=state)


def start(args: argparse.Namespace, worktree: Path, entries: List[Checkout],
          state: Optional[State]) -> List[str]:
    """A plain run: refuse while an attach is stopped or another rebase is in progress, else move."""
    if state is not None:
        raise AttachError(f"an attach to {state.target_branch} is stopped for resolution in this worktree; "
                          "finish it with --continue or drop it with --abort")
    resolve.refuse_foreign_rebase(worktree)
    branch = resolve_branch(entries, args.target)
    target = target_checkout(entries, branch, worktree)
    rules = load_rules(target, args.auto_resolve)
    move = move_committed if args.committed else move_staged
    return move(worktree, target, branch, rules)


def attach(args: argparse.Namespace) -> List[str]:
    """Move the worktree's work onto the target branch, remove the worktree, return the report lines."""
    check_git_version(git_version())
    worktree = worktree_path(args.worktree)
    entries = checkouts(worktree)
    main = entries[0].path
    if worktree == main:
        raise AttachError(f"{worktree.as_posix()} is the main checkout, not a linked worktree")
    state = resolve.read_state(worktree)
    if args.resume or args.abort:
        state = check_resume(args, state, entries, worktree)
        if args.abort:
            return resolve.abort(worktree, state)
    try:
        lines = resume(worktree, entries, state) if args.resume else start(args, worktree, entries, state)
    except AttachError as exc:
        raise resolve.keep_hint(worktree, exc) from exc
    resolve.clear_state(worktree)
    return finish(lines, worktree, main)


class Parser(argparse.ArgumentParser):
    """An argument parser whose usage errors exit 1, since exit 2 means stopped for resolution."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def parse_args(argv: Optional[list]) -> argparse.Namespace:
    parser = Parser(description=__doc__.splitlines()[0])
    parser.add_argument("target_positional", nargs="?", metavar="TARGET",
                        help="target branch, or HEAD for the main checkout's branch")
    parser.add_argument("--target-branch", "--target_branch", dest="target_flag", metavar="BRANCH",
                        help="target branch, as a flag")
    parser.add_argument("--worktree", type=Path, help="worktree to attach (default: the current directory)")
    parser.add_argument("--committed", action="store_true",
                        help="fast-forward the target to the worktree's commits instead of staging")
    parser.add_argument("--auto-resolve", dest="auto_resolve", action="append", type=parse_rule, default=[],
                        metavar="PATTERN=SIDE",
                        help="settle a conflict on paths matching PATTERN with SIDE's whole file "
                             "(worktree or branch); repeatable")
    parser.add_argument("--continue", dest="resume", action="store_true",
                        help="finish an attach stopped for resolution, once its conflicts are added")
    parser.add_argument("--abort", action="store_true",
                        help="drop an attach stopped for resolution; the worktree returns to its "
                             "original HEAD")
    args = parser.parse_args(argv)
    args.target = args.target_flag or args.target_positional
    if not args.target and not (args.resume or args.abort):
        parser.error("a target branch is required, as TARGET or --target-branch")
    return args


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    try:
        lines = attach(args)
    except StopForResolution as stop:
        print("\n".join(stop.lines))
        return 2
    except AttachError as exc:
        if exc.report:
            print("\n".join(exc.report))
        print(f"attach_worktree: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
