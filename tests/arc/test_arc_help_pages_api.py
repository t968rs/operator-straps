"""arc-help-pages API: the pages a project has, and the two checks that keep a page and its links honest.

``check_help_page`` reports a page a rebuild would change (``help_page_stale``), a fragment the build refuses
(``fragment_invalid``) and a tool whose canonical XML does not link the page (``help_page_unlinked``).
``check_links`` reads every ``file:`` href in a tool's canonical XML: one under the checkout prefix must name
a file in the current tree (``link_target_missing``), and any other is dead in production
(``link_outside_checkout``). The prefix match ignores case; the checkout prefix is the main checkout's, so the
checks agree when they run from a linked worktree. A tracked page checked out with CRLF line endings
(``core.autocrlf``) is current when its text matches.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import List

import pytest

import arc_help_pages_api as api
import arc_help_pages_config as config
from arc_help_pages_models import HelpProblem, HelpProblemCode
from arc._arc_help_project import (
    CANONICAL, HELP_DIR, MODE_PARAM, PAGE, TOOL, TOOL_DIR, fragment, make_help_project,
)
from conftest import REPO_ROOT, git

SCRIPTS = REPO_ROOT / "plugins" / "arc-straps" / "skills" / "arc-help-pages" / "scripts"
MODULES = ("arc_help_pages_config", "arc_help_pages_models", "arc_help_pages_source", "arc_help_pages_build",
           "arc_help_pages_api")
SURFACE = {"help_pages", "build_page", "apply_help", "check_help_page", "check_links", "format_problems",
           "paths"}


def _codes(problems) -> List[str]:
    return sorted(p.code.value for p in problems)


def _usage(root: Path, html: str) -> None:
    """Rewrite the demo canonical XML under ``root`` with ``html`` as its usage."""
    text = CANONICAL.replace("<p>Usage.</p>", html)
    (root / TOOL_DIR / f"{TOOL}.xml").write_text(text, encoding="utf-8")


def _link(root: Path, href: str) -> None:
    _usage(root, f'<p>See <a href="{href}">the help page</a>.</p>')


def _project(make_project) -> Path:
    return make_help_project(make_project, fragments={PAGE: fragment()})


def test_the_api_binds_the_spec_surface() -> None:
    assert SURFACE <= set(api.__all__)


def test_help_pages_lists_each_fragment_stem(make_project) -> None:
    root = make_help_project(make_project, fragments={"demo": fragment(), "alpha": fragment()})
    assert api.help_pages(repo=root) == ["alpha", "demo"]


def test_check_help_page_reports_a_missing_or_edited_page_as_stale(make_project) -> None:
    root = _project(make_project)
    _link(root, config.paths(root).page_href(PAGE))
    assert _codes(api.check_help_page(PAGE, repo=root)) == ["help_page_stale"]
    api.apply_help(PAGE, apply=True, repo=root)
    assert api.check_help_page(PAGE, repo=root) == []
    target = root / HELP_DIR / f"{PAGE}.html"
    target.write_bytes(target.read_bytes() + b"<!-- edited -->\n")
    assert _codes(api.check_help_page(PAGE, repo=root)) == ["help_page_stale"]


def test_check_help_page_reads_a_crlf_page_as_current(make_project) -> None:
    root = _project(make_project)
    _link(root, config.paths(root).page_href(PAGE))
    target = root / HELP_DIR / f"{PAGE}.html"
    target.write_bytes(api.build_page(PAGE, repo=root).replace("\n", "\r\n").encode("utf-8"))
    assert api.check_help_page(PAGE, repo=root) == []


def test_check_help_page_reports_an_unlinked_page(make_project) -> None:
    root = _project(make_project)
    api.apply_help(PAGE, apply=True, repo=root)
    assert _codes(api.check_help_page(PAGE, repo=root)) == ["help_page_unlinked"]


def test_check_help_page_counts_a_link_to_another_page_as_unlinked(make_project) -> None:
    root = _project(make_project)
    _link(root, config.paths(root).page_href("other"))
    api.apply_help(PAGE, apply=True, repo=root)
    assert _codes(api.check_help_page(PAGE, repo=root)) == ["help_page_unlinked"]


def test_check_help_page_reports_a_page_it_cannot_build_as_one_problem(make_project) -> None:
    """A HelpError from the build (here the canonical XML lacks a tool.content parameter) is one
    help_page_stale problem carrying the refusal, not a traceback and not a second problem."""
    root = make_help_project(make_project, canonical=CANONICAL.replace(MODE_PARAM, ""),
                             fragments={PAGE: fragment()})
    problems = api.check_help_page(PAGE, repo=root)
    assert _codes(problems) == ["help_page_stale"]
    assert "Mode" in problems[0].detail


def test_check_help_page_matches_the_link_prefix_ignoring_case(make_project) -> None:
    root = _project(make_project)
    p = config.paths(root)
    _link(root, p.prefix.upper() + p.page_href(PAGE)[len(p.prefix):])
    api.apply_help(PAGE, apply=True, repo=root)
    assert api.check_help_page(PAGE, repo=root) == []


def test_check_help_page_reports_an_invalid_fragment_alone(make_project) -> None:
    root = make_help_project(make_project, fragments={PAGE: fragment(syntax=False)})
    assert _codes(api.check_help_page(PAGE, repo=root)) == ["fragment_invalid"]


def test_check_links_reports_a_missing_target(make_project) -> None:
    root = _project(make_project)
    _link(root, config.paths(root).prefix + "tool_metadata/tool_help/gone.html")
    assert _codes(api.check_links(TOOL, repo=root)) == ["link_target_missing"]


def test_check_links_decodes_the_tail_and_drops_the_fragment(make_project) -> None:
    root = make_help_project(make_project, fragments={PAGE: fragment()},
                             extra_files={f"{HELP_DIR}/img/a b.png": "png"})
    _link(root, config.paths(root).prefix + "tool_metadata/tool_help/img/a%20b.png#top")
    assert api.check_links(TOOL, repo=root) == []


def test_check_links_reports_a_file_href_outside_the_checkout(make_project) -> None:
    root = _project(make_project)
    _link(root, "file:///Z:/elsewhere/help.html")
    assert _codes(api.check_links(TOOL, repo=root)) == ["link_outside_checkout"]


def test_check_links_ignores_anchors_and_web_links(make_project) -> None:
    root = _project(make_project)
    _usage(root, '<p><a href="#top">Top</a> and <a href="https://example.com/x">web</a>.</p>')
    assert api.check_links(TOOL, repo=root) == []


def test_check_links_reports_relative_hrefs(make_project) -> None:
    """Pro renders the "?" page from a temp copy, so a relative href breaks there (decision D9)."""
    root = _project(make_project)
    _usage(root, '<p><a href="docs/demo.html">a</a>, <a href="../x.html">b</a> and <a href="#top">c</a>.</p>')
    problems = api.check_links(TOOL, repo=root)
    assert _codes(problems) == ["link_relative", "link_relative"]
    details = " | ".join(p.detail for p in problems)
    assert "docs/demo.html" in details and "../x.html" in details and "#top" not in details


def _lower_drive(prefix: str) -> str:
    """``prefix`` with its drive letter lower-cased (``file:///C:/`` -> ``file:///c:/``); else unchanged."""
    return re.sub(r"^(file:///)([A-Za-z]):", lambda m: f"{m.group(1)}{m.group(2).lower()}:", prefix)


@pytest.mark.parametrize("case", ["upper", "lower_drive"])
def test_check_links_matches_the_prefix_ignoring_case(make_project, case: str) -> None:
    """Under a re-cased prefix the present target is clean and the absent one is missing, not outside."""
    root = make_help_project(make_project, fragments={PAGE: fragment()},
                             extra_files={f"{HELP_DIR}/img/a.png": "png"})
    p = config.paths(root)
    prefix = p.prefix.upper() if case == "upper" else _lower_drive(p.prefix)
    _usage(root, f'<p><a href="{prefix}tool_metadata/tool_help/img/a.png">here</a> and '
                 f'<a href="{prefix}tool_metadata/tool_help/gone.html">gone</a>.</p>')
    problems = api.check_links(TOOL, repo=root)
    assert _codes(problems) == ["link_target_missing"]
    assert "gone.html" in problems[0].detail


@pytest.mark.cross_os
def test_the_checks_from_a_worktree_use_the_main_checkout_prefix(make_project, tmp_path) -> None:
    """The linked checkout converts the tracked page to CRLF (core.autocrlf), as a Windows checkout does."""
    root = _project(make_project)
    _link(root, config.paths(root).page_href(PAGE))
    api.apply_help(PAGE, apply=True, repo=root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "page")
    git(root, "config", "core.autocrlf", "true")
    linked = tmp_path / "linked"
    git(root, "worktree", "add", "-q", "--detach", str(linked))
    assert b"\r\n" in (linked / HELP_DIR / f"{PAGE}.html").read_bytes()
    assert api.check_links(TOOL, repo=linked) == []
    assert api.check_help_page(PAGE, repo=linked) == []


def test_format_problems_prints_one_line_each_or_clean() -> None:
    assert api.format_problems([]) == "clean"
    problem = HelpProblem(code=HelpProblemCode.LINK_TARGET_MISSING, subject=TOOL, detail="gone.html")
    assert api.format_problems([problem]) == "link_target_missing | Demo | gone.html"


def test_no_module_of_the_skill_imports_arc_meta() -> None:
    found = []
    for stem in MODULES:
        tree = ast.parse((SCRIPTS / f"{stem}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            found += [f"{stem}: {name}" for name in names if name.split(".")[0].startswith("arc_meta")]
    assert not found, found
