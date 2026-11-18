"""``harness_lib.review_adversarial``: the plan-path classification, the code refuter's scope, the refuter
slots, the Workflow args, the ``adversarial_check`` log entry, the pinned-schema check and the agent count.

The module is imported inside each test (``_ra``), so a missing module fails the test, not its collection.
"""
from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Dict, Iterator, List, Optional, Sequence

import pytest

from conftest import project_factory
from harness_lib import freeze_ledger as fl
from harness_lib import plan_doc as pd
from harness_lib import review_models as rm
from harness_lib import review_plan as rp
from harness_lib.config import activate, load_config
from harness_lib.plan_enums import ItemStatus
from harness_lib.plan_models import ActionItem, ActionPlan, PlannedTest
from harness_lib.plan_models import Frozen as PlanFrozen
from harness_lib.strap_models import Frozen as SpecFrozen
from harness_lib.strap_models import Grader, SkillSpec, SpecMode, driver_digest, dump_spec

WALK_ROOTS = ()  # walks nothing; the classification reads a make_project tree
_PLANS = "docs/plans"
_SHA = "a" * 40
_DIGEST = "e" * 64
_DATE = "2026-11-12"
_AT = "2026-11-12T00:00:00+00:00"
_RUN_ID = "local-x_20261112T000000Z"


def _ra() -> ModuleType:
    return importlib.import_module("harness_lib.review_adversarial")


# --- the classification project -----------------------------------------------------------------------------


def _plan_text(plan_id: str, ledger: Optional[str] = None, frozen: bool = False) -> str:
    item = ActionItem(id="TASK-1", title="Item", action="Do it.", status=ItemStatus.PENDING,
                      evidence="not started", files=["src/a.py"], dependencies=None,
                      tests=[PlannedTest(node="tests/test_a.py::test_a", red="ImportError")])
    stamp = PlanFrozen(commit=_SHA, tree=_SHA, date=_DATE, digest=_DIGEST) if frozen else None
    plan = ActionPlan(plan_id=plan_id, plan_created=_DATE, execution_model="serial", base_commit=_SHA,
                      frozen=stamp, ledger=ledger, items=[item])
    return pd.dump_plan(plan)


def _entry(kind: fl.EntryKind, seq: int) -> fl.LedgerEntry:
    if kind is fl.EntryKind.freeze:
        return fl.LedgerEntry(kind=kind, round=1, seq=seq, tree=_SHA, at=_AT, digest=_DIGEST)
    return fl.LedgerEntry(kind=kind, round=1, seq=seq, at=_AT)


def _ledger(stem: str, kinds: Sequence[fl.EntryKind]) -> Dict[str, str]:
    """``<plans>/freezes/<stem>/r1.<k>-<kind>.json`` files, one per kind, in order."""
    out: Dict[str, str] = {}
    for seq, kind in enumerate(kinds, start=1):
        entry = _entry(kind, seq)
        out[f"{_PLANS}/{fl.FREEZES_DIR}/{stem}/{fl.entry_name(entry)}"] = fl.entry_text(entry)
    return out


def _ledger_plan(plan_id: str, slug: str, kinds: Sequence[fl.EntryKind]) -> Dict[str, str]:
    stem = fl.plan_stem(plan_id, slug)
    files = {f"{_PLANS}/{plan_id}_{slug}{pd.PLAN_SUFFIX}": _plan_text(plan_id, ledger=stem)}
    return {**files, **_ledger(stem, kinds)}


def _spec_text(name: str, frozen: bool) -> str:
    stamp = SpecFrozen(skill_hash="0" * 64, grader=Grader.SESSION, at=_AT) if frozen else None
    spec = SkillSpec(name=name, mode=SpecMode.NEW, plugin_dir="plugins/demo", frozen=stamp)
    return dump_spec(spec.model_copy(update={"driver_digest": driver_digest(spec)}))


def _plan_files() -> Dict[str, str]:
    """Every row of the classification table, as files under ``docs/plans``."""
    freeze, lock = fl.EntryKind.freeze, fl.EntryKind.lock
    files: Dict[str, str] = {}
    files.update(_ledger_plan("1016", "x", [freeze]))
    files.update(_ledger_plan("1017", "lk", [freeze, lock]))
    files.update(_ledger_plan("1018", "ar", [freeze, lock, fl.EntryKind.arm]))
    files.update(_ledger_plan("1019", "un", [freeze, lock, fl.EntryKind.unlock]))
    files[f"{_PLANS}/1020_legacy{pd.PLAN_SUFFIX}"] = _plan_text("1020", frozen=True)
    files[f"{_PLANS}/1021_open{pd.PLAN_SUFFIX}"] = _plan_text("1021")
    files[f"{_PLANS}/0002_a{pd.PLAN_SUFFIX}"] = _plan_text("0002", frozen=True)
    files[f"{_PLANS}/0002_b{pd.PLAN_SUFFIX}"] = _plan_text("0002", frozen=True)
    files[f"{_PLANS}/9999_bad{pd.PLAN_SUFFIX}"] = "not json\n"
    for rel in ("1016_x_PIP.html", "1016_y_PIP.md", "1021_open_PIP.md", "1016/design.md", "1019/design.md",
                "0002/design.md", "0042/design.md", "2026-10-13-port.md",
                "strap/open-skill/fixtures/SC-1/a.py", "strap/locked-skill/notes.md"):
        files[f"{_PLANS}/{rel}"] = "x\n"
    files[f"{_PLANS}/strap/locked-skill/SkillSpec.json"] = _spec_text("locked-skill", frozen=False)
    files[f"{_PLANS}/strap/frozen-skill/SkillSpec.json"] = _spec_text("frozen-skill", frozen=True)
    files[f"{_PLANS}/strap/open-skill/SkillSpec.json"] = _spec_text("open-skill", frozen=False)
    files.update(_ledger(fl.skill_stem("locked-skill"), [lock]))
    files["src/a.py"] = "def f():\n    return 1\n"
    return files


@pytest.fixture(scope="module")
def plans_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One project holding every classification row; ``artifacts.plans`` is ``docs/plans``."""
    make = project_factory(tmp_path_factory.mktemp("adversarial"))
    return make(config={"artifacts": {"plans": _PLANS}}, files=_plan_files(), name="plans")


@pytest.fixture()
def active_plans(plans_project: Path) -> Iterator[Path]:
    activate(load_config(plans_project))
    yield plans_project


_ROWS = [
    ("1016_x_ActionPlan.json", "frozen"),
    ("1017_lk_ActionPlan.json", "frozen"),
    ("1018_ar_ActionPlan.json", "frozen"),
    ("1019_un_ActionPlan.json", "unfrozen"),
    ("1020_legacy_ActionPlan.json", "frozen"),
    ("1021_open_ActionPlan.json", "unfrozen"),
    ("1016_x_PIP.html", "frozen"),
    ("1016_y_PIP.md", "unfrozen"),
    ("1021_open_PIP.md", "unfrozen"),
    ("1016/design.md", "frozen"),
    ("1019/design.md", "unfrozen"),
    ("0002/design.md", "unfrozen"),
    ("0042/design.md", "unfrozen"),
    ("freezes/plan/1016-x/r1.1-freeze.json", "excluded"),
    ("strap/open-skill/fixtures/SC-1/a.py", "excluded"),
    ("strap/locked-skill/SkillSpec.json", "frozen"),
    ("strap/locked-skill/notes.md", "frozen"),
    ("strap/frozen-skill/SkillSpec.json", "frozen"),
    ("strap/open-skill/SkillSpec.json", "unfrozen"),
    ("2026-10-13-port.md", "unfrozen"),
    ("9999_bad_ActionPlan.json", "unfrozen"),
]


def _where(classified: object, rel: str) -> List[str]:
    return [name for name in ("frozen", "unfrozen", "excluded") if rel in getattr(classified, name)]


@pytest.mark.parametrize(("rel", "expected"), _ROWS, ids=[r[0] for r in _ROWS])
def test_each_plan_path_lands_in_its_row(active_plans: Path, rel: str, expected: str) -> None:
    path = f"{_PLANS}/{rel}"
    classified = _ra().classify_plan_paths([path, "src/a.py"], at_head=True)
    assert _where(classified, path) == [expected]


def test_a_path_outside_the_plans_folder_is_not_classified(active_plans: Path) -> None:
    classified = _ra().classify_plan_paths(["src/a.py"], at_head=True)
    assert _where(classified, "src/a.py") == [] and classified.notes == ()


def test_a_readable_plan_adds_no_note(active_plans: Path) -> None:
    classified = _ra().classify_plan_paths([f"{_PLANS}/1016_x_ActionPlan.json"], at_head=True)
    assert classified.notes == ()


@pytest.mark.parametrize(("rel", "named"), [
    ("0002/design.md", "0002"), ("0042/design.md", "0042"), ("9999_bad_ActionPlan.json", "9999_bad"),
], ids=["several-plans", "no-plan", "unreadable"])
def test_an_unresolved_state_is_unfrozen_with_a_note(active_plans: Path, rel: str, named: str) -> None:
    classified = _ra().classify_plan_paths([f"{_PLANS}/{rel}"], at_head=True)
    assert f"{_PLANS}/{rel}" in classified.unfrozen
    assert any(named in note for note in classified.notes), classified.notes


def test_a_tree_off_the_head_unfreezes_every_plan_path_with_one_note(active_plans: Path) -> None:
    paths = [f"{_PLANS}/{rel}" for rel, _ in _ROWS]
    classified = _ra().classify_plan_paths(paths, at_head=False)
    assert classified.frozen == ()
    assert f"{_PLANS}/1016_x_ActionPlan.json" in classified.unfrozen
    assert len(classified.notes) == 1


# --- code scope ---------------------------------------------------------------------------------------------


def _plan_paths() -> object:
    return _ra().PlanPaths(
        frozen=("docs/plans/1016/tool.py", "docs/plans/1016_x_ActionPlan.json"),
        unfrozen=("docs/plans/1021/tool.py", "docs/plans/1021_open_ActionPlan.json"),
        excluded=("docs/plans/strap/s/fixtures/a.py",), notes=())


def _buckets() -> Dict[str, tuple]:
    return {"runtime": ("src/a.py", "docs/plans/1016/tool.py", "docs/plans/1021/tool.py",
                        "docs/plans/strap/s/fixtures/a.py"),
            "tests": ("tests/test_a.py",),
            "docs": ("docs/a.md", "docs/plans/1016_x_ActionPlan.json",
                     "docs/plans/1021_open_ActionPlan.json"),
            "config-or-registry": ("pyproject.toml",)}


def test_code_scope_takes_runtime_tests_and_unfrozen_plans_only() -> None:
    scope = _ra().code_scope(_buckets(), _plan_paths())
    assert scope == {"runtime": ("src/a.py",), "tests": ("tests/test_a.py",),
                     "plans": ("docs/plans/1021/tool.py", "docs/plans/1021_open_ActionPlan.json")}


def test_code_scope_of_a_docs_only_change_is_empty() -> None:
    ra = _ra()
    assert ra.code_scope({"docs": ("docs/a.md",), "runtime": ()}, ra.PlanPaths()) == {}


def test_registry_files_merged_into_tests_are_in_scope(make_project) -> None:
    root = make_project(config={"tests": {"registry": "tests/registry.json"}})
    activate(load_config(root))
    buckets, notes = rp.merge_registry_into_tests(rp.sort_buckets(["tests/test_a.py", "tests/registry.json"]))
    assert notes
    ra = _ra()
    assert "tests/registry.json" in ra.code_scope(buckets, ra.PlanPaths())["tests"]


# --- refuter slots ------------------------------------------------------------------------------------------


def test_a_small_change_pools_the_scope_in_one_code_refuter() -> None:
    scope = {"runtime": ("src/a.py",), "tests": ("tests/test_a.py",)}
    plan = _ra().refuter_slots(["tests", "runtime", "overall"], scope, reviewable_count=rp.SMALL_PR_FILES - 1)
    assert [(c.id, c.paths) for c in plan.code] == [("adv_code", ("src/a.py", "tests/test_a.py"))]
    assert [(r.id, r.target) for r in plan.refute] == [
        ("adv_refute_tests", "tests"), ("adv_refute_runtime", "runtime"), ("adv_refute_overall", "overall"),
        ("adv_refute_adv_code", "adv_code")]


def test_a_large_change_gets_one_code_refuter_per_scope_bucket() -> None:
    ra = _ra()
    scope = ra.code_scope(_buckets(), _plan_paths())
    plan = ra.refuter_slots(["runtime", "overall"], scope, reviewable_count=rp.SMALL_PR_FILES)
    assert [c.id for c in plan.code] == ["adv_code_runtime", "adv_code_tests", "adv_code_plans"]
    assert [r.target for r in plan.refute][-3:] == ["adv_code_runtime", "adv_code_tests", "adv_code_plans"]


def test_each_scope_path_lands_in_exactly_one_code_slot() -> None:
    ra = _ra()
    scope = ra.code_scope(_buckets(), _plan_paths())
    for count in (1, rp.SMALL_PR_FILES):
        code = ra.refuter_slots(["overall"], scope, reviewable_count=count).code
        slotted = [p for c in code for p in c.paths]
        assert sorted(slotted) == sorted(p for paths in scope.values() for p in paths)


def test_an_empty_scope_plans_no_code_refuter() -> None:
    plan = _ra().refuter_slots(["docs", "overall"], {}, reviewable_count=3)
    assert plan.code == ()
    assert [r.target for r in plan.refute] == ["docs", "overall"]


def test_every_refuter_slot_runs_on_opus() -> None:
    plan = _ra().refuter_slots(["runtime", "overall"], {"runtime": ("src/a.py",), "tests": ("t.py",)},
                               reviewable_count=rp.SMALL_PR_FILES)
    assert rm.REFUTER_MODEL == "opus"
    assert {s.model for s in (*plan.code, *plan.refute)} == {rm.REFUTER_MODEL}


def test_the_plan_records_code_and_refute_entries() -> None:
    plan = _ra().refuter_slots(["runtime"], {"runtime": ("src/a.py",)}, reviewable_count=1)
    assert plan.record() == {
        "code": [{"id": "adv_code", "paths": ["src/a.py"], "model": "opus"}],
        "refute": [{"id": "adv_refute_runtime", "target": "runtime", "model": "opus"},
                   {"id": "adv_refute_adv_code", "target": "adv_code", "model": "opus"}]}


# --- workflow args ------------------------------------------------------------------------------------------


def _args() -> Dict[str, object]:
    ra = _ra()
    plan = ra.refuter_slots(["runtime", "overall"], {"runtime": ("src/a.py",)}, reviewable_count=2)
    reviewers = [{"id": "runtime", "model": "sonnet", "prompt": "P runtime"},
                 {"id": "overall", "model": "opus", "prompt": "P overall"}]
    prompts = {s.id: f"P {s.id}" for s in (*plan.code, *plan.refute)}
    return ra.workflow_args("local-x", _RUN_ID, reviewers, plan, prompts)


def test_workflow_args_carry_the_run_and_no_guidance() -> None:
    args = _args()
    assert args["run_key"] == "local-x" and args["run_id"] == _RUN_ID
    assert "guidance" in args and args["guidance"] is None
    assert json.loads(json.dumps(args)) == args


def test_workflow_args_name_the_reviewer_agent_for_reviewers() -> None:
    assert _args()["reviewers"] == [
        {"id": "runtime", "agentType": "harness:pr-reviewer", "model": "sonnet", "prompt": "P runtime"},
        {"id": "overall", "agentType": "harness:pr-reviewer", "model": "opus", "prompt": "P overall"}]


def test_workflow_args_name_the_adversarial_agent_for_code_and_refuters() -> None:
    args = _args()
    agent, model = rm.ADVERSARIAL_AGENT, rm.REFUTER_MODEL
    assert args["code"] == [{"id": "adv_code", "agentType": agent, "model": model, "prompt": "P adv_code"}]
    assert args["refute"] == [
        {"id": f"adv_refute_{t}", "target": t, "agentType": agent, "model": model,
         "prompt": f"P adv_refute_{t}"} for t in ("runtime", "overall", "adv_code")]


# --- adversarial_check --------------------------------------------------------------------------------------


def _check() -> Dict[str, object]:
    ra = _ra()
    return ra.adversarial_check(ra.refuter_slots(["runtime"], {"runtime": ("src/a.py",)}, reviewable_count=1))


def test_the_initial_check_records_the_plan() -> None:
    check = _check()
    assert set(check) == {"applies", "workflow", "code_slots", "refute_slots", "result"}
    assert check["applies"] is True and check["workflow"] == rm.ADVERSARIAL_WORKFLOW
    assert check["code_slots"] == ["adv_code"]
    assert check["refute_slots"] == ["adv_refute_runtime", "adv_refute_adv_code"]
    assert str(check["result"]).startswith("PENDING")


def test_the_completed_check_counts_findings_and_lists_refuted_ids() -> None:
    check = _check()
    done = _ra().complete_check(check, checked=4, refuted=1, code_findings=2, refuted_ids=["M2"])
    assert done["counts"] == {"findings_checked": 4, "findings_refuted": 1, "findings_upheld": 3,
                              "code_findings": 2}
    assert done["refuted_ids"] == ["M2"] and done["unrefuted_ids"] == []
    assert str(done["result"]).startswith("OK")
    assert "counts" not in check


# --- pinned schema, agent count, lens names -----------------------------------------------------------------


def _schema(path: Path, statuses: Sequence[str]) -> Path:
    body = {"definitions": {"post_review_resolution": {"properties": {"status": {"enum": list(statuses)}}}}}
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


_ADVERSARIAL_STATUSES = ("REFUTED", "BUBBLED", "NOT_RESOLVED")


@pytest.mark.parametrize("statuses", [
    ("RESOLVED", "CLOSED_NO_ACTION"),
    ("RESOLVED", "BUBBLED", "NOT_RESOLVED"),
    ("RESOLVED", "REFUTED", "NOT_RESOLVED"),
    ("RESOLVED", "REFUTED", "BUBBLED"),
], ids=["none", "no-refuted", "no-bubbled", "no-not-resolved"])
def test_a_schema_without_the_adversarial_statuses_is_a_problem(tmp_path: Path, statuses: tuple) -> None:
    path = _schema(tmp_path / "PR_REVIEW.schema.json", statuses)
    problem = _ra().schema_problem(path)
    missing = [s for s in _ADVERSARIAL_STATUSES if s not in statuses]
    assert problem and path.name in problem, problem
    assert all(re.search(rf"\b{s}\b", problem) for s in missing), problem


def test_a_schema_with_all_three_statuses_is_no_problem(tmp_path: Path) -> None:
    path = _schema(tmp_path / "PR_REVIEW.schema.json", ("RESOLVED", *_ADVERSARIAL_STATUSES))
    assert _ra().schema_problem(path) is None


def test_agent_count_is_twice_reviewers_plus_code_refuters() -> None:
    ra = _ra()
    plan = ra.refuter_slots(["runtime", "overall"], {"runtime": ("src/a.py",)}, reviewable_count=2)
    total = 2 + len(plan.code) + len(plan.refute)
    assert ra.agent_count(2, len(plan.code)) == total == 2 * (2 + 1)


def test_worst_case_agent_count_matches_the_planner() -> None:
    buckets = {b: (f"{b.value}/x1", f"{b.value}/x2") for b in rp.PathBucket.slotted()}
    lenses = {rp.Lens.SKILL_PACKAGE.value: ("a",), rp.Lens.MULTI_ARTIFACT.value: ("b",),
              "lens-one": ("c",), "lens-two": ("d",)}
    reviewable = tuple(f"f{i}.py" for i in range(rp.SMALL_PR_FILES))
    slots = rp.slot_plan(buckets, lenses, True, reviewable, extra_lenses=("lens-one", "lens-two"))
    ra = _ra()
    scope = {"runtime": ("a.py",), "tests": ("t.py",), "plans": ("docs/plans/p.md",)}
    code = ra.refuter_slots([s.id for s in slots], scope, reviewable_count=len(reviewable)).code
    assert len(slots) == 10 + 2 and len(code) == 3
    assert ra.worst_case_agents(2) == ra.agent_count(len(slots), len(code)) == 26 + 2 * 2


@pytest.mark.parametrize("name", ["adv-code", "adv-refute-x"])
def test_a_project_lens_may_not_take_the_adv_prefix(name: str) -> None:
    lens = {"name": name, "trigger": {"path_globs": ["src/*.py"]}, "scope_template": "t"}
    rp._check_project_lens({**lens, "name": "advisory-docs"})
    with pytest.raises(ValueError, match=re.escape(name)):
        rp._check_project_lens(lens)
