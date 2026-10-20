"""Retire finished TODO items: drop them from the catalog, renumber the rest, rewrite every id that moved.

Rule T6 ties each id to its rank (``TODO-<rank>``, ranks 1..n), so removing an item renames every item
ranked below it. ``retire_items`` is pure: it returns the new catalog plus the follow-up the catalog cannot
record by itself (issues to list as close candidates, trackers whose prose names the retired work, prose
that still names a retired id). ``apply_retirement`` writes the catalog, rewrites moved ids in the research
catalog and the stubs, and lists other files that name a TODO id without touching them.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Sequence, Set, Tuple

from harness_lib.config import HarnessConfig
from harness_lib.todo_sync import TodoSyncError
from harness_lib.todo_sync.ranking import RankingError, expected_order, method_from, score
from harness_lib.todo_sync.report import write_atomic
from harness_lib.todo_sync.rules_todo import catalog_counts
from harness_lib.todo_sync.sources import Sources, posix

ID_RE = re.compile(r"\bTODO-\d{3,}\b")
_SHORT = re.compile(r"(?i)(?:TODO-)?0*([1-9]\d*)")


def todo_id(rank: int) -> str:
    """The id T6 expects at ``rank``."""
    return f"TODO-{rank:03d}"


def normalize_id(raw: str) -> str:
    """``TODO-007`` from ``TODO-007``, ``todo-7``, ``007`` or ``7``."""
    match = _SHORT.fullmatch(raw.strip())
    if not match:
        raise TodoSyncError(f"not a TODO id: {raw!r} (use TODO-007, 007 or 7)")
    return todo_id(int(match.group(1)))


@dataclass(frozen=True)
class Retirement:
    """The catalog after retiring items, and the follow-up left to a person."""

    catalog: Dict[str, Any]
    retired: Tuple[Dict[str, Any], ...]
    renames: Dict[str, str]
    issues_to_close: Tuple[int, ...]
    trackers_touched: Tuple[int, ...]
    dangling: Tuple[str, ...]


def retire_items(catalog: Dict[str, Any], ids: Iterable[str]) -> Retirement:
    """Remove ``ids`` from a copy of ``catalog`` and renumber, relink and recount what remains."""
    data = copy.deepcopy(catalog)
    items = [i for i in data.get("items") or [] if isinstance(i, dict)]
    gone = _resolve(items, ids)
    retired = tuple(i for i in items if i.get("id") in gone)
    kept = _ordered([i for i in items if i.get("id") not in gone], gone, data.get("ranking_method"))
    moved = {str(i.get("id")): todo_id(n) for n, i in enumerate(kept, 1)}
    _drop_links(data, gone)
    data["items"] = kept
    dangling: List[str] = []
    data = _rewrite_catalog(data, moved, gone, dangling)
    for n, item in enumerate(data["items"], 1):
        item["rank"] = n
    data["counts"] = _counts(data.get("counts"), data, retired)
    listed = {c.get("number") for c in data.get("close_candidates") or [] if isinstance(c, dict)}
    issues = {n for i in retired for n in i.get("gh_issues") or []} - listed
    trackers = {i["tracker"] for i in retired if i.get("tracker") is not None}
    return Retirement(data, retired, {o: n for o, n in moved.items() if o != n}, tuple(sorted(issues)),
                      tuple(sorted(trackers)), tuple(dangling))


def _resolve(items: List[Dict[str, Any]], ids: Iterable[str]) -> Set[str]:
    wanted = {normalize_id(raw) for raw in ids}
    if not wanted:
        raise TodoSyncError("name at least one TODO id to retire")
    unknown = sorted(wanted - {str(i.get("id")) for i in items})
    if unknown:
        raise TodoSyncError(f"no such item(s) in the catalog: {', '.join(unknown)}")
    return wanted


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


def _rewrite_catalog(data: Dict[str, Any], moved: Dict[str, str], gone: Set[str],
                     dangling: List[str]) -> Dict[str, Any]:
    """Every string of ``data`` with moved ids renamed; retired ids are left and noted in ``dangling``."""
    def sub(text: str, where: str) -> str:
        for hit in sorted({m for m in ID_RE.findall(text) if m in gone}):
            dangling.append(f"{where} names retired {hit}")
        return remap_text(text, moved)

    out: Dict[str, Any] = {}
    for key, value in data.items():
        if key == "items":
            out[key] = [_walk(item, f"items/{todo_id(n)}", sub) for n, item in enumerate(value, 1)]
        else:
            out[key] = _walk(value, key, sub)
    return out


def _walk(obj: Any, where: str, sub: Callable[[str, str], str]) -> Any:
    if isinstance(obj, dict):
        return {k: _walk(v, f"{where}/{k}", sub) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v, f"{where}/{n}", sub) for n, v in enumerate(obj)]
    return sub(obj, where) if isinstance(obj, str) else obj


def remap_text(text: str, renames: Dict[str, str]) -> str:
    """``text`` with each TODO id in ``renames`` replaced in one pass (no chained renames)."""
    return ID_RE.sub(lambda m: renames.get(m.group(0), m.group(0)), text)


def _counts(stored: Any, data: Dict[str, Any], retired: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """``counts`` retallied; the untallied ``sources_absorbed`` and ``merged_items`` lose the retired items."""
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
    rewritten: Tuple[str, ...]
    dangling: Tuple[str, ...]
    references: Tuple[str, ...]


def apply_retirement(cfg: HarnessConfig, ids: Iterable[str], dry_run: bool = False) -> RetireResult:
    """Retire ``ids`` in the project's catalog and rewrite moved ids in the research catalog and stubs."""
    if not cfg.todo.catalog:
        raise TodoSyncError("retire needs todo.folder")
    catalog_path = cfg.path(cfg.todo.catalog)
    try:
        raw = catalog_path.read_bytes().decode("utf-8")
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TodoSyncError(f"{posix(cfg.todo.catalog)}: unparseable: {exc}") from exc
    if not isinstance(data, dict):
        raise TodoSyncError(f"{posix(cfg.todo.catalog)}: top level is not an object")
    out = retire_items(data, ids)
    edits, dangling = _companion_edits(cfg, out)
    if not dry_run:
        write_atomic(catalog_path, dump_like(out.catalog, raw))
        for rel, text in edits.items():
            cfg.path(rel).write_bytes(text.encode("utf-8"))
    skip = [posix(cfg.todo.catalog), *edits, *_companions(cfg)]
    if cfg.todo.snapshots.dir:
        skip.append(posix(cfg.todo.snapshots.dir))
    refs = _references(cfg, skip) if out.renames else ()
    return RetireResult(out, len(out.catalog["items"]), tuple(edits), (*out.dangling, *dangling), refs)


def dump_like(data: Dict[str, Any], raw: str) -> str:
    """``data`` as JSON in ``raw``'s style: indent width, ASCII escaping, line ending, final newline."""
    found = re.search(r"\n( +)\S", raw)
    indent = len(found.group(1)) if found else 2
    text = json.dumps(data, indent=indent, ensure_ascii=raw.isascii() and "\\u" in raw)
    if raw.endswith("\n"):
        text += "\n"
    return text.replace("\n", "\r\n") if "\r\n" in raw else text


def _companions(cfg: HarnessConfig) -> List[str]:
    """Repo-relative files whose TODO ids follow the catalog: the research catalog and the stubs."""
    rels: List[str] = []
    research = cfg.todo.research.catalog
    if research and cfg.path(research).is_file():
        rels.append(posix(research))
    src = Sources(cfg)
    if cfg.todo.stub_name and src.research_root.is_dir():
        rels.extend(src.stub_files())
    return rels


def _companion_edits(cfg: HarnessConfig, out: Retirement) -> Tuple[Dict[str, str], List[str]]:
    """``(rel -> rewritten text, dangling notes)`` for the companions whose ids move."""
    gone = {str(i.get("id")) for i in out.retired}
    edits: Dict[str, str] = {}
    dangling: List[str] = []
    for rel in _companions(cfg):
        text = cfg.path(rel).read_bytes().decode("utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            dangling.extend(f"{rel}:{n} names retired {hit}" for hit in sorted(set(ID_RE.findall(line)) & gone))
        new = remap_text(text, out.renames)
        if new != text:
            edits[rel] = new
    return edits, dangling


REFERENCE_CAP = 30


def summary_lines(result: RetireResult, dry_run: bool) -> List[str]:
    """The driver's report: what moved, what was rewritten and the follow-up left to a person."""
    out = result.retirement
    ids = ", ".join(str(i.get("id")) for i in out.retired)
    lines = [f"{'would retire' if dry_run else 'retired'} {ids}; {result.remaining} item(s) remain"]
    if out.renames:
        lines.append(f"renumbered {len(out.renames)} item(s): "
                     + ", ".join(f"{old}->{new}" for old, new in out.renames.items()))
    lines.extend(f"rewrote ids in {rel}" for rel in result.rewritten)
    lines.extend(f"issue #{n}: a retired item resolves it; add a close_candidates entry with evidence"
                 for n in out.issues_to_close)
    lines.extend(f"tracker #{n}: lost child items; revisit status_note and recommended_action"
                 for n in out.trackers_touched)
    lines.extend(f"dangling: {note}" for note in result.dangling)
    lines.extend(f"reference (not rewritten): {ref}" for ref in result.references[:REFERENCE_CAP])
    if len(result.references) > REFERENCE_CAP:
        lines.append(f"... {len(result.references) - REFERENCE_CAP} more reference(s)")
    if not dry_run:
        lines.append("next: todo_sync.py render, then todo_sync.py check")
    return lines


def _references(cfg: HarnessConfig, skip: Sequence[str]) -> Tuple[str, ...]:
    """``path:line: text`` of other tracked or untracked files naming a TODO id; empty outside git."""
    excludes = [f":(exclude){rel}" for rel in skip]
    argv = ["git", "-C", str(cfg.project_root), "grep", "--untracked", "-n", "-I", "-E", "TODO-[0-9]{3,}",
            "--", ".", *excludes]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ()
    return tuple(line.strip() for line in done.stdout.splitlines()) if done.returncode == 0 else ()
