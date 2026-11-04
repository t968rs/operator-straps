"""Pin the agent-watcher mod's mirrored harness defaults to ``plugins/harness/config/defaults.json``.

An installed mod lives in its own plugin cache directory and cannot read the harness plugin's defaults,
so the mod copies the values of the keys it reads: the core keys in
``plugins/agent-watcher/hooks/core/config.ts``, the pr-review layer's in
``plugins/agent-watcher/hooks/layers/pr-review/config.ts``. This test fails when ``defaults.json``
changes one of those values without the mod following, and checks the copies against the merged
configuration the harness library builds for a project with no overrides.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from harness_lib.config import activate, load_config
from mods._mods_helpers import ts_optional_string

_CORE_CONFIG_TS_REL = "plugins/agent-watcher/hooks/core/config.ts"
_LAYER_CONFIG_TS_REL = "plugins/agent-watcher/hooks/layers/pr-review/config.ts"
_DEFAULTS_REL = "plugins/harness/config/defaults.json"

#: defaults.json key path -> (config.ts holding the copy, exported constant)
_MIRRORED = {
    ("state_dir",): (_CORE_CONFIG_TS_REL, "DEFAULT_STATE_DIR"),
    ("agent_usage_path",): (_CORE_CONFIG_TS_REL, "DEFAULT_AGENT_USAGE_PATH"),
    ("matrix_path",): (_LAYER_CONFIG_TS_REL, "DEFAULT_MATRIX_PATH"),
    ("artifacts", "reviews"): (_LAYER_CONFIG_TS_REL, "DEFAULT_REVIEWS"),
    ("artifacts", "scratch"): (_LAYER_CONFIG_TS_REL, "DEFAULT_SCRATCH"),
    ("base_branch",): (_LAYER_CONFIG_TS_REL, "DEFAULT_BASE_BRANCH"),
}


def _at(data: Dict[str, Any], path: tuple) -> Optional[str]:
    for key in path:
        data = data[key]
    return data  # type: ignore[return-value]


@pytest.fixture(scope="module")
def config_ts(repo_root: Path) -> Dict[str, str]:
    """Each mirroring config.ts by its repo-relative path."""
    rels = (_CORE_CONFIG_TS_REL, _LAYER_CONFIG_TS_REL)
    return {rel: (repo_root / rel).read_text(encoding="utf-8") for rel in rels}


@pytest.mark.parametrize("path,source", sorted(_MIRRORED.items()), ids=lambda v: str(v))
def test_mirrored_default_equals_defaults_json(
    repo_root: Path, config_ts: Dict[str, str], path: tuple, source: tuple
) -> None:
    rel, name = source
    defaults = json.loads((repo_root / _DEFAULTS_REL).read_text(encoding="utf-8"))
    assert ts_optional_string(config_ts[rel], name) == _at(defaults, path)


def test_mirrored_defaults_equal_an_unconfigured_project(make_project, config_ts: Dict[str, str]) -> None:
    cfg = activate(load_config(make_project(config={})))
    loaded = {
        "DEFAULT_STATE_DIR": cfg.state_dir,
        "DEFAULT_MATRIX_PATH": cfg.matrix_path,
        "DEFAULT_AGENT_USAGE_PATH": cfg.agent_usage_path,
        "DEFAULT_REVIEWS": cfg.artifacts.reviews,
        "DEFAULT_SCRATCH": cfg.artifacts.scratch,
        "DEFAULT_BASE_BRANCH": cfg.base_branch,
    }
    copied = {name: ts_optional_string(config_ts[rel], name) for rel, name in _MIRRORED.values()}
    assert copied == loaded
