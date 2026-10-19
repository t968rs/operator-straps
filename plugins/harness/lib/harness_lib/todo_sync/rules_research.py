"""Research rules S1-S6: the research catalog against its stubs and folders.

Terminal statuses are ``FULLY_IMPLEMENTED`` and ``NOT_APPLICABLE``. A missing stub file is reported once:
by S3 for a non-terminal entry, by S1 for a terminal one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from harness_lib.todo_sync.report import Finding
from harness_lib.todo_sync.sources import TERMINAL_RESEARCH, Sources, posix


def _stub_path(entry: Dict[str, Any]) -> Optional[str]:
    value = entry.get("stub_path")
    return posix(value) if isinstance(value, str) and value else None


def _terminal(entry: Dict[str, Any]) -> bool:
    return entry.get("status") in TERMINAL_RESEARCH


def _entry_finding(src: Sources, rule: str, entry: Dict[str, Any], message: str, fix: str,
                   severity: str = "error") -> Finding:
    return Finding(rule, severity, src.research.rel, message, subject=str(entry.get("id")), fix=fix)


def s1_stub_anchor(src: Sources) -> List[Finding]:
    """S1: an entry's stub exists (terminal entries; S3 covers the rest) and its anchor names the entry."""
    out: List[Finding] = []
    for entry in src.entries():
        rel = _stub_path(entry)
        if rel is None:
            continue
        stub = src.stub(rel)
        if not stub.exists:
            if _terminal(entry):
                out.append(_entry_finding(src, "S1", entry, f"stub_path {rel} does not exist",
                                          "Point stub_path at the stub, or set it to null."))
            continue
        out.extend(_anchor_findings(entry, stub))
    return out


def _anchor_findings(entry: Dict[str, Any], stub: Any) -> List[Finding]:
    entry_id = str(entry.get("id"))
    if stub.error:
        return [Finding("S1", "error", stub.rel, f"stub unreadable: {stub.error}", subject=entry_id)]
    if stub.anchor is None:
        return [Finding("S1", "error", stub.rel, "no line matches todo.research.anchor_pattern",
                        subject=entry_id, fix=f"Add the catalog_entry anchor line for #{entry_id}.")]
    if stub.anchor.value != entry_id:
        return [Finding("S1", "error", stub.rel, f"anchor #{stub.anchor.value}, expected #{entry_id}",
                        line=stub.anchor.line, subject=entry_id, fix=f"Point the anchor at #{entry_id}.")]
    return []


def s2_orphan_stubs(src: Sources) -> List[Finding]:
    """S2: every stub file under the research root is some entry's ``stub_path``."""
    referenced = {_stub_path(e) for e in src.entries()}
    return [Finding("S2", "error", rel, "stub referenced by no catalog entry",
                    fix="Add a catalog entry whose stub_path names it, or delete the stub.")
            for rel in src.stub_files() if rel not in referenced]


def s3_non_terminal_stub(src: Sources) -> List[Finding]:
    """S3: a non-terminal entry has a non-null ``stub_path`` that exists."""
    out: List[Finding] = []
    for entry in src.entries():
        if _terminal(entry):
            continue
        rel = _stub_path(entry)
        status = entry.get("status")
        if rel is None:
            out.append(_entry_finding(src, "S3", entry, f"status {status} but stub_path is null",
                                      "Write the stub and set stub_path."))
        elif not src.stub(rel).exists:
            out.append(_entry_finding(src, "S3", entry, f"status {status} but stub_path {rel} does not exist",
                                      "Write the stub, or fix stub_path."))
    return out


def s4_stub_header(src: Sources) -> List[Finding]:
    """S4: a stub's first ``status:`` and ``loe:`` values equal the entry's ``status`` / ``loe``."""
    out: List[Finding] = []
    for entry in src.entries():
        rel = _stub_path(entry)
        stub = src.stub(rel) if rel else None
        if stub is None or not stub.exists or stub.error:
            continue
        for name in ("status", "loe"):
            out.extend(_header_finding(entry, stub, name))
    return out


def _header_finding(entry: Dict[str, Any], stub: Any, name: str) -> List[Finding]:
    want, got = entry.get(name), getattr(stub, name)
    entry_id = str(entry.get("id"))
    if got is None:
        if want is None:
            return []
        return [Finding("S4", "error", stub.rel, f"no {name}: line (catalog: {want})", subject=entry_id,
                        fix=f"Add '{name}: {want}' to the stub header.")]
    if got.value == want:
        return []
    return [Finding("S4", "error", stub.rel, f"{name}: {got.value!r} differs from the catalog's {want!r}",
                    line=got.line, subject=entry_id, fix="Make the stub header and the catalog entry agree.")]


def s5_research_folder(src: Sources) -> List[Finding]:
    """S5: an entry's ``research_folder`` (when set) exists."""
    out: List[Finding] = []
    for entry in src.entries():
        folder = entry.get("research_folder")
        if isinstance(folder, str) and folder and not src.cfg.path(folder).is_dir():
            out.append(_entry_finding(src, "S5", entry, f"research_folder {posix(folder)} does not exist",
                                      "Repoint research_folder at an existing folder."))
    return out


def _top_name(src: Sources, rel: Any, is_file: bool) -> Optional[str]:
    """Top-level research folder holding ``rel`` (a folder path, or a file path when ``is_file``)."""
    if not isinstance(rel, str) or not rel:
        return None
    try:
        parts = (src.root / rel).relative_to(src.research_root).parts
    except ValueError:
        return None
    return parts[0] if len(parts) > int(is_file) else None


def _covered(src: Sources) -> Set[str]:
    """Top-level folders holding an entry's folder or stub, the TODO catalog or the snapshot folder."""
    names = {_top_name(src, e.get("research_folder"), False) for e in src.entries()}
    names |= {_top_name(src, e.get("stub_path"), True) for e in src.entries()}
    names |= {_top_name(src, src.cfg.todo.catalog, True), _top_name(src, src.cfg.todo.snapshots.dir, False)}
    return {n for n in names if n}


def s6_uncovered_folders(src: Sources) -> List[Finding]:
    """S6 (warn): every top-level research folder is covered by an entry or ignored."""
    root: Path = src.research_root
    if not root.is_dir():
        return []
    covered = _covered(src)
    ignored = {posix(i).strip("/") for i in src.cfg.todo.research.ignore_folders}
    out: List[Finding] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        rel = src.rel(folder)
        if folder.name in covered or folder.name in ignored or rel in ignored:
            continue
        out.append(Finding("S6", "warn", rel, "research folder covered by no catalog entry",
                           fix="Add an entry whose research_folder lies in it, or list it in "
                               "todo.research.ignore_folders."))
    return out
