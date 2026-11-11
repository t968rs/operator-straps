"""strap-skills: the author's API over ``SkillSpec``, as validating factories and piecewise operations.

Every operation takes the skill name first, loads ``<plans>/strap/<name>/SkillSpec.json``, refuses a spec
whose driver-owned fields no longer match the stored ``driver_digest`` (or one already frozen, outside the
part and green-run operations below), applies one change, re-validates the whole document from its dump,
stamps a fresh digest and only then writes the file. A refusal or a failed validation writes nothing.

A frozen spec still takes part edits (``add_part``, ``remove_part``) and the reply and grades of a green
run, so a part change can be proven again on the new skill hash before ``strap.py freeze --refreeze``.
Behaviors, scenarios, draws and baselines stay locked until ``strap.py reopen`` starts a new round; after
it, a behavior frozen in an earlier round keeps its ``tests`` and ``kind``. A Locked spec (its ledger's
current round ends in a ``lock`` entry, ``strap.py lock``) refuses every operation that saves, with
``<name> is locked; reopen to change it``.

``__all__`` is the surface ``skill_api.py`` binds for an api heredoc. ``record_run`` stays importable for
``strap.py record-run`` but is left out of it, so an api session cannot record a reply. Requires an
activated config.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple, Union

from harness_lib.config import active
from harness_lib.project import main_worktree, plugin_root
from harness_lib.strap_lock import LockRefused, locked_problem
from harness_lib.strap_models import (
    DRIVER_OWNED_BEHAVIOR, NAME_PATTERN, SEAL_BROKEN, SPEC_FILE, Arm, Behavior, BehaviorKind, BehaviorState,
    Check, CheckKind, Grade, Grader, GradeValue, JudgedItem, JudgmentType, Part, PartKind, PlannedTest,
    Pressure, RedException, ReplyAct, Run, Scenario, SkillSpec, driver_digest, dump_spec, load_spec,
    part_path, seal_broken, sealed,
)
from harness_lib.strap_runs import quote_found, redact_paths

__all__ = [
    "StrapError", "spec_path", "new_behavior", "new_test", "new_scenario", "new_check", "new_judged",
    "add_behavior", "update_behavior", "drop_behavior", "add_scenario", "add_part", "remove_part", "grade",
]

_TAMPERED = "driver-owned fields changed outside strap.py"
_LOCKED_WHEN_DRAWN = ("scenarios", "kind", "type")
_LOCKED_AFTER_ROUND = ("tests", "kind")
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
                 fixture: Optional[str] = None, role: str = "session",
                 sees_skill: Optional[bool] = None) -> Scenario:
    """A validated scenario with the placeholder id ``SC-0``; ``add_scenario`` assigns the real one.

    ``sees_skill`` None follows the role (the session sees the SKILL.md, a role agent does not); True or
    False overrides it, and False needs a role.
    """
    return Scenario(id=f"{_SCENARIO_PREFIX}0", task=task, tempts=tempts, pressures=list(pressures),
                    checks=list(checks), judged=list(judged), fixture=fixture, role=role,
                    sees_skill=sees_skill)


def new_check(kind: Union[CheckKind, str], target: str, baseline: bool, green: bool) -> Check:
    """A machine-evaluated check and the fact each arm is expected to observe."""
    return Check(kind=kind, target=target, expect_baseline=baseline, expect_green=green)


def new_judged(act: Union[ReplyAct, str], of: str, baseline: Union[GradeValue, str],
               green: Union[GradeValue, str]) -> JudgedItem:
    """A judged reply act and its expected grade on each arm."""
    return JudgedItem(act=act, of=of, expect_baseline=baseline, expect_green=green)


# --- load, re-validate, write ---------------------------------------------------------------------------

def _load(name: str, frozen_ok: bool = False) -> SkillSpec:
    """The spec as stored; refused when missing, hand-edited in driver-owned fields or, once frozen, in
    authored fields, Locked, or frozen (unless ``frozen_ok``)."""
    path = spec_path(name)
    if not path.is_file():
        raise StrapError(f"no spec for {name} at {path.as_posix()}")
    spec = load_spec(path)
    if spec.driver_digest != driver_digest(spec):
        raise StrapError(_TAMPERED)
    if seal_broken(spec):
        raise StrapError(SEAL_BROKEN)
    try:
        locked = locked_problem(spec)
    except LockRefused as exc:
        raise StrapError("; ".join(exc.problems)) from None
    if locked:
        raise StrapError(locked)
    if spec.frozen is not None and not frozen_ok:
        raise StrapError(f"{name} is frozen")
    return spec


def _commit(name: str, changed: SkillSpec) -> SkillSpec:
    """Re-validate ``changed`` from its dump, seal a frozen spec, stamp the digest, then write; nothing is
    written on failure."""
    checked = sealed(SkillSpec.model_validate(changed.model_dump()))
    stamped = checked.model_copy(update={"driver_digest": driver_digest(checked)})
    spec_path(name).write_text(dump_spec(stamped), encoding="utf-8", newline="\n")
    return stamped


def _apply(name: str, change: Callable[[SkillSpec], SkillSpec], frozen_ok: bool = False) -> SkillSpec:
    """Load ``name``'s spec, apply ``change`` and commit the result; ``frozen_ok`` admits a frozen spec."""
    return _commit(name, change(_load(name, frozen_ok)))


def _refuse_frozen_baseline(spec: SkillSpec, run: Run) -> None:
    """A frozen spec takes the reply and grades of a green run only."""
    if spec.frozen is not None and run.arm != Arm.GREEN:
        raise StrapError(f"{spec.name} is frozen; {run.id} is a {Arm(run.arm).value} run")


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
    """Refuse driver-owned fields, the assigned id, the locked fields of a drawn behavior, and the proven
    fields of a behavior frozen in an earlier round (``red`` skips it, so changed tests would go unproven)."""
    drawn = any(draw.behavior == behavior_id for draw in spec.draws)
    earlier = any(behavior_id in done.behaviors for done in spec.rounds)
    for field in fields:
        if field in DRIVER_OWNED_BEHAVIOR:
            raise StrapError(f"{field} is driver-owned")
        if field == "id":
            raise StrapError("id is assigned by add_behavior")
        if drawn and field in _LOCKED_WHEN_DRAWN:
            raise StrapError(f"{behavior_id} is drawn")
        if earlier and field in _LOCKED_AFTER_ROUND:
            raise StrapError(f"{behavior_id} was frozen in an earlier round; its {field} stays as proven, "
                             "so a changed rule goes on a new behavior")


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
    """Append a deliverable part; a path already listed is refused. Allowed on a frozen spec."""
    part = Part(kind=kind, path=path)

    def change(spec: SkillSpec) -> SkillSpec:
        if any(existing.path == part.path for existing in spec.parts):
            raise StrapError(f"{part.path} is already a part")
        return spec.model_copy(update={"parts": [*spec.parts, part]})

    return _apply(name, change, frozen_ok=True)


def remove_part(name: str, path: str) -> SkillSpec:
    """Drop the part listed at ``path``; an unlisted path and a path ``scaffold`` plans are refused.

    ``scaffold`` plans the SKILL.md, the contract test and, for a mechanical behavior, the models and api
    modules (in an edit, only those that exist); removing one would only see it planned again. ``path``
    matches in any spelling ``Part`` normalizes. Allowed on a frozen spec.
    """
    from harness_lib.strap_scaffold import scaffold_parts  # strap_scaffold imports this module
    try:
        path = part_path(path)
    except ValueError as exc:
        raise StrapError(str(exc)) from None

    def change(spec: SkillSpec) -> SkillSpec:
        if not any(part.path == path for part in spec.parts):
            raise StrapError(f"{path} is not a part")
        if path in {part.path for part in scaffold_parts(spec)}:
            raise StrapError(f"{path} is a part scaffold requires")
        return spec.model_copy(update={"parts": [part for part in spec.parts if part.path != path]})

    return _apply(name, change, frozen_ok=True)


# --- driver and grading operations ----------------------------------------------------------------------

def run_tree(run: Run) -> Optional[Path]:
    """The run's working tree: ``tree`` under the configured worktree root, None when unset.

    An absolute ``tree``, as runs placed before trees were stored relative hold it, stands as is.
    """
    return active().resolve_worktree_root() / run.tree if run.tree else None


def tree_name(tree: Path) -> str:
    """``tree`` relative to the configured worktree root, in POSIX form, for ``Run.tree``."""
    root = active().resolve_worktree_root().resolve()
    try:
        return Path(tree).resolve().relative_to(root).as_posix()
    except ValueError:
        raise StrapError(f"{Path(tree).as_posix()} is not under the worktree root") from None


def _machine_paths(run: Run) -> List[Tuple[str, Path]]:
    """``(placeholder, path)`` for each machine path a reply may name: the run tree, the worktree root, the
    project root, the main checkout (when the project is a linked worktree), the harness plugin root and the
    home folder, each also in its resolved spelling."""
    cfg = active()
    tree = run_tree(run)
    main = main_worktree(cfg.project_root)
    pairs = [("<worktree_root>", cfg.resolve_worktree_root()), ("<project>", cfg.project_root),
             *([("<main>", main)] if main != cfg.project_root.resolve() else []),
             ("<plugin>", plugin_root()), ("~", Path.home()),
             *([("<tree>", tree)] if tree is not None else [])]
    return [*pairs, *((holder, path.resolve()) for holder, path in pairs)]


def record_run(name: str, run_id: str, reply: str) -> SkillSpec:
    """Store the reply of an unrecorded run with its sha256; ``strap.py record-run`` fills diff and checks.

    Machine paths in the reply under the roots ``_machine_paths`` lists become placeholders before the hash,
    so the tracked spec names none of those roots.
    """
    def change(spec: SkillSpec) -> SkillSpec:
        index = _run_index(spec, run_id)
        run = spec.runs[index]
        _refuse_frozen_baseline(spec, run)
        if run.recorded:
            raise StrapError(f"{run_id} already recorded")
        text = redact_paths(reply, _machine_paths(run))
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        runs = list(spec.runs)
        runs[index] = run.model_copy(update={"reply": text, "reply_sha256": sha, "recorded": True})
        return spec.model_copy(update={"runs": runs})

    return _apply(name, change, frozen_ok=True)


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
        _refuse_frozen_baseline(spec, spec.runs[_run_index(spec, run_id)])
        run = _gradable_run(spec, run_id, item)
        if not quote_found(quote, run.reply):
            raise StrapError(f"quote not found in {run_id}")
        given = Grade(run=run_id, item=item, value=value, quote=quote, grader=who)
        return spec.model_copy(update={"grades": [*spec.grades, given]})

    return _apply(name, change, frozen_ok=True)
