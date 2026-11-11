"""plan driver: start a plan, check its claims against the tree, freeze it, record each item with evidence.

The mechanical half of the ``write-plan`` skill. A plan is an ActionPlan JSON under the project's
``artifacts.plans`` (``<plan_id>_<Title>_ActionPlan.json``) with its PIP rendered beside it and the test files
it plans under ``<plan_id>/tests/<repo-relative path>``. Every defect is one ``problem: ...`` line on stderr
with exit 1; success exits 0 and writes nothing on a refusal. Every command validates the plan on load and
refuses an invalid one with ``schema:`` lines.

``new TITLE [--spec PATH] [--base BRANCH] [--no-fetch]``
    Write an empty plan with the next plan id, the spec path and the base commit (the merge base of the base
    branch and HEAD, fetched from ``origin`` when the remote exists), then render its PIP. A plan bound for
    the receipts scheme (``plan_render_html.uses_html``) gets the HTML page, named as its ``documentation``.

``check PLAN``
    Lint (item ids, dependencies, decisions, values, commands, planned test files), open every anchor, run
    every sweep, on a frozen plan compare the freeze digest, and apply the record rules of
    ``harness_lib.plan_record``: every item ``record`` moved carries a sealed record that matches the item
    (on a plan frozen without a record scheme, the legacy reference shape still passes). On a receipts plan
    the item states come from its record book (``plan_receipts.book_for``): its receipt problems replace
    the record rules, and the DesignEvolution catalog's ``schema:`` lines and plan problems are added. No
    git command judges an item: the recorded tree and commit are never compared with HEAD, so an amend, a
    squash, a rebase or a staged attach leaves the plan valid. Open decisions are listed as ``open:``
    lines, not problems. Read-only.

``render PLAN``
    Write the PIP from the plan JSON. On a frozen receipts plan, rebuild ``live.js`` and write the HTML page
    only when it is missing: ``freeze``, ``--refreeze`` and ``plan_api.write`` write an existing page. A
    plan not frozen yet has no ``live.js``; its page says the live parts appear after ``freeze``, and one
    whose ``documentation`` still names the markdown PIP keeps that PIP until the first freeze.

``red PLAN``
    Copy the planned test files onto a throwaway detached worktree at HEAD, run every open item's test
    nodes there (one pytest process per node) and require each to fail with its planned exception. The
    runs import the worktree's code: it is the working directory, and a src-layout ``src/`` goes first on
    ``PYTHONPATH``, ahead of an editable install of the checkout. The worktree is removed afterwards; the
    checkout is never written. A receipts plan's open items are read from its receipts.

``freeze PLAN [--refreeze]``
    Refuse while ``check`` has a problem, a decision is open, an open item has neither a test nor a command,
    an item is not PENDING on a first freeze, or ``red`` has a problem; otherwise record HEAD, its tree, the
    date, the record scheme and the digest. A first freeze (every item PENDING without a record), the path
    every new plan takes, stores ``plan_record.FIRST_SCHEME``, receipts: the digest covers every field but
    ``frozen``, a ``documentation`` naming the markdown PIP moves to the HTML page (the markdown PIP is
    deleted), and the freeze writes the page and ``live.js``. A receipts plan keeps the scheme on a
    refreeze (stored, proven by the digest, or stored at HEAD; checked before the sealed rule), reads its
    item states from its receipts, tolerates a receipt whose seal the refreeze broke (printing
    ``re-record after refreeze: <ITEM>``, as below), refuses every other
    receipt problem, and saves the plan JSON itself, never the status view.

    Plans frozen before receipts keep their own rules. Their digest covers every field but the execution
    fields (the ``Mutable`` fields of ``harness_lib.plan_models``): the item status, evidence, verification
    references and record and the plan's completed, frozen and markdown sync fields. Their scheme is
    ``sealed`` unless an item ``record`` moved still carries the legacy shape, and a sealed plan stays
    sealed: a refreeze of a plan whose stored scheme is sealed, whose digest proves the scheme was deleted
    by hand, or whose copy at HEAD stores the sealed scheme (a hand edit that deletes the scheme and changes
    a digested field) judges its items as sealed. Only a plan whose deleted scheme was never committed can
    be judged as legacy again. A refreeze tolerates a record whose seal no longer matches (an item whose
    files or tests changed) and prints ``re-record after refreeze: <ITEM>`` for each; on a sealed plan a
    non-PENDING item without a record still refuses.

``lanes PLAN [--target BRANCH]``
    Print the ``parallel2`` plan JSON of a frozen plan's open items (waves from dependencies and file
    overlap), ready for ``parallel2.py plan -``. Refuses a plan that fails the digest or the record rules.
    The open items and the record problems come from the plan's record book (its receipts on a receipts
    plan).

``record PLAN ITEM (--sha SHA | --staged | --start | --blocked REASON | --closed RATIONALE)
[--also PATH] [--substitute PLANNED=NODE] [--cite ID]``
    On a frozen plan whose digest holds (a broken seal, on this item or another, never blocks: recording
    again is the repair): ``--sha`` needs every dependency done with a valid record, ``SHA`` changing one of
    the item's files since the base, the item's files unchanged since ``SHA`` and the item's test nodes
    passing on a throwaway detached worktree at ``SHA``; ``SHA`` is any revision (a tag or a branch is
    resolved to its full SHA) and need not be reachable from HEAD.
    ``--staged`` applies the same rules to the index: its tree (``git write-tree``) against the base, the
    item's files without unstaged or untracked changes, and the tests on a throwaway worktree at a dangling
    commit of that tree on HEAD, which no ref keeps. Either marks the item COMPLETE with a sealed record of
    the tree, the commit when there was one, and the passed nodes. An item without test nodes is recorded on
    the tree alone: its commands are not run. The other flags record IN_PROGRESS, BLOCKED or
    CLOSED_NO_ACTION, sealed the same way. The PIP is rendered again.

    On a receipts plan the dependency gate reads the receipts, and the outcome goes to a sealed receipt
    (``<plans>/<id>/receipts/<ITEM>.json``) and ``live.js``; the plan JSON and its PIP are never written. A
    revision that is not a prefix of its SHA is kept as the receipt's ``ref``. Deviations, repeatable and
    read in order (D1): ``--also PATH`` (a file the plan does not list) and ``--substitute PLANNED=NODE``
    (``NODE`` runs in place of the planned node ``PLANNED``); each ``--cite ID`` binds every uncited
    deviation before it to the DesignChange ``ID``, which must exist in the plan's catalog and list the
    item; the receipt keeps that change's digest (D8). A deviation without a ``--cite`` after it is refused.
    Extra files and substituted node files join the item's paths for the base-diff and clean-path rules,
    and the substitutes are the nodes run. The deviation flags need ``--sha`` or ``--staged`` and a
    receipts plan.

``verify PLAN [--staged]``
    Run every COMPLETE item's test nodes on one throwaway detached worktree at HEAD (``--staged``: at a
    dangling commit of the index), one pytest run per item, and print ``<ITEM> pass`` or
    ``<ITEM> no tests`` for each. A failure names the item and the ``record`` call to make after the fix.
    A COMPLETE item without a valid record (no sealed record, a broken seal, or a non-legacy shape on a
    legacy plan) fails the run without a test run and names the ``record`` call. Writes nothing. On a
    receipts plan the COMPLETE items, their nodes (substitutes included) and a broken seal come from the
    receipts.

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
                                           [--also PATH] [--substitute PLANNED=NODE] [--cite ID] ...
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


from harness_lib.doctor import missing_pydantic  # noqa: E402

_MISSING = missing_pydantic()
if _MISSING is not None:
    print(f"problem: {_MISSING} is not installed; plan needs it (pip install '{_MISSING}')", file=sys.stderr)
    sys.exit(1)

from pydantic import ValidationError  # noqa: E402

from harness_lib import evolution_doc as ed  # noqa: E402
from harness_lib import parallel_lanes as pl  # noqa: E402
from harness_lib import plan_checks as pc  # noqa: E402
from harness_lib import plan_doc as pd  # noqa: E402
from harness_lib import plan_lanes as plx  # noqa: E402
from harness_lib import plan_live  # noqa: E402
from harness_lib import plan_models as pm  # noqa: E402
from harness_lib import plan_receipts as prt  # noqa: E402
from harness_lib import plan_record as prc  # noqa: E402
from harness_lib import plan_red as pr  # noqa: E402
from harness_lib import plan_render_html as prh  # noqa: E402
from harness_lib.branch_capture import (CaptureError, current_branch, git, git_out,  # noqa: E402
                                        resolve_merge_base, snapshot_commit)
from harness_lib.config import ConfigError, active, activate, load_config  # noqa: E402
from harness_lib.plan_enums import (DONE, ItemStatus, OutcomeKind, RecordProblemKind,  # noqa: E402
                                    RecordScheme, RecordSource, VerifyKind)
from harness_lib.project import plugin_root, project_root  # noqa: E402
from harness_lib.receipt_models import Deviations, Receipt, substituted_nodes  # noqa: E402

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


def save(plan_file: Path, plan: pm.ActionPlan) -> Path:
    """Save the plan JSON and write its PIP (``plan_render_html.write_pip``); the PIP's path."""
    pd.save_plan(plan_file, plan)
    return prh.write_pip(plan_file, plan)


def book_of(plan_file: Path, plan: pm.ActionPlan) -> prt.RecordBook:
    """The plan's record book (D10): its receipts on a receipts plan, its own sealed records otherwise.

    Receipts are read beside ``plan_file``, the folder ``record`` writes them to, so a plan addressed by a
    path outside ``artifacts.plans`` reads and writes one receipts folder.
    """
    return prt.book_for(plan_file.parent, plan)


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
    plan = pd.validate_plan(raw)
    if prh.uses_html(plan):
        plan.documentation = rel(repo, pd.pip_html_path(plan_file))
    pip = save(plan_file, plan)
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
    if frozen.records == RecordScheme.receipts:
        return ["plan changed after freeze (any field but frozen: a receipts plan records its items in "
                "receipt files); restore it, or rerun freeze --refreeze"]
    return ["plan changed after freeze (a field outside the item status, evidence, verification "
            "references and record and the completed, frozen and markdown sync fields); "
            "restore it, or rerun freeze --refreeze"]


def evolution_problems(folder: Path, plan: pm.ActionPlan) -> List[str]:
    """On a receipts plan, the DesignEvolution catalog's ``schema:`` lines, else its ``plan_problems``;
    the catalog is read under ``folder``, the plan file's folder ``evolution_api`` writes it to."""
    if not prt.uses_receipts(plan):
        return []
    try:
        evolution = ed.load_evolution(ed.catalog_path(folder, plan.plan_id))
    except pd.PlanError as exc:
        return exc.problems
    return [] if evolution is None else ed.plan_problems(evolution, plan)


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


def all_problems(repo: Path, plan_file: Path, plan: pm.ActionPlan, book: prt.RecordBook) -> List[str]:
    """Every check of a plan that loaded: the claims (on the book's status view), the freeze digest, the
    DesignEvolution catalog of a receipts plan and the book's record problems."""
    return (claim_problems(repo, book.view()) + digest_problems(plan)
            + evolution_problems(plan_file.parent, plan) + book.problems())


def check_summary(plan: pm.ActionPlan, view: pm.ActionPlan) -> str:
    anchors = sum(1 for _ in pc.anchors_of(plan))
    opened = pc.open_decisions(plan)
    rev = claims_rev(view)
    where = "" if rev is None else f" | anchors and sweeps at base {rev[:7]}"
    return (f"check [ok] | plan {plan.plan_id} | {len(plan.items)} items, {anchors} anchors, "
            f"{len(plan.sweeps)} sweeps | open decisions: {len(opened)}{where}")


def cmd_check(repo: Path, args: argparse.Namespace) -> int:
    plan_file = locate(repo, args.plan)
    plan = pd.load_plan(plan_file)
    book = book_of(plan_file, plan)
    problems = all_problems(repo, plan_file, plan, book)
    if problems:
        raise pd.PlanError(problems)
    print("\n".join([check_summary(plan, book.view()), *(f"open: {d}" for d in pc.open_decisions(plan))]))
    return 0


def cmd_render(repo: Path, args: argparse.Namespace) -> int:
    plan_file = locate(repo, args.plan)
    pip = prh.refresh_pip(plan_file, pd.load_plan(plan_file))
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
    plan_file = locate(repo, args.plan)
    plan = book_of(plan_file, pd.load_plan(plan_file)).view()
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


def receipt_split(book: prt.ReceiptBook, refreeze: bool) -> Tuple[List[str], List[str]]:
    """The receipt problems a freeze refuses, and the items whose receipt seal a refreeze tolerates.

    A tolerated receipt still has its citations checked; every other receipt problem refuses.
    """
    plan, found = book.plan, book.receipts
    broken = [i.id for i in plan.items if refreeze and i.id in found.receipts
              and not prt.receipt_holds(plan, found, i.id)]
    kept = prt.ReceiptSet(receipts={k: r for k, r in found.receipts.items() if k not in broken},
                          problems=found.problems)
    refused = prt.receipt_problems(plan, kept, book.evolution)
    for item_id in broken:
        refused += prt.citation_problems(book.evolution, item_id, found.receipts[item_id].deviations)
    return refused, broken


def record_split(plan: pm.ActionPlan, book: prt.RecordBook, refreeze: bool) -> Tuple[List[str], List[str]]:
    """The record problems a freeze refuses, and the items whose broken seal a refreeze tolerates."""
    if isinstance(book, prt.ReceiptBook):
        return receipt_split(book, refreeze)
    found = [(p, refreeze and p.kind == RecordProblemKind.seal) for p in prc.record_problems(plan)]
    refused = [str(p) for p, tolerated in found if not tolerated]
    return refused, [p.item for p, tolerated in found if tolerated]


def freeze_problems(repo: Path, plan: pm.ActionPlan, book: prt.RecordBook,
                    refreeze: bool) -> Tuple[List[str], List[str]]:
    """The problems that refuse a freeze, and the items a refreeze leaves to record again.

    The freeze digest is not checked: a first freeze has none, and a refreeze replaces it. The claims and the
    item states are read on the book's status view.
    """
    frozen = plan.frozen
    if frozen is not None and not refreeze:
        return [f"plan {plan.plan_id} is already frozen ({frozen.date}); pass --refreeze"], []
    view = book.view()
    refused, rerecord = record_split(plan, book, refreeze)
    problems = claim_problems(repo, view) + refused + base_claim_problems(repo, view)
    problems += [f"decision {d} is open: {q}" for d, q in (o.split(": ", 1) for o in pc.open_decisions(plan))]
    problems += started_items(view) + unproven_items(view)
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


def pin_scheme(repo: Path, plan_file: Path, plan: pm.ActionPlan) -> Optional[str]:
    """Pin the scheme a frozen plan keeps across a refreeze; the scheme its copy at HEAD stores.

    Receipts are checked first, then sealed: each is kept when the plan stores it, its digest proves a hand
    deleted it, or its copy at HEAD stores it. The committed copy closes the path the digest cannot: a hand
    edit that deletes the scheme and changes a digested field in one go, which a refreeze would otherwise
    judge as legacy. The record rules then judge the items under the pinned scheme.
    """
    if plan.frozen is None:
        return None
    committed = committed_scheme(repo, plan_file)
    if prc.keeps_receipts(plan, committed):
        kept = RecordScheme.receipts
    elif prc.keeps_sealed(plan) or committed == RecordScheme.sealed:
        kept = RecordScheme.sealed
    else:
        return committed
    plan.frozen = plan.frozen.model_copy(update={"records": kept})
    return committed


def move_documentation(repo: Path, plan_file: Path, plan: pm.ActionPlan) -> Optional[Path]:
    """Point a ``documentation`` that names this plan's markdown PIP at its HTML page; the markdown PIP
    to delete once the plan is saved, or None when the documentation names something else."""
    markdown = pd.pip_path(plan_file)
    if plan.documentation != rel(repo, markdown):
        return None
    plan.documentation = rel(repo, pd.pip_html_path(plan_file))
    return markdown


def store_freeze(repo: Path, plan_file: Path, plan: pm.ActionPlan, committed: Optional[str]) -> None:
    """Stamp the freeze record and save the raw plan with its PIP (the page and ``live.js`` on receipts).

    A first freeze that stores receipts first moves a markdown ``documentation`` to the HTML page, so the
    digest covers the new path, and deletes the superseded markdown PIP.
    """
    first = plan.frozen is None
    scheme = prc.scheme_for(plan, committed)
    moved = move_documentation(repo, plan_file, plan) if first and scheme == RecordScheme.receipts else None
    plan.frozen = new_frozen(repo, plan, scheme)
    save(plan_file, plan)
    if moved is not None and moved.exists():
        moved.unlink()


def cmd_freeze(repo: Path, args: argparse.Namespace) -> int:
    plan_file = locate(repo, args.plan)
    plan = pd.load_plan(plan_file)
    committed = pin_scheme(repo, plan_file, plan)
    book = book_of(plan_file, plan)
    problems, rerecord = freeze_problems(repo, plan, book, args.refreeze)
    if problems:
        raise pd.PlanError(problems)
    problems = red_problems(repo, book.view())[1]
    if problems:
        raise pd.PlanError(problems)
    store_freeze(repo, plan_file, plan, committed)
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


def require_valid(plan: pm.ActionPlan, book: prt.RecordBook) -> None:
    """The gate of ``lanes``: ``require_frozen`` and the book's record problems (``lanes`` writes nothing)."""
    require_frozen(plan)
    problems = book.problems()
    if problems:
        raise pd.PlanError(problems)


def dependency_problems(plan: pm.ActionPlan, book: prt.RecordBook, item: pm.ActionItem) -> List[str]:
    """One line per dependency not done in the book, or done without a record that proves it."""
    out = []
    for dep in item.dependencies or []:
        status = book.status(dep)
        done = status in DONE
        if done and book.holds(dep):
            continue
        command = prc.record_command(plan.plan_id, dep, status)
        fix = f" without a valid record; {command}" if done else ""
        out.append(f"{item.id} depends on {dep}, which is {status}{fix}")
    return out


def item_paths(item: pm.ActionItem) -> List[str]:
    nodes = [plx.node_file(t.node) for t in item.tests]
    return list(dict.fromkeys([*item.files, *nodes]))


def deviation_paths(item: pm.ActionItem, deviations: Deviations) -> List[str]:
    """The item's paths, then each extra file and the file of each substituted node."""
    extra = [entry.path for entry in deviations.extra_files]
    swapped = [plx.node_file(sub.node) for sub in deviations.substitutions]
    return list(dict.fromkeys([*item_paths(item), *extra, *swapped]))


def resolve_commit(repo: Path, sha: str) -> str:
    """The full SHA of the commit the revision ``sha`` names; it need not be reachable from HEAD."""
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


def commit_problems(repo: Path, plan: pm.ActionPlan, item_id: str, paths: List[str],
                    prov: pm.Provenance) -> List[str]:
    """The recorded tree changes one of ``paths`` since the base; the working tree still matches it there."""
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


def run_tests(repo: Path, item_id: str, nodes: List[str], prov: pm.Provenance) -> Optional[pm.PassedTests]:
    """``nodes`` after they passed on the recorded code; a problem when they fail."""
    if not nodes:
        return None
    argv = pytest_argv(nodes)
    done = tests_at(repo, testable_commit(repo, prov), argv)
    if done.returncode != 0:
        raise pd.PlanError([f"{item_id} tests failed at {prov.where}: {tail(done)}"])
    return pm.PassedTests.of(nodes, argv)


def revision_ref(revision: Optional[str], prov: pm.Provenance) -> Optional[str]:
    """``--sha`` as given when it is not a prefix of the commit it names (a tag, a branch, ``HEAD~1``)."""
    if revision is None or prov.commit is None or prov.commit.startswith(revision.strip().lower()):
        return None
    return revision


def complete(repo: Path, plan: pm.ActionPlan, book: prt.RecordBook, item: pm.ActionItem,
             args: argparse.Namespace, deviations: Deviations) -> Tuple[pm.Completed, Optional[str]]:
    """The Completed outcome of ``--sha`` or ``--staged`` once every rule holds, and the revision kept as
    ``ref``. Extra files and substituted node files join the item's paths; the substitutes are the nodes
    run."""
    problems = dependency_problems(plan, book, item)
    if problems:
        raise pd.PlanError(problems)
    prov = provenance_of(repo, args)
    problems = commit_problems(repo, plan, item.id, deviation_paths(item, deviations), prov)
    if problems:
        raise pd.PlanError(problems)
    tests = run_tests(repo, item.id, substituted_nodes(item, deviations), prov)
    return pm.Completed.of(prov, tests), revision_ref(args.sha, prov)


def reject_empty(flag: str, value: Optional[str]) -> None:
    if value is not None and not value.strip():
        raise pd.PlanError([f"--{flag} needs a non-empty value (an unset shell variable?)"])


def apply_record(repo: Path, plan: pm.ActionPlan, book: prt.RecordBook, item: pm.ActionItem,
                 args: argparse.Namespace, deviations: Deviations) -> Tuple[pm.Outcome, Optional[str]]:
    """The outcome the flags ask for and the ``ref`` to keep; ``--sha`` and ``--staged`` first prove it."""
    for flag, value in (("sha", args.sha), ("blocked", args.blocked), ("closed", args.closed)):
        reject_empty(flag, value)
    if args.sha is not None or args.staged:
        return complete(repo, plan, book, item, args, deviations)
    if args.start:
        return pm.Started(kind=OutcomeKind.started), None
    if args.blocked is not None:
        return pm.Blocked(kind=OutcomeKind.blocked, reason=args.blocked), None
    return pm.Closed(kind=OutcomeKind.closed, rationale=args.closed), None


# --- record: deviations (D1) ------------------------------------------------------------------------------

DEVIATION_FLAGS = ("--also", "--substitute", "--cite")
# Stands in for a cited change the catalog lacks; ``citation_problems`` reports the missing change first.
_NO_DIGEST = "0" * 64
Bound = Dict[str, List[Dict[str, str]]]


class _InOrder(argparse.Action):
    """Append ``(flag, value)`` to one shared list, so the deviation flags keep the order given."""

    def __call__(self, parser: argparse.ArgumentParser, namespace: argparse.Namespace, values: Any,
                 option_string: Optional[str] = None) -> None:
        given = list(getattr(namespace, self.dest, None) or [])
        given.append((option_string, values))
        setattr(namespace, self.dest, given)


def deviation_flag_problems(plan: pm.ActionPlan, args: argparse.Namespace) -> List[str]:
    """One line per deviation flag given without ``--sha`` or ``--staged``, or on a plan without receipts."""
    flags = list(dict.fromkeys(flag for flag, _ in args.deviations or []))
    out = []
    if args.sha is None and not args.staged:
        out += [f"{flag} needs --sha or --staged: only a COMPLETE record carries deviations"
                for flag in flags]
    if not prt.uses_receipts(plan):
        out += [f"{flag} needs a receipts plan; plan {plan.plan_id} keeps its records in the plan JSON"
                for flag in flags]
    return out


def one_deviation(item: pm.ActionItem, flag: str, value: str) -> Tuple[str, Dict[str, str]]:
    """The ``Deviations`` field and entry of one ``--also`` or ``--substitute`` value; raise on a bad one."""
    reject_empty(flag.lstrip("-"), value)
    if flag == "--also":
        return "extra_files", {"path": Path(value.strip()).as_posix()}
    pair = prt.split_substitution(value)
    if pair is None:
        raise pd.PlanError([f"--substitute {value} is not PLANNED=NODE (two pytest node ids)"])
    planned = [test.node for test in item.tests]
    if pair[0] not in planned:
        raise pd.PlanError([f"--substitute {value}: {pair[0]} is not a planned test node of {item.id} "
                            f"(planned: {', '.join(planned) or 'none'})"])
    return "substitutions", {"planned": pair[0], "node": pair[1]}


def uncited_line(item_id: str, key: str, entry: Dict[str, str]) -> str:
    """The refusal of one deviation no ``--cite`` follows, naming its path or node."""
    what = entry["path"] if key == "extra_files" else f"{entry['planned']}={entry['node']}"
    return (f"{item_id}: {what} has no --cite after it; record the DesignChange that allows it with "
            "evolution_api.add, then pass --cite ID after the deviation")


def bind_deviations(item: pm.ActionItem, given: Sequence[Tuple[str, str]]) -> Bound:
    """The ``--also`` and ``--substitute`` entries, each bound to the change of the next ``--cite``."""
    bound: Bound = {"extra_files": [], "substitutions": []}
    pending: List[Tuple[str, Dict[str, str]]] = []
    for flag, value in given:
        if flag != "--cite":
            pending.append(one_deviation(item, flag, value))
            continue
        reject_empty("cite", value)
        if not pending:
            raise pd.PlanError([f"--cite {value} follows no --also or --substitute for it to bind"])
        for key, entry in pending:
            bound[key].append({**entry, "change": value.strip()})
        pending = []
    if pending:
        raise pd.PlanError([uncited_line(item.id, key, entry) for key, entry in pending])
    return bound


def change_digest(book: prt.ReceiptBook, change_id: str) -> str:
    """The digest of the cited change in the plan's catalog (D8); ``_NO_DIGEST`` when it has none."""
    change = None if book.evolution is None else book.evolution.find(change_id)
    return _NO_DIGEST if change is None else change.digest()


def deviations_of(book: prt.ReceiptBook, item: pm.ActionItem, given: Sequence[Tuple[str, str]]) -> Deviations:
    """The receipt's deviations with each cited change's digest; raise on a deviation or citation problem."""
    bound = bind_deviations(item, given)
    cited = dict.fromkeys(entry["change"] for entry in (*bound["extra_files"], *bound["substitutions"]))
    digests = {change_id: change_digest(book, change_id) for change_id in cited}
    try:
        found = Deviations.model_validate({**bound, "change_digests": digests})
    except ValidationError as exc:
        raise pd.PlanError([f"deviation {line}" for line in pd.schema_lines(exc)]) from exc
    problems = prt.citation_problems(book.evolution, item.id, found)
    if problems:
        raise pd.PlanError(problems)
    return found


# --- record: writers --------------------------------------------------------------------------------------

def record_receipt(repo: Path, plan_file: Path, book: prt.ReceiptBook, item: pm.ActionItem,
                   args: argparse.Namespace) -> pm.ActionPlan:
    """Write the item's receipt and ``live.js``; the plan JSON and its PIP stay as they are. The status view
    after the write."""
    plan, folder = book.plan, plan_file.parent
    deviations = deviations_of(book, item, args.deviations or [])
    outcome, ref = apply_record(repo, plan, book, item, args, deviations)
    prt.write_receipt(folder, Receipt.sealed(plan.plan_id, item, outcome=outcome, date=today(),
                                             deviations=deviations, ref=ref))
    plan_live.write_live(folder, plan.plan_id)
    return prt.book_for(folder, plan).view()


def record_sealed(repo: Path, plan_file: Path, plan: pm.ActionPlan, item: pm.ActionItem,
                  args: argparse.Namespace) -> pm.ActionPlan:
    """Stamp the item's sealed record into the plan and save it with its PIP; the saved plan."""
    book = prt.SealedBook(plan)
    outcome, _ = apply_record(repo, plan, book, item, args, Deviations())
    prc.stamp(plan, item, outcome, today())
    if all(i.status in DONE for i in plan.items):
        plan.completed = today()
    else:
        plan.completed = None
        plan.model_fields_set.discard("completed")
    save(plan_file, plan)
    return plan


def cmd_record(repo: Path, args: argparse.Namespace) -> int:
    plan_file = locate(repo, args.plan)
    plan = pd.load_plan(plan_file)
    require_frozen(plan)
    problems = deviation_flag_problems(plan, args)
    if problems:
        raise pd.PlanError(problems)
    item = pd.item_by_id(plan, args.item)
    book = book_of(plan_file, plan)
    if isinstance(book, prt.ReceiptBook):
        view = record_receipt(repo, plan_file, book, item, args)
    else:
        view = record_sealed(repo, plan_file, plan, item, args)
    left = [i.id for i in view.items if i.status not in DONE]
    status = pd.item_by_id(view, item.id).status
    print(f"record [done] | {item.id} {status} | open: {', '.join(left) or 'none'}")
    return 0


# --- lanes ------------------------------------------------------------------------------------------------

def cmd_lanes(repo: Path, args: argparse.Namespace) -> int:
    plan_file = locate(repo, args.plan)
    plan = pd.load_plan(plan_file)
    book = book_of(plan_file, plan)
    require_valid(plan, book)
    target = args.target or current_branch(repo)
    if not target:
        raise CaptureError(["detached HEAD: check out the target branch or pass --target"])
    print(json.dumps(plx.lanes_plan(book.view(), target), indent=2))
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


def unrun_result(plan_id: str, book: prt.RecordBook, item: pm.ActionItem) -> Optional[prc.VerifyResult]:
    """The result of a COMPLETE item verify does not run: no valid record or receipt (a broken seal
    included), or a record without tests."""
    if not book.holds(item.id):
        return prc.VerifyResult(item=item.id, kind=VerifyKind.unrecorded,
                                detail=prc.record_command(plan_id, item.id, item.status))
    if not book.nodes(item.id):
        return prc.VerifyResult(item=item.id, kind=VerifyKind.no_tests)
    return None


def run_result(plan_id: str, book: prt.RecordBook, item: pm.ActionItem, tree: Path,
               where: str) -> prc.VerifyResult:
    """Run the item's recorded nodes (``book.nodes``) in ``tree``: pass, or fail with the tail and repair."""
    done = pr.run_pytest(pytest_argv(book.nodes(item.id)), tree)
    if done.returncode == 0:
        return prc.VerifyResult(item=item.id, kind=VerifyKind.pass_)
    command = prc.record_command(plan_id, item.id, item.status, again=True)
    detail = f"{where}: {tail(done)}; fix the code, then {command}"
    return prc.VerifyResult(item=item.id, kind=VerifyKind.fail, detail=detail)


def verify_items(repo: Path, book: prt.RecordBook, prov: pm.Provenance) -> List[prc.VerifyResult]:
    """One result per COMPLETE item of the book's view, in plan order; the runs share one throwaway
    worktree, made on demand."""
    view = book.view()
    items = [i for i in view.items if i.status == ItemStatus.COMPLETE]
    known = {i.id: unrun_result(view.plan_id, book, i) for i in items}
    if all(result is not None for result in known.values()):
        return [result for result in known.values() if result is not None]
    where = verify_where(prov)
    with pr.throwaway_tree(repo, testable_commit(repo, prov), active().resolve_worktree_root()) as tree:
        return [run_result(view.plan_id, book, i, tree, where) if known[i.id] is None else known[i.id]
                for i in items]


def cmd_verify(repo: Path, args: argparse.Namespace) -> int:
    plan_file = locate(repo, args.plan)
    plan = pd.load_plan(plan_file)
    prov = verify_target(repo, args.staged)
    results = verify_items(repo, book_of(plan_file, plan), prov)
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
    helps = {"--also": ("PATH", "A file the item changed that the plan does not list (a deviation)."),
             "--substitute": ("PLANNED=NODE", "Run NODE in place of the planned node PLANNED (a deviation)."),
             "--cite": ("ID", "The DesignChange id that allows every uncited deviation before it.")}
    for flag in DEVIATION_FLAGS:
        metavar, text = helps[flag]
        record.add_argument(flag, dest="deviations", action=_InOrder, metavar=metavar, help=text)


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
