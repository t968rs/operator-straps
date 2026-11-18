"""The ``strap.target`` and ``agents_dir`` configuration keys in the four places a key lives.

Pins the defaults (``project`` and ``.claude/agents/``), an override read back from ``harness.json``, and the
schema and README entries.
"""
from __future__ import annotations

import json

from conftest import PLUGIN_ROOT, REPO_ROOT
from harness_lib.config import ConfigError, load_config


def _loaded(make_project, config: dict):
    """The configuration of a fresh project; a refused file fails the test as an AssertionError."""
    root = make_project(config=config)
    try:
        return load_config(root)
    except ConfigError as exc:
        raise AssertionError(str(exc)) from exc


def test_strap_target_defaults_to_project(make_project) -> None:
    assert _loaded(make_project, {}).strap.target == "project"


def test_strap_target_reads_the_override(make_project) -> None:
    assert _loaded(make_project, {"strap": {"target": "harness"}}).strap.target == "harness"


def test_agents_dir_defaults_beside_skills_dir(make_project) -> None:
    cfg = _loaded(make_project, {})
    assert (cfg.skills_dir, cfg.agents_dir) == (".claude/skills/", ".claude/agents/")


def test_schema_declares_both_keys() -> None:
    schema = json.loads((PLUGIN_ROOT / "config" / "harness.schema.json").read_text(encoding="utf-8"))
    properties = schema["properties"]
    assert "agents_dir" in properties
    assert properties.get("strap", {}).get("properties", {}).get("target", {}).get("enum") == [
        "harness", "project"]


def test_readme_key_table_lists_both_keys() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "| `strap.target`" in text and "| `agents_dir`" in text
