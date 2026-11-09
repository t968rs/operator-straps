"""Retire finished TODO items: drop them from the catalog, record their ids as retired, re-rank the rest.

Item ids are stable (``todo-k7qf``), so retiring renames nothing: the retired ids join ``retired_ids``, which
new draws skip, and the kept items take ranks 1..n in their order. ``retire_items`` is pure: it returns the
new catalog plus the follow-up the catalog cannot record by itself (issues to list as close candidates,
trackers whose prose names the retired work, prose that still names a retired id). ``apply_retirement``
writes only the catalog, then lists the research-catalog and stub lines and the other files that name a
retired id, rewriting none of them.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from harness_lib.config import HarnessConfig
from harness_lib.todo_sync import TodoSyncError
from harness_lib.todo_sync import ids as todo_ids
from harness_lib.todo_sync.ranking import RankingError, expected_order, method_from, score
from harness_lib.todo_sync.report import write_atomic
from harness_lib.todo_sync.rules_todo import catalog_counts
from harness_lib.todo_sync.sources import Sources, posix

#: Top-level catalog records whose strings are ids by design, never prose naming a retired id.
_ID_RECORDS = frozenset({"retired_ids", "legacy_ids", "split_ids"})
GREP_TIMEOUT = 60


@dataclass(frozen=True)
class Retirement:
    """The catalog after retiring items, and the follow-up left to a person."""

    catalog: Dict[str, Any]
    retired: Tuple[Dict[str, Any], ...]
    issues_to_close: Tuple[int, ...]
    trackers_touched: Tuple[int, ...]
    dangling: Tuple[str, ...]


def retire_items(catalog: Dict[str, Any], ids: Iterable[str]) -> Retirement:
    """Remove ``ids`` from a copy of ``catalog`` and record them in ``retired_ids``; unlink, re-rank and
    recount what remains. No other id and no prose string changes.

    Raises:
        TodoSyncError: a catalog holding ``TODO-NNN`` ids, or ``ids`` naming no live item.
    """
    todo_ids.require_stable(catalog, "retire")
    gone = set(todo_ids.resolve_ids(catalog, ids))
    data = copy.deepcopy(catalog)
    items = [i for i in data.get("items") or [] if isinstance(i, dict)]
    retired = tuple(i for i in items if i.get("id") in gone)
    kept = _ordered([i for i in items if i.get("id") not in gone], gone, data.get("ranking_method"))
    _drop_links(data, gone)
    for n, item in enumerate(kept, 1):
        item["rank"] = n
    data["items"] = kept
    retired_ids = [str(i.get("id")) for i in retired]
    _record_retired(data, retired_ids)
    data["counts"] = recount(data.get("counts"), data, retired)
    listed = {c.get("number") for c in data.get("close_candidates") or [] if isinstance(c, dict)}
    issues = {n for i in retired for n in i.get("gh_issues") or []} - listed
    trackers = {i["tracker"] for i in retired if i.get("tracker") is not None}
    return Retirement(data, retired, tuple(sorted(issues)), tuple(sorted(trackers)),
                      tuple(_dangling(data, retired_ids)))


def _ordered(kept: List[Dict[str, Any]], gone: Set[str], method_raw: Any) -> List[Dict[str, Any]]:
    """``kept`` with retired ids unlinked; re-sorted only when an unblock bonus changed a score."""
    rescored = False
    for item in kept:
        item["depends_on"] = [x for x in item.get("depends_on") or [] if x not in gone]
        before = item.get("unblocks") or []
        item["unblocks"] = [x for x in before if x not in gone]
        if bool(before) != bool(item["unblocks"]):
            _rescore(item, method_raw)
            rescored = True
    if not rescored:
        return kept
    by_id = {str(i.get("id")): i for i in kept}
    return [by_id[x] for x in expected_order(kept, method_from(method_raw))]


def _rescore(item: Dict[str, Any], method_raw: Any) -> None:
    try:
        value, components = score(item, method_from(method_raw))
    except RankingError as exc:
        raise TodoSyncError(f"cannot rescore {item.get('id')}: {exc}") from exc
    item["priority"] = {"score": value, "components": components}


def _drop_links(data: Dict[str, Any], gone: Set[str]) -> None:
    for key, field in (("trackers", "child_todo_ids"), ("close_candidates", "related_todo_ids")):
        for record in data.get(key) or []:
            if isinstance(record, dict) and isinstance(record.get(field), list):
                record[field] = [x for x in record[field] if x not in gone]


def _record_retired(data: Dict[str, Any], retired_ids: Sequence[str]) -> None:
    """Append ``retired_ids`` to ``data['retired_ids']`` (created when absent), skipping ids already there."""
    stored = data.get("retired_ids")
    if stored is not None and not isinstance(stored, list):
        raise TodoSyncError("retire: retired_ids is not a list")
    record = list(stored or [])
    record.extend(x for x in retired_ids if x not in record)
    data["retired_ids"] = record


def _dangling(data: Dict[str, Any], gone: Sequence[str]) -> List[str]:
    """``<json path> names retired <id>`` for each catalog string naming a ``gone`` id (``mention_paths``)."""
    return mention_paths(data, gone, lambda hit: f"names retired {hit}")


def mention_paths(data: Dict[str, Any], ids: Sequence[str], note: Callable[[str], str]) -> List[str]:
    """``<json path> <note(id)>`` for each catalog string naming one of ``ids`` in any case; item paths read
    ``items/<id>/...`` and the id records (``_ID_RECORDS``) are skipped."""
    found: List[str] = []

    def scan(text: str, where: str) -> str:
        found.extend(f"{where} {note(hit)}" for hit in todo_ids.mentions(text, ids))
        return text

    for key, value in data.items():
        if key == "items":
            for item in value:
                walk_strings(item, f"items/{item.get('id')}", scan)
        elif key not in _ID_RECORDS:
            walk_strings(value, key, scan)
    return found


def walk_strings(obj: Any, where: str, sub: Callable[[str, str], str]) -> Any:
    """A copy of ``obj`` with every string passed through ``sub(text, json_path)``."""
    if isinstance(obj, dict):
        return {k: walk_strings(v, f"{where}/{k}", sub) for k, v in obj.items()}
    if isinstance(obj, list):
        return [walk_strings(v, f"{where}/{n}", sub) for n, v in enumerate(obj)]
    return sub(obj, where) if isinstance(obj, str) else obj


def recount(stored: Any, data: Dict[str, Any], retired: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """``counts`` retallied; the untallied ``sources_absorbed`` and ``merged_items`` lose the retired
    items."""
    out = dict(stored) if isinstance(stored, dict) else {}
    for key, value in catalog_counts(data).items():
        out[key] = _merge_tally(out.get(key), value) if isinstance(value, dict) else value
    absorbed = out.get("sources_absorbed")
    if isinstance(absorbed, dict):
        for source in (s for i in retired for s in i.get("sources") or [] if isinstance(s, dict)):
            if isinstance(absorbed.get(source.get("type")), int):
                absorbed[source["type"]] = max(0, absorbed[source["type"]] - 1)
    if isinstance(out.get("merged_items"), int):
        merged = sum(1 for i in retired if len(i.get("sources") or []) > 1)
        out["merged_items"] = max(0, out["merged_items"] - merged)
    return out


def _merge_tally(old: Any, new: Dict[str, int]) -> Dict[str, int]:
    """``new`` in ``old``'s key order; every stored key stays, at zero when no item has it (the schema
    requires each ``by_loe`` size)."""
    old = old if isinstance(old, dict) else {}
    merged = {k: new.get(k, 0) for k in old}
    merged.update({k: new[k] for k in sorted(new) if k not in merged})
    return merged


@dataclass(frozen=True)
class RetireResult:
    """What ``apply_retirement`` changed (or would change) and what it left for a person."""

    retirement: Retirement
    remaining: int
    dangling: Tuple[str, ...]
    references: Tuple[str, ...]
    scan_error: Optional[str] = None


def apply_retirement(cfg: HarnessConfig, ids: Iterable[str], dry_run: bool = False) -> RetireResult:
    """Retire ``ids`` in the project's catalog and write it (unless ``dry_run``), then list the companion
    lines and other files still naming a retired id; nothing but the catalog is written."""
    raw, data = load_catalog(cfg, "retire")
    out = retire_items(data, ids)
    gone = [str(i.get("id")) for i in out.retired]
    if not dry_run:
        write_edits(cfg, dump_like(out.catalog, raw))
    try:
        refs, scan_error = other_references(cfg, gone), None
    except TodoSyncError as exc:
        refs, scan_error = (), str(exc)
    noted = companion_mentions(cfg, {x: f"names retired {x}" for x in gone})
    return RetireResult(out, len(out.catalog["items"]), (*out.dangling, *noted), refs, scan_error)


def load_catalog(cfg: HarnessConfig, verb: str, stable: bool = True) -> Tuple[str, Dict[str, Any]]:
    """``(raw text, parsed object)`` of the project's catalog; ``verb`` names the caller in errors.

    Raises:
        TodoSyncError: no catalog configured, an unparseable file, a top level that is not an object, or
            (with ``stable``) a catalog still holding ``TODO-NNN`` ids.
    """
    if not cfg.todo.catalog:
        raise TodoSyncError(f"{verb} needs todo.folder")
    try:
        raw = cfg.path(cfg.todo.catalog).read_bytes().decode("utf-8")
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TodoSyncError(f"{posix(cfg.todo.catalog)}: unparseable: {exc}") from exc
    if not isinstance(data, dict):
        raise TodoSyncError(f"{posix(cfg.todo.catalog)}: top level is not an object")
    if stable:
        todo_ids.require_stable(data, verb)
    return raw, data


def write_edits(cfg: HarnessConfig, catalog_text: str) -> None:
    """Write the catalog atomically."""
    write_atomic(cfg.path(cfg.todo.catalog), catalog_text)


def history_paths(cfg: HarnessConfig) -> Tuple[str, ...]:
    """Repo-relative POSIX folders, without a trailing ``/``, whose files are history the reference scans
    skip: plans, reviews, commit messages, summaries, scratch, each planning prefix and the snapshots."""
    art = cfg.artifacts
    out: List[str] = []
    for rel in (art.plans, art.reviews, art.commit_messages, art.summaries, art.scratch,
                *art.planning_prefixes, cfg.todo.snapshots.dir):
        path = posix(rel).rstrip("/") if rel else ""
        if path and path not in out:
            out.append(path)
    return tuple(out)


def git_grep(cfg: HarnessConfig, args: Sequence[str]) -> Tuple[str, ...]:
    """Stdout lines of ``git -C <project root> grep <args>``; exit 1 (no match) gives ``()``.

    Raises:
        TodoSyncError: ``git grep failed: <reason>`` on an OSError, a timeout or an exit of 2 or more.
    """
    argv = ["git", "-C", str(cfg.project_root), "grep", *args]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=GREP_TIMEOUT)
    except OSError as exc:
        raise TodoSyncError(f"git grep failed: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TodoSyncError(f"git grep failed: timed out after {GREP_TIMEOUT} s") from exc
    if done.returncode == 1:
        return ()
    if done.returncode != 0:
        first = next((line.strip() for line in done.stderr.splitlines() if line.strip()), "")
        raise TodoSyncError(f"git grep failed: {first or f'exit {done.returncode}'}")
    return tuple(done.stdout.splitlines())


def other_references(cfg: HarnessConfig, ids: Sequence[str]) -> Tuple[str, ...]:
    """``path:line:text`` of tracked or untracked files naming any of ``ids`` (any case, whole word) outside
    the catalog, its companions and ``history_paths``; ``()`` when ``ids`` is empty or the project root
    holds no ``.git``.

    The skipped paths are dropped here rather than passed as exclude pathspecs, which overrun the Windows
    command line once the list grows.

    Raises:
        TodoSyncError: from ``git_grep``.
    """
    wanted = list(ids)
    if not wanted or not (cfg.project_root / ".git").exists():
        return ()
    patterns = [arg for x in wanted for arg in ("-e", x)]
    lines = git_grep(cfg, ["--untracked", "-n", "-I", "-i", "-F", "-w", *patterns])
    skip = [posix(rel) for rel in (cfg.todo.catalog, *companions(cfg)) if rel] + list(history_paths(cfg))
    return tuple(line.strip() for line in lines if not under_any(line.partition(":")[0], skip))


def under_any(path: str, roots: Iterable[str]) -> bool:
    """True when ``path`` is one of ``roots`` or lies inside one."""
    return any(path == root or path.startswith(root + "/") for root in roots)


def dump_like(data: Dict[str, Any], raw: str) -> str:
    """``data`` as JSON in ``raw``'s style: indent width, ASCII escaping, line ending, final newline."""
    found = re.search(r"\n( +)\S", raw)
    indent = len(found.group(1)) if found else 2
    text = json.dumps(data, indent=indent, ensure_ascii=raw.isascii() and "\\u" in raw)
    if raw.endswith("\n"):
        text += "\n"
    return text.replace("\n", "\r\n") if "\r\n" in raw else text


def companions(cfg: HarnessConfig) -> List[str]:
    """Repo-relative companion files of the catalog: the research catalog and the stubs, scanned for mentions
    of a retired or split id (and rewritten only by migrate-ids)."""
    rels: List[str] = []
    research = cfg.todo.research.catalog
    if research and cfg.path(research).is_file():
        rels.append(posix(research))
    src = Sources(cfg)
    if cfg.todo.stub_name and src.research_root.is_dir():
        rels.extend(src.stub_files())
    return rels


def companion_mentions(cfg: HarnessConfig, notes: Dict[str, str]) -> List[str]:
    """``<rel>:<line> <note>`` for each research-catalog or stub line naming an id in ``notes`` (any case);
    nothing is rewritten."""
    found: List[str] = []
    for rel in companions(cfg):
        text = cfg.path(rel).read_bytes().decode("utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            found.extend(f"{rel}:{n} {notes[hit]}" for hit in todo_ids.mentions(line, notes))
    return found


REFERENCE_CAP = 30


def summary_lines(result: RetireResult, dry_run: bool) -> List[str]:
    """The driver's report: what was retired and the follow-up left to a person."""
    out = result.retirement
    ids = ", ".join(str(i.get("id")) for i in out.retired)
    lines = [f"{'would retire' if dry_run else 'retired'} {ids}; {result.remaining} item(s) remain"]
    lines.extend(f"issue #{n}: a retired item resolves it; add a close_candidates entry with evidence"
                 for n in out.issues_to_close)
    lines.extend(f"tracker #{n}: lost child items; revisit status_note and recommended_action"
                 for n in out.trackers_touched)
    lines.extend(f"dangling: {note}" for note in result.dangling)
    lines.extend(f"reference (not rewritten): {ref}" for ref in result.references[:REFERENCE_CAP])
    if len(result.references) > REFERENCE_CAP:
        lines.append(f"... {len(result.references) - REFERENCE_CAP} more reference(s)")
    if result.scan_error:
        lines.append(f"reference scan failed: {result.scan_error}")
    if not dry_run:
        lines.append("next: todo_sync.py render, then todo_sync.py check")
    return lines
