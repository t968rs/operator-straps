"""Pin the bubble-stamp mod's mirrored harness default to ``plugins/harness/config/defaults.json``.

An installed mod lives in its own plugin cache directory and cannot read the harness plugin's defaults, so
``plugins/bubble-stamp/hooks/config.ts`` copies the one value it reads: the reviews folder.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_lib.config import activate, load_config
from mods._mods_helpers import ts_optional_string

_CONFIG_TS_REL = "plugins/bubble-stamp/hooks/config.ts"
_DEFAULTS_REL = "plugins/harness/config/defaults.json"


@pytest.fixture(scope="module")
def config_ts(repo_root: Path) -> str:
    path = repo_root / _CONFIG_TS_REL
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def test_the_mirrored_reviews_folder_equals_defaults_json(repo_root: Path, config_ts: str) -> None:
    defaults = json.loads((repo_root / _DEFAULTS_REL).read_text(encoding="utf-8"))
    assert ts_optional_string(config_ts, "DEFAULT_REVIEWS") == defaults["artifacts"]["reviews"]


def test_the_mirror_equals_an_unconfigured_project(make_project, config_ts: str) -> None:
    cfg = activate(load_config(make_project(config={})))
    assert ts_optional_string(config_ts, "DEFAULT_REVIEWS") == cfg.artifacts.reviews
