"""Contract tests for the ``working_refs.max_chars`` config key: default, typed load, validation, README row."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from harness_lib.config import ConfigError, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = REPO_ROOT / "plugins" / "harness" / "config" / "defaults.json"


def test_max_chars_defaults_to_the_defaults_json_value(make_project) -> None:
    from harness_lib.config import WorkingRefsConfig
    cfg = load_config(make_project())
    assert isinstance(cfg.working_refs, WorkingRefsConfig)
    default = json.loads(DEFAULTS.read_text(encoding="utf-8"))["working_refs"]["max_chars"]
    assert cfg.working_refs.max_chars == default
    assert isinstance(default, int) and default > 0


def test_max_chars_reads_the_project_value(make_project) -> None:
    from harness_lib.config import WorkingRefsConfig
    cfg = load_config(make_project({"working_refs": {"max_chars": 80}}))
    assert cfg.working_refs == WorkingRefsConfig(max_chars=80)
    hash(cfg)


@pytest.mark.parametrize("bad", [0, -5, "120", 1.5, True], ids=["zero", "negative", "text", "float", "bool"])
def test_a_bad_max_chars_raises_naming_the_field(make_project, bad) -> None:
    with pytest.raises(ConfigError, match="working_refs/max_chars"):
        load_config(make_project({"working_refs": {"max_chars": bad}}))


def test_an_unknown_working_refs_key_raises(make_project) -> None:
    with pytest.raises(ConfigError, match=r"working_refs: .*max_char"):
        load_config(make_project({"working_refs": {"max_char": 80}}))


@pytest.mark.parametrize("bad", [0, "120", True], ids=["zero", "text", "bool"])
def test_a_bad_max_chars_raises_without_jsonschema(make_project, monkeypatch: pytest.MonkeyPatch, bad) -> None:
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError, match="working_refs/max_chars"):
        load_config(make_project({"working_refs": {"max_chars": bad}}))


def test_an_unknown_key_raises_without_jsonschema(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError, match=r"working_refs: .*max_char"):
        load_config(make_project({"working_refs": {"max_char": 80}}))


def test_readme_documents_the_key() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "| `working_refs.max_chars`" in readme
