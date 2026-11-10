"""strap-skills: content hashes, seeded draws, check evaluation, quote matching, pass rules, retest pool.

Skill-agnostic helpers over the ``strap_models`` documents. Nothing here reads configuration or knows what
a skill is, so the module can be lifted into a generic A/B tester. It imports ``strap_models`` and the
standard library only.
"""
from __future__ import annotations

import hashlib
import random
import re
import secrets
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from harness_lib.strap_models import (
    Arm, Behavior, Check, CheckKind, CheckResult, DrawReason, Grade, GradeValue, Run, Scenario, SkillSpec,
)

_MISSING = b"<missing>"
_SEED_BITS = 32


def content_hash(root: Path, paths: Sequence[str]) -> str:
    """Hash ``paths`` under ``root`` in sorted order; a missing file hashes as a marker.

    CRLF line endings hash as LF, so a ``core.autocrlf`` checkout of unchanged parts keeps the frozen hash.
    """
    digest = hashlib.sha256()
    for rel in sorted(paths):
        target = root / rel
        body = target.read_bytes().replace(b"\r\n", b"\n") if target.is_file() else _MISSING
        digest.update(rel.encode("utf-8") + b"\0" + body + b"\0")
    return digest.hexdigest()


def draw_scenario(behavior: Behavior, exclude: Sequence[str], seed: int) -> str:
    """Pick one scenario id not in ``exclude``, seeded, over the declared order."""
    pool = [s.id for s in behavior.scenarios if s.id not in exclude]
    if not pool:
        raise ValueError(f"{behavior.id} has no undrawn scenario")
    return random.Random(seed).choice(pool)


def new_seed() -> int:
    """A fresh 32-bit draw seed."""
    return secrets.randbits(_SEED_BITS)


def _fact(check: Check, changed: Sequence[str], present: Callable[[str], bool], head_moved: bool,
          reply: str) -> bool:
    """The observed truth of one check, independent of the arm."""
    kind = check.kind
    if kind == CheckKind.FILE_CHANGED:
        return check.target in changed
    if kind == CheckKind.FILE_UNCHANGED:
        return check.target not in changed
    if kind == CheckKind.PATH_PRESENT:
        return bool(present(check.target))
    if kind == CheckKind.PATH_ABSENT:
        return not present(check.target)
    if kind == CheckKind.HEAD_UNCHANGED:
        return not head_moved
    found = re.search(check.target, reply, re.MULTILINE) is not None
    return found if kind == CheckKind.REPLY_MATCHES else not found


def evaluate_checks(checks: Sequence[Check], arm: Arm, changed: Sequence[str],
                    present: Callable[[str], bool], head_moved: bool, reply: str) -> List[CheckResult]:
    """One result per check: held when the observed fact equals the arm's expectation."""
    results: List[CheckResult] = []
    for index, check in enumerate(checks):
        observed = _fact(check, changed, present, head_moved, reply)
        expected = check.expect_baseline if arm == Arm.BASELINE else check.expect_green
        results.append(CheckResult(index=index, held=observed == expected,
                                   detail=f"{check.kind.value} {check.target}: observed {observed}"))
    return results


def _squash(text: str) -> str:
    """Collapse every whitespace run to one space and trim the ends."""
    return " ".join(text.split())


def quote_found(quote: str, reply: str) -> bool:
    """True when the whitespace-normalized quote is a substring of the normalized reply."""
    return _squash(quote) in _squash(reply)


_SEP = r"[/\\]+"
_NAME_CHAR = r"[\w.-]"


def _path_pattern(path: str) -> Optional[re.Pattern]:
    """A pattern for absolute ``path`` in any separator spelling; a drive path also as ``/c/...``.

    A drive path matches case-insensitively; neither form matches inside a longer name. None for a path
    with fewer than two segments, which would match too much.
    """
    parts = [part for part in re.split(_SEP, path) if part]
    drive = re.fullmatch(r"([A-Za-z]):", parts[0]) if parts else None
    rest = parts[1:] if drive else parts
    if len(parts) < 2 or not rest:
        return None
    head = rf"(?:{drive.group(1)}:|/{drive.group(1)})" if drive else ""
    body = _SEP + _SEP.join(re.escape(part) for part in rest)
    return re.compile(rf"(?<!{_NAME_CHAR}){head}{body}(?![\w-])", re.IGNORECASE if drive else 0)


def redact_paths(text: str, pairs: Sequence[Tuple[str, Union[str, Path]]]) -> str:
    """``text`` with each ``(placeholder, path)`` path replaced by its placeholder, longest path first.

    The longest-first order lets a path under another keep its own placeholder.
    """
    ordered = sorted(((holder, str(path)) for holder, path in pairs), key=lambda pair: -len(pair[1]))
    for holder, path in ordered:
        pattern = _path_pattern(path)
        if pattern is not None:
            text = pattern.sub(lambda _: holder, text)
    return text


def item_matches(expected: Union[bool, GradeValue], observed: Union[bool, GradeValue]) -> bool:
    """Equality of one expectation with its observation (a check bool or a judged grade)."""
    return expected == observed


def _grade_map(run: Run, grades: Sequence[Grade]) -> Dict[int, GradeValue]:
    """The grade of each judged item index for ``run``; the first grade of an item wins."""
    found: Dict[int, GradeValue] = {}
    for grade in grades:
        if grade.run == run.id and grade.item not in found:
            found[grade.item] = grade.value
    return found


def baseline_failed(scenario: Scenario, run: Run, grades: Sequence[Grade]) -> bool:
    """True when any present check result held or any judged grade equals its baseline expectation."""
    if any(result.held for result in run.checks):
        return True
    graded = _grade_map(run, grades)
    return any(index in graded and item_matches(item.expect_baseline, graded[index])
               for index, item in enumerate(scenario.judged))


def green_passed(scenario: Scenario, run: Run, grades: Sequence[Grade]) -> bool:
    """True when the check results are complete and held, and every judged item graded as expected."""
    if sorted(result.index for result in run.checks) != list(range(len(scenario.checks))):
        return False
    if not all(result.held for result in run.checks):
        return False
    graded = _grade_map(run, grades)
    return all(index in graded and item_matches(item.expect_green, graded[index])
               for index, item in enumerate(scenario.judged))


def _scenario_of(behavior: Behavior, scenario_id: str) -> Optional[Scenario]:
    return next((s for s in behavior.scenarios if s.id == scenario_id), None)


def _failed_greens(spec: SkillSpec, behavior: Behavior) -> List[str]:
    """Scenario ids with a recorded green run that did not pass, in first-seen order."""
    seen: List[str] = []
    for run in spec.runs:
        scenario = _scenario_of(behavior, run.scenario)
        if run.behavior != behavior.id or run.arm != Arm.GREEN or not run.recorded or scenario is None:
            continue
        if not green_passed(scenario, run, spec.grades) and run.scenario not in seen:
            seen.append(run.scenario)
    return seen


def _void_retest(spec: SkillSpec, behavior: Behavior, scenario_id: str) -> bool:
    """True when recorded baselines of the scenario exist and none of them failed."""
    scenario = _scenario_of(behavior, scenario_id)
    baselines = [r for r in spec.runs if r.behavior == behavior.id and r.scenario == scenario_id
                 and r.arm == Arm.BASELINE and r.recorded]
    if scenario is None or not baselines:
        return False
    return not any(baseline_failed(scenario, run, spec.grades) for run in baselines)


def must_pass(spec: SkillSpec, behavior_id: str) -> List[str]:
    """Failed-green scenario ids plus the latest non-void retest draw, in first-seen order."""
    behavior = next((b for b in spec.behaviors if b.id == behavior_id), None)
    if behavior is None:
        return []
    pool = _failed_greens(spec, behavior)
    retests = [d for d in spec.draws if d.behavior == behavior_id and d.reason == DrawReason.RETEST]
    if retests and not _void_retest(spec, behavior, retests[-1].scenario):
        if retests[-1].scenario not in pool:
            pool.append(retests[-1].scenario)
    return pool
