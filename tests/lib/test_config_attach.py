"""Contract tests for the ``attach.auto_resolve`` config key: default, typed load, validation, README row."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from harness_lib.config import ConfigError, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]

BAD_RULES = [
    pytest.param({"attach": {"auto_resolve": [{"pattern": "*.json", "in_favor_of": "neither"}]}},
                 id="unknown-side"),
    pytest.param({"attach": {"auto_resolve": [{"pattern": "*.json"}]}}, id="missing-side"),
]


def test_attach_auto_resolve_defaults_to_empty(make_project) -> None:
    cfg = load_config(make_project())
    assert cfg.attach.auto_resolve == ()


def test_attach_auto_resolve_loads_rules_in_order(make_project) -> None:
    from harness_lib.config import AutoResolve
    cfg = load_config(make_project({"attach": {"auto_resolve": [
        {"pattern": "*offlineTestReport.json", "in_favor_of": "branch"},
        {"pattern": "docs/generated/*", "in_favor_of": "worktree"},
    ]}}))
    assert cfg.attach.auto_resolve == (AutoResolve("*offlineTestReport.json", "branch"),
                                       AutoResolve("docs/generated/*", "worktree"))
    assert hash(cfg) == hash(cfg)


@pytest.mark.parametrize("bad", BAD_RULES)
def test_invalid_rules_raise_naming_the_field(make_project, bad: dict) -> None:
    with pytest.raises(ConfigError, match="in_favor_of"):
        load_config(make_project(bad))


@pytest.mark.parametrize("bad", BAD_RULES)
def test_invalid_rules_raise_without_jsonschema(make_project, monkeypatch: pytest.MonkeyPatch,
                                                bad: dict) -> None:
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError, match="in_favor_of"):
        load_config(make_project(bad))


def test_an_empty_glob_raises_without_jsonschema(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    with pytest.raises(ConfigError, match="auto_resolve/0/pattern"):
        load_config(make_project({"attach": {"auto_resolve": [{"pattern": "", "in_favor_of": "branch"}]}}))


def test_the_readme_key_table_names_the_key() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "| `attach.auto_resolve`" in text
