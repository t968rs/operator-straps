"""plan driver: start a plan, check its claims against the tree, freeze it, record each item with evidence.

The mechanical half of the ``write-plan`` skill. A plan is an ActionPlan JSON under the project's
``artifacts.plans`` (``<plan_id>_<Title>_ActionPlan.json``) with its PIP rendered beside it and the test files
it plans under ``<plan_id>/tests/<repo-relative path>``. Every defect is one ``problem: ...`` line on stderr
with exit 1; success exits 0 and writes nothing on a refusal. Every command validates the plan on load and
refuses an invalid one with ``schema:`` lines.

``new TITLE [--spec PATH] [--base BRANCH] [--no-fetch]``
    Write an empty plan with the next plan id, the spec path and the base commit (the merge base of the base
    branch and HEAD, fetched from ``origin`` when the remote exists), then render its PIP.

``check PLAN``
    Lint (item ids, dependencies, decisions, values, commands, planned test files), open every anchor, run
    every sweep, on a frozen plan compare the freeze digest, and apply the record rules of
    ``harness_lib.plan_record``: every item ``record`` moved carries a sealed record that matches the item
    (on a plan frozen without a record scheme, the legacy reference shape still passes). No git command
    judges an item: the recorded tree and commit are never compared with HEAD, so an amend, a squash, a
    rebase or a staged attach leaves the plan valid. Open decisions are listed as ``open:`` lines, not
    problems. Read-only.

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
    date, the record scheme and the digest of every field but the execution fields (the ``Mutable`` fields
    of ``harness_lib.plan_models``): the item status, evidence, verification references and record and the
    plan's completed, frozen and markdown sync fields. The scheme is ``sealed`` unless an item ``record``
    moved still carries the legacy shape, and a sealed plan stays sealed: a refreeze of a plan whose stored
    scheme is sealed, whose digest proves the scheme was deleted by hand, or whose copy at HEAD stores the
    sealed scheme (a hand edit that deletes the scheme and changes a digested field) judges its items as
    sealed. Only a plan whose deleted scheme was never committed can be judged as legacy again. A
    refreeze tolerates a record whose seal no longer matches (an item whose files or tests changed) and
    prints ``re-record after refreeze: <ITEM>`` for each; on a sealed plan a non-PENDING item without a
    record still refuses.

``lanes PLAN [--target BRANCH]``
    Print the ``parallel2`` plan JSON of a frozen plan's open items (waves from dependencies and file
    overlap), ready for ``parallel2.py plan -``. Refuses a plan that fails the digest or the record rules.

``record PLAN ITEM (--sha SHA | --staged | --start | --blocked REASON | --closed RATIONALE)``
    On a frozen plan whose digest holds (a broken seal, on this item or another, never blocks: recording
    again is the repair): ``--sha`` needs every dependency done with a valid record, ``SHA`` changing one of
    the item's files since the base, the item's files unchanged since ``SHA`` and the item's test nodes
    passing on a throwaway detached worktree at ``SHA``; ``SHA`` need not be reachable from HEAD.
    ``--staged`` applies the same rules to the index: its tree (``git write-tree``) against the base, the
    item's files without unstaged or untracked changes, and the tests on a throwaway worktree at a dangling
    commit of that tree on HEAD, which no ref keeps. Either marks the item COMPLETE with a sealed record of
    the tree, the commit when there was one, and the passed nodes. An item without test nodes is recorded on
    the tree alone: its commands are not run. The other flags record IN_PROGRESS, BLOCKED or
    CLOSED_NO_ACTION, sealed the same way. The PIP is rendered again.

``verify PLAN [--staged]``
    Run every COMPLETE item's test nodes on one throwaway detached worktree at HEAD (``--staged``: at a
    dangling commit of the index), one pytest run per item, and print ``<ITEM> pass`` or
    ``<ITEM> no tests`` for each. A failure names the item and the ``record`` call to make after the fix.
    A COMPLETE item without a valid record (no sealed record, a broken seal, or a non-legacy shape on a
    legacy plan) fails the run without a test run and names the ``record`` call. Writes nothing.

``PLAN`` is a plan id (``7`` or ``0007``) or a path to the plan file. ``--repo`` (default: the working
directory) names a directory inside the project. Usage::

    plan.py [--repo DIR] new TITLE [--spec PATH] [--base BRANCH] [--no-fetch]
    plan.py [--repo DIR] check PLAN
    plan.py [--repo DIR] render PLAN
    plan.py [--repo DIR] red PLAN
    plan.py [--repo DIR] freeze PLAN [--refreeze]
    plan.py [--repo DIR] lanes PLAN [--target BRANCH]
    plan.py [--repo DIR] record PLAN ITEM (--sha SHA | --staged | --start | --blocked REASON
                                           | --closed RATIONALE)
    plan.py [--repo DIR] verify PLAN [--staged]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))


def _pydantic_missing() -> bool:
    """True when pydantic 2 does not import: the plan models need it."""
    try:
        import pydantic
    except ImportError:
        return True
    return not hasattr(pydantic, "model_validator")


if _pydantic_missing():
    print("problem: pydantic>=2 is not installed; plan needs it (pip install 'pydantic>=2')", file=sys.stderr)
    sys.exit(1)

from harness_lib import parallel_lanes as pl  # noqa: E402
from harness_lib import plan_checks as pc  # noqa: E402
from harness_lib import plan_doc as pd  # noqa: E402
from harness_lib import plan_lanes as plx  # noqa: E402
from harness_lib import plan_models as pm  # noqa: E402
from harness_lib import plan_record as prc  # noqa: E402
from harness_lib import plan_red as pr  # noqa: E402
from harness_lib.branch_capture import (CaptureError, current_branch, git, git_out,  # noqa: E402
                                        resolve_merge_base, snapshot_commit)
from harness_lib.config import ConfigError, active, activate, load_config  # noqa: E402
from harness_lib.plan_enums import (DONE, ItemStatus, OutcomeKind, RecordProblemKind,  # noqa: E402
                                    RecordScheme, RecordSource, VerifyKind)
from harness_lib.plan_render import render_pip  # noqa: E402
from harness_lib.project import plugin_root, project_root  # noqa: E402

PROBLEMS = (pd.PlanError, pl.PlanError, CaptureError, ConfigError)
# The fixed identity of the dangling index snapshots ``record --staged`` and ``verify --staged`` test on.
SNAPSHOT_IDENTITY = {
    "GIT_AUTHOR_NAME": "plan-record", "GIT_AUTHOR_EMAIL": "plan-record@localhost",
    "GIT_COMMITTER_NAME": "plan-record", "GIT_COMMITTER_EMAIL": "plan-record@localhost",
}


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


def write_pip(plan_file: Path, plan: pm.ActionPlan) -> Path:
    target = pd.pip_path(plan_file)
    target.write_text(render_pip(plan, plan_file.name), encoding="utf-8")
    return target


def save(plan_file: Path, plan: pm.ActionPlan) -> Path:
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
    raw = skeleton(plan_id, spec, base, base_commit, current_branch(repo), rel(repo, pd.pip_path(plan_file)))
    pip = save(plan_file, pd.validate_plan(raw))
    tests = rel(repo, pd.planned_tests_dir(folder, plan_id))
    lib = plugin_root().as_posix() + "/lib"
    hpy = plugin_root().as_posix() + "/scripts/hpy"
    print("\n".join([f"new [done] | plan {plan_id} | base {base} @ {base_commit[:7]}",
                     f"plan:  {rel(repo, plan_file)}", f"pip:   {rel(repo, pip)}",
                     f"tests: {tests}/<repo-relative path>",
                     f"author: PYTHONPATH=\"{lib}\" sh \"{hpy}\" - <<'EOF'  "
                     f"(from harness_lib import plan_api; plan = plan_api.load(\"{plan_id}\"))",
                     f"next: fill decisions, items, anchors and sweeps; then plan.py check {plan_id}"]))
    return 0


# --- check ------------------------------------------------------------------------------------------------

def digest_problems(plan: pm.ActionPlan) -> List[str]:
    """The freeze digest, under the plan's stored record scheme, no longer matches the plan."""
    frozen = plan.frozen
    if frozen is None or frozen.digest == pd.frozen_digest(plan, frozen.records):
        return []
    return ["plan changed after freeze (a field outside the item status, evidence, verification "
            "references and record and the completed, frozen and markdown sync fields); "
            "restore it, or rerun freeze --refreeze"]


def claims_rev(plan: pm.ActionPlan) -> Optional[str]:
    """The base commit once an item is done, else None (the working tree).

    Anchors and sweeps describe the code before the work; once a done item has changed that code, they hold
    only at the base, so a refreeze in mid-plan checks them there.
    """
    return (plan.base_commit or None) if any(i.status in DONE for i in plan.items) else None


def claim_problems(repo: Path, plan: pm.ActionPlan) -> List[str]:
    """The lint, anchor and sweep checks of a plan that loaded: loading already validated its shape."""
    rev = claims_rev(plan)
    return (pc.lint_problems(plan, repo, plans_dir()) + pc.anchor_problems(plan, repo, rev)
            + pc.sweep_problems(plan, repo, active().artifacts.plans, rev))


def all_problems(repo: Path, plan: pm.ActionPlan) -> List[str]:
    """Every check of a plan that loaded: the claims, the freeze digest and the record rules."""
    return claim_problems(repo, plan) + digest_problems(plan) + prc.record_lines(plan)


def check_summary(plan: pm.ActionPlan) -> str:
    anchors = sum(1 for _ in pc.anchors_of(plan))
    opened = pc.open_decisions(plan)
    rev = claims_rev(plan)
    where = "" if rev is None else f" | anchors and sweeps at base {rev[:7]}"
    return (f"check [ok] | plan {plan.plan_id} | {len(plan.items)} items, {anchors} anchors, "
            f"{len(plan.sweeps)} sweeps | open decisions: {len(opened)}{where}")


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

def planned_nodes(plan: pm.ActionPlan) -> int:
    return sum(len(item.tests) for item in plx.open_items(plan))


def red_results(repo: Path, plan: pm.ActionPlan) -> List[pr.RedResult]:
    """Run the open items' test nodes on a throwaway worktree at HEAD with the planned files laid over it."""
    if not planned_nodes(plan):
        return []
    head = git_out(repo, "rev-parse", "HEAD").strip()
    with pr.throwaway_tree(repo, head, active().resolve_worktree_root()) as tree:
        pr.overlay(pr.test_sources(plan, plans_dir()), tree)
        return pr.run_red(plan, tree, sys.executable)


def red_problems(repo: Path, plan: pm.ActionPlan) -> Tuple[List[pr.RedResult], List[str]]:
    results = red_results(repo, plan)
    return results, [f"red: {p}" for p in pr.red_problems(results)]


def cmd_red(repo: Path, args: argparse.Namespace) -> int:
    plan = pd.load_plan(locate(repo, args.plan))
    results, problems = red_problems(repo, plan)
    if problems:
        raise pd.PlanError(problems)
    head = f"red [ok] | plan {plan.plan_id}"
    if not results:
        print(f"{head} | no planned test nodes in open items")
        return 0
    rows = [f"{r.item} {r.node}: {r.got} (planned {r.expected})" for r in results]
    print("\n".join([f"{head} | {len(results)} nodes fail as planned", *rows]))
    return 0


# --- freeze -----------------------------------------------------------------------------------------------

def unproven_items(plan: pm.ActionPlan) -> List[str]:
    return [f"{i.id} has no test and no command: nothing proves it" for i in plan.items
            if i.status not in DONE and not i.tests and not i.commands]


def started_items(plan: pm.ActionPlan) -> List[str]:
    """On a plan never frozen, one line per item not PENDING: only ``record`` sets the other states."""
    if plan.frozen is not None:
        return []
    return [f"{i.id} is {i.status}: a first freeze needs every item PENDING; "
            "record sets the rest" for i in plan.items if i.status != ItemStatus.PENDING]


def base_claim_problems(repo: Path, plan: pm.ActionPlan) -> List[str]:
    """Anchors and sweeps that hold in the tree but not at the base, while no item is done.

    Once an item is done, ``check`` reads them at the base (``claims_rev``), so a freeze before that point
    makes sure they hold there too: a branch with commits from before ``new`` can move the anchored code.
    """
    base = plan.base_commit
    if not base or claims_rev(plan) is not None:
        return []
    found = (pc.anchor_problems(plan, repo, base)
             + pc.sweep_problems(plan, repo, active().artifacts.plans, base))
    return [f"at base {base[:7]}: {p}" for p in found]


def record_split(plan: pm.ActionPlan, refreeze: bool) -> Tuple[List[str], List[str]]:
    """The record problems a freeze refuses, and the items whose broken seal a refreeze tolerates."""
    found = [(p, refreeze and p.kind == RecordProblemKind.seal) for p in prc.record_problems(plan)]
    refused = [str(p) for p, tolerated in found if not tolerated]
    return refused, [p.item for p, tolerated in found if tolerated]


def freeze_problems(repo: Path, plan: pm.ActionPlan, refreeze: bool) -> Tuple[List[str], List[str]]:
    """The problems that refuse a freeze, and the items a refreeze leaves to record again.

    The freeze digest is not checked: a first freeze has none, and a refreeze replaces it.
    """
    frozen = plan.frozen
    if frozen is not None and not refreeze:
        return [f"plan {plan.plan_id} is already frozen ({frozen.date}); pass --refreeze"], []
    refused, rerecord = record_split(plan, refreeze)
    problems = claim_problems(repo, plan) + refused + base_claim_problems(repo, plan)
    problems += [f"decision {d} is open: {q}" for d, q in (o.split(": ", 1) for o in pc.open_decisions(plan))]
    problems += started_items(plan) + unproven_items(plan)
    return problems + ([] if plan.items else ["the plan has no items"]), rerecord


def new_frozen(repo: Path, plan: pm.ActionPlan, records: Optional[RecordScheme]) -> pm.Frozen:
    """The freeze record at HEAD under the record scheme ``records``."""
    head = git_out(repo, "rev-parse", "HEAD").strip()
    tree = git_out(repo, "rev-parse", "HEAD^{tree}").strip()
    return pm.Frozen.at(head, tree, today(), pd.frozen_digest(plan, records), records)


def committed_scheme(repo: Path, plan_file: Path) -> Optional[str]:
    """The record scheme the plan's copy at HEAD stores; None when HEAD holds no frozen copy of the plan."""
    name = git(repo, "ls-files", "--full-name", "--", str(plan_file.resolve())).stdout.strip()
    done = git(repo, "show", f"HEAD:{name}") if name else None
    if done is None or done.returncode != 0:
        return None
    try:
        frozen = json.loads(done.stdout).get("frozen")
    except (ValueError, AttributeError):
        return None
    return frozen.get("records") if isinstance(frozen, dict) else None


def stays_sealed(repo: Path, plan_file: Path, plan: pm.ActionPlan) -> bool:
    """The plan keeps the sealed scheme: it stores it, its digest proves it, or its copy at HEAD stores it.

    The committed copy closes the path the digest cannot: a hand edit that deletes the scheme and changes
    a digested field in one go, which a refreeze would otherwise judge as legacy.
    """
    if plan.frozen is None:
        return False
    return prc.keeps_sealed(plan) or committed_scheme(repo, plan_file) == RecordScheme.sealed


def cmd_freeze(repo: Path, args: argparse.Namespace) -> int:
    plan_file = locate(repo, args.plan)
    plan = pd.load_plan(plan_file)
    if stays_sealed(repo, plan_file, plan):
        # A sealed plan stays sealed: the record rules judge its items as sealed, and the scheme is kept.
        plan.frozen = plan.frozen.model_copy(update={"records": RecordScheme.sealed})
    problems, rerecord = freeze_problems(repo, plan, args.refreeze)
    if problems:
        raise pd.PlanError(problems)
    problems = red_problems(repo, plan)[1]
    if problems:
        raise pd.PlanError(problems)
    plan.frozen = new_frozen(repo, plan, prc.scheme_for(plan))
    save(plan_file, plan)
    print("\n".join([f"freeze [done] | plan {plan.plan_id} | at {plan.frozen.commit[:7]} | "
                     f"{len(plan.items)} items", *(f"re-record after refreeze: {i}" for i in rerecord)]))
    return 0


# --- record -----------------------------------------------------------------------------------------------

def require_frozen(plan: pm.ActionPlan) -> None:
    """The gate of ``record``: a frozen plan whose digest holds. A broken seal never blocks a record."""
    if plan.frozen is None:
        raise pd.PlanError([f"plan {plan.plan_id} is not frozen; run freeze first"])
    problems = digest_problems(plan)
    if problems:
        raise pd.PlanError(problems)


def require_valid(plan: pm.ActionPlan) -> None:
    """The gate of ``lanes``: ``require_frozen`` and the record rules (``lanes`` writes nothing)."""
    require_frozen(plan)
    problems = prc.record_lines(plan)
    if problems:
        raise pd.PlanError(problems)


def dependency_problems(plan: pm.ActionPlan, item: pm.ActionItem) -> List[str]:
    """One line per dependency not done, or done without a record that proves it."""
    out = []
    for dep in item.dependencies or []:
        upstream = pd.item_by_id(plan, dep)
        done = upstream.status in DONE
        if done and prc.record_holds(plan, upstream):
            continue
        command = prc.record_command(plan.plan_id, dep, upstream.status)
        fix = f" without a valid record; {command}" if done else ""
        out.append(f"{item.id} depends on {dep}, which is {upstream.status}{fix}")
    return out


def item_paths(item: pm.ActionItem) -> List[str]:
    nodes = [plx.node_file(t.node) for t in item.tests]
    return list(dict.fromkeys([*item.files, *nodes]))


def resolve_commit(repo: Path, sha: str) -> str:
    """The full SHA of the commit ``sha`` names; it need not be reachable from HEAD."""
    done = git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    if done.returncode != 0:
        raise pd.PlanError([f"{sha} does not name a commit"])
    return done.stdout.strip()


def index_provenance(repo: Path) -> pm.Provenance:
    """The staged index as recorded code: its tree (``git write-tree``), no commit."""
    return pm.Provenance(source=RecordSource.staged, tree=git_out(repo, "write-tree").strip())


def commit_provenance(repo: Path, sha: str) -> pm.Provenance:
    """The commit ``sha`` (full) and its tree as recorded code."""
    tree = git_out(repo, "rev-parse", f"{sha}^{{tree}}").strip()
    return pm.Provenance(source=RecordSource.commit, tree=tree, commit=sha)


def provenance_of(repo: Path, args: argparse.Namespace) -> pm.Provenance:
    """The code a COMPLETE record names: the ``--sha`` commit and its tree, or the index tree."""
    return index_provenance(repo) if args.staged else commit_provenance(repo, resolve_commit(repo, args.sha))


def testable_commit(repo: Path, prov: pm.Provenance) -> str:
    """The commit a throwaway worktree checks out for ``prov``: its own, or a dangling tree snapshot."""
    if prov.source == RecordSource.commit and prov.commit:
        return prov.commit
    head = git_out(repo, "rev-parse", "HEAD").strip()
    return snapshot_commit(repo, prov.tree, head, "plan.py index snapshot", SNAPSHOT_IDENTITY)


def worktree_problems(repo: Path, item_id: str, paths: List[str], prov: pm.Provenance) -> List[str]:
    """The item's paths in the working tree differ from the commit (``--sha``) or the index (``--staged``)."""
    by_commit = prov.source == RecordSource.commit
    against = [prov.tree] if by_commit else []
    differ = git_out(repo, "diff", "--name-only", *against, "--", *paths).split()
    differ += git_out(repo, "ls-files", "--others", "--exclude-standard", "--", *paths).split()
    if not differ:
        return []
    listed = ", ".join(sorted(set(differ)))
    if by_commit:
        return [f"{item_id} files differ from {prov.where} in the working tree: {listed}; "
                "commit them and record that commit"]
    return [f"{item_id} files differ from the index in the working tree: {listed}; "
            "stage them and record again"]


def commit_problems(repo: Path, plan: pm.ActionPlan, item: pm.ActionItem, prov: pm.Provenance) -> List[str]:
    """The recorded tree changes one of the item's files since the base; the working tree still matches it."""
    paths, item_id = item_paths(item), item.id
    if not paths:
        return []
    changed = git_out(repo, "diff", "--name-only", plan.base_commit, prov.tree, "--", *paths).split()
    out = [] if changed else [f"{item_id}: no file of the item changed between the base and {prov.where}"]
    return out + worktree_problems(repo, item_id, paths, prov)


def tests_at(repo: Path, sha: str, cmd: List[str]) -> "subprocess.CompletedProcess[str]":
    """Run ``cmd`` on a throwaway detached worktree at ``sha``, so the tests see that commit alone."""
    with pr.throwaway_tree(repo, sha, active().resolve_worktree_root()) as tree:
        return pr.run_pytest(cmd, tree)


def pytest_argv(nodes: List[str]) -> List[str]:
    """The pytest command line of ``nodes`` under this interpreter, with the red run's pinned options."""
    return [sys.executable, *pr.PYTEST_ARGS, *nodes]


def tail(done: "subprocess.CompletedProcess[str]") -> str:
    """The last three lines of a pytest run's output, joined on one line."""
    return " | ".join(done.stdout.strip().splitlines()[-3:])


def run_tests(repo: Path, item: pm.ActionItem, prov: pm.Provenance) -> Optional[pm.PassedTests]:
    """The item's nodes after they passed on the recorded code; a problem when they fail."""
    nodes = [t.node for t in item.tests]
    if not nodes:
        return None
    argv = pytest_argv(nodes)
    done = tests_at(repo, testable_commit(repo, prov), argv)
    if done.returncode != 0:
        raise pd.PlanError([f"{item.id} tests failed at {prov.where}: {tail(done)}"])
    return pm.PassedTests.of(nodes, argv)


def complete(repo: Path, plan: pm.ActionPlan, item: pm.ActionItem, args: argparse.Namespace) -> pm.Completed:
    """The Completed outcome of ``--sha`` or ``--staged`` once every rule holds."""
    problems = dependency_problems(plan, item)
    if problems:
        raise pd.PlanError(problems)
    prov = provenance_of(repo, args)
    problems = commit_problems(repo, plan, item, prov)
    if problems:
        raise pd.PlanError(problems)
    return pm.Completed.of(prov, run_tests(repo, item, prov))


def reject_empty(flag: str, value: Optional[str]) -> None:
    if value is not None and not value.strip():
        raise pd.PlanError([f"--{flag} needs a non-empty value (an unset shell variable?)"])


def apply_record(repo: Path, plan: pm.ActionPlan, item: pm.ActionItem,
                 args: argparse.Namespace) -> pm.Outcome:
    """The outcome the flags ask for; ``--sha`` and ``--staged`` first prove it."""
    for flag, value in (("sha", args.sha), ("blocked", args.blocked), ("closed", args.closed)):
        reject_empty(flag, value)
    if args.sha is not None or args.staged:
        return complete(repo, plan, item, args)
    if args.start:
        return pm.Started(kind=OutcomeKind.started)
    if args.blocked is not None:
        return pm.Blocked(kind=OutcomeKind.blocked, reason=args.blocked)
    return pm.Closed(kind=OutcomeKind.closed, rationale=args.closed)


def cmd_record(repo: Path, args: argparse.Namespace) -> int:
    plan_file = locate(repo, args.plan)
    plan = pd.load_plan(plan_file)
    require_frozen(plan)
    item = pd.item_by_id(plan, args.item)
    prc.stamp(plan, item, apply_record(repo, plan, item, args), today())
    if all(i.status in DONE for i in plan.items):
        plan.completed = today()
    else:
        plan.completed = None
        plan.model_fields_set.discard("completed")
    save(plan_file, plan)
    left = [i.id for i in plan.items if i.status not in DONE]
    print(f"record [done] | {item.id} {item.status} | open: {', '.join(left) or 'none'}")
    return 0


# --- lanes ------------------------------------------------------------------------------------------------

def cmd_lanes(repo: Path, args: argparse.Namespace) -> int:
    plan = pd.load_plan(locate(repo, args.plan))
    require_valid(plan)
    target = args.target or current_branch(repo)
    if not target:
        raise CaptureError(["detached HEAD: check out the target branch or pass --target"])
    print(json.dumps(plx.lanes_plan(plan, target), indent=2))
    return 0


# --- verify -----------------------------------------------------------------------------------------------

def verify_target(repo: Path, staged: bool) -> pm.Provenance:
    """The code ``verify`` runs on: the staged index, or HEAD and its tree."""
    if staged:
        return index_provenance(repo)
    return commit_provenance(repo, git_out(repo, "rev-parse", "HEAD").strip())


def verify_where(prov: pm.Provenance) -> str:
    """How verify lines name the code: ``HEAD <h7>``, or the index and its short tree."""
    return f"HEAD {prov.where}" if prov.source == RecordSource.commit else prov.where


def unrun_result(plan: pm.ActionPlan, item: pm.ActionItem) -> Optional[prc.VerifyResult]:
    """The result of a COMPLETE item verify does not run: no valid record, or a record without tests."""
    if not prc.record_holds(plan, item):
        return prc.VerifyResult(item=item.id, kind=VerifyKind.unrecorded,
                                detail=prc.record_command(plan.plan_id, item.id, item.status))
    if not prc.recorded_nodes(item):
        return prc.VerifyResult(item=item.id, kind=VerifyKind.no_tests)
    return None


def run_result(plan: pm.ActionPlan, item: pm.ActionItem, tree: Path, where: str) -> prc.VerifyResult:
    """Run the item's recorded nodes in ``tree``: pass, or fail with the tail and the repair."""
    done = pr.run_pytest(pytest_argv(prc.recorded_nodes(item)), tree)
    if done.returncode == 0:
        return prc.VerifyResult(item=item.id, kind=VerifyKind.pass_)
    command = prc.record_command(plan.plan_id, item.id, item.status, again=True)
    detail = f"{where}: {tail(done)}; fix the code, then {command}"
    return prc.VerifyResult(item=item.id, kind=VerifyKind.fail, detail=detail)


def verify_items(repo: Path, plan: pm.ActionPlan, prov: pm.Provenance) -> List[prc.VerifyResult]:
    """One result per COMPLETE item, in plan order; the runs share one throwaway worktree, made on demand."""
    items = [i for i in plan.items if i.status == ItemStatus.COMPLETE]
    known = {i.id: unrun_result(plan, i) for i in items}
    if all(result is not None for result in known.values()):
        return [result for result in known.values() if result is not None]
    where = verify_where(prov)
    with pr.throwaway_tree(repo, testable_commit(repo, prov), active().resolve_worktree_root()) as tree:
        return [run_result(plan, i, tree, where) if known[i.id] is None else known[i.id] for i in items]


def cmd_verify(repo: Path, args: argparse.Namespace) -> int:
    plan = pd.load_plan(locate(repo, args.plan))
    prov = verify_target(repo, args.staged)
    results = verify_items(repo, plan, prov)
    lines = [str(r) for r in results if not r.failed]
    failed = [str(r) for r in results if r.failed]
    if failed:
        if lines:
            print("\n".join(lines))
        raise pd.PlanError(failed)
    passed = sum(1 for r in results if r.kind == VerifyKind.pass_)
    head = f"verify [ok] | plan {plan.plan_id} | {passed} item(s) pass at {verify_where(prov)}"
    print("\n".join([head, *lines]))
    return 0


# --- command line -----------------------------------------------------------------------------------------

def _record_parser(sub: Any) -> None:
    record = sub.add_parser("record", help="Record an item's status with its evidence.")
    record.add_argument("plan", help="Plan id or plan file.")
    record.add_argument("item", help="Item id, such as TASK-1.")
    mode = record.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sha", help="Commit that implements the item; marks it COMPLETE.")
    mode.add_argument("--staged", action="store_true",
                      help="Record the staged index (uncommitted) as the item's code; marks it COMPLETE.")
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
    verify = sub.add_parser("verify", help="Rerun the COMPLETE items' tests at HEAD; writes nothing.")
    verify.add_argument("plan", help="Plan id or plan file.")
    verify.add_argument("--staged", action="store_true", help="Run them on the staged index instead.")
    return parser


COMMANDS: Dict[str, Callable[[Path, argparse.Namespace], int]] = {
    "new": cmd_new, "check": cmd_check, "render": cmd_render, "red": cmd_red, "freeze": cmd_freeze,
    "lanes": cmd_lanes, "record": cmd_record, "verify": cmd_verify,
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
