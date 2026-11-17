"""Field updates of existing TODO items: set the fields a person judges on live items, then re-rank.

An update spec is ``{"updates": [{"id": "todo-k7qf", "fields": {"summary": "..."}}, ...]}``. Each entry
names one live item (in any case, with or without its ``todo-`` prefix) and sets only the fields an ``add``
spec may carry, less the issue keys (``UPDATE_FIELDS``); ids, ranks, scores, links and sources stay computed.
Every other field of the item is left as it was. The values pass the same shape and schema checks an added
item does, one spec sets each field of an item once, and the whole catalog is rescored and re-ranked after.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from harness_lib.todo_sync import TodoSyncError
from harness_lib.todo_sync import ids as todo_ids
from harness_lib.todo_sync import reshape
from harness_lib.todo_sync.reshape import ADD_OPTIONAL, ADD_REQUIRED, ISSUE_KEYS, Move

#: The fields an update may set: the ``add`` spec keys less the issue keys, in that order.
UPDATE_FIELDS = tuple(k for k in ADD_REQUIRED + ADD_OPTIONAL if k not in ISSUE_KEYS)

#: One updated item: ``(id, fields set)``.
ItemFields = Tuple[str, Tuple[str, ...]]


@dataclass(frozen=True)
class Updated:
    """The catalog after an update, the ``(id, fields)`` set per item in first-update order (fields in
    first-set order), and the rescored ids and rank moves in new-rank order."""

    catalog: Dict[str, Any]
    updated: Tuple[ItemFields, ...]
    rescored: Tuple[str, ...]
    reranked: Tuple[Move, ...]


def merge_updated(pairs: Iterable[Tuple[str, Sequence[str]]]) -> Tuple[ItemFields, ...]:
    """One ``(id, fields)`` per item in first-seen order, each item's fields merged in first-set order."""
    merged: Dict[str, List[str]] = {}
    for item_id, fields in pairs:
        known = merged.setdefault(item_id, [])
        known.extend(f for f in fields if f not in known)
    return tuple((item_id, tuple(fields)) for item_id, fields in merged.items())


def _resolve(n: int, catalog: Dict[str, Any], raw: str) -> str:
    """The live id update ``n`` names; a retired, split or unknown id, or a raw naming more than one
    id, raises."""
    try:
        found = todo_ids.resolve_ids(catalog, [raw])
    except TodoSyncError as exc:
        raise TodoSyncError(f"update {n}: {exc}") from exc
    if len(found) != 1:
        raise TodoSyncError(f"update {n} names {len(found)} ids; an update names one")
    return found[0]


def _check_entry(n: int, entry: Any, catalog: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Refuse update ``n`` unless it is an object naming one live item and setting update fields of the
    right base shape; ``(canonical id, fields)``."""
    if not isinstance(entry, dict):
        raise TodoSyncError(f"update {n} is not an object")
    if not reshape._text(entry.get("id")):
        raise TodoSyncError(f"update {n} names no id")
    fields = entry.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise TodoSyncError(f"update {n} sets no field")
    for key in fields:
        if key not in UPDATE_FIELDS:
            raise TodoSyncError(f"update {n} sets {key}; an update never sets it")
    reshape._check_types(n, fields, "update")
    return _resolve(n, catalog, entry["id"]), fields


def _apply_one(n: int, item: Dict[str, Any], fields: Dict[str, Any], seen: Set[Tuple[str, str]]) -> None:
    """Lay ``fields`` over ``item`` (deep copies) and hold it to the catalog schema; a field an earlier
    update of the same spec set raises."""
    item_id = str(item.get("id"))
    for key in fields:
        if (item_id, key) in seen:
            raise TodoSyncError(f"update {n} sets {item_id} {key} again; one spec sets a field once")
    seen.update((item_id, key) for key in fields)
    item.update({key: copy.deepcopy(value) for key, value in fields.items()})
    reshape._check_item(n, item, "update")


def apply_updates(catalog: Dict[str, Any], entries: Sequence[Any]) -> Updated:
    """Set each entry's fields on its item in a copy of ``catalog``, then rescore and re-rank.

    Raises:
        TodoSyncError: a catalog holding rank-tied ids, an empty ``entries`` or a bad entry.
    """
    todo_ids.require_stable(catalog, "update")
    if not entries:
        raise TodoSyncError("update needs at least one update in the spec")
    data = copy.deepcopy(catalog)
    data["items"] = [i for i in data.get("items") or [] if isinstance(i, dict)]
    by_id = {str(i.get("id")): i for i in data["items"]}
    seen: Set[Tuple[str, str]] = set()
    pairs: List[Tuple[str, Tuple[str, ...]]] = []
    for n, entry in enumerate(entries, 1):
        item_id, fields = _check_entry(n, entry, data)
        _apply_one(n, by_id[item_id], fields, seen)
        pairs.append((item_id, tuple(fields)))
    rescored, reranked = reshape._rerank(data)
    return Updated(data, merge_updated(pairs), rescored, reranked)
