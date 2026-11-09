"""TODO catalog rules T1-T10: schema, snapshot freshness, cross-catalog links and cross-record rules.

T4 checks only the catalog-link half of the design rule (every non-terminal research entry is referenced
by an item); its issue-cache half needs the cache ``fetch`` writes and is not evaluated yet.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Set

from harness_lib.project import schema_path
from harness_lib.todo_sync.ids import LEGACY_RE, MIGRATE_HINT, is_legacy
from harness_lib.todo_sync.ranking import RankingError, expected_order, method_from, score
from harness_lib.todo_sync.report import Finding
from harness_lib.todo_sync.sources import TERMINAL_RESEARCH, Sources, posix, rows_sha256

CAP = 20
TOLERANCE = 5e-5
HARNESS_SCHEMA = "catalogs/TodoCatalog.schema.json"
COMPONENTS = ("impact_weight", "value", "loe_points", "blast_factor", "cost", "base_score", "unblock_bonus")


def capped(findings: List[Finding], rule: str, file: Optional[str]) -> List[Finding]:
    """The first ``CAP`` findings plus one ``N more`` finding."""
    if len(findings) <= CAP:
        return findings
    more = Finding(rule, findings[CAP].severity, file, f"{len(findings) - CAP} more finding(s) not listed")
    return findings[:CAP] + [more]


def _schema(src: Sources) -> Any:
    rel = src.cfg.todo.catalog_schema
    path = src.cfg.path(rel) if rel else schema_path(HARNESS_SCHEMA, src.cfg)
    return json.loads(path.read_text(encoding="utf-8"))


def _subject(src: Sources, path: List[Any]) -> Optional[str]:
    if len(path) >= 2 and path[0] == "items" and isinstance(path[1], int):
        items = src.todo.data.get("items") or []
        if path[1] < len(items) and isinstance(items[path[1]], dict):
            return str(items[path[1]].get("id"))
    return None


def _legacy_id_error(error: Any) -> bool:
    """True for a ``pattern`` error on a rank-tied ``TODO-NNN`` id."""
    return error.validator == "pattern" and isinstance(error.instance, str) \
        and LEGACY_RE.fullmatch(error.instance) is not None


def t1_schema(src: Sources) -> List[Finding]:
    """T1: the catalog validates against ``todo.catalog_schema`` (else the harness TodoCatalog schema).

    On a catalog that still holds ``TODO-NNN`` item ids, the pattern errors those ids raise are left to T6,
    which reports the whole catalog once.
    """
    import jsonschema
    rel = src.todo.rel
    try:
        schema = _schema(src)
    except (OSError, ValueError) as exc:
        if src.cfg.todo.catalog_schema:
            return [Finding("T1", "error", posix(src.cfg.todo.catalog_schema),
                            f"catalog schema unreadable: {exc}")]
        return [Finding("T1", "error", None, f"harness schema {HARNESS_SCHEMA} unreadable: {exc}")]
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    validator = cls(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(src.todo.data), key=lambda e: [str(p) for p in e.absolute_path])
    if isinstance(src.todo.data, dict) and is_legacy(src.todo.data):
        errors = [e for e in errors if not _legacy_id_error(e)]
    out = [Finding("T1", "error", rel, f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: "
                   f"{e.message[:200]}", subject=_subject(src, list(e.absolute_path)),
                   fix="Make the catalog match its schema.") for e in errors]
    return capped(out, "T1", rel)


def t2_snapshot(src: Sources) -> List[Finding]:
    """T2 (warn): the newest snapshot's header hash equals the hash of the current top-N rows.

    Catalog-side drift only (D10): the table body under the header is never compared.
    """
    folder = posix(src.cfg.todo.snapshots.dir)
    snap = src.snapshot()
    fix = "Run todo_sync.py render."
    if snap is None:
        return [Finding("T2", "warn", folder, "no snapshot matching todo.snapshots.name_pattern", fix=fix)]
    if snap.header is None:
        return [Finding("T2", "warn", snap.rel, "snapshot not produced by render (no header)", line=1,
                        fix=fix)]
    top_n = src.cfg.todo.top_n
    if snap.header.top == top_n and snap.header.rows_sha256 == rows_sha256(src.items(), top_n):
        return []
    return [Finding("T2", "warn", snap.rel, f"top {top_n} rows changed since the snapshot "
                    f"rendered {snap.header.rendered}", line=1, fix=fix)]


def _entry_ids(src: Sources) -> Dict[str, Dict[str, Any]]:
    return {str(e.get("id")): e for e in src.entries()}


def t3_links_resolve(src: Sources) -> List[Finding]:
    """T3: ``catalog_entry_ids`` resolve in the research catalog; stub and folder sources exist."""
    known, out = _entry_ids(src), []
    for item in src.items():
        item_id = str(item.get("id"))
        for entry_id in item.get("catalog_entry_ids") or []:
            if entry_id not in known:
                out.append(Finding("T3", "error", src.todo.rel, f"catalog entry {entry_id} not in "
                                   f"{src.research.rel}", subject=item_id, fix="Fix or drop the entry id."))
        for source in item.get("sources") or []:
            if not isinstance(source, dict):
                continue
            ref = source.get("ref")
            if source.get("type") in ("research_folder", "impl_stub") and isinstance(ref, str):
                if not src.cfg.path(ref).exists():
                    out.append(Finding("T3", "error", src.todo.rel, f"{source['type']} source {ref} does "
                                       "not exist", subject=item_id, fix="Repoint the source ref."))
    return out


def t4_entries_referenced(src: Sources) -> List[Finding]:
    """T4 (warn): every non-terminal research entry is referenced by some item's ``catalog_entry_ids``."""
    cited = {str(e) for item in src.items() for e in item.get("catalog_entry_ids") or []}
    return [Finding("T4", "warn", src.research.rel, f"{e.get('status')} entry referenced by no TODO item",
                    subject=str(e.get("id")), fix="Add a TODO item citing it, or update its status.")
            for e in src.entries()
            if e.get("status") not in TERMINAL_RESEARCH and str(e.get("id")) not in cited]


def t5_live_entries(src: Sources) -> List[Finding]:
    """T5: an item does not reference only terminal research entries."""
    known, out = _entry_ids(src), []
    for item in src.items():
        resolved = [known[e] for e in item.get("catalog_entry_ids") or [] if e in known]
        if resolved and all(e.get("status") in TERMINAL_RESEARCH for e in resolved):
            ids = ", ".join(str(e.get("id")) for e in resolved)
            out.append(Finding("T5", "error", src.todo.rel,
                               f"references only terminal research entries ({ids})",
                               subject=str(item.get("id")), fix="Remove the item, or reopen the entry."))
    return out


def _catalog(src: Sources) -> Dict[str, Any]:
    return src.todo.data if isinstance(src.todo.data, dict) else {}


def _retired(src: Sources) -> Set[str]:
    raw = _catalog(src).get("retired_ids")
    return {r for r in raw if isinstance(r, str)} if isinstance(raw, list) else set()


def _duplicate_ids(src: Sources) -> List[Finding]:
    return [Finding("T6", "error", src.todo.rel, f"id {item_id} appears {n} times", subject=item_id)
            for item_id, n in Counter(str(i.get("id")) for i in src.items()).items() if n > 1]


def _retired_items(src: Sources, retired: Set[str]) -> List[Finding]:
    return [Finding("T6", "error", src.todo.rel, f"id {item_id} is in retired_ids", subject=item_id,
                    fix="Drop the id from retired_ids, or give the item a new id.")
            for item_id in (str(i.get("id")) for i in src.items()) if item_id in retired]


def _split_records(src: Sources, retired: Set[str]) -> List[Finding]:
    """Every ``split_ids`` key is retired; every part it names is a live item or retired."""
    raw, rel = _catalog(src).get("split_ids"), src.todo.rel
    live, out = {str(i.get("id")) for i in src.items()}, []
    for split_id, parts in (raw.items() if isinstance(raw, dict) else ()):
        if split_id not in retired:
            out.append(Finding("T6", "error", rel, f"split id {split_id} is not in retired_ids",
                               subject=split_id, fix="Add the split id to retired_ids."))
        for part in parts if isinstance(parts, list) else ():
            if part not in live and part not in retired:
                out.append(Finding("T6", "error", rel, f"split id {split_id} names part {part}, neither an "
                                   "item nor retired", subject=split_id,
                                   fix="Fix the part id, or add it to retired_ids."))
    return out


def _legacy_orphans(src: Sources, retired: Set[str]) -> List[Finding]:
    """Every ``legacy_ids`` map value is a live item or retired, so no draw can reuse a migrated id."""
    legacy = _catalog(src).get("legacy_ids")
    mapping = legacy.get("map") if isinstance(legacy, dict) else None
    if not isinstance(mapping, dict):
        return []
    live = {str(i.get("id")) for i in src.items()}
    return [Finding("T6", "error", src.todo.rel,
                    f"legacy id {old} maps to {new}, neither an item nor retired", subject=new,
                    fix="Restore the item, or add the id to retired_ids.")
            for old, new in mapping.items() if isinstance(new, str) and new not in live | retired]


def _rank_order(src: Sources) -> List[Finding]:
    return [Finding("T6", "error", src.todo.rel, f"rank {item.get('rank')} at position {pos}",
                    subject=str(item.get("id")), fix="Set ranks 1..n in item order.")
            for pos, item in enumerate(src.items(), 1) if item.get("rank") != pos]


def t6_ids_and_ranks(src: Sources) -> List[Finding]:
    """T6: ids are unique and not retired, ``split_ids`` and ``legacy_ids`` records hold, ranks run 1..n.

    A catalog that still holds rank-tied ``TODO-NNN`` ids gets one finding naming ``migrate-ids``, plus
    its duplicate-id findings, which ``migrate-ids`` needs cleared first.
    """
    rel = src.todo.rel
    if is_legacy(_catalog(src)):
        legacy = Finding("T6", "error", rel, MIGRATE_HINT,
                         fix="Run todo_sync.py migrate-ids --dry-run, then without --dry-run.")
        return capped([legacy] + _duplicate_ids(src), "T6", rel)
    retired = _retired(src)
    out = (_duplicate_ids(src) + _retired_items(src, retired) + _split_records(src, retired)
           + _legacy_orphans(src, retired) + _rank_order(src))
    return capped(out, "T6", rel)


def _inverse(src: Sources, item: Dict[str, Any], field: str, back: str,
             by_id: Dict[str, Dict[str, Any]]) -> Iterable[Finding]:
    item_id = str(item.get("id"))
    for other in item.get(field) or []:
        if other not in by_id:
            yield Finding("T7", "error", src.todo.rel, f"{field} names unknown id {other}", subject=item_id)
        elif item_id not in (by_id[other].get(back) or []):
            yield Finding("T7", "error", src.todo.rel, f"{field} has {other}, but {other}.{back} lacks "
                          f"{item_id}", subject=item_id, fix=f"Add {item_id} to {other}.{back}.")


def t7_dependencies(src: Sources) -> List[Finding]:
    """T7: ``depends_on`` and ``unblocks`` are mutual inverses naming existing ids."""
    by_id = {str(i.get("id")): i for i in src.items()}
    pairs = (("depends_on", "unblocks"), ("unblocks", "depends_on"))
    return [f for item in src.items() for field, back in pairs
            for f in _inverse(src, item, field, back, by_id)]


def _trackers(src: Sources) -> List[Dict[str, Any]]:
    return [t for t in src.todo.data.get("trackers") or [] if isinstance(t, dict)]


def t8_trackers(src: Sources) -> List[Finding]:
    """T8: an item's ``tracker`` is a ``trackers[].number``; ``child_todo_ids`` lists exactly its items."""
    rel, numbers = src.todo.rel, {t.get("number") for t in _trackers(src)}
    out = [Finding("T8", "error", rel, f"tracker #{i['tracker']} is not in trackers[]",
                   subject=str(i.get("id")), fix="Add the tracker, or clear the item's tracker.")
           for i in src.items() if i.get("tracker") is not None and i.get("tracker") not in numbers]
    for tracker in _trackers(src):
        pointing = {str(i.get("id")) for i in src.items() if i.get("tracker") == tracker.get("number")}
        listed: Set[str] = set(tracker.get("child_todo_ids") or [])
        if listed != pointing:
            out.append(Finding("T8", "error", rel, f"child_todo_ids {sorted(listed)} but items pointing at "
                               f"it are {sorted(pointing)}", subject=f"#{tracker.get('number')}",
                               fix="Set child_todo_ids to the items whose tracker is this number."))
    return out


def _tally(values: Iterable[Any]) -> Dict[str, int]:
    return {str(k): n for k, n in Counter(values).items() if n}


def _nonzero(raw: Any) -> Any:
    return {k: v for k, v in raw.items() if v} if isinstance(raw, dict) else raw


def catalog_counts(data: Dict[str, Any]) -> Dict[str, Any]:
    """The ``counts`` values T9 checks, tallied from the catalog ``data`` (zero tallies omitted)."""
    items = [i for i in data.get("items") or [] if isinstance(i, dict)]
    return {
        "items": len(items), "needs_decision": sum(1 for i in items if i.get("needs_decision")),
        "trackers": len(data.get("trackers") or []),
        "close_candidates": len(data.get("close_candidates") or []),
        "by_status": _tally(i.get("status") for i in items),
        "by_impact": _tally(i.get("impact") for i in items),
        "by_loe": _tally((i.get("loe") or {}).get("size") for i in items),
    }


def t9_counts(src: Sources) -> List[Finding]:
    """T9: ``counts`` tally the items (``sources_absorbed`` and ``merged_items`` are not checked)."""
    data = src.todo.data
    want = catalog_counts(data)
    stored = data.get("counts") or {}
    return [Finding("T9", "error", src.todo.rel,
                    f"counts.{key} is {stored.get(key)!r}, items tally {value!r}",
                    subject=f"counts.{key}", fix="Recompute counts from the items.")
            for key, value in want.items() if _nonzero(stored.get(key)) != _nonzero(value)]


def _score_drift(item: Dict[str, Any], method: Any) -> List[str]:
    value, components = score(item, method)
    priority = item.get("priority") or {}
    stored = priority.get("components") or {}
    drift = [] if _close(priority.get("score"), value) else [f"score {priority.get('score')} != {value}"]
    return drift + [f"{k} {stored.get(k)} != {components[k]}" for k in COMPONENTS
                    if not _close(stored.get(k), components[k])]


def _close(stored: Any, value: float) -> bool:
    return isinstance(stored, (int, float)) and abs(stored - value) <= TOLERANCE


def _t10_scores(src: Sources, method: Any) -> List[Finding]:
    out = []
    for item in src.items():
        try:
            drift = _score_drift(item, method)
        except (RankingError, TypeError, KeyError, ValueError, ZeroDivisionError) as exc:
            drift = [f"cannot score: {exc}"]
        if drift:
            out.append(Finding("T10", "error", src.todo.rel, "priority differs from ranking_method: "
                               + "; ".join(drift), subject=str(item.get("id")),
                               fix="Recompute priority from ranking_method."))
    return out


def _stored_ranks(items: List[Dict[str, Any]]) -> Dict[str, List[Any]]:
    """Stored ranks per ``str`` id, in item order; a duplicated id keeps one rank per copy."""
    queues: Dict[str, List[Any]] = {}
    for item in items:
        queues.setdefault(str(item.get("id")), []).append(item.get("rank"))
    return queues


def _t10_ranks(src: Sources, method: Any) -> List[Finding]:
    queues, out = _stored_ranks(src.items()), []
    for pos, item_id in enumerate(expected_order(src.items(), method), 1):
        rank = queues[item_id].pop(0)
        if rank != pos:
            msg = f"rank {rank}, recomputed order puts it at {pos}"
            out.append(Finding("T10", "error", src.todo.rel, msg, subject=item_id,
                               fix="Re-rank the items by score and tie breakers."))
    return out


def t10_ranking(src: Sources) -> List[Finding]:
    """T10: ``priority`` and ``rank`` equal what ``ranking_method`` recomputes from the item fields."""
    try:
        method = method_from(src.todo.data.get("ranking_method"))
    except (RankingError, TypeError, ValueError) as exc:
        return [Finding("T10", "error", src.todo.rel, str(exc), fix="Restore the ranking_method tables.")]
    scores = _t10_scores(src, method)
    if any(f.message.startswith("priority differs from ranking_method: cannot score") for f in scores):
        return capped(scores, "T10", src.todo.rel)
    return capped(scores + _t10_ranks(src, method), "T10", src.todo.rel)
