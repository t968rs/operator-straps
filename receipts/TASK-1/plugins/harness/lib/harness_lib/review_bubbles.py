"""Pending fixer bubbles of a pr-review run: shared by ``pr_review.py`` and ``bubble_memo.py``."""
from __future__ import annotations

from pathlib import Path
from typing import List, Mapping, Set, Tuple

from harness_lib import review_merge as rmg
from harness_lib import review_models as rm


def closed_ids(doc: Mapping[str, object]) -> Set[str]:
    """Ids whose latest resolution is RESOLVED or CLOSED_NO_ACTION."""
    latest = {str(r["id"]): r.get("status") for r in doc.get("post_review_resolutions") or []}  # type: ignore
    return {i for i, status in latest.items() if status in rmg.CLOSED_STATUSES}


def fixer_bubbles(run: Path) -> List[Tuple[str, rm.FixBubble]]:
    """(fixer, bubble) for every bubble a fixer of this run recorded, by report file name."""
    return [(r.fixer, b) for r in rm.load_fix_reports(run / "fixes") for b in r.bubbled]


def pending_bubbles(doc: Mapping[str, object], run: Path) -> List[Tuple[str, rm.FixBubble]]:
    """Fixer bubbles whose id is not closed and in neither the review's ``bubbles`` nor its ``bubble_up``."""
    known = {str(b) for b in doc.get("bubbles") or []} | closed_ids(doc)  # type: ignore[union-attr]
    known |= {str(b["id"]) for b in doc.get("bubble_up") or []}  # type: ignore[union-attr, index]
    return [(fixer, b) for fixer, b in fixer_bubbles(run) if b.id not in known]
