"""Split one TODO item into parts, add items (for open issues or local notes), or refresh every item's score
and rank; ids never change, only ranks move.

Item ids are stable (``todo-k7qf``), so the three operations end the same way: rescore from
``ranking_method``, sort, set each ``rank`` to the item's position and recount. A split's parts start as
copies of the original item with the spec's fields laid over them, each under a new id drawn past every live
and retired id; they inherit its links (``depends_on``, ``unblocks``, tracker ``child_todo_ids``,
close-candidate ``related_todo_ids``), tracker and close candidates. The original id joins ``retired_ids``
and ``split_ids`` records its parts in spec order. Prose naming the original id is listed for a person and
left as written, because only a person can say which part a sentence meant. An added item starts from a spec
that holds the fields a person judges (title, kind, summary, scoring inputs) and either names its issue
(``issue`` and ``url``) or names none, which makes it a local-only item with a dated ``note`` source; the
script supplies its new id, source, links and score, so the new item takes the rank its score earns and the
items below it move down. ``apply_add`` with ``file_issues`` first files an issue for each item that names
none, once the whole spec has validated.
"""
from __future__ import annotations

import copy
import datetime as dt
import functools
import json
import random
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Container, Dict, List, Optional, Sequence, Set, Tuple

from harness_lib.config import HarnessConfig
from harness_lib.project import plugin_root
from harness_lib.todo_sync import TodoSyncError
from harness_lib.todo_sync import ids as todo_ids
from harness_lib.todo_sync import issues
from harness_lib.todo_sync.issues import catalog_issue_numbers
from harness_lib.todo_sync.ranking import (NOTE_SOURCE, RankingError, RankingMethod, expected_order,
                                           method_from, score)
from harness_lib.todo_sync.retire import (REFERENCE_CAP, companion_mentions, dump_like, load_catalog,
                                          mention_paths, other_references, recount, write_edits)

#: Fields a split computes; a part spec may not set them.
COMPUTED = ("id", "rank", "priority")
#: Catalog sections whose records hold id lists, and those lists.
LINKS = {"items": ("depends_on", "unblocks"), "trackers": ("child_todo_ids",),
         "close_candidates": ("related_todo_ids",)}
#: A valid stable id the schema check of an added item runs under.
_PROBE_ID = "todo-2a2a"

#: One rank move: ``(id, old rank, new rank)``.
Move = Tuple[str, Any, int]


@dataclass(frozen=True)
class Reshape:
    """The catalog after a split, add or refresh, with what moved; no id changes, only ranks.

    ``rescored`` and ``reranked`` run in new-rank order and leave out the items the same call made (added
    items and split parts had no rank).
    """

    catalog: Dict[str, Any]
    parts: Tuple[str, ...]
    rescored: Tuple[str, ...]
    reranked: Tuple[Move, ...]
    flagged: Tuple[str, ...]
    split: Optional[str] = None
    added: Tuple[Tuple[str, Optional[int]], ...] = ()


def split_item(catalog: Dict[str, Any], raw_id: str, parts: Sequence[Any],
               rng: Optional[random.Random] = None) -> Reshape:
    """Replace one item of a copy of ``catalog`` with ``parts`` (field overrides of the item), each under a
    new id drawn from ``rng``; retire the original id, record its parts in ``split_ids`` and re-rank.

    Raises:
        TodoSyncError: a catalog holding rank-tied ids, ``raw_id`` naming no live item, or a bad part.
    """
    todo_ids.require_stable(catalog, "split")
    [orig_id] = todo_ids.resolve_ids(catalog, [raw_id])
    data = copy.deepcopy(catalog)
    items = [i for i in data.get("items") or [] if isinstance(i, dict)]
    orig = next(i for i in items if i.get("id") == orig_id)
    others = [i for i in items if i is not orig]
    built = _build_parts(orig, parts, {str(i.get("id")) for i in others}, todo_ids.taken_ids(data), rng)
    _unlink(data, others, orig_id)
    _link_parts(data, others, built, orig_id)
    data["items"] = others + built
    part_ids = tuple(str(p["id"]) for p in built)
    _record_split(data, orig_id, part_ids)
    rescored, reranked = _rerank(data, part_ids)
    flags = tuple(_split_flags(data, orig_id, part_ids))
    return Reshape(data, part_ids, rescored, reranked, flags, orig_id)


def refresh_items(catalog: Dict[str, Any]) -> Reshape:
    """Rescore, re-sort, re-rank and recount a copy of ``catalog`` after hand edits to item fields.

    Raises:
        TodoSyncError: a catalog holding rank-tied ids.
    """
    todo_ids.require_stable(catalog, "refresh")
    data = copy.deepcopy(catalog)
    data["items"] = [i for i in data.get("items") or [] if isinstance(i, dict)]
    rescored, reranked = _rerank(data)
    return Reshape(data, (), rescored, reranked, ())


#: Keys an ``add`` spec item must carry, and those it may carry; everything else is computed or refused.
#: ``issue`` and ``url`` come together; an item with neither is a local-only note.
ADD_REQUIRED = ("title", "kind", "summary", "proposed_change", "blast_radius", "loe", "impact", "severity",
                "why_ranked")
ADD_OPTIONAL = ("issue", "url", "needs_decision", "decision_question", "status", "files", "related_gh_issues",
                "code_snippet")
#: Spec keys that name the item's GitHub issue.
ISSUE_KEYS = ("issue", "url")


def add_items(catalog: Dict[str, Any], specs: Sequence[Any], today: Optional[str] = None,
              rng: Optional[random.Random] = None) -> Reshape:
    """Add one item per spec to a copy of ``catalog``, each under a new id drawn from ``rng`` (its source is
    the spec's issue, else a note dated ``today``, default the current date), then re-rank.

    Raises:
        TodoSyncError: a catalog holding rank-tied ids, an empty ``specs`` or a bad spec item.
    """
    todo_ids.require_stable(catalog, "add")
    if not specs:
        raise TodoSyncError("add needs at least one item in the spec")
    day = today or dt.date.today().isoformat()
    data = copy.deepcopy(catalog)
    known, listed, taken = catalog_issue_numbers(data), set(), todo_ids.taken_ids(data)
    built: List[Dict[str, Any]] = []
    for n, spec in enumerate(specs, 1):
        _check_spec(n, spec, known, listed)
        built.append(_new_item(n, spec, day, _draw(taken, rng)))
    data["items"] = [i for i in data.get("items") or [] if isinstance(i, dict)] + built
    new_ids = tuple(str(i["id"]) for i in built)
    rescored, reranked = _rerank(data, new_ids)
    _count_sources(data["counts"], built)
    return Reshape(data, (), rescored, reranked, (),
                   added=tuple(zip(new_ids, ((i["gh_issues"] or [None])[0] for i in built))))


def _draw(taken: Set[str], rng: Optional[random.Random]) -> str:
    """A new id drawn past ``taken``, which then holds it too."""
    new = todo_ids.new_id(taken, rng)
    taken.add(new)
    return new


def _count_sources(counts: Dict[str, Any], built: List[Dict[str, Any]]) -> None:
    """Add the new items' sources to ``counts.sources_absorbed``; the ``note`` tally starts on first use."""
    absorbed = counts.get("sources_absorbed")
    if not isinstance(absorbed, dict):
        return
    for item in built:
        kind = item["sources"][0]["type"]
        if kind == NOTE_SOURCE:
            absorbed.setdefault(NOTE_SOURCE, 0)
        if isinstance(absorbed.get(kind), int):
            absorbed[kind] += 1


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
                     and isinstance(v.get("consumers"), list),
                     "an object with level, reasoning and consumers"),
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
    probe = {**item, "id": _PROBE_ID, "rank": 1, "priority": _PLACEHOLDER_PRIORITY}
    errors = sorted(_item_validator().iter_errors(probe), key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        where = "/".join(str(p) for p in errors[0].absolute_path) or "item"
        raise TodoSyncError(f"item {n}: {where}: {errors[0].message[:200]}")


def _check_spec(n: int, spec: Any, known: Set[int], listed: Set[int]) -> None:
    """Refuse spec item ``n`` unless it is an object holding every required key, no computed one, values of
    the right base shape and, when it names one, a new issue."""
    if not isinstance(spec, dict):
        raise TodoSyncError(f"item {n} is not an object")
    for key in spec:
        if key not in ADD_REQUIRED + ADD_OPTIONAL:
            raise TodoSyncError(f"item {n} sets {key}; add computes it or does not take it")
    missing = [k for k in ADD_REQUIRED if k not in spec]
    if missing:
        raise TodoSyncError(f"item {n} lacks {', '.join(missing)}")
    _check_types(n, spec)
    if "issue" in spec or "url" in spec:
        _check_issue(n, spec, known, listed)


def _new_item(n: int, spec: Dict[str, Any], day: str, item_id: str) -> Dict[str, Any]:
    """The catalog item ``item_id`` for checked spec item ``n``; rank and priority are placeholders the
    re-rank fills."""
    item = _item_fields(item_id, spec, day)
    _check_item(n, item)
    return item


def _check_issue(n: int, spec: Dict[str, Any], known: Set[int], listed: Set[int]) -> None:
    """Refuse a spec item's issue unless it comes with its url, is a positive number and is new."""
    if not all(key in spec for key in ISSUE_KEYS):
        raise TodoSyncError(f"item {n}: issue and url come together; a local note sets neither")
    issue = spec["issue"]
    if isinstance(issue, bool) or not isinstance(issue, int) or issue < 1:
        raise TodoSyncError(f"item {n}: issue must be a positive integer")
    if issue in listed:
        raise TodoSyncError(f"issue #{issue} appears twice in the spec")
    if issue in known:
        raise TodoSyncError(f"issue #{issue} is already in the catalog (item {n})")
    listed.add(issue)


def _source(spec: Dict[str, Any], day: str) -> Dict[str, Any]:
    """The item's one source: its GitHub issue, else a note dated ``day``."""
    if "issue" in spec:
        return {"type": "gh_issue", "ref": f"#{spec['issue']}", "url": spec["url"]}
    return {"type": NOTE_SOURCE, "ref": day}


def _item_fields(item_id: str, spec: Dict[str, Any], day: str) -> Dict[str, Any]:
    """The item's keys in schema order, with the spec's values and the defaults of the optional ones."""
    item: Dict[str, Any] = {
        "id": item_id, "rank": 0, "title": spec["title"], "kind": spec["kind"],
        "status": spec.get("status", "OPEN"), "needs_decision": spec.get("needs_decision", False),
        "decision_question": spec.get("decision_question"), "tracker": None,
        "sources": [_source(spec, day)], "gh_issues": [spec["issue"]] if "issue" in spec else [],
        "related_gh_issues": list(spec.get("related_gh_issues") or []), "catalog_entry_ids": [],
        "summary": spec["summary"], "proposed_change": spec["proposed_change"]}
    if "code_snippet" in spec:
        item["code_snippet"] = spec["code_snippet"]
    item.update({"files": list(spec.get("files") or []), "blast_radius": spec["blast_radius"],
                 "loe": spec["loe"], "impact": spec["impact"], "severity": spec["severity"], "priority": {},
                 "depends_on": [], "unblocks": [], "why_ranked": spec["why_ranked"]})
    return item


def _build_parts(orig: Dict[str, Any], parts: Sequence[Any], known: Set[str], taken: Set[str],
                 rng: Optional[random.Random]) -> List[Dict[str, Any]]:
    """One item per part spec: a copy of ``orig`` with the spec laid over it, under a new id drawn past
    ``taken``."""
    if len(parts) < 2:
        raise TodoSyncError("a split needs at least two parts")
    built: List[Dict[str, Any]] = []
    for n, spec in enumerate(parts, 1):
        _check_part(n, spec)
        part = {**copy.deepcopy(orig), **copy.deepcopy(spec), "id": _draw(taken, rng)}
        _check_links(part, n, known, str(orig.get("id")))
        built.append(part)
    titles = [p["title"] for p in built]
    shared = sorted({t for t in titles if titles.count(t) > 1})
    if shared:
        raise TodoSyncError(f"parts share the title {shared[0]!r}")
    return built


def _check_part(n: int, spec: Any) -> None:
    """Refuse part spec ``n`` unless it is an object with a title that sets no computed field."""
    if not isinstance(spec, dict):
        raise TodoSyncError(f"part {n} is not an object")
    fixed = [k for k in COMPUTED if k in spec]
    if fixed:
        raise TodoSyncError(f"part {n} sets {', '.join(fixed)}; the split computes it")
    if not isinstance(spec.get("title"), str) or not spec["title"].strip():
        raise TodoSyncError(f"part {n} needs a title")


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
    """Add ``value`` to ``record[field]`` once; a sorted list (an empty one counts) stays sorted."""
    listed = list(record.get(field) or [])
    if value not in listed:
        ordered = listed == sorted(listed, key=str)
        listed.append(value)
        if ordered:
            listed.sort(key=str)
    record[field] = listed


def _record_split(data: Dict[str, Any], orig_id: str, part_ids: Tuple[str, ...]) -> None:
    """Append ``orig_id`` to ``retired_ids`` and set ``split_ids[orig_id]`` to ``part_ids`` in spec order;
    either record is created when absent."""
    retired, splits = data.get("retired_ids"), data.get("split_ids")
    if retired is not None and not isinstance(retired, list):
        raise TodoSyncError("split: retired_ids is not a list")
    if splits is not None and not isinstance(splits, dict):
        raise TodoSyncError("split: split_ids is not an object")
    record = list(retired or [])
    if orig_id not in record:
        record.append(orig_id)
    data["retired_ids"] = record
    data["split_ids"] = {**(splits or {}), orig_id: list(part_ids)}


def _split_note(orig_id: str, part_ids: Sequence[str]) -> str:
    """``names split <orig> (parts <a>, <b>)``: the tail of every flag a split raises."""
    return f"names split {orig_id} (parts {', '.join(part_ids)})"


def _split_flags(data: Dict[str, Any], orig_id: str, part_ids: Sequence[str]) -> List[str]:
    """``<json path> names split <orig> (parts ...)`` for each catalog string naming ``orig_id`` in any case,
    left as written (``mention_paths``)."""
    note = _split_note(orig_id, part_ids)
    return mention_paths(data, [orig_id], lambda _hit: note)


def _method(data: Dict[str, Any]) -> RankingMethod:
    try:
        return method_from(data.get("ranking_method"))
    except RankingError as exc:
        raise TodoSyncError(f"ranking_method: {exc}") from exc


def _rescore(items: List[Dict[str, Any]], method: RankingMethod) -> List[str]:
    """Store each item's recomputed ``priority`` where it differs; the ids that changed."""
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


def _rerank(data: Dict[str, Any], fresh: Container[str] = ()) -> Tuple[Tuple[str, ...], Tuple[Move, ...]]:
    """Rescore, sort by ``expected_order``, set each ``rank`` to its position and recount ``data`` in place.

    Returns:
        The rescored ids and the ``(id, old rank, new rank)`` moves, both in new-rank order; ids in ``fresh``
        (items made by the same call, which had no rank) appear in neither.
    """
    method = _method(data)
    changed = set(_rescore(data["items"], method))
    by_id = {str(i.get("id")): i for i in data["items"]}
    order = expected_order(data["items"], method)
    data["items"] = [by_id[x] for x in order]
    moves: List[Move] = []
    for n, item in enumerate(data["items"], 1):
        if order[n - 1] not in fresh and item.get("rank") != n:
            moves.append((order[n - 1], item.get("rank"), n))
        item["rank"] = n
    data["counts"] = recount(data.get("counts"), data, ())
    rescored = tuple(x for x in order if x in changed and x not in fresh)
    return rescored, tuple(moves)


@dataclass(frozen=True)
class ReshapeResult:
    """What ``apply_split``, ``apply_add`` or ``apply_refresh`` changed (or would change) and what it left
    for a person."""

    reshape: Reshape
    flagged: Tuple[str, ...]
    references: Tuple[str, ...]
    scan_error: Optional[str] = None
    #: Issues ``add --file-issue`` filed (number, URL), how many a dry run would file, and the ids of the
    #: items it would file them for.
    filed: Tuple[Tuple[int, str], ...] = ()
    to_file: int = 0
    pending: Tuple[str, ...] = ()


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


def apply_split(cfg: HarnessConfig, raw_id: str, spec: Path, dry_run: bool = False,
                rng: Optional[random.Random] = None) -> ReshapeResult:
    """Split one item of the project's catalog per ``spec``, its parts' ids drawn from ``rng``; only the
    catalog is written."""
    parts = read_spec(spec)
    return _apply(cfg, "split", lambda data: split_item(data, raw_id, parts, rng), dry_run)


def apply_add(cfg: HarnessConfig, spec: Path, dry_run: bool = False, file_issues: bool = False,
              today: Optional[str] = None, rng: Optional[random.Random] = None) -> ReshapeResult:
    """Add the items of the ``add`` spec file to the project's catalog, their ids drawn from ``rng``; only the
    catalog is written. With ``file_issues``, each item that names no issue gets one filed first, once the
    whole spec passes a dry run; a dry run files nothing and ranks each item to file under a placeholder issue
    above every catalog number, so ties sort as the real run's ``gh_issue`` source does. A failure after
    filing names the issues filed."""
    specs = read_spec(spec, "items")
    day = today or dt.date.today().isoformat()
    pending = ([n for n, s in enumerate(specs) if isinstance(s, dict) and "issue" not in s]
               if file_issues else [])
    if not pending:
        return _apply(cfg, "add", lambda data: add_items(data, specs, day, rng), dry_run)
    preview = _apply(cfg, "add", lambda data: _preview_add(data, specs, pending, day, rng), True)
    if dry_run:
        ids = tuple(preview.reshape.added[n][0] for n in pending)
        return replace(preview, to_file=len(pending), pending=ids)
    filed_specs, filed = _file_pending(cfg, specs, pending)
    try:
        result = _apply(cfg, "add", lambda data: add_items(data, filed_specs, day, rng), False)
    except (TodoSyncError, RankingError, OSError) as exc:
        raise TodoSyncError(_with_filed(str(exc), filed)) from exc
    return replace(result, filed=filed)


#: The URL a dry run gives an issue it would file; the ``.invalid`` host never resolves.
PLACEHOLDER_URL = "https://placeholder.invalid/issues/{}"


def _preview_add(data: Dict[str, Any], specs: Sequence[Any], pending: Sequence[int], day: str,
                 rng: Optional[random.Random] = None) -> Reshape:
    """Validate ``specs`` as written, then add them with a placeholder issue for each index in ``pending``."""
    add_items(data, specs, day, rng)
    named = {s["issue"] for s in specs if isinstance(s, dict) and isinstance(s.get("issue"), int)}
    top = max(catalog_issue_numbers(data) | named, default=0)
    out = list(specs)
    for k, n in enumerate(pending, 1):
        out[n] = {**out[n], "issue": top + k, "url": PLACEHOLDER_URL.format(top + k)}
    return add_items(data, out, day, rng)


def _with_filed(message: str, filed: Sequence[Tuple[int, str]]) -> str:
    """``message`` naming the issues already filed, so a rerun adds them instead of filing them again."""
    if not filed:
        return message
    done = ", ".join(f"#{num} {link}" for num, link in filed)
    return f"{message}; already filed: {done} (add them with issue and url set)"


def _file_pending(cfg: HarnessConfig, specs: Sequence[Any], pending: Sequence[int]
                  ) -> Tuple[List[Any], Tuple[Tuple[int, str], ...]]:
    """``specs`` with an issue filed for each index in ``pending``; a failed filing names the ones done."""
    out, filed = list(specs), []
    for n in pending:
        try:
            number, url = issues.file_issue(cfg, out[n]["title"], issues.issue_body(out[n]))
        except TodoSyncError as exc:
            raise TodoSyncError(_with_filed(str(exc), filed)) from exc
        out[n] = {**out[n], "issue": number, "url": url}
        filed.append((number, url))
    return out, tuple(filed)


def apply_refresh(cfg: HarnessConfig, dry_run: bool = False) -> ReshapeResult:
    """Refresh the project's catalog ranking; only the catalog is written."""
    return _apply(cfg, "refresh", refresh_items, dry_run)


def _apply(cfg: HarnessConfig, verb: str, fn: Callable[[Dict[str, Any]], Reshape],
           dry_run: bool) -> ReshapeResult:
    """Run ``fn`` on the project's catalog (refused while it holds rank-tied ids) and write only the
    catalog unless ``dry_run``; a split also lists the companion lines and other files naming its original
    id, and a failed reference scan lands in ``scan_error``."""
    raw, data = load_catalog(cfg, verb)
    out = fn(data)
    if not dry_run and out.catalog != data:
        write_edits(cfg, dump_like(out.catalog, raw))
    if out.split is None:
        return ReshapeResult(out, out.flagged, ())
    noted = companion_mentions(cfg, {out.split: _split_note(out.split, out.parts)})
    try:
        refs, scan_error = other_references(cfg, [out.split]), None
    except TodoSyncError as exc:
        refs, scan_error = (), str(exc)
    return ReshapeResult(out, (*out.flagged, *noted), refs, scan_error)


#: The line a dry run that draws ids adds: the real run draws its own.
DRAW_NOTE = "note: new ids are drawn at random; the real run draws its own"


def summary_lines(result: ReshapeResult, dry_run: bool) -> List[str]:
    """The driver's report: what was added or split, what moved rank and the prose left for a person."""
    out = result.reshape
    changed = out.split is not None or bool(out.added)
    lines = [_head(out, dry_run, len(out.catalog["items"]), result.pending)]
    lines.extend(f"filed #{number} {url}" for number, url in result.filed)
    if result.to_file:
        lines.append(f"would file {result.to_file} issue(s)")
    if dry_run and changed:
        lines.append(DRAW_NOTE)
    if out.rescored:
        lines.append(f"rescored {len(out.rescored)} item(s): {', '.join(out.rescored)}")
    if out.reranked:
        lines.append(f"re-ranked {len(out.reranked)} item(s): "
                     + ", ".join(f"{item} {old}->{new}" for item, old, new in out.reranked))
    if not changed and not out.rescored and not out.reranked:
        lines.append("nothing changed")
    lines.extend(f"dangling: {note}" for note in result.flagged)
    lines.extend(f"reference (not rewritten): {ref}" for ref in result.references[:REFERENCE_CAP])
    if len(result.references) > REFERENCE_CAP:
        lines.append(f"... {len(result.references) - REFERENCE_CAP} more reference(s)")
    if result.scan_error:
        lines.append(f"reference scan failed: {result.scan_error}")
    if not dry_run and (changed or out.rescored or out.reranked):
        lines.append("next: todo_sync.py render, then todo_sync.py check")
    return lines


def _head(out: Reshape, dry_run: bool, count: int, pending: Tuple[str, ...] = ()) -> str:
    """The first report line: what a split, an add or a refresh did to the catalog; ``pending`` items are
    the ones a dry run would file an issue for."""
    if out.split is not None:
        return f"{'would split' if dry_run else 'split'} {out.split} into {', '.join(out.parts)}; " \
               f"{count} item(s) now"
    if out.added:
        added = ", ".join(f"{item} ({_label(item, issue, pending)})" for item, issue in out.added)
        return f"{'would add' if dry_run else 'added'} {added}; {count} item(s) now"
    return f"{'would refresh' if dry_run else 'refreshed'} {count} item(s)"


def _label(item: str, issue: Optional[int], pending: Tuple[str, ...]) -> str:
    """An added item's source on the head line: an issue to file, its issue number, or ``note``."""
    if item in pending:
        return "issue to file"
    return "note" if issue is None else f"#{issue}"
