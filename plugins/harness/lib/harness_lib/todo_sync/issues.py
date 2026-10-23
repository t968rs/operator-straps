"""Open GitHub issues that no TODO catalog record mentions, for ``todo_sync.py untracked``.

An issue is tracked when an item (``gh_issues``, ``related_gh_issues``, a ``gh_issue`` source), a tracker
(its number or a child), a close candidate or a research catalog entry (``issues``) names it. The rows
``find_untracked`` returns carry what an agent needs to draft an item: the issue text, its comments and
the text of the PR reviews it links.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from harness_lib.config import HarnessConfig
from harness_lib.todo_sync import TodoSyncError, gh
from harness_lib.todo_sync.report import write_atomic
from harness_lib.todo_sync.reviews import fetch_reviews, review_links, slug_of
from harness_lib.todo_sync.sources import Sources

LIST_LIMIT = 1000
LIST_FIELDS = "number,title,url,labels,body,comments"


def untracked_path(cfg: HarnessConfig) -> Path:
    """Where ``untracked`` writes its rows: ``<state_dir>/todo-sync/untracked.json``."""
    return cfg.path(cfg.state_dir) / "todo-sync" / "untracked.json"


def as_number(value: Any) -> Optional[int]:
    """The issue number in an int, a digit string or a ``#N`` string, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    match = re.fullmatch(r"#?(\d+)", value.strip()) if isinstance(value, str) else None
    return int(match.group(1)) if match else None


def _numbers(values: Any) -> Set[int]:
    return {n for n in (as_number(v) for v in values or []) if n is not None}


def _item_numbers(item: Dict[str, Any]) -> Set[int]:
    found = _numbers(item.get("gh_issues")) | _numbers(item.get("related_gh_issues"))
    for source in item.get("sources") or []:
        if isinstance(source, dict) and source.get("type") == "gh_issue":
            found |= _numbers([source.get("ref")])
    return found


def catalog_issue_numbers(catalog: Dict[str, Any]) -> Set[int]:
    """Issue numbers the TODO catalog records: items, trackers with their children, close candidates."""
    found: Set[int] = set()
    for item in catalog.get("items") or []:
        found |= _item_numbers(item) if isinstance(item, dict) else set()
    for tracker in catalog.get("trackers") or []:
        if isinstance(tracker, dict):
            found |= _numbers([tracker.get("number")]) | _numbers(tracker.get("children"))
    for candidate in catalog.get("close_candidates") or []:
        found |= _numbers([candidate.get("number")]) if isinstance(candidate, dict) else set()
    return found


def tracked_numbers(src: Sources) -> Set[int]:
    """``catalog_issue_numbers`` plus the issues the research catalog's entries list."""
    if not src.todo.ok:
        raise TodoSyncError(f"{src.todo.rel}: {src.todo.error}")
    found = catalog_issue_numbers(src.todo.data)
    if src.cfg.todo.research.catalog:
        for entry in src.entries():
            found |= _numbers(entry.get("issues"))
    return found


def _flatten(raw: Dict[str, Any]) -> Dict[str, Any]:
    comments = [{"author": (c.get("author") or {}).get("login") or "", "body": c.get("body") or ""}
                for c in raw.get("comments") or [] if isinstance(c, dict)]
    return {"number": raw["number"], "title": raw.get("title") or "", "url": raw.get("url") or "",
            "labels": [str(lab.get("name")) for lab in raw.get("labels") or [] if isinstance(lab, dict)],
            "body": raw.get("body") or "", "comments": comments, "reviews": [], "reviews_truncated": False,
            "review_errors": []}


def open_issues(cfg: HarnessConfig) -> List[Dict[str, Any]]:
    """Every open issue (up to ``LIST_LIMIT``) as a flat row."""
    if not cfg.todo.enabled:
        raise TodoSyncError("untracked needs todo.folder")
    repo = ["--repo", cfg.todo.gh_repo] if cfg.todo.gh_repo else []
    out = gh.run_gh(cfg.project_root, ["issue", "list", "--state", "open", "--limit", str(LIST_LIMIT),
                                       "--json", LIST_FIELDS, *repo])
    return [_flatten(raw) for raw in json.loads(out) if isinstance(raw, dict) and "number" in raw]


def find_untracked(cfg: HarnessConfig) -> List[Dict[str, Any]]:
    """The open issues no catalog record mentions, sorted by number."""
    rows = open_issues(cfg)
    tracked = tracked_numbers(Sources(cfg))
    fresh = sorted((r for r in rows if r["number"] not in tracked), key=lambda r: r["number"])
    for row in fresh:
        attach_reviews(cfg, row)
    return fresh


def attach_reviews(cfg: HarnessConfig, row: Dict[str, Any]) -> None:
    """Fill ``reviews`` and ``reviews_truncated`` of ``row`` from the PR reviews its text links."""
    slug = slug_of(row["url"])
    texts = [row["body"], *(c["body"] for c in row["comments"])]
    links = review_links(texts, slug) if slug else []
    if links:
        row["reviews"], row["reviews_truncated"], row["review_errors"] = fetch_reviews(
            cfg.project_root, slug, links)


def write_untracked(cfg: HarnessConfig, rows: List[Dict[str, Any]]) -> Path:
    """Write ``rows`` to ``untracked_path`` and return it."""
    return write_atomic(untracked_path(cfg), json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
