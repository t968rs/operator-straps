"""pr-review merge, verdict, review document and closeout over recorded reports; the fix-wave planner
is ``harness_lib.review_waves``.

Pure functions over ``harness_lib.review_models`` reports and ``PR_REVIEW.schema.json`` dicts, plus
``validate_review``: the in-process gate every review write goes through (the schema ``schema_path``
resolves, with a registry of its sibling ``*.schema.json`` files, the hook's pending-``pre_fix_time``
coherence rule, and ``harness_lib.validation.pr_json_validation.validate_issue_counts``).

``schema_ref`` in a review document: the POSIX path from the review file's directory to the project's pinned
``PR_REVIEW.schema.json`` (``<schemas_dir>/PR_REVIEW.schema.json``) when the project pins one, else the
plugin schema's ``$id``. A project-relative path would dangle in a project that pins nothing, and an absolute
path into the installed plugin would name a versioned cache directory, so the plugin case carries the
schema's stable identifier instead.

Merge rule: two findings merge only when they share the primary file and some line range of one lies within
``MERGE_WINDOW`` lines of some range of the other, and a finding joins a merged group only when that holds for
every member (no transitive chaining); findings without lines never auto-merge and surface through
``merge_candidates``. Ids are numbered per severity by (primary file, first line, name). A source folded
after build goes through ``append_findings``: the same conversion for its one report, ids continuing per
severity after the review's highest, nothing renumbered or merged; ``cross_candidates`` only reports pairs.

Closeout: a fixer may resolve only the ids its planned parts assign it; a split issue (some fixer owns less
than its file set, or a mechanical issue planned over more than one file, all parts in one fixer included)
resolves only when its fixers' entries together cover every planned part, each part edited or marked
``no_change`` by its fixer (a part's entry may also list the rest of its fixer's file set, never the same
issue's parts other fixers own); only ids already closed
(latest status in ``CLOSED_STATUSES``) are skipped. ``remaining_parts`` and ``only_files`` let
a follow-up wave re-plan just the unrecorded parts of a partially fixed split issue; given the closeout
inputs, ``remaining_parts`` counts only the entries closeout accepts, so a rejected entry is re-planned.
"""
from __future__ import annotations

import copy
import functools
import json
import math
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import (TYPE_CHECKING, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple,
                    Union)

from harness_lib.review_models import (AttackFinding, Finding, FixEntry, FixReport, Refutation,
                                       RefutationReport, RefutationVerdict, ReviewerReport, Severity,
                                       config_for, finding_key)
from harness_lib.validation.id_handling import counted_resolutions, latest_statuses, reopened_ids

if TYPE_CHECKING:
    from jsonschema.protocols import Validator

    from harness_lib.config import HarnessConfig

MERGE_WINDOW = 3
PENDING = "pending - to be populated in Phase 4"
SCHEMA_NAME = "PR_REVIEW.schema.json"
SCHEMA_VERSION = "2.3.0"
EVIDENCE_NOTE = "(working-tree snapshot; developer commits)"
TIERS = ("critical", "important", "minor")
CLOSED_STATUSES = ("RESOLVED", "CLOSED_NO_ACTION", "REFUTED")
_LETTER = {"critical": "C", "important": "I", "minor": "M"}
_TIER_OF = {v: k for k, v in _LETTER.items()}
# Shared with review_waves: _RANK, _union, _tier, _files and _id_key are imported by the fix-wave planner
# (harness_lib.review_waves). Each carries a "used by review_waves" note; a rename or signature change here
# must update that module too.
_RANK = {tier: n for n, tier in enumerate(TIERS)}
_LINES = re.compile(r"^\d+(-\d+)?(,\s*\d+(-\d+)?)*$")
_ISSUE_ID = re.compile(r"^([CIM])(\d+)$")
_TOKEN = re.compile(r"[a-z0-9]+")
_SLUG_DROP = re.compile(r"[^A-Za-z0-9._-]")
MAX_SLUG_LEN = 60

Issue = Dict[str, object]
Range = Tuple[int, int]
Parts = Mapping[str, Mapping[str, Sequence[str]]]


# --- line ranges and the merge record -----------------------------------------------------------------------


def line_ranges(lines: Optional[str]) -> Tuple[Range, ...]:
    """``(start, end)`` ranges of a ``lines`` string (``"9,146-155"``); empty for None; malformed raises."""
    if lines is None:
        return ()
    if not _LINES.match(lines):
        raise ValueError(f"lines {lines!r} is not a comma-separated list of N or N-M")
    pairs = [[int(n) for n in part.strip().split("-")] for part in lines.split(",")]
    return tuple((min(p), max(p)) for p in pairs)


def _near(a: Sequence[Range], b: Sequence[Range]) -> bool:
    """True when some range of ``a`` lies within ``MERGE_WINDOW`` lines of some range of ``b``."""
    return any(s1 <= e2 + MERGE_WINDOW and s2 <= e1 + MERGE_WINDOW for s1, e1 in a for s2, e2 in b)


def same_issue(a: Finding, b: Finding) -> bool:
    """True when ``a`` and ``b`` share the primary file and have line ranges within the merge window."""
    return a.file == b.file and _near(line_ranges(a.lines), line_ranges(b.lines))


# Used by review_waves.
def _union(items: Iterable[str]) -> Tuple[str, ...]:
    """Distinct ``items`` in first-seen order."""
    return tuple(dict.fromkeys(items))


def _merge_ranges(ranges: Iterable[Range]) -> Tuple[Range, ...]:
    """Sorted ranges with overlapping or touching ranges joined."""
    out: List[Range] = []
    for start, end in sorted(ranges):
        if out and start <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return tuple(out)


# Used by review_waves.
def _tier(issue_id: str) -> str:
    """Tier name of an issue id (``I3`` -> ``important``)."""
    return _TIER_OF[issue_id[0]]


# Used by review_waves (unit ownership relies on the ``[file]`` fallback).
def _files(issue: Mapping[str, object]) -> List[str]:
    """Full file list of a schema issue: ``files`` when present, else ``[file]``."""
    files = issue.get("files") or [issue["file"]]
    return [str(f) for f in files]  # type: ignore[union-attr]


@dataclass(frozen=True)
class _Record:
    """One finding or issue while merging; ``rank`` 0 is critical. ``attacks`` (a code refuter's attack
    texts) exist only to fold ``Attack: <text>`` into the issue summary; no schema field holds them."""

    rank: int
    name: str
    summary: str
    fix: Tuple[str, ...]
    file: str
    also: Tuple[str, ...]
    ranges: Tuple[Range, ...]
    slots: Tuple[str, ...]
    judgment: bool
    attacks: Tuple[str, ...] = ()

    @classmethod
    def of_finding(cls, slot: str, finding: Finding) -> _Record:
        """Record for one finding of reviewer ``slot`` (a code refuter's finding carries its attack)."""
        attacks = (finding.attack,) if isinstance(finding, AttackFinding) else ()
        return cls(_RANK[finding.severity.value], finding.name, finding.summary, finding.fix, finding.file,
                   finding.also, line_ranges(finding.lines), (slot,), finding.fix_kind.value == "judgment",
                   attacks)

    @classmethod
    def of_issue(cls, issue: Mapping[str, object]) -> _Record:
        """Record for a schema issue dict (a missing ``fix_kind`` reads as judgment)."""
        files = _files(issue)
        slots = tuple(s.strip() for s in str(issue.get("reviewer", "")).split(",") if s.strip())
        lines = issue.get("lines")
        ranges = line_ranges(None if lines is None else str(lines))
        fixes = tuple(str(f) for f in issue["fix"])  # type: ignore[attr-defined]
        return cls(_RANK[_tier(str(issue["id"]))], str(issue["name"]), str(issue["summary"]),
                   fixes, files[0], tuple(files[1:]), ranges, slots, issue.get("fix_kind") != "mechanical")

    def issue(self, issue_id: str) -> Issue:
        """Schema issue dict under ``issue_id``."""
        out: Issue = {"id": issue_id, "name": self.name, "file": self.file}
        if self.also:
            out["files"] = [self.file, *self.also]
        if self.ranges:
            out["lines"] = ",".join(f"{s}" if s == e else f"{s}-{e}" for s, e in self.ranges)
        out["reviewer"] = ", ".join(self.slots)
        if len(self.slots) > 1:
            out["both_reviewers"] = True
        out["fix_kind"] = "judgment" if self.judgment else "mechanical"
        summary = "\n\n".join([self.summary, *(f"Attack: {a}" for a in self.attacks)])
        out.update(summary=summary, fix=list(self.fix))
        return out


def _summary(records: Sequence[_Record]) -> str:
    """The first record's summary, then each other distinct summary tagged with its reviewers."""
    parts = [records[0].summary]
    seen = {records[0].summary}
    for record in records[1:]:
        if record.summary not in seen:
            seen.add(record.summary)
            parts.append(f"Also ({', '.join(record.slots)}): {record.summary}")
    return "\n\n".join(parts)


def _combine(records: Sequence[_Record], shaped: Optional[int] = None) -> _Record:
    """One record from ``records``; the first supplies the name and primary file, the best rank wins.

    With ``shaped``, only the first ``shaped`` records (the upheld ones of a mixed group) supply the rank,
    summary, attacks and fix kind; files, lines, fixes and reviewers union over every record.
    """
    first, shape = records[0], records[:shaped or len(records)]
    others = _union(f for r in records for f in (r.file, *r.also))
    fixes = _union(f for r in records for f in r.fix)
    return _Record(
        min(r.rank for r in shape), first.name, _summary(shape), fixes,
        first.file, tuple(f for f in others if f != first.file),
        _merge_ranges(rng for r in records if r.file == first.file for rng in r.ranges),
        _union(s for r in records for s in r.slots), any(r.judgment for r in shape),
        _union(a for r in shape for a in r.attacks),
    )


# --- merge --------------------------------------------------------------------------------------------------


def _groups(findings: Sequence[Finding]) -> List[List[int]]:
    """Indexes of ``findings`` grouped by ``same_issue``, in first-seen order; a finding joins the first group
    whose every member is ``same_issue`` with it (no chaining: 10, 13 and 16 make two groups), else starts
    its own."""
    groups: List[List[int]] = []
    for i, finding in enumerate(findings):
        home = next((g for g in groups if all(same_issue(finding, findings[j]) for j in g)), None)
        if home is None:
            groups.append([i])
        else:
            home.append(i)
    return groups


def _sort_key(record: _Record) -> Tuple[str, float, str]:
    """Id order inside a tier: primary file, first line (no lines last), name."""
    return record.file, (record.ranges[0][0] if record.ranges else math.inf), record.name


def _numbered(records: Sequence[_Record]) -> List[Tuple[str, int]]:
    """``(issue id, index into records)`` pairs, ids numbered per tier in ``_sort_key`` order, tiers
    critical first."""
    out: List[Tuple[str, int]] = []
    for rank, tier in enumerate(TIERS):
        tiered = sorted((n for n, r in enumerate(records) if r.rank == rank),
                        key=lambda n: _sort_key(records[n]))
        out += [(f"{_LETTER[tier]}{k}", n) for k, n in enumerate(tiered, start=1)]
    return out


def _number(records: Sequence[_Record]) -> List[Issue]:
    """Schema issues with ids numbered per tier in ``_sort_key`` order, tiers critical first."""
    return [records[n].issue(issue_id) for issue_id, n in _numbered(records)]


Member = Tuple[str, Finding]
Trace = Dict[str, List[Tuple[str, str]]]


def _member_groups(reports: Sequence[ReviewerReport]) -> List[List[Member]]:
    """``(slot, finding)`` members of every report, grouped by ``_groups``."""
    items = [(report.reviewer, finding) for report in reports for finding in report.findings]
    return [[items[i] for i in group] for group in _groups([finding for _, finding in items])]


def _by_rank(records: Iterable[_Record]) -> List[_Record]:
    """``records`` sorted by rank, critical first (stable)."""
    return sorted(records, key=lambda r: r.rank)


def _trace(groups: Sequence[Sequence[Member]], numbered: Sequence[Tuple[str, int]]) -> Trace:
    """Issue id -> ``(slot, finding_key)`` of each finding merged into it."""
    return {issue_id: [(slot, finding_key(f)) for slot, f in groups[n]] for issue_id, n in numbered}


def merge_findings_traced(reports: Sequence[ReviewerReport]) -> Tuple[List[Issue], Trace]:
    """``merge_findings`` plus its trace: issue id -> ``(source slot, finding_key)`` per merged finding."""
    groups = _member_groups(reports)
    records = [_combine(_by_rank(_Record.of_finding(*m) for m in group)) for group in groups]
    numbered = _numbered(records)
    return [records[n].issue(i) for i, n in numbered], _trace(groups, numbered)


def merge_findings(reports: Sequence[ReviewerReport]) -> List[Issue]:
    """Schema issue dicts from every report's findings, merged by ``same_issue`` and numbered per tier."""
    return merge_findings_traced(reports)[0]


Verdicts = Mapping[Tuple[str, str], Refutation]


def _refuted(member: Member, verdicts: Verdicts) -> Optional[Refutation]:
    """The refuted verdict on ``member``; None when upheld or never refuted (a folded source)."""
    found = verdicts.get((member[0], finding_key(member[1])))
    return found if found is not None and found.verdict is RefutationVerdict.refuted else None


@dataclass(frozen=True)
class _Judged:
    """One merged group under refutation: its record, the ``refuted`` evidence when every finding was
    refuted, and the merge notes a mixed group's refuted findings leave."""

    record: _Record
    refuted: Optional[str] = None
    notes: Tuple[str, ...] = ()


def _judge(group: Sequence[Member], verdicts: Verdicts) -> _Judged:
    """``_Judged`` for one group: upheld findings shape a mixed group; refuted ones add only notes."""
    refuted = {n: r for n, r in ((n, _refuted(m, verdicts)) for n, m in enumerate(group)) if r is not None}
    records = [_Record.of_finding(*m) for m in group]
    upheld = _by_rank(r for n, r in enumerate(records) if n not in refuted)
    if not refuted or not upheld:
        evidence = "\n\n".join(_union(r.evidence for r in refuted.values())) or None
        return _Judged(_combine(_by_rank(records)), evidence)
    notes = tuple(f"refuted ({group[n][0]}) {group[n][1].name}: {r.evidence}" for n, r in refuted.items())
    return _Judged(_combine(upheld), None, notes)


def merge_adversarial(reports: Sequence[ReviewerReport],
                      refutations: Mapping[str, RefutationReport]) -> Tuple[List[Issue], List[str]]:
    """Issues and merge notes from every source report (reviewer, code refuter, folded), grouped as
    ``merge_findings`` groups them, with the findings refuters' verdicts looked up per group member by
    (slot, finding_key).

    A finding without a refutation entry counts as upheld. An issue whose every finding was refuted
    carries ``refuted`` (the evidence, distinct texts joined by a blank line). A mixed group is built from
    its upheld findings only; each refuted finding contributes only its evidence, as one
    ``<issue id>: refuted (<slot>) <name>: <evidence>`` note. With nothing refuted the issues equal
    ``merge_findings``.
    """
    verdicts = {(rep.target, r.key): r for rep in refutations.values() for r in rep.refutations}
    judged = [_judge(group, verdicts) for group in _member_groups(reports)]
    numbered = _numbered([j.record for j in judged])
    issues: List[Issue] = []
    notes: List[str] = []
    for issue_id, n in numbered:
        issue = judged[n].record.issue(issue_id)
        if judged[n].refuted is not None:
            issue["refuted"] = judged[n].refuted
        issues.append(issue)
        notes += [f"{issue_id}: {note}" for note in judged[n].notes]
    return issues, notes


def _tokens(name: object) -> Set[str]:
    """Lowercase alphanumeric tokens of an issue name."""
    return set(_TOKEN.findall(str(name).lower()))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    """Jaccard similarity of two token sets (0 when both are empty)."""
    return len(a & b) / len(a | b) if a | b else 0.0


def merge_candidates(issues: Sequence[Issue]) -> List[Tuple[str, str]]:
    """Id pairs sharing a file whose name tokens have Jaccard similarity of at least 0.5."""
    pairs: List[Tuple[str, str]] = []
    for j, b in enumerate(issues):
        for a in issues[:j]:
            shared = set(_files(a)) & set(_files(b))
            if shared and _jaccard(_tokens(a["name"]), _tokens(b["name"])) >= 0.5:
                pairs.append((str(a["id"]), str(b["id"])))
    return pairs


# --- append after build -------------------------------------------------------------------------------------


def _highest(issues: Sequence[Issue], tier: str) -> int:
    """Highest id number of ``tier`` among ``issues`` (0 when the tier is empty)."""
    return max((int(str(i["id"])[1:]) for i in issues if _tier(str(i["id"])) == tier), default=0)


def append_findings(existing: Sequence[Issue], report: ReviewerReport) -> List[Issue]:
    """Schema issues for one report, one issue per finding (no grouping: findings on the same lines stay
    separate), numbered as ``merge_findings`` numbers them, with ids continuing per tier after the highest
    id of ``existing``; ``existing`` is neither renumbered nor merged into."""
    offset = {tier: _highest(existing, tier) for tier in TIERS}
    added = _number([_combine([_Record.of_finding(report.reviewer, f)]) for f in report.findings])
    return [{**i, "id": f"{str(i['id'])[0]}{int(str(i['id'])[1:]) + offset[_tier(str(i['id']))]}"}
            for i in added]


def cross_candidates(existing: Sequence[Issue], new: Sequence[Issue]) -> List[Tuple[str, str]]:
    """``merge_candidates`` pairs of one ``existing`` id and one ``new`` id, existing id first."""
    old = {str(i["id"]) for i in existing}
    return [(a, b) for a, b in merge_candidates([*existing, *new]) if (a in old) != (b in old)]


# --- verdict ------------------------------------------------------------------------------------------------


# Used by review_waves (cut tie-breaks and group ordering).
def _id_key(issue_id: str) -> Tuple[int, int]:
    """Natural id order: tier, then number."""
    return _RANK[_tier(issue_id)], int(issue_id[1:])


def _tolerant_key(issue_id: str) -> Tuple[int, int, str]:
    """Natural id order that accepts any string: well-formed ids by tier and number, others after them."""
    match = _ISSUE_ID.match(issue_id)
    if match is None:
        return len(TIERS), 0, issue_id
    return _RANK[_TIER_OF[match.group(1)]], int(match.group(2)), issue_id


def _listed(ids: Iterable[str]) -> str:
    """Ids in natural order (malformed ids last), comma-separated."""
    return ", ".join(sorted(ids, key=_tolerant_key))


def issues_by_severity(issues: Sequence[Issue]) -> Dict[str, List[Issue]]:
    """Issues keyed by tier (every tier present), in input order."""
    return {tier: [i for i in issues if _tier(str(i["id"])) == tier] for tier in TIERS}


def _ids(issues: Mapping[str, Sequence[Issue]]) -> Set[str]:
    """Every issue id across the tiers."""
    return {str(i["id"]) for tier in issues.values() for i in tier}


def _closed_ids(resolutions: Sequence[Mapping[str, object]]) -> Set[str]:
    """Ids whose latest resolution is ``RESOLVED``, ``CLOSED_NO_ACTION`` or ``REFUTED``."""
    return {i for i, status in latest_statuses(resolutions).items() if status in CLOSED_STATUSES}


def _bubbled_ids(bubbles: Sequence[str], bubble_up: Sequence[Mapping[str, object]]) -> Set[str]:
    """Ids in ``bubbles`` or the ``bubble_up`` ledger."""
    return set(bubbles) | {str(b["id"]) for b in bubble_up}


def _entry_ids(resolutions: Sequence[Mapping[str, object]]) -> Set[str]:
    """Every id any resolution names, whatever its status (the orphan check and the merge refusal)."""
    return {str(r["id"]) for r in resolutions}


def _mentioned_ids(resolutions: Sequence[Mapping[str, object]], bubbles: Sequence[str],
                   bubble_up: Sequence[Mapping[str, object]]) -> Set[str]:
    """Every id any resolution (whatever its status), ``bubbles`` or ``bubble_up`` entry names, raw: the
    orphan check of ``compute_verdict`` and ``review_edit._disposed_ids``."""
    return _entry_ids(resolutions) | _bubbled_ids(bubbles, bubble_up)


def _named_ids(resolutions: Sequence[Mapping[str, object]], bubbles: Sequence[str],
               bubble_up: Sequence[Mapping[str, object]]) -> Set[str]:
    """Ids carrying a disposition: a resolution, a ``bubbles`` or a ``bubble_up`` entry; an id whose latest
    resolution is ``NOT_RESOLVED`` carries none (a refutation overruled to Phase 5 waves reopens it).
    No production caller: the orphan check and ``review_edit._disposed_ids`` read ``_mentioned_ids``."""
    return _mentioned_ids(resolutions, bubbles, bubble_up) - reopened_ids(resolutions)


def _settled_ids(resolutions: Sequence[Mapping[str, object]], bubbles: Sequence[str],
                 bubble_up: Sequence[Mapping[str, object]]) -> Set[str]:
    """Ids closed (latest status in ``CLOSED_STATUSES``) or bubbled; a ``DOWNGRADED_TO_*`` (or any other
    non-closing) resolution alone does not settle an id, and a latest ``NOT_RESOLVED`` leaves it open
    whatever ``bubbles`` or ``bubble_up`` say."""
    return (_closed_ids(resolutions) | _bubbled_ids(bubbles, bubble_up)) - reopened_ids(resolutions)


def undispositioned_ids(doc: Mapping[str, object]) -> List[str]:
    """Issue ids of a review document neither closed nor bubbled, natural order."""
    settled = _settled_ids(doc.get("post_review_resolutions") or [],  # type: ignore[arg-type]
                           doc.get("bubbles") or [], doc.get("bubble_up") or [])  # type: ignore[arg-type]
    return sorted(_ids(doc["issues"]) - settled, key=_tolerant_key)  # type: ignore[arg-type]


def _ready_text(ids: Set[str], resolutions: Sequence[Mapping[str, object]], closed: Set[str],
                bubbled: Set[str]) -> str:
    """READY line: R of T resolved (closed ids not REFUTED), B bubbled, then ``, K refuted`` when K > 0."""
    latest = latest_statuses(resolutions)
    refuted = {i for i in closed if latest.get(i) == "REFUTED"}
    text = f"READY TO MERGE - {len(closed - refuted)} of {len(ids)} findings resolved, {len(bubbled)} bubbled"
    return f"{text}, {len(refuted)} refuted" if refuted else text


def compute_verdict(issues: Mapping[str, Sequence[Issue]], resolutions: Sequence[Mapping[str, object]],
                    bubbles: Sequence[str], bubble_up: Sequence[Mapping[str, object]]) -> str:
    """Verdict line per the pr-review verdict rule; an orphan disposition id raises ``ValueError``. The
    READY line counts REFUTED ids apart from resolved ones (``_ready_text``)."""
    ids = _ids(issues)
    named = _mentioned_ids(resolutions, bubbles, bubble_up)
    if named - ids:
        raise ValueError(f"orphan disposition ids (match no issue): {_listed(named - ids)}")
    closed = _closed_ids(resolutions)
    for tier in ("critical", "important"):
        open_ids = {str(i["id"]) for i in issues.get(tier, ())} - closed
        if open_ids:
            return f"NOT READY TO MERGE - {tier}: {_listed(open_ids)}"
    pending = ids - _settled_ids(resolutions, bubbles, bubble_up)
    if pending:
        return f"NOT READY TO MERGE - minor findings pending Phase 5: {_listed(pending)}"
    bubbled = _bubbled_ids(bubbles, bubble_up) - closed
    return _ready_text(ids, resolutions, closed, bubbled)


# --- amend --------------------------------------------------------------------------------------------------


def _flat(issues: Sequence[Issue]) -> List[Issue]:
    """Deep copies of ``issues`` ordered by tier, input order within a tier."""
    return [copy.deepcopy(i) for tier in issues_by_severity(issues).values() for i in tier]


def _find(issues: Sequence[Issue], issue_id: str) -> Issue:
    """The issue with ``issue_id``; ``ValueError`` when absent."""
    for issue in issues:
        if issue["id"] == issue_id:
            return issue
    raise ValueError(f"no issue {issue_id}")


def _tier_name(severity: Union[Severity, str]) -> str:
    """Tier name from a ``Severity`` or a letter / name in any case; ``ValueError`` otherwise."""
    text = str(getattr(severity, "value", severity)).strip().lower()
    tier = _TIER_OF.get(text.upper(), text)
    if tier not in TIERS:
        raise ValueError(f"unknown severity {severity!r}")
    return tier


def regrade(issues: Sequence[Issue], issue_id: str, severity: Union[Severity, str]) -> List[Issue]:
    """Issues with ``issue_id`` moved to ``severity`` under a new id at the end of that tier; the moved
    issue keeps every other key, ``refuted`` included."""
    tier = _tier_name(severity)
    out = _flat(issues)
    moving = _find(out, issue_id)
    if _tier(issue_id) == tier:
        raise ValueError(f"{issue_id} is already {tier}")
    numbers = [int(str(i["id"])[1:]) for i in out if _tier(str(i["id"])) == tier]
    out.remove(moving)
    moving["id"] = f"{_LETTER[tier]}{max(numbers, default=0) + 1}"
    return _flat([*out, moving])


FIX_KINDS = ("mechanical", "judgment")


def set_fix_kind(issues: Sequence[Issue], issue_id: str, fix_kind: str) -> List[Issue]:
    """Issues with ``issue_id`` given ``fix_kind`` in place (id and order kept); a missing kind reads as
    judgment."""
    if fix_kind not in FIX_KINDS:
        raise ValueError(f"unknown fix kind {fix_kind!r} (expected {' or '.join(FIX_KINDS)})")
    out = _flat(issues)
    moving = _find(out, issue_id)
    if (moving.get("fix_kind") or "judgment") == fix_kind:
        raise ValueError(f"{issue_id} is already {fix_kind}")
    moving["fix_kind"] = fix_kind
    return out


def _folded(merged: Sequence[Issue], keep: str) -> Issue:
    """``merged`` (keep first) combined into one issue under ``keep``, upheld issues (no ``refuted`` key)
    ordered first and shaping it; ``refuted`` kept only when every issue carries it."""
    upheld = [i for i in merged if "refuted" not in i]
    refuted = [i for i in merged if "refuted" in i]
    records = [_Record.of_issue(i) for i in [*upheld, *refuted]]
    combined = _combine(records, len(upheld) or None)
    out = replace(combined, rank=_RANK[_tier(keep)]).issue(keep)
    if not upheld:
        out["refuted"] = "\n\n".join(_union(str(i["refuted"]) for i in refuted))
    return out


def merge_ids(issues: Sequence[Issue], keep: str, drop: Sequence[str]) -> List[Issue]:
    """Issues with each ``drop`` id folded into ``keep`` (fixes, files, lines, reviewers, fix kind).

    In a mixed group (some issues carry ``refuted``) the upheld issues supply the name, primary file,
    summary and fix kind; files, lines, fixes and reviewers union over every issue; the id stays ``keep``.
    The refuted issues' evidence is dropped in a mixed group (the merged issue is upheld).
    """
    if not drop or keep in drop:
        raise ValueError("merge needs at least one id to drop, and keep must not be dropped")
    out = _flat(issues)
    kept = _find(out, keep)
    dropped = [_find(out, d) for d in drop]
    if any(_RANK[_tier(d)] < _RANK[_tier(keep)] for d in drop):
        raise ValueError(f"cannot fold a higher-severity issue into {keep}; regrade first")
    out[out.index(kept)] = _folded([kept, *dropped], keep)
    return [i for i in out if i["id"] not in drop]


def refuted_resolutions(issues: Sequence[Issue], date: str) -> List[Dict[str, str]]:
    """One ``REFUTED`` resolution (``date``, the issue's ``refuted`` evidence) per issue carrying the key,
    in input order; ``ValueError`` naming the id when ``refuted`` is not a non-blank string."""
    out: List[Dict[str, str]] = []
    for issue in (i for i in issues if "refuted" in i):
        evidence = issue["refuted"]
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"{issue['id']}: refuted needs non-blank evidence text")
        out.append(_resolution(str(issue["id"]), "REFUTED", date, evidence))
    return out


def strip_refuted(issues: Sequence[Issue]) -> List[Issue]:
    """Deep copies of ``issues`` without the ``refuted`` key."""
    return [{k: copy.deepcopy(v) for k, v in i.items() if k != "refuted"} for i in issues]


# --- review document and validation -------------------------------------------------------------------------


def slugify_title(title: str) -> str:
    """Filename slug of a PR title (pr-team rule: strip backticks and colons, ``_`` runs, keep ``._-``).

    A slug longer than ``MAX_SLUG_LEN`` is cut at the last ``_`` inside the limit (hard cut without one), so
    the ``Review artifacts:`` line of a merge message stays within its column budget.
    """
    text = title.replace("`", "").replace(":", "")
    text = re.sub(r"\s+", "_", text)
    slug = _SLUG_DROP.sub("", text).strip("_")
    if len(slug) <= MAX_SLUG_LEN:
        return slug
    head = slug[:MAX_SLUG_LEN + 1]
    cut = head.rfind("_")
    return (head[:cut] if cut > 0 else slug[:MAX_SLUG_LEN]).rstrip("_")


def default_schema_ref() -> str:
    """The plugin ``PR_REVIEW.schema.json``'s ``$id`` (its file name when the schema carries none)."""
    from harness_lib.project import plugin_root
    schema = json.loads((plugin_root() / "schemas" / SCHEMA_NAME).read_text(encoding="utf-8"))
    return str(schema.get("$id") or SCHEMA_NAME)


def schema_ref_for(review_path: Path, cfg: HarnessConfig) -> str:
    """``schema_ref`` for a review written to ``review_path``: the POSIX path from its directory to the
    project's pinned schema when ``cfg`` pins one, else ``default_schema_ref()``."""
    pinned = cfg.path(cfg.schemas_dir) / SCHEMA_NAME
    if not pinned.is_file():
        return default_schema_ref()
    return Path(os.path.relpath(pinned.resolve(), Path(review_path).resolve().parent)).as_posix()


def review_document(meta: Mapping[str, object], draft: Mapping[str, object],
                    dispatch_time: Mapping[str, object], *,
                    schema_ref: Optional[str] = None) -> Dict[str, object]:
    """PR_REVIEW document from capture ``meta``, the merge ``draft`` and the Phase 1 ``dispatch_time`` block.

    ``meta`` keys: pr, pr_title, branch, base_branch, base_sha, head_sha, review_date, stats and optional
    scoped_review_files. ``draft`` keys: issues (flat list), strengths, reviewers. ``schema_ref`` defaults
    to ``default_schema_ref()``; a writer that knows the target path passes ``schema_ref_for``.

    A draft issue carrying ``refuted`` gets one ``REFUTED`` resolution dated ``review_date``
    (``refuted_resolutions``) and loses the key (``strip_refuted``); the verdict counts those resolutions,
    and ``post_review_resolutions`` is written only when there is one.
    """
    flat = _flat(draft["issues"])  # type: ignore[arg-type]
    resolutions = refuted_resolutions(flat, str(meta["review_date"]))
    issues = issues_by_severity(strip_refuted(flat))
    named = ("pr", "pr_title", "branch", "base_branch", "base_sha", "head_sha", "review_date")
    doc: Dict[str, object] = {
        "schema_ref": schema_ref or default_schema_ref(), "version": SCHEMA_VERSION,
        **{k: meta[k] for k in named},
        "verdict": compute_verdict(issues, resolutions, [], []), "stats": copy.deepcopy(meta["stats"]),
        "reviewers": list(draft["reviewers"]),  # type: ignore[call-overload]
        "scoped_review_files": list(meta.get("scoped_review_files") or []),  # type: ignore[call-overload]
        "bubbles": [], "strengths": list(draft["strengths"]),  # type: ignore[call-overload]
        "issues": issues, "bubble_up": [],
        "verification_log": {"dispatch_time": copy.deepcopy(dict(dispatch_time)), "pre_fix_time": PENDING},
    }
    if resolutions:
        doc["post_review_resolutions"] = resolutions
    return doc


def review_validator(schema_file: Path) -> Validator:
    """Validator for the PR_REVIEW schema at ``schema_file``; a ``$ref`` to a sibling ``*.schema.json``
    loads that sibling on first use (cached per path and modification time)."""
    path = Path(schema_file).resolve()
    return _cached_validator(str(path), path.stat().st_mtime_ns)


@functools.lru_cache(maxsize=8)
def _cached_validator(schema_file: str, _mtime_ns: int) -> Validator:
    """The validator ``review_validator`` returns; ``_mtime_ns`` only keys the cache."""
    import jsonschema
    from referencing import Registry

    path = Path(schema_file)
    schema = json.loads(path.read_text(encoding="utf-8"))
    registry = Registry(retrieve=_sibling_retriever(path.parent))
    return jsonschema.validators.validator_for(schema)(schema, registry=registry)


def _sibling_retriever(folder: Path) -> Callable[[str], object]:
    """A ``referencing`` retrieve callback: the URI's last segment names a ``*.schema.json`` in ``folder``.

    Only a referenced sibling is read, so an unrelated file in the folder never breaks validation, and
    a sibling without ``$schema`` is read as draft 2020-12, the validator default.
    """
    from referencing import Resource
    from referencing.exceptions import NoSuchResource
    from referencing.jsonschema import DRAFT202012

    @functools.lru_cache(maxsize=None)
    def retrieve(uri: str) -> Resource:
        name = uri.rsplit("/", 1)[-1]
        sibling = folder / name
        if not name.endswith(".schema.json") or not sibling.is_file():
            raise NoSuchResource(ref=uri)
        content = json.loads(sibling.read_text(encoding="utf-8"))
        return Resource.from_contents(content, default_specification=DRAFT202012)

    return retrieve


def _schema_problems(doc: Mapping[str, object], schema_file: Path) -> List[str]:
    """One ``schema: <path>: <message>`` line per schema error."""
    errors = sorted(review_validator(schema_file).iter_errors(doc),
                    key=lambda e: list(map(str, e.absolute_path)))
    return [f"schema: {'.'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors]


def _pending_problems(doc: Mapping[str, object]) -> List[str]:
    """The hook's Layer 2 rule: a pending ``pre_fix_time`` allows no READY verdict and no resolution other
    than ``REFUTED`` / ``BUBBLED`` / ``NOT_RESOLVED``."""
    log = doc.get("verification_log")
    if not isinstance(log, dict) or log.get("pre_fix_time") != PENDING:
        return []
    ready = str(doc.get("verdict") or "").startswith("READY TO MERGE")
    if ready or counted_resolutions(doc.get("post_review_resolutions") or []):  # type: ignore[arg-type]
        return ["pre_fix_time is still pending but the review has a READY verdict or resolutions"]
    return []


def validate_review(doc: Mapping[str, object], repo: Optional[Path] = None) -> List[str]:
    """Problems that block writing ``doc``: schema errors, the pending rule and the issue-count check.

    ``repo`` names the project whose schema governs (default: the active project).
    """
    from harness_lib.project import schema_path
    from harness_lib.validation.pr_json_validation import IssueTabulationError, validate_issue_counts

    problems = _schema_problems(doc, schema_path(SCHEMA_NAME, config_for(repo))) + _pending_problems(doc)
    try:
        validate_issue_counts(dict(doc))
    except IssueTabulationError as exc:
        problems.append(f"issue counts: {exc.message}")
    return problems


# --- closeout -----------------------------------------------------------------------------------------------


def _resolution(issue_id: str, status: str, today: str, evidence: str) -> Dict[str, str]:
    """A ``post_review_resolutions`` entry."""
    return {"id": issue_id, "status": status, "date": today, "evidence": evidence}


def _entry_problem(entry: FixEntry, fixer: str, bin_files: Set[str], changed: Set[str],
                   created: Set[str]) -> Optional[str]:
    """Why a fixed entry does not count, or None when every listed file is changed and in bounds and every
    ``no_change`` file lies in the fixer's set."""
    unchanged = [f for f in entry.files if f not in changed]
    if unchanged:
        return f"{entry.id} ({fixer}): listed files not changed since build: {', '.join(unchanged)}"
    outside = [f for f in entry.files if f not in bin_files and f not in created]
    if outside:
        return f"{entry.id} ({fixer}): files outside the fixer's set and not new: {', '.join(outside)}"
    foreign = [f for f in entry.no_change if f not in bin_files]
    if foreign:
        return f"{entry.id} ({fixer}): no_change files outside the fixer's set: {', '.join(foreign)}"
    return None


@dataclass(frozen=True)
class _Planned:
    """What closeout checks entries against: fixer file sets, each fixer's assigned ids (None when no plan
    parts are known), per split issue each fixer's part, and per issue its own files (primary and also)."""

    fixer_files: Mapping[str, Sequence[str]]
    split: Mapping[str, Mapping[str, Tuple[str, ...]]]
    ids: Set[str]
    assigned: Optional[Mapping[str, Set[str]]] = None
    own: Mapping[str, Set[str]] = field(default_factory=dict)

    def is_assigned(self, fixer: str, issue_id: str) -> bool:
        """True when ``issue_id`` is in ``fixer``'s planned parts, or when no parts were given."""
        return self.assigned is None or issue_id in self.assigned.get(fixer, set())

    def owned(self, fixer: str, issue_id: str) -> Optional[Set[str]]:
        """Files ``fixer`` may list for ``issue_id``; None when it owns none. A split part also allows the
        rest of the fixer's file set (widened tests, named paths, its other issues' files) except the
        same issue's planned parts other fixers own."""
        if fixer not in self.fixer_files:
            return None
        if issue_id in self.split:
            part = self.split[issue_id].get(fixer)
            rest = set(self.fixer_files[fixer]) - set(self.required(issue_id))
            return None if part is None else set(part) | rest
        return set(self.fixer_files[fixer])

    def required(self, issue_id: str) -> List[str]:
        """Every file planned for a split issue across its fixers, first-seen order."""
        return list(_union(f for part in self.split[issue_id].values() for f in part))


def _full_files(issues: Iterable[Issue]) -> Dict[str, Set[str]]:
    """Issue id -> full file set."""
    return {str(i["id"]): set(_files(i)) for i in issues}


def _doc_issues(doc: Mapping[str, object]) -> List[Issue]:
    """Every issue of a review document, tier by tier."""
    return [i for tier in doc["issues"].values() for i in tier]  # type: ignore[attr-defined]


def _mechanical_ids(issues: Iterable[Issue]) -> Set[str]:
    """Ids of the ``mechanical`` issues."""
    return {str(i["id"]) for i in issues if i.get("fix_kind") == "mechanical"}


def _is_split(issue_id: str, fixers: Mapping[str, Tuple[str, ...]], full: Mapping[str, Set[str]],
              mechanical: Set[str]) -> bool:
    """True when some fixer owns less than the issue's file set, or when a mechanical issue's planned part
    files number more than one (whatever the placement, one fixer included)."""
    if issue_id not in full:
        return False
    if any(set(f) < full[issue_id] for f in fixers.values()):
        return True
    return issue_id in mechanical and len({f for files in fixers.values() for f in files}) > 1


def _split_parts(full: Mapping[str, Set[str]], parts: Optional[Parts],
                 mechanical: Optional[Set[str]] = None) -> Dict[str, Dict[str, Tuple[str, ...]]]:
    """Issue id -> fixer -> owned files, for ids planned as parts (``_is_split``)."""
    by_id: Dict[str, Dict[str, Tuple[str, ...]]] = {}
    for fixer, owned in (parts or {}).items():
        for issue_id, files in owned.items():
            by_id.setdefault(issue_id, {})[fixer] = tuple(files)
    return {i: fixers for i, fixers in by_id.items() if _is_split(i, fixers, full, mechanical or set())}


def _check_entry(planned: _Planned, fixer: str, entry: FixEntry, changed: Set[str],
                 created: Set[str]) -> Optional[str]:
    """Why ``entry`` of ``fixer`` does not count, or None; a problem leads with the issue id."""
    if fixer not in planned.fixer_files:
        return f"{entry.id} ({fixer}): not a planned fixer; not resolved"
    if entry.id not in planned.ids:
        return f"{entry.id} ({fixer}): no such issue"
    if not planned.is_assigned(fixer, entry.id):
        return f"{entry.id} ({fixer}): not assigned to this fixer"
    owned = planned.owned(fixer, entry.id)
    if owned is None:
        return f"{entry.id} ({fixer}): no part of {entry.id} planned for this fixer"
    return _entry_problem(entry, fixer, owned, changed, created) or _own_file_problem(planned, fixer, entry)


def _own_file_problem(planned: _Planned, fixer: str, entry: FixEntry) -> Optional[str]:
    """Why a non-split entry that edited files edited none of its issue's own files, or None; widened tests,
    docs and the fixer's other issues' files alone do not resolve an issue."""
    if entry.id in planned.split or not entry.files or set(entry.files) & planned.own.get(entry.id, set()):
        return None
    own = ", ".join(sorted(planned.own.get(entry.id, set())))
    return f"{entry.id} ({fixer}): no listed file is one of the issue's own files ({own})"


def _valid_entries(planned: _Planned, fixes: Sequence[FixReport], changed: Set[str],
                   created: Set[str]) -> Tuple[Dict[str, List[FixEntry]], List[Tuple[str, str]]]:
    """Validated fixed entries per issue id (first-seen order), plus each rejected entry's (id, problem)."""
    valid: Dict[str, List[FixEntry]] = {}
    rejected: List[Tuple[str, str]] = []
    for report in fixes:
        for entry in report.fixed:
            problem = _check_entry(planned, report.fixer, entry, changed, created)
            if problem:
                rejected.append((entry.id, problem))
            else:
                valid.setdefault(entry.id, []).append(entry)
    return valid, rejected


def _present_files(planned: _Planned, issue_id: str, entries: Sequence[FixEntry],
                   changed: Set[str]) -> List[str]:
    """The issue's own files its entries list under ``no_change`` that are in ``changed``: a fix already in
    the tree (an earlier entry or the developer made it). ``changed`` excludes files another issue's
    validated entry of this closeout edited (``_apply_fixed``), so a sibling edit is no proof."""
    own = planned.own.get(issue_id, set())
    return [f for f in _union(f for e in entries for f in e.no_change) if f in own and f in changed]


def _edited_own(planned: _Planned, issue_id: str, entries: Sequence[FixEntry]) -> bool:
    """True when some entry edited one of the issue's own files (primary or also)."""
    own = planned.own.get(issue_id, set())
    return any(set(e.files) & own for e in entries)


def _counts(planned: _Planned, issue_id: str, entries: Sequence[FixEntry], changed: Set[str]) -> bool:
    """True when some entry edited one of the issue's own files or the fix is already present
    (``_present_files``); edits of other files alone (another issue's, a widened test) do not count."""
    present = _present_files(planned, issue_id, entries, changed)
    return _edited_own(planned, issue_id, entries) or bool(present)


def _sibling_edits(valid: Mapping[str, Sequence[FixEntry]], issue_id: str) -> Set[str]:
    """Files the validated entries of issues other than ``issue_id`` list under ``files``."""
    return {f for other, entries in valid.items() if other != issue_id for e in entries for f in e.files}


def _coverage_problem(planned: _Planned, issue_id: str, entries: Sequence[FixEntry],
                      changed: Set[str]) -> Optional[str]:
    """``<id> partially fixed: missing <files>`` when a split issue's entries miss a planned file (a file
    edited or marked ``no_change`` by its owner counts as covered); a problem too when no entry edited one
    of the issue's own files and the fix is not already present."""
    if not _counts(planned, issue_id, entries, changed):
        return f"{issue_id}: no fixed entry edited a file (only no_change files)"
    if issue_id not in planned.split:
        return None
    covered = {f for entry in entries for f in (*entry.files, *entry.no_change)}
    missing = [f for f in planned.required(issue_id) if f not in covered]
    return f"{issue_id} partially fixed: missing {', '.join(missing)}" if missing else None


def _fixed_evidence(planned: _Planned, issue_id: str, entries: Sequence[FixEntry], changed: Set[str],
                    head: str) -> str:
    """Evidence for a fixed issue: the entries' ``what`` (every one for a split issue), plus an
    ``(already present: ...)`` note when no entry edited one of the issue's own files."""
    whats = _union(e.what for e in entries) if issue_id in planned.split else (entries[0].what,)
    evidence = f"{head} {EVIDENCE_NOTE} - {'; '.join(whats)}"
    if _edited_own(planned, issue_id, entries):
        return evidence
    present = ", ".join(_present_files(planned, issue_id, entries, changed))
    return f"{evidence} (already present: {present} changed since build)"


def _apply_fixed(doc: Dict[str, object], planned: _Planned, valid: Mapping[str, Sequence[FixEntry]],
                 changed: Set[str], head: str, today: str) -> List[Tuple[str, str]]:
    """Append a RESOLVED entry per issue whose validated entries suffice; return each coverage problem's
    (id, problem). A file another issue's validated entry edited never proves this issue already fixed."""
    resolutions: List[Dict[str, str]] = doc["post_review_resolutions"]  # type: ignore[assignment]
    already = _closed_ids(resolutions)
    problems: List[Tuple[str, str]] = []
    for issue_id, entries in valid.items():
        if issue_id in already:
            continue
        own_changed = changed - _sibling_edits(valid, issue_id)
        problem = _coverage_problem(planned, issue_id, entries, own_changed)
        if problem:
            problems.append((issue_id, problem))
            continue
        evidence = _fixed_evidence(planned, issue_id, entries, own_changed, head)
        resolutions.append(_resolution(issue_id, "RESOLVED", today, evidence))
    return problems


def _bubble_problem(planned: _Planned, fixer: str, issue_id: str) -> Optional[str]:
    """Why a bubble of ``issue_id`` by ``fixer`` does not count, or None; a problem leads with the id."""
    if fixer not in planned.fixer_files:
        return f"{issue_id} ({fixer}): not a planned fixer; not bubbled"
    if issue_id not in planned.ids:
        return f"{issue_id} ({fixer}): bubbled id matches no issue"
    if not planned.is_assigned(fixer, issue_id):
        return f"{issue_id} ({fixer}): bubbled id not assigned to this fixer"
    return None


def reopened_bubble_entry(resolutions: Sequence[Mapping[str, object]], issue_id: str, today: str,
                          reason: str) -> Optional[Dict[str, str]]:
    """The ``BUBBLED`` entry (date ``today``, evidence ``reason``) a bubble of ``issue_id`` appends when its
    latest resolution is ``NOT_RESOLVED``, so the id settles through the bubble; None otherwise."""
    if issue_id not in reopened_ids(resolutions):
        return None
    return _resolution(issue_id, "BUBBLED", today, reason)


def _apply_bubbles(doc: Dict[str, object], planned: _Planned, report: FixReport, today: str) -> List[str]:
    """Add each bubble of ``report`` to ``bubbles`` and ``bubble_up`` unless closed; return the problems.

    A bubble counts only from a planned fixer, for an id assigned to it (the rule fixed entries follow).
    An id whose latest resolution is ``NOT_RESOLVED`` also gains a ``BUBBLED`` entry (evidence: the
    bubble's reason), so it settles through the bubble.
    """
    resolutions: List[Dict[str, str]] = doc["post_review_resolutions"]  # type: ignore[assignment]
    resolved = _closed_ids(resolutions)
    problems: List[str] = []
    for bubble in report.bubbled:
        problem = _bubble_problem(planned, report.fixer, bubble.id)
        if problem:
            problems.append(problem)
        elif bubble.id not in resolved:
            entry = reopened_bubble_entry(resolutions, bubble.id, today, bubble.reason)
            if entry is not None:
                resolutions.append(entry)
            if bubble.id not in doc["bubbles"]:  # type: ignore[operator]
                doc["bubbles"].append(bubble.id)  # type: ignore[attr-defined]
            if bubble.id not in {b["id"] for b in doc["bubble_up"]}:  # type: ignore[attr-defined]
                doc["bubble_up"].append(bubble.model_dump(mode="json"))  # type: ignore[attr-defined]
    return problems


def _apply_closed(doc: Dict[str, object], closed: Mapping[str, str], head: str, today: str) -> List[str]:
    """Append a CLOSED_NO_ACTION entry per ``closed`` id not yet closed; return the problems."""
    resolutions: List[Dict[str, str]] = doc["post_review_resolutions"]  # type: ignore[assignment]
    ids, already = _ids(doc["issues"]), _closed_ids(resolutions)  # type: ignore[arg-type]
    problems: List[str] = []
    for issue_id, rationale in closed.items():
        if issue_id not in ids:
            problems.append(f"{issue_id}: closed id matches no issue")
        elif issue_id not in already:
            evidence = f"{head} {EVIDENCE_NOTE} - closed, no action: {rationale}"
            resolutions.append(_resolution(issue_id, "CLOSED_NO_ACTION", today, evidence))
    return problems


def _ensure_bubble_up(doc: Dict[str, object], issue_id: str, text: str) -> None:
    """Add a ``needs_follow_up`` ``bubble_up`` entry for ``issue_id`` (reason: ``text``, one line, at most
    200 characters) unless one exists."""
    ledger: List[Dict[str, object]] = doc["bubble_up"]  # type: ignore[assignment]
    if issue_id not in {str(b["id"]) for b in ledger}:
        reason = " ".join(text.split())[:200]
        ledger.append({"id": issue_id, "classification": "needs_follow_up", "reason": reason})


def _apply_deferred(doc: Dict[str, object], deferred: Mapping[str, str], head: str, today: str) -> List[str]:
    """Resolve each ``deferred`` id not yet closed as a developer-confirmed defer; return the problems."""
    resolutions: List[Dict[str, str]] = doc["post_review_resolutions"]  # type: ignore[assignment]
    ids, already = _ids(doc["issues"]), _closed_ids(resolutions)  # type: ignore[arg-type]
    problems: List[str] = []
    for issue_id, text in deferred.items():
        if issue_id not in ids:
            problems.append(f"{issue_id}: deferred id matches no issue")
        elif issue_id not in already:
            evidence = f"{head} (developer-confirmed defer) - {text}"
            resolutions.append(_resolution(issue_id, "RESOLVED", today, evidence))
            _ensure_bubble_up(doc, issue_id, text)
    return problems


def _planned(full: Mapping[str, Set[str]], fixer_files: Mapping[str, Sequence[str]],
             parts: Optional[Parts], mechanical: Optional[Set[str]] = None) -> _Planned:
    """The closeout plan over ``full`` (issue id -> files): fixer file sets, split issues (``mechanical``
    ids count as split once planned over more than one file) and, when ``parts`` is given, assigned ids."""
    assigned = None if parts is None else {fixer: set(owned) for fixer, owned in parts.items()}
    return _Planned(fixer_files, _split_parts(full, parts, mechanical), set(full), assigned, full)


def _resolved_problem(issue: Optional[Issue], issue_id: str, changed: Set[str]) -> Optional[str]:
    """Why a developer-directed resolution of ``issue_id`` does not count, or None."""
    if issue is None:
        return f"{issue_id}: resolved id matches no issue"
    if not set(_files(issue)) & changed:
        return f"{issue_id}: none of its files changed since build: {', '.join(_files(issue))}"
    return None


def _apply_resolved(doc: Dict[str, object], resolved: Mapping[str, str], changed: Set[str], head: str,
                    today: str) -> List[str]:
    """Resolve each ``resolved`` id (a fix in the tree no accepted fixer entry records: developer-directed
    work or a rejected fixer edit) when one of its files changed; return the problems."""
    resolutions: List[Dict[str, str]] = doc["post_review_resolutions"]  # type: ignore[assignment]
    by_id, already = {str(i["id"]): i for i in _doc_issues(doc)}, _closed_ids(resolutions)
    problems: List[str] = []
    for issue_id, what in resolved.items():
        problem = _resolved_problem(by_id.get(issue_id), issue_id, changed)
        if problem:
            problems.append(problem)
        elif issue_id not in already:
            evidence = f"{head} {EVIDENCE_NOTE} - {what} (outside fixer waves)"
            resolutions.append(_resolution(issue_id, "RESOLVED", today, evidence))
    return problems


def apply_closeout(review: Mapping[str, object], fixes: Sequence[FixReport],
                   fixer_files: Mapping[str, Sequence[str]], changed: Set[str], created: Set[str], head: str,
                   today: str, closed: Mapping[str, str], parts: Optional[Parts] = None,
                   deferred: Optional[Mapping[str, str]] = None,
                   resolved: Optional[Mapping[str, str]] = None) -> Tuple[Dict[str, object], List[str]]:
    """Review with validated fixes resolved, ``closed`` ids closed, fixer bubbles recorded, ``deferred``
    ids resolved as developer-confirmed defers and ``resolved`` ids resolved as a fix in the tree no
    accepted fixer entry records (developer-directed work or a rejected fixer edit); plus problems.

    A fixed entry counts only when every listed file is in ``changed`` and either in its fixer's
    ``fixer_files`` set or in ``created``. ``parts`` (fixer -> issue id -> owned files, as
    ``review_waves.plan_waves`` writes them) assigns ids to fixers: an entry or a bubble for an id outside its
    fixer's parts, or from a fixer outside ``fixer_files``, is rejected with a problem. A rejected entry
    raises nothing when its id ends the closeout closed (a ``CLOSED_STATUSES`` status by any path,
    e.g. a later fixer's valid entry or ``closed``); a rejected bubble always raises its problem. It also
    marks split issues (some fixer owns less than the file set, or a mechanical issue planned over more
    than one file, even in one fixer): there an entry may list its fixer's part and the rest of the fixer's
    file set, never the same
    issue's parts other fixers own, and the issue resolves only when its validated entries together cover
    every planned file, each edited or marked ``no_change`` by its part's fixer (evidence joins their
    ``what`` texts); otherwise it gets a ``partially fixed`` problem. A non-split entry that edits files
    must list at least one of its issue's own files (primary or also); widened files alone are rejected
    with a problem. An issue whose validated entries edited none of its own files gets a problem instead
    of a resolution, unless one of its own files listed under ``no_change`` is in ``changed`` and no other
    issue's validated entry lists it under ``files``: the fix is already present, and the evidence says
    so. Rejected-entry and coverage problems of an id that ends the closeout closed
    (``CLOSED_STATUSES``) are dropped; bubble, ``closed``, ``deferred`` and ``resolved`` problems stay.
    Every problem about one issue leads with its id (``resolvable_hints`` reads it there).
    Only ids already closed (latest status in ``CLOSED_STATUSES``) are skipped. A
    ``deferred`` id (id -> decision text) is RESOLVED with ``<head> (developer-confirmed defer) - <text>``
    evidence and keeps (or gains) a ``needs_follow_up`` ``bubble_up`` entry. A
    ``resolved`` id (id -> what changed) is RESOLVED with ``<head> (working-tree snapshot; developer
    commits) - <what> (outside fixer waves)`` evidence when one of its files is in ``changed``. A fixer
    bubble of an id whose latest resolution is ``NOT_RESOLVED`` appends a ``BUBBLED`` entry. Closed ids
    leave ``bubbles``; the verdict is recomputed.
    """
    doc = copy.deepcopy(dict(review))
    doc["post_review_resolutions"] = list(doc.get("post_review_resolutions") or [])
    doc["bubbles"], doc["bubble_up"] = list(doc.get("bubbles") or []), list(doc.get("bubble_up") or [])
    issues = _doc_issues(doc)
    planned = _planned(_full_files(issues), fixer_files, parts, _mechanical_ids(issues))
    valid, rejected = _valid_entries(planned, fixes, changed, created)
    rejected += _apply_fixed(doc, planned, valid, changed, head, today)
    problems = _apply_closed(doc, closed, head, today)
    problems += _apply_resolved(doc, resolved or {}, changed, head, today)
    for report in fixes:
        problems += _apply_bubbles(doc, planned, report, today)
    problems += _apply_deferred(doc, deferred or {}, head, today)
    resolved = _closed_ids(doc["post_review_resolutions"])  # type: ignore[arg-type]
    problems = [problem for issue_id, problem in rejected if issue_id not in resolved] + problems
    doc["bubbles"] = [b for b in doc["bubbles"] if b not in resolved]  # type: ignore[attr-defined]
    doc["verdict"] = compute_verdict(doc["issues"], doc["post_review_resolutions"],  # type: ignore[arg-type]
                                     doc["bubbles"], doc["bubble_up"])  # type: ignore[arg-type]
    return doc, problems


def resolvable_hints(doc: Mapping[str, object], problems: Sequence[str], changed: Set[str]) -> List[str]:
    """One ``hint:`` line per undispositioned issue a closeout problem names whose own files are in
    ``changed``: the fix may be in the tree with no fixer entry closeout accepts, which ``closeout
    --resolved`` records. Every problem about one issue leads with its id (``<id>:`` or ``<id> (<fixer>):``),
    which names it here. ``partially fixed`` problems get no hint (their route is a ``waves`` rerun for the
    missing parts), nor does a fixer-level problem (``<fixer>: no fix report``, re-dispatched instead)."""
    open_ids = set(undispositioned_ids(doc))
    named = _union(p.split(" ", 1)[0].rstrip(":") for p in problems if " partially fixed: " not in p)
    by_id = {str(i["id"]): i for i in _doc_issues(doc)}
    hints: List[str] = []
    for issue_id in (i for i in named if i in open_ids):
        touched = [f for f in _files(by_id[issue_id]) if f in changed]
        if touched:
            hints.append(f"hint: {issue_id}: {', '.join(touched)} changed since build but no accepted "
                         f"fixer entry records it; if the fix is in place, rerun closeout with --resolved "
                         f'{issue_id}="what changed"')
    return hints


# --- follow-up waves ----------------------------------------------------------------------------------------


def _listed_files(fixes: Sequence[FixReport], known: Set[str]) -> Dict[str, Set[str]]:
    """Issue id -> files any fixed entry lists (edited or ``no_change``) for it, for ids in ``known``."""
    listed: Dict[str, Set[str]] = {}
    for report in fixes:
        for entry in (e for e in report.fixed if e.id in known):
            listed.setdefault(entry.id, set()).update(entry.files, entry.no_change)
    return listed


def _accepted_files(full: Mapping[str, Set[str]], parts: Optional[Parts], fixes: Sequence[FixReport],
                    fixer_files: Mapping[str, Sequence[str]], changed: Set[str],
                    created: Set[str], mechanical: Optional[Set[str]] = None) -> Dict[str, Set[str]]:
    """Issue id -> files (edited or ``no_change``) listed by the fixed entries closeout accepts
    (``_check_entry``), for ids in ``full``. An id whose accepted entries edit no file is absent unless the
    fix is already present, as ``_coverage_problem`` rejects it."""
    planned = _planned(full, fixer_files, parts, mechanical)
    valid, _ = _valid_entries(planned, fixes, changed, created)
    return {issue_id: {f for e in entries for f in (*e.files, *e.no_change)}
            for issue_id, entries in valid.items() if _counts(planned, issue_id, entries, changed)}


def remaining_parts(issues: Sequence[Issue], parts: Optional[Parts], fixes: Sequence[FixReport],
                    fixer_files: Optional[Mapping[str, Sequence[str]]] = None,
                    changed: Optional[Set[str]] = None,
                    created: Optional[Set[str]] = None) -> Dict[str, List[str]]:
    """Issue id -> planned files no counted fixed entry lists yet, for every id some counted entry covers.

    Without ``changed`` every recorded fixed entry counts. With ``changed`` (and ``fixer_files`` /
    ``created``, as ``apply_closeout`` takes them) only entries closeout accepts count, so an entry it
    rejects (unchanged files, unassigned id, files outside the fixer's set) leaves its issue to re-plan.
    A split issue (planned as parts, see ``apply_closeout``) needs each planned file listed by some counted
    entry; any other counted id is fully covered (an empty list). Ids without a counted entry are absent.
    """
    full, mechanical = _full_files(issues), _mechanical_ids(issues)
    split = _split_parts(full, parts, mechanical)
    if changed is None:
        listed = _listed_files(fixes, set(full))
    else:
        listed = _accepted_files(full, parts, fixes, fixer_files or {}, changed, created or set(), mechanical)
    out: Dict[str, List[str]] = {}
    for issue_id, files in listed.items():
        required = _union(f for part in split.get(issue_id, {}).values() for f in part)
        out[issue_id] = [f for f in required if f not in files]
    return out


def only_files(issue: Issue, files: Sequence[str]) -> Issue:
    """Copy of ``issue`` narrowed to ``files`` (issue file order); ``lines`` stays only with the primary
    file; ``ValueError`` when no file of ``files`` belongs to the issue."""
    keep = [f for f in _union(_files(issue)) if f in set(files)]
    if not keep:
        raise ValueError(f"{issue['id']}: none of {', '.join(files)} belongs to the issue")
    out = copy.deepcopy(dict(issue))
    out.pop("files", None)
    if keep[0] != issue["file"]:
        out.pop("lines", None)
    out["file"] = keep[0]
    if len(keep) > 1:
        out["files"] = keep
    return out
