"""Pin the names the working-refs mod copies from the harness (plan 2025, issue #301).

The harness ``working`` command writes ``<state_dir>/working-refs/overrides.json``; the mod reads it, watches
``artifacts.plans`` for ``*_PIP.html`` pages, reads each sibling ``*_ActionPlan.json`` and writes
``<state_dir>/working-refs/line.txt`` for the ccstatusline widget. An installed mod cannot import the harness
plugin, so ``plugins/working-refs/hooks/mirror.ts`` copies these names; this test fails when one side changes
without the other. Each test reads the mirror before importing the harness module, so it fails on the missing
mirror whether or not ``harness_lib.working_refs`` exists yet.
"""
from __future__ import annotations

import json
from pathlib import Path

from harness_lib import plan_doc as pd
from mods._mods_helpers import ts_number, ts_string

_MIRROR_TS_REL = "plugins/working-refs/hooks/mirror.ts"
_DEFAULTS_REL = "plugins/harness/config/defaults.json"


def _mirror(repo_root: Path) -> str:
    path = repo_root / _MIRROR_TS_REL
    assert path.is_file(), f"missing {_MIRROR_TS_REL}"
    return path.read_text(encoding="utf-8")


def test_store_paths_match(repo_root: Path) -> None:
    mirror = _mirror(repo_root)
    from harness_lib.working_refs import LINE_REL, OVERRIDES_REL
    assert ts_string(mirror, "OVERRIDES_PATH") == OVERRIDES_REL
    assert ts_string(mirror, "LINE_PATH") == LINE_REL


def test_store_version_and_detached_key_match(repo_root: Path) -> None:
    mirror = _mirror(repo_root)
    from harness_lib.working_refs import DETACHED, STORE_VERSION
    assert ts_number(mirror, "STORE_VERSION") == STORE_VERSION
    assert ts_string(mirror, "DETACHED_KEY") == DETACHED


def test_override_and_refs_field_names_match(repo_root: Path, tmp_path: Path) -> None:
    mirror = _mirror(repo_root)
    from harness_lib.plan_models import PlanRefs
    from harness_lib.working_refs import parse_refs, set_override
    store = tmp_path / "overrides.json"
    set_override(store, "b", parse_refs(["todo-k69m", "#301"]))
    data = json.loads(store.read_text(encoding="utf-8"))
    branches_key = ts_string(mirror, "BRANCHES_KEY")
    assert branches_key in data
    entry = data[branches_key]["b"]
    assert ts_string(mirror, "TODO_IDS_KEY") in entry
    assert ts_string(mirror, "ISSUES_KEY") in entry
    assert {ts_string(mirror, "TODO_IDS_KEY"), ts_string(mirror, "ISSUES_KEY")} == set(PlanRefs.model_fields)


def test_defaults_equal_defaults_json(repo_root: Path) -> None:
    mirror = _mirror(repo_root)
    defaults = json.loads((repo_root / _DEFAULTS_REL).read_text(encoding="utf-8"))
    assert ts_string(mirror, "DEFAULT_STATE_DIR") == defaults["state_dir"]
    assert ts_string(mirror, "DEFAULT_PLANS") == defaults["artifacts"]["plans"]


def test_plan_file_suffixes_match_plan_doc(repo_root: Path) -> None:
    mirror = _mirror(repo_root)
    assert ts_string(mirror, "PLAN_SUFFIX") == pd.PLAN_SUFFIX
    assert ts_string(mirror, "PIP_HTML_SUFFIX") == pd.PIP_HTML_SUFFIX
