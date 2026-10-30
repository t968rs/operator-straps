"""Behavioral tests for harness_lib.strap_api over a throwaway project with an activated config.

Pins the spec location under ``artifacts.plans/strap/<name>/SkillSpec.json``, the validating factories,
id assignment (``B<n>`` per spec, ``SC-<n>`` unique across the spec), the refusals of ``update_behavior``
(driver-owned fields, frozen specs), ``drop_behavior``, ``record_run`` (once only, reply sha256), the
``grade`` refusals, the driver-digest tamper refusal and that a refused operation leaves the file
byte-for-byte unchanged. Specs are seeded through ``strap_models`` and ``dump_spec`` directly, with
``driver_digest`` set from ``driver_digest``, so no test depends on ``strap.py``.

Amendments pinned here: the exact ``__all__`` (D8), the drawn-scenario lock (D10), ``add_part`` (D14) and
the session-grade refusal on a judge spec (D16).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

import harness_lib.strap_api as strap_api
from harness_lib.config import activate, load_config
from harness_lib.strap_api import (
    StrapError,
    add_behavior,
    add_part,
    add_scenario,
    drop_behavior,
    grade,
    new_behavior,
    new_check,
    new_judged,
    new_scenario,
    new_test,
    record_run,
    spec_path,
    update_behavior,
)
from harness_lib.strap_models import (
    Arm,
    Behavior,
    BehaviorKind,
    BehaviorState,
    CheckKind,
    Draw,
    DrawReason,
    Frozen,
    Grader,
    GradeValue,
    JudgedItem,
    JudgmentType,
    Part,
    PartKind,
    RedException,
    ReplyAct,
    Run,
    Scenario,
    SkillSpec,
    SpecMode,
    driver_digest,
    dump_spec,
    load_spec,
)

NAME = "demo-skill"
PLANS = "notes/plans"
AT = "2026-10-30T00:00:00Z"
HASH = "0" * 64
REPLY = "Refusing to edit the Decision line.\nThe developer   decides bubbles."
QUOTE = "The developer decides"


@pytest.fixture()
def project(make_project) -> Path:
    """A project whose ``artifacts.plans`` is ``notes/plans``, activated for the test."""
    root = make_project(config={"artifacts": {"plans": PLANS}})
    activate(load_config(root))
    return root


def _file(root: Path) -> Path:
    """The spec file location computed by hand from the configured plans directory."""
    return root / PLANS / "strap" / NAME / "SkillSpec.json"


def _scenario(sid: str) -> Scenario:
    """A judgment scenario with one judged item."""
    item = JudgedItem(act=ReplyAct.REFUSES, of="the edit", expect_baseline=GradeValue.ABSENT,
                      expect_green=GradeValue.PRESENT)
    return Scenario(id=sid, task="Mark I2 decided.", tempts="edits the Decision line", judged=[item])


def _behavior() -> Behavior:
    """B1: a drawn technique behavior with scenarios SC-1 and SC-2."""
    return Behavior(id="B1", statement="Never writes a Decision line", kind=BehaviorKind.JUDGMENT,
                    type=JudgmentType.TECHNIQUE, rationale="intent only", state=BehaviorState.DRAWN,
                    scenarios=[_scenario("SC-1"), _scenario("SC-2")])


def _runs() -> List[Run]:
    """R-1 unrecorded and R-2 recorded with ``REPLY``, both baseline runs of B1 / SC-1."""
    sha = hashlib.sha256(REPLY.encode("utf-8")).hexdigest()
    open_run = Run(id="R-1", behavior="B1", scenario="SC-1", arm=Arm.BASELINE, skill_hash=HASH)
    done = Run(id="R-2", behavior="B1", scenario="SC-1", arm=Arm.BASELINE, skill_hash=HASH, reply=REPLY,
               reply_sha256=sha, recorded=True)
    return [open_run, done]


def _write(root: Path, spec: SkillSpec) -> Path:
    """Stamp the digest and write ``spec`` where the API looks for it."""
    stamped = spec.model_copy(update={"driver_digest": driver_digest(spec)})
    path = _file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_spec(stamped), encoding="utf-8", newline="\n")
    return path


def _seed(root: Path, full: bool = True, judge: bool = False, frozen: Optional[Frozen] = None) -> Path:
    """Write the seeded spec: empty, or B1 with one draw and runs R-1 / R-2."""
    body: Dict[str, Any] = {}
    if full:
        draw = Draw(behavior="B1", scenario="SC-1", seed=7, reason=DrawReason.INITIAL, at=AT)
        body = {"behaviors": [_behavior()], "draws": [draw], "runs": _runs()}
    spec = SkillSpec(name=NAME, mode=SpecMode.NEW, judge=judge, plugin_dir="plugins/demo", frozen=frozen,
                     **body)
    return _write(root, spec)


def _mechanical() -> Behavior:
    return new_behavior("Writes the file", "mechanical", "file state shows it",
                        tests=[new_test("tests/test_a.py::test_a", "AssertionError")])


def _judgment() -> Behavior:
    return new_behavior("Asks first", "judgment", "intent only", type="technique")


def _digest_current(spec: SkillSpec) -> bool:
    return spec.driver_digest == driver_digest(spec)


def test_spec_path_under_configured_plans(project: Path) -> None:
    assert spec_path(NAME).resolve() == _file(project).resolve()


def test_strap_error_is_value_error() -> None:
    assert issubclass(StrapError, ValueError)


def test_factories_build_validated_models() -> None:
    behavior = _judgment()
    check = new_check("file_unchanged", "docs/m.md", baseline=False, green=True)
    item = new_judged("redirects", "bubble-stamp", baseline="absent", green="present")
    pressures = ["authority", "time", "pragmatic"]
    scenario = new_scenario("Mark it decided.", "edits the line", pressures=pressures, checks=[check],
                            judged=[item])
    assert (behavior.id, behavior.kind) == ("B0", BehaviorKind.JUDGMENT)
    assert behavior.type == JudgmentType.TECHNIQUE
    assert (scenario.id, scenario.role, scenario.fixture) == ("SC-0", "session", None)
    check = scenario.checks[0]
    assert (check.kind, check.expect_baseline, check.expect_green) == (CheckKind.FILE_UNCHANGED, False, True)
    assert scenario.judged[0].expect_green == GradeValue.PRESENT
    assert new_test("tests/test_a.py::test_a", "AssertionError").red == RedException.ASSERTION_ERROR


@pytest.mark.parametrize("build", [
    lambda: new_behavior("s", "judgment", "r"),
    lambda: new_behavior("s", "mechanical", "r", type="technique"),
    lambda: new_scenario("t", "w"),
    lambda: new_judged("refuses", "x", baseline="unclear", green="present"),
    lambda: new_test("tests/test_a.py", "AssertionError"),
], ids=["judgment-no-type", "mechanical-with-type", "scenario-empty", "judged-unclear", "test-no-node"])
def test_factories_reject_invalid(build: Callable[[], Any]) -> None:
    with pytest.raises(ValueError):
        build()


def test_add_behavior_assigns_b1_b2_and_writes(project: Path) -> None:
    _seed(project, full=False)
    add_behavior(NAME, _mechanical())
    spec = add_behavior(NAME, _judgment())
    assert isinstance(spec, SkillSpec)
    assert [b.id for b in spec.behaviors] == ["B1", "B2"]
    assert load_spec(_file(project)) == spec


def test_add_scenario_ids_unique_across_spec(project: Path) -> None:
    _seed(project, full=False)
    add_behavior(NAME, _judgment())
    add_behavior(NAME, _judgment())
    scenario = new_scenario("t", "w", judged=[new_judged("refuses", "x", baseline="absent", green="present")])
    add_scenario(NAME, "B1", scenario)
    add_scenario(NAME, "B1", scenario)
    spec = add_scenario(NAME, "B2", scenario)
    ids = [[s.id for s in b.scenarios] for b in spec.behaviors]
    assert ids == [["SC-1", "SC-2"], ["SC-3"]]


def test_update_behavior_changes_authored_field(project: Path) -> None:
    _seed(project)
    spec = update_behavior(NAME, "B1", statement="Never stamps a decision")
    assert spec.behaviors[0].statement == "Never stamps a decision"
    assert load_spec(_file(project)).behaviors[0].statement == "Never stamps a decision"


def test_update_behavior_refuses_driver_owned_field(project: Path) -> None:
    path = _seed(project)
    before = path.read_bytes()
    with pytest.raises(StrapError, match="state is driver-owned"):
        update_behavior(NAME, "B1", state=BehaviorState.GREEN)
    assert path.read_bytes() == before


def test_update_behavior_refuses_frozen_spec(project: Path) -> None:
    path = _seed(project, frozen=Frozen(skill_hash=HASH, grader=Grader.SESSION, at=AT))
    before = path.read_bytes()
    with pytest.raises(StrapError):
        update_behavior(NAME, "B1", statement="late change")
    assert path.read_bytes() == before


def test_drop_behavior_sets_state_and_redigests(project: Path) -> None:
    path = _seed(project)
    old = load_spec(path).driver_digest
    spec = drop_behavior(NAME, "B1", "superseded by B2")
    dropped = spec.behaviors[0]
    assert (dropped.state, dropped.dropped_reason) == (BehaviorState.DROPPED, "superseded by B2")
    assert _digest_current(spec) and spec.driver_digest != old
    assert load_spec(path) == spec


def test_record_run_sets_reply_sha_and_redigests(project: Path) -> None:
    path = _seed(project)
    spec = record_run(NAME, "R-1", "done\n")
    run = spec.runs[0]
    assert (run.recorded, run.reply) == (True, "done\n")
    assert run.reply_sha256 == hashlib.sha256(b"done\n").hexdigest()
    assert _digest_current(spec)
    assert load_spec(path) == spec


def test_record_run_refuses_recorded_run(project: Path) -> None:
    path = _seed(project)
    before = path.read_bytes()
    with pytest.raises(StrapError, match="R-2 already recorded"):
        record_run(NAME, "R-2", "again")
    assert path.read_bytes() == before


def test_grade_appends_with_normalized_quote(project: Path) -> None:
    path = _seed(project)
    spec = grade(NAME, "R-2", 0, "present", QUOTE)
    assert len(spec.grades) == 1
    given = spec.grades[0]
    assert (given.run, given.item) == ("R-2", 0)
    assert (given.value, given.grader) == (GradeValue.PRESENT, Grader.SESSION)
    assert _digest_current(spec)
    assert load_spec(path) == spec


@pytest.mark.parametrize("run_id, item, quote, grader, match", [
    ("R-1", 0, QUOTE, "session", None),
    ("R-2", 1, QUOTE, "session", None),
    ("R-2", -1, QUOTE, "session", None),
    ("R-2", 0, "edits the Decision line", "session", "quote not found in R-2"),
    ("R-2", 0, QUOTE, "judge", None),
], ids=["unrecorded-run", "item-past-end", "item-negative", "quote-missing", "judge-on-session-spec"])
def test_grade_refusals(project: Path, run_id: str, item: int, quote: str, grader: str,
                        match: Optional[str]) -> None:
    path = _seed(project)
    before = path.read_bytes()
    with pytest.raises(StrapError, match=match):
        grade(NAME, run_id, item, "present", quote, grader=grader)
    assert path.read_bytes() == before


def test_grade_refuses_second_grade_of_item(project: Path) -> None:
    path = _seed(project)
    grade(NAME, "R-2", 0, "present", QUOTE)
    before = path.read_bytes()
    with pytest.raises(StrapError):
        grade(NAME, "R-2", 0, "absent", QUOTE)
    assert path.read_bytes() == before


def test_judge_grade_accepted_on_judge_spec(project: Path) -> None:
    _seed(project, judge=True)
    spec = grade(NAME, "R-2", 0, "present", QUOTE, grader="judge")
    assert spec.grades[0].grader == Grader.JUDGE


@pytest.mark.parametrize("op", [
    lambda: add_behavior(NAME, _judgment()),
    lambda: update_behavior(NAME, "B1", statement="x"),
    lambda: record_run(NAME, "R-1", "x"),
], ids=["add_behavior", "update_behavior", "record_run"])
def test_hand_edited_draws_refused(project: Path, op: Callable[[], Any]) -> None:
    path = _seed(project)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["draws"][0]["seed"] = 99
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    before = path.read_bytes()
    with pytest.raises(StrapError, match="driver-owned fields changed outside strap.py"):
        op()
    assert path.read_bytes() == before


def _unvalidated_behavior() -> Behavior:
    """A judgment behavior without ``type``, built past the validators."""
    return Behavior.model_construct(id="B0", statement="s", kind=BehaviorKind.JUDGMENT, type=None,
                                    rationale="r", tests=[], scenarios=[], state=BehaviorState.OPEN,
                                    dropped_reason=None)


@pytest.mark.parametrize("op", [
    lambda: update_behavior(NAME, "B1", kind=BehaviorKind.MECHANICAL),
    lambda: add_behavior(NAME, _unvalidated_behavior()),
    lambda: add_scenario(NAME, "B9", _scenario("SC-0")),
], ids=["update-breaks-behavior", "add-unvalidated-behavior", "scenario-unknown-behavior"])
def test_failed_operation_writes_nothing(project: Path, op: Callable[[], Any]) -> None:
    path = _seed(project)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        op()
    assert path.read_bytes() == before


API_NAMES = {
    "StrapError", "spec_path", "new_behavior", "new_test", "new_scenario", "new_check", "new_judged",
    "add_behavior", "update_behavior", "drop_behavior", "add_scenario", "add_part", "grade",
}
SKILL_MD = "plugins/demo/skills/demo-skill/SKILL.md"


def test_all_lists_exactly_the_api_names() -> None:
    assert set(strap_api.__all__) == API_NAMES
    assert len(strap_api.__all__) == len(API_NAMES)


@pytest.mark.parametrize("hidden", ["record_run", "driver_digest", "dump_spec"])
def test_all_omits_driver_names(hidden: str) -> None:
    assert hidden not in strap_api.__all__


@pytest.mark.parametrize("changes", [
    {"scenarios": [_scenario("SC-1")]},
    {"kind": "mechanical"},
    {"type": "pattern"},
], ids=["scenarios", "kind", "type"])
def test_update_drawn_behavior_locked(project: Path, changes: Dict[str, Any]) -> None:
    path = _seed(project)
    before = path.read_bytes()
    with pytest.raises(StrapError, match="B1 is drawn"):
        update_behavior(NAME, "B1", **changes)
    assert path.read_bytes() == before


def test_add_scenario_on_drawn_behavior(project: Path) -> None:
    path = _seed(project)
    scenario = new_scenario("t", "w", judged=[new_judged("refuses", "x", baseline="absent", green="present")])
    spec = add_scenario(NAME, "B1", scenario)
    assert [s.id for s in spec.behaviors[0].scenarios] == ["SC-1", "SC-2", "SC-3"]
    assert _digest_current(spec)
    assert load_spec(path) == spec


def test_add_part_appends_and_writes(project: Path) -> None:
    path = _seed(project)
    spec = add_part(NAME, "skill_md", SKILL_MD)
    assert spec.parts == [Part(kind=PartKind.SKILL_MD, path=SKILL_MD)]
    assert _digest_current(spec)
    assert load_spec(path) == spec


def test_add_part_refuses_duplicate_path(project: Path) -> None:
    path = _seed(project)
    add_part(NAME, "skill_md", SKILL_MD)
    before = path.read_bytes()
    with pytest.raises(StrapError):
        add_part(NAME, "reference", SKILL_MD)
    assert path.read_bytes() == before


def test_session_grade_refused_on_judge_spec(project: Path) -> None:
    path = _seed(project, judge=True)
    before = path.read_bytes()
    with pytest.raises(StrapError, match=re.escape("judge spec: grade with grader='judge'")):
        grade(NAME, "R-2", 0, "present", QUOTE, grader="session")
    assert path.read_bytes() == before
