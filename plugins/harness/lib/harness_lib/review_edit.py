"""Per-field editors for a ``PR_REVIEW.schema.json`` document, plus its byte-stable load / save.

Every editor takes a loaded review document and returns a new one (the input is never mutated), so callers
compose edits and write once through ``save_review``, which validates with ``review_merge.validate_review``
and refuses an invalid document. ``save_review(path, load_review(path))`` reproduces the file byte for byte
when it is in the canonical form (2-space indent, ``ensure_ascii=False``, trailing newline), keeping its LF or
CRLF line endings.

One editor (or a tight pair) per schema root field:

=========================================== =================================================================
``schema_ref``, ``version``                 ``set_schema``
``pr``, ``pr_title``, ``branch``,           ``set_pr_meta``
``base_branch``
``base_sha``, ``head_sha``                  ``set_shas``
``review_date``                             ``set_review_date``
``verdict``                                 ``set_verdict``, ``recompute_verdict``
``stats``                                   ``set_stats``
``reviewers``                               ``add_reviewer``, ``remove_reviewer``
``scoped_review_files``                     ``set_scoped_files`` (undeclared, optional; written by ``build``)
``bubbles``                                 ``add_bubble``, ``clear_bubble``
``issues``                                  ``add_issue``, ``regrade_issue``, ``merge_issue_ids``,
                                            ``set_issue_field``
``strengths``                               ``add_strength``, ``set_strengths``
``bubble_up``                               ``add_bubble_up``, ``drop_bubble_up``, ``mirror_bubble_ups``
``post_review_resolutions``                 ``resolve``, ``resolve_all`` (``snapshot_evidence`` builds the
                                            evidence text)
``verification_log``                        ``set_verification_phase``
=========================================== =================================================================

``post_review_resolutions`` is append-only history: ``resolve`` appends an entry, never replacing, reordering
or dropping an existing one; the latest entry per id is the one ``review_merge.compute_verdict`` reads.
``resolve_all`` is the idempotent batch: it skips an entry whose id already has a latest resolution of the
same status, so re-running one proposal adds no duplicate history.

Issue ids and dispositions move together: ``regrade_issue`` renames the id in ``bubbles``, ``bubble_up`` and
``post_review_resolutions`` too, ``merge_issue_ids`` refuses to drop an id that carries a disposition (or
to fold into a ``keep`` id already closed or bubbled), and ``add_issue`` numbers past every id an issue or a
disposition still names, so a new issue never inherits an existing disposition. An id freed by a regrade or a
merge names nothing afterwards and can be issued again.
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Union

from harness_lib import review_merge as rmg

Doc = Dict[str, object]

KNOWN_VERSIONS = (rmg.SCHEMA_VERSION,)
RESOLUTION_STATUSES = ("RESOLVED", "DOWNGRADED_TO_MINOR", "DOWNGRADED_TO_IMPORTANT", "CLOSED_NO_ACTION")
BUBBLE_CLASSIFICATIONS = ("architectural_ambiguity", "out_of_scope", "needs_follow_up", "fixer_failed")
VERIFICATION_PHASES = ("skipped", "dispatch_time", "pre_fix_time")
_SHA = re.compile(r"^(?:[0-9a-f]{7,40}|[0-9a-f]{64})$")
# Evidence SHAs stay within the schema hook's ``^[0-9a-f]{7,40}( |$)`` rule, so the Phase 5 sentinel clears.
_EVIDENCE_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_EVIDENCE_LEAD = re.compile(r"^[0-9a-f]{7,40}( |$)")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VERDICT = re.compile(r"^(READY TO MERGE|NOT READY TO MERGE)")
_ISSUE_ID = re.compile(r"^[CIM][0-9]+$")


# --- I/O ----------------------------------------------------------------------------------------------------


def load_review(path: Union[str, Path]) -> Doc:
    """The review JSON object at ``path``; ``ValueError`` when it is not an object."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: review JSON must be an object")
    return data


def dumps_review(doc: Mapping[str, object], newline: str = "\n") -> str:
    """Canonical text of ``doc``: 2-space indent, ``ensure_ascii=False``, trailing newline, ``newline``
    line endings."""
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    return text.replace("\n", newline) if newline != "\n" else text


def _newline_of(path: Path) -> str:
    """``\\r\\n`` when the existing file at ``path`` uses CRLF, else ``\\n``."""
    try:
        return "\r\n" if b"\r\n" in path.read_bytes() else "\n"
    except FileNotFoundError:
        return "\n"


def save_review(path: Union[str, Path], doc: Mapping[str, object], repo: Optional[Path] = None) -> None:
    """Validate ``doc`` and write it to ``path`` atomically, keeping the file's line-ending style.

    ``repo`` names the project whose schema governs (default: the active project). An invalid document raises
    ``ValueError`` with one problem per line and leaves the file untouched. A failed write or replace (for
    example a Windows file lock) removes the ``.tmp`` file and re-raises the ``OSError``.
    """
    problems = rmg.validate_review(doc, repo)
    if problems:
        raise ValueError("\n".join(problems))
    target = Path(path)
    data = dumps_review(doc, _newline_of(target)).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


# --- helpers ------------------------------------------------------------------------------------------------


def _with(doc: Mapping[str, object], **fields: object) -> Doc:
    """Deep copy of ``doc`` with ``fields`` set."""
    out = copy.deepcopy(dict(doc))
    out.update(copy.deepcopy(fields))
    return out


def _flat_issues(doc: Mapping[str, object]) -> List[Dict[str, object]]:
    """Every issue of ``doc``, critical first."""
    issues: Mapping[str, Sequence[Dict[str, object]]] = doc.get("issues") or {}  # type: ignore[assignment]
    return [i for tier in rmg.TIERS for i in issues.get(tier, ())]


def _issue_ids(doc: Mapping[str, object]) -> List[str]:
    return [str(i["id"]) for i in _flat_issues(doc)]


def _require_issue(doc: Mapping[str, object], issue_id: str) -> None:
    if issue_id not in _issue_ids(doc):
        raise ValueError(f"no issue {issue_id}")


def _today() -> str:
    return datetime.date.today().isoformat()


def _check_date(date: str) -> str:
    """``date`` when it is a real ``YYYY-MM-DD`` date; ``ValueError`` otherwise."""
    if not _DATE.match(date):
        raise ValueError(f"date must be YYYY-MM-DD: {date!r}")
    datetime.date.fromisoformat(date)
    return date


# --- scalar root fields -------------------------------------------------------------------------------------


def set_schema(doc: Mapping[str, object], ref: str, version: str) -> Doc:
    """``schema_ref`` and ``version``; ``version`` must be a known payload version."""
    if version not in KNOWN_VERSIONS:
        raise ValueError(f"unknown schema version {version!r} (known: {', '.join(KNOWN_VERSIONS)})")
    if not ref.strip():
        raise ValueError("schema_ref must not be blank")
    return _with(doc, schema_ref=ref, version=version)


def set_pr_meta(doc: Mapping[str, object], *, pr: Optional[Union[int, str]] = None,
                pr_title: Optional[str] = None, branch: Optional[str] = None,
                base_branch: Optional[str] = None) -> Doc:
    """Any of ``pr``, ``pr_title``, ``branch``, ``base_branch``; ``None`` keeps the current value."""
    given = {"pr": pr, "pr_title": pr_title, "branch": branch, "base_branch": base_branch}
    return _with(doc, **{k: v for k, v in given.items() if v is not None})


def set_shas(doc: Mapping[str, object], base_sha: Optional[str] = None,
             head_sha: Optional[str] = None) -> Doc:
    """``base_sha`` / ``head_sha`` (lowercase hex, 7-40 or 64 characters); ``None`` keeps the value."""
    given = {"base_sha": base_sha, "head_sha": head_sha}
    for name, sha in given.items():
        if sha is not None and not _SHA.match(sha):
            raise ValueError(f"{name} must be 7-40 (or 64) lowercase hex characters: {sha!r}")
    return _with(doc, **{k: v for k, v in given.items() if v is not None})


def set_review_date(doc: Mapping[str, object], date: str) -> Doc:
    """``review_date`` as ``YYYY-MM-DD``."""
    return _with(doc, review_date=_check_date(date))


def set_stats(doc: Mapping[str, object], additions: int, deletions: int, files_changed: int) -> Doc:
    """``stats`` from three non-negative integer counts (``bool`` refused)."""
    counts = {"additions": additions, "deletions": deletions, "files_changed": files_changed}
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts.values()):
        raise ValueError(f"stats must be non-negative integers: {counts}")
    return _with(doc, stats=counts)


# --- verdict ------------------------------------------------------------------------------------------------


PHASE4_HOLD = "NOT READY TO MERGE - Phase 4 first run failed: {reason}"


def _pre_fix_pending(doc: Mapping[str, object]) -> bool:
    """True when ``verification_log.pre_fix_time`` is still the Phase 4 placeholder."""
    log = doc.get("verification_log")
    return isinstance(log, Mapping) and log.get("pre_fix_time") == rmg.PENDING


def recompute_verdict(doc: Mapping[str, object]) -> Doc:
    """``verdict`` per ``review_merge.compute_verdict`` over the document's dispositions; while
    ``pre_fix_time`` is pending, a READY result is held as ``PHASE4_HOLD`` (reason: pre_fix_time pending)."""
    verdict = rmg.compute_verdict(doc["issues"], doc.get("post_review_resolutions") or [],  # type: ignore
                                  doc.get("bubbles") or [], doc.get("bubble_up") or [])  # type: ignore
    if verdict.startswith("READY TO MERGE") and _pre_fix_pending(doc):
        verdict = PHASE4_HOLD.format(reason="pre_fix_time pending")
    return _with(doc, verdict=verdict)


def set_verdict(doc: Mapping[str, object], text: str) -> Doc:
    """``verdict`` set to ``text``; a READY verdict is refused while any issue is undispositioned or while
    ``recompute_verdict`` is not READY (a bubbled but unclosed critical / important issue blocks it)."""
    if not _VERDICT.match(text):
        raise ValueError("verdict must start with READY TO MERGE or NOT READY TO MERGE")
    if text.startswith("READY"):
        pending = rmg.undispositioned_ids(doc)
        if pending:
            raise ValueError(f"READY verdict refused; undispositioned: {', '.join(pending)}")
        computed = str(recompute_verdict(doc)["verdict"])
        if not computed.startswith("READY TO MERGE"):
            raise ValueError(f"READY verdict refused; computed verdict: {computed}")
    return _with(doc, verdict=text)


# --- list root fields ---------------------------------------------------------------------------------------


def add_reviewer(doc: Mapping[str, object], name: str) -> Doc:
    """``name`` appended to ``reviewers`` unless present."""
    reviewers = list(doc.get("reviewers") or [])  # type: ignore[call-overload]
    return _with(doc, reviewers=reviewers if name in reviewers else [*reviewers, name])


def remove_reviewer(doc: Mapping[str, object], name: str) -> Doc:
    """``name`` removed from ``reviewers``; ``ValueError`` when absent."""
    reviewers = list(doc.get("reviewers") or [])  # type: ignore[call-overload]
    if name not in reviewers:
        raise ValueError(f"no reviewer {name!r}")
    return _with(doc, reviewers=[r for r in reviewers if r != name])


def set_scoped_files(doc: Mapping[str, object], paths: Sequence[str]) -> Doc:
    """``scoped_review_files`` (optional, undeclared in the schema) as de-duplicated POSIX paths."""
    posix = [str(p).replace("\\", "/") for p in paths]
    return _with(doc, scoped_review_files=list(dict.fromkeys(posix)))


def add_bubble(doc: Mapping[str, object], issue_id: str) -> Doc:
    """``issue_id`` appended to ``bubbles`` unless present; the id must name an issue."""
    _require_issue(doc, issue_id)
    bubbles = list(doc.get("bubbles") or [])  # type: ignore[call-overload]
    return _with(doc, bubbles=bubbles if issue_id in bubbles else [*bubbles, issue_id])


def clear_bubble(doc: Mapping[str, object], issue_id: str) -> Doc:
    """``issue_id`` removed from ``bubbles``; ``ValueError`` when absent."""
    bubbles = list(doc.get("bubbles") or [])  # type: ignore[call-overload]
    if issue_id not in bubbles:
        raise ValueError(f"{issue_id} is not bubbled")
    return _with(doc, bubbles=[b for b in bubbles if b != issue_id])


def add_strength(doc: Mapping[str, object], text: str) -> Doc:
    """``text`` appended to ``strengths`` unless present."""
    if not text.strip():
        raise ValueError("strength must not be blank")
    strengths = list(doc.get("strengths") or [])  # type: ignore[call-overload]
    return _with(doc, strengths=strengths if text in strengths else [*strengths, text])


def set_strengths(doc: Mapping[str, object], items: Sequence[str]) -> Doc:
    """``strengths`` replaced by the non-blank ``items`` (duplicates dropped, order kept)."""
    return _with(doc, strengths=list(dict.fromkeys(i for i in items if i.strip())))


# --- issues -------------------------------------------------------------------------------------------------


def _with_issues(doc: Mapping[str, object], flat: Sequence[Dict[str, object]]) -> Doc:
    return _with(doc, issues=rmg.issues_by_severity(flat))


def _disposed_ids(doc: Mapping[str, object]) -> List[str]:
    """Ids named by any ``post_review_resolutions``, ``bubbles`` or ``bubble_up`` entry."""
    return sorted(rmg._named_ids(doc.get("post_review_resolutions") or [],  # type: ignore[arg-type]
                                 doc.get("bubbles") or [], doc.get("bubble_up") or []))  # type: ignore[arg-type]


def add_issue(doc: Mapping[str, object], severity: str, issue: Mapping[str, object]) -> Doc:
    """``issue`` (no ``id``) appended to the ``severity`` tier under the next id of that tier free of both
    issues and dispositions."""
    if "id" in issue:
        raise ValueError("add_issue assigns the id; drop it from the issue")
    tier = rmg._tier_name(severity)
    letter = tier[0].upper()
    taken = [*_issue_ids(doc), *_disposed_ids(doc)]
    numbers = [int(i[1:]) for i in taken if _ISSUE_ID.match(i) and i[0] == letter]
    new = {"id": f"{letter}{max(numbers, default=0) + 1}", **copy.deepcopy(dict(issue))}
    return _with_issues(doc, [*_flat_issues(doc), new])


def _renamed_dispositions(doc: Mapping[str, object], old: str, new: str) -> Dict[str, object]:
    """The disposition fields present in ``doc`` with ``old`` renamed to ``new``, entry order kept."""
    out: Dict[str, object] = {}
    if "bubbles" in doc:
        out["bubbles"] = [new if str(b) == old else b for b in doc["bubbles"] or []]  # type: ignore[union-attr]
    for name in ("bubble_up", "post_review_resolutions"):
        if name in doc:
            out[name] = [{**e, "id": new} if str(e["id"]) == old else e
                         for e in doc[name] or []]  # type: ignore[union-attr]
    return out


def regrade_issue(doc: Mapping[str, object], issue_id: str, severity: str) -> Doc:
    """``issue_id`` moved to ``severity`` under a new id (``review_merge.regrade``); its ``bubbles``,
    ``bubble_up`` and ``post_review_resolutions`` entries follow it to the new id."""
    before = set(_issue_ids(doc))
    out = _with_issues(doc, rmg.regrade(_flat_issues(doc), issue_id, severity))
    new_id = next(i for i in _issue_ids(out) if i not in before)
    return _with(out, **_renamed_dispositions(out, issue_id, new_id))


def merge_issue_ids(doc: Mapping[str, object], keep: str, drop: Sequence[str]) -> Doc:
    """``drop`` ids folded into ``keep`` (``review_merge.merge_ids``); refused while a ``drop`` id carries a
    resolution or bubble, so no disposition is orphaned or transferred to ``keep``, and refused while ``keep``
    is settled (closed or bubbled), so an open dropped finding never inherits a closed state unverified."""
    held = [d for d in drop if d in _disposed_ids(doc)]
    if held:
        raise ValueError(f"merge refused; {', '.join(held)} carries a resolution or bubble "
                         "(merge before dispositioning)")
    settled = rmg._settled_ids(doc.get("post_review_resolutions") or [],  # type: ignore[arg-type]
                               doc.get("bubbles") or [], doc.get("bubble_up") or [])  # type: ignore[arg-type]
    if keep in settled:
        raise ValueError(f"merge refused; {keep} is already closed or bubbled (merge before dispositioning)")
    return _with_issues(doc, rmg.merge_ids(_flat_issues(doc), keep, drop))


def set_issue_field(doc: Mapping[str, object], issue_id: str, name: str, value: object) -> Doc:
    """Field ``name`` of issue ``issue_id`` set to ``value``; ``id`` changes go through ``regrade_issue``."""
    if name == "id":
        raise ValueError("an issue id changes through regrade_issue or merge_issue_ids")
    out = _with(doc)
    for issue in _flat_issues(out):
        if issue["id"] == issue_id:
            issue[name] = copy.deepcopy(value)
            return out
    raise ValueError(f"no issue {issue_id}")


# --- bubble_up ----------------------------------------------------------------------------------------------


def add_bubble_up(doc: Mapping[str, object], issue_id: str, classification: str, reason: str) -> Doc:
    """A ``bubble_up`` entry for ``issue_id``; one per id, ``reason`` one line of at most 200 characters."""
    _require_issue(doc, issue_id)
    if classification not in BUBBLE_CLASSIFICATIONS:
        raise ValueError(f"classification must be one of {', '.join(BUBBLE_CLASSIFICATIONS)}")
    line = " ".join(reason.split())
    if not line or len(line) > 200:
        raise ValueError("bubble_up reason must be 1-200 characters")
    ledger = list(doc.get("bubble_up") or [])  # type: ignore[call-overload]
    if issue_id in {str(b["id"]) for b in ledger}:
        raise ValueError(f"{issue_id} already has a bubble_up entry; drop it first")
    entry = {"id": issue_id, "classification": classification, "reason": line}
    return _with(doc, bubble_up=[*ledger, entry])


def drop_bubble_up(doc: Mapping[str, object], issue_id: str) -> Doc:
    """The ``bubble_up`` entry of ``issue_id`` removed; ``ValueError`` when absent."""
    ledger = list(doc.get("bubble_up") or [])  # type: ignore[call-overload]
    kept = [b for b in ledger if str(b["id"]) != issue_id]
    if len(kept) == len(ledger):
        raise ValueError(f"{issue_id} has no bubble_up entry")
    return _with(doc, bubble_up=kept)


# --- post_review_resolutions --------------------------------------------------------------------------------


def snapshot_evidence(sha: str, text: str) -> str:
    """Evidence in the ``<sha> (working-tree snapshot; developer commits) - <text>`` convention; ``sha`` is
    7-40 lowercase hex (the schema hook's evidence rule) and ``text`` must not be blank."""
    if not _EVIDENCE_SHA.match(sha):
        raise ValueError(f"evidence sha must be 7-40 lowercase hex characters: {sha!r}")
    if not text.strip():
        raise ValueError("evidence text must not be blank (a rationale or a description of the change)")
    return f"{sha} {rmg.EVIDENCE_NOTE} - {text.strip()}"


def resolve(doc: Mapping[str, object], issue_id: str, status: str, evidence: str,
            date: Optional[str] = None) -> Doc:
    """A ``post_review_resolutions`` entry for ``issue_id`` (date default: today), always appended.

    Earlier entries for the id stay as history; the latest one decides the verdict. Every status needs
    non-blank evidence; for ``CLOSED_NO_ACTION`` it is the rationale.
    """
    _require_issue(doc, issue_id)
    if status not in RESOLUTION_STATUSES:
        raise ValueError(f"status must be one of {', '.join(RESOLUTION_STATUSES)}")
    if not evidence.strip():
        kind = "a rationale" if status == "CLOSED_NO_ACTION" else "evidence"
        raise ValueError(f"{issue_id}: {status} requires {kind}")
    entry = {"id": issue_id, "status": status, "date": _check_date(date or _today()), "evidence": evidence}
    entries = list(doc.get("post_review_resolutions") or [])  # type: ignore[call-overload]
    return _with(doc, post_review_resolutions=[*entries, entry])


def _proposed_evidence(entry: Mapping[str, object], sha: Optional[str]) -> str:
    """Evidence of a proposed entry, which must be a string (never coerced); with ``sha``, text not already
    led by a SHA takes the snapshot form."""
    text = entry.get("evidence", "")
    if not isinstance(text, str):
        raise ValueError(f"evidence must be a string, not {type(text).__name__}")
    return snapshot_evidence(sha, text) if sha and not _EVIDENCE_LEAD.match(text) else text


def _latest_status(doc: Mapping[str, object], issue_id: str) -> Optional[str]:
    """Status of the latest ``post_review_resolutions`` entry for ``issue_id``; ``None`` when it has none."""
    statuses = [str(e.get("status")) for e in doc.get("post_review_resolutions") or []  # type: ignore[union-attr]
                if str(e.get("id")) == issue_id]
    return statuses[-1] if statuses else None


def _put_bubble_up(doc: Mapping[str, object], issue_id: str, classification: str, reason: str) -> Doc:
    """``add_bubble_up`` that replaces an existing entry of ``issue_id`` in place instead of refusing it."""
    ledger = list(doc.get("bubble_up") or [])  # type: ignore[call-overload]
    rest = [b for b in ledger if str(b["id"]) != issue_id]
    added = add_bubble_up(_with(doc, bubble_up=rest), issue_id, classification, reason)
    if len(rest) == len(ledger):
        return added
    entry = added["bubble_up"][-1]  # type: ignore[index]
    return _with(doc, bubble_up=[entry if str(b["id"]) == issue_id else b for b in ledger])


def mirror_bubble_ups(doc: Mapping[str, object], items: Sequence[Mapping[str, object]]) -> Doc:
    """Every ``{id, classification, reason}`` item of a pr-team ``bubble_ups.json`` sidecar written to the
    ``bubble_up`` ledger; an id already in the ledger has its entry replaced in place (the later
    classification wins), so mirroring the same sidecar again changes nothing."""
    out = _with(doc)
    for n, item in enumerate(items, 1):
        fields = ("id", "classification", "reason")
        if not isinstance(item, Mapping) or not all(isinstance(item.get(k), str) for k in fields):
            raise ValueError(f"bubble-up item {n}: needs string id, classification and reason")
        try:
            out = _put_bubble_up(out, str(item["id"]), str(item["classification"]), str(item["reason"]))
        except ValueError as exc:
            raise ValueError(f"bubble-up item {n} ({item['id']}): {exc}") from exc
    return out


def resolve_all(doc: Mapping[str, object], entries: Sequence[Mapping[str, object]],
                sha: Optional[str] = None, bubble_ups: Sequence[Mapping[str, object]] = ()) -> Doc:
    """``bubble_ups`` sidecar items mirrored into ``bubble_up`` (``mirror_bubble_ups``), every proposed
    ``{id, status, evidence[, date]}`` entry applied through ``resolve`` in order, then the verdict
    recomputed; any bad entry raises ``ValueError`` naming its position, so nothing partial results. Ids
    closed by their latest resolution leave the transient ``bubbles`` list; ``bubble_up`` keeps them.

    An entry whose id already has a latest resolution of the same status is skipped, so re-running the same
    proposal (a QA_FAIL retry, a FORK resume) appends nothing. With ``sha``, evidence not already starting
    with a SHA takes the ``snapshot_evidence`` form; evidence that is not a string is refused.
    """
    out = mirror_bubble_ups(doc, bubble_ups)
    for n, entry in enumerate(entries, 1):
        if not isinstance(entry, Mapping) or not {"id", "status"} <= set(entry):
            raise ValueError(f"entry {n}: needs id, status and evidence")
        try:
            issue_id, status = str(entry["id"]), str(entry["status"])
            evidence = _proposed_evidence(entry, sha)
            if _latest_status(out, issue_id) == status:
                continue
            date = str(entry["date"]) if entry.get("date") else None
            out = resolve(out, issue_id, status, evidence, date)
        except ValueError as exc:
            raise ValueError(f"entry {n} ({entry['id']}): {exc}") from exc
    return recompute_verdict(_without_closed_bubbles(out))


def _without_closed_bubbles(doc: Mapping[str, object]) -> Doc:
    """``doc`` with ids whose latest resolution is ``RESOLVED`` / ``CLOSED_NO_ACTION`` dropped from the
    transient ``bubbles`` list (as ``review_merge.apply_closeout`` does); ``bubble_up`` is kept."""
    if "bubbles" not in doc:
        return _with(doc)
    closed = rmg._closed_ids(doc.get("post_review_resolutions") or [])  # type: ignore[arg-type]
    return _with(doc, bubbles=[b for b in doc["bubbles"] or [] if str(b) not in closed])  # type: ignore


# --- verification_log ---------------------------------------------------------------------------------------


def set_verification_phase(doc: Mapping[str, object], phase: str, payload: object) -> Doc:
    """``verification_log`` edit: ``skipped`` (payload: reason text) replaces the log with the skipped
    shape; ``dispatch_time`` / ``pre_fix_time`` set that block of the nested shape (a skipped log restarts
    as an empty nested one). ``save_review`` validates the result against the schema's three shapes."""
    if phase not in VERIFICATION_PHASES:
        raise ValueError(f"phase must be one of {', '.join(VERIFICATION_PHASES)}")
    if phase == "skipped":
        if not isinstance(payload, str) or not payload.strip():
            raise ValueError("a skipped verification_log needs a reason")
        return _with(doc, verification_log={"skipped": True, "reason": payload})
    log = doc.get("verification_log")
    nested = dict(log) if isinstance(log, dict) and not log.get("skipped") else {}
    nested[phase] = payload
    return _with(doc, verification_log=nested)
