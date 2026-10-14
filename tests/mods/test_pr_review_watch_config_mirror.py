"""Pin the pr-review-watch mod's mirrored harness defaults to ``plugins/harness/config/defaults.json``.

An installed mod lives in its own plugin cache directory and cannot read the harness plugin's defaults,
so ``plugins/pr-review-watch/hooks/config.ts`` copies the values of the keys it reads. This test fails
when ``defaults.json`` changes one of those values without the mod following, and checks the copies
against the merged configuration the harness library builds for a project with no overrides.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from harness_lib.config import activate, load_config
from mods._mods_helpers import ts_optional_string

_CONFIG_TS_REL = "plugins/pr-review-watch/hooks/config.ts"
_DEFAULTS_REL = "plugins/harness/config/defaults.json"

#: defaults.json key path -> exported constant in config.ts
_MIRRORED = {
    ("state_dir",): "DEFAULT_STATE_DIR",
    ("matrix_path",): "DEFAULT_MATRIX_PATH",
    ("artifacts", "reviews"): "DEFAULT_REVIEWS",
    ("artifacts", "scratch"): "DEFAULT_SCRATCH",
    ("base_branch",): "DEFAULT_BASE_BRANCH",
}


def _at(data: Dict[str, Any], path: tuple) -> Optional[str]:
    for key in path:
        data = data[key]
    return data  # type: ignore[return-value]


@pytest.fixture(scope="module")
def config_ts(repo_root: Path) -> str:
    return (repo_root / _CONFIG_TS_REL).read_text(encoding="utf-8")


@pytest.mark.parametrize("path,name", sorted(_MIRRORED.items()), ids=lambda v: str(v))
def test_mirrored_default_equals_defaults_json(
    repo_root: Path, config_ts: str, path: tuple, name: str
) -> None:
    defaults = json.loads((repo_root / _DEFAULTS_REL).read_text(encoding="utf-8"))
    assert ts_optional_string(config_ts, name) == _at(defaults, path)


def test_mirrored_defaults_equal_an_unconfigured_project(make_project, config_ts: str) -> None:
    cfg = activate(load_config(make_project(config={})))
    loaded = {
        "DEFAULT_STATE_DIR": cfg.state_dir,
        "DEFAULT_MATRIX_PATH": cfg.matrix_path,
        "DEFAULT_REVIEWS": cfg.artifacts.reviews,
        "DEFAULT_SCRATCH": cfg.artifacts.scratch,
        "DEFAULT_BASE_BRANCH": cfg.base_branch,
    }
    assert {name: ts_optional_string(config_ts, name) for name in loaded} == loaded
