"""spec-it: where a spec sheet lands, and writing it, reading it back and naming the next step.

A sheet is written to ``<artifacts.specs>/<YYYY-MM-DD>-<slug>.md``, the slug drawn from its title (a ``-2``,
``-3`` suffix when another title on that day already holds the slug). The page
``render_sheet`` produces is the whole stored form; ``load_sheet`` parses it and refuses a page out of shape.
``__all__`` is the surface ``skill_api.py`` binds for an api heredoc. Requires an activated config.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import List, Optional, Sequence

from harness_lib.config import active
from harness_lib.spec_it_models import (
    MAX_LINES,
    TARGET_LINES,
    SpecSheet,
    parse_sheet,
    render_sheet,
)

__all__ = ["MAX_LINES", "SheetExists", "SpecSheet", "TARGET_LINES", "load_sheet", "new_sheet", "next_step",
           "plan_refs", "render_sheet", "sheet_path", "write_sheet"]

_REF = re.compile(r"todo-[a-z0-9]{4}|#\d+")


class SheetExists(ValueError):
    """A sheet already sits at the path a write would take; pass ``replace=True`` to rewrite it."""


def new_sheet(title: str, request: str, goals: Sequence[str], avoid: Sequence[str] = (),
              day: Optional[date] = None) -> SpecSheet:
    """A validated sheet, dated ``day`` (today when None); ``goals`` and ``avoid`` reach the model as given,
    so a single string is refused rather than split into characters."""
    return SpecSheet(title=title, request=request, goals=goals, avoid=avoid, day=day or date.today())


def slug(title: str) -> str:
    """Lower-case ASCII words of ``title`` (accents folded) joined by hyphens; ``sheet`` when none remain."""
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-") or "sheet"


def _title_at(path: Path) -> Optional[str]:
    """The ``# `` title on the first line of the page at ``path``; None when absent or unreadable."""
    try:
        with path.open(encoding="utf-8") as handle:
            first = handle.readline().rstrip("\r\n")
    except (OSError, UnicodeDecodeError):
        return None
    return first[2:] if first.startswith("# ") else None


def sheet_path(sheet: SpecSheet) -> Path:
    """``<artifacts.specs>/<YYYY-MM-DD>-<slug>.md`` for ``sheet``, under the project root.

    When a page there holds another title (two titles sharing a slug), ``-2``, ``-3`` and on follow the slug
    until a free path or the page with this title turns up, so distinct sheets never share a file.
    """
    cfg = active()
    folder, stem = cfg.path(cfg.artifacts.specs), f"{sheet.day.isoformat()}-{slug(sheet.title)}"
    path, n = folder / f"{stem}.md", 1
    while path.exists() and _title_at(path) != sheet.title:
        n += 1
        path = folder / f"{stem}-{n}.md"
    return path


def write_sheet(sheet: SpecSheet, replace: bool = False) -> Path:
    """Write ``sheet``'s page and return its path; refuses an existing page unless ``replace``."""
    checked = SpecSheet.model_validate(sheet.model_dump())
    path = sheet_path(checked)
    if path.exists() and not replace:
        raise SheetExists(f"{_rel(path)} exists; pass replace=True to rewrite it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_sheet(checked), encoding="utf-8", newline="\n")
    return path


def load_sheet(path: Path) -> SpecSheet:
    """The sheet at ``path`` (relative paths from the project root); ``ValueError`` when out of shape."""
    target = Path(path)
    if not target.is_absolute():
        target = active().path(target.as_posix())
    return parse_sheet(target.read_text(encoding="utf-8"))


def _rel(path: Path) -> str:
    """``path`` relative to the project root, POSIX style; the path itself when outside it."""
    root = active().project_root.resolve()
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return Path(path).as_posix()


def plan_refs(refs: Sequence[str]) -> List[str]:
    """The TODO ids and issue numbers in ``refs``, split on commas, blanks skipped, first occurrence kept.

    Raises:
        ValueError: A ref that is neither a TODO id (``todo-k69m``) nor an issue number (``#301``).
    """
    out: List[str] = []
    for token in (part.strip() for ref in refs for part in ref.split(",")):
        if token and not _REF.fullmatch(token):
            raise ValueError(f"--refs {token} is neither a TODO id nor an issue number")
        if token and token not in out:
            out.append(token)
    return out


def next_step(sheet: SpecSheet, path: Path, refs: Sequence[str] = ()) -> str:
    """The write-plan invocation that takes ``sheet`` at ``path`` as its spec; the title and the path are both
    quoted, so a folder name holding a space stays one argument. ``refs`` (see ``plan_refs``) follow as
    single-quoted ``--refs`` tokens, the TODO ids and issues the sheet itself cannot hold."""
    title = sheet.title.replace('"', "'")
    step = f'/harness:write-plan "{title}" --spec "{_rel(path)}"'
    tokens = plan_refs(refs)
    return f"{step} --refs " + " ".join(f"'{token}'" for token in tokens) if tokens else step
