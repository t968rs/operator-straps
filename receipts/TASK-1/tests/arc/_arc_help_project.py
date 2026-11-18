"""A demo project for arc-help-pages tests: one archive, its canonical XML, a page template and fragments.

Imports nothing from arc-meta, so the tests of a skill that must not import arc-meta do not lean on it. The
canonical XML lists the parameters in another order than ``tool.content``, so a test can tell which order a
page follows. ``fragment`` reads the marker spellings from ``arc_help_pages_build`` when called, never at
import time.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Callable, Dict, Optional

from conftest import git

TOOL = "Demo"
PAGE = "demo"
ALIAS = "demo"
ATBX = "demo_toolbox.atbx"
TOOL_DIR = "tool_metadata/tools"
HELP_DIR = "tool_metadata/tool_help"
SIGNATURE = "arcpy.demo.Demo(in_poly, {Mode}, tolerance)"

# Dialog order: required, optional, derived, then a required parameter after the optional one.
CONTENT: dict = {
    "type": "ScriptTool",
    "displayname": "$rc:title",
    "params": {
        "in_poly": {"displayname": "$rc:in_poly.title", "datatype": {"type": "GPFeatureLayer"}},
        "Mode": {"type": "optional", "displayname": "$rc:mode.title", "datatype": {"type": "GPString"}},
        "Out_Poly": {"type": "derived", "direction": "out", "displayname": "$rc:out_poly.title",
                     "datatype": {"type": "GPFeatureLayer"}},
        "tolerance": {"displayname": "$rc:tolerance.title", "datatype": {"type": "GPDouble"}},
    },
}

MODE_PARAM = """      <param name="Mode" displayname="Mode" type="Optional" direction="Input" \
datatype="GPString">
        <dialogReference><para></para></dialogReference>
      </param>
"""

CANONICAL: str = """<?xml version="1.0"?>
<metadata xml:lang="en">
  <Esri><ArcGISFormat>1.0</ArcGISFormat><ArcGISProfile>ItemDescription</ArcGISProfile></Esri>
  <tool name="Demo" displayname="Demo &amp; Tool" xmlns="">
    <summary><![CDATA[<p>Makes <b>polygons</b>.</p>]]></summary>
    <usage><![CDATA[<p>Usage.</p>]]></usage>
    <parameters>
      <param name="tolerance" displayname="Tolerance" type="Required" direction="Input" datatype="GPDouble">
        <dialogReference><![CDATA[<p>Distance in <b>feet</b>.</p>]]></dialogReference>
      </param>
      <param name="Out_Poly" displayname="Output Polygons" type="Derived" direction="Output" \
datatype="GPFeatureLayer">
        <dialogReference><para>Derived output.</para></dialogReference>
      </param>
      <param name="in_poly" displayname="Input Polygons" type="Required" direction="Input" \
datatype="GPFeatureLayer">
        <dialogReference><para>Polygons &lt;to&gt; process.</para></dialogReference>
      </param>
""" + MODE_PARAM + """    </parameters>
  </tool>
</metadata>
"""

TEMPLATE: str = (
    "<!DOCTYPE html>\n<html><head><title>$title</title></head><body>\n"
    "<header><h1>$title</h1><p>$summary</p></header>\n"
    "<nav>$nav</nav>\n<main>\n$sections\n<footer>$footer</footer>\n</main></body></html>\n"
)

OVERVIEW = '<section class="panel" id="overview"><h2>Overview</h2><p>What it does.</p></section>'
SCALE = '<section class="panel" id="scale"><h2>Large <em>inputs</em></h2><p>Big.</p></section>'


def fragment(tool: str = TOOL, tool_line: bool = True, parameters: bool = True, syntax: bool = True,
             extra: str = "") -> str:
    """A fragment for ``tool``: the tool line, two story sections and both markers, each part optional."""
    import arc_help_pages_build as build

    lines = [build.tool_line(tool)] if tool_line else []
    lines.append(OVERVIEW)
    lines += [build.PARAMETERS_MARKER] if parameters else []
    lines.append(SCALE)
    lines += [build.SYNTAX_MARKER] if syntax else []
    lines += [extra] if extra else []
    return "\n".join(lines) + "\n"


def write_archive(path: Path, members: Dict[str, bytes]) -> Path:
    """Write ``members`` into a fresh zip at ``path``; return ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def archive_members(content: Optional[dict] = None, alias: str = ALIAS) -> Dict[str, bytes]:
    """``toolbox.content`` with the alias and the tool's ``tool.content``."""
    tool_content = CONTENT if content is None else content
    return {
        "toolbox.content": json.dumps({"version": "1.0", "alias": alias}).encode("utf-8"),
        f"{TOOL}.tool/tool.content": json.dumps(tool_content, indent=4).encode("utf-8"),
    }


def make_help_project(make_project: Callable[..., Path], canonical: str = CANONICAL,
                      fragments: Optional[Dict[str, str]] = None, template: str = TEMPLATE,
                      members: Optional[Dict[str, bytes]] = None, config: Optional[dict] = None,
                      extra_files: Optional[Dict[str, str]] = None) -> Path:
    """A committed project: ``ATBX`` at the root, ``<TOOL_DIR>/Demo.xml``, the template and the fragments
    under ``HELP_DIR``, plus ``extra_files``. The archive is written after ``make_project`` (which writes only
    text) and committed with ``conftest.git``."""
    files = {f"{TOOL_DIR}/{TOOL}.xml": canonical, f"{HELP_DIR}/_template.html": template}
    files.update({f"{HELP_DIR}/_fragments/{page}.html": text for page, text in (fragments or {}).items()})
    files.update(extra_files or {})
    root = make_project(config=config, files=files)
    write_archive(root / ATBX, archive_members() if members is None else members)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "toolbox")
    return root
