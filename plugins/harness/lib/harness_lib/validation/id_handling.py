"""Shared id-set predicates for PR_REVIEW disposition accounting.

Single source of truth for which issue ids exist (``issue_ids``) and which are
dispositioned (``disposition_ids``) across ``post_review_resolutions``, the
transient ``bubbles`` array, and the ``bubble_up`` ledger. Imported by both the
issue-count validator (``pr_json_validation.validate_issue_counts``) and the
Layer 3 sentinel-cleanup gate (``hooks/validate_pr_json_schema.py``) so the two never
drift.
"""
from typing import Any, Dict, Set


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


def disposition_ids(report: Dict[str, Any]) -> Set[str]:
    """Collect dispositioned ids from all three channels: post_review_resolutions,
    the transient ``bubbles`` array, and the ``bubble_up`` terminal ledger."""
    ids: Set[str] = set()
    for resolution in report.get("post_review_resolutions") or []:
        if isinstance(resolution, dict) and isinstance(resolution.get("id"), str):
            ids.add(resolution["id"])
    for bubble in report.get("bubbles") or []:
        if isinstance(bubble, str):
            ids.add(bubble)
    for bubbled in report.get("bubble_up") or []:
        if isinstance(bubbled, dict) and isinstance(bubbled.get("id"), str):
            ids.add(bubbled["id"])
    return ids


def all_issues_dispositioned(report: Dict[str, Any]) -> bool:
    """True iff there is at least one issue and every issue id is dispositioned.

    The empty-issues case returns False: a review with no issues is not a
    completed Phase 5 closeout to clear a sentinel on.
    """
    ids = issue_ids(report)
    return bool(ids) and ids <= disposition_ids(report)
