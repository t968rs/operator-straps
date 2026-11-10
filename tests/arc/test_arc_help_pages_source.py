"""arc-help-pages source: what a help page is built from, read from the canonical XML and the archive.

The canonical XML gives the title, the summary and each parameter's attributes and text; the archive gives
the parameter order (``<Tool>.tool/tool.content``) and the toolbox alias (``toolbox.content``). The records
are frozen pydantic models that forbid extra keys, as arc-meta's are.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

import arc_help_pages_models as models
import arc_help_pages_source as source
from arc._arc_help_project import ALIAS, CANONICAL, MODE_PARAM, TOOL, TOOL_DIR, make_help_project


def test_tool_doc_reads_the_canonical_text_and_the_archive_alias(make_project) -> None:
    doc = source.tool_doc(TOOL, repo=make_help_project(make_project))
    assert (doc.name, doc.displayname, doc.alias) == (TOOL, "Demo & Tool", ALIAS)
    assert doc.summary == "Makes polygons."


def test_params_follow_tool_content_order_not_the_canonical_order(make_project) -> None:
    doc = source.tool_doc(TOOL, repo=make_help_project(make_project))
    assert [p.name for p in doc.params] == ["in_poly", "Mode", "Out_Poly", "tolerance"]


def test_param_doc_carries_the_canonical_attributes_and_reference_html(make_project) -> None:
    params = {p.name: p for p in source.tool_doc(TOOL, repo=make_help_project(make_project)).params}
    kinds = models.ParamKind
    assert [params[n].type for n in ("in_poly", "Mode", "Out_Poly")] == [kinds.REQUIRED, kinds.OPTIONAL,
                                                                        kinds.DERIVED]
    assert (params["Out_Poly"].direction, params["in_poly"].direction) == ("Output", "Input")
    assert (params["in_poly"].displayname, params["tolerance"].datatype) == ("Input Polygons", "GPDouble")
    assert params["tolerance"].reference_html == "<p>Distance in <b>feet</b>.</p>"
    assert params["in_poly"].reference_html == "<p>Polygons &lt;to&gt; process.</p>"
    assert params["Mode"].reference_html == ""


def test_a_tool_content_param_missing_from_the_canonical_xml_is_refused(make_project) -> None:
    root = make_help_project(make_project, canonical=CANONICAL.replace(MODE_PARAM, ""))
    with pytest.raises(models.HelpError, match="Mode"):
        source.tool_doc(TOOL, repo=root)


def test_a_tool_needs_both_its_canonical_xml_and_its_archive_entry(make_project) -> None:
    root = make_help_project(make_project)
    (root / TOOL_DIR / "Other.xml").write_text(CANONICAL.replace('name="Demo"', 'name="Other"'),
                                               encoding="utf-8")
    assert source.has_tool(TOOL, repo=root)
    assert not source.has_tool("Other", repo=root) and not source.has_tool("Ghost", repo=root)
    with pytest.raises(models.HelpError):
        source.tool_doc("Ghost", repo=root)


def test_records_are_frozen_and_forbid_extra_keys() -> None:
    param = models.ParamDoc(name="x", displayname="X", type=models.ParamKind.REQUIRED, direction="Input",
                            datatype="GPString", reference_html="")
    with pytest.raises(ValidationError):
        param.name = "y"
    with pytest.raises(ValidationError):
        models.ParamDoc.model_validate({**param.model_dump(), "extra": 1})
    assert issubclass(models.FragmentError, models.HelpError) and issubclass(models.HelpError, ValueError)


def test_problem_codes_spell_the_spec_values() -> None:
    """The spec's five codes, then link_relative (decision D9)."""
    assert [code.value for code in models.HelpProblemCode] == [
        "help_page_stale", "help_page_unlinked", "fragment_invalid", "link_target_missing",
        "link_outside_checkout", "link_relative"]
