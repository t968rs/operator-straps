"""parallel2 driver: plan lanes, set up one worktree per implementer lane, stage a finished lane, clean up.

The mechanical half of the ``parallel2`` skill. The run state lives in the consuming project at
``<main checkout>/<state_dir>/parallel2/<target-slug>.json`` and the lane briefs beside it in
``<target-slug>/<lane-id>.md``. One run exists per target branch. Every defect is one ``problem: ...`` line
on stderr with exit 1; success exits 0. A refusal (a validation defect) writes nothing, while a stage
conflict or a partial cleanup records what was done before exiting 1.

``plan PLAN_JSON [--replace]``
    Validate a dispatch plan (lane ids, kinds, models, tools, file entries, waves, overlap inside a wave;
    ``-`` reads it from stdin), pack unwaved lanes into waves, write the state and print the waves, the
    worktree prong and the probe prong. An earlier run with lanes not yet cleaned up is refused unless
    ``--replace``; ``--replace`` itself is refused while an earlier lane still has a worktree.

``setup [--wave N] [--probe] [--with-setup]``
    For the lowest planned wave (or ``N``): cut ``p2/<lane-id>`` branches and worktrees from HEAD for the
    implement lanes (all at once), write a brief for every lane of the wave and print one dispatch row per
    lane, then, with ``--probe``, the wave's probe output as ``probe --wave N`` prints it. ``--with-setup``
    runs the project's ``worktree_setup`` and ``worktree_baseline`` in each new lane worktree, as ``d-w``
    does, reported on stderr; a failed step never fails setup. The
    checkout must be on the target branch and hold no unstaged or untracked change under a lane's files.
    With changes staged (an earlier wave's ``stage``), the lanes are cut from a commit of the index on HEAD
    that no branch references, so a later wave builds on the staged work without a commit on the target.

``probe [--wave N] [--passed PROFILE ...]``
    Print one permission-probe prompt per tool profile of the wave's implement lanes. A profile whose tools
    lanes already probed clean cover (worktrees in the same folder) prints a ``skipped`` line instead.
    ``--passed`` records the named profiles' lanes probed clean and prints no prompt.

``stage LANE [--include-undeclared]``
    Apply a finished implement lane's committed diff (from its base) three-way onto the index of the
    checkout (no commit), so target commits made since setup are merged rather than reverted. A leftover
    probe file is deleted first. Refused when the lane worktree is dirty, the lane has no commits, it changed
    paths outside its files, or a changed path is unstaged, untracked or restaged since setup in the
    checkout. A conflict leaves markers, records the lane staged and exits 1 naming the conflicted paths.

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
    parallel2.py [--repo DIR] [--target BRANCH] setup [--wave N] [--probe] [--with-setup]
    parallel2.py [--repo DIR] [--target BRANCH] probe [--wave N] [--passed PROFILE ...]
    parallel2.py [--repo DIR] [--target BRANCH] stage LANE [--include-undeclared]
    parallel2.py [--repo DIR] [--target BRANCH] status
    parallel2.py [--repo DIR] [--target BRANCH] cleanup [--lane ID ...] [--all]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib import branch_capture as bc
from harness_lib import parallel_lanes as pl
from harness_lib.branch_capture import CaptureError, capture_paths, current_branch, git, git_out
from harness_lib.commit_grouping import CapturedPath
from harness_lib.config import ConfigError, active, activate, load_config
from harness_lib.project import main_worktree, project_root

PROBLEMS = (pl.PlanError, CaptureError, ConfigError)
MAX_PARALLEL_ADDS = 8
SNAPSHOT_IDENTITY = {
    "GIT_AUTHOR_NAME": "parallel2", "GIT_AUTHOR_EMAIL": "parallel2@localhost",
    "GIT_COMMITTER_NAME": "parallel2", "GIT_COMMITTER_EMAIL": "parallel2@localhost",
}


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
    """Lanes of the target's run, or None when no run exists; a problem when the state names another run."""
    path = state_file(repo, target)
    if not path.is_file():
        return None
    stored, lanes = pl.load_state(path.read_text(encoding="utf-8"))
    if stored != target:
        raise CaptureError([f"state file {path.name} belongs to target {stored}, not {target}"])
    return lanes


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


def status_entries(repo: Path) -> List[Tuple[str, str]]:
    """``(XY, path)`` per changed path (a rename's old side too, with its entry's XY), minus the run state."""
    tokens = iter(git_out(repo, "status", "--porcelain", "-z", "-uall").split("\0"))
    entries: List[Tuple[str, str]] = []
    for token in tokens:
        if not token:
            continue
        entries.append((token[:2], token[3:]))
        if token[0] in "RC" or token[1:2] in ("R", "C"):
            entries.append((token[:2], next(tokens, "")))
    prefix = _own_state_prefix(repo)
    return [(code, path) for code, path in entries if path and not (prefix and path.startswith(prefix))]


def dirty_paths(repo: Path) -> List[str]:
    """Paths with an unstaged or untracked change: what an index snapshot leaves out of a lane's base."""
    return [path for code, path in status_entries(repo) if code[1] != " "]


def _names(listing: str) -> List[str]:
    return [path for path in listing.split("\0") if path]


def overwritten_paths(repo: Path, base_sha: str) -> List[str]:
    """Checkout paths a lane's apply would overwrite.

    Unstaged or untracked paths, and staged paths whose index content differs from the lane's base (restaged
    since the snapshot). A staged path equal to the base came in with the snapshot and merges cleanly.
    """
    staged = set(_names(git_out(repo, "diff", "--cached", "--name-only", "--no-renames", "-z")))
    moved = set(_names(git_out(repo, "diff", "--cached", "--name-only", "--no-renames", "-z", base_sha)))
    return [*dirty_paths(repo), *sorted(staged & moved)]


# --- plan -------------------------------------------------------------------------------------------------

def read_plan(path: Path) -> object:
    """The plan JSON from ``path``, or from stdin when ``path`` is ``-``."""
    try:
        return json.loads(sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise pl.PlanError([f"cannot read plan {path}: {exc}"]) from exc


def guard_existing_run(path: Path, replace: bool) -> None:
    """Refuse to replace a run that still has lanes not cleaned up.

    ``--replace`` discards the record of unfinished lanes, but never of a lane that still has a worktree:
    dropping it would leave that worktree and its ``p2/`` branch beyond the reach of ``cleanup``.
    """
    if not path.is_file():
        return
    lanes = pl.load_state(path.read_text(encoding="utf-8"))[1]
    live = [item.id for item in lanes if pl.has_live_worktree(item)]
    if replace and live:
        raise pl.PlanError([f"a run for this target still has worktrees for lanes: {', '.join(live)}; "
                            "run cleanup --all before --replace"])
    left = pl.unfinished(lanes)
    if left and not replace:
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


def overlap_problems(batch: Sequence[pl.Lane], dirty: Sequence[str]) -> List[str]:
    """Unstaged or untracked checkout paths inside an implement lane's files: the snapshot would miss them."""
    problems = []
    for item in batch:
        hit = pl.pending_in_entries(dirty, item.files) if item.kind == pl.IMPLEMENT else []
        if hit:
            problems.append(f"pending changes in the checkout overlap lane {item.id}: {', '.join(hit)}")
    return problems


def free_worktree_path(root: Path, lane_id: str, taken: Sequence[Path] = ()) -> Path:
    """First of ``p2-<id>``, ``p2-<id>-2``, ... under ``root`` that neither exists nor is ``taken``."""
    path, number = root / f"p2-{lane_id}", 2
    while path.exists() or path in taken:
        path, number = root / f"p2-{lane_id}-{number}", number + 1
    return path


def drop_probe_file(item: pl.Lane) -> None:
    """Delete a probe file left in the lane worktree (a probe without ``Bash(rm)`` cannot)."""
    if item.worktree:
        (Path(str(item.worktree)) / pl.PROBE_FILE).unlink(missing_ok=True)


def remove_worktree(repo: Path, item: pl.Lane, force: bool = False) -> Tuple[bool, Optional[str]]:
    """Remove a lane's worktree, then its branch: ``(worktree removed, problem text or None)``."""
    drop_probe_file(item)
    done = git(repo, "worktree", "remove", *(["--force"] if force else []), str(item.worktree))
    if done.returncode != 0:
        return False, f"lane {item.id}: git worktree remove failed: {done.stderr.strip()}"
    done = git(repo, "branch", "-D", str(item.branch))
    if done.returncode != 0:
        reason = done.stderr.strip()
        return True, f"lane {item.id}: worktree removed, git branch -D {item.branch} failed: {reason}"
    return True, None


def assign_worktrees(batch: Sequence[pl.Lane]) -> List[pl.Lane]:
    """Name each implement lane's branch and a free worktree path; return those lanes."""
    root = active().resolve_worktree_root()
    root.mkdir(parents=True, exist_ok=True)
    items = [i for i in batch if i.kind == pl.IMPLEMENT]
    taken: List[Path] = []
    for item in items:
        taken.append(free_worktree_path(root, item.id, taken))
        item.branch, item.worktree = f"p2/{item.id}", taken[-1].as_posix()
    return items


def add_worktree(repo: Path, item: pl.Lane, base_sha: str) -> Optional[str]:
    """Cut one lane's branch and worktree; the problem text on a failure, else None."""
    done = git(repo, "worktree", "add", "-b", str(item.branch), str(item.worktree), base_sha)
    return None if done.returncode == 0 else f"lane {item.id}: git worktree add failed: {done.stderr.strip()}"


def create_worktrees(repo: Path, batch: Sequence[pl.Lane], base_sha: str) -> None:
    """Cut every implement lane's branch and worktree at once; on any failure, undo all this call made."""
    items = assign_worktrees(batch)
    if not items:
        return
    with ThreadPoolExecutor(max_workers=min(len(items), MAX_PARALLEL_ADDS)) as pool:
        problems = list(pool.map(lambda item: add_worktree(repo, item, base_sha), items))
    if any(problems):
        for item in (i for i, problem in zip(items, problems) if problem is None):
            remove_worktree(repo, item, force=True)
        raise CaptureError([problem for problem in problems if problem])


def write_briefs(repo: Path, target: str, batch: Sequence[pl.Lane]) -> List[Path]:
    folder = briefs_dir(repo, target)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for item in batch:
        path = folder / f"{item.id}.md"
        path.write_text(pl.render_brief(item, item.worktree or repo.as_posix()), encoding="utf-8")
        paths.append(path)
    return paths


def snapshot_commit(repo: Path, head: str, message: str) -> str:
    """A commit of the index on ``head``, referenced by no branch, under the fixed snapshot identity."""
    tree = git_out(repo, "write-tree").strip()
    return bc.snapshot_commit(repo, tree, head, message, SNAPSHOT_IDENTITY)


def cut_base(repo: Path, target: str, wave: int) -> Tuple[str, str, int]:
    """``(base, head, staged count)``: HEAD itself, or an index snapshot on HEAD when changes are staged.

    The snapshot puts staged work (an earlier wave's ``stage``) into the lanes' base without a commit on the
    target branch.
    """
    head = git_out(repo, "rev-parse", "HEAD").strip()
    staged = _names(git_out(repo, "diff", "--cached", "--name-only", "--no-renames", "-z"))
    if not staged:
        return head, head, 0
    return snapshot_commit(repo, head, f"parallel2 index snapshot: {target} wave {wave}"), head, len(staged)


def dw_commands() -> ModuleType:
    """d-w's ``new_worktree.py``, whose ``prepare`` runs the project's worktree setup and baseline steps."""
    path = Path(__file__).resolve().parents[1] / "skills" / "d-w" / "commands" / "new_worktree.py"
    problem = f"cannot load the d-w worktree setup runner at {path.as_posix()}"
    spec = importlib.util.spec_from_file_location("harness_dw_new_worktree", path)
    if spec is None or spec.loader is None:
        raise CaptureError([problem])
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (ImportError, OSError, SyntaxError) as exc:
        raise CaptureError([f"{problem}: {exc}"]) from exc
    return module


def prepare_lanes(batch: Sequence[pl.Lane], prepare: Callable[..., object]) -> None:
    """Run ``worktree_setup``, then ``worktree_baseline``, in each implement lane; stderr names each lane."""
    for item in (i for i in batch if i.kind == pl.IMPLEMENT):
        print(f"lane {item.id}:", file=sys.stderr, flush=True)
        prepare(active(), Path(str(item.worktree)))


def cmd_setup(repo: Path, args: argparse.Namespace) -> int:
    target = run_target(repo, args)
    lanes = require_lanes(repo, target)
    require_checked_out(repo, target)
    wave = pick_wave(lanes, args.wave)
    batch = [i for i in lanes if i.wave == wave and i.status == pl.PLANNED]
    dirty = dirty_paths(repo)
    problems = branch_problems(repo, batch) + overlap_problems(batch, dirty)
    if problems:
        raise CaptureError(problems)
    prepare = dw_commands().prepare if args.with_setup else None
    base_sha, head_sha, staged = cut_base(repo, target, wave)
    create_worktrees(repo, batch, base_sha)
    briefs = write_briefs(repo, target, batch)
    for item in batch:
        item.status, item.base_sha, item.head_sha = pl.DISPATCHED, base_sha, head_sha
    save_lanes(repo, target, lanes)
    if prepare is not None:
        prepare_lanes(batch, prepare)
    print_notes(base_sha, head_sha, staged, dirty)
    print_dispatch(batch, briefs)
    if args.probe:
        print_probes(lanes, wave)
    return 0


def print_notes(base_sha: str, head_sha: str, staged: int, dirty: Sequence[str]) -> None:
    if base_sha != head_sha:
        print(f"note: lanes cut from an index snapshot {base_sha[:7]} of HEAD {head_sha[:7]} "
              f"({staged} staged paths)")
    if dirty:
        print(f"note: {len(dirty)} unstaged or untracked paths in the checkout are not in the lanes' base; "
              "stage them first if a lane reads them")


def print_dispatch(batch: Sequence[pl.Lane], briefs: Sequence[Path]) -> None:
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


def wave_members(lanes: Sequence[pl.Lane], wave: int) -> List[pl.Lane]:
    """The wave's implement lanes with a live worktree: the lanes a probe covers."""
    return [i for i in lanes if i.wave == wave and i.kind == pl.IMPLEMENT and pl.has_live_worktree(i)]


def print_probes(lanes: Sequence[pl.Lane], wave: int) -> None:
    """One probe prompt per profile of the wave, or a skip line for a profile earlier probes cover."""
    members = wave_members(lanes, wave)
    if not members:
        print(f"no implement lanes in wave {wave}: nothing to probe")
    for profile in pl.probe_profiles(members):
        first = lane_by_id(members, profile.lane_ids[0])
        cover = pl.probed_cover(profile.tools, lanes, str(first.worktree))
        if cover:
            print(f"probe={profile.name} skipped: its tools were probed clean ({', '.join(cover)})")
            continue
        tree = Path(str(first.worktree))
        print(f"probe={profile.name} model={profile.model}")
        print(pl.render_probe_prompt(profile.tools, str(first.worktree), probe_read_target(tree, first)))
        print()


def record_passed(repo: Path, target: str, lanes: List[pl.Lane], wave: int, names: Sequence[str]) -> None:
    """Mark the lanes of each named profile of the wave probed clean; a problem for an unknown name."""
    profiles = {profile.name: profile for profile in pl.probe_profiles(wave_members(lanes, wave))}
    unknown = [name for name in names if name not in profiles]
    if unknown:
        raise CaptureError([f"no probe profile {name} in wave {wave}" for name in unknown])
    for name in names:
        for lane_id in profiles[name].lane_ids:
            lane_by_id(lanes, lane_id).probed = True
    save_lanes(repo, target, lanes)
    print("\n".join(f"recorded {name} clean: {', '.join(profiles[name].lane_ids)}" for name in names))


def cmd_probe(repo: Path, args: argparse.Namespace) -> int:
    target = run_target(repo, args)
    lanes = require_lanes(repo, target)
    wave = probe_wave(lanes, args.wave)
    if args.passed:
        record_passed(repo, target, lanes, wave, args.passed)
    else:
        print_probes(lanes, wave)
    return 0


# --- stage ------------------------------------------------------------------------------------------------

def stageable_lane(lanes: Sequence[pl.Lane], lane_id: str) -> pl.Lane:
    item = lane_by_id(lanes, lane_id)
    if item.kind != pl.IMPLEMENT:
        raise CaptureError([f"lane {lane_id} is a {item.kind} lane; only implement lanes are staged"])
    if item.status != pl.DISPATCHED:
        raise CaptureError([f"lane {lane_id} is {item.status}, not dispatched"])
    return item


def moved_note(repo: Path, item: pl.Lane) -> Optional[str]:
    """A note when the target gained commits since setup, else None (older state has no ``head_sha``)."""
    head = git_out(repo, "rev-parse", "HEAD").strip()
    since = str(item.head_sha or item.base_sha)
    if head == since:
        return None
    return f"note: target moved from {since[:7]} to {head[:7]} since setup; merged three-way"


def require_clean_worktree(item: pl.Lane) -> None:
    """Refuse a lane worktree with uncommitted changes; a leftover probe file is deleted first."""
    drop_probe_file(item)
    lines = git_out(Path(str(item.worktree)), "status", "--porcelain").splitlines()
    if any(line[3:] != pl.PROBE_FILE for line in lines if line.strip()):
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
    pending = pl.pending_overlap(changed, overwritten_paths(repo, str(item.base_sha)))
    if pending:
        raise CaptureError([f"pending changes in the checkout would be overwritten: {', '.join(pending)}"])
    return changes


def _stderr(done: subprocess.CompletedProcess) -> str:
    return done.stderr.decode("utf-8", errors="replace").strip()


def apply_lane(repo: Path, item: pl.Lane, changed: Sequence[str]) -> List[str]:
    """Apply the lane's committed diff three-way onto the checkout's index; return the conflicted paths.

    The diff runs from the lane's base, so commits the target gained since setup are merged, never reverted.
    Plumbing ``diff-tree`` builds the patch, so diff prefix, color, external and textconv settings never
    reach it. Only unmerged paths among the lane's ``changed`` paths count as its conflicts.
    """
    diff = subprocess.run(["git", "diff-tree", "-p", "--binary", "-M", "--full-index", str(item.base_sha),
                           str(item.branch)], cwd=repo, capture_output=True)
    if diff.returncode != 0:
        raise CaptureError([f"git diff of lane {item.id} failed: {_stderr(diff)}"])
    done = subprocess.run(["git", "apply", "--3way", "--whitespace=nowarn"], cwd=repo, input=diff.stdout,
                          capture_output=True)
    listing = git_out(repo, "diff", "--name-only", "--diff-filter=U", "-z")
    own = set(changed)
    conflicts = [path for path in listing.split("\0") if path and path in own]
    if done.returncode != 0 and not conflicts:
        raise CaptureError([f"git apply of lane {item.id} failed: {_stderr(done)}"])
    return conflicts


def cmd_stage(repo: Path, args: argparse.Namespace) -> int:
    target = run_target(repo, args)
    lanes = require_lanes(repo, target)
    item = stageable_lane(lanes, args.lane)
    require_checked_out(repo, target)
    require_clean_worktree(item)
    changes = lane_changes(repo, item, args.include_undeclared)
    report = pl.staging_report(changes)
    note = moved_note(repo, item)
    conflicts = apply_lane(repo, item, [path for change in changes for path in change.paths])
    item.status, item.staged = pl.STAGED, report.touched
    save_lanes(repo, target, lanes)
    waiting = [i.id for i in lanes if i.kind == pl.IMPLEMENT and i.status == pl.DISPATCHED]
    still = ", ".join(waiting) or "none"
    print("\n".join([*([note] if note else []), *report.lines, "next: git diff --cached",
                     f"still dispatched: {still}"]))
    if conflicts:
        raise CaptureError([f"three-way merge left conflicts in {', '.join(conflicts)}; "
                            "resolve the markers and git add them"])
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
        finish_state(repo, target, lanes)
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
    setup.add_argument("--probe", action="store_true", help="Also print the wave's probe prompts.")
    setup.add_argument("--with-setup", action="store_true",
                       help="Run the project's worktree_setup and worktree_baseline in each lane worktree.")
    probe = sub.add_parser("probe", parents=shared, help="Print permission-probe prompts for a wave.")
    probe.add_argument("--wave", type=int, help="Wave to probe (default: the lowest set-up wave).")
    probe.add_argument("--passed", nargs="+", metavar="PROFILE",
                       help="Record these profiles of the wave probed clean instead of printing prompts.")
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
