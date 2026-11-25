"""arc-meta: replace a tool's ``tool.metadata.xml`` ("?" help page) in the toolbox archive with a clean one.

The "?" page renders ``<Tool>.tool/tool.metadata.xml``, distinct from the hover tooltip and the tool dialog,
which read ``tool.content.rc`` (see ``arc_meta_rc``). Repeated Pro metadata imports MERGE, so that member
accumulates duplicate parameters, stacked summaries and large merged thumbnails. This writer regenerates it
from the canonical ``<tool_dir>/<Tool>.xml`` and writes it straight into the archive, bypassing Pro's merge.

Rendering rules, derived from observed round-trips:
  - summary / usage render as Pro's native escaped HTML, styled DIV/P/UL/LI with list items holding no
    inner <P> (shape and styles: ``arc_meta_format`` module docstring). A single clean block renders.
  - parameter dialogReference renders cleanly from a <para> child element.
  - the tool's ``tool.illustration.png`` (when the archive holds one) is embedded as
    ``<Binary><Thumbnail><img src="data:image/png;base64,..."/></Thumbnail></Binary>``, the element Pro's
    stylesheets draw as the page illustration. The image is read from the archive, never from the canonical
    XML, and a tool without one gets no <Binary> block. A relative file link would break, since Pro renders
    the page from a temp copy.

The page itself is built by ``arc_meta_canonical.page``, the builder the check API compares against.
DRY-RUN BY DEFAULT: nothing is written until ``apply=True``. On apply the archive is rewritten through
``arc_meta_archive.rewrite`` (validate, keep ``<atbx>.bak``, swap). The apply can run with the toolbox open
in ArcGIS Pro; a file Pro holds is refused as locked, and reopening the toolbox shows the change. The page is
written as UTF-8, as before the port.
"""
from __future__ import annotations

import re
import zipfile
import zlib
from pathlib import Path
from typing import List, NamedTuple, Optional

import arc_meta_canonical
import arc_meta_format as mf
from arc_meta_archive import decode, rewrite
from arc_meta_config import RepoLike, paths
from arc_meta_models import ApiError, ApplyOutcome, Surface

__all__ = ["apply_page", "run_page", "build_page", "read_illustration", "ApplyOutcome"]

_DATA_URI = re.compile(r'src="data:image/png;base64,[^"]*"')
_CORRUPT = (zipfile.BadZipFile, zlib.error)


class _OldPage(NamedTuple):
    """The archive's current page: whether the member exists, its size in bytes, its text when readable."""

    present: bool
    size: int
    text: Optional[str]


def _page_entry(tool: str) -> str:
    return f"{tool}.tool/tool.metadata.xml"


def _open(atbx: Path) -> zipfile.ZipFile:
    """The archive at ``atbx``; refused when absent or not a zip."""
    if not atbx.is_file():
        raise ApiError(f"no toolbox at {atbx.as_posix()}")
    try:
        return zipfile.ZipFile(atbx)
    except zipfile.BadZipFile as exc:
        raise ApiError(f"{atbx.name} is not a zip archive ({exc})") from exc


def read_illustration(atbx: Path, tool: str) -> Optional[bytes]:
    """The tool's ``tool.illustration.png`` bytes from the archive, or None when it has none.

    A member that fails its CRC or does not inflate is refused.
    """
    atbx, entry = Path(atbx), mf.illustration_entry(tool)
    with _open(atbx) as zf:
        if entry not in set(zf.namelist()):
            return None
        try:
            return zf.read(entry)
        except _CORRUPT as exc:
            raise ApiError(f"{entry} in {atbx.name} is corrupt ({exc})") from exc


def build_page(tool: str, tool_dir: Path, illustration: Optional[bytes] = None) -> str:
    """The clean ``tool.metadata.xml`` for ``tool`` from ``<tool_dir>/<tool>.xml``, with the illustration."""
    return arc_meta_canonical.page(arc_meta_canonical.load(tool_dir, tool)[1], illustration)


def _current_page(atbx: Path, tool: str) -> _OldPage:
    """The archive's page for ``tool``; refused only when the archive does not hold the tool.

    A linked-script tool without a page member reads as absent; a corrupt or undecodable member reads as
    present with no text, so the rewrite that repairs it is never blocked.
    """
    with _open(atbx) as zf:
        names = set(zf.namelist())
        if f"{tool}.tool/tool.content" not in names:
            raise ApiError(f"{tool} is not a tool in {atbx.name}")
        entry = _page_entry(tool)
        return _old_page(zf, entry) if entry in names else _OldPage(False, 0, None)


def _old_page(zf: zipfile.ZipFile, entry: str) -> _OldPage:
    """Member ``entry`` as an ``_OldPage``; its text is None when it fails to read or decode."""
    try:
        raw = zf.read(entry)
    except _CORRUPT:
        return _OldPage(True, zf.getinfo(entry).file_size, None)
    try:
        return _OldPage(True, len(raw), decode(raw))
    except UnicodeDecodeError:
        return _OldPage(True, len(raw), None)


def _params(xml: str) -> int:
    return len(re.findall(r"<param ", xml))


def _origin(old: _OldPage) -> str:
    if not old.present:
        return "new entry"
    return f"unreadable page ({old.size:,} bytes)" if old.text is None else f"{old.size:,} bytes"


def _summary(tool: str, old: _OldPage, new_xml: str, illustration: Optional[bytes]) -> str:
    """The one-line size, parameter-count and illustration report."""
    origin = _origin(old)
    params = f"params {_params(old.text or '')} -> {_params(new_xml)}"
    image = ("no illustration" if illustration is None
             else f"illustration {len(illustration):,} bytes embedded")
    return f"{tool}: metadata.xml {origin} -> {len(new_xml):,} bytes | {params} | {image}"


def _write_report(atbx: Path, tool: str, new_xml: str, apply: bool) -> List[str]:
    """The new page (data URI elided), then the write or the dry-run notice; writes when ``apply``."""
    lines = ["", "--- new tool.metadata.xml ---", ""]
    lines += _DATA_URI.sub('src="data:image/png;base64,..."', new_xml).splitlines()
    if not apply:
        return lines + ["", "DRY-RUN: nothing written. Re-run with apply=True to write."]
    rewrite(atbx, {_page_entry(tool): new_xml.encode("utf-8")})
    return lines + ["", f"APPLIED. Backup at {atbx.name}.bak. Reopen the toolbox in ArcGIS Pro to re-sync."]


def run_page(tool: str, atbx: Path, tool_dir: Path, apply: bool = False) -> ApplyOutcome:
    """Dry-run (default) or apply the ``tool.metadata.xml`` replacement for one tool.

    A linked-script tool carries no ``tool.metadata.xml`` member; the apply appends one. A page already
    equal to the canonical build is reported unchanged and never rewritten; an unreadable page counts as
    changed.
    """
    atbx = Path(atbx)
    old = _current_page(atbx, tool)
    illustration = read_illustration(atbx, tool)
    new_xml = build_page(tool, tool_dir, illustration)
    lines = [_summary(tool, old, new_xml, illustration)]
    if old.text == new_xml:
        lines.append("UP TO DATE: the archive page matches the canonical source; nothing to write.")
        return ApplyOutcome(surface=Surface.PAGE, tool=tool, changed=False, applied=False, lines=lines)
    lines += _write_report(atbx, tool, new_xml, apply)
    return ApplyOutcome(surface=Surface.PAGE, tool=tool, changed=True, applied=apply, lines=lines)


def apply_page(tool: str, apply: bool = False, repo: RepoLike = None) -> ApplyOutcome:
    """``run_page`` on the archive and canonical folder configured for ``repo`` (default: active project)."""
    p = paths(repo)
    return run_page(tool, p.atbx, p.tool_dir, apply)
