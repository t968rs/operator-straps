"""Split one TODO item into parts, add items for open issues, or refresh every item's score and rank; all
three end by renumbering.

Rule T6 ties each id to its rank, so the operations finish the same way: rescore from ``ranking_method``,
sort, renumber ``TODO-<rank>``, map the link lists (``depends_on``, ``unblocks``, tracker ``child_todo_ids``,
close-candidate ``related_todo_ids``) id for id, and rewrite every other string in one pass. A split's parts
start as copies of the original item with the spec's fields laid over them; they inherit its links, tracker
and close candidates. Prose naming the original id is pointed at the first part and listed for a person to
check, because only a person can say which part a sentence meant. An added item starts from a spec that names
its issue and the fields a person judges (title, kind, summary, scoring inputs); the script supplies its
source, links and score, so the new item takes the rank its score earns and the items below it move down.
"""
from __future__ import annotations

import copy
import functools
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from harness_lib.config import HarnessConfig
from harness_lib.project import plugin_root
from harness_lib.todo_sync import TodoSyncError
from harness_lib.todo_sync.issues import catalog_issue_numbers
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
    """The catalog after a split, add or refresh, with what moved."""

    catalog: Dict[str, Any]
    renames: Dict[str, str]
    parts: Tuple[str, ...]
    rescored: Tuple[str, ...]
    flagged: Tuple[str, ...]
    split: Optional[str] = None
    added: Tuple[Tuple[str, int], ...] = ()


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


#: Keys an ``add`` spec item must carry, and those it may carry; everything else is computed or refused.
ADD_REQUIRED = ("issue", "url", "title", "kind", "summary", "proposed_change", "blast_radius", "loe",
                "impact", "severity", "why_ranked")
ADD_OPTIONAL = ("needs_decision", "decision_question", "status", "files", "related_gh_issues", "code_snippet")


def add_items(catalog: Dict[str, Any], specs: Sequence[Any]) -> Reshape:
    """Add one item per spec to a copy of ``catalog`` (its source is the spec's issue), then renumber."""
    if not specs:
        raise TodoSyncError("add needs at least one item in the spec")
    data = copy.deepcopy(catalog)
    known, listed = catalog_issue_numbers(data), set()
    built = [_new_item(n, spec, known, listed) for n, spec in enumerate(specs, 1)]
    data["items"] = [i for i in data.get("items") or [] if isinstance(i, dict)] + built
    out = _renumber(data, None, None)
    temps = [str(i["id"]) for i in built]
    new_ids = tuple(out.renames[t] for t in temps)
    absorbed = out.catalog["counts"].get("sources_absorbed")
    if isinstance(absorbed, dict) and isinstance(absorbed.get("gh_issue"), int):
        absorbed["gh_issue"] += len(built)
    return replace(out, renames={o: n for o, n in out.renames.items() if o not in temps},
                   rescored=tuple(r for r in out.rescored if r not in new_ids),
                   added=tuple(zip(new_ids, (i["gh_issues"][0] for i in built))))


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


ADD_STATUSES = ("OPEN", "PARTIAL", "NEEDS_DECISION", "BLOCKED")
#: The schema an added item must pass, under the plugin's ``schemas`` folder.
ITEM_SCHEMA = "catalogs/TodoCatalog.schema.json"
_PLACEHOLDER_PRIORITY = {"score": 0, "components": {k: 0 for k in (
    "impact_weight", "value", "loe_points", "blast_factor", "cost", "base_score", "unblock_bonus")}}
#: Per spec key: a check on its value and what to say when it fails.
_TYPE_RULES: Dict[str, Tuple[Callable[[Any], bool], str]] = {
    **{k: (_text, "a non-empty string") for k in ("url", "title", "kind", "summary", "proposed_change",
                                                    "impact", "why_ranked")},
    "severity": (lambda v: _count(v) and v <= 5, "an integer from 1 to 5"),
    "loe": (lambda v: isinstance(v, dict) and _text(v.get("size")) and _text(v.get("reasoning")),
            "an object with size and reasoning"),
    "blast_radius": (lambda v: isinstance(v, dict) and _text(v.get("level")) and _text(v.get("reasoning"))
                     and isinstance(v.get("consumers"), list), "an object with level, reasoning and consumers"),
    "needs_decision": (lambda v: isinstance(v, bool), "true or false"),
    "decision_question": (lambda v: v is None or isinstance(v, str), "a string or null"),
    "status": (lambda v: v in ADD_STATUSES, f"one of {', '.join(ADD_STATUSES)}"),
    "files": (lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v), "a list of strings"),
    "related_gh_issues": (lambda v: isinstance(v, list) and all(_count(x) for x in v),
                          "a list of issue numbers"),
    "code_snippet": (lambda v: isinstance(v, str), "a string"),
}


def _check_types(n: int, spec: Dict[str, Any]) -> None:
    """Refuse a spec value of the wrong base shape with a plain message; ``_check_item`` then holds the built
    item to the catalog schema."""
    for key, (valid, wanted) in _TYPE_RULES.items():
        if key in spec and not valid(spec[key]):
            raise TodoSyncError(f"item {n}: {key} must be {wanted}")


@functools.lru_cache(maxsize=1)
def _item_validator() -> Any:
    """A validator for one catalog item: ``$defs/item`` of the harness TodoCatalog schema."""
    import jsonschema
    schema = json.loads((plugin_root() / "schemas" / ITEM_SCHEMA).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/item"})


def _check_item(n: int, item: Dict[str, Any]) -> None:
    """Refuse a built item the catalog schema rejects (enums, patterns, unique lists, the needs_decision
    rules), before it is scored or written; the computed fields get valid placeholders first."""
    probe = {**item, "id": "TODO-001", "rank": 1, "priority": _PLACEHOLDER_PRIORITY}
    errors = sorted(_item_validator().iter_errors(probe), key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        where = "/".join(str(p) for p in errors[0].absolute_path) or "item"
        raise TodoSyncError(f"item {n}: {where}: {errors[0].message[:200]}")


def _new_item(n: int, spec: Any, known: Set[int], listed: Set[int]) -> Dict[str, Any]:
    """The catalog item for spec item ``n``; id, rank and priority are placeholders the renumber fills."""
    if not isinstance(spec, dict):
        raise TodoSyncError(f"item {n} is not an object")
    for key in spec:
        if key not in ADD_REQUIRED + ADD_OPTIONAL:
            raise TodoSyncError(f"item {n} sets {key}; add computes it or does not take it")
    missing = [k for k in ADD_REQUIRED if k not in spec]
    if missing:
        raise TodoSyncError(f"item {n} lacks {', '.join(missing)}")
    _check_types(n, spec)
    issue = spec["issue"]
    if isinstance(issue, bool) or not isinstance(issue, int) or issue < 1:
        raise TodoSyncError(f"item {n}: issue must be a positive integer")
    if issue in listed:
        raise TodoSyncError(f"issue #{issue} appears twice in the spec")
    if issue in known:
        raise TodoSyncError(f"issue #{issue} is already in the catalog (item {n})")
    listed.add(issue)
    item = _item_fields(n, spec)
    _check_item(n, item)
    return item


def _item_fields(n: int, spec: Dict[str, Any]) -> Dict[str, Any]:
    """The item's keys in schema order, with the spec's values and the defaults of the optional ones."""
    issue = spec["issue"]
    item: Dict[str, Any] = {
        "id": f"add-new-{n}", "rank": 0, "title": spec["title"], "kind": spec["kind"],
        "status": spec.get("status", "OPEN"), "needs_decision": spec.get("needs_decision", False),
        "decision_question": spec.get("decision_question"), "tracker": None,
        "sources": [{"type": "gh_issue", "ref": f"#{issue}", "url": spec["url"]}], "gh_issues": [issue],
        "related_gh_issues": list(spec.get("related_gh_issues") or []), "catalog_entry_ids": [],
        "summary": spec["summary"], "proposed_change": spec["proposed_change"]}
    if "code_snippet" in spec:
        item["code_snippet"] = spec["code_snippet"]
    item.update({"files": list(spec.get("files") or []), "blast_radius": spec["blast_radius"],
                 "loe": spec["loe"], "impact": spec["impact"], "severity": spec["severity"], "priority": {},
                 "depends_on": [], "unblocks": [], "why_ranked": spec["why_ranked"]})
    return item


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
    """What ``apply_split``, ``apply_add`` or ``apply_refresh`` changed (or would change) and what it left
    for a person."""

    reshape: Reshape
    rewritten: Tuple[str, ...]
    flagged: Tuple[str, ...]
    references: Tuple[str, ...]


def read_spec(path: Path, key: str = "parts") -> List[Any]:
    """The ``key`` list of a spec file: ``{"parts": [{...}, {...}]}`` for a split, ``{"items": [...]}`` for
    an add."""
    what = "split spec" if key == "parts" else "add spec"
    try:
        doc = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TodoSyncError(f"{what} {path}: unreadable: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get(key), list):
        raise TodoSyncError(f"{what} {path}: expected an object with a '{key}' list")
    return doc[key]


def apply_split(cfg: HarnessConfig, raw_id: str, spec: Path, dry_run: bool = False) -> ReshapeResult:
    """Split one item of the project's catalog per ``spec`` and rewrite moved ids in its companions."""
    parts = read_spec(spec)
    return _apply(cfg, "split", lambda data: split_item(data, raw_id, parts), dry_run)


def apply_add(cfg: HarnessConfig, spec: Path, dry_run: bool = False) -> ReshapeResult:
    """Add the items of the ``add`` spec file to the project's catalog and rewrite moved ids in its
    companions."""
    specs = read_spec(spec, "items")
    return _apply(cfg, "add", lambda data: add_items(data, specs), dry_run)


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
    changed = out.split is not None or bool(out.added)
    lines = [_head(out, dry_run, count)]
    if out.rescored:
        lines.append(f"rescored {len(out.rescored)} item(s): {', '.join(out.rescored)}")
    if out.renames:
        lines.append(f"renumbered {len(out.renames)} item(s): "
                     + ", ".join(f"{old}->{new}" for old, new in out.renames.items()))
    if not changed and not out.rescored and not out.renames:
        lines.append("nothing changed")
    lines.extend(f"rewrote ids in {rel}" for rel in result.rewritten)
    lines.extend(f"review: {note}" for note in result.flagged)
    lines.extend(f"reference (not rewritten): {ref}" for ref in result.references[:REFERENCE_CAP])
    if len(result.references) > REFERENCE_CAP:
        lines.append(f"... {len(result.references) - REFERENCE_CAP} more reference(s)")
    if not dry_run and (changed or out.rescored or out.renames):
        lines.append("next: todo_sync.py render, then todo_sync.py check")
    return lines


def _head(out: Reshape, dry_run: bool, count: int) -> str:
    """The first report line: what a split, an add or a refresh did to the catalog."""
    if out.split is not None:
        return f"{'would split' if dry_run else 'split'} {out.split} into {', '.join(out.parts)}; " \
               f"{count} item(s) now"
    if out.added:
        added = ", ".join(f"{item} (#{issue})" for item, issue in out.added)
        return f"{'would add' if dry_run else 'added'} {added}; {count} item(s) now"
    return f"{'would refresh' if dry_run else 'refreshed'} {count} item(s)"
