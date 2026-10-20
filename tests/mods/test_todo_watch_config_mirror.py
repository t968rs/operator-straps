"""Pin the todo-watch mod's mirrored harness defaults to ``plugins/harness/config/defaults.json``.

An installed mod lives in its own plugin cache directory and cannot read the harness plugin's defaults,
so ``plugins/todo-watch/hooks/config.ts`` copies the values of the keys it reads. This test fails when
``defaults.json`` changes one of those values without the mod following, and checks the copies against
the merged configuration the harness library builds for a project with no overrides.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Tuple, Union

import pytest

from harness_lib.config import activate, load_config
from mods._mods_helpers import ts_boolean, ts_number, ts_optional_string

_CONFIG_TS_REL = "plugins/todo-watch/hooks/config.ts"
_DEFAULTS_REL = "plugins/harness/config/defaults.json"

Reader = Callable[[str, str], Any]

#: defaults.json key path -> (exported constant in config.ts, literal reader)
_MIRRORED: Dict[Tuple[str, ...], Tuple[str, Reader]] = {
    ("state_dir",): ("DEFAULT_STATE_DIR", ts_optional_string),
    ("artifacts", "research"): ("DEFAULT_RESEARCH", ts_optional_string),
    ("artifacts", "plans"): ("DEFAULT_PLANS", ts_optional_string),
    ("todo", "folder"): ("DEFAULT_FOLDER", ts_optional_string),
    ("todo", "catalog"): ("DEFAULT_CATALOG", ts_optional_string),
    ("todo", "catalog_schema"): ("DEFAULT_CATALOG_SCHEMA", ts_optional_string),
    ("todo", "top_n"): ("DEFAULT_TOP_N", ts_number),
    ("todo", "snapshots", "dir"): ("DEFAULT_SNAPSHOTS_DIR", ts_optional_string),
    ("todo", "research", "catalog"): ("DEFAULT_RESEARCH_CATALOG", ts_optional_string),
    ("todo", "gh", "max_age_hours"): ("DEFAULT_GH_MAX_AGE_HOURS", ts_number),
    ("todo", "inject_context"): ("DEFAULT_INJECT_CONTEXT", ts_boolean),
    ("todo", "notice", "style"): ("DEFAULT_NOTICE_STYLE", ts_optional_string),
    ("todo", "notice", "toast_seconds"): ("DEFAULT_TOAST_SECONDS", ts_number),
}

Value = Union[str, float, bool, None]


def _at(data: Dict[str, Any], path: Tuple[str, ...]) -> Value:
    for key in path:
        data = data[key]
    return data  # type: ignore[return-value]


@pytest.fixture(scope="module")
def config_ts(repo_root: Path) -> str:
    return (repo_root / _CONFIG_TS_REL).read_text(encoding="utf-8")


@pytest.mark.parametrize("path", sorted(_MIRRORED), ids=lambda v: "/".join(v))
def test_mirrored_default_equals_defaults_json(
    repo_root: Path, config_ts: str, path: Tuple[str, ...]
) -> None:
    defaults = json.loads((repo_root / _DEFAULTS_REL).read_text(encoding="utf-8"))
    name, reader = _MIRRORED[path]
    assert reader(config_ts, name) == _at(defaults, path)


def test_every_mirrored_key_is_pinned(config_ts: str) -> None:
    lines = config_ts.splitlines()
    exported = {line.split()[2].rstrip(":") for line in lines if line.startswith("export const DEFAULT_")}
    assert exported == {name for name, _ in _MIRRORED.values()}


_FOLDER = "docs/RESEARCH/_TODO"

#: config.ts constant -> TodoConfig path the harness resolves it to under ``todo.folder``
_RESOLVED: Dict[str, Callable[[Any], Value]] = {
    "DEFAULT_CATALOG": lambda t: t.catalog,
    "DEFAULT_CATALOG_SCHEMA": lambda t: t.catalog_schema,
    "DEFAULT_SNAPSHOTS_DIR": lambda t: t.snapshots.dir,
    "DEFAULT_RESEARCH_CATALOG": lambda t: t.research.catalog,
}


def _ts(config_ts: str, name: str) -> Value:
    readers = {n: reader for n, reader in _MIRRORED.values()}
    return readers[name](config_ts, name)


def test_mirrored_defaults_equal_an_unconfigured_project(make_project, config_ts: str) -> None:
    cfg = activate(load_config(make_project(config={})))
    loaded: Dict[str, Value] = {
        "DEFAULT_STATE_DIR": cfg.state_dir,
        "DEFAULT_RESEARCH": cfg.artifacts.research,
        "DEFAULT_PLANS": cfg.artifacts.plans,
        "DEFAULT_FOLDER": cfg.todo.folder,
        "DEFAULT_TOP_N": cfg.todo.top_n,
        "DEFAULT_GH_MAX_AGE_HOURS": cfg.todo.gh_max_age_hours,
        "DEFAULT_INJECT_CONTEXT": cfg.todo.inject_context,
        "DEFAULT_NOTICE_STYLE": cfg.todo.notice_style,
        "DEFAULT_TOAST_SECONDS": cfg.todo.notice_toast_seconds,
    }
    assert {name: _ts(config_ts, name) for name in loaded} == loaded


def test_mirrored_names_resolve_under_the_folder_as_the_harness_does(make_project, config_ts: str) -> None:
    optional = ("DEFAULT_CATALOG_SCHEMA", "DEFAULT_RESEARCH_CATALOG")
    files = {f"{_FOLDER}/{_ts(config_ts, n)}": "{}" for n in optional}
    todo = activate(load_config(make_project(config={"todo": {"folder": _FOLDER}}, files=files))).todo
    resolved = {name: get(todo) for name, get in _RESOLVED.items()}
    assert resolved == {name: f"{_FOLDER}/{_ts(config_ts, name)}" for name in _RESOLVED}
