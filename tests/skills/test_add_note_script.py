"""Behavioral tests for the harness add-bookmark command ``commands/add_note.py``.

The script keeps the session notes the session-bookmark mod prints in its bookmark. Each test runs it against
a throwaway project built by ``make_project`` and reads the notes file the mod reads.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Dict, List

import pytest

_NOTES_REL = ".claude/state/harness/session-bookmark/notes.json"


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> ModuleType:
    path = plugin_root / "skills" / "add-bookmark" / "commands" / "add_note.py"
    assert path.exists(), f"missing {path}"
    spec = importlib.util.spec_from_file_location("add_note", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(script: ModuleType, project: Path, *args: str) -> int:
    return script.main(["--repo", str(project), *args])


def _notes(project: Path) -> List[Dict[str, str]]:
    data = json.loads((project / _NOTES_REL).read_text(encoding="utf-8"))
    return data["notes"]


def test_add_creates_the_file_with_version_timestamp_and_text(script, make_project, capsys) -> None:
    project = make_project(config={})
    assert _run(script, project, "add", "keep", "the", "API", "frozen") == 0
    data = json.loads((project / _NOTES_REL).read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert [n["text"] for n in data["notes"]] == ["keep the API frozen"]
    assert data["notes"][0]["added"].endswith("Z")
    assert "note 1/" in capsys.readouterr().out


def test_add_appends_in_order(script, make_project) -> None:
    project = make_project(config={})
    _run(script, project, "add", "first")
    _run(script, project, "add", "second")
    assert [n["text"] for n in _notes(project)] == ["first", "second"]


def test_state_dir_comes_from_the_project_config(script, make_project) -> None:
    project = make_project(config={"state_dir": "var/state"})
    _run(script, project, "add", "note")
    assert (project / "var/state/session-bookmark/notes.json").exists()
    assert not (project / _NOTES_REL).exists()


def test_blank_text_is_refused(script, make_project, capsys) -> None:
    project = make_project(config={})
    assert _run(script, project, "add", "   ") == 1
    assert not (project / _NOTES_REL).exists()
    assert "blank" in capsys.readouterr().err


def test_text_past_the_cap_is_refused(script, make_project, capsys) -> None:
    project = make_project(config={})
    assert _run(script, project, "add", "x" * (script.MAX_NOTE_CHARS + 1)) == 1
    assert str(script.MAX_NOTE_CHARS) in capsys.readouterr().err


def test_a_full_file_refuses_another_note(script, make_project, capsys) -> None:
    project = make_project(config={})
    for i in range(script.MAX_NOTES):
        assert _run(script, project, "add", f"n{i}") == 0
    assert _run(script, project, "add", "one too many") == 1
    assert len(_notes(project)) == script.MAX_NOTES
    assert "clear" in capsys.readouterr().err


def test_list_numbers_the_notes(script, make_project, capsys) -> None:
    project = make_project(config={})
    _run(script, project, "add", "alpha")
    _run(script, project, "add", "beta")
    capsys.readouterr()
    assert _run(script, project, "list") == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(". ", 1)[1] for line in lines] == ["alpha", "beta"]
    assert lines[0].startswith("1. ")


def test_list_with_no_file_says_none(script, make_project, capsys) -> None:
    project = make_project(config={})
    assert _run(script, project, "list") == 0
    assert capsys.readouterr().out.strip() == "no notes"


def test_clear_empties_the_file_and_reports_the_count(script, make_project, capsys) -> None:
    project = make_project(config={})
    _run(script, project, "add", "a")
    _run(script, project, "add", "b")
    capsys.readouterr()
    assert _run(script, project, "clear") == 0
    assert capsys.readouterr().out.strip() == "cleared 2 notes"
    assert _notes(project) == []


def test_a_malformed_file_is_replaced_not_fatal(script, make_project) -> None:
    project = make_project(config={}, files={_NOTES_REL: "{not json"})
    assert _run(script, project, "add", "fresh") == 0
    assert [n["text"] for n in _notes(project)] == ["fresh"]


def test_no_temp_file_is_left_behind(script, make_project) -> None:
    project = make_project(config={})
    _run(script, project, "add", "a")
    left = sorted(p.name for p in (project / _NOTES_REL).parent.iterdir())
    assert left == ["notes.json"]
