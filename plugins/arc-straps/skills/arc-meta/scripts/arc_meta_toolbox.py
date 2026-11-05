"""arc-meta: write a toolbox archive's toolbox-level metadata from its canonical source.

Two toolbox-level surfaces read separate members inside the ``.atbx`` zip:

  - ``toolbox.content.rc``: the toolbox title and description shown in the Catalog pane.
  - ``toolbox.metadata.xml``: the toolbox item description page (summary, description, credits, tags,
    use limitations).

Both are generated from the configured ``toolbox_source`` (ArcGIS metadata format, ItemDescription
profile; default ``<parent of tool_dir>/<archive file name>.xml``) and written straight into the zip,
bypassing Pro's metadata Import, which merges instead of replacing. The regenerated page carries no
``<Binary>`` thumbnail and no geoprocessing lineage. Toolset names in the resource file are left untouched.

DRY-RUN BY DEFAULT. With ``apply=True`` the archive is rewritten through ``arc_meta_archive.rewrite``
(temp copy, validation, ``<atbx>.bak``, swap). The apply can run with the toolbox open in ArcGIS Pro; a
file Pro holds is refused as locked, and reopening the toolbox shows the change. Both members are written as
UTF-8 without a byte-order mark.
"""
from __future__ import annotations

import copy
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import arc_meta_format as mf
from arc_meta_archive import read_json, rewrite
from arc_meta_config import RepoLike, paths
from arc_meta_models import ApiError, ApplyOutcome, Surface

__all__ = ["apply_toolbox", "run_toolbox", "load_source", "build_rc", "build_metadata", "ApplyOutcome"]

RC_ENTRY = "toolbox.content.rc"
META_ENTRY = "toolbox.metadata.xml"
RC_LINE_BREAK = "\r\n"


@dataclass(frozen=True)
class ToolboxSource:
    """Toolbox-level fields read from the canonical metadata source."""

    title: str
    summary: str
    abstract_html: str
    credit: str
    keywords: Tuple[str, ...]
    use_limit_html: str


def _text(root: ET.Element, path: str) -> str:
    """The stripped text at ``path``, or an empty string."""
    return (root.findtext(path) or "").strip()


def _parse_source(path: Path) -> ET.Element:
    """The parsed root of the source; ApiError when it is absent or not well-formed XML."""
    if not path.is_file():
        raise ApiError(f"no toolbox source at {path.as_posix()}")
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ApiError(f"{path.as_posix()} is not well-formed XML ({exc})") from exc


def load_source(path: Path) -> ToolboxSource:
    """Parse the canonical ArcGIS-format source into a ToolboxSource.

    Raises ApiError when the description or use limitation holds HTML the generator cannot convert.
    """
    path = Path(path)
    source = _read_source(_parse_source(path))
    for tag, html in (("idAbs", source.abstract_html), ("useLimit", source.use_limit_html)):
        try:
            mf.parse(html)
        except ValueError as exc:
            raise ApiError(f"{path.as_posix()} <{tag}> cannot be converted ({exc})") from exc
    return source


def _read_source(root: ET.Element) -> ToolboxSource:
    """The toolbox-level fields of a parsed source root."""
    return ToolboxSource(
        title=_text(root, "dataIdInfo/idCitation/resTitle"),
        summary=_text(root, "dataIdInfo/idPurp"),
        abstract_html=_text(root, "dataIdInfo/idAbs"),
        credit=_text(root, "dataIdInfo/idCredit"),
        keywords=tuple(k.text.strip() for k in root.iter("keyword") if k.text and k.text.strip()),
        use_limit_html=_text(root, "dataIdInfo/resConst/Consts/useLimit"),
    )


def rc_description(source: ToolboxSource) -> str:
    """Flatten the description to plain lines: one per paragraph or list item."""
    lines: List[str] = []
    for kind, content in mf.parse(source.abstract_html):
        groups = [content] if kind == "p" else content
        lines.extend("".join(run.text for run in runs) for runs in groups)
    return RC_LINE_BREAK.join(lines)


def _updated(data: dict, source: ToolboxSource) -> dict:
    """A deep copy of the resource ``data`` with the title and description replaced."""
    new = copy.deepcopy(data)
    new["map"]["title"] = source.title
    new["map"]["descr"] = rc_description(source)
    return new


def _dump_rc(data: dict) -> str:
    """The resource JSON text as the writer stores it."""
    return json.dumps(data, indent=4, ensure_ascii=False)


def build_rc(rc_text: str, source: ToolboxSource) -> str:
    """Return the resource JSON with the title and description replaced."""
    return _dump_rc(_updated(json.loads(rc_text), source))


def _add(parent: ET.Element, path: str, text: Optional[str] = None) -> ET.Element:
    """Create the slash-separated element chain under parent; set text on the last."""
    node = parent
    for tag in path.split("/"):
        node = ET.SubElement(node, tag)
    if text is not None:
        node.text = text
    return node


def _add_identification(root: ET.Element, source: ToolboxSource) -> None:
    """Add the dataIdInfo block: title, summary, description, credit, tags, limits."""
    did = _add(root, "dataIdInfo")
    _add(did, "idCitation/resTitle", source.title)
    _add(did, "idPurp", source.summary)
    _add(did, "idAbs", mf.to_pro_html(mf.parse(source.abstract_html)))
    _add(did, "idCredit", source.credit)
    keys = _add(did, "searchKeys")
    for keyword in source.keywords:
        _add(keys, "keyword", keyword)
    if source.use_limit_html:
        _add(did, "resConst/Consts/useLimit", mf.to_pro_html(mf.parse(source.use_limit_html)))


def build_metadata(source: ToolboxSource) -> str:
    """Return a clean toolbox.metadata.xml: no thumbnail, no lineage."""
    root = ET.Element("metadata", {"xml:lang": "en"})
    esri = _add(root, "Esri")
    _add(esri, "ArcGISFormat", "1.0")
    _add(esri, "ArcGISProfile", "ItemDescription")
    _add(root, "distInfo/distributor/distorFormat/formatName", "ArcToolbox Toolbox")
    _add_identification(root, source)
    _add(root, "mdHrLv/ScopeCd").set("value", "005")
    return '<?xml version="1.0"?>\n' + ET.tostring(root, encoding="unicode")


def _current(atbx: Path) -> Tuple[dict, Dict[str, bytes]]:
    """The archive's parsed toolbox rc and the raw bytes of each toolbox-level member it holds."""
    if not atbx.is_file():
        raise ApiError(f"no toolbox archive at {atbx.as_posix()}")
    try:
        with zipfile.ZipFile(atbx) as zin:
            rc = read_json(zin, RC_ENTRY, atbx.name)
            names = set(zin.namelist())
            old = {name: zin.read(name) for name in (RC_ENTRY, META_ENTRY) if name in names}
    except zipfile.BadZipFile as exc:
        raise ApiError(f"{atbx.name} is not a zip archive ({exc})") from exc
    if rc is None:
        raise ApiError(f"{RC_ENTRY} is missing from {atbx.name}")
    if not isinstance(rc, dict) or not isinstance(rc.get("map"), dict):
        raise ApiError(f"{RC_ENTRY} in {atbx.name} has no \"map\" object")
    return rc, old


def _replacements(new_rc: dict, source: ToolboxSource) -> Dict[str, bytes]:
    """The new bytes for each toolbox-level member."""
    return {
        RC_ENTRY: _dump_rc(new_rc).encode("utf-8"),
        META_ENTRY: build_metadata(source).encode("utf-8"),
    }


def _changed(rc: dict, new_rc: dict, old: Dict[str, bytes], replacements: Dict[str, bytes]) -> bool:
    """Whether the archive differs from the source: the rc by meaning, the page by bytes.

    Comparing the rc by meaning keeps a Pro re-save in its own formatting from counting as a change.
    """
    return rc != new_rc or old.get(META_ENTRY) != replacements[META_ENTRY]


def _report(old: Dict[str, bytes], replacements: Dict[str, bytes]) -> List[str]:
    """Member sizes before and after, then each new member's text."""
    lines: List[str] = []
    for name, data in replacements.items():
        before = old.get(name, b"")
        note = " | thumbnail removed" if b"<Binary>" in before else ""
        lines.append(f"{name}: {len(before):,} -> {len(data):,} bytes{note}")
    for name, data in replacements.items():
        lines.extend(["", f"--- new {name} ---", *data.decode("utf-8").splitlines()])
    return lines


def run_toolbox(atbx: Path, source: Path, apply: bool = False) -> ApplyOutcome:
    """Dry-run (default) or apply the toolbox-level metadata from ``source`` to ``atbx``."""
    atbx = Path(atbx)
    fields = load_source(Path(source))
    rc, old = _current(atbx)
    new_rc = _updated(rc, fields)
    replacements = _replacements(new_rc, fields)
    changed = _changed(rc, new_rc, old, replacements)
    lines = _report(old, replacements) + [""]
    if not changed:
        lines.append("UNCHANGED: the archive already matches the source; nothing written.")
    elif not apply:
        lines.append("DRY-RUN: nothing written. Re-run with apply=True to write.")
    else:
        rewrite(atbx, replacements)
        lines.append(f"APPLIED. Backup at {atbx.name}.bak. Reopen the toolbox in ArcGIS Pro to re-sync.")
    return ApplyOutcome(surface=Surface.TOOLBOX, changed=changed, applied=changed and apply, lines=lines)


def apply_toolbox(apply: bool = False, repo: RepoLike = None) -> ApplyOutcome:
    """Dry-run (default) or apply the configured toolbox source to the configured archive."""
    p = paths(repo)
    return run_toolbox(p.atbx, p.toolbox_source, apply)
