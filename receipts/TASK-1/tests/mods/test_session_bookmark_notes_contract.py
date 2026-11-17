"""Pin the notes file the harness add-bookmark script writes to the names the session-bookmark mod reads.

The script (``plugins/harness/skills/add-bookmark/commands/add_note.py``) writes
``<state_dir>/session-bookmark/notes.json``; the mod (``plugins/session-bookmark/hooks/notes.ts``) reads it at
every compaction. An installed mod cannot import the harness plugin, so ``notes.ts`` copies the file's path,
version and limits, and the default ``state_dir``. This test fails when one side changes without the other.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from harness_lib.config import activate, load_config
from mods._mods_helpers import ts_number, ts_string

_NOTES_TS_REL = "plugins/session-bookmark/hooks/notes.ts"
_SCRIPT_REL = "plugins/harness/skills/add-bookmark/commands/add_note.py"
_DEFAULTS_REL = "plugins/harness/config/defaults.json"


@pytest.fixture(scope="module")
def notes_ts(repo_root: Path) -> str:
    return (repo_root / _NOTES_TS_REL).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("add_note_contract", repo_root / _SCRIPT_REL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_notes_path_matches(notes_ts: str, script: ModuleType) -> None:
    assert ts_string(notes_ts, "NOTES_PATH") == script.NOTES_REL


def test_schema_version_matches(notes_ts: str, script: ModuleType) -> None:
    assert ts_number(notes_ts, "NOTES_SCHEMA_VERSION") == script.NOTES_VERSION


def test_note_limits_match(notes_ts: str, script: ModuleType) -> None:
    assert ts_number(notes_ts, "MAX_NOTES") == script.MAX_NOTES
    assert ts_number(notes_ts, "MAX_NOTE_CHARS") == script.MAX_NOTE_CHARS


def test_default_state_dir_equals_defaults_json(repo_root: Path, notes_ts: str) -> None:
    defaults = json.loads((repo_root / _DEFAULTS_REL).read_text(encoding="utf-8"))
    assert ts_string(notes_ts, "DEFAULT_STATE_DIR") == defaults["state_dir"]


def test_default_state_dir_equals_an_unconfigured_project(make_project, notes_ts: str) -> None:
    cfg = activate(load_config(make_project(config={})))
    assert ts_string(notes_ts, "DEFAULT_STATE_DIR") == cfg.state_dir


def test_a_stored_note_has_the_shape_the_mod_parses(make_project, script: ModuleType) -> None:
    project = make_project(config={})
    assert script.main(["--repo", str(project), "add", "keep the API frozen"]) == 0
    stored = json.loads((project / ".claude/state/harness" / script.NOTES_REL).read_text(encoding="utf-8"))
    assert stored["version"] == script.NOTES_VERSION
    assert [sorted(n) for n in stored["notes"]] == [["added", "text"]]
