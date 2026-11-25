"""arc-help-pages build: a fragment and the canonical XML filled into the project's page template.

The template's ``string.Template`` slots take the title, the summary, the nav, the sections and the footer.
The sections are the fragment's own, with the generated Parameters and Python syntax sections placed at its
two markers; the nav lists every section by its ``id`` and ``<h2>``. A fragment the build cannot place is
refused with ``FragmentError``. A rebuild of unchanged sources is byte-identical wherever the project sits,
and matches a golden page; ``apply_help`` is a dry run unless ``apply=True`` and compares pages without
regard to line endings, since a checkout with ``core.autocrlf`` holds the tracked page with CRLF.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

import arc_help_pages_build as build
from arc_help_pages_models import FragmentError, HelpError
from arc._arc_help_project import (
    ATBX, HELP_DIR, OVERVIEW, PAGE, SIGNATURE, TOOL, archive_members, fragment, make_help_project,
)

SLOTS = ("$title", "$summary", "$nav", "$sections", "$footer")
THEAD = ("<table><thead><tr><th>Python parameter</th><th>Label</th><th>Description</th>"
         "<th>ArcGIS data type</th></tr></thead><tbody>")
DRY_RUN = "DRY-RUN: nothing written. Re-run with apply=True to write."

# A one-input, one-derived-output tool and a template without the footer slot, for the golden page.
MINI_CONTENT: dict = {"params": {
    "in_poly": {"datatype": {"type": "GPFeatureLayer"}},
    "Out": {"type": "derived", "direction": "out", "datatype": {"type": "GPFeatureLayer"}},
}}
MINI_CANONICAL = """<?xml version="1.0"?>
<metadata xml:lang="en">
  <tool name="Demo" displayname="Mini" xmlns="">
    <summary><![CDATA[<p>Does it.</p>]]></summary>
    <parameters>
      <param name="in_poly" displayname="Input" type="Required" direction="Input" datatype="GPFeatureLayer">
        <dialogReference><para>In.</para></dialogReference>
      </param>
      <param name="Out" displayname="Output" type="Derived" direction="Output" datatype="GPFeatureLayer">
        <dialogReference><para></para></dialogReference>
      </param>
    </parameters>
  </tool>
</metadata>
"""
MINI_TEMPLATE = "<h1>$title</h1><p>$summary</p><nav>$nav</nav>\n$sections\n"
GOLDEN = (
    '<h1>Mini</h1><p>Does it.</p><nav><a href="#overview">Overview</a><a href="#parameters">Parameters</a>'
    '<a href="#syntax">Python syntax</a></nav>\n'
    '<section class="panel" id="overview"><h2>Overview</h2><p>What it does.</p></section>\n'
    '<section class="panel" id="parameters"><h2>Parameters</h2>' + THEAD +
    '<tr><td>in_poly</td><td>Input</td><td><p>In.</p></td><td>GPFeatureLayer</td></tr>'
    '<tr><td>Out <span class="tag">derived</span></td><td>Output</td><td>No description.</td>'
    '<td>GPFeatureLayer</td></tr></tbody></table></section>\n'
    '<section class="panel" id="syntax"><h2>Python syntax</h2>'
    '<pre><code>import arcpy\narcpy.ImportToolbox(r"&lt;folder&gt;\\demo_toolbox.atbx")\n'
    'arcpy.demo.Demo(in_poly)</code></pre>'
    '<p><code>ImportToolbox</code> adds the tools of demo_toolbox.atbx to arcpy under the toolbox alias '
    '<code>demo</code>; &lt;folder&gt; stands for the folder that holds it.</p>'
    '<p>Derived output: <code>Out</code></p></section>\n'
)


def _project(make_project, text: Optional[str] = None) -> Path:
    """The demo project with one fragment, ``text`` or the default ``fragment()``."""
    return make_help_project(make_project, fragments={PAGE: fragment() if text is None else text})


def _section(html: str, section_id: str) -> str:
    """The body of the section whose ``id`` is ``section_id``."""
    return html.partition(f'id="{section_id}"')[2].partition("</section>")[0]


def test_template_fill_replaces_every_slot(make_project) -> None:
    html = build.build_page(PAGE, repo=_project(make_project))
    assert not [slot for slot in SLOTS if slot in html]
    assert "<title>Demo &amp; Tool</title>" in html and "<h1>Demo &amp; Tool</h1>" in html
    assert "<p>Makes polygons.</p>" in html
    assert '<section class="panel" id="overview"><h2>Overview</h2><p>What it does.</p></section>' in html


def test_nav_lists_each_section_by_id_and_h2_in_page_order(make_project) -> None:
    html = build.build_page(PAGE, repo=_project(make_project))
    nav = html.partition("<nav>")[2].partition("</nav>")[0]
    assert nav == ('<a href="#overview">Overview</a><a href="#parameters">Parameters</a>'
                   '<a href="#scale">Large inputs</a><a href="#syntax">Python syntax</a>')


def test_parameters_table_follows_tool_content_order_with_tags(make_project) -> None:
    table = _section(build.build_page(PAGE, repo=_project(make_project)), "parameters")
    assert THEAD in table and table.endswith("</tbody></table>"), table
    order = [table.index(f"<td>{name}") for name in ("in_poly", "Mode", "Out_Poly", "tolerance")]
    assert order == sorted(order)
    assert '<td>Mode <span class="tag">optional</span></td>' in table
    assert '<td>Out_Poly <span class="tag">derived</span></td>' in table
    assert "<td>No description.</td>" in table
    assert "<td><p>Distance in <b>feet</b>.</p></td>" in table
    assert "<td><p>Polygons &lt;to&gt; process.</p></td>" in table
    assert "<td>Input Polygons</td>" in table and "<td>GPDouble</td>" in table


def test_syntax_braces_optional_params_and_lists_derived_outputs_after_it(make_project) -> None:
    syntax = _section(build.build_page(PAGE, repo=_project(make_project)), "syntax")
    assert SIGNATURE in syntax
    assert syntax.index("Out_Poly") > syntax.index(SIGNATURE)


def test_syntax_imports_the_toolbox_by_file_name_before_the_call(make_project) -> None:
    """``arcpy.<alias>`` exists only after ``arcpy.ImportToolbox``, so the block imports the archive first.
    It names the archive file and no folder, which keeps the page free of paths."""
    root = _project(make_project)
    syntax = _section(build.build_page(PAGE, repo=root), "syntax")
    code = syntax.partition("<code>")[2].partition("</code>")[0]
    assert code.splitlines() == ["import arcpy", f'arcpy.ImportToolbox(r"&lt;folder&gt;\\{ATBX}")', SIGNATURE]
    assert str(root) not in syntax and root.as_posix() not in syntax


REFUSALS = {
    "no_tool_line": {"tool_line": False},
    "unknown_tool": {"tool": "Ghost"},
    "no_parameters": {"parameters": False},
    "no_syntax": {"syntax": False},
    "no_section_id": {"extra": '<section class="panel"><h2>Notes</h2><p>x</p></section>'},
    "no_section_h2": {"extra": '<section class="panel" id="notes"><p>x</p></section>'},
    "reserved_parameters_id": {"extra": '<section class="panel" id="parameters"><h2>P</h2></section>'},
    "reserved_syntax_id": {"extra": '<section class="panel" id="syntax"><h2>S</h2></section>'},
    "duplicate_id": {"extra": OVERVIEW},
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_fragment_refusals(make_project, case: str) -> None:
    root = _project(make_project, fragment(**REFUSALS[case]))
    with pytest.raises(FragmentError):
        build.build_page(PAGE, repo=root)


def test_archive_without_alias_is_refused(make_project) -> None:
    root = make_help_project(make_project, members=archive_members(alias=""), fragments={PAGE: fragment()})
    with pytest.raises(HelpError, match="has no alias"):
        build.build_page(PAGE, repo=root)


def test_rebuild_is_byte_identical_and_apply_writes_it(make_project) -> None:
    root = _project(make_project)
    first = build.build_page(PAGE, repo=root)
    assert build.build_page(PAGE, repo=root) == first
    target = root / HELP_DIR / f"{PAGE}.html"
    dry = build.apply_help(PAGE, repo=root)
    assert (dry.changed, dry.applied, target.exists()) == (True, False, False)
    assert any("DRY-RUN" in line for line in dry.lines), dry.lines
    done = build.apply_help(PAGE, apply=True, repo=root)
    assert (done.changed, done.applied, target.read_bytes()) == (True, True, first.encode("utf-8"))
    again = build.apply_help(PAGE, apply=True, repo=root)
    assert (again.changed, again.applied) == (False, False)
    assert any("UP TO DATE" in line for line in again.lines), again.lines


def test_the_marker_spellings_are_the_fragment_contract() -> None:
    """Pinned as literals: a project's fragments spell these lines by hand, so a renamed constant that
    changed the spelling would orphan every fragment written against it (decision D3)."""
    assert build.tool_line("Demo") == "<!-- help:tool Demo -->"
    assert build.PARAMETERS_MARKER == "<!-- help:parameters -->"
    assert build.SYNTAX_MARKER == "<!-- help:syntax -->"


def test_the_footer_is_one_fixed_line(make_project) -> None:
    """The footer names no path, time or version, so a rebuild stays byte-identical (decision D4)."""
    assert build.FOOTER == ("Built by arc-help-pages from the canonical tool help and a page fragment. "
                            "Edit those sources, not this page.")
    html = build.build_page(PAGE, repo=_project(make_project))
    assert f"<footer>{build.FOOTER}</footer>" in html


def test_the_build_matches_the_golden_page_wherever_the_project_sits(make_project) -> None:
    """Two projects at different paths build the same bytes, equal to GOLDEN: no path, no date stamp."""
    text = "\n".join([build.tool_line(TOOL), OVERVIEW, build.PARAMETERS_MARKER, build.SYNTAX_MARKER]) + "\n"
    roots = [make_help_project(make_project, canonical=MINI_CANONICAL, template=MINI_TEMPLATE,
                               members=archive_members(content=MINI_CONTENT), fragments={PAGE: text})
             for _ in range(2)]
    assert roots[0] != roots[1]
    assert [build.build_page(PAGE, repo=root) for root in roots] == [GOLDEN, GOLDEN]


def test_the_dry_run_report_names_the_page_and_ends_with_the_notice(make_project) -> None:
    """The skill prints ``"\\n".join(apply_help(name).lines)``; that text names the page it would write."""
    root = _project(make_project)
    report = "\n".join(build.apply_help(PAGE, repo=root).lines)
    assert f"{HELP_DIR}/{PAGE}.html" in report, report
    assert report.splitlines()[-1] == DRY_RUN, report
    assert not (root / HELP_DIR / f"{PAGE}.html").exists()


def test_a_crlf_checkout_of_the_page_is_up_to_date(make_project) -> None:
    root = _project(make_project)
    target = root / HELP_DIR / f"{PAGE}.html"
    crlf = build.build_page(PAGE, repo=root).replace("\n", "\r\n").encode("utf-8")
    target.write_bytes(crlf)
    outcome = build.apply_help(PAGE, apply=True, repo=root)
    assert (outcome.changed, outcome.applied) == (False, False), outcome.lines
    assert target.read_bytes() == crlf
