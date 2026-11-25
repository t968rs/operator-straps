"""pr-review fix waves: file-disjoint fixer waves over a review's issues.

Fix waves: a mechanical multi-file issue splits into one single-file part per file; a judgment multi-file
issue stays whole. Units link through a shared owned file or serial-test lock; a linked group of at most
``MAX_ISSUES_PER_FIXER`` units runs whole in the first wave. A larger group is cut: units are deferred until
every remaining group fits, and the deferred units re-enter the pool for the next wave. The most-connected cut
defers the most connected unit (ties: the least severe), so the units that hung on a deferred hub run in
parallel before it; the light-first cut defers light units (mechanical parts, minor issues) before heavy ones
(critical or important judgment fixes), so heavy work runs in the first wave. Either cut may return the
deferred units it no longer needs (``_readmit``), and a judgment-only group one unit over the cap may run
whole (``_fits``). The layout is planned under every mix of these rules and the one with the lowest estimated
wall time (``HAIKU_SECONDS``, ``OPUS_SECONDS``) wins, the plain most-connected cut on a tie. A group
sharing nothing with the wave's fixers joins the fixer holding another part of one of its issues when it fits
and that fixer holds no heavy unit; otherwise it opens a fixer of its
own while the wave holds fewer than ``FIXERS_PER_WAVE``, and past that it joins the smallest fixer with room,
preferring one without a heavy unit, then one of its own fix kind, so a wave spreads its work across fixers
instead of filling one to the cap. Fixers within a wave are file-disjoint over the
files they own and never hold the same serial-test lock; tracking paths belong to no fixer. Given a test
registry map, each unit also owns the registered tests targeting its files and the existing paths its
``fix`` text names (widened files: in the fixer's ``files`` and the disjointness check, never in ``parts``).

Closeout (``review_merge.apply_closeout``) validates each fixer's report against the ``parts`` and
``files`` of the fixer rows ``plan_waves`` returns.
"""
from __future__ import annotations

import fnmatch
import itertools
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from harness_lib.review_merge import _RANK, Issue, _files, _id_key, _tier, _union

MAX_ISSUES_PER_FIXER = 6
FIXERS_PER_WAVE = 4
# Estimated fixer seconds, calibrated on recorded fixer runs: a haiku fixer's base and per-unit cost; an opus
# fixer's base and its cost per heavy unit (a critical or important judgment fix), per minor judgment unit and
# per mechanical part. Only the ratios steer the layout choice.
HAIKU_SECONDS = (25, 7)
OPUS_SECONDS = {"base": 20, "heavy": 65, "judgment": 30, "mechanical": 10}
_PATH_TOKEN = re.compile(r"[\w.-]+(?:/[\w.-]+)+")
_PATH_EXT = re.compile(r"/[^/]*\w\.[A-Za-z0-9]+$")


def fix_paths(issue: Mapping[str, object]) -> List[str]:
    """Path tokens shaped ``a/b/c.ext`` named in an issue's ``fix`` options, first-seen order; tokens with a
    ``..`` segment are dropped (existence is the caller's check)."""
    text = " ".join(str(option) for option in issue.get("fix") or [])  # type: ignore[union-attr]
    tokens = (t.rstrip(".,:;") for t in _PATH_TOKEN.findall(text))
    paths = (t[2:] if t.startswith("./") else t for t in tokens if _PATH_EXT.search(t))
    return list(_union(p for p in paths if ".." not in p.split("/")))


def _target_covers(target: str, files: Set[str]) -> bool:
    """True when ``target`` equals a file of ``files`` or, as a directory, contains one (the registry's
    exact-or-descendant rule: ``src/pkg`` covers ``src/pkg/mod.py``, not ``src/pkg_other.py``)."""
    prefix = target.rstrip("/") + "/"
    return target in files or any(f.startswith(prefix) for f in files)


def registry_tests(files: Iterable[str], registry: Mapping[str, Sequence[str]]) -> List[str]:
    """Registered test files (``registry``: test file -> ``test_target_paths``) targeting any of ``files``,
    a directory target covering every file beneath it (the rule registry test selection applies)."""
    wanted = set(files)
    return [test for test, targets in registry.items() if any(_target_covers(t, wanted) for t in targets)]


def is_tracking(path: str, patterns: Sequence[str]) -> bool:
    """True when ``path`` matches a tracking-path glob (``fnmatch``, the rule of the exclusions file)."""
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def tracking_rows(issues: Sequence[Issue], held: Sequence[str], done: Sequence[str],
                  patterns: Sequence[str]) -> List[Tuple[str, List[str]]]:
    """(id, files) of each issue, minus ``held`` and ``done`` ids, whose every file is a tracking path: no
    fixer owns it, so the main session edits it."""
    skip = set(held) | set(done)
    rows = [(str(i["id"]), list(_union(_files(i)))) for i in issues if i["id"] not in skip]
    return [(issue_id, files) for issue_id, files in rows if all(is_tracking(f, patterns) for f in files)]


def mixed_tracking_rows(issues: Sequence[Issue], held: Sequence[str], done: Sequence[str],
                        patterns: Sequence[str]) -> List[Tuple[str, List[str]]]:
    """(id, tracking files) of each issue, minus ``held`` and ``done`` ids, holding both tracking and other
    files: a fixer owns the others and its entry resolves the id, so the main session edits the tracking
    files after that fixer's wave."""
    skip = set(held) | set(done)
    rows = [(str(i["id"]), list(_union(_files(i)))) for i in issues if i["id"] not in skip]
    split = [(issue_id, [f for f in files if is_tracking(f, patterns)], len(files))
             for issue_id, files in rows]
    return [(issue_id, tracked) for issue_id, tracked, total in split if 0 < len(tracked) < total]


def _widening(issue: Issue, files: Sequence[str], registry: Mapping[str, Sequence[str]],
              existing: Set[str], tracking: Sequence[str] = ()) -> Tuple[str, ...]:
    """Files a unit's fixer may also edit: tests targeting ``files`` or the existing paths the fix names, and
    those named paths themselves, minus the issue's own files; a tracking path is never named in."""
    own = set(_files(issue))
    named = [p for p in fix_paths(issue) if p in existing and not is_tracking(p, tracking)]
    found = [*registry_tests([*files, *named], registry), *named]
    return tuple(f for f in _union(found) if f not in own)


@dataclass(frozen=True)
class _Unit:
    """One placement unit: a whole issue, or one file (part) of a split mechanical issue, plus the widened
    files its fixer also owns (tests and fix-named paths; never part of the issue's parts)."""

    issue: Issue
    files: Tuple[str, ...]
    extra: Tuple[str, ...] = ()
    locks: Tuple[str, ...] = ()

    @property
    def id(self) -> str:
        """The issue id."""
        return str(self.issue["id"])


def _locks(files: Sequence[str], test_locks: Mapping[str, Sequence[str]]) -> Tuple[str, ...]:
    """Lock names held by the registered tests among ``files`` (a unit's files and widened files)."""
    return _union(lock for f in files for lock in test_locks.get(f, ()))


def _units(issue: Issue, registry: Mapping[str, Sequence[str]], existing: Set[str],
           tracking: Sequence[str] = (),
           test_locks: Optional[Mapping[str, Sequence[str]]] = None) -> List[_Unit]:
    """One part per file of a mechanical multi-file issue, else the whole issue; each widened. Tracking files
    belong to no unit, so an issue with only tracking files has none."""
    files = tuple(f for f in _union(_files(issue)) if not is_tracking(f, tracking))
    split = issue.get("fix_kind") == "mechanical" and len(files) > 1
    parts = [(f,) for f in files] if split else ([files] if files else [])
    units = []
    for part in parts:
        extra = _widening(issue, part, registry, existing, tracking)
        units.append(_Unit(issue, part, extra, _locks((*part, *extra), test_locks or {})))
    return units


def _keys(unit: _Unit) -> Set[Tuple[str, str]]:
    """What a unit holds exclusively within a wave: its files, widened files and serial-test locks."""
    return {*(("file", f) for f in (*unit.files, *unit.extra)), *(("lock", k) for k in unit.locks)}


def _components(units: Sequence[_Unit]) -> List[List[_Unit]]:
    """Groups of ``units`` linked by a shared key (see ``_keys``), first-seen order. Units of different groups
    share nothing, so they may run in one wave; units of one group run in one fixer or in different waves."""
    parent = list(range(len(units)))

    def find(n: int) -> int:
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    held: Dict[Tuple[str, str], int] = {}
    for n, unit in enumerate(units):
        for key in _keys(unit):
            parent[find(n)] = find(held.setdefault(key, n))
    groups: Dict[int, List[_Unit]] = {}
    for n, unit in enumerate(units):
        groups.setdefault(find(n), []).append(unit)
    return list(groups.values())


def _degree(unit: _Unit, units: Sequence[_Unit]) -> int:
    """Number of other ``units`` that share a key with ``unit``."""
    return sum(1 for other in units if other is not unit and _keys(unit) & _keys(other))


def _heavy(unit: _Unit) -> bool:
    """True for a judgment fix of a critical or important issue: the work that sets a fixer's wall time."""
    return unit.issue.get("fix_kind") != "mechanical" and _tier(unit.id) != "minor"


def _holds_heavy(chunk: Sequence[_Unit]) -> bool:
    """True when ``chunk`` holds a heavy unit (``_heavy``)."""
    return any(_heavy(u) for u in chunk)


@dataclass(frozen=True)
class _Rules:
    """Options one candidate layout is planned under; ``plan_waves`` plans every mix and keeps the cheapest.

    ``light_first``: the cut defers light units before heavy ones (``_cut``). ``readmit``: deferred units the
    finished cut no longer needs rejoin the wave (``_readmit``). ``stretch``: a judgment-only group one unit
    over the cap runs whole instead of leaving one unit for a later wave (``_schedule``)."""

    light_first: bool = False
    readmit: bool = False
    stretch: bool = False


def _readmit(groups: Sequence[List[_Unit]], deferred: Sequence[_Unit],
             cap: int) -> Tuple[List[List[_Unit]], List[_Unit]]:
    """Return deferred units to the wave, in deferral order: a unit linked to no group starts a group of its
    own, a unit linked to exactly one group with room joins it, and a unit linked to two or more groups stays
    deferred (rejoining would merge them). The greedy cut can defer a unit early that a later deferral made
    unnecessary; every group still fits ``cap`` and groups stay disjoint."""
    kept = [list(g) for g in groups]
    left: List[_Unit] = []
    for unit in deferred:
        keys = _keys(unit)
        linked = [g for g in kept if any(keys & _keys(u) for u in g)]
        if not linked:
            kept.append([unit])
        elif len(linked) == 1 and len(linked[0]) < cap:
            linked[0].append(unit)
        else:
            left.append(unit)
    return kept, left


def _cut(group: Sequence[_Unit], cap: int, rules: _Rules = _Rules()) -> Tuple[List[List[_Unit]], List[_Unit]]:
    """Cut a group over ``cap`` units: defer the most connected unit (ties: the least severe) until every
    remaining group fits ``cap``. Returns the groups that run now and the deferred units, which fall to a
    later wave. Removing a deferred hub removes the links through it, so neighbours that shared only the hub
    fall into separate groups and run in parallel instead of queueing behind the fixer that owns the hub;
    neighbours that also share a file or lock stay in one component, and that component is cut again if
    it is still over ``cap``. With ``rules.light_first``, a heavy unit (``_heavy``) is deferred only when the
    crowded groups hold no light one, so heavy work stays in the earliest wave and the later waves carry
    the cheap units. With ``rules.readmit``, the finished cut returns the units it no longer needs
    (``_readmit``)."""
    kept, deferred = list(group), []
    groups = [list(kept)]
    light_first = rules.light_first
    while any(len(g) > cap for g in groups):
        crowded = [u for g in groups if len(g) > cap for u in g]
        hub = max(crowded, key=lambda u: (light_first and not _heavy(u), _degree(u, kept), _id_key(u.id)))
        kept = [u for u in kept if u is not hub]
        deferred.append(hub)
        groups = _components(kept)
    return _readmit(groups, deferred, cap) if rules.readmit else (groups, deferred)


def _fits(group: Sequence[_Unit], cap: int, rules: _Rules) -> bool:
    """True when ``group`` runs whole: at most ``cap`` units, or, with ``rules.stretch``, exactly one over
    ``cap`` with no mechanical unit."""
    if len(group) <= cap:
        return True
    judgment_only = not any(u.issue.get("fix_kind") == "mechanical" for u in group)
    return rules.stretch and len(group) == cap + 1 and judgment_only


def _schedule(units: Sequence[_Unit], cap: int, rules: _Rules = _Rules()) -> List[List[List[_Unit]]]:
    """Waves of file-disjoint groups, each at most ``cap`` units (one more under ``rules.stretch``, see
    ``_fits``): a group that fits runs whole in the first wave, a larger one is cut (``_cut``) and its
    deferred units re-enter the pool for the next wave."""
    waves: List[List[List[_Unit]]] = []
    pool = list(units)
    while pool:
        wave: List[List[_Unit]] = []
        pool, later = [], pool
        for group in _components(later):
            run, deferred = ([group], []) if _fits(group, cap, rules) else _cut(group, cap, rules)
            wave.extend(run)
            pool.extend(deferred)
        waves.append(sorted(wave, key=lambda g: (-len(g), min(_id_key(u.id) for u in g))))
    return waves


def _chunk_files(chunk: Sequence[_Unit]) -> Set[str]:
    """Owned file set of a chunk, widened files included."""
    return {f for unit in chunk for f in (*unit.files, *unit.extra)}


def _chunk_locks(chunk: Sequence[_Unit]) -> Set[str]:
    """Serial-test locks held by a chunk."""
    return {lock for unit in chunk for lock in unit.locks}


def _mechanical(chunk: Sequence[_Unit]) -> bool:
    """True when every unit of ``chunk`` is a mechanical fix (a haiku fixer)."""
    return all(u.issue.get("fix_kind") == "mechanical" for u in chunk)


def _place_free(wave: List[List[_Unit]], chunk: List[_Unit], cap: int, target: int) -> None:
    """Place a group that shares nothing with the fixers of ``wave``: the fixer already holding another part
    of one of its issues (a split issue stays whole while it fits) unless that fixer holds a heavy unit,
    else a new fixer while the wave holds fewer than ``target``, else the smallest fixer with room (one
    without a heavy unit first, then one of the group's own fix kind), else a new fixer. A fixer holding
    heavy work is usually the slowest of its wave, so among fixers with room it is the last to take an
    extra group, whatever its fix kind."""
    roomy = [b for b in wave if len(b) + len(chunk) <= cap]
    ids = {u.id for u in chunk}
    kin = [b for b in roomy if ids & {u.id for u in b} and not _holds_heavy(b)]
    if kin:
        kin[0].extend(chunk)
    elif len(wave) < target or not roomy:
        wave.append(list(chunk))
    else:
        kind = _mechanical(chunk)
        min(roomy, key=lambda b: (_holds_heavy(b), _mechanical(b) != kind, len(b))).extend(chunk)


def _fixer_seconds(chunk: Sequence[_Unit]) -> int:
    """Estimated wall seconds of one fixer over ``chunk`` (``HAIKU_SECONDS``, ``OPUS_SECONDS``)."""
    if _mechanical(chunk):
        base, per_unit = HAIKU_SECONDS
        return base + per_unit * len(chunk)
    costs = [OPUS_SECONDS["mechanical"] if u.issue.get("fix_kind") == "mechanical"
             else OPUS_SECONDS["heavy" if _heavy(u) else "judgment"] for u in chunk]
    return OPUS_SECONDS["base"] + sum(costs)


def _wall_seconds(waves: Sequence[Sequence[Sequence[_Unit]]]) -> int:
    """Estimated wall seconds of a layout: the slowest fixer of each wave, summed over the waves."""
    return sum(max(_fixer_seconds(chunk) for chunk in wave) for wave in waves)


def _layout(units: Sequence[_Unit], cap: int, fixers: int, rules: _Rules) -> List[List[List[_Unit]]]:
    """Waves of fixers (unit lists): ``_schedule`` under ``rules``, each wave's groups placed on fixers."""
    waves: List[List[List[_Unit]]] = []
    for groups in _schedule(units, cap, rules):
        wave: List[List[_Unit]] = []
        for group in groups:
            _place_free(wave, group, cap, fixers)
        waves.append(wave)
    return waves


def _parts(chunk: Sequence[_Unit]) -> Dict[str, List[str]]:
    """Owned files per issue id (in the issue's file order), ids minor, then important, then critical."""
    owned: Dict[str, Set[str]] = {}
    issues: Dict[str, Issue] = {}
    for unit in chunk:
        owned.setdefault(unit.id, set()).update(unit.files)
        issues[unit.id] = unit.issue
    ids = sorted(owned, key=lambda i: (-_RANK[_tier(i)], int(i[1:])))
    return {i: [f for f in _union(_files(issues[i])) if f in owned[i]] for i in ids}


def _fixer(wave: int, number: int, chunk: Sequence[_Unit]) -> Dict[str, object]:
    """Fixer row: id, model, issue ids (minor, then important, then critical), parts and owned files."""
    parts = _parts(chunk)
    model = "haiku" if _mechanical(chunk) else "opus"
    row: Dict[str, object] = {"id": f"w{wave}_fix_{number}", "model": model,
                              "issue_ids": list(parts), "parts": parts,
                              "files": sorted(_chunk_files(chunk))}
    if _chunk_locks(chunk):
        row["locks"] = sorted(_chunk_locks(chunk))
    return row


def plan_waves(issues: Sequence[Issue], held: Sequence[str], done: Sequence[str],
               cap: int = MAX_ISSUES_PER_FIXER, start_wave: int = 1,
               registry: Optional[Mapping[str, Sequence[str]]] = None,
               existing: Optional[Set[str]] = None, tracking: Sequence[str] = (),
               test_locks: Optional[Mapping[str, Sequence[str]]] = None,
               fixers: int = FIXERS_PER_WAVE) -> List[List[Dict[str, object]]]:
    """Fix waves (lists of file-disjoint fixers) over ``issues`` minus ``held`` and ``done`` ids.

    A mechanical multi-file issue is planned as one part per file; ``cap`` counts parts and whole issues.
    Each fixer's ``parts`` maps an issue id to the files that fixer owns for it. ``start_wave`` numbers the
    first wave, so follow-up waves never reuse an earlier fixer id. Each unit's file set widens by the
    ``registry`` tests (test file -> ``test_target_paths``) targeting its files and by the ``fix_paths``
    found in ``existing``; widened files join the fixer's ``files`` and the disjointness check, never
    ``parts``. ``tracking`` globs name files no fixer owns: they drop out of every unit and out of the
    widening (``tracking_rows`` and ``mixed_tracking_rows`` list them for the main session).
    ``test_locks`` (test file -> serial-test lock names) makes two fixers that hold the same lock touch
    each other like a shared file, so they never share a wave; a fixer record names its ``locks``.
    ``fixers`` is the number of fixers a wave opens for unrelated chunks before they start sharing a fixer
    (``_place_free``); a wave may exceed it when no fixer has room for a group.
    One layout is planned per mix of ``_Rules`` (cut most connected first or light units first; deferred
    units returned or not; a judgment-only group one over ``cap`` stretched or cut); the one with the lowest
    estimated wall time (``_wall_seconds``) is returned. A tie keeps the earlier mix in
    ``itertools.product`` order, so the plain most-connected cut wins every tie it is part of.
    """
    skip = set(held) | set(done)
    units = [u for i in issues if i["id"] not in skip
             for u in _units(i, registry or {}, existing or set(), tracking, test_locks)]
    mixes = [_Rules(*flags) for flags in itertools.product((False, True), repeat=3)]
    waves = min((_layout(units, cap, fixers, rules) for rules in mixes), key=_wall_seconds)
    return [[_fixer(start_wave + w, k, b) for k, b in enumerate(wave, start=1)]
            for w, wave in enumerate(waves)]
