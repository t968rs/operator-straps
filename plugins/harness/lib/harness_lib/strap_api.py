"""strap-skills: the author's API over ``SkillSpec``, as validating factories and piecewise operations.

Every operation takes the skill name first, loads ``<plans>/strap/<name>/SkillSpec.json``, refuses a spec
whose driver-owned fields no longer match the stored ``driver_digest`` (or one already frozen), applies one
change, re-validates the whole document from its dump, stamps a fresh digest and only then writes the file.
A refusal or a failed validation writes nothing.

``__all__`` is the surface ``skill_api.py`` binds for an api heredoc. ``record_run`` stays importable for
``strap.py record-run`` but is left out of it, so an api session cannot record a reply. Requires an
activated config.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Sequence, Union

from harness_lib.config import active
from harness_lib.strap_models import (
    DRIVER_OWNED_BEHAVIOR, NAME_PATTERN, SPEC_FILE, Behavior, BehaviorKind, BehaviorState, Check, CheckKind,
    Grade, Grader, GradeValue, JudgedItem, JudgmentType, Part, PartKind, PlannedTest, Pressure, RedException,
    ReplyAct, Run, Scenario, SkillSpec, driver_digest, dump_spec, load_spec,
)
from harness_lib.strap_runs import quote_found

__all__ = [
    "StrapError", "spec_path", "new_behavior", "new_test", "new_scenario", "new_check", "new_judged",
    "add_behavior", "update_behavior", "drop_behavior", "add_scenario", "add_part", "grade",
]

_TAMPERED = "driver-owned fields changed outside strap.py"
_LOCKED_WHEN_DRAWN = ("scenarios", "kind", "type")
_BEHAVIOR_PREFIX = "B"
_SCENARIO_PREFIX = "SC-"
_JUDGE_SPEC = "judge spec: grade with grader='judge'"


class StrapError(ValueError):
    """A refused strap-skills operation; the message names the defect."""


def spec_path(name: str) -> Path:
    """Location of the skill's spec: ``<artifacts.plans>/strap/<name>/SkillSpec.json``."""
    if not re.fullmatch(NAME_PATTERN, name):
        raise StrapError(f"{name!r} is not a skill name")
    cfg = active()
    return cfg.path(cfg.artifacts.plans) / "strap" / name / SPEC_FILE


# --- factories ------------------------------------------------------------------------------------------

def new_behavior(statement: str, kind: Union[BehaviorKind, str], rationale: str,
                 type: Optional[Union[JudgmentType, str]] = None,
                 tests: Sequence[PlannedTest] = ()) -> Behavior:
    """A validated behavior with the placeholder id ``B0``; ``add_behavior`` assigns the real one."""
    return Behavior(id=f"{_BEHAVIOR_PREFIX}0", statement=statement, kind=kind, type=type,
                    rationale=rationale, tests=list(tests))


def new_test(node: str, red: Union[RedException, str]) -> PlannedTest:
    """A planned pytest node and the exception it raises before the code exists."""
    return PlannedTest(node=node, red=red)


def new_scenario(task: str, tempts: str, pressures: Sequence[Union[Pressure, str]] = (),
                 checks: Sequence[Check] = (), judged: Sequence[JudgedItem] = (),
                 fixture: Optional[str] = None, role: str = "session") -> Scenario:
    """A validated scenario with the placeholder id ``SC-0``; ``add_scenario`` assigns the real one."""
    return Scenario(id=f"{_SCENARIO_PREFIX}0", task=task, tempts=tempts, pressures=list(pressures),
                    checks=list(checks), judged=list(judged), fixture=fixture, role=role)


def new_check(kind: Union[CheckKind, str], target: str, baseline: bool, green: bool) -> Check:
    """A machine-evaluated check and the fact each arm is expected to observe."""
    return Check(kind=kind, target=target, expect_baseline=baseline, expect_green=green)


def new_judged(act: Union[ReplyAct, str], of: str, baseline: Union[GradeValue, str],
               green: Union[GradeValue, str]) -> JudgedItem:
    """A judged reply act and its expected grade on each arm."""
    return JudgedItem(act=act, of=of, expect_baseline=baseline, expect_green=green)


# --- load, re-validate, write ---------------------------------------------------------------------------

def _load(name: str) -> SkillSpec:
    """The spec as stored, refused when missing, hand-edited in driver-owned fields, or frozen."""
    path = spec_path(name)
    if not path.is_file():
        raise StrapError(f"no spec for {name} at {path.as_posix()}")
    spec = load_spec(path)
    if spec.driver_digest != driver_digest(spec):
        raise StrapError(_TAMPERED)
    if spec.frozen is not None:
        raise StrapError(f"{name} is frozen")
    return spec


def _commit(name: str, changed: SkillSpec) -> SkillSpec:
    """Re-validate ``changed`` from its dump, stamp the digest, then write; nothing is written on failure."""
    checked = SkillSpec.model_validate(changed.model_dump())
    stamped = checked.model_copy(update={"driver_digest": driver_digest(checked)})
    spec_path(name).write_text(dump_spec(stamped), encoding="utf-8", newline="\n")
    return stamped


def _apply(name: str, change: Callable[[SkillSpec], SkillSpec]) -> SkillSpec:
    """Load ``name``'s spec, apply ``change`` and commit the result."""
    return _commit(name, change(_load(name)))


# --- lookups --------------------------------------------------------------------------------------------

def _next_id(prefix: str, taken: Iterable[str]) -> str:
    """``prefix`` plus one more than the highest number already used with it."""
    numbers = [int(ident[len(prefix):]) for ident in taken if ident[len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1}"


def _scenario_ids(spec: SkillSpec) -> List[str]:
    return [scenario.id for behavior in spec.behaviors for scenario in behavior.scenarios]


def _behavior_index(spec: SkillSpec, behavior_id: str) -> int:
    for index, behavior in enumerate(spec.behaviors):
        if behavior.id == behavior_id:
            return index
    raise StrapError(f"unknown behavior {behavior_id}")


def _run_index(spec: SkillSpec, run_id: str) -> int:
    for index, run in enumerate(spec.runs):
        if run.id == run_id:
            return index
    raise StrapError(f"unknown run {run_id}")


def _with_behavior(spec: SkillSpec, index: int, behavior: Behavior) -> SkillSpec:
    behaviors = list(spec.behaviors)
    behaviors[index] = behavior
    return spec.model_copy(update={"behaviors": behaviors})


def _scenario_of_run(spec: SkillSpec, run: Run) -> Scenario:
    behavior = spec.behaviors[_behavior_index(spec, run.behavior)]
    return next(s for s in behavior.scenarios if s.id == run.scenario)


# --- authored operations --------------------------------------------------------------------------------

def _renumbered(spec: SkillSpec, scenarios: Sequence[Scenario]) -> List[Scenario]:
    """``scenarios`` with fresh ids that continue the spec-wide ``SC-<n>`` sequence."""
    taken = _scenario_ids(spec)
    out: List[Scenario] = []
    for scenario in scenarios:
        fresh = _next_id(_SCENARIO_PREFIX, taken)
        taken.append(fresh)
        out.append(scenario.model_copy(update={"id": fresh}))
    return out


def add_behavior(name: str, behavior: Behavior) -> SkillSpec:
    """Append ``behavior`` as the next ``B<n>``, in state ``open``."""
    if not isinstance(behavior, Behavior):
        raise StrapError("add_behavior takes a Behavior built by new_behavior")

    def change(spec: SkillSpec) -> SkillSpec:
        ident = _next_id(_BEHAVIOR_PREFIX, (b.id for b in spec.behaviors))
        fresh = behavior.model_copy(update={"id": ident, "state": BehaviorState.OPEN,
                                            "scenarios": _renumbered(spec, behavior.scenarios)})
        return spec.model_copy(update={"behaviors": [*spec.behaviors, fresh]})

    return _apply(name, change)


def _refuse_fields(spec: SkillSpec, behavior_id: str, fields: Iterable[str]) -> None:
    """Refuse driver-owned fields, the assigned id, and the locked fields of a drawn behavior."""
    drawn = any(draw.behavior == behavior_id for draw in spec.draws)
    for field in fields:
        if field in DRIVER_OWNED_BEHAVIOR:
            raise StrapError(f"{field} is driver-owned")
        if field == "id":
            raise StrapError("id is assigned by add_behavior")
        if drawn and field in _LOCKED_WHEN_DRAWN:
            raise StrapError(f"{behavior_id} is drawn")


def update_behavior(name: str, behavior_id: str, **changes: Any) -> SkillSpec:
    """Change authored fields of one behavior; enum fields accept members or their string values."""
    def change(spec: SkillSpec) -> SkillSpec:
        index = _behavior_index(spec, behavior_id)
        _refuse_fields(spec, behavior_id, changes)
        data = spec.behaviors[index].model_dump()
        data.update(changes)
        return _with_behavior(spec, index, Behavior.model_validate(data))

    return _apply(name, change)


def drop_behavior(name: str, behavior_id: str, reason: str) -> SkillSpec:
    """Set the behavior's state to ``dropped`` with ``reason``; the one api path that writes a state."""
    def change(spec: SkillSpec) -> SkillSpec:
        index = _behavior_index(spec, behavior_id)
        data = spec.behaviors[index].model_dump()
        data.update(state=BehaviorState.DROPPED, dropped_reason=reason)
        return _with_behavior(spec, index, Behavior.model_validate(data))

    return _apply(name, change)


def add_scenario(name: str, behavior_id: str, scenario: Scenario) -> SkillSpec:
    """Append ``scenario`` to the behavior as the next ``SC-<n>``, unique across the spec."""
    if not isinstance(scenario, Scenario):
        raise StrapError("add_scenario takes a Scenario built by new_scenario")

    def change(spec: SkillSpec) -> SkillSpec:
        index = _behavior_index(spec, behavior_id)
        target = spec.behaviors[index]
        scenarios = [*target.scenarios, *_renumbered(spec, [scenario])]
        return _with_behavior(spec, index, target.model_copy(update={"scenarios": scenarios}))

    return _apply(name, change)


def add_part(name: str, kind: Union[PartKind, str], path: str) -> SkillSpec:
    """Append a deliverable part; a path already listed is refused."""
    part = Part(kind=kind, path=path)

    def change(spec: SkillSpec) -> SkillSpec:
        if any(existing.path == part.path for existing in spec.parts):
            raise StrapError(f"{part.path} is already a part")
        return spec.model_copy(update={"parts": [*spec.parts, part]})

    return _apply(name, change)


# --- driver and grading operations ----------------------------------------------------------------------

def record_run(name: str, run_id: str, reply: str) -> SkillSpec:
    """Store the reply of an unrecorded run with its sha256; ``strap.py record-run`` fills diff and checks."""
    def change(spec: SkillSpec) -> SkillSpec:
        index = _run_index(spec, run_id)
        run = spec.runs[index]
        if run.recorded:
            raise StrapError(f"{run_id} already recorded")
        sha = hashlib.sha256(reply.encode("utf-8")).hexdigest()
        runs = list(spec.runs)
        runs[index] = run.model_copy(update={"reply": reply, "reply_sha256": sha, "recorded": True})
        return spec.model_copy(update={"runs": runs})

    return _apply(name, change)


def _as_grader(grader: Union[Grader, str]) -> Grader:
    try:
        return Grader(grader)
    except ValueError:
        raise StrapError(f"unknown grader {grader!r}") from None


def _refuse_grader(spec: SkillSpec, grader: Grader) -> None:
    """A judge spec takes judge grades only; a session spec takes session grades only."""
    if spec.judge and grader != Grader.JUDGE:
        raise StrapError(_JUDGE_SPEC)
    if not spec.judge and grader == Grader.JUDGE:
        raise StrapError("judge grades need a spec created with --judge")


def _gradable_run(spec: SkillSpec, run_id: str, item: int) -> Run:
    """The recorded run ``run_id`` whose scenario has judged item ``item`` not yet graded."""
    run = spec.runs[_run_index(spec, run_id)]
    if not run.recorded:
        raise StrapError(f"{run_id} is not recorded")
    count = len(_scenario_of_run(spec, run).judged)
    if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item < count:
        raise StrapError(f"{run_id} has no judged item {item!r} (items 0..{count - 1})")
    if any(given.run == run_id and given.item == item for given in spec.grades):
        raise StrapError(f"{run_id} item {item} already graded")
    return run


def grade(name: str, run_id: str, item: int, value: Union[GradeValue, str], quote: str,
          grader: Union[Grader, str] = "session") -> SkillSpec:
    """Grade judged item ``item`` of a recorded run; ``quote`` must appear in the reply, whitespace-folded."""
    who = _as_grader(grader)

    def change(spec: SkillSpec) -> SkillSpec:
        _refuse_grader(spec, who)
        run = _gradable_run(spec, run_id, item)
        if not quote_found(quote, run.reply):
            raise StrapError(f"quote not found in {run_id}")
        given = Grade(run=run_id, item=item, value=value, quote=quote, grader=who)
        return spec.model_copy(update={"grades": [*spec.grades, given]})

    return _apply(name, change)
