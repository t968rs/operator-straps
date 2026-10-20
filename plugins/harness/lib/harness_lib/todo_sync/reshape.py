"""Split one TODO item into parts, or refresh every item's score and rank; both end by renumbering.

Rule T6 ties each id to its rank, so both operations finish the same way: rescore from ``ranking_method``,
sort, renumber ``TODO-<rank>``, map the link lists (``depends_on``, ``unblocks``, tracker ``child_todo_ids``,
close-candidate ``related_todo_ids``) id for id, and rewrite every other string in one pass. A split's parts
start as copies of the original item with the spec's fields laid over them; they inherit its links, tracker
and close candidates. Prose naming the original id is pointed at the first part and listed for a person to
check, because only a person can say which part a sentence meant.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from harness_lib.config import HarnessConfig
from harness_lib.todo_sync import TodoSyncError
from harness_lib.todo_sync.ranking import RankingError, RankingMethod, expected_order, method_from, score
from harness_lib.todo_sync.retire import (ID_RE, REFERENCE_CAP, companion_edits, dump_like, load_catalog,
                                          normalize_id, other_references, recount, remap_text, todo_id,
                                          walk_strings, write_edits)

#: Fields a split computes; a part spec may not set them.
COMPUTED = ("id", "rank", "priority")
#: Catalog sections whose records hold id lists, and those lists.
LINKS = {"items": ("depends_on", "unblocks"), "trackers": ("child_todo_ids",),
         "close_candidates": ("related_todo_ids",)}


@dataclass(frozen=True)
class Reshape:
    """The catalog after a split or refresh, with what moved."""

    catalog: Dict[str, Any]
    renames: Dict[str, str]
    parts: Tuple[str, ...]
    rescored: Tuple[str, ...]
    flagged: Tuple[str, ...]
    split: Optional[str] = None


def split_item(catalog: Dict[str, Any], raw_id: str, parts: Sequence[Any]) -> Reshape:
    """Replace one item of a copy of ``catalog`` with ``parts`` (field overrides of the item), then
    renumber."""
    data = copy.deepcopy(catalog)
    items = [i for i in data.get("items") or [] if isinstance(i, dict)]
    orig_id = normalize_id(raw_id)
    orig = next((i for i in items if i.get("id") == orig_id), None)
    if orig is None:
        raise TodoSyncError(f"no such item in the catalog: {orig_id}")
    others = [i for i in items if i is not orig]
    built = _build_parts(orig, parts, {str(i.get("id")) for i in others})
    _unlink(data, others, orig_id)
    _link_parts(data, others, built, orig_id)
    data["items"] = others + built
    temps = [str(p["id"]) for p in built]
    out = _renumber(data, orig_id, temps[0])
    return Reshape(out.catalog, {o: n for o, n in out.renames.items() if o not in temps},
                   tuple(out.renames[t] for t in temps), out.rescored, out.flagged, orig_id)


def refresh_items(catalog: Dict[str, Any]) -> Reshape:
    """Rescore, re-sort, renumber and recount a copy of ``catalog`` after hand edits to item fields."""
    data = copy.deepcopy(catalog)
    data["items"] = [i for i in data.get("items") or [] if isinstance(i, dict)]
    return _renumber(data, None, None)


def _build_parts(orig: Dict[str, Any], parts: Sequence[Any], known: Set[str]) -> List[Dict[str, Any]]:
    if len(parts) < 2:
        raise TodoSyncError("a split needs at least two parts")
    built: List[Dict[str, Any]] = []
    for n, spec in enumerate(parts, 1):
        if not isinstance(spec, dict):
            raise TodoSyncError(f"part {n} is not an object")
        fixed = [k for k in COMPUTED if k in spec]
        if fixed:
            raise TodoSyncError(f"part {n} sets {', '.join(fixed)}; the split computes it")
        if not isinstance(spec.get("title"), str) or not spec["title"].strip():
            raise TodoSyncError(f"part {n} needs a title")
        part = {**copy.deepcopy(orig), **copy.deepcopy(spec), "id": f"split-part-{n}"}
        _check_links(part, n, known, str(orig.get("id")))
        built.append(part)
    titles = [p["title"] for p in built]
    shared = sorted({t for t in titles if titles.count(t) > 1})
    if shared:
        raise TodoSyncError(f"parts share the title {shared[0]!r}")
    return built


def _check_links(part: Dict[str, Any], n: int, known: Set[str], orig_id: str) -> None:
    for field in LINKS["items"]:
        for ref in part.get(field) or []:
            if ref == orig_id:
                raise TodoSyncError(f"part {n} {field} names the item being split ({orig_id})")
            if ref not in known:
                raise TodoSyncError(f"part {n} {field} names {ref}, which is not in the catalog")


def _unlink(data: Dict[str, Any], others: List[Dict[str, Any]], orig_id: str) -> None:
    """Drop ``orig_id`` from every id list; close candidates that named it are marked ``_split_of``."""
    for item in others:
        for field in LINKS["items"]:
            item[field] = [x for x in item.get(field) or [] if x != orig_id]
    for key in ("trackers", "close_candidates"):
        field = LINKS[key][0]
        for record in data.get(key) or []:
            if isinstance(record, dict) and isinstance(record.get(field), list) and orig_id in record[field]:
                record[field] = [x for x in record[field] if x != orig_id]
                if key == "close_candidates":
                    record["_split_of"] = True


def _link_parts(data: Dict[str, Any], others: List[Dict[str, Any]], built: List[Dict[str, Any]],
                orig_id: str) -> None:
    """Give each part's links their inverses; trackers list their parts, close candidates every part."""
    by_id = {str(i.get("id")): i for i in others}
    for part in built:
        for ref in part.get("unblocks") or []:
            _append(by_id[ref], "depends_on", part["id"])
        for ref in part.get("depends_on") or []:
            _append(by_id[ref], "unblocks", part["id"])
    for record in data.get("trackers") or []:
        if isinstance(record, dict):
            for part in (p for p in built if p.get("tracker") == record.get("number")):
                _append(record, "child_todo_ids", part["id"])
    for record in data.get("close_candidates") or []:
        if isinstance(record, dict) and record.pop("_split_of", None):
            for part in built:
                _append(record, "related_todo_ids", part["id"])


def _append(record: Dict[str, Any], field: str, value: str) -> None:
    listed = list(record.get(field) or [])
    if value not in listed:
        listed.append(value)
    record[field] = listed


def _method(data: Dict[str, Any]) -> RankingMethod:
    try:
        return method_from(data.get("ranking_method"))
    except RankingError as exc:
        raise TodoSyncError(f"ranking_method: {exc}") from exc


def _rescore(items: List[Dict[str, Any]], method: RankingMethod) -> List[str]:
    """Store each item's recomputed ``priority`` where it differs; the ids (pre-renumber) that changed."""
    changed: List[str] = []
    for item in items:
        try:
            value, components = score(item, method)
        except RankingError as exc:
            raise TodoSyncError(f"cannot score {item.get('id')}: {exc}") from exc
        fresh = {"score": value, "components": components}
        if item.get("priority") != fresh:
            item["priority"] = fresh
            changed.append(str(item.get("id")))
    return changed


def _renumber(data: Dict[str, Any], orig_id: Optional[str], first: Optional[str]) -> Reshape:
    """Rescore, sort, renumber and rewrite ``data`` in place; ``orig_id`` prose points at ``first``'s id."""
    method = _method(data)
    changed = _rescore(data["items"], method)
    by_id = {str(i.get("id")): i for i in data["items"]}
    order = expected_order(data["items"], method)
    moved = {old: todo_id(n) for n, old in enumerate(order, 1)}
    data["items"] = [by_id[x] for x in order]
    prose = dict(moved)
    if orig_id is not None and first is not None:
        prose[orig_id] = moved[first]
    flagged: List[str] = []
    out = _rewrite(data, moved, prose, orig_id, flagged)
    for n, item in enumerate(out["items"], 1):
        item["id"], item["rank"] = todo_id(n), n
    out["counts"] = recount(out.get("counts"), out, ())
    renames = {o: n for o, n in sorted(moved.items()) if o != n}
    return Reshape(out, renames, (), tuple(sorted(moved[x] for x in changed)), tuple(flagged))


def _rewrite(data: Dict[str, Any], moved: Dict[str, str], prose: Dict[str, str], orig_id: Optional[str],
             flagged: List[str]) -> Dict[str, Any]:
    """``data`` with id lists mapped through ``moved`` and other strings through ``prose`` in one pass."""
    def sub(text: str, where: str) -> str:
        if orig_id is not None and orig_id in ID_RE.findall(text):
            flagged.append(f"{where} names split {orig_id}, now {prose[orig_id]} (first part)")
        return remap_text(text, prose)

    out: Dict[str, Any] = {}
    for key, value in data.items():
        if key in LINKS and isinstance(value, list):
            out[key] = [_record(r, _where(key, n, r, moved), LINKS[key], moved, sub)
                        for n, r in enumerate(value)]
        else:
            out[key] = walk_strings(value, key, sub)
    return out


def _where(key: str, n: int, record: Any, moved: Dict[str, str]) -> str:
    if key == "items" and isinstance(record, dict):
        return f"items/{moved.get(str(record.get('id')), record.get('id'))}"
    return f"{key}/{n}"


def _record(record: Any, where: str, fields: Tuple[str, ...], moved: Dict[str, str],
            sub: Callable[[str, str], str]) -> Any:
    """One record with its id lists mapped (kept sorted when they were) and its other strings rewritten."""
    if not isinstance(record, dict):
        return walk_strings(record, where, sub)
    out: Dict[str, Any] = {}
    for k, v in record.items():
        if k in fields and isinstance(v, list):
            mapped = [moved.get(x, x) for x in v]
            out[k] = sorted(mapped) if v == sorted(v) else mapped
        else:
            out[k] = walk_strings(v, f"{where}/{k}", sub)
    return out


@dataclass(frozen=True)
class ReshapeResult:
    """What ``apply_split`` or ``apply_refresh`` changed (or would change) and what it left for a person."""

    reshape: Reshape
    rewritten: Tuple[str, ...]
    flagged: Tuple[str, ...]
    references: Tuple[str, ...]


def read_spec(path: Path) -> List[Any]:
    """The ``parts`` list of a split spec file: ``{"parts": [{...}, {...}]}``."""
    try:
        doc = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TodoSyncError(f"split spec {path}: unreadable: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("parts"), list):
        raise TodoSyncError(f"split spec {path}: expected an object with a 'parts' list")
    return doc["parts"]


def apply_split(cfg: HarnessConfig, raw_id: str, spec: Path, dry_run: bool = False) -> ReshapeResult:
    """Split one item of the project's catalog per ``spec`` and rewrite moved ids in its companions."""
    parts = read_spec(spec)
    return _apply(cfg, "split", lambda data: split_item(data, raw_id, parts), dry_run)


def apply_refresh(cfg: HarnessConfig, dry_run: bool = False) -> ReshapeResult:
    """Refresh the project's catalog ranking and rewrite moved ids in its companions."""
    return _apply(cfg, "refresh", refresh_items, dry_run)


def _apply(cfg: HarnessConfig, verb: str, fn: Callable[[Dict[str, Any]], Reshape],
           dry_run: bool) -> ReshapeResult:
    raw, data = load_catalog(cfg, verb)
    out = fn(data)
    renames, notes = dict(out.renames), {}
    if out.split is not None:
        renames[out.split] = out.parts[0]
        notes[out.split] = f"names split {out.split}, now {out.parts[0]} (first part)"
    edits, noted = companion_edits(cfg, renames, notes)
    if not dry_run and (out.catalog != data or edits):
        write_edits(cfg, dump_like(out.catalog, raw), edits)
    refs = other_references(cfg, edits) if renames else ()
    return ReshapeResult(out, tuple(edits), (*out.flagged, *noted), refs)


def summary_lines(result: ReshapeResult, dry_run: bool) -> List[str]:
    """The driver's report: what moved, what was rewritten and the prose left for a person to check."""
    out = result.reshape
    count = len(out.catalog["items"])
    if out.split is not None:
        head = f"{'would split' if dry_run else 'split'} {out.split} into {', '.join(out.parts)}"
    else:
        head = f"{'would refresh' if dry_run else 'refreshed'} {count} item(s)"
    lines = [f"{head}; {count} item(s) now" if out.split is not None else head]
    if out.rescored:
        lines.append(f"rescored {len(out.rescored)} item(s): {', '.join(out.rescored)}")
    if out.renames:
        lines.append(f"renumbered {len(out.renames)} item(s): "
                     + ", ".join(f"{old}->{new}" for old, new in out.renames.items()))
    if out.split is None and not out.rescored and not out.renames:
        lines.append("nothing changed")
    lines.extend(f"rewrote ids in {rel}" for rel in result.rewritten)
    lines.extend(f"review: {note}" for note in result.flagged)
    lines.extend(f"reference (not rewritten): {ref}" for ref in result.references[:REFERENCE_CAP])
    if len(result.references) > REFERENCE_CAP:
        lines.append(f"... {len(result.references) - REFERENCE_CAP} more reference(s)")
    if not dry_run and (out.split is not None or out.rescored or out.renames):
        lines.append("next: todo_sync.py render, then todo_sync.py check")
    return lines
