"""Behavioral tests for harness_lib.strap_runs (skill-agnostic draws, hashes, checks and pass rules).

Pins the content hash formula (sorted paths, per-file bytes, the ``<missing>`` marker), seeded scenario draws
with exclusion and the exhausted-pool ``ValueError``, ``evaluate_checks`` for every ``CheckKind`` on both
arms, whitespace-normalized quote verification, the baseline-failure (any) and green-pass (all) rules with
complete check results (D8), the must-pass retest pool without void retest draws (D15), and the module's
import boundary: ``strap_models`` plus the standard library only.
"""
from __future__ import annotations

import ast
import hashlib
import random
import sys
from pathlib import Path
from typing import List, Optional, Sequence

import pytest

from harness_lib import strap_runs
from harness_lib.strap_models import (
    Arm, Behavior, BehaviorKind, Check, CheckKind, CheckResult, Draw, DrawReason, Grade, Grader, GradeValue,
    JudgedItem, JudgmentType, ReplyAct, Run, Scenario, SkillSpec, SpecMode,
)

_FILES = {"skills/demo/SKILL.md": "---\nname: demo\n---\nbody\n", "lib/demo.py": "X = 1\n"}
_REPLY = "Not editing the memo.\nDecision belongs to bubble-stamp; redirecting there.\n"
_FACTS_REPLY = "intro line\nDecision: A\n"


def _expected_hash(root: Path, paths: Sequence[str]) -> str:
    """The contract's content hash, computed independently."""
    digest = hashlib.sha256()
    for rel in sorted(paths):
        target = root / rel
        body = target.read_bytes() if target.is_file() else b"<missing>"
        digest.update(rel.encode("utf-8") + b"\0" + body + b"\0")
    return digest.hexdigest()


def _scenario(sid: str = "SC-1") -> Scenario:
    """A scenario with one file check and one judged item."""
    check = Check(kind=CheckKind.FILE_UNCHANGED, target="memo.md", expect_baseline=False, expect_green=True)
    judged = JudgedItem(act=ReplyAct.REDIRECTS, of="bubble-stamp", expect_baseline=GradeValue.ABSENT,
                        expect_green=GradeValue.PRESENT)
    return Scenario(id=sid, task="write the memo", tempts="edits the Decision line", checks=[check],
                    judged=[judged])


def _behavior(bid: str = "B1", ids: Sequence[str] = ("SC-1", "SC-2", "SC-3", "SC-4")) -> Behavior:
    """A judgment (technique) behavior holding scenarios ``ids``."""
    return Behavior(id=bid, statement="redirects decisions", kind=BehaviorKind.JUDGMENT,
                    type=JudgmentType.TECHNIQUE, rationale="no file state shows intent",
                    scenarios=[_scenario(sid) for sid in ids])


def _run(rid: str, arm: Arm, held: bool, scenario: str = "SC-1", behavior: str = "B1",
         skill_hash: str = "h1") -> Run:
    """A recorded run whose single check result is ``held``."""
    return Run(id=rid, behavior=behavior, scenario=scenario, arm=arm, skill_hash=skill_hash, reply=_REPLY,
               reply_sha256=hashlib.sha256(_REPLY.encode("utf-8")).hexdigest(),
               checks=[CheckResult(index=0, held=held, detail="")], recorded=True)


def _grade(rid: str, value: GradeValue) -> Grade:
    """A session grade of judged item 0 on run ``rid``."""
    return Grade(run=rid, item=0, value=value, quote="redirecting there", grader=Grader.SESSION)


def _check(kind: CheckKind, target: str, baseline: bool, green: bool) -> Check:
    return Check(kind=kind, target=target, expect_baseline=baseline, expect_green=green)


def _evaluate(checks: List[Check], arm: Arm, head_moved: bool = False) -> List[CheckResult]:
    """``evaluate_checks`` over fixed facts: ``a.txt`` changed, only ``there.txt`` present."""
    return strap_runs.evaluate_checks(checks, arm, ["a.txt"], lambda p: p == "there.txt", head_moved,
                                      _FACTS_REPLY)


def test_content_hash_matches_formula(make_project) -> None:
    root = make_project(files=_FILES)
    paths = ["skills/demo/SKILL.md", "lib/demo.py"]
    assert strap_runs.content_hash(root, paths) == _expected_hash(root, paths)


def test_content_hash_ignores_input_order(make_project) -> None:
    root = make_project(files=_FILES)
    forward = strap_runs.content_hash(root, ["lib/demo.py", "skills/demo/SKILL.md"])
    assert forward == strap_runs.content_hash(root, ["skills/demo/SKILL.md", "lib/demo.py"])


def test_content_hash_changes_with_one_byte(make_project) -> None:
    root = make_project(files=_FILES)
    paths = ["skills/demo/SKILL.md", "lib/demo.py"]
    before = strap_runs.content_hash(root, paths)
    (root / "lib" / "demo.py").write_bytes(b"X = 2\n")
    assert strap_runs.content_hash(root, paths) != before


def test_content_hash_missing_file_uses_marker(make_project) -> None:
    root = make_project(files=_FILES)
    expected = hashlib.sha256(b"gone.txt\0<missing>\0").hexdigest()
    assert strap_runs.content_hash(root, ["gone.txt"]) == expected


def test_draw_scenario_is_seeded_choice_in_declared_order() -> None:
    behavior = _behavior()
    for seed in (0, 7, 12345):
        expected = random.Random(seed).choice(["SC-1", "SC-3", "SC-4"])
        assert strap_runs.draw_scenario(behavior, ["SC-2"], seed) == expected
        assert strap_runs.draw_scenario(behavior, ["SC-2"], seed) == expected


def test_draw_scenario_never_returns_excluded() -> None:
    behavior = _behavior()
    picks = {strap_runs.draw_scenario(behavior, ["SC-1", "SC-2", "SC-4"], seed) for seed in range(25)}
    assert picks == {"SC-3"}


def test_draw_scenario_exhausted_pool_raises() -> None:
    behavior = _behavior(bid="B7", ids=("SC-1", "SC-2"))
    with pytest.raises(ValueError, match=r"^B7 has no undrawn scenario$"):
        strap_runs.draw_scenario(behavior, ["SC-1", "SC-2"], 3)


def test_new_seed_is_32_bit_int() -> None:
    seed = strap_runs.new_seed()
    assert isinstance(seed, int) and 0 <= seed < 2 ** 32


@pytest.mark.parametrize("kind, target, fact", [
    (CheckKind.FILE_CHANGED, "a.txt", True),
    (CheckKind.FILE_CHANGED, "b.txt", False),
    (CheckKind.FILE_UNCHANGED, "b.txt", True),
    (CheckKind.FILE_UNCHANGED, "a.txt", False),
    (CheckKind.PATH_PRESENT, "there.txt", True),
    (CheckKind.PATH_PRESENT, "gone.txt", False),
    (CheckKind.PATH_ABSENT, "gone.txt", True),
    (CheckKind.PATH_ABSENT, "there.txt", False),
    (CheckKind.HEAD_UNCHANGED, "HEAD", True),
    (CheckKind.REPLY_MATCHES, r"^Decision: A$", True),
    (CheckKind.REPLY_MATCHES, r"^nope", False),
    (CheckKind.REPLY_LACKS, r"^nope", True),
    (CheckKind.REPLY_LACKS, r"^Decision", False),
], ids=["changed-hit", "changed-miss", "unchanged-hit", "unchanged-miss", "present-hit", "present-miss",
        "absent-hit", "absent-miss", "head", "matches-hit", "matches-miss", "lacks-hit", "lacks-miss"])
def test_evaluate_checks_holds_when_fact_equals_arm_expectation(kind: CheckKind, target: str,
                                                                fact: bool) -> None:
    tempted = [_check(kind, target, baseline=fact, green=not fact)]
    assert [r.held for r in _evaluate(tempted, Arm.BASELINE)] == [True]
    assert [r.held for r in _evaluate(tempted, Arm.GREEN)] == [False]
    mirrored = [_check(kind, target, baseline=not fact, green=fact)]
    assert [r.held for r in _evaluate(mirrored, Arm.BASELINE)] == [False]
    assert [r.held for r in _evaluate(mirrored, Arm.GREEN)] == [True]


def test_evaluate_checks_head_moved_breaks_head_unchanged() -> None:
    checks = [_check(CheckKind.HEAD_UNCHANGED, "HEAD", baseline=False, green=True)]
    assert [r.held for r in _evaluate(checks, Arm.GREEN, head_moved=True)] == [False]
    assert [r.held for r in _evaluate(checks, Arm.BASELINE, head_moved=True)] == [True]


def test_evaluate_checks_indexes_follow_input_order() -> None:
    checks = [_check(CheckKind.FILE_CHANGED, "a.txt", True, True),
              _check(CheckKind.PATH_ABSENT, "gone.txt", True, True),
              _check(CheckKind.REPLY_LACKS, "zzz", True, True)]
    results = _evaluate(checks, Arm.GREEN)
    assert [r.index for r in results] == [0, 1, 2]
    assert all(isinstance(r, CheckResult) and r.held for r in results)


@pytest.mark.parametrize("quote, expected", [
    ("redirecting   there", True),
    ("Decision belongs\nto bubble-stamp", True),
    ("  memo.\n\tDecision  ", True),
    ("redirecting elsewhere", False),
])
def test_quote_found_normalizes_whitespace(quote: str, expected: bool) -> None:
    assert strap_runs.quote_found(quote, _REPLY) is expected


def test_item_matches_bool_and_grade() -> None:
    assert strap_runs.item_matches(True, True) and not strap_runs.item_matches(True, False)
    assert strap_runs.item_matches(GradeValue.PRESENT, GradeValue.PRESENT)
    assert not strap_runs.item_matches(GradeValue.PRESENT, GradeValue.UNCLEAR)


@pytest.mark.parametrize("held, value, expected", [
    (False, GradeValue.PRESENT, False),
    (True, GradeValue.PRESENT, True),
    (False, GradeValue.ABSENT, True),
])
def test_baseline_failed_when_any_item_matches_baseline(held: bool, value: GradeValue,
                                                        expected: bool) -> None:
    run = _run("R-1", Arm.BASELINE, held)
    assert strap_runs.baseline_failed(_scenario(), run, [_grade("R-1", value)]) is expected


def test_baseline_failed_ignores_other_runs_grades() -> None:
    run = _run("R-1", Arm.BASELINE, held=False)
    grades = [_grade("R-9", GradeValue.ABSENT), _grade("R-1", GradeValue.PRESENT)]
    assert strap_runs.baseline_failed(_scenario(), run, grades) is False


@pytest.mark.parametrize("held, value, expected", [
    (True, GradeValue.PRESENT, True),
    (False, GradeValue.PRESENT, False),
    (True, GradeValue.ABSENT, False),
    (True, GradeValue.UNCLEAR, False),
])
def test_green_passed_requires_every_item(held: bool, value: GradeValue, expected: bool) -> None:
    run = _run("R-2", Arm.GREEN, held)
    assert strap_runs.green_passed(_scenario(), run, [_grade("R-2", value)]) is expected


def test_green_passed_missing_grade_fails() -> None:
    run = _run("R-2", Arm.GREEN, held=True)
    assert strap_runs.green_passed(_scenario(), run, [_grade("R-9", GradeValue.PRESENT)]) is False
    assert strap_runs.green_passed(_scenario(), run, []) is False


@pytest.mark.parametrize("results", [
    [],
    [CheckResult(index=1, held=True, detail="")],
    [CheckResult(index=0, held=True, detail=""), CheckResult(index=1, held=True, detail="")],
], ids=["none", "wrong_index", "extra_index"])
def test_green_passed_needs_complete_check_results(results: List[CheckResult]) -> None:
    """D8: green passes only when the result indexes are exactly ``range(len(scenario.checks))``."""
    run = _run("R-2", Arm.GREEN, held=True).model_copy(update={"checks": results})
    assert strap_runs.green_passed(_scenario(), run, [_grade("R-2", GradeValue.PRESENT)]) is False


def test_green_passed_judged_only_scenario() -> None:
    """A scenario without checks needs no check results; its judged items decide."""
    scenario = _scenario().model_copy(update={"checks": []})
    run = _run("R-2", Arm.GREEN, held=True).model_copy(update={"checks": []})
    assert strap_runs.green_passed(scenario, run, [_grade("R-2", GradeValue.PRESENT)]) is True


@pytest.mark.parametrize("value, expected", [
    (GradeValue.PRESENT, False),
    (GradeValue.ABSENT, True),
])
def test_baseline_failed_ignores_missing_results(value: GradeValue, expected: bool) -> None:
    """D8: a missing check result never counts as the failure; the judged item still can."""
    run = _run("R-1", Arm.BASELINE, held=True).model_copy(update={"checks": []})
    assert strap_runs.baseline_failed(_scenario(), run, [_grade("R-1", value)]) is expected


def _draw(behavior: str, scenario: str, reason: DrawReason) -> Draw:
    return Draw(behavior=behavior, scenario=scenario, seed=1, reason=reason, at="2026-10-30T00:00:00Z")


def _pool_spec(retest: Optional[str]) -> SkillSpec:
    """B1 failed green on SC-1 twice and passed on SC-2; B2 failed green on SC-5."""
    runs = [_run("R-1", Arm.GREEN, False), _run("R-2", Arm.GREEN, False, skill_hash="h2"),
            _run("R-3", Arm.GREEN, True, scenario="SC-2"),
            _run("R-4", Arm.GREEN, False, scenario="SC-5", behavior="B2")]
    grades = [_grade(r.id, GradeValue.PRESENT) for r in runs]
    draws = [_draw("B1", "SC-1", DrawReason.INITIAL), _draw("B2", "SC-5", DrawReason.INITIAL)]
    if retest is not None:
        draws += [_draw("B1", "SC-2", DrawReason.RETEST), _draw("B1", retest, DrawReason.RETEST)]
    behaviors = [_behavior("B1", ("SC-1", "SC-2", "SC-3", "SC-4")), _behavior("B2", ("SC-5", "SC-6"))]
    return SkillSpec(name="demo-skill", mode=SpecMode.NEW, plugin_dir="plugins/demo", behaviors=behaviors,
                     draws=draws, runs=runs, grades=grades)


def test_must_pass_failed_greens_without_retest() -> None:
    assert strap_runs.must_pass(_pool_spec(None), "B1") == ["SC-1"]
    assert strap_runs.must_pass(_pool_spec(None), "B2") == ["SC-5"]


def test_must_pass_adds_latest_retest_draw() -> None:
    assert strap_runs.must_pass(_pool_spec("SC-3"), "B1") == ["SC-1", "SC-3"]


def _with_baseline(spec: SkillSpec, held: bool, recorded: bool = True) -> SkillSpec:
    """``spec`` plus a baseline run R-5 of B1 / SC-3 graded PRESENT (the expectation is ABSENT)."""
    if recorded:
        run = _run("R-5", Arm.BASELINE, held, scenario="SC-3", skill_hash="h3")
        grades = [*spec.grades, _grade("R-5", GradeValue.PRESENT)]
    else:
        run = Run(id="R-5", behavior="B1", scenario="SC-3", arm=Arm.BASELINE, skill_hash="h3")
        grades = list(spec.grades)
    doc = spec.model_dump()
    doc["runs"] = [*doc["runs"], run.model_dump()]
    doc["grades"] = [g.model_dump() for g in grades]
    return SkillSpec.model_validate(doc)


@pytest.mark.parametrize("held, recorded, expected", [
    (False, True, ["SC-1"]),
    (True, True, ["SC-1", "SC-3"]),
    (False, False, ["SC-1", "SC-3"]),
], ids=["void", "failed", "unrecorded"])
def test_must_pass_skips_void_retest_draw(held: bool, recorded: bool, expected: List[str]) -> None:
    """D15: a retest draw whose recorded baseline did not fail leaves ``must_pass``; a failed or
    unrecorded baseline keeps it."""
    spec = _with_baseline(_pool_spec("SC-3"), held, recorded)
    assert strap_runs.must_pass(spec, "B1") == expected


def _harness_names(node: ast.AST) -> List[str]:
    """Harness modules an import node names; relative imports count as harness modules."""
    if isinstance(node, ast.ImportFrom) and node.level > 0:
        return [node.module or alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "harness_lib":
        return [node.module.split(".", 1)[1]] if "." in node.module else [a.name for a in node.names]
    if isinstance(node, ast.Import):
        return [a.name.split(".", 1)[-1] for a in node.names if a.name.split(".")[0] == "harness_lib"]
    return []


def _foreign_tops(node: ast.AST) -> List[str]:
    """Absolute, non-harness top-level module names an import node names."""
    if isinstance(node, ast.Import):
        tops = [a.name.split(".")[0] for a in node.names]
    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        tops = [node.module.split(".")[0]]
    else:
        tops = []
    return [t for t in tops if t != "harness_lib"]


def test_strap_runs_imports_only_strap_models_and_stdlib() -> None:
    source = Path(strap_runs.__file__).read_text(encoding="utf-8")
    nodes = [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.Import, ast.ImportFrom))]
    harness = {name for n in nodes for name in _harness_names(n)}
    assert harness <= {"strap_models"}, harness
    foreign = {t for n in nodes for t in _foreign_tops(n)} - set(sys.stdlib_module_names)
    assert not foreign, foreign
