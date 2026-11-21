"""Pin the names the working-refs mod copies from the harness (plans 2025 and 2027, issue #301).

The harness ``working`` command writes ``<state_dir>/working-refs/overrides.json``; the mod reads it, watches
``artifacts.plans`` for ``*_PIP.html`` pages, reads each sibling ``*_ActionPlan.json`` and writes
``<state_dir>/working-refs/line.txt`` and the branch-stamped ``line.json`` for the ccstatusline widget. It
hides TODO ids the catalog (``todo.folder`` / ``todo.catalog``) lists in ``retired_ids`` and issues ``gh``
reports closed, and labels each TODO id with the catalog item's ``keyword`` (plan 2028, ``KEYWORD_KEY``, a
property of ``$defs/item`` in ``TodoCatalog.schema.json``); the open list ``todo_sync.py untracked`` writes (``todo-sync/open_issues.json``, whose
``version`` ``hide.ts`` checks) answers only OPEN, an issue missing from it is due for a ``gh`` check
(``todo.gh.repo``), rechecked past ``todo.gh.max_age_hours``; ``working_refs.max_chars`` caps the line. An
installed mod cannot import the harness plugin, so ``plugins/working-refs/hooks/mirror.ts`` copies these
names; this test fails when one side changes without the other. ``plans.ts`` reads the ActionPlan fields
inline as ``data.<field>``; one test pins each against ``ActionPlan.model_fields``. Each test reads the
mirror before importing the harness module, so it fails on the missing mirror whether or not
``harness_lib.working_refs`` exists yet.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from harness_lib import plan_doc as pd
from mods._mods_helpers import ts_number, ts_optional_string, ts_string

_MIRROR_TS_REL = "plugins/working-refs/hooks/mirror.ts"
_DEFAULTS_REL = "plugins/harness/config/defaults.json"
_PLANS_TS_REL = "plugins/working-refs/hooks/plans.ts"
_HIDE_TS_REL = "plugins/working-refs/hooks/hide.ts"
_TODO_SCHEMA_REL = "plugins/harness/schemas/catalogs/TodoCatalog.schema.json"


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


def test_plan_fields_read_by_plans_ts_match_action_plan(repo_root: Path) -> None:
    path = repo_root / _PLANS_TS_REL
    assert path.is_file(), f"missing {_PLANS_TS_REL}"
    names = set(re.findall(r"data\.(\w+)", path.read_text(encoding="utf-8")))
    from harness_lib.plan_models import ActionPlan
    assert names, f"no ActionPlan field read found in {_PLANS_TS_REL}"
    assert names <= set(ActionPlan.model_fields), sorted(names - set(ActionPlan.model_fields))


def test_defaults_equal_defaults_json(repo_root: Path) -> None:
    mirror = _mirror(repo_root)
    defaults = json.loads((repo_root / _DEFAULTS_REL).read_text(encoding="utf-8"))
    assert ts_string(mirror, "DEFAULT_STATE_DIR") == defaults["state_dir"]
    assert ts_string(mirror, "DEFAULT_PLANS") == defaults["artifacts"]["plans"]


def test_plan_file_suffixes_match_plan_doc(repo_root: Path) -> None:
    mirror = _mirror(repo_root)
    assert ts_string(mirror, "PLAN_SUFFIX") == pd.PLAN_SUFFIX
    assert ts_string(mirror, "PIP_HTML_SUFFIX") == pd.PIP_HTML_SUFFIX


def test_line_json_and_open_issues_paths_match(repo_root: Path) -> None:
    mirror = _mirror(repo_root)
    line_json = ts_string(mirror, "LINE_JSON_PATH")
    open_issues = ts_string(mirror, "OPEN_ISSUES_PATH")
    from harness_lib.todo_sync.issues import OPEN_ISSUES_REL
    from harness_lib.working_refs import LINE_JSON_REL
    assert line_json == LINE_JSON_REL
    assert open_issues == OPEN_ISSUES_REL


def test_open_list_version_matches_the_writer(repo_root: Path) -> None:
    path = repo_root / _HIDE_TS_REL
    assert path.is_file(), f"missing {_HIDE_TS_REL}"
    version = ts_number(path.read_text(encoding="utf-8"), "OPEN_LIST_VERSION")
    from harness_lib.todo_sync.issues import OPEN_ISSUES_VERSION
    assert version == OPEN_ISSUES_VERSION


def test_set_at_key_matches_the_override_entry(repo_root: Path, tmp_path: Path) -> None:
    mirror = _mirror(repo_root)
    set_at = ts_string(mirror, "SET_AT_KEY")
    from harness_lib.working_refs import parse_refs, set_override
    store = tmp_path / "overrides.json"
    set_override(store, "b", parse_refs(["todo-k69m"]))
    assert set_at in json.loads(store.read_text(encoding="utf-8"))["branches"]["b"]


def test_todo_and_cap_defaults_equal_defaults_json(repo_root: Path) -> None:
    mirror = _mirror(repo_root)
    defaults = json.loads((repo_root / _DEFAULTS_REL).read_text(encoding="utf-8"))
    assert ts_string(mirror, "DEFAULT_TODO_CATALOG") == defaults["todo"]["catalog"]
    assert ts_number(mirror, "DEFAULT_GH_MAX_AGE_HOURS") == defaults["todo"]["gh"]["max_age_hours"]
    assert ts_number(mirror, "DEFAULT_MAX_CHARS") == defaults["working_refs"]["max_chars"]
    assert ts_optional_string(mirror, "DEFAULT_TODO_FOLDER") == defaults["todo"]["folder"]
    assert ts_optional_string(mirror, "DEFAULT_GH_REPO") == defaults["todo"]["gh"]["repo"]


def test_keyword_key_is_a_catalog_item_property(repo_root: Path) -> None:
    mirror = _mirror(repo_root)
    key = ts_string(mirror, "KEYWORD_KEY")
    schema = json.loads((repo_root / _TODO_SCHEMA_REL).read_text(encoding="utf-8"))
    assert key in schema["$defs"]["item"]["properties"]
