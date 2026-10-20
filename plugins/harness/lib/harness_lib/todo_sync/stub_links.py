"""Snapshot item links: an item's ``_IMPL_TODO.md`` stubs and their Markdown link targets.

``item_stubs`` collects every distinct stub on disk for a TODO item, in route order: ``impl_stub`` source
refs, then ``<research_folder ref>/<stub_name>``, then each listed research entry's ``stub_path`` followed by
every stub whose anchor names that entry. ``link_target`` turns a stub path into a target relative to the
snapshot folder.
"""
from __future__ import annotations

import os
import posixpath
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from harness_lib.todo_sync.sources import Sources, posix

_ENCODE = {" ": "%20", "(": "%28", ")": "%29", "<": "%3C", ">": "%3E", "|": "%7C"}


def _norm(ref: Any) -> Optional[str]:
    """``ref`` as a normalized repo-relative POSIX path, or None when it is empty, absolute or escapes."""
    if not isinstance(ref, str) or not ref.strip():
        return None
    rel = posixpath.normpath(posix(ref.strip()))
    if rel.startswith("/") or rel == ".." or rel.startswith("../") or ":" in rel.split("/")[0]:
        return None
    return rel


def _listed(item: Dict[str, Any], key: str) -> List[Any]:
    """``item[key]`` when it is a list, else empty."""
    value = item.get(key)
    return value if isinstance(value, list) else []


def _sources_of(item: Dict[str, Any], kind: str) -> Iterator[Any]:
    for source in _listed(item, "sources"):
        if isinstance(source, dict) and source.get("type") == kind:
            yield source.get("ref")


def _entry_ids(item: Dict[str, Any]) -> List[str]:
    return [e for e in _listed(item, "catalog_entry_ids") if isinstance(e, str)]


def _disk_name(folder: Path, part: str) -> Optional[str]:
    """The on-disk spelling of ``part`` in ``folder``; a case variant only where the filesystem accepts it."""
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    if part in names:
        return part
    if not (folder / part).exists():
        return None
    return next((n for n in names if n.casefold() == part.casefold()), None)


def _on_disk(root: Path, rel: str) -> Optional[str]:
    """``rel`` spelled as on disk when it names an existing file under ``root``, else None."""
    parts: List[str] = []
    folder = root
    for part in rel.split("/"):
        name = _disk_name(folder, part)
        if name is None:
            return None
        parts.append(name)
        folder = folder / name
    return "/".join(parts) if folder.is_file() else None


def _entry_stub_paths(src: Sources, entry_id: str) -> Iterator[Any]:
    if src.cfg.todo.research.catalog:
        for entry in src.entries():
            if entry.get("id") == entry_id:
                yield entry.get("stub_path")


def _anchored(src: Sources, entry_id: str) -> Iterator[str]:
    if src.cfg.todo.stub_name and src.research_root.is_dir():
        for rel in src.stub_files():
            anchor = src.stub(rel).anchor
            if anchor is not None and anchor.value == entry_id:
                yield rel


def _candidates(src: Sources, item: Dict[str, Any]) -> Iterator[Any]:
    yield from _sources_of(item, "impl_stub")
    name = src.cfg.todo.stub_name
    if name:
        for ref in _sources_of(item, "research_folder"):
            yield f"{ref}/{name}" if isinstance(ref, str) else None
    for entry_id in _entry_ids(item):
        yield from _entry_stub_paths(src, entry_id)
        yield from _anchored(src, entry_id)


def item_stubs(src: Sources, item: Dict[str, Any]) -> List[str]:
    """Distinct existing stub paths of ``item`` (repo-relative POSIX), in route order."""
    found: List[str] = []
    for ref in _candidates(src, item):
        rel = _norm(ref)
        disk = None if rel is None else _on_disk(src.root, rel)
        if disk is not None and disk not in found:
            found.append(disk)
    return found


def link_target(stub_rel: str, from_dir_rel: str) -> str:
    """``stub_rel`` relative to ``from_dir_rel`` (POSIX), with space, parentheses, ``<>`` and ``|``
    percent-encoded."""
    rel = posixpath.relpath("/" + posix(stub_rel), "/" + posix(from_dir_rel))
    return "".join(_ENCODE.get(ch, ch) for ch in rel)
