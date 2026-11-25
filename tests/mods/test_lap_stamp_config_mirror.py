"""Pin the lap-stamp mod's mirrored harness default to ``plugins/harness/config/defaults.json`` (plan 2031).

An installed mod lives in its own plugin cache directory and cannot read the harness plugin's defaults, so
``plugins/lap-stamp/hooks/config.ts`` copies the one value it reads, ``state_dir``, and names the laps file
it keeps under it.
"""
from __future__ import annotations

import json
from pathlib import Path

from mods._mods_helpers import ts_string

_CONFIG_TS_REL = "plugins/lap-stamp/hooks/config.ts"
_DEFAULTS_REL = "plugins/harness/config/defaults.json"


def _config_ts(repo_root: Path) -> str:
    path = repo_root / _CONFIG_TS_REL
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def test_the_mirrored_state_dir_equals_defaults_json(repo_root: Path) -> None:
    config_ts = _config_ts(repo_root)
    defaults = json.loads((repo_root / _DEFAULTS_REL).read_text(encoding="utf-8"))
    assert ts_string(config_ts, "DEFAULT_STATE_DIR") == defaults["state_dir"]


def test_the_laps_file_sits_in_the_mod_folder_under_state_dir(repo_root: Path) -> None:
    assert ts_string(_config_ts(repo_root), "LAPS_PATH") == "lap-stamp/laps.jsonl"
