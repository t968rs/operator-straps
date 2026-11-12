"""Shared id-set predicates for PR_REVIEW disposition accounting.

Single source of truth for which issue ids exist (``issue_ids``) and which ids any
channel names (``disposition_ids``: ``post_review_resolutions`` of any status, the
transient ``bubbles`` array, and the ``bubble_up`` ledger). The issue-count validator
(``pr_json_validation.validate_issue_counts``) reads ``disposition_ids`` for its
orphan and unaccounted checks.

The Layer 3 sentinel-cleanup gate (``hooks/validate_pr_json_schema.py``) reads
``all_issues_dispositioned`` instead, which follows the latest status per id and so
differs from ``disposition_ids``: an id whose latest resolution is ``BUBBLED`` counts
only through ``bubbles`` / ``bubble_up``, and one whose latest resolution is
``NOT_RESOLVED`` never counts. It follows ``review_merge._settled_ids`` except that a
latest ``DOWNGRADED_TO_*`` resolution counts here and does not settle an id there.

The adversarial statuses (``REFUTED``, ``BUBBLED``, ``NOT_RESOLVED``) live here too: ``latest_statuses``
maps each id to its latest status, ``reopened_ids`` names the ids whose latest resolution is
``NOT_RESOLVED`` (open whatever else names them), and ``counted_resolutions`` drops the adversarial
entries from the Layer 2 and Layer 3 rules of the hook and ``review_merge``.
"""
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Set

ADVERSARIAL_STATUSES = ("REFUTED", "BUBBLED", "NOT_RESOLVED")
REOPENED_STATUS = "NOT_RESOLVED"


def issue_ids(report: Dict[str, Any]) -> Set[str]:
    """Collect every issue id across the critical / important / minor lists."""
    issues = report.get("issues") or {}
    ids: Set[str] = set()
    for bucket in issues.values():
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                ids.add(item["id"])
    return ids


def _bubble_channel_ids(report: Dict[str, Any]) -> Set[str]:
    """Ids in the transient ``bubbles`` array or the ``bubble_up`` ledger."""
    ids: Set[str] = set()
    for bubble in report.get("bubbles") or []:
        if isinstance(bubble, str):
            ids.add(bubble)
    for bubbled in report.get("bubble_up") or []:
        if isinstance(bubbled, dict) and isinstance(bubbled.get("id"), str):
            ids.add(bubbled["id"])
    return ids


def disposition_ids(report: Dict[str, Any]) -> Set[str]:
    """Collect dispositioned ids from all three channels: post_review_resolutions,
    the transient ``bubbles`` array, and the ``bubble_up`` terminal ledger."""
    ids: Set[str] = set()
    for resolution in report.get("post_review_resolutions") or []:
        if isinstance(resolution, dict) and isinstance(resolution.get("id"), str):
            ids.add(resolution["id"])
    return ids | _bubble_channel_ids(report)


def latest_statuses(resolutions: Iterable[Any]) -> Dict[str, object]:
    """Status of the last entry per id, in list order; entries without a string ``id`` are skipped."""
    latest: Dict[str, object] = {}
    for resolution in resolutions or []:
        if isinstance(resolution, Mapping) and isinstance(resolution.get("id"), str):
            latest[resolution["id"]] = resolution.get("status")
    return latest


def reopened_ids(resolutions: Iterable[Any]) -> Set[str]:
    """Ids whose latest resolution status is ``NOT_RESOLVED`` (a refutation overruled to Phase 5 waves)."""
    return {i for i, status in latest_statuses(resolutions).items() if status == REOPENED_STATUS}


def counted_resolutions(resolutions: Iterable[Any]) -> List[Any]:
    """Resolutions other than ``REFUTED`` / ``BUBBLED`` / ``NOT_RESOLVED`` entries, in order."""
    return [r for r in resolutions or []
            if not (isinstance(r, Mapping) and r.get("status") in ADVERSARIAL_STATUSES)]


def all_issues_dispositioned(report: Dict[str, Any]) -> bool:
    """True iff there is at least one issue and every issue id is dispositioned.

    The empty-issues case returns False: a review with no issues is not a
    completed Phase 5 closeout to clear a sentinel on. The resolution channel
    counts an id only when its latest status is neither ``BUBBLED`` nor
    ``NOT_RESOLVED``; ``bubbles`` and ``bubble_up`` are added after it; an id
    whose latest resolution is ``NOT_RESOLVED`` stays open even when a bubble
    channel names it.
    """
    ids = issue_ids(report)
    resolutions = report.get("post_review_resolutions") or []
    resolved = {i for i, status in latest_statuses(resolutions).items()
                if status not in ("BUBBLED", REOPENED_STATUS)}
    settled = (resolved | _bubble_channel_ids(report)) - reopened_ids(resolutions)
    return bool(ids) and ids <= settled
