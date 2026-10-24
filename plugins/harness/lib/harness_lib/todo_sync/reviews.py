"""PR review text for the issues ``todo_sync.py untracked`` lists.

An issue that points at a review ("resolve the points in <review url>") is only useful with the review's own
words, so the review body and its inline comments are fetched through ``gh api``. Only links into the
issue's own repository are followed; a dismissed review and a review with nothing to say are left out.
Reviews after an issue's first stop at a character budget; the first is always kept whole, so a single
oversized review can pass the budget.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from harness_lib.todo_sync import TodoSyncError, gh

REVIEW_CHARS = 20000
_PR_LINK = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)(?:#pullrequestreview-(\d+))?")
_ISSUE_URL = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+)/issues/\d+")


@dataclass(frozen=True)
class ReviewLink:
    """A pull request, and one of its reviews when the link names it."""

    pr: int
    review_id: Optional[int]


def slug_of(issue_url: str) -> str:
    """``owner/repo`` of a GitHub issue URL, else empty."""
    match = _ISSUE_URL.match(issue_url)
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def review_links(texts: Iterable[str], slug: str) -> List[ReviewLink]:
    """Links to pull requests (or their reviews) of ``slug`` in ``texts``, first occurrence first."""
    found: List[ReviewLink] = []
    for text in texts:
        for owner, repo, pr, review_id in _PR_LINK.findall(text or ""):
            link = ReviewLink(int(pr), int(review_id) if review_id else None)
            if f"{owner}/{repo}".lower() == slug.lower() and link not in found:
                found.append(link)
    return found


def _login(obj: Dict[str, Any]) -> str:
    user = obj.get("user")
    return str(user.get("login") or "") if isinstance(user, dict) else ""


def _inline(cwd: Path, base: str, review_id: int) -> List[Dict[str, Any]]:
    out = []
    for raw in gh.api_list(cwd, f"{base}/reviews/{review_id}/comments"):
        body = str(raw.get("body") or "").strip()
        if body and raw.get("path"):
            line = raw.get("line") or raw.get("original_line")
            out.append({"path": str(raw["path"]), "line": line or None, "author": _login(raw), "body": body})
    return out


def _review(cwd: Path, slug: str, link: ReviewLink, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One review as a dict, or None when it is dismissed or has no body and no inline comment."""
    review_id = int(raw.get("id") or link.review_id or 0)
    if str(raw.get("state")) == "DISMISSED":
        return None
    body = str(raw.get("body") or "").strip()
    comments = _inline(cwd, f"repos/{slug}/pulls/{link.pr}", review_id)
    if not body and not comments:
        return None
    return {"source": f"https://github.com/{slug}/pull/{link.pr}#pullrequestreview-{review_id}",
            "state": str(raw.get("state") or ""), "author": _login(raw), "body": body, "comments": comments}


def _raw_reviews(cwd: Path, slug: str, link: ReviewLink) -> List[Dict[str, Any]]:
    base = f"repos/{slug}/pulls/{link.pr}/reviews"
    if link.review_id is not None:
        return [gh.api_object(cwd, f"{base}/{link.review_id}")]
    return gh.api_list(cwd, base)


def _size(review: Dict[str, Any]) -> int:
    return len(review["body"]) + sum(len(c["body"]) for c in review["comments"])


def _link_url(slug: str, link: ReviewLink) -> str:
    base = f"https://github.com/{slug}/pull/{link.pr}"
    return f"{base}#pullrequestreview-{link.review_id}" if link.review_id is not None else base


def _link_reviews(cwd: Path, slug: str, link: ReviewLink) -> List[Dict[str, Any]]:
    found = (_review(cwd, slug, link, raw) for raw in _raw_reviews(cwd, slug, link))
    return [review for review in found if review is not None]


def fetch_reviews(cwd: Path, slug: str, links: Sequence[ReviewLink],
                  budget: int = REVIEW_CHARS) -> Tuple[List[Dict[str, Any]], bool, List[str]]:
    """The reviews ``links`` name, a flag set when ``budget`` characters cut later ones off, and one
    ``<link>: <reason>`` line per link that could not be read (a deleted review, an issue number).

    The first review is always kept whole; a later one that would pass the budget ends the list.
    """
    kept: List[Dict[str, Any]] = []
    errors: List[str] = []
    used = 0
    for link in links:
        try:
            found = _link_reviews(cwd, slug, link)
        except (TodoSyncError, ValueError) as exc:
            errors.append(f"{_link_url(slug, link)}: {exc}")
            continue
        for review in found:
            if any(k["source"] == review["source"] for k in kept):
                continue
            if kept and used + _size(review) > budget:
                return kept, True, errors
            kept.append(review)
            used += _size(review)
    return kept, False, errors
