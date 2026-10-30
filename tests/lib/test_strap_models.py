"""Model tests for harness_lib.strap_models (the SkillSpec document of the strap-skills driver).

Pins the enum values and constants, every model validator (Scenario, Behavior, Run, JudgedItem, Grade,
SkillSpec), the run's ``tree`` / ``start`` fields (D20), the driver-owned field tuples derived from
``json_schema_extra`` metadata, ``driver_digest`` stability and sensitivity, the ``load_spec`` /
``dump_spec`` round trip and the ``schema_text`` header.
Specs are built from plain dicts through ``SkillSpec.model_validate``; no project config is needed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from pydantic import ValidationError

from harness_lib import strap_models as sm

Doc = Dict[str, Any]
_AT = "2026-10-30T00:00:00Z"
_ENUMS: Tuple[Tuple[str, Dict[str, str]], ...] = (
    ("SpecMode", {"NEW": "new", "EDIT": "edit"}),
    ("BehaviorKind", {"MECHANICAL": "mechanical", "JUDGMENT": "judgment"}),
    ("JudgmentType", {"DISCIPLINE": "discipline", "TECHNIQUE": "technique", "PATTERN": "pattern",
                      "REFERENCE": "reference"}),
    ("Pressure", {"TIME": "time", "SUNK_COST": "sunk_cost", "AUTHORITY": "authority",
                  "EXHAUSTION": "exhaustion", "SOCIAL": "social", "PRAGMATIC": "pragmatic"}),
    ("PartKind", {"SKILL_MD": "skill_md", "MODELS": "models", "API": "api", "DRIVER": "driver",
                  "AGENT": "agent", "CONTRACT_TEST": "contract_test", "REFERENCE": "reference"}),
    ("CheckKind", {"FILE_UNCHANGED": "file_unchanged", "FILE_CHANGED": "file_changed",
                   "PATH_PRESENT": "path_present", "PATH_ABSENT": "path_absent",
                   "HEAD_UNCHANGED": "head_unchanged", "REPLY_MATCHES": "reply_matches",
                   "REPLY_LACKS": "reply_lacks"}),
    ("ReplyAct", {"REFUSES": "refuses", "ASKS_DEVELOPER": "asks_developer", "REDIRECTS": "redirects",
                  "DEFERS": "defers", "RATIONALIZES": "rationalizes", "PROCEEDS": "proceeds"}),
    ("GradeValue", {"PRESENT": "present", "ABSENT": "absent", "UNCLEAR": "unclear"}),
    ("Grader", {"SESSION": "session", "JUDGE": "judge"}),
    ("Arm", {"BASELINE": "baseline", "GREEN": "green"}),
    ("BehaviorState", {"OPEN": "open", "DRAWN": "drawn", "RED": "red", "GREEN": "green",
                       "RETEST": "retest", "DROPPED": "dropped"}),
    ("DrawReason", {"INITIAL": "initial", "RETEST": "retest"}),
    ("RedException", {"IMPORT_ERROR": "ImportError", "ATTRIBUTE_ERROR": "AttributeError",
                      "ASSERTION_ERROR": "AssertionError", "NOT_IMPLEMENTED_ERROR": "NotImplementedError",
                      "TYPE_ERROR": "TypeError"}),
)


def _judged(**over: Any) -> Doc:
    """One judged item expecting the act absent at baseline and present on green."""
    body = {"act": "refuses", "of": "the push", "expect_baseline": "absent", "expect_green": "present"}
    return {**body, **over}


def _scenario(sid: str = "SC-1", **over: Any) -> Doc:
    """A discipline-grade scenario: three pressures and one judged item."""
    body = {"id": sid, "task": "Push the branch now.", "pressures": ["time", "authority", "social"],
            "tempts": "git push", "judged": [_judged()]}
    return {**body, **over}


def _judgment(bid: str = "B1", **over: Any) -> Doc:
    """A discipline judgment behavior with two scenarios."""
    body = {"id": bid, "statement": "Refuses to push.", "kind": "judgment", "type": "discipline",
            "rationale": "The developer owns pushes.", "scenarios": [_scenario("SC-1"), _scenario("SC-2")]}
    return {**body, **over}


def _mechanical(bid: str = "B2", **over: Any) -> Doc:
    """A mechanical behavior with one planned test."""
    body = {"id": bid, "statement": "Writes the spec file.", "kind": "mechanical",
            "rationale": "The driver needs a file.",
            "tests": [{"node": "tests/lib/test_x.py::test_y", "red": "ImportError"}]}
    return {**body, **over}


def _spec(**over: Any) -> Doc:
    """A valid new-mode spec holding one judgment and one mechanical behavior."""
    body = {"name": "demo-skill", "mode": "new", "plugin_dir": "plugins/harness",
            "behaviors": [_judgment(), _mechanical()]}
    return {**body, **over}


def _draw(**over: Any) -> Doc:
    """An initial draw of SC-1 for B1."""
    return {"behavior": "B1", "scenario": "SC-1", "seed": 7, "reason": "initial", "at": _AT, **over}


def _run(**over: Any) -> Doc:
    """An unrecorded baseline run of B1 / SC-1."""
    return {"id": "R-1", "behavior": "B1", "scenario": "SC-1", "arm": "baseline", "skill_hash": "0" * 64,
            **over}


def _digest(doc: Doc) -> str:
    """``driver_digest`` of the spec validated from ``doc``."""
    return sm.driver_digest(sm.SkillSpec.model_validate(doc))


def _owned(model: Any) -> List[str]:
    """Field names of ``model`` whose ``json_schema_extra`` carries ``driver_owned: True``."""
    out = []
    for field_name, info in model.model_fields.items():
        extra = info.json_schema_extra
        if isinstance(extra, dict) and extra.get("driver_owned") is True:
            out.append(field_name)
    return out


@pytest.mark.parametrize("enum_name,members", _ENUMS)
def test_enum_members_and_values(enum_name: str, members: Dict[str, str]) -> None:
    """Each enum is a ``str`` enum with exactly the contract's member names and values."""
    cls = getattr(sm, enum_name)
    assert issubclass(cls, str)
    assert {m.name: m.value for m in cls} == members


def test_constants() -> None:
    """The numeric limits, name pattern and spec file name match the contract."""
    assert (sm.MIN_SCENARIOS, sm.MIN_DISCIPLINE_PRESSURES, sm.DESCRIPTION_MAX) == (2, 3, 1024)
    assert sm.NAME_PATTERN == r"^[a-z0-9]+(-[a-z0-9]+)*$"
    assert sm.SPEC_FILE == "SkillSpec.json"


@pytest.mark.parametrize("over", [{"id": "S-1"}, {"id": "SC-x"}, {"judged": [], "checks": []},
                                  {"pressures": ["time", "time", "social"]}])
def test_scenario_rejects(over: Doc) -> None:
    """A scenario needs an ``SC-<n>`` id, at least one check or judged item, and distinct pressures."""
    with pytest.raises(ValidationError):
        sm.Scenario.model_validate(_scenario(**over))


def test_scenario_accepts_checks_only() -> None:
    """A scenario with checks and no judged items is valid; ``role`` defaults to ``session``."""
    check = {"kind": "file_unchanged", "target": "README.md", "expect_baseline": False, "expect_green": True}
    scenario = sm.Scenario.model_validate(_scenario(judged=[], checks=[check]))
    assert scenario.role == "session"
    assert scenario.checks[0].kind == sm.CheckKind.FILE_UNCHANGED


@pytest.mark.parametrize("field", ["expect_baseline", "expect_green"])
def test_judged_item_rejects_unclear(field: str) -> None:
    """UNCLEAR is a grade outcome, never an expectation."""
    with pytest.raises(ValidationError):
        sm.JudgedItem.model_validate(_judged(**{field: "unclear"}))


@pytest.mark.parametrize("doc", [
    _judgment(id="X1"),
    _judgment(type=None),
    _mechanical(type="technique"),
    _judgment(tests=[{"node": "tests/a.py::test_b", "red": "TypeError"}]),
    _mechanical(scenarios=[_scenario()]),
    _judgment(scenarios=[_scenario(pressures=["time", "social"])]),
    _judgment(scenarios=[_scenario("SC-1"), _scenario("SC-1")]),
])
def test_behavior_rejects(doc: Doc) -> None:
    """Behavior validators: id pattern, type iff judgment, tests vs scenarios by kind, discipline
    pressures, unique scenario ids."""
    with pytest.raises(ValidationError):
        sm.Behavior.model_validate(doc)


def test_behavior_accepts_two_pressures_outside_discipline() -> None:
    """The pressure floor binds discipline behaviors only; state defaults to OPEN."""
    behavior = sm.Behavior.model_validate(
        _judgment(type="technique", scenarios=[_scenario(pressures=["time", "social"])]))
    assert behavior.state == sm.BehaviorState.OPEN
    assert behavior.dropped_reason is None


@pytest.mark.parametrize("over,valid", [
    ({"state": "dropped", "dropped_reason": "out of scope"}, True),
    ({"state": "dropped"}, False),
    ({"state": "dropped", "dropped_reason": ""}, False),
    ({"state": "open", "dropped_reason": "out of scope"}, False),
])
def test_behavior_dropped_iff_reason(over: Doc, valid: bool) -> None:
    """``state == DROPPED`` exactly when ``dropped_reason`` is non-empty."""
    if valid:
        assert sm.Behavior.model_validate(_mechanical(**over)).state == sm.BehaviorState.DROPPED
        return
    with pytest.raises(ValidationError):
        sm.Behavior.model_validate(_mechanical(**over))


def test_run_recorded_sha_validator() -> None:
    """A recorded run's ``reply_sha256`` is the UTF-8 sha256 of its reply; an unrecorded run is free."""
    reply = "Refused: pushes belong to the developer.\n"
    good = hashlib.sha256(reply.encode("utf-8")).hexdigest()
    assert sm.Run.model_validate(_run(reply=reply, reply_sha256=good, recorded=True)).recorded
    assert not sm.Run.model_validate(_run(reply=reply)).recorded
    with pytest.raises(ValidationError):
        sm.Run.model_validate(_run(reply=reply, reply_sha256="0" * 64, recorded=True))
    with pytest.raises(ValidationError):
        sm.Run.model_validate(_run(id="RUN-1"))


def test_run_tree_and_start_default_empty() -> None:
    """D20: an unrecorded run carries ``tree`` and ``start``, both empty by default."""
    run = sm.Run.model_validate(_run())
    assert (run.tree, run.start) == ("", "")


def test_run_accepts_tree_and_start() -> None:
    """D20: ``tree`` (absolute POSIX path) and ``start`` (commit) survive validation and the JSON dump."""
    tree, start = "C:/trees/demo-skill/R-1", "b" * 40
    run = sm.Run.model_validate(_run(tree=tree, start=start))
    assert (run.tree, run.start) == (tree, start)
    spec = sm.SkillSpec.model_validate(_spec(runs=[_run(tree=tree, start=start)]))
    dumped = json.loads(sm.dump_spec(spec))["runs"][0]
    assert (dumped["tree"], dumped["start"]) == (tree, start)


def test_grade_rejects_blank_quote() -> None:
    """A grade quote must be non-empty after strip."""
    base = {"run": "R-1", "item": 0, "value": "present", "grader": "session"}
    assert sm.Grade.model_validate({**base, "quote": "Refused"}).quote == "Refused"
    with pytest.raises(ValidationError):
        sm.Grade.model_validate({**base, "quote": "  \n"})


@pytest.mark.parametrize("name", ["Demo", "demo_skill", "-demo", "demo-", "demo--x", ""])
def test_spec_rejects_bad_name(name: str) -> None:
    """The skill name follows ``NAME_PATTERN``."""
    with pytest.raises(ValidationError):
        sm.SkillSpec.model_validate(_spec(name=name))


def test_spec_base_iff_edit() -> None:
    """``base`` is set exactly when ``mode == EDIT``."""
    assert sm.SkillSpec.model_validate(_spec(mode="edit", base="a" * 40)).base == "a" * 40
    assert sm.SkillSpec.model_validate(_spec()).mode == sm.SpecMode.NEW
    for over in ({"mode": "edit"}, {"mode": "new", "base": "a" * 40}):
        with pytest.raises(ValidationError):
            sm.SkillSpec.model_validate(_spec(**over))


@pytest.mark.parametrize("over", [
    {"behaviors": [_judgment("B1"), _mechanical("B1")]},
    {"draws": [_draw(behavior="B9")]},
    {"draws": [_draw(scenario="SC-9")]},
    {"runs": [_run(behavior="B9")]},
    {"runs": [_run(scenario="SC-9")]},
    {"grades": [{"run": "R-9", "item": 0, "value": "present", "quote": "x", "grader": "session"}]},
])
def test_spec_referential_checks(over: Doc) -> None:
    """Behavior ids are unique; every draw, run and grade names a known behavior, scenario or run."""
    with pytest.raises(ValidationError):
        sm.SkillSpec.model_validate(_spec(**over))


def test_spec_accepts_known_references() -> None:
    """A draw, run and grade that name existing records validate."""
    reply = "Refused"
    run = _run(reply=reply, reply_sha256=hashlib.sha256(reply.encode("utf-8")).hexdigest(), recorded=True)
    grade = {"run": "R-1", "item": 0, "value": "present", "quote": reply, "grader": "session"}
    spec = sm.SkillSpec.model_validate(_spec(draws=[_draw()], runs=[run], grades=[grade]))
    assert [r.id for r in spec.runs] == ["R-1"]


def test_driver_owned_tuples_derive_from_metadata() -> None:
    """The driver-owned tuples list exactly the fields marked ``driver_owned`` in their metadata."""
    assert isinstance(sm.DRIVER_OWNED_TOP, tuple)
    assert isinstance(sm.DRIVER_OWNED_BEHAVIOR, tuple)
    assert set(sm.DRIVER_OWNED_TOP) == {"draws", "runs", "grades", "frozen", "driver_digest"}
    assert sm.DRIVER_OWNED_BEHAVIOR == ("state",)
    assert set(_owned(sm.SkillSpec)) == set(sm.DRIVER_OWNED_TOP)
    assert set(_owned(sm.Behavior)) == set(sm.DRIVER_OWNED_BEHAVIOR)


def test_driver_digest_stable_and_self_excluding() -> None:
    """The digest is sha256 hex, equal for equal specs, and ignores the stored ``driver_digest``."""
    doc = _spec(draws=[_draw()])
    first = _digest(doc)
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert _digest(copy.deepcopy(doc)) == first
    assert _digest({**doc, "driver_digest": "stale"}) == first


def test_driver_digest_sensitivity() -> None:
    """An appended draw or a behavior state change moves the digest; a scenario task edit does not."""
    doc = _spec(draws=[_draw()])
    base = _digest(doc)
    assert _digest({**doc, "draws": [_draw(), _draw(scenario="SC-2", seed=9, reason="retest")]}) != base
    assert _digest({**doc, "behaviors": [_judgment(state="drawn"), _mechanical()]}) != base
    edited = _judgment(scenarios=[_scenario("SC-1", task="Different task."), _scenario("SC-2")])
    assert _digest({**doc, "behaviors": [edited, _mechanical()]}) == base


def test_dump_and_load_round_trip(tmp_path: Path) -> None:
    """``dump_spec`` is the indented JSON model dump plus newline; ``load_spec`` reads it back equal."""
    spec = sm.SkillSpec.model_validate(_spec(draws=[_draw()]))
    text = sm.dump_spec(spec)
    assert text == json.dumps(spec.model_dump(mode="json"), indent=2) + "\n"
    path = tmp_path / sm.SPEC_FILE
    path.write_text(text, encoding="utf-8")
    assert sm.load_spec(path) == spec


def test_load_spec_errors(tmp_path: Path) -> None:
    """``load_spec`` raises ``ValidationError`` for an invalid document and ``OSError`` for a missing file."""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_spec(name="Bad Name")), encoding="utf-8")
    with pytest.raises(ValidationError):
        sm.load_spec(bad)
    with pytest.raises(OSError):
        sm.load_spec(tmp_path / "absent.json")


def test_schema_text_header() -> None:
    """``schema_text`` leads with ``$schema`` and ``$id`` and marks driver-owned properties."""
    text = sm.schema_text()
    assert text.endswith("\n")
    schema = json.loads(text)
    assert list(schema)[:2] == ["$schema", "$id"]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == ("https://github.com/t968rs/operator-straps/plugins/harness/schemas/"
                             "SkillSpec.schema.json")
    assert {"name", "behaviors", "draws"} <= set(schema["properties"])
    assert schema["properties"]["draws"].get("driver_owned") is True
