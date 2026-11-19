"""The TODO ids and issue numbers a branch works on: parsing, catalog fill, the override file, the line text.

The override file is ``<state_dir>/OVERRIDES_REL``: ``{"version": 1, "branches": {<branch>: {"todo_ids":
[...], "issues": [...], "set_at": "<UTC ISO 8601>"}}}``. Only the harness writes it; the working-refs mod
reads it and writes the rendered line to ``<state_dir>/LINE_REL``, so each file has one writer.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from pydantic import ValidationError

from harness_lib.config import HarnessConfig
from harness_lib.plan_models import PlanRefs
from harness_lib.todo_sync.ids import canonical
from harness_lib.todo_sync.sources import read_json

OVERRIDES_REL = "working-refs/overrides.json"
LINE_REL = "working-refs/line.txt"
STORE_VERSION = 1
DETACHED = "(detached)"

_SEPARATORS = re.compile(r"[,\s]+")
_ISSUE = re.compile(r"#?([0-9]+)")


class WorkingRefsError(ValueError):
    """A ref token or an override file the library refuses."""


def _issue(token: str) -> int:
    """The issue number ``#N`` or ``N`` names, or -1 when ``token`` is not one."""
    match = _ISSUE.fullmatch(token)
    number = int(match.group(1)) if match else 0
    return number if number > 0 else -1


def _add(seen: List[Any], value: Any) -> None:
    if value not in seen:
        seen.append(value)


def parse_refs(tokens: Iterable[str]) -> PlanRefs:
    """The refs ``tokens`` name, split on commas and whitespace, duplicates dropped in first order.

    ``#301`` and ``301`` are issues; ``TODO-K69M`` and ``k69m`` are TODO ids, canonicalized as ``todo_sync``
    does. Raises ``WorkingRefsError`` for a token that is neither, and when no token is left to name a ref
    (separators only).
    """
    todo_ids: List[str] = []
    issues: List[int] = []
    for token in (t for raw in tokens for t in _SEPARATORS.split(raw) if t):
        number = _issue(token)
        todo_id = canonical(token) if number < 0 else None
        if number < 0 and todo_id is None:
            raise WorkingRefsError(f"{token!r} is neither a TODO id nor an issue number")
        if number > 0:
            _add(issues, number)
        else:
            _add(todo_ids, todo_id)
    if not todo_ids and not issues:
        raise WorkingRefsError("no TODO id or issue number given")
    return PlanRefs(todo_ids=todo_ids, issues=issues)


def catalog_data(cfg: HarnessConfig) -> Dict[str, Any]:
    """The TODO catalog object, or ``{}`` when ``todo.catalog`` is unset or its file is absent or unusable."""
    if not cfg.todo.catalog:
        return {}
    found = read_json(cfg.project_root, cfg.todo.catalog)
    return found.data if found.ok else {}


def _positive_ints(raw: Any) -> List[int]:
    """The positive, non-bool integers of a ``gh_issues`` value; empty when it is not a list."""
    if not isinstance(raw, list):
        return []
    return [n for n in raw if isinstance(n, int) and not isinstance(n, bool) and n > 0]


def _catalog_issues(catalog: Mapping[str, Any]) -> Dict[str, List[int]]:
    """Each catalog item id mapped to its positive integer ``gh_issues``."""
    items = catalog.get("items")
    found: Dict[str, List[int]] = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            found[item["id"]] = _positive_ints(item.get("gh_issues"))
    return found


def fill_issues(refs: PlanRefs, catalog: Mapping[str, Any]) -> PlanRefs:
    """``refs`` unchanged when it names an issue, else the named ids' catalog ``gh_issues`` in id order."""
    if refs.issues:
        return refs
    by_id = _catalog_issues(catalog)
    issues: List[int] = []
    for todo_id in refs.todo_ids:
        for number in by_id.get(todo_id, []):
            _add(issues, number)
    return PlanRefs(todo_ids=list(refs.todo_ids), issues=issues)


def _read_branches(path: Path) -> Dict[str, Any]:
    """The raw ``branches`` object of the override file; empty for an absent file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as exc:
        raise WorkingRefsError(f"{path} is not JSON") from exc
    version = data.get("version") if isinstance(data, dict) else None
    if isinstance(version, bool) or version != STORE_VERSION or not isinstance(data.get("branches"), dict):
        raise WorkingRefsError(f"{path} is not a version {STORE_VERSION} override file")
    return data["branches"]


def read_overrides(path: Path) -> Dict[str, PlanRefs]:
    """Each branch's override refs; an absent file holds none, and an unusable entry is skipped.

    Raises ``WorkingRefsError`` for a file that is not JSON or not a version-1 object with ``branches``.
    """
    found: Dict[str, PlanRefs] = {}
    for branch, entry in _read_branches(path).items():
        if not isinstance(entry, dict):
            continue
        try:
            found[branch] = PlanRefs(todo_ids=entry.get("todo_ids", []), issues=entry.get("issues", []))
        except ValidationError:
            continue
    return found


def _write_branches(path: Path, branches: Dict[str, Any]) -> None:
    """Write the file through a sibling temp file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps({"version": STORE_VERSION, "branches": branches}, indent=2) + "\n"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def set_override(path: Path, branch: str, refs: PlanRefs) -> None:
    """Store ``refs`` as ``branch``'s override, stamped with the UTC time; other branches stay as they are."""
    branches = _read_branches(path)
    set_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    branches[branch] = {"todo_ids": list(refs.todo_ids), "issues": list(refs.issues), "set_at": set_at}
    _write_branches(path, branches)


def clear_override(path: Path, branch: str) -> bool:
    """Drop ``branch``'s override; False, with nothing written, when it has none."""
    branches = _read_branches(path)
    if branch not in branches:
        return False
    del branches[branch]
    _write_branches(path, branches)
    return True


def format_refs(refs: PlanRefs) -> str:
    """``todo-k69m (301)``: ids joined by ``, ``, then issues in parentheses; issues alone ``#301, #315``."""
    issues = ", ".join(str(n) for n in refs.issues)
    if not refs.todo_ids:
        return ", ".join(f"#{n}" for n in refs.issues)
    ids = ", ".join(refs.todo_ids)
    return f"{ids} ({issues})" if issues else ids
