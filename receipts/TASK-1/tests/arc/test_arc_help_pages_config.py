"""arc-help-pages paths: the plugins.arc-straps.arc_help_pages section resolved against one project.

The section resolves by the same rules as ``arc_meta`` but on its own: its own defaults, its own type checks
(also without ``jsonschema``) and its own archive lookup. ``root`` is the checkout the call runs in;
``checkout_root`` is the main checkout of its repository, so an href written against the main checkout
still matches when the checks run from a linked worktree.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List

import pytest

import arc_help_pages_config
from conftest import git
from harness_lib.config import ConfigError, activate, load_config

SECTION = "arc-straps"
KEYS = {"atbx", "tool_dir", "help_dir"}


def _cfg(**section) -> dict:
    return {"plugins": {SECTION: {"arc_help_pages": section}}}


def test_defaults_resolve_every_location(make_project) -> None:
    root = make_project(files={"box.atbx": "zip"})
    p = arc_help_pages_config.paths(root)
    assert (p.atbx, p.tool_dir, p.help_dir) == (
        root / "box.atbx", root / "tool_metadata" / "tools", root / "tool_metadata" / "tool_help")
    assert p.root == root and p.checkout_root.resolve() == root.resolve()


def test_overrides_win(make_project) -> None:
    root = make_project(_cfg(atbx="tbx/x.atbx", tool_dir="help/tools/", help_dir="help/pages"))
    p = arc_help_pages_config.paths(root)
    assert (p.atbx, p.tool_dir, p.help_dir) == (
        root / "tbx" / "x.atbx", root / "help" / "tools", root / "help" / "pages")


def test_the_section_resolves_apart_from_arc_meta(make_project) -> None:
    config = {"plugins": {SECTION: {"arc_meta": {"atbx": "a.atbx", "tool_dir": "meta/tools"},
                                    "arc_help_pages": {"atbx": "b.atbx"}}}}
    root = make_project(config)
    p = arc_help_pages_config.paths(root)
    assert (p.atbx, p.tool_dir) == (root / "b.atbx", root / "tool_metadata" / "tools")


@pytest.mark.cross_os
def test_checkout_root_from_a_worktree_is_the_main_checkout(make_project, tmp_path) -> None:
    root = make_project(_cfg(atbx="box.atbx"), files={"box.atbx": "z"})
    linked = tmp_path / "linked"
    git(root, "worktree", "add", "-q", "--detach", str(linked))
    p = arc_help_pages_config.paths(linked)
    assert p.root.resolve() == linked.resolve()
    assert p.checkout_root.resolve() == root.resolve()
    assert p.atbx.resolve() == (linked / "box.atbx").resolve()


@pytest.mark.cross_os
def test_page_href_is_the_main_checkout_uri_plus_the_repo_path(make_project, tmp_path) -> None:
    root = make_project(_cfg(atbx="box.atbx"), files={"box.atbx": "z"})
    linked = tmp_path / "linked"
    git(root, "worktree", "add", "-q", "--detach", str(linked))
    p = arc_help_pages_config.paths(linked)
    assert p.prefix == p.checkout_root.as_uri() + "/"
    assert p.page_href("demo") == p.prefix + "tool_metadata/tool_help/demo.html"


def test_checkout_root_outside_git_falls_back_to_the_root(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    folder = tmp_path / "nogit"
    folder.mkdir()
    (folder / "box.atbx").write_text("z", encoding="utf-8")
    p = arc_help_pages_config.paths(folder)
    assert p.root.resolve() == folder.resolve() == p.checkout_root.resolve()
    assert p.page_href("demo") == p.checkout_root.as_uri() + "/tool_metadata/tool_help/demo.html"


@pytest.mark.parametrize("files,match", [({}, "no .atbx"), ({"a.atbx": "z", "b.atbx": "z"}, "2 .atbx files")],
                         ids=["none", "two"])
def test_an_ambiguous_archive_is_refused(make_project, files: dict, match: str) -> None:
    with pytest.raises(ConfigError, match=rf"{match}.*arc_help_pages\.atbx"):
        arc_help_pages_config.paths(make_project(files=files))


def test_unknown_keys_are_refused(make_project) -> None:
    with pytest.raises(ConfigError, match="arc_help_pages"):
        arc_help_pages_config.paths(make_project(_cfg(nope=1), files={"box.atbx": "z"}))


BAD_TYPES = [({"arc_help_pages": 3}, r"arc_help_pages: must be an object"),
             ({"arc_help_pages": {"atbx": 3}}, r"arc_help_pages\.atbx: must be"),
             ({"arc_help_pages": {"help_dir": None}}, r"arc_help_pages\.help_dir: must be"),
             ({"arc_help_pages": {"tool_dir": ""}}, r"arc_help_pages\.tool_dir: must not be empty")]


@pytest.mark.parametrize("section,match", BAD_TYPES, ids=["section", "atbx", "help_dir", "tool_dir"])
def test_bad_types_raise_config_error_without_jsonschema(make_project, monkeypatch: pytest.MonkeyPatch,
                                                         section: dict, match: str) -> None:
    root = make_project({"plugins": {SECTION: section}}, files={"box.atbx": "z"})
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError, match=match):
        arc_help_pages_config.paths(root)


OUTSIDE = [({"help_dir": "../pages"}, "help_dir"), ({"atbx": "../x.atbx"}, "atbx")]


@pytest.mark.parametrize("section,key", OUTSIDE, ids=["help_dir", "atbx"])
def test_locations_outside_the_project_are_refused(make_project, section: dict, key: str) -> None:
    root = make_project(_cfg(**section), files={"box.atbx": "z"})
    with pytest.raises(ConfigError, match=rf"arc_help_pages\.{key}: resolves outside the project root"):
        arc_help_pages_config.paths(root)


def test_defaults_and_schema_carry_the_section(repo_root) -> None:
    config = repo_root / "plugins" / "arc-straps" / "config"
    defaults = json.loads((config / "defaults.json").read_text(encoding="utf-8"))
    schema = json.loads((config / "arc-straps.schema.json").read_text(encoding="utf-8"))
    assert defaults.get("arc_help_pages") == {
        "atbx": None, "tool_dir": "tool_metadata/tools", "help_dir": "tool_metadata/tool_help"}
    section = schema["properties"].get("arc_help_pages", {})
    assert set(section.get("properties", {})) == KEYS and section.get("additionalProperties") is False


def _first_table_keys(text: str, marker: str) -> List[str]:
    """The backticked first cells of the first Markdown table after the first ``marker`` in ``text``."""
    after = text.partition(marker)[2].splitlines()
    start = next((n for n, line in enumerate(after) if line.startswith("|")), len(after))
    rows = []
    for line in after[start:]:
        if not line.startswith("|"):
            break
        rows.append(line)
    return re.findall(r"^\|\s*`([^`]+)`\s*\|", "\n".join(rows), re.MULTILINE)


def test_the_plugin_readme_documents_every_key(repo_root) -> None:
    """The first table after the section's first mention lists exactly the arc_help_pages keys."""
    text = (repo_root / "plugins" / "arc-straps" / "README.md").read_text(encoding="utf-8")
    assert set(_first_table_keys(text, "`plugins.arc-straps.arc_help_pages`")) == KEYS


def test_no_repo_reads_the_active_project(make_project) -> None:
    root = make_project(_cfg(atbx="tbx/x.atbx"))
    activate(load_config(root))
    assert arc_help_pages_config.paths().atbx == root / "tbx" / "x.atbx"
