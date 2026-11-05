"""arc-meta: readers of the canonical per-tool help XML and the one "?" page builder.

The check API, the three apply writers and the tests all build the hover text and the help page here, so
the checker and the writers cannot drift apart. ``<tool_dir>/<Tool>.xml`` is the canonical source; refusals
raise ``ApiError``. Imports only the standard library, the generator and the sibling models module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple
from xml.etree import ElementTree as ET

import arc_meta_format as mf
from arc_meta_models import ApiError

__all__ = ["load", "rc_text", "add_dialog_ref", "tool_element", "fields_of", "fields", "page"]


def load(tool_dir: Path, tool: str) -> Tuple[str, ET.Element]:
    """The text and root element of ``<tool_dir>/<tool>.xml``; refused when absent, not UTF-8 or not
    well-formed."""
    path = Path(tool_dir) / f"{tool}.xml"
    if not path.is_file():
        raise ApiError(f"no canonical source at {path.as_posix()}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(f"{path.as_posix()} is not UTF-8 text ({exc})") from exc
    try:
        return text, ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        raise ApiError(f"{path.as_posix()} is not well-formed XML ({exc})") from exc


def rc_text(blocks: list, summary: bool = False) -> str:
    """The rc value for ``blocks``: empty when blank, plain text for the summary and an unformatted
    parameter, ``xdoc`` rich text for a formatted parameter."""
    if not mf.plain_text(blocks).strip():
        return ""
    return mf.plain_text(blocks) if summary or mf.is_plain(blocks) else mf.to_xdoc(blocks)


def add_dialog_ref(param_el: ET.Element, blocks: list) -> None:
    """Add a <dialogReference>: a plain <para> when unformatted, else escaped HTML."""
    ref = ET.SubElement(param_el, "dialogReference")
    if mf.is_plain(blocks):
        ET.SubElement(ref, "para").text = mf.plain_text(blocks)
    else:
        ref.text = mf.to_pro_html(blocks)


def tool_element(root: ET.Element, label: str) -> ET.Element:
    """The ``<tool>`` element of a parsed canonical or page root; refused, naming ``label``, when absent."""
    tool_el = root.find("tool")
    if tool_el is None:
        raise ApiError(f"{label} has no <tool> element")
    return tool_el


def fields_of(root: ET.Element, label: str) -> Tuple[str, Dict[str, str]]:
    """``(summary rc text, {lowercased parameter name: rc text})`` of a parsed canonical root.

    The summary is always plain text; a parameter keeps a bare string when plain and becomes ``xdoc`` rich
    text when the canonical XML carries ``<b>``/``<i>``/``<ul>`` markup. The writer and the check API both
    read hover text here.
    """
    tool_el = tool_element(root, label)
    summary = rc_text(mf.parse(mf.inner_html(tool_el.find("summary"))), summary=True)
    descr = {param.get("name", "").lower(): rc_text(mf.parse(mf.inner_html(param.find("dialogReference"))))
             for param in root.iter("param")}
    return summary, descr


def fields(tool_dir: Path, tool: str) -> Tuple[str, Dict[str, str]]:
    """``fields_of`` for the canonical XML of ``tool`` under ``tool_dir``."""
    return fields_of(load(tool_dir, tool)[1], f"{tool}.xml")


def _set_rich(parent: ET.Element, tag: str, blocks: list) -> None:
    """Add <tag> holding blocks as Pro's escaped item-metadata HTML."""
    ET.SubElement(parent, tag).text = mf.to_pro_html(blocks)


def _add_illustration(root: ET.Element, png: bytes) -> None:
    """Append the ``Binary/Thumbnail/img`` block the Pro stylesheets render as the page illustration."""
    thumb = ET.SubElement(ET.SubElement(root, "Binary"), "Thumbnail")
    ET.SubElement(thumb, "img", {"src": mf.illustration_data_uri(png)})


def _add_tool(root: ET.Element, src: ET.Element, src_tool: ET.Element) -> None:
    """The page's <tool>: name, display name, summary, usage when it holds text, and every parameter."""
    tool_el = ET.SubElement(root, "tool", {"name": src_tool.get("name", ""),
                                           "displayname": src_tool.get("displayname", ""), "xmlns": ""})
    _set_rich(tool_el, "summary", mf.parse(mf.inner_html(src_tool.find("summary"))))
    usage_blocks = mf.parse(mf.inner_html(src_tool.find("usage")))
    if usage_blocks:
        _set_rich(tool_el, "usage", usage_blocks)
    params = ET.SubElement(tool_el, "parameters")
    for p in src.iter("param"):
        pe = ET.SubElement(params, "param", {
            "name": p.get("name", ""),
            "displayname": p.get("displayname", ""),
            "type": p.get("type", ""),
            "direction": p.get("direction", ""),
            "datatype": p.get("datatype", ""),
        })
        add_dialog_ref(pe, mf.parse(mf.inner_html(p.find("dialogReference"))))


def page(src: ET.Element, illustration: Optional[bytes] = None) -> str:
    """The clean ``tool.metadata.xml`` ("?" help page) for the parsed canonical root ``src``.

    ``illustration`` holds the PNG bytes of the tool's ``tool.illustration.png`` when it has one; they are
    embedded so the "?" page shows the image the tool dialog already shows.
    """
    src_tool = tool_element(src, "the canonical XML")
    if not src_tool.get("name"):
        raise ApiError("the canonical <tool> has no name")
    root = ET.Element("metadata", {"xml:lang": "en"})
    esri = ET.SubElement(root, "Esri")
    ET.SubElement(esri, "ArcGISFormat").text = "1.0"
    ET.SubElement(esri, "ArcGISProfile").text = "ItemDescription"
    _add_tool(root, src, src_tool)
    did = ET.SubElement(root, "dataIdInfo")
    ET.SubElement(ET.SubElement(did, "idCitation"), "resTitle").text = src_tool.get("displayname", "")
    keys = ET.SubElement(did, "searchKeys")
    for kw in src.iter("keyword"):
        ET.SubElement(keys, "keyword").text = kw.text
    if illustration is not None:
        _add_illustration(root, illustration)
    return '<?xml version="1.0"?>\n' + ET.tostring(root, encoding="unicode")
