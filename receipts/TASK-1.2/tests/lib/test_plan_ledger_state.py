"""Plan 1015 PST-1: the plan freeze stamp is read from the freeze ledger (decision D1, hydrate option).

A plan JSON names its ledger in the static ``ledger`` field (the stem ``plan/<id>-<slug>``); ``load_plan``
then reads ``freeze_ledger.ledger_dir(<plan folder>, stem)`` and fills ``ActionPlan.frozen`` from the last
``freeze`` entry whenever the state is frozen, locked, armed or unlocked: a stamp without a commit, with the
entry's tree, date (the ``at`` day), digest and record scheme. A ``ledger`` field whose folder is missing or
empty is a ``PlanError`` naming the stem. ``save_plan`` leaves ``frozen`` out of the JSON while ``ledger`` is
set. A legacy plan (in-file stamp, no ``ledger``) loads and saves as before, and ``Frozen`` accepts a stamp
whose commit is unset. ``plan_api.write`` refuses a Locked plan, armed or not, naming ``unlock --arm``. The
renderers print ``<date> at <tree7>`` for a ledger stamp, and the todo_sync P1 rule reads the receipts
scheme from the ledger's last freeze.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest
from pydantic import ValidationError

from harness_lib import plan_api
from harness_lib import plan_doc as pd
from harness_lib import plan_models as pm
from harness_lib import plan_render, plan_render_html
from harness_lib.plan_enums import RecordScheme

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import PIP, PIP_REL, PLAN_REL, build, rule_findings, todo_files  # noqa: E402

PLAN_ID = "0001"
SLUG = "sample"
NAME = f"{PLAN_ID}_Sample_ActionPlan.json"
PLANS = "docs/PLANS"
BASE = "e" * 40
TREE = "abcdef1" + "2" * 33
TREE2 = "1234567" + "8" * 33
BLOB = "f" * 40
AT = "2026-11-11T09:30:00+00:00"
AT2 = "2026-11-12T08:00:00+00:00"
LEGACY = {"commit": "a" * 40, "tree": "b" * 40, "date": "2026-11-10", "digest": "d" * 64,
          "records": "receipts"}
CHAINS = {"frozen": ("freeze",), "locked": ("freeze", "lock"), "armed": ("freeze", "lock", "arm"),
          "unlocked": ("freeze", "lock", "arm", "unlock")}


def raw_plan(stem: Optional[str] = None) -> Dict[str, Any]:
    """A minimal valid plan body with no freeze stamp; ``stem`` sets its ``ledger`` field."""
    raw: Dict[str, Any] = {
        "plan_id": PLAN_ID, "plan_created": "2026-11-10", "execution_model": "serial", "base_commit": BASE,
        "items": [{"id": "TASK-1", "title": "Add sub", "action": "Add sub beside add.", "status": "PENDING",
                   "evidence": "not started", "files": ["src/calc.py"],
                   "tests": [{"node": "tests/test_calc_sub.py::test_sub", "red": "ImportError"}]}],
    }
    if stem is not None:
        raw["ledger"] = stem
    return raw


def write_plan(folder: Path, raw: Dict[str, Any]) -> Path:
    """``raw`` written as the plan file ``NAME`` under ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / NAME
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return path


def entry(fl: Any, kind: str, seq: int, **fields: Any) -> Any:
    """A round-1 plan ledger entry; ``freeze`` and ``lock`` carry ``TREE`` and a receipts digest."""
    body: Dict[str, Any] = {
        "kind": kind, "round": 1, "seq": seq, "tree": None, "files": {}, "ignored": {}, "at": AT,
        "base": BASE, "history": False, "digest": None, "records": None, "skill_hash": None, "grader": None,
    }
    if kind in ("freeze", "lock"):
        body.update(tree=TREE, files={f"{PLANS}/{NAME}": BLOB}, digest="d" * 64, records="receipts")
    if kind == "arm":
        body["reason"] = "design change agreed with the developer"
    body.update(fields)
    return fl.LedgerEntry.model_validate(body)


def add_entries(fl: Any, plans_dir: Path, entries: Sequence[Any]) -> Path:
    """Write ``entries`` into the ledger folder of plan ``PLAN_ID`` under ``plans_dir``; the folder."""
    folder = fl.ledger_dir(plans_dir, fl.plan_stem(PLAN_ID, SLUG))
    folder.mkdir(parents=True, exist_ok=True)
    for one in entries:
        fl.write_entry(folder, one)
    return folder


def chain(fl: Any, kinds: Sequence[str], digest: str) -> List[Any]:
    """Entries of ``kinds`` with seqs 1, 2, ...; each freeze and lock carries ``digest``."""
    out = []
    for seq, kind in enumerate(kinds, start=1):
        extra = {"digest": digest} if kind in ("freeze", "lock") else {}
        out.append(entry(fl, kind, seq, **extra))
    return out


def ledger_plan(fl: Any, folder: Path, kinds: Sequence[str] = ("freeze",)) -> Path:
    """A plan file naming its ledger, plus that ledger holding ``kinds`` on the plan's true digest."""
    raw = raw_plan(fl.plan_stem(PLAN_ID, SLUG))
    path = write_plan(folder, raw)
    digest = pd.frozen_digest(pd.validate_plan(raw), RecordScheme.receipts)
    add_entries(fl, folder, chain(fl, kinds, digest))
    return path


def assert_stamp(frozen: Optional[pm.Frozen], tree: str, at: str, digest: str, label: str) -> None:
    """``frozen`` is a ledger stamp: no commit, ``tree``, the day of ``at``, ``digest``, receipts."""
    assert frozen is not None, f"{label}: the ledger's last freeze must hydrate ActionPlan.frozen"
    assert frozen.commit is None, label
    assert frozen.tree == tree, label
    assert frozen.date == at[:10], label
    assert frozen.digest == digest, label
    assert frozen.records == RecordScheme.receipts, label


def problems_text(exc: pd.PlanError) -> str:
    return " ".join(exc.problems)


def test_load_plan_hydrates_frozen_from_ledger(tmp_path: Path) -> None:
    from harness_lib import freeze_ledger as fl

    for state, kinds in CHAINS.items():
        folder = tmp_path / state
        path = ledger_plan(fl, folder, kinds)
        ledger = fl.ledger_dir(folder, fl.plan_stem(PLAN_ID, SLUG))
        assert fl.state(fl.load_entries(ledger)) == fl.LedgerState[state]
        digest = pd.frozen_digest(pd.validate_plan(raw_plan(fl.plan_stem(PLAN_ID, SLUG))),
                                  RecordScheme.receipts)
        assert_stamp(pd.load_plan(path).frozen, TREE, AT, digest, state)
    folder = tmp_path / "unlocked"
    refreeze = entry(fl, "freeze", len(CHAINS["unlocked"]) + 1, tree=TREE2, at=AT2, digest="c" * 64)
    add_entries(fl, folder, [refreeze])
    assert_stamp(pd.load_plan(folder / NAME).frozen, TREE2, AT2, "c" * 64, "refrozen after unlock")


def test_save_plan_omits_frozen_when_ledger_exists(tmp_path: Path) -> None:
    from harness_lib import freeze_ledger as fl

    path = ledger_plan(fl, tmp_path, CHAINS["locked"])
    plan = pd.load_plan(path)
    assert plan.frozen is not None
    pd.save_plan(path, plan)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "frozen" not in data, "with a ledger the stamp lives there, not in the plan JSON"
    assert data["ledger"] == fl.plan_stem(PLAN_ID, SLUG)
    reloaded = pd.load_plan(path)
    assert reloaded.frozen is not None and reloaded.frozen.tree == TREE
    assert pd.frozen_digest(reloaded, RecordScheme.receipts) == reloaded.frozen.digest


def test_missing_ledger_folder_is_a_problem(tmp_path: Path) -> None:
    from harness_lib import freeze_ledger as fl

    stem = fl.plan_stem(PLAN_ID, SLUG)
    path = write_plan(tmp_path, raw_plan(stem))
    with pytest.raises(pd.PlanError) as missing:
        pd.load_plan(path)
    assert stem in problems_text(missing.value), "a ledger field without its folder names the stem"
    fl.ledger_dir(tmp_path, stem).mkdir(parents=True)
    with pytest.raises(pd.PlanError) as empty:
        pd.load_plan(path)
    assert stem in problems_text(empty.value), "an empty ledger folder reads as missing"


def test_legacy_plan_keeps_in_file_stamp(tmp_path: Path) -> None:
    path = write_plan(tmp_path, dict(raw_plan(), frozen=dict(LEGACY)))
    plan = pd.load_plan(path)
    assert plan.frozen is not None
    assert plan.frozen.commit == LEGACY["commit"] and plan.frozen.tree == LEGACY["tree"]
    assert plan.frozen.date == LEGACY["date"]
    pd.save_plan(path, plan)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["frozen"]["commit"] == LEGACY["commit"], "a plan without a ledger keeps its in-file stamp"
    assert "ledger" not in data
    try:
        stamp = pm.Frozen(commit=None, tree=TREE, date=AT[:10], digest="d" * 64,
                          records=RecordScheme.receipts)
    except ValidationError as exc:
        assert False, f"Frozen must accept commit=None for a ledger stamp: {exc}"
    assert stamp.commit is None and stamp.tree == TREE


def refused(root: Path, label: str) -> None:
    """``plan_api.write`` of a revised plan ``PLAN_ID`` refuses, names ``unlock --arm`` and writes nothing."""
    plan = plan_api.load(PLAN_ID, repo=root)
    path = root / PLANS / NAME
    before = path.read_bytes()
    revised = plan.model_copy(deep=True)
    revised.items[0].action = "Add sub and mul beside add."
    with pytest.raises(pd.PlanError) as caught:
        plan_api.write(revised, repo=root)
    assert "unlock --arm" in problems_text(caught.value), label
    assert path.read_bytes() == before, f"{label}: a refused write leaves the plan file alone"


def test_write_refuses_locked_plan(make_project) -> None:
    from harness_lib import freeze_ledger as fl

    root = make_project(files={f"{PLANS}/{NAME}": raw_plan(fl.plan_stem(PLAN_ID, SLUG))})
    plans_dir = root / PLANS
    add_entries(fl, plans_dir, chain(fl, CHAINS["locked"], "d" * 64))
    refused(root, "a Locked plan")
    add_entries(fl, plans_dir, [entry(fl, "arm", 3)])
    refused(root, "an armed plan stays Locked")
    add_entries(fl, plans_dir, [entry(fl, "unlock", 4)])
    plan = plan_api.load(PLAN_ID, repo=root)
    revised = plan.model_copy(deep=True)
    revised.items[0].action = "Add sub and mul beside add."
    written = plan_api.write(revised, repo=root)
    assert written.items[0].action == "Add sub and mul beside add.", "an unlocked plan is editable again"


def test_rules_plans_reads_receipts_scheme_from_ledger(make_project) -> None:
    from harness_lib import freeze_ledger as fl

    files = todo_files()
    files[PIP_REL] = PIP.replace("- [ ] open", "- [X] open")
    cfg = build(make_project, files)
    assert rule_findings(cfg, "P1"), "without a ledger the checked box of a PENDING item is a P1 error"
    plan_file = cfg.path(PLAN_REL)
    data = json.loads(plan_file.read_text(encoding="utf-8"))
    data["ledger"] = fl.plan_stem(PLAN_ID, SLUG)
    plan_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    plans_dir = plan_file.parent
    add_entries(fl, plans_dir, [entry(fl, "freeze", 1, records="sealed")])
    assert rule_findings(cfg, "P1"), "a sealed freeze in the ledger keeps P1 on the plan"
    add_entries(fl, plans_dir, [entry(fl, "freeze", 2)])
    assert rule_findings(cfg, "P1") == [], "a last freeze with receipts makes P1 skip the plan"


def test_render_frozen_text_without_commit(tmp_path: Path) -> None:
    from harness_lib import freeze_ledger as fl

    plan = pd.load_plan(ledger_plan(fl, tmp_path, CHAINS["locked"]))
    assert plan.frozen is not None and plan.frozen.commit is None
    markdown = plan_render.render_pip(plan, NAME)
    assert f"**Frozen:** {AT[:10]} at `{TREE[:7]}`" in markdown
    page = plan_render_html.render_pip_html(plan, NAME)
    assert f"<dt>Frozen</dt><dd>{AT[:10]} at <code>{TREE[:7]}</code></dd>" in page
