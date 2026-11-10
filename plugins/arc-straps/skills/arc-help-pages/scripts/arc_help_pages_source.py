"""arc-help-pages source: what a help page is built from, read from the canonical XML and the archive.

The canonical XML (``<tool_dir>/<Tool>.xml``) gives the title, the summary and each parameter's attributes
and text; the archive gives the parameter order (``<Tool>.tool/tool.content``) and the toolbox alias
(``toolbox.content``). Locations come from ``arc_help_pages_config.paths``; refusals raise ``HelpError``.
Imports only the standard library and the sibling config and models modules.
"""
from __future__ import annotations

import json
import zipfile
import zlib
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from arc_help_pages_config import HelpPaths, RepoLike, paths
from arc_help_pages_models import HelpError, ParamDoc, ParamKind, ToolDoc

__all__ = ["has_tool", "tool_doc"]

_KINDS = {kind.value.lower(): kind for kind in ParamKind}
_BLOCK_TAGS = frozenset({"p", "li", "ul", "ol", "br", "div"})


def has_tool(tool: str, repo: RepoLike = None) -> bool:
    """True when ``<tool_dir>/<tool>.xml`` exists and the archive holds ``<tool>.tool/tool.content``."""
    p = paths(repo)
    if not (p.tool_dir / f"{tool}.xml").is_file() or not p.atbx.is_file():
        return False
    try:
        with zipfile.ZipFile(p.atbx) as zf:
            return f"{tool}.tool/tool.content" in zf.namelist()
    except zipfile.BadZipFile:
        return False


def tool_doc(tool: str, repo: RepoLike = None) -> ToolDoc:
    """The canonical text and archive facts of ``tool``; params follow ``tool.content`` order.

    A ``tool.content`` parameter with no canonical ``<param>`` is refused, naming it. Canonical parameters
    absent from ``tool.content`` are left out.
    """
    p = paths(repo)
    tool_el = _tool_element(_canonical_root(p.tool_dir, tool), f"{tool}.xml")
    content, alias = _archive_facts(p, tool)
    canonical = {el.get("name"): el for el in tool_el.findall("parameters/param")}
    rows = [_param_doc(name, canonical, tool) for name in _param_names(content, tool)]
    return ToolDoc(name=tool, displayname=tool_el.get("displayname", ""),
                   summary=_collapsed(_field_text(tool_el.find("summary"))), alias=alias, params=rows)


# --- canonical XML --------------------------------------------------------------------------------------

def _canonical_root(tool_dir: Path, tool: str) -> ET.Element:
    """The root of ``<tool_dir>/<tool>.xml``; refused when absent, not UTF-8 or not well-formed."""
    path = Path(tool_dir) / f"{tool}.xml"
    if not path.is_file():
        raise HelpError(f"no canonical source at {path.as_posix()}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HelpError(f"{path.as_posix()} is not UTF-8 text ({exc})") from exc
    try:
        return ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        raise HelpError(f"{path.as_posix()} is not well-formed XML ({exc})") from exc


def _tool_element(root: ET.Element, label: str) -> ET.Element:
    tool_el = root.find("tool")
    if tool_el is None:
        raise HelpError(f"{label} has no <tool> element")
    return tool_el


def _param_doc(name: str, canonical: Dict[Optional[str], ET.Element], tool: str) -> ParamDoc:
    """The row of ``name``; refused when the canonical XML has no ``<param>`` of that exact name."""
    el = canonical.get(name)
    if el is None:
        raise HelpError(f"{tool}.xml has no <param name=\"{name}\"> for the tool.content parameter {name}")
    kind = _KINDS.get(el.get("type", "").strip().lower())
    if kind is None:
        raise HelpError(f"{tool}.xml <param name=\"{name}\"> has type {el.get('type')!r}, "
                        f"not one of {[k.value for k in ParamKind]}")
    return ParamDoc(name=name, displayname=el.get("displayname", ""), type=kind,
                    direction=el.get("direction", ""), datatype=el.get("datatype", ""),
                    reference_html=_reference_html(el.find("dialogReference")))


def _reference_html(element: Optional[ET.Element]) -> str:
    """A field's text as HTML: CDATA as written, each ``<para>`` as an escaped ``<p>``; '' without text."""
    if element is None:
        return ""
    paras = [p for p in element.findall("para") if "".join(p.itertext()).strip()]
    if paras:
        return "".join(f"<p>{escape(''.join(p.itertext()), quote=False)}</p>" for p in paras)
    text = element.text or ""
    return text if text.strip() else ""


def _field_text(element: Optional[ET.Element]) -> str:
    """A field's plain text: ``<para>`` text joined, or CDATA HTML with tags stripped and entities decoded."""
    if element is None:
        return ""
    paras = element.findall("para")
    if paras:
        return " ".join("".join(p.itertext()) for p in paras)
    return _strip_tags(element.text or "")


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")


def _strip_tags(html: str) -> str:
    parser = _TextOnly()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)


def _collapsed(text: str) -> str:
    return " ".join(text.split())


# --- archive --------------------------------------------------------------------------------------------

def _archive_facts(p: HelpPaths, tool: str) -> Tuple[object, str]:
    """``(tool.content, toolbox alias)`` from the archive; refused when the tool is not in it or the archive
    has no ``toolbox.content`` with a non-empty string alias (the Python syntax line needs it)."""
    if not p.atbx.is_file():
        raise HelpError(f"no toolbox at {p.atbx.as_posix()}")
    try:
        with zipfile.ZipFile(p.atbx) as zf:
            content = _member_json(zf, f"{tool}.tool/tool.content", p.atbx.name)
            toolbox = _member_json(zf, "toolbox.content", p.atbx.name)
    except zipfile.BadZipFile as exc:
        raise HelpError(f"{p.atbx.name} is not a zip archive ({exc})") from exc
    if content is None:
        raise HelpError(f"{tool} is not a tool in {p.atbx.name}")
    alias = toolbox.get("alias") if isinstance(toolbox, dict) else None
    if not isinstance(alias, str) or not alias:
        raise HelpError(f"toolbox.content in {p.atbx.name} has no alias")
    return content, alias


def _decode(raw: bytes) -> str:
    """Archive entry text: UTF-16 when it carries a UTF-16 byte-order mark, else UTF-8 (BOM dropped)."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _member_json(zf: zipfile.ZipFile, name: str, label: str) -> Optional[object]:
    """Member ``name`` parsed as JSON, None when absent; refused when unreadable or not JSON."""
    if name not in zf.namelist():
        return None
    try:
        return json.loads(_decode(zf.read(name)))
    except (UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise HelpError(f"{name} in {label} cannot be read as JSON ({exc})") from exc


def _param_names(content: object, tool: str) -> List[str]:
    """The ``params`` keys of ``tool.content`` in dialog order; a missing ``params`` key reads as no
    parameters (a parameterless tool omits it). Refused when ``tool.content`` is not a JSON object or its
    ``params`` is not an object."""
    params = content.get("params", {}) if isinstance(content, dict) else None
    if not isinstance(params, dict):
        raise HelpError(f"{tool}.tool/tool.content is not a JSON object with a params object")
    return list(params)
