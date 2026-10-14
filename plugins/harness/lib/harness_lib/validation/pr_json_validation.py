"""Issue-count tabulation and disposition-id validation for PR_REVIEW JSON schema."""
from typing import Any, Dict, Iterable, Set

from harness_lib.validation.id_handling import disposition_ids as _disposition_ids
from harness_lib.validation.id_handling import issue_ids as _issue_ids


class IssueTabulationError(Exception):
    """Raised when a PR_REVIEW JSON's issue ids are not coherently accounted for.

    Carries the offending id sets so the caller can render a single-line,
    paste-friendly message. Calls super().__init__ so str(exc) and exc.args
    both carry the text (not only the .message attribute).
    """

    def __init__(self, *, unaccounted: Iterable[str] = (), orphans: Iterable[str] = ()) -> None:
        self.unaccounted: Set[str] = set(unaccounted)
        self.orphans: Set[str] = set(orphans)
        parts = []
        if self.unaccounted:
            parts.append(
                "unaccounted issue ids (no resolution / bubble / bubble_up): "
                f"{sorted(self.unaccounted)}"
            )
        if self.orphans:
            parts.append(f"orphan disposition ids (match no issue): {sorted(self.orphans)}")
        self.message = "; ".join(parts) or "issue tabulation incoherent"
        super().__init__(self.message)


def validate_issue_counts(report: Dict[str, Any]) -> None:
    """Coherence check by id-set membership across all disposition channels.

    An issue is accounted for iff its id appears in the union of
    post_review_resolutions, `bubbles`, and the `bubble_up` ledger. Firing is
    verdict-gated so the check fires on real incoherence without blocking the
    legitimate open-review state:
      * an ORPHAN disposition id (matching no issue) is always a defect,
        regardless of verdict (catches typos / stale references);
      * a "READY TO MERGE" verdict additionally requires every issue id to be
        accounted for — a READY closeout that leaves any issue undispositioned
        is incoherent, even when nothing was dispositioned at all;
      * a "NOT READY TO MERGE" review with no orphans is still open: partial or
        zero disposition is valid;
      * a clean review (no issues) is never tabulated.
    ActionPlan and any other label are exempt at the call site (PR_REVIEW-only).
    """
    issue_ids = _issue_ids(report)
    if not issue_ids:
        return
    dispositioned = _disposition_ids(report)
    verdict = report.get("verdict") or ""
    orphans = dispositioned - issue_ids
    unaccounted: Set[str] = issue_ids - dispositioned if verdict.startswith("READY TO MERGE") else set()
    if unaccounted or orphans:
        raise IssueTabulationError(unaccounted=unaccounted, orphans=orphans)
