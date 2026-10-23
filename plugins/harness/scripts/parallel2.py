"""parallel2 driver: plan lanes, set up one worktree per implementer lane, stage a finished lane, clean up.

The mechanical half of the ``parallel2`` skill. The run state lives in the consuming project at
``<main checkout>/<state_dir>/parallel2/<target-slug>.json`` and the lane briefs beside it in
``<target-slug>/<lane-id>.md``. One run exists per target branch. Every defect is one ``problem: ...`` line
on stderr with exit 1 and nothing written; success exits 0.

``plan PLAN_JSON [--replace]``
    Validate a dispatch plan (lane ids, kinds, models, tools, file entries, waves, overlap inside a wave),
    pack unwaved lanes into waves, write the state and print the waves, the worktree prong and the probe
    prong. An earlier run with lanes not yet cleaned up is refused unless ``--replace``.

``setup [--wave N]``
    For the lowest planned wave (or ``N``): cut ``p2/<lane-id>`` branches and worktrees from HEAD for the
    implement lanes, write a brief for every lane of the wave and print one dispatch row per lane. The
    checkout must be on the target branch and hold no pending change under a lane's files.

``probe [--wave N]``
    Print one permission-probe prompt per tool profile of the wave's implement lanes.

``stage LANE [--include-undeclared]``
    Apply a finished implement lane to the index of the checkout (no commit). Refused when HEAD moved since
    setup, the lane worktree is dirty, the lane has no commits, it changed paths outside its files, or a
    changed path is pending in the checkout.

``status``
    Print ``id wave kind status branch worktree`` per lane.

``cleanup [--lane ID ...] [--all]``
    Remove the worktree and branch of staged lanes (``--lane``: the named lanes, ``--all``: every lane with a
    worktree). Only lanes recorded in the state are touched; the state and briefs are deleted once no lane
    keeps a worktree or waits for setup.

``--repo`` (default: the working directory) names a directory inside the checkout where the target branch is
checked out; ``--target`` names the run when that differs from the checked-out branch. Both go before or
after the subcommand. Usage::

    parallel2.py [--repo DIR] [--target BRANCH] plan PLAN_JSON [--replace]
    parallel2.py [--repo DIR] [--target BRANCH] setup [--wave N]
    parallel2.py [--repo DIR] [--target BRANCH] probe [--wave N]
    parallel2.py [--repo DIR] [--target BRANCH] stage LANE [--include-undeclared]
    parallel2.py [--repo DIR] [--target BRANCH] status
    parallel2.py [--repo DIR] [--target BRANCH] cleanup [--lane ID ...] [--all]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib import parallel_lanes as pl
from harness_lib.branch_capture import CaptureError, capture_paths, current_branch, git, git_out
from harness_lib.commit_grouping import CapturedPath
from harness_lib.config import ConfigError, active, activate, load_config
from harness_lib.project import main_worktree, project_root

PROBLEMS = (pl.PlanError, CaptureError, ConfigError)
LITERAL = "--literal-pathspecs"


# --- locations and state ----------------------------------------------------------------------------------

def state_folder(repo: Path) -> Path:
    """Folder of every run's state, in the project's main checkout."""
    return main_worktree(repo) / active().state_dir / "parallel2"


def state_file(repo: Path, target: str) -> Path:
    return state_folder(repo) / f"{pl.target_slug(target)}.json"


def briefs_dir(repo: Path, target: str) -> Path:
    return state_folder(repo) / pl.target_slug(target)


def run_target(repo: Path, args: argparse.Namespace) -> str:
    """The run's target: ``--target`` or the checked-out branch."""
    target = args.target or current_branch(repo)
    if not target:
        raise CaptureError(["detached HEAD: check out the target branch or pass --target"])
    return target


def load_lanes(repo: Path, target: str) -> Optional[List[pl.Lane]]:
    """Lanes of the target's run, or None when no run exists."""
    path = state_file(repo, target)
    return pl.load_state(path.read_text(encoding="utf-8"))[1] if path.is_file() else None


def require_lanes(repo: Path, target: str) -> List[pl.Lane]:
    lanes = load_lanes(repo, target)
    if lanes is None:
        raise CaptureError([f"no parallel2 run for {target}; run plan first"])
    return lanes


def save_lanes(repo: Path, target: str, lanes: Sequence[pl.Lane]) -> None:
    path = state_file(repo, target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pl.dump_state(target, lanes), encoding="utf-8")


def require_checked_out(repo: Path, target: str) -> None:
    branch = current_branch(repo)
    if branch != target:
        where = branch or "detached HEAD"
        raise CaptureError([f"target {target} is not checked out in {repo.as_posix()} (on {where})"])


def lane_by_id(lanes: Sequence[pl.Lane], lane_id: str) -> pl.Lane:
    for item in lanes:
        if item.id == lane_id:
            return item
    raise CaptureError([f"lane {lane_id} is not recorded in the run"])


# --- pending paths ----------------------------------------------------------------------------------------

def _own_state_prefix(repo: Path) -> Optional[str]:
    try:
        return state_folder(repo).resolve().relative_to(repo.resolve()).as_posix() + "/"
    except ValueError:
        return None


def pending_paths(repo: Path) -> List[str]:
    """Paths with a staged, unstaged or untracked change (rename old sides included), minus the run state."""
    tokens = iter(git_out(repo, "status", "--porcelain", "-z", "-uall").split("\0"))
    paths: List[str] = []
    for token in tokens:
        if not token:
            continue
        paths.append(token[3:])
        if token[0] in "RC":
            paths.append(next(tokens, ""))
    prefix = _own_state_prefix(repo)
    return [path for path in paths if path and not (prefix and path.startswith(prefix))]


# --- plan -------------------------------------------------------------------------------------------------

def read_plan(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise pl.PlanError([f"cannot read plan {path}: {exc}"]) from exc


def guard_existing_run(path: Path, replace: bool) -> None:
    """Refuse to replace a run that still has lanes not cleaned up."""
    if replace or not path.is_file():
        return
    left = pl.unfinished(pl.load_state(path.read_text(encoding="utf-8"))[1])
    if left:
        raise pl.PlanError([f"a run for this target has unfinished lanes: {', '.join(left)}; pass --replace"])


def cmd_plan(repo: Path, args: argparse.Namespace) -> int:
    planned, lanes = pl.plan_lanes(read_plan(args.plan_json))
    target = planned or run_target(repo, args)
    guard_existing_run(state_file(repo, target), args.replace)
    save_lanes(repo, target, lanes)
    print(pl.render_plan_summary(target, lanes))
    return 0


# --- setup ------------------------------------------------------------------------------------------------

def pick_wave(lanes: Sequence[pl.Lane], wanted: Optional[int]) -> int:
    """``wanted``, else the lowest wave holding a planned lane; a problem when there is none."""
    waves = sorted({item.wave for item in lanes if item.status == pl.PLANNED and item.wave is not None})
    if wanted is not None and wanted not in waves:
        raise CaptureError([f"no planned lane in wave {wanted}"])
    if wanted is None and not waves:
        raise CaptureError(["no planned lane to set up"])
    return waves[0] if wanted is None else wanted


def branch_problems(repo: Path, batch: Sequence[pl.Lane]) -> List[str]:
    return [
        f"branch p2/{item.id} already exists"
        for item in batch if item.kind == pl.IMPLEMENT
        and git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/p2/{item.id}").returncode == 0
    ]


def overlap_problems(batch: Sequence[pl.Lane], pending: Sequence[str]) -> List[str]:
    problems = []
    for item in batch:
        hit = pl.pending_in_entries(pending, item.files) if item.kind == pl.IMPLEMENT else []
        if hit:
            problems.append(f"pending changes in the checkout overlap lane {item.id}: {', '.join(hit)}")
    return problems


def free_worktree_path(root: Path, lane_id: str) -> Path:
    path, number = root / f"p2-{lane_id}", 2
    while path.exists():
        path, number = root / f"p2-{lane_id}-{number}", number + 1
    return path


def remove_worktree(repo: Path, item: pl.Lane, force: bool = False) -> Tuple[bool, Optional[str]]:
    """Remove a lane's worktree, then its branch: ``(worktree removed, problem text or None)``."""
    done = git(repo, "worktree", "remove", *(["--force"] if force else []), str(item.worktree))
    if done.returncode != 0:
        return False, f"lane {item.id}: git worktree remove failed: {done.stderr.strip()}"
    done = git(repo, "branch", "-D", str(item.branch))
    if done.returncode != 0:
        reason = done.stderr.strip()
        return True, f"lane {item.id}: worktree removed, git branch -D {item.branch} failed: {reason}"
    return True, None


def create_worktrees(repo: Path, batch: Sequence[pl.Lane], base_sha: str) -> None:
    """Cut a branch and worktree per implement lane; undo this call's own creations on a failure."""
    root = active().resolve_worktree_root()
    root.mkdir(parents=True, exist_ok=True)
    made: List[pl.Lane] = []
    for item in (i for i in batch if i.kind == pl.IMPLEMENT):
        item.branch, item.worktree = f"p2/{item.id}", free_worktree_path(root, item.id).as_posix()
        done = git(repo, "worktree", "add", "-b", item.branch, item.worktree, base_sha)
        if done.returncode != 0:
            for earlier in made:
                remove_worktree(repo, earlier, force=True)
            raise CaptureError([f"lane {item.id}: git worktree add failed: {done.stderr.strip()}"])
        made.append(item)


def write_briefs(repo: Path, target: str, batch: Sequence[pl.Lane]) -> List[Path]:
    folder = briefs_dir(repo, target)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for item in batch:
        path = folder / f"{item.id}.md"
        path.write_text(pl.render_brief(item, item.worktree or repo.as_posix()), encoding="utf-8")
        paths.append(path)
    return paths


def cmd_setup(repo: Path, args: argparse.Namespace) -> int:
    target = run_target(repo, args)
    lanes = require_lanes(repo, target)
    require_checked_out(repo, target)
    wave = pick_wave(lanes, args.wave)
    batch = [i for i in lanes if i.wave == wave and i.status == pl.PLANNED]
    pending = pending_paths(repo)
    problems = branch_problems(repo, batch) + overlap_problems(batch, pending)
    if problems:
        raise CaptureError(problems)
    base_sha = git_out(repo, "rev-parse", "HEAD").strip()
    create_worktrees(repo, batch, base_sha)
    briefs = write_briefs(repo, target, batch)
    for item in batch:
        item.status, item.base_sha = pl.DISPATCHED, base_sha
    save_lanes(repo, target, lanes)
    print_dispatch(batch, briefs, pending)
    return 0


def print_dispatch(batch: Sequence[pl.Lane], briefs: Sequence[Path], pending: Sequence[str]) -> None:
    if pending:
        print(f"note: {len(pending)} pending paths in the checkout are not in the lanes' base; "
              "commit them first if a lane reads them")
    for item, brief in zip(batch, briefs):
        print(pl.render_dispatch_row(item, item.worktree, brief.resolve().as_posix()))


# --- probe ------------------------------------------------------------------------------------------------

def probe_read_target(tree: Path, item: pl.Lane) -> Optional[str]:
    """First existing plain file of the lane's entries, else ``README.md`` when present."""
    for entry in pl.plain_files(item.files):
        if (tree / entry).is_file():
            return entry
    return "README.md" if (tree / "README.md").is_file() else None


def probe_wave(lanes: Sequence[pl.Lane], wanted: Optional[int]) -> int:
    """``wanted`` when set up, else the lowest wave holding an implement lane with a live worktree."""
    if wanted is not None:
        if any(i.wave == wanted and i.status == pl.PLANNED for i in lanes):
            raise CaptureError([f"wave {wanted} is not set up; run setup --wave {wanted}"])
        return wanted
    live = [i.wave for i in lanes if i.kind == pl.IMPLEMENT and pl.has_live_worktree(i) and i.wave]
    if not live:
        raise CaptureError(["no wave is set up; run setup first"])
    return min(live)


def cmd_probe(repo: Path, args: argparse.Namespace) -> int:
    lanes = require_lanes(repo, run_target(repo, args))
    wave = probe_wave(lanes, args.wave)
    members = [i for i in lanes if i.wave == wave and i.kind == pl.IMPLEMENT and pl.has_live_worktree(i)]
    if not members:
        print(f"no implement lanes in wave {wave}: nothing to probe")
    for profile in pl.probe_profiles(members):
        first = lane_by_id(members, profile.lane_ids[0])
        tree = Path(str(first.worktree))
        print(f"probe={profile.name} model={profile.model}")
        print(pl.render_probe_prompt(profile.tools, str(first.worktree), probe_read_target(tree, first)))
        print()
    return 0


# --- stage ------------------------------------------------------------------------------------------------

def stageable_lane(lanes: Sequence[pl.Lane], lane_id: str) -> pl.Lane:
    item = lane_by_id(lanes, lane_id)
    if item.kind != pl.IMPLEMENT:
        raise CaptureError([f"lane {lane_id} is a {item.kind} lane; only implement lanes are staged"])
    if item.status != pl.DISPATCHED:
        raise CaptureError([f"lane {lane_id} is {item.status}, not dispatched"])
    return item


def require_unmoved_head(repo: Path, item: pl.Lane) -> None:
    head = git_out(repo, "rev-parse", "HEAD").strip()
    if head != item.base_sha:
        raise CaptureError([
            f"target moved from {str(item.base_sha)[:7]} to {head[:7]} since setup; "
            "re-scope the lane against the new HEAD"
        ])


def require_clean_worktree(item: pl.Lane) -> None:
    if git_out(Path(str(item.worktree)), "status", "--porcelain").strip():
        raise CaptureError([f"lane {item.id} worktree has uncommitted changes; commit in the worktree first"])


def lane_changes(repo: Path, item: pl.Lane, include_undeclared: bool) -> List[CapturedPath]:
    """The lane's committed changes; a problem when empty, undeclared, or pending in the checkout."""
    changes = capture_paths(repo, str(item.base_sha), str(item.branch))
    if not changes:
        raise CaptureError([f"lane {item.id} has no commits"])
    outside = [] if include_undeclared else pl.undeclared_paths(changes, item.files)
    if outside:
        raise CaptureError([f"lane {item.id} changed paths outside its files: {', '.join(outside)}"])
    changed = [path for change in changes for path in change.paths]
    pending = pl.pending_overlap(changed, pending_paths(repo))
    if pending:
        raise CaptureError([f"pending changes in the checkout would be overwritten: {', '.join(pending)}"])
    return changes


def apply_staging(repo: Path, branch: str, plan: pl.StagePlan) -> None:
    for chunk in pl.chunks(plan.checkout):
        git_out(repo, LITERAL, "checkout", branch, "--", *chunk)
    for chunk in pl.chunks(plan.remove):
        git_out(repo, LITERAL, "rm", "--quiet", "--", *chunk)


def cmd_stage(repo: Path, args: argparse.Namespace) -> int:
    target = run_target(repo, args)
    lanes = require_lanes(repo, target)
    item = stageable_lane(lanes, args.lane)
    require_checked_out(repo, target)
    require_unmoved_head(repo, item)
    require_clean_worktree(item)
    plan = pl.plan_staging(lane_changes(repo, item, args.include_undeclared))
    apply_staging(repo, str(item.branch), plan)
    item.status, item.staged = pl.STAGED, plan.touched
    save_lanes(repo, target, lanes)
    waiting = [i.id for i in lanes if i.kind == pl.IMPLEMENT and i.status == pl.DISPATCHED]
    still = ", ".join(waiting) or "none"
    print("\n".join([*plan.lines, "next: git diff --cached", f"still dispatched: {still}"]))
    return 0


# --- status and cleanup -----------------------------------------------------------------------------------

def cmd_status(repo: Path, args: argparse.Namespace) -> int:
    target = run_target(repo, args)
    lanes = load_lanes(repo, target)
    if lanes is None:
        print(f"no parallel2 run for {target}")
        return 0
    print("\n".join(pl.render_status_line(item) for item in lanes))
    return 0


def select_for_cleanup(lanes: Sequence[pl.Lane], ids: Sequence[str], everything: bool) -> List[pl.Lane]:
    if everything:
        return [i for i in lanes if pl.has_live_worktree(i)]
    if ids:
        return [lane_by_id(lanes, lane_id) for lane_id in ids]
    return [i for i in lanes if i.status == pl.STAGED and pl.has_live_worktree(i)]


def clean_lane(repo: Path, item: pl.Lane) -> Optional[str]:
    """Remove one lane; None on success, else the problem. A removed worktree marks the lane cleaned."""
    if not pl.has_live_worktree(item):
        return f"lane {item.id}: no worktree to remove"
    removed, problem = remove_worktree(repo, item)
    if removed:
        item.status = pl.CLEANED
    return problem


def finish_state(repo: Path, target: str, lanes: Sequence[pl.Lane]) -> None:
    if pl.state_is_spent(lanes):
        state_file(repo, target).unlink(missing_ok=True)
        shutil.rmtree(briefs_dir(repo, target), ignore_errors=True)
    else:
        save_lanes(repo, target, lanes)


def cmd_cleanup(repo: Path, args: argparse.Namespace) -> int:
    target = run_target(repo, args)
    lanes = load_lanes(repo, target)
    if lanes is None:
        print(f"no parallel2 run for {target}")
        return 0
    chosen = select_for_cleanup(lanes, args.lane or [], args.all)
    if not chosen:
        print("nothing to clean up")
        return 0
    problems: List[str] = []
    for item in chosen:
        problem = clean_lane(repo, item)
        if problem:
            problems.append(problem)
        else:
            print(f"removed {item.id} ({item.branch})")
    finish_state(repo, target, lanes)
    if problems:
        raise CaptureError(problems)
    return 0


# --- command line -----------------------------------------------------------------------------------------

_REPO_HELP = "Directory inside the checkout holding the target branch (default: the working directory)."
_TARGET_HELP = "Target branch naming the run (default: the checked-out branch)."


def _shared() -> argparse.ArgumentParser:
    """``--repo`` and ``--target`` for each subcommand; suppressed defaults keep top-level values intact."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help=_REPO_HELP)
    parent.add_argument("--target", default=argparse.SUPPRESS, help=_TARGET_HELP)
    return parent


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="parallel2.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=None, help=_REPO_HELP)
    parser.add_argument("--target", default=None, help=_TARGET_HELP)
    sub = parser.add_subparsers(dest="command", required=True)
    shared = [_shared()]
    plan = sub.add_parser("plan", parents=shared, help="Validate a plan JSON and write the run state.")
    plan.add_argument("plan_json", type=Path, help="Plan JSON (UTF-8).")
    plan.add_argument("--replace", action="store_true", help="Replace a run with unfinished lanes.")
    setup = sub.add_parser("setup", parents=shared, help="Create worktrees and briefs for a wave.")
    setup.add_argument("--wave", type=int, help="Wave to set up (default: the lowest planned wave).")
    probe = sub.add_parser("probe", parents=shared, help="Print permission-probe prompts for a wave.")
    probe.add_argument("--wave", type=int, help="Wave to probe (default: the lowest set-up wave).")
    stage = sub.add_parser("stage", parents=shared, help="Stage a finished lane onto the target branch.")
    stage.add_argument("lane", help="Lane id.")
    stage.add_argument(
        "--include-undeclared", action="store_true", help="Also stage paths outside the lane's files.",
    )
    sub.add_parser("status", parents=shared, help="Print every lane's state.")
    clean = sub.add_parser("cleanup", parents=shared, help="Remove worktrees and branches the run created.")
    clean.add_argument("--lane", action="append", help="Lane id to clean (repeatable).")
    clean.add_argument("--all", action="store_true", help="Clean every lane with a worktree.")
    return parser


COMMANDS: Dict[str, Callable[[Path, argparse.Namespace], int]] = {
    "plan": cmd_plan, "setup": cmd_setup, "probe": cmd_probe, "stage": cmd_stage,
    "status": cmd_status, "cleanup": cmd_cleanup,
}


def activate_project(start: Optional[Path]) -> Path:
    """Activate the configuration of the project holding ``start`` (default: cwd); return its root."""
    root = project_root(start)
    activate(load_config(root))
    return root


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point; return 0 on success, 1 on a problem."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        return COMMANDS[args.command](activate_project(args.repo), args)
    except PROBLEMS as exc:
        problems = exc.problems if hasattr(exc, "problems") else [str(exc)]
        sys.stderr.write("\n".join(f"problem: {line}" for line in problems) + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
