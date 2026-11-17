"""``plugin_section``: a plugin's defaults merged under its harness.json section and checked by its schema."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from harness_lib.config import ConfigError, activate, load_config
from harness_lib.plugin_config import plugin_section

SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"x": {"type": "object", "additionalProperties": False,
                               "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}}}


@pytest.fixture()
def files(tmp_path: Path) -> tuple:
    defaults, schema = tmp_path / "defaults.json", tmp_path / "schema.json"
    defaults.write_text(json.dumps({"x": {"a": "d", "b": 1}}), encoding="utf-8")
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    return defaults, schema


def test_defaults_without_a_section(make_project, files: tuple) -> None:
    cfg = load_config(make_project())
    assert plugin_section("demo", *files, cfg=cfg) == {"x": {"a": "d", "b": 1}}


def test_section_merges_over_defaults(make_project, files: tuple) -> None:
    cfg = load_config(make_project({"plugins": {"demo": {"x": {"b": 2}}}}))
    assert plugin_section("demo", *files, cfg=cfg) == {"x": {"a": "d", "b": 2}}


def test_schema_defect_names_the_path(make_project, files: tuple) -> None:
    cfg = load_config(make_project({"plugins": {"demo": {"x": {"b": "two"}}}}))
    with pytest.raises(ConfigError, match=r"plugins/demo/x/b"):
        plugin_section("demo", *files, cfg=cfg)


def test_no_schema_skips_validation(make_project, files: tuple) -> None:
    cfg = load_config(make_project({"plugins": {"demo": {"y": 1}}}))
    assert plugin_section("demo", files[0], cfg=cfg)["y"] == 1


def test_unknown_key_without_jsonschema(make_project, files: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_config(make_project({"plugins": {"demo": {"y": 1}}}))
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError, match=r"plugins/demo: unknown keys \['y'\]"):
        plugin_section("demo", *files, cfg=cfg)


def test_unreadable_defaults_raise(make_project, tmp_path: Path) -> None:
    cfg = load_config(make_project())
    with pytest.raises(ConfigError, match="missing.json"):
        plugin_section("demo", tmp_path / "missing.json", cfg=cfg)


def test_open_schema_flags_nothing_without_jsonschema(make_project, files: tuple,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    files[1].write_text(json.dumps({"type": "object", "properties": {}}), encoding="utf-8")
    cfg = load_config(make_project({"plugins": {"demo": {"y": 1}}}))
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    assert plugin_section("demo", *files, cfg=cfg) == {"x": {"a": "d", "b": 1}, "y": 1}


def test_no_cfg_reads_the_active_config(make_project, files: tuple) -> None:
    activate(load_config(make_project({"plugins": {"demo": {"x": {"b": 3}}}})))
    assert plugin_section("demo", *files) == {"x": {"a": "d", "b": 3}}
