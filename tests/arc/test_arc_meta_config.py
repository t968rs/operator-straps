"""arc-meta paths: the plugins.arc-straps section resolved against one project."""
from __future__ import annotations

import json
import sys

import pytest

import arc_meta_config
from harness_lib.config import ConfigError, activate, load_config

SECTION = "arc-straps"


def _cfg(**meta) -> dict:
    return {"plugins": {SECTION: {"arc_meta": meta}}}


def test_defaults_find_the_only_archive(make_project) -> None:
    root = make_project(files={"box.atbx": "zip"})
    p = arc_meta_config.paths(root)
    assert p.atbx == root / "box.atbx"
    assert p.tool_dir == root / "tool_metadata" / "tools"
    assert p.toolbox_source == root / "tool_metadata" / "box.atbx.xml"
    assert p.registry is None


def test_overrides_win(make_project) -> None:
    root = make_project(_cfg(atbx="tbx/x.atbx", tool_dir="help/tools/", toolbox_source="help/tb.xml",
                             registry="reg.json"))
    p = arc_meta_config.paths(root)
    assert (p.atbx, p.tool_dir) == (root / "tbx" / "x.atbx", root / "help" / "tools")
    assert (p.toolbox_source, p.registry) == (root / "help" / "tb.xml", root / "reg.json")


@pytest.mark.parametrize("files,match", [({}, "no .atbx"), ({"a.atbx": "z", "b.atbx": "z"}, "2 .atbx files")])
def test_ambiguous_archive_is_refused(make_project, files: dict, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        arc_meta_config.paths(make_project(files=files))


def test_schema_refuses_unknown_and_absolute(make_project) -> None:
    with pytest.raises(ConfigError, match="plugins/arc-straps"):
        arc_meta_config.paths(make_project(_cfg(nope=1)))
    with pytest.raises(ConfigError, match="plugins/arc-straps/arc_meta/atbx"):
        arc_meta_config.paths(make_project(_cfg(atbx="C:/x.atbx")))


def test_defaults_validate_against_the_schema(repo_root) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    config = repo_root / "plugins" / "arc-straps" / "config"
    defaults = json.loads((config / "defaults.json").read_text(encoding="utf-8"))
    schema = json.loads((config / "arc-straps.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(defaults)


def test_a_subfolder_reads_the_project_config(make_project) -> None:
    root = make_project(_cfg(atbx="box.atbx"), files={"box.atbx": "z", "sub/k.txt": "x"})
    assert arc_meta_config.paths(root / "sub").atbx == root / "box.atbx"


@pytest.mark.parametrize("meta,key", [({"tool_dir": "."}, "toolbox_source"), ({"atbx": "../x.atbx"}, "atbx")])
def test_paths_outside_the_project_are_refused(make_project, meta: dict, key: str) -> None:
    root = make_project(_cfg(**meta), files={"box.atbx": "z"})
    with pytest.raises(ConfigError, match=rf"arc_meta\.{key}: resolves outside the project root"):
        arc_meta_config.paths(root)


BAD_TYPES = [({"arc_meta": 3}, r"arc_meta: must be an object"),
             ({"arc_meta": {"atbx": 3}}, r"arc_meta\.atbx: must be"),
             ({"arc_meta": {"tool_dir": None}}, r"arc_meta\.tool_dir: must be")]


@pytest.mark.parametrize("section,match", BAD_TYPES)
def test_bad_types_raise_config_error_without_jsonschema(make_project, monkeypatch: pytest.MonkeyPatch,
                                                         section: dict, match: str) -> None:
    root = make_project({"plugins": {SECTION: section}}, files={"box.atbx": "z"})
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError, match=match):
        arc_meta_config.paths(root)


def test_no_repo_reads_the_active_project(make_project) -> None:
    root = make_project(_cfg(atbx="tbx/x.atbx"))
    activate(load_config(root))
    assert arc_meta_config.paths().atbx == root / "tbx" / "x.atbx"
