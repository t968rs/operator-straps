"""A demo toolbox project for arc-meta tests: one archive, its canonical XML, optional config."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Callable, Dict, Optional
from xml.etree import ElementTree as ET

import arc_meta_canonical
import arc_meta_format as mf
from conftest import git

TOOL = "Demo"
ATBX = "demo_toolbox.atbx"
TOOL_DIR = "tool_metadata/tools"
LYRX = "layers/demo.lyrx"

CONTENT: dict = {
    "type": "ScriptTool",
    "displayname": "$rc:title",
    "description": "$rc:description",
    "params": {
        "in_poly": {"displayname": "$rc:in_poly.title", "datatype": {"type": "GPFeatureLayer"},
                    "description": "$rc:in_poly.descr"},
        "Mode": {"type": "optional", "displayname": "$rc:mode.title", "datatype": {"type": "GPString"},
                 "domain": {"type": "GPCodedValueDomain",
                            "items": [{"value": "Fast", "code": "$rc:mode.domain.Fast"},
                                      {"value": "Slow", "code": "$rc:mode.domain.Slow"}]},
                 "value": "Fast"},
        "Out_Poly": {"type": "derived", "direction": "out", "displayname": "$rc:out_poly.title",
                     "datatype": {"type": "GPFeatureLayer"}, "symbologylayer": LYRX,
                     "description": "$rc:out_poly.descr"},
    },
}

RC: dict = {"map": {
    "title": "00 Demo Tool",
    "description": "Makes polygons.",
    "in_poly.title": "Input Polygons",
    "in_poly.descr": "Polygons to process.",
    "mode.title": "Mode",
    "out_poly.title": "Output Polygons",
    "out_poly.descr": "Derived output set to the polygons.",
}}

CANONICAL: str = """<?xml version="1.0"?>
<metadata xml:lang="en">
  <Esri><ArcGISFormat>1.0</ArcGISFormat><ArcGISProfile>ItemDescription</ArcGISProfile></Esri>
  <tool name="Demo" displayname="Demo Tool" xmlns="">
    <summary><![CDATA[<p>Makes polygons.</p>]]></summary>
    <usage><![CDATA[<p><b>Outputs:</b></p><ul><li>One polygon class.</li></ul>]]></usage>
    <parameters>
      <param name="in_poly" displayname="Input Polygons" type="Required" direction="Input" \
datatype="GPFeatureLayer">
        <dialogReference><para>Polygons to process.</para></dialogReference>
      </param>
      <param name="Mode" displayname="Mode" type="Optional" direction="Input" datatype="GPString">
        <dialogReference><para></para></dialogReference>
      </param>
      <param name="Out_Poly" displayname="Output Polygons" type="Derived" direction="Output" \
datatype="GPFeatureLayer">
        <dialogReference><para>Derived output set to the polygons.</para></dialogReference>
      </param>
    </parameters>
  </tool>
  <dataIdInfo><idCitation><resTitle>Demo Tool</resTitle></idCitation></dataIdInfo>
</metadata>
"""

BAD_CANONICAL: str = """<?xml version="1.0"?>
<metadata xml:lang="en">
  <Esri><ArcGISFormat>1.0</ArcGISFormat><ArcGISProfile>ItemDescription</ArcGISProfile></Esri>
  <tool name="Demo" displayname="00 Demo Tool" xmlns="">
    <summary><![CDATA[<p>Makes “polygons”. See <code>the page</code>.</p>]]></summary>
    <usage><![CDATA[<ul><li>A<ul><li>B<ul><li>C</li></ul></li></ul></li></ul>]]></usage>
    <parameters>
      <param name="inpoly" displayname="Input Polygons" type="Required" direction="Input" \
datatype="GPFeatureLayer">
        <dialogReference><para>Polygons to process.</para></dialogReference>
      </param>
      <param name="Mode" displayname="Mode" type="Required" direction="Input" datatype="GPString">
        <dialogReference><![CDATA[<ul><li>Speed<ul><li>Fast</li></ul>tail</li></ul>]]></dialogReference>
      </param>
      <param name="Out_Poly" displayname="Output Polygons" type="Derived" direction="Input" \
datatype="GPFeatureLayer">
        <dialogReference><para>Derived output.</para></dialogReference>
      </param>
    </parameters>
  </tool>
  <Binary><Thumbnail><Data>AAAA</Data></Thumbnail></Binary>
</metadata>
"""

PNG_A: bytes = b"\x89PNG\r\n\x1a\n" + b"illustration-a"
PNG_B: bytes = b"\x89PNG\r\n\x1a\n" + b"illustration-b"
ILLUSTRATION_ENTRY = mf.illustration_entry(TOOL)


def write_archive(path: Path, members: Dict[str, bytes]) -> Path:
    """Write ``members`` into a fresh zip at ``path`` (deflated, in the given order); return ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def default_page(canonical: str = CANONICAL, illustration: Optional[bytes] = None) -> str:
    """The page the writer produces: ``arc_meta_canonical.page`` over ``canonical``."""
    return arc_meta_canonical.page(ET.fromstring(canonical.encode("utf-8")), illustration)


def toolbox_members(canonical: str = CANONICAL, content: Optional[dict] = None, rc: Optional[dict] = None,
                    page: Optional[str] = None, extra: Optional[Dict[str, bytes]] = None) -> Dict[str, bytes]:
    """The ``Demo.tool/`` members: content, rc and ``tool.metadata.xml`` (``page``, default
    ``default_page(canonical)``), plus ``extra``."""
    shown = page if page is not None else default_page(canonical)
    content = CONTENT if content is None else content
    rc = RC if rc is None else rc
    members = {
        f"{TOOL}.tool/tool.content": json.dumps(content, indent=4).encode("utf-8"),
        f"{TOOL}.tool/tool.content.rc": json.dumps(rc, indent=1).encode("utf-8"),
        f"{TOOL}.tool/tool.metadata.xml": shown.encode("utf-8"),
    }
    members.update(extra or {})
    return members


def make_toolbox(make_project: Callable[..., Path], canonical: str = CANONICAL,
                 members: Optional[Dict[str, bytes]] = None, config: Optional[dict] = None) -> Path:
    """A committed project holding ``ATBX`` at its root and ``tool_metadata/tools/Demo.xml``.

    ``make_project`` writes only text, so the archive is written after it with ``write_archive``
    (``members`` default ``toolbox_members(canonical)``) and committed with ``conftest.git``.
    """
    root = make_project(config=config, files={f"{TOOL_DIR}/{TOOL}.xml": canonical})
    write_archive(root / ATBX, members if members is not None else toolbox_members(canonical))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "toolbox")
    return root
