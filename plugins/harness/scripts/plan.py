"""plan driver: start a plan, check its claims against the tree, freeze it, record each item with evidence.

The mechanical half of the ``write-plan`` skill. A plan is an ActionPlan JSON under the project's
``artifacts.plans`` (``<plan_id>_<Title>_ActionPlan.json``) with its PIP rendered beside it and the test files
it plans under ``<plan_id>/tests/<repo-relative path>``. Every defect is one ``problem: ...`` line on stderr
with exit 1; success exits 0 and writes nothing on a refusal.

``new TITLE [--spec PATH] [--base BRANCH] [--no-fetch]``
    Write an empty plan with the next plan id, the spec path and the base commit (the merge base of the base
    branch and HEAD, fetched from ``origin`` when the remote exists), then render its PIP.

``check PLAN``
    Validate the schema; then lint (item ids, dependencies, decisions, values, commands, planned test files),
    open every anchor, run every sweep, require each COMPLETE item to carry the commit (reachable from HEAD)
    and tree ``record --sha`` writes and, on a frozen plan, compare the freeze digest. Open decisions are
    listed as ``open:`` lines, not problems. Read-only.

``render PLAN``
    Write the PIP from the plan JSON.

``red PLAN``
    Copy the planned test files onto a throwaway detached worktree at HEAD, run every open item's test
    nodes there (one pytest process per node) and require each to fail with its planned exception. The
    runs import the worktree's code: it is the working directory, and a src-layout ``src/`` goes first on
    ``PYTHONPATH``, ahead of an editable install of the checkout. The worktree is removed afterwards; the
    checkout is never written.

``freeze PLAN [--refreeze]``
    Refuse while ``check`` has a problem, a decision is open, an open item has neither a test nor a command,
    an item is not PENDING on a first freeze, or ``red`` has a problem; otherwise record HEAD, its tree, the
    date and the digest of every field but the execution fields (``plan_doc.MUTABLE_TOP`` and
    ``MUTABLE_ITEM``): the item status, evidence and verification references and the plan's completed,
    frozen and markdown sync fields.

``lanes PLAN [--target BRANCH]``
    Print the ``parallel2`` plan JSON of a frozen plan's open items (waves from dependencies and file
    overlap), ready for ``parallel2.py plan -``.

``record PLAN ITEM (--sha SHA | --start | --blocked REASON | --closed RATIONALE)``
    On a frozen, unedited plan: ``--sha`` needs every dependency done, ``SHA`` reachable from HEAD and
    changing one of the item's files since the base, the item's files unchanged since ``SHA``, and the
    item's test nodes passing on a throwaway detached worktree at ``SHA``; it then marks the item COMPLETE
    with the SHA, tree and test command as evidence. An item without test nodes is recorded on the commit
    alone: its commands are not run. The other flags set IN_PROGRESS, BLOCKED or CLOSED_NO_ACTION, with no
    commit. The PIP is rendered again.

``PLAN`` is a plan id (``7`` or ``0007``) or a path to the plan file. ``--repo`` (default: the working
directory) names a directory inside the project. Usage::

    plan.py [--repo DIR] new TITLE [--spec PATH] [--base BRANCH] [--no-fetch]
    plan.py [--repo DIR] check PLAN
    plan.py [--repo DIR] render PLAN
    plan.py [--repo DIR] red PLAN
    plan.py [--repo DIR] freeze PLAN [--refreeze]
    plan.py [--repo DIR] lanes PLAN [--target BRANCH]
    plan.py [--repo DIR] record PLAN ITEM (--sha SHA | --start | --blocked REASON | --closed RATIONALE)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib import parallel_lanes as pl
from harness_lib import plan_checks as pc
from harness_lib import plan_doc as pd
from harness_lib import plan_lanes as plx
from harness_lib import plan_red as pr
from harness_lib.branch_capture import CaptureError, current_branch, git, git_out, resolve_merge_base
from harness_lib.config import ConfigError, active, activate, load_config
from harness_lib.plan_render import render_pip
from harness_lib.project import project_root

PROBLEMS = (pd.PlanError, pl.PlanError, CaptureError, ConfigError)
SHA40 = re.compile(r"[0-9a-f]{40}")


def today() -> str:
    return dt.date.today().isoformat()


# --- locations --------------------------------------------------------------------------------------------

def plans_dir() -> Path:
    return active().path(active().artifacts.plans)


def locate(repo: Path, ref: str) -> Path:
    """The plan file named by ``ref``: an existing ``*_ActionPlan.json`` path, else a plan id."""
    for candidate in (Path(ref), repo / ref):
        if candidate.name.endswith(pd.PLAN_SUFFIX) and candidate.is_file():
            return candidate
    if not ref.isdigit():
        raise pd.PlanError([f"{ref} is neither a plan file nor a plan id"])
    return pd.find_plan(plans_dir(), ref)


def rel(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_pip(plan_file: Path, plan: Dict[str, Any]) -> Path:
    target = pd.pip_path(plan_file)
    target.write_text(render_pip(plan, plan_file.name), encoding="utf-8")
    return target


def save(plan_file: Path, plan: Dict[str, Any]) -> Path:
    pd.save_plan(plan_file, plan)
    return write_pip(plan_file, plan)


# --- new --------------------------------------------------------------------------------------------------

def has_origin(repo: Path) -> bool:
    return git(repo, "remote", "get-url", "origin").returncode == 0


def skeleton(plan_id: str, spec: Optional[str], base: str, base_commit: str, branch: str,
             pip_rel: str) -> Dict[str, Any]:
    return {
        "plan_id": plan_id, "plan_created": today(), "execution_model": "serial",
        "source_document": spec, "documentation": pip_rel, "branch": branch or None, "base_branch": base,
        "base_commit": base_commit, "frozen": None, "decisions": [], "values": [], "formats": [],
        "sweeps": [], "items": [],
    }


def cmd_new(repo: Path, args: argparse.Namespace) -> int:
    spec = Path(args.spec).as_posix() if args.spec else None
    if spec and not (repo / spec).is_file():
        raise pd.PlanError([f"spec {spec} does not exist"])
    base = args.base or active().resolve_base_branch()
    base_commit = resolve_merge_base(repo, base, fetch=not args.no_fetch and has_origin(repo))
    folder = plans_dir()
    plan_id = pd.next_plan_id(folder)
    plan_file = pd.plan_path(folder, plan_id, pd.title_slug(args.title))
    plan = skeleton(plan_id, spec, base, base_commit, current_branch(repo), rel(repo, pd.pip_path(plan_file)))
    pip = save(plan_file, plan)
    tests = rel(repo, pd.planned_tests_dir(folder, plan_id))
    print("\n".join([f"new [done] | plan {plan_id} | base {base} @ {base_commit[:7]}",
                     f"plan:  {rel(repo, plan_file)}", f"pip:   {rel(repo, pip)}",
                     f"tests: {tests}/<repo-relative path>",
                     f"next: fill decisions, items, anchors and sweeps; then plan.py check {plan_id}"]))
    return 0


# --- check ------------------------------------------------------------------------------------------------

def digest_problems(plan: Dict[str, Any]) -> List[str]:
    frozen = plan.get("frozen")
    if not isinstance(frozen, dict) or frozen.get("digest") == pd.frozen_digest(plan):
        return []
    return ["plan changed after freeze (a field outside the item status, evidence and verification "
            "references and the completed, frozen and markdown sync fields); "
            "restore it, or rerun freeze --refreeze"]


def record_shape_problem(repo: Path, item: Dict[str, Any]) -> Optional[str]:
    """Why a COMPLETE item lacks what ``record --sha`` writes: a commit reachable from HEAD, then its tree."""
    refs = [str(ref) for ref in item.get("verification_references") or []]
    sha = refs[0] if refs else ""
    if not SHA40.fullmatch(sha) or git(repo, "merge-base", "--is-ancestor", sha, "HEAD").returncode != 0:
        return "no commit reachable from HEAD"
    tree = git_out(repo, "rev-parse", f"{sha}^{{tree}}").strip()
    return None if refs[1:2] == [f"tree {tree}"] else f"no tree entry of {sha[:7]}"


def completion_problems(repo: Path, plan: Dict[str, Any]) -> List[str]:
    """One line per COMPLETE item that ``record --sha`` did not mark (a hand-set status)."""
    out = []
    for item in pd.items_of(plan):
        why = record_shape_problem(repo, item) if item.get("status") == "COMPLETE" else None
        if why:
            out.append(f"{item.get('id')} is COMPLETE without the record of record --sha ({why}); "
                       "set it back and run record")
    return out


def all_problems(repo: Path, plan: Dict[str, Any]) -> List[str]:
    """Schema problems alone when there are any (later checks assume the shape), else every check."""
    schema = pd.schema_problems(plan, active())
    if schema:
        return schema
    return (pc.lint_problems(plan, repo, plans_dir()) + pc.anchor_problems(plan, repo)
            + pc.sweep_problems(plan, repo, active().artifacts.plans) + digest_problems(plan)
            + completion_problems(repo, plan))


def check_summary(plan: Dict[str, Any]) -> str:
    items = pd.items_of(plan)
    anchors = sum(1 for _ in pc.anchors_of(plan))
    sweeps = len(plan.get("sweeps") or [])
    opened = pc.open_decisions(plan)
    return (f"check [ok] | plan {plan.get('plan_id')} | {len(items)} items, {anchors} anchors, "
            f"{sweeps} sweeps | open decisions: {len(opened)}")


def cmd_check(repo: Path, args: argparse.Namespace) -> int:
    plan = pd.load_plan(locate(repo, args.plan))
    problems = all_problems(repo, plan)
    if problems:
        raise pd.PlanError(problems)
    print("\n".join([check_summary(plan), *(f"open: {d}" for d in pc.open_decisions(plan))]))
    return 0


def cmd_render(repo: Path, args: argparse.Namespace) -> int:
    plan_file = locate(repo, args.plan)
    pip = write_pip(plan_file, pd.load_plan(plan_file))
    print(f"render [done] | {rel(repo, pip)}")
    return 0


# --- red --------------------------------------------------------------------------------------------------

def planned_nodes(plan: Dict[str, Any]) -> int:
    return sum(len(item.get("tests") or []) for item in plx.open_items(plan))


def red_results(repo: Path, plan: Dict[str, Any]) -> List[pr.RedResult]:
    """Run the open items' test nodes on a throwaway worktree at HEAD with the planned files laid over it."""
    if not planned_nodes(plan):
        return []
    head = git_out(repo, "rev-parse", "HEAD").strip()
    tree = pr.make_tree(repo, head, active().resolve_worktree_root())
    try:
        pr.overlay(pr.test_sources(plan, plans_dir()), tree)
        return pr.run_red(plan, tree, sys.executable)
    finally:
        pr.drop_tree(repo, tree)


def red_problems(repo: Path, plan: Dict[str, Any]) -> Tuple[List[pr.RedResult], List[str]]:
    results = red_results(repo, plan)
    return results, [f"red: {p}" for p in pr.red_problems(results)]


def cmd_red(repo: Path, args: argparse.Namespace) -> int:
    plan = pd.load_plan(locate(repo, args.plan))
    results, problems = red_problems(repo, plan)
    if problems:
        raise pd.PlanError(problems)
    head = f"red [ok] | plan {plan.get('plan_id')}"
    if not results:
        print(f"{head} | no planned test nodes in open items")
        return 0
    rows = [f"{r.item} {r.node}: {r.got} (planned {r.expected})" for r in results]
    print("\n".join([f"{head} | {len(results)} nodes fail as planned", *rows]))
    return 0


# --- freeze -----------------------------------------------------------------------------------------------

def unproven_items(plan: Dict[str, Any]) -> List[str]:
    return [f"{i.get('id')} has no test and no command: nothing proves it" for i in pd.items_of(plan)
            if i.get("status") not in pd.DONE and not i.get("tests") and not i.get("commands")]


def started_items(plan: Dict[str, Any]) -> List[str]:
    """On a plan never frozen, one line per item not PENDING: only ``record`` sets the other states."""
    if isinstance(plan.get("frozen"), dict):
        return []
    return [f"{i.get('id')} is {i.get('status')}: a first freeze needs every item PENDING; "
            "record sets the rest" for i in pd.items_of(plan) if i.get("status") != "PENDING"]


def freeze_problems(repo: Path, plan: Dict[str, Any], refreeze: bool) -> List[str]:
    frozen = plan.get("frozen")
    if isinstance(frozen, dict) and not refreeze:
        return [f"plan {plan.get('plan_id')} is already frozen ({frozen.get('date')}); pass --refreeze"]
    problems = [p for p in all_problems(repo, plan) if not (refreeze and p.startswith("plan changed after"))]
    problems += [f"decision {d} is open: {q}" for d, q in (o.split(": ", 1) for o in pc.open_decisions(plan))]
    problems += started_items(plan) + unproven_items(plan)
    return problems + ([] if pd.items_of(plan) else ["the plan has no items"])


def cmd_freeze(repo: Path, args: argparse.Namespace) -> int:
    plan_file = locate(repo, args.plan)
    plan = pd.load_plan(plan_file)
    problems = freeze_problems(repo, plan, args.refreeze)
    if problems:
        raise pd.PlanError(problems)
    problems = red_problems(repo, plan)[1]
    if problems:
        raise pd.PlanError(problems)
    head = git_out(repo, "rev-parse", "HEAD").strip()
    tree = git_out(repo, "rev-parse", "HEAD^{tree}").strip()
    plan["frozen"] = {"commit": head, "tree": tree, "date": today(), "digest": pd.frozen_digest(plan)}
    save(plan_file, plan)
    print(f"freeze [done] | plan {plan.get('plan_id')} | at {head[:7]} | {len(pd.items_of(plan))} items")
    return 0


# --- record -----------------------------------------------------------------------------------------------

def require_frozen(repo: Path, plan: Dict[str, Any]) -> None:
    if not isinstance(plan.get("frozen"), dict):
        raise pd.PlanError([f"plan {plan.get('plan_id')} is not frozen; run freeze first"])
    problems = digest_problems(plan) + completion_problems(repo, plan)
    if problems:
        raise pd.PlanError(problems)


def dependency_problems(plan: Dict[str, Any], item: Dict[str, Any]) -> List[str]:
    out = []
    for dep in item.get("dependencies") or []:
        status = pd.item_by_id(plan, dep).get("status")
        if status not in pd.DONE:
            out.append(f"{item.get('id')} depends on {dep}, which is {status}")
    return out


def item_paths(item: Dict[str, Any]) -> List[str]:
    nodes = [str(t.get("node")).split("::")[0] for t in item.get("tests") or []]
    return list(dict.fromkeys([*(item.get("files") or []), *nodes]))


def resolve_commit(repo: Path, sha: str) -> str:
    done = git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    if done.returncode != 0:
        raise pd.PlanError([f"{sha} does not name a commit"])
    full = done.stdout.strip()
    if git(repo, "merge-base", "--is-ancestor", full, "HEAD").returncode != 0:
        raise pd.PlanError([f"commit {full[:7]} is not reachable from HEAD"])
    return full


def commit_problems(repo: Path, plan: Dict[str, Any], item: Dict[str, Any], sha: str) -> List[str]:
    """The commit changes one of the item's files since the base; the tree still matches it there."""
    paths, item_id = item_paths(item), item.get("id")
    if not paths:
        return []
    changed = git_out(repo, "diff", "--name-only", str(plan.get("base_commit")), sha, "--", *paths).split()
    out = [] if changed else [f"{item_id}: no file of the item changed between the base and {sha[:7]}"]
    differ = git_out(repo, "diff", "--name-only", sha, "--", *paths).split()
    differ += git_out(repo, "ls-files", "--others", "--exclude-standard", "--", *paths).split()
    if differ:
        listed = ", ".join(sorted(set(differ)))
        out.append(f"{item_id} files differ from {sha[:7]} in the working tree: {listed}; "
                   "commit them and record that commit")
    return out


def tests_at(repo: Path, sha: str, cmd: List[str]) -> "subprocess.CompletedProcess[str]":
    """Run ``cmd`` on a throwaway detached worktree at ``sha``, so the tests see that commit alone."""
    tree = pr.make_tree(repo, sha, active().resolve_worktree_root())
    try:
        return pr.run_pytest(cmd, tree)
    finally:
        pr.drop_tree(repo, tree)


def run_tests(repo: Path, item: Dict[str, Any], sha: str) -> List[str]:
    """The pytest command of the item's nodes after they passed at ``sha``; a problem when they fail."""
    nodes = [str(t.get("node")) for t in item.get("tests") or []]
    if not nodes:
        return []
    done = tests_at(repo, sha, [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *nodes])
    if done.returncode != 0:
        tail = " | ".join(done.stdout.strip().splitlines()[-3:])
        raise pd.PlanError([f"{item.get('id')} tests failed at {sha[:7]}: {tail}"])
    return ["python -m pytest -q " + " ".join(nodes)]


def complete(repo: Path, plan: Dict[str, Any], item: Dict[str, Any], sha_ref: str) -> str:
    problems = dependency_problems(plan, item)
    if problems:
        raise pd.PlanError(problems)
    sha = resolve_commit(repo, sha_ref)
    problems = commit_problems(repo, plan, item, sha)
    if problems:
        raise pd.PlanError(problems)
    command = run_tests(repo, item, sha)
    tree = git_out(repo, "rev-parse", f"{sha}^{{tree}}").strip()
    nodes = len(item.get("tests") or [])
    item["evidence"] = f"commit {sha[:7]}: {nodes} test node(s) passed" if nodes else f"commit {sha[:7]}"
    item["verification_references"] = [sha, f"tree {tree}", *command]
    return "COMPLETE"


def reject_empty(flag: str, value: Optional[str]) -> None:
    if value is not None and not value.strip():
        raise pd.PlanError([f"--{flag} needs a non-empty value (an unset shell variable?)"])


def apply_record(repo: Path, plan: Dict[str, Any], item: Dict[str, Any], args: argparse.Namespace) -> str:
    for flag, value in (("sha", args.sha), ("blocked", args.blocked), ("closed", args.closed)):
        reject_empty(flag, value)
    if args.sha is not None:
        return complete(repo, plan, item, args.sha)
    status, evidence = (("IN_PROGRESS", f"started {today()}") if args.start
                        else ("BLOCKED", args.blocked) if args.blocked is not None
                        else ("CLOSED_NO_ACTION", args.closed))
    item["evidence"] = evidence
    return status


def cmd_record(repo: Path, args: argparse.Namespace) -> int:
    plan_file = locate(repo, args.plan)
    plan = pd.load_plan(plan_file)
    require_frozen(repo, plan)
    item = pd.item_by_id(plan, args.item)
    item["status"] = apply_record(repo, plan, item, args)
    if all(i.get("status") in pd.DONE for i in pd.items_of(plan)):
        plan["completed"] = today()
    else:
        plan.pop("completed", None)
    save(plan_file, plan)
    left = [str(i.get("id")) for i in pd.items_of(plan) if i.get("status") not in pd.DONE]
    print(f"record [done] | {item['id']} {item['status']} | open: {', '.join(left) or 'none'}")
    return 0


# --- lanes ------------------------------------------------------------------------------------------------

def cmd_lanes(repo: Path, args: argparse.Namespace) -> int:
    plan = pd.load_plan(locate(repo, args.plan))
    require_frozen(repo, plan)
    target = args.target or current_branch(repo)
    if not target:
        raise CaptureError(["detached HEAD: check out the target branch or pass --target"])
    print(json.dumps(plx.lanes_plan(plan, target), indent=2))
    return 0


# --- command line -----------------------------------------------------------------------------------------

def _record_parser(sub: Any) -> None:
    record = sub.add_parser("record", help="Record an item's status with its evidence.")
    record.add_argument("plan", help="Plan id or plan file.")
    record.add_argument("item", help="Item id, such as TASK-1.")
    mode = record.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sha", help="Commit that implements the item; marks it COMPLETE.")
    mode.add_argument("--start", action="store_true", help="Mark the item IN_PROGRESS.")
    mode.add_argument("--blocked", metavar="REASON", help="Mark the item BLOCKED.")
    mode.add_argument("--closed", metavar="RATIONALE", help="Mark the item CLOSED_NO_ACTION.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plan.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=None, help="Directory inside the project (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="Start a plan.")
    new.add_argument("title", help="Plan title; becomes part of the file name.")
    new.add_argument("--spec", help="Repo-relative path of the spec the plan implements.")
    new.add_argument("--base", help="Base branch (default: the configured base branch).")
    new.add_argument("--no-fetch", action="store_true", help="Do not fetch the base branch from origin.")
    for name, text in (("check", "Check the plan against the tree."), ("render", "Write the PIP."),
                       ("red", "Run the planned tests and require each to fail as planned.")):
        sub.add_parser(name, help=text).add_argument("plan", help="Plan id or plan file.")
    freeze = sub.add_parser("freeze", help="Freeze a plan that passes check and red.")
    freeze.add_argument("plan", help="Plan id or plan file.")
    freeze.add_argument("--refreeze", action="store_true", help="Freeze a frozen plan again after a change.")
    lanes = sub.add_parser("lanes", help="Print the parallel2 plan of a frozen plan's open items.")
    lanes.add_argument("plan", help="Plan id or plan file.")
    lanes.add_argument("--target", help="Target branch of the lanes (default: the checked-out branch).")
    _record_parser(sub)
    return parser


COMMANDS: Dict[str, Callable[[Path, argparse.Namespace], int]] = {
    "new": cmd_new, "check": cmd_check, "render": cmd_render, "red": cmd_red, "freeze": cmd_freeze,
    "lanes": cmd_lanes, "record": cmd_record,
}


def activate_project(start: Optional[Path]) -> Path:
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
