"""The one-time switch of a TODO catalog from rank-tied ``TODO-NNN`` ids to stable ``todo-xxxx`` ids.

``migrate_catalog`` is pure: each legacy item draws a stable id (seeded from its old id and title, so two
checkouts of one catalog, and a dry run and its real run, agree), every catalog string outside
``legacy_ids`` is rewritten through the full map (the stored ``legacy_ids.map`` plus the new entries) and the
map is recorded. ``apply_migration`` writes the catalog, then rewrites the live files naming an old id: the
companions plus every file ``git grep`` finds, minus the catalog, its schema, the history folders and the
excluded paths. A rerun on a migrated catalog finishes the job through the stored map.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from harness_lib.config import HarnessConfig
from harness_lib.todo_sync import TodoSyncError
from harness_lib.todo_sync import ids as todo_ids
from harness_lib.todo_sync.report import write_atomic
from harness_lib.todo_sync.retire import (REFERENCE_CAP, companions, dump_like, git_grep, history_paths,
                                          load_catalog, under_any)
from harness_lib.todo_sync.rules_todo import HARNESS_SCHEMA
from harness_lib.todo_sync.sources import posix

#: Catalog lists whose entries are item ids; an old id with no mapping is dropped from them.
LINK_LISTS = frozenset({"depends_on", "unblocks", "child_todo_ids", "related_todo_ids"})
#: ``git grep`` arguments listing every tracked or untracked text file naming a rank-tied id.
GREP_ARGS = ("--untracked", "-l", "-z", "-I", "-E", "TODO-[0-9]{3,}")
SCHEMA_ERROR_CAP = 200
_Pair = Tuple[str, str]


@dataclass(frozen=True)
class Migration:
    """The migrated catalog, the new ``old -> new`` entries, and the catalog strings left naming an old id."""

    catalog: Dict[str, Any]
    mapping: Dict[str, str]
    unmapped: Tuple[str, ...]


@dataclass(frozen=True)
class _Stored:
    """The ``legacy_ids`` record a catalog already holds."""

    migrated: Optional[str]
    map: Dict[str, Any]


def migrate_catalog(catalog: Dict[str, Any], today: str,
                    rng: Optional[random.Random] = None) -> Migration:
    """A copy of ``catalog`` whose legacy item ids are stable, with every string rewritten through the map.

    Raises:
        TodoSyncError: nothing to migrate, duplicate legacy ids, a legacy id already in ``legacy_ids``,
            or a ``legacy_ids`` record that is not an object holding a ``map`` object.
    """
    olds = _legacy_items(catalog)
    stored = _stored(catalog)
    _refuse([old for old, _ in olds], stored)
    known = stored.map if stored else {}
    mapping = _draw(catalog, olds, known, rng)
    full = {**_strings_only(known), **mapping}
    data, unmapped = _rewrite_catalog(catalog, full)
    if "retired_ids" not in data:
        data["retired_ids"] = []
    migrated = stored.migrated if stored and stored.migrated else today
    data["legacy_ids"] = {"migrated": migrated, "map": {**known, **mapping}}
    return Migration(data, mapping, unmapped)


def _legacy_items(catalog: Dict[str, Any]) -> List[Tuple[str, str]]:
    """``(old id, title)`` of each item whose id is a rank-tied ``TODO-NNN``, in item order."""
    items = catalog.get("items")
    rows = items if isinstance(items, list) else []
    return [(i["id"], str(i.get("title") or "")) for i in rows
            if isinstance(i, dict) and isinstance(i.get("id"), str) and todo_ids.LEGACY_RE.fullmatch(i["id"])]


def _stored(catalog: Dict[str, Any]) -> Optional[_Stored]:
    """The stored ``legacy_ids`` record, or None when the catalog holds none."""
    legacy = catalog.get("legacy_ids")
    if legacy is None:
        return None
    mapping = legacy.get("map") if isinstance(legacy, dict) else None
    if not isinstance(mapping, dict):
        raise TodoSyncError("migrate-ids: legacy_ids is not an object holding a map object")
    migrated = legacy.get("migrated")
    return _Stored(migrated if isinstance(migrated, str) else None, mapping)


def _refuse(olds: List[str], stored: Optional[_Stored]) -> None:
    """Raise the first refusal that applies to the legacy ids ``olds`` and the stored record."""
    if not olds and stored is None:
        raise TodoSyncError("nothing to migrate: every item id is already stable")
    counts = Counter(olds)
    dups = list(dict.fromkeys(x for x in olds if counts[x] > 1))
    if dups:
        raise TodoSyncError(f"duplicate legacy id(s): {', '.join(dups)}; give each item its own id first")
    hit = next((x for x in olds if stored and x in stored.map), None)
    if hit is not None:
        date = stored.migrated or "an unrecorded date"
        raise TodoSyncError(f"{hit} is already in legacy_ids (migrated {date}); an older harness may have "
                            "renumbered the catalog: restore it from git")


def _seeded(old: str, title: str) -> random.Random:
    """A generator seeded from the first 8 bytes of ``sha256('<old>\\0<title>')``."""
    digest = hashlib.sha256(f"{old}\0{title}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _draw(catalog: Dict[str, Any], olds: List[Tuple[str, str]], known: Dict[str, Any],
          rng: Optional[random.Random]) -> Dict[str, str]:
    """``old -> new`` for each legacy item, drawn over the live, retired and already mapped ids."""
    taken = todo_ids.taken_ids(catalog) | {v for v in known.values() if isinstance(v, str)}
    mapping: Dict[str, str] = {}
    for old, title in olds:
        new = todo_ids.new_id(taken, rng if rng is not None else _seeded(old, title))
        mapping[old] = new
        taken.add(new)
    return mapping


def _strings_only(known: Dict[str, Any]) -> Dict[str, str]:
    return {k: v for k, v in known.items() if isinstance(k, str) and isinstance(v, str)}


def _swap(text: str, full: Dict[str, str]) -> Tuple[str, int, List[str]]:
    """``text`` with each mapped ``TODO-NNN`` replaced in one pass (no chained renames), the number
    replaced, and the unmapped old ids in order of first appearance."""
    hits: List[str] = []
    missing: List[str] = []

    def one(match: Any) -> str:
        old = match.group(0)
        if old in full:
            hits.append(old)
            return full[old]
        if old not in missing:
            missing.append(old)
        return old

    return todo_ids.LEGACY_RE.sub(one, text), len(hits), missing


def _rewrite_catalog(catalog: Dict[str, Any], full: Dict[str, str]) -> Tuple[Dict[str, Any], Tuple[str, ...]]:
    """A rewritten copy of ``catalog`` (``legacy_ids`` untouched) and the notes on unmapped old ids."""
    notes: List[str] = []
    out: Dict[str, Any] = {}
    for key, value in catalog.items():
        if key == "legacy_ids":
            out[key] = value
        elif key == "items" and isinstance(value, list):
            out[key] = [_item(item, n, full, notes) for n, item in enumerate(value)]
        else:
            out[key] = _field(key, value, key, full, notes)
    return out, tuple(notes)


def _item(item: Any, n: int, full: Dict[str, str], notes: List[str]) -> Any:
    """One rewritten item; its notes read ``items/<new id>/...``."""
    if not isinstance(item, dict):
        return _walk(item, f"items/{n}", full, notes)
    old = item.get("id")
    where = f"items/{full.get(old, old) if isinstance(old, str) else n}"
    return {k: _field(k, v, f"{where}/{k}", full, notes) for k, v in item.items()}


def _field(key: str, value: Any, where: str, full: Dict[str, str], notes: List[str]) -> Any:
    if key in LINK_LISTS and isinstance(value, list):
        return _link_list(value, where, full, notes)
    return _walk(value, where, full, notes)


def _walk(value: Any, where: str, full: Dict[str, str], notes: List[str]) -> Any:
    """A rewritten copy of ``value``; each string keeps an unmapped old id and notes it."""
    if isinstance(value, dict):
        return {k: _field(k, v, f"{where}/{k}", full, notes) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, f"{where}/{n}", full, notes) for n, v in enumerate(value)]
    if not isinstance(value, str):
        return value
    text, _, missing = _swap(value, full)
    notes.extend(f"{where} names {old}, no live item" for old in missing)
    return text


def _link_list(value: List[Any], where: str, full: Dict[str, str], notes: List[str]) -> List[Any]:
    """A link list through ``full``: an old id with no mapping is dropped and noted; a sorted list stays
    sorted."""
    ordered = all(isinstance(x, str) for x in value) and value == sorted(value)
    out: List[Any] = []
    for n, entry in enumerate(value):
        if isinstance(entry, str) and todo_ids.LEGACY_RE.fullmatch(entry) and entry not in full:
            notes.append(f"{where} dropped {entry}, no live item")
        else:
            out.append(_walk(entry, f"{where}/{n}", full, notes))
    return sorted(out) if ordered else out


@dataclass(frozen=True)
class MigrateResult:
    """What ``apply_migration`` changed (or would change) and what it left as written."""

    migration: Migration
    rewritten: Tuple[Tuple[str, int], ...]
    unmapped: Tuple[str, ...]
    skipped: Tuple[Tuple[str, str], ...]
    schema_problem: Optional[str]
    history: Tuple[str, ...] = ()


def apply_migration(cfg: HarnessConfig, dry_run: bool = False, exclude: Iterable[str] = (),
                    today: Optional[str] = None, rng: Optional[random.Random] = None) -> MigrateResult:
    """Migrate the project's catalog and rewrite the live files naming an old id (unless ``dry_run``).

    Raises:
        TodoSyncError: a refusal of ``migrate_catalog``, a failed ``git grep`` (before any write), a
            project catalog schema rejecting the result (real run, before any write), or files not
            written (after the catalog).
    """
    raw, data = load_catalog(cfg, "migrate-ids", stable=False)
    migration = migrate_catalog(data, today or dt.date.today().isoformat(), rng)
    problem = schema_problem(cfg, migration.catalog)
    if problem and not dry_run:
        raise TodoSyncError(problem)
    full = _strings_only(migration.catalog["legacy_ids"]["map"])
    texts, skipped = _read_files(cfg, live_files(cfg, exclude))
    edits: Dict[str, str] = {}
    rewritten: List[Tuple[str, int]] = []
    unmapped: List[str] = []
    for rel, text in texts:
        new, count, missing = _rewrite_text(rel, text, full)
        unmapped.extend(missing)
        if count:
            edits[rel] = new
            rewritten.append((rel, count))
    if not dry_run:
        _write_all(cfg, raw, migration.catalog, edits)
    return MigrateResult(migration, tuple(rewritten), tuple(unmapped), skipped, problem, history_paths(cfg))


def schema_problem(cfg: HarnessConfig, catalog: Dict[str, Any]) -> Optional[str]:
    """Why the project's ``todo.catalog_schema`` (its declared draft, as T1 reads it) rejects ``catalog``;
    None when no project schema is set or it accepts the catalog."""
    rel = cfg.todo.catalog_schema
    if not rel:
        return None
    import jsonschema
    name = posix(rel)
    try:
        schema = json.loads(cfg.path(rel).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) else exc
        return f"{name} is unreadable ({reason}); fix it, then rerun"
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    validator = cls(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(catalog), key=lambda e: [str(p) for p in e.absolute_path])
    if not errors:
        return None
    where = "/".join(str(p) for p in errors[0].absolute_path) or "<root>"
    first = f"{where}: {errors[0].message}"[:SCHEMA_ERROR_CAP]
    return (f"{name} rejects the migrated catalog ({first}); replace it with the harness {HARNESS_SCHEMA} "
            "or update its id pattern, then rerun")


def live_files(cfg: HarnessConfig, exclude: Iterable[str] = ()) -> List[str]:
    """Repo-relative POSIX files to rewrite: the companions plus every file ``git grep`` finds naming a
    ``TODO-NNN``, minus the catalog, its schema, ``history_paths`` and each ``exclude`` (relative to the
    project root, as ``exclude_paths`` returns it; matched by path component: ``vendor`` skips
    ``vendor/x.md``, never ``vendored.md``).

    Raises:
        TodoSyncError: from ``git_grep``.
    """
    found = [name for line in git_grep(cfg, GREP_ARGS) for name in line.split("\0") if name]
    skip = [posix(rel) for rel in (cfg.todo.catalog, cfg.todo.catalog_schema) if rel]
    history = history_paths(cfg)
    excluded = [e for e in (posix(x).rstrip("/") for x in exclude) if e]
    out: List[str] = []
    for rel in (posix(r) for r in (*companions(cfg), *found)):
        if rel in out or rel in skip or under_any(rel, history) or under_any(rel, excluded):
            continue
        out.append(rel)
    return out


def exclude_paths(cfg: HarnessConfig, values: Iterable[str], cwd: Path) -> List[str]:
    """Each ``--exclude`` value (absolute, or relative to ``cwd``) as a POSIX path relative to the project
    root, the form ``live_files`` matches.

    Raises:
        TodoSyncError: a value that names the project root or lies outside it.
    """
    return [_below_root(cfg.project_root, cwd, value) for value in values if value.strip()]


def _below_root(root: Path, cwd: Path, value: str) -> str:
    """``value`` resolved against ``cwd`` and taken relative to ``root``."""
    try:
        rel = os.path.relpath((cwd / posix(value)).resolve(), root.resolve())
    except ValueError:
        rel = os.pardir
    if rel == os.curdir or rel == os.pardir or rel.startswith(os.pardir + os.sep):
        raise TodoSyncError(f"migrate-ids: --exclude {value} is not a path below the project root")
    return posix(rel)


def _read_files(cfg: HarnessConfig, rels: List[str]) -> Tuple[List[_Pair], Tuple[_Pair, ...]]:
    """``(rel, text)`` of each file strictly decoded as UTF-8, and ``(rel, reason)`` of each skipped."""
    texts: List[_Pair] = []
    skipped: List[_Pair] = []
    for rel in rels:
        try:
            texts.append((rel, cfg.path(rel).read_bytes().decode("utf-8")))
        except UnicodeDecodeError:
            skipped.append((rel, "not UTF-8"))
        except OSError as exc:
            skipped.append((rel, f"unreadable: {exc.strerror or type(exc).__name__}"))
    return texts, tuple(skipped)


def _rewrite_text(rel: str, text: str, full: Dict[str, str]) -> Tuple[str, int, List[str]]:
    """``text`` through ``full`` with its line endings kept, the number replaced, and
    ``<rel>:<line> names TODO-NNN`` for each old id left unmapped."""
    lines: List[str] = []
    count = 0
    missing: List[str] = []
    for n, line in enumerate(text.split("\n"), 1):
        new, hits, unmapped = _swap(line, full)
        lines.append(new)
        count += hits
        missing.extend(f"{rel}:{n} names {old}" for old in unmapped)
    return "\n".join(lines), count, missing


def write_file(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` as is."""
    path.write_bytes(data)


def _write_all(cfg: HarnessConfig, raw: str, catalog: Dict[str, Any], edits: Dict[str, str]) -> None:
    """Write the catalog (only when its text changed), then each rewritten file.

    Raises:
        TodoSyncError: ``not written: <rels>; rerun ...`` naming every file a write failed for.
    """
    text = dump_like(catalog, raw)
    if text != raw:
        write_atomic(cfg.path(cfg.todo.catalog), text)
    failed: List[str] = []
    first: Optional[OSError] = None
    for rel, new in edits.items():
        try:
            write_file(cfg.path(rel), new.encode("utf-8"))
        except OSError as exc:
            failed.append(rel)
            first = first or exc
    if failed:
        raise TodoSyncError(f"not written: {', '.join(failed)}; rerun migrate-ids to finish through the "
                            "stored map") from first


def summary_lines(result: MigrateResult, dry_run: bool) -> List[str]:
    """The driver's report: the new ids, the files rewritten, and what was left as written."""
    mapping = result.migration.mapping
    lines = [f"{'would migrate' if dry_run else 'migrated'} {len(mapping)} item(s) to stable ids"]
    lines.extend(f"id {old} -> {new}" for old, new in mapping.items())
    verb = "would rewrite" if dry_run else "rewrote"
    lines.extend(f"{verb} {rel} ({n} reference(s))" for rel, n in result.rewritten)
    unmapped = (*result.migration.unmapped, *result.unmapped)
    lines.extend(f"unmapped: {note}" for note in unmapped[:REFERENCE_CAP])
    if len(unmapped) > REFERENCE_CAP:
        lines.append(f"... {len(unmapped) - REFERENCE_CAP} more unmapped reference(s)")
    lines.extend(f"skipped: {rel} ({reason})" for rel, reason in result.skipped)
    if result.schema_problem:
        lines.append(f"schema: {result.schema_problem}")
    if result.history:
        lines.append(f"history left as written: {', '.join(result.history)}")
    if not dry_run:
        lines.append("next: todo_sync.py render, then todo_sync.py check")
    return lines
