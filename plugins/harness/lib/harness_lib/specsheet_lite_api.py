"""Specsheet Lite: where a spec sheet lands, and writing it, reading it back and naming the next step.

A sheet is written to ``<artifacts.specs>/<YYYY-MM-DD>-<slug>.md``, the slug drawn from its title. The page
``render_sheet`` produces is the whole stored form; ``load_sheet`` parses it and refuses a page out of shape.
``__all__`` is the surface ``skill_api.py`` binds for an api heredoc. Requires an activated config.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

from harness_lib.config import active
from harness_lib.specsheet_lite_models import (
    MAX_LINES,
    TARGET_LINES,
    SpecSheet,
    parse_sheet,
    render_sheet,
)

__all__ = ["MAX_LINES", "SheetExists", "SpecSheet", "TARGET_LINES", "load_sheet", "new_sheet", "next_step",
           "render_sheet", "sheet_path", "write_sheet"]


class SheetExists(ValueError):
    """A sheet already sits at the path a write would take; pass ``replace=True`` to rewrite it."""


def new_sheet(title: str, request: str, goals: Sequence[str], avoid: Sequence[str] = (),
              day: Optional[date] = None) -> SpecSheet:
    """A validated sheet, dated ``day`` (today when None)."""
    return SpecSheet(title=title, request=request, goals=list(goals), avoid=list(avoid),
                     day=day or date.today())


def slug(title: str) -> str:
    """Lower-case words of ``title`` joined by hyphens; ``sheet`` when none remain."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "sheet"


def sheet_path(sheet: SpecSheet) -> Path:
    """``<artifacts.specs>/<YYYY-MM-DD>-<slug>.md`` for ``sheet``, under the project root."""
    cfg = active()
    return cfg.path(cfg.artifacts.specs) / f"{sheet.day.isoformat()}-{slug(sheet.title)}.md"


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


def next_step(sheet: SpecSheet, path: Path) -> str:
    """The write-plan invocation that takes ``sheet`` at ``path`` as its spec."""
    title = sheet.title.replace('"', "'")
    return f'/harness:write-plan "{title}" --spec {_rel(path)}'
