"""Pin the notes file the harness bookmark script writes to the names the session-bookmark mod reads.

The script (``plugins/harness/skills/bookmark/commands/add_note.py``) writes
``<state_dir>/session-bookmark/notes.json``; the mod (``plugins/session-bookmark/hooks/notes.ts``) reads it at
every compaction and for ``/session-bookmark notes``. An installed mod cannot import the harness plugin, so
``notes.ts`` copies the file's path, version, limits, the branch key and the other-branch mark, the default
``state_dir`` and the printed line format (the script's ``note_line`` against the mod's ``noteLine``). This
test fails when one side changes without the other.
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
_BOOKMARK_TS_REL = "plugins/session-bookmark/hooks/bookmark.ts"
_MOD_README_REL = "plugins/session-bookmark/README.md"
_SCRIPT_REL = "plugins/harness/skills/bookmark/commands/add_note.py"
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


def test_branch_key_matches(notes_ts: str, script: ModuleType) -> None:
    assert ts_string(notes_ts, "NOTE_BRANCH_KEY") == script.BRANCH_KEY


def test_other_branch_mark_matches(notes_ts: str, script: ModuleType) -> None:
    assert ts_string(notes_ts, "OTHER_BRANCH_MARK") == script.OTHER_BRANCH_MARK


_TS_NOTE = {"text": "${note.text}", "branch": "${note.branch}"}


def _as_ts_template(script: ModuleType, body: str) -> str:
    """A ``note_body`` rendered from TS placeholders, as the template literal ``noteBody`` holds."""
    mark = f"; {script.OTHER_BRANCH_MARK} "
    return "`" + body.replace(mark, "; ${OTHER_BRANCH_MARK} ") + "`"


@pytest.mark.parametrize("current", ["${note.branch}", "${current}"], ids=["same-branch", "other-branch"])
def test_branch_tagged_line_matches_the_mod_template(notes_ts: str, script: ModuleType, current: str) -> None:
    assert _as_ts_template(script, script.note_body(_TS_NOTE, current)) in notes_ts


def test_standing_line_and_numbering_match_the_mod(notes_ts: str, script: ModuleType) -> None:
    assert script.note_body({"text": "keep"}, "main") == "keep"
    assert "if (note.branch === null) return note.text" in notes_ts
    line = script.note_line("${i}", {"text": "${noteBody(note, current)}"}, None)
    assert f"`{line}`" in notes_ts


def _ts_function_body(source: str, name: str) -> str:
    """The text of the exported arrow function ``name`` up to the next blank line."""
    start = source.index(f"export const {name} = ")
    end = source.find("\n\n", start)
    return source[start:] if end < 0 else source[start:end]


def test_live_view_numbers_every_note_as_the_script_does(
    make_project, notes_ts: str, script: ModuleType
) -> None:
    """``/session-bookmark notes`` reads through ``parseNotesOrNull``; ``remove N`` picks from ``read_notes``.

    Both keep every usable note, so a hand-edited file past ``MAX_NOTES`` numbers alike on both sides.
    """
    assert "MAX_NOTES" not in _ts_function_body(notes_ts, "parseNotesOrNull")
    project = make_project(config={})
    path = script.notes_path(project)
    texts = [f"n{i}" for i in range(script.MAX_NOTES + 3)]
    script.write_notes(path, [{"text": t} for t in texts])
    assert [n["text"] for n in script.read_notes(path)] == texts


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
    assert [sorted(n) for n in stored["notes"]] == [["added", script.BRANCH_KEY, "text"]]
    assert stored["notes"][0][script.BRANCH_KEY] == "main"


def test_the_notes_argument_is_the_documented_one(repo_root: Path) -> None:
    bookmark_ts = (repo_root / _BOOKMARK_TS_REL).read_text(encoding="utf-8")
    readme = (repo_root / _MOD_README_REL).read_text(encoding="utf-8")
    arg = ts_string(bookmark_ts, "NOTES_ARG")
    assert arg == "notes"
    assert f"/session-bookmark {arg}" in readme
