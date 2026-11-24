"""Behavioral tests for the harness bookmark command ``commands/add_note.py``.

The script keeps the session notes the session-bookmark mod prints in its bookmark. Each test runs it against
a throwaway project built by ``make_project`` (a git repository on branch ``main``) and reads the notes file
the mod reads. A note records the branch it was added on, unless it is standing; ``remove`` and ``edit``
change one note by its listed number.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, List

import pytest

from harness_lib import add_todo_api

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import CATALOG_REL, config, todo_files  # noqa: E402

WALK_ROOTS = ()  # walks only the notes folder of a make_project repo
_NOTES_REL = ".claude/state/harness/session-bookmark/notes.json"


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> ModuleType:
    path = plugin_root / "skills" / "bookmark" / "commands" / "add_note.py"
    assert path.exists(), f"missing {path}"
    spec = importlib.util.spec_from_file_location("add_note", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(script: ModuleType, project: Path, *args: str) -> int:
    """``main`` with ``--repo``; an argparse refusal (an unknown subcommand or flag) fails the test."""
    try:
        return script.main(["--repo", str(project), *args])
    except SystemExit as exc:
        raise AssertionError(f"argparse refused {args}: exit {exc.code}") from exc


def _notes(project: Path) -> List[Dict[str, str]]:
    data = json.loads((project / _NOTES_REL).read_text(encoding="utf-8"))
    return data["notes"]


def _file(*notes: Dict[str, str]) -> str:
    return json.dumps({"version": 1, "notes": list(notes)})


def _entry(text: str, branch: object = None) -> Dict[str, object]:
    entry: Dict[str, object] = {"added": "2026-11-18T00:00:00Z", "text": text}
    if branch is not None:
        entry["branch"] = branch
    return entry


def test_add_creates_the_file_with_version_timestamp_and_text(script, make_project, capsys) -> None:
    project = make_project(config={})
    assert _run(script, project, "add", "keep", "the", "API", "frozen") == 0
    data = json.loads((project / _NOTES_REL).read_text(encoding="utf-8"))
    assert data["version"] == script.NOTES_VERSION
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
    assert not (project / _NOTES_REL).exists()


def test_text_at_the_cap_is_stored(script, make_project) -> None:
    project = make_project(config={})
    text = "x" * script.MAX_NOTE_CHARS
    assert _run(script, project, "add", text) == 0
    assert [n["text"] for n in _notes(project)] == [text]


def test_add_from_a_subdirectory_stores_at_the_git_top_level(script, make_project) -> None:
    project = make_project(config={})
    sub = project / "sub"
    sub.mkdir()
    assert _run(script, sub, "add", "from below") == 0
    assert [n["text"] for n in _notes(project)] == ["from below"]
    assert not (sub / _NOTES_REL).exists()


def test_a_full_file_refuses_another_note(script, make_project, capsys) -> None:
    project = make_project(config={})
    for i in range(script.MAX_NOTES):
        assert _run(script, project, "add", f"n{i}") == 0
    capsys.readouterr()
    assert _run(script, project, "add", "one too many") == 1
    assert len(_notes(project)) == script.MAX_NOTES
    err = capsys.readouterr().err
    assert "remove" in err and "clear" in err


def test_list_numbers_the_notes(script, make_project, capsys) -> None:
    project = make_project(config={})
    _run(script, project, "add", "alpha")
    _run(script, project, "add", "beta")
    capsys.readouterr()
    assert _run(script, project, "list") == 0
    assert capsys.readouterr().out.splitlines() == ["1. [main] alpha", "2. [main] beta"]


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


def test_a_malformed_file_is_refused_not_overwritten(script, make_project, capsys) -> None:
    project = make_project(config={}, files={_NOTES_REL: "{not json"})
    assert _run(script, project, "add", "fresh") == 1
    assert (project / _NOTES_REL).read_text(encoding="utf-8") == "{not json"
    assert "clear" in capsys.readouterr().err


def test_clear_resets_a_malformed_file(script, make_project) -> None:
    project = make_project(config={}, files={_NOTES_REL: "{not json"})
    assert _run(script, project, "clear") == 0
    assert _notes(project) == []
    assert _run(script, project, "add", "fresh") == 0
    assert [n["text"] for n in _notes(project)] == ["fresh"]


_MIXED = json.dumps({"version": 1, "notes": [5, None, {"added": "x", "text": "keep me"}, {"text": "  "}]})


def test_list_skips_bad_entries_and_shows_the_valid_ones(script, make_project, capsys) -> None:
    project = make_project(config={}, files={_NOTES_REL: _MIXED})
    assert _run(script, project, "list") == 0
    assert capsys.readouterr().out.strip() == "1. keep me"


def test_add_keeps_the_valid_entries_of_a_mixed_file(script, make_project) -> None:
    project = make_project(config={}, files={_NOTES_REL: _MIXED})
    assert _run(script, project, "add", "fresh") == 0
    assert [n["text"] for n in _notes(project)] == ["keep me", "fresh"]


@pytest.mark.parametrize("version", [2, True, None])
def test_a_foreign_version_is_left_untouched(script, make_project, capsys, version) -> None:
    text = json.dumps({"version": version, "notes": [{"added": "x", "text": "other"}]})
    project = make_project(config={}, files={_NOTES_REL: text})
    assert _run(script, project, "add", "fresh") == 1
    assert _run(script, project, "list") == 1
    assert (project / _NOTES_REL).read_text(encoding="utf-8") == text
    assert "version" in capsys.readouterr().err


def test_no_temp_file_is_left_behind(script, make_project) -> None:
    project = make_project(config={})
    _run(script, project, "add", "a")
    left = sorted(p.name for p in (project / _NOTES_REL).parent.iterdir())
    assert left == ["notes.json"]


# ---------------------------------------------------------------------------
# Branch scope (#279)


def test_add_records_the_current_branch(script, make_project, capsys) -> None:
    project = make_project(config={})
    assert _run(script, project, "add", "keep", "it") == 0
    assert _notes(project)[0].get(script.BRANCH_KEY) == "main"
    assert capsys.readouterr().out.strip() == f"note 1/{script.MAX_NOTES}: [main] keep it"


def test_add_standing_stores_no_branch(script, make_project, capsys) -> None:
    project = make_project(config={})
    assert _run(script, project, "add", "--standing", "every", "branch") == 0
    assert [sorted(n) for n in _notes(project)] == [["added", "text"]]
    assert capsys.readouterr().out.strip() == f"note 1/{script.MAX_NOTES}: every branch"


@pytest.mark.parametrize(("args", "text", "branch"), [
    (("add", "--", "-x", "leading", "dash"), "-x leading dash", "main"),
    (("add", "--standing", "--", "-y"), "-y", None),
], ids=["add", "add-standing"])
def test_add_after_a_double_dash_keeps_a_leading_dash(script, make_project, args, text, branch) -> None:
    project = make_project(config={})
    assert _run(script, project, *args) == 0
    stored = _notes(project)[0]
    assert stored["text"] == text
    assert stored.get(script.BRANCH_KEY) == branch


def test_add_on_a_detached_head_stores_a_standing_note(script, make_project) -> None:
    project = make_project(config={})
    subprocess.run(["git", "-C", str(project), "checkout", "-q", "--detach"], check=True)
    assert script.current_branch(project) is None
    assert _run(script, project, "add", "detached") == 0
    assert script.BRANCH_KEY not in _notes(project)[0]


def test_add_on_an_unborn_branch_records_its_name(script, tmp_path) -> None:
    repo = tmp_path / "unborn"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "trunk"], check=True)
    assert script.current_branch(repo) == "trunk"
    assert _run(script, repo, "add", "first") == 0
    assert _notes(repo)[0].get(script.BRANCH_KEY) == "trunk"


def test_list_marks_a_note_from_another_branch(script, make_project, capsys) -> None:
    notes = _file(_entry("a", "other"), _entry("b", "main"), _entry("c"))
    project = make_project(config={}, files={_NOTES_REL: notes})
    assert _run(script, project, "list") == 0
    mark = script.OTHER_BRANCH_MARK
    assert capsys.readouterr().out.splitlines() == [f"1. [other; {mark} main] a", "2. [main] b", "3. c"]


def test_a_branch_that_is_not_text_reads_as_standing(script, make_project, capsys) -> None:
    project = make_project(config={}, files={_NOTES_REL: _file(_entry("x", 5), _entry("y", "  "))})
    assert _run(script, project, "list") == 0
    assert capsys.readouterr().out.splitlines() == ["1. x", "2. y"]


# ---------------------------------------------------------------------------
# remove and edit (#272)


def test_remove_drops_one_note_and_prints_the_list(script, make_project, capsys) -> None:
    notes = _file(_entry("a", "main"), _entry("b", "main"), _entry("c"))
    project = make_project(config={}, files={_NOTES_REL: notes})
    assert _run(script, project, "remove", "2") == 0
    assert [n["text"] for n in _notes(project)] == ["a", "c"]
    assert capsys.readouterr().out.splitlines() == ["removed note 2: [main] b", "1. [main] a", "2. c"]


def test_removing_the_last_note_says_none_are_left(script, make_project, capsys) -> None:
    project = make_project(config={}, files={_NOTES_REL: _file(_entry("only"))})
    assert _run(script, project, "remove", "1") == 0
    assert _notes(project) == []
    assert capsys.readouterr().out.splitlines() == ["removed note 1: only", "no notes"]


def test_remove_or_edit_out_of_range_changes_nothing(script, make_project, capsys) -> None:
    text = _file(_entry("a", "main"), _entry("b"))
    project = make_project(config={}, files={_NOTES_REL: text})
    for args in (("remove", "0"), ("remove", "3"), ("edit", "3", "new"), ("edit", "0", "new")):
        assert _run(script, project, *args) == 1, args
        assert (project / _NOTES_REL).read_text(encoding="utf-8") == text
        assert "no note" in capsys.readouterr().err


def test_remove_on_an_absent_file_is_refused(script, make_project, capsys) -> None:
    project = make_project(config={})
    assert _run(script, project, "remove", "1") == 1
    assert not (project / _NOTES_REL).exists()
    assert "no note 1" in capsys.readouterr().err


def test_edit_replaces_the_text_and_keeps_added_and_branch(script, make_project, capsys) -> None:
    first = _entry("old words", "other")
    project = make_project(config={}, files={_NOTES_REL: _file(first, _entry("b"))})
    assert _run(script, project, "edit", "1", "new", "words") == 0
    stored = _notes(project)
    assert stored[0] == {**first, "text": "new words"}
    assert stored[1]["text"] == "b"
    mark = script.OTHER_BRANCH_MARK
    assert capsys.readouterr().out.splitlines() == [
        f"edited note 1: [other; {mark} main] new words", f"1. [other; {mark} main] new words", "2. b"]


def test_edit_after_a_double_dash_stores_a_leading_dash_and_keeps_the_branch(script, make_project) -> None:
    first = _entry("old", "other")
    project = make_project(config={}, files={_NOTES_REL: _file(first)})
    assert _run(script, project, "edit", "1", "--", "-z") == 0
    assert _notes(project) == [{**first, "text": "-z"}]


def test_edit_of_a_full_file_is_allowed(script, make_project) -> None:
    full = _file(*(_entry(f"n{i}") for i in range(script.MAX_NOTES)))
    project = make_project(config={}, files={_NOTES_REL: full})
    assert _run(script, project, "edit", str(script.MAX_NOTES), "last") == 0
    assert _notes(project)[-1]["text"] == "last"


def test_edit_refuses_blank_and_too_long_text(script, make_project, capsys) -> None:
    text = _file(_entry("keep"))
    project = make_project(config={}, files={_NOTES_REL: text})
    assert _run(script, project, "edit", "1", "   ") == 1
    assert "blank" in capsys.readouterr().err
    assert _run(script, project, "edit", "1", "x" * (script.MAX_NOTE_CHARS + 1)) == 1
    assert str(script.MAX_NOTE_CHARS) in capsys.readouterr().err
    assert (project / _NOTES_REL).read_text(encoding="utf-8") == text


def test_remove_and_edit_refuse_a_malformed_file(script, make_project, capsys) -> None:
    project = make_project(config={}, files={_NOTES_REL: "{not json"})
    assert _run(script, project, "remove", "1") == 1
    assert _run(script, project, "edit", "1", "x") == 1
    assert (project / _NOTES_REL).read_text(encoding="utf-8") == "{not json"
    assert "clear" in capsys.readouterr().err


_HOOK_REL = f".claude/state/harness/{add_todo_api.HOOK_REL}"


def _switch(project: Path) -> Dict[str, object]:
    return json.loads((project / _HOOK_REL).read_text(encoding="utf-8"))


def _todo_project(make_project) -> Path:
    return make_project(config(), files=todo_files())


def _first_id(project: Path) -> str:
    return json.loads((project / CATALOG_REL).read_text(encoding="utf-8"))["items"][0]["id"]


def test_goal_arms_the_switch_with_the_text(script, make_project, capsys) -> None:
    project = make_project(config={})
    assert _run(script, project, "goal", "--", "the", "tests", "in", "test_x.py", "pass") == 0
    stored = _switch(project)
    assert stored["version"] == add_todo_api.HOOK_VERSION and stored["fired"] is None
    assert stored["hook"]["goal"] == "the tests in test_x.py pass"
    assert stored["hook"]["todo_id"] is None and isinstance(stored["hook"]["start_time"], float)
    assert capsys.readouterr().out.strip() == "goal armed: the tests in test_x.py pass"


def test_goal_refuses_blank_and_too_long_text(script, make_project, capsys) -> None:
    project = make_project(config={})
    assert _run(script, project, "goal", "--", "  ") == 1
    assert "blank" in capsys.readouterr().err
    assert _run(script, project, "goal", "--", "x" * (script.MAX_GOAL_CHARS + 1)) == 1
    assert str(script.MAX_GOAL_CHARS) in capsys.readouterr().err
    assert not (project / _HOOK_REL).exists()


def test_goal_for_a_todo_item_names_the_item_and_its_closing(script, make_project, capsys) -> None:
    project = _todo_project(make_project)
    todo_id = _first_id(project)
    assert _run(script, project, "goal", "--todo", todo_id, "--closed-by", "developer") == 0
    stored = _switch(project)
    assert stored["hook"]["todo_id"] == todo_id and stored["hook"]["closed_by"] == "developer"
    assert stored["hook"]["goal"].startswith(f"TODO {todo_id} (")
    assert capsys.readouterr().out.startswith(f"goal armed for {todo_id} (developer): TODO {todo_id}")


def test_goal_for_a_todo_item_needs_a_known_id_and_a_closing(script, make_project, capsys) -> None:
    project = _todo_project(make_project)
    assert _run(script, project, "goal", "--todo", "todo-zzzz", "--closed-by", "retired") == 1
    assert "no catalog item todo-zzzz" in capsys.readouterr().err
    assert _run(script, project, "goal", "--todo", _first_id(project)) == 1
    assert "--closed-by" in capsys.readouterr().err
    assert not (project / _HOOK_REL).exists()


def test_goal_for_a_todo_item_needs_a_todo_folder(script, make_project, capsys) -> None:
    assert _run(script, make_project(config={}), "goal", "--todo", "todo-af2e", "--closed-by", "retired") == 1
    assert "todo.folder" in capsys.readouterr().err


def test_goal_takes_text_or_a_todo_item_not_both(script, make_project, capsys) -> None:
    project = _todo_project(make_project)
    args = ("goal", "--todo", _first_id(project), "--closed-by", "retired", "--", "x")
    assert _run(script, project, *args) == 1
    assert "not both" in capsys.readouterr().err


def test_goal_clear_removes_the_switch(script, make_project, capsys) -> None:
    project = make_project(config={})
    _run(script, project, "goal", "--", "ship it")
    capsys.readouterr()
    assert _run(script, project, "goal", "--clear") == 0
    assert _run(script, project, "goal", "--clear") == 0
    assert capsys.readouterr().out.splitlines() == ["goal: cleared", "goal: none"]
    assert not (project / _HOOK_REL).exists()


def test_goal_clear_refuses_text_or_a_closing(script, make_project, capsys) -> None:
    project = make_project(config={})
    _run(script, project, "goal", "--", "ship it")
    capsys.readouterr()
    assert _run(script, project, "goal", "--clear", "--", "some", "text") == 1
    assert _run(script, project, "goal", "--clear", "--closed-by", "retired") == 1
    assert "--clear" in capsys.readouterr().err
    assert _switch(project)["hook"]["goal"] == "ship it"


def test_goal_records_the_arming_session(script, make_project, monkeypatch) -> None:
    project = _todo_project(make_project)
    monkeypatch.setenv(add_todo_api.SESSION_ENV, "sess-1")
    _run(script, project, "goal", "--", "ship it")
    assert _switch(project)[add_todo_api.SESSION_KEY] == "sess-1"
    _run(script, project, "goal", "--todo", _first_id(project), "--closed-by", "retired")
    assert _switch(project)[add_todo_api.SESSION_KEY] == "sess-1"
    monkeypatch.delenv(add_todo_api.SESSION_ENV)
    _run(script, project, "goal", "--", "ship it")
    assert _switch(project)[add_todo_api.SESSION_KEY] is None


def test_a_new_goal_replaces_a_fired_switch(script, make_project) -> None:
    project = make_project(config={})
    _run(script, project, "goal", "--", "first")
    fired = {**_switch(project), "fired": {"at": 1}}
    (project / _HOOK_REL).write_text(json.dumps(fired), encoding="utf-8")
    _run(script, project, "goal", "--", "second")
    assert _switch(project)["fired"] is None and _switch(project)["hook"]["goal"] == "second"


def test_remove_takes_several_numbers_from_one_listing(script, make_project, capsys) -> None:
    text = _file(_entry("a"), _entry("b"), _entry("c"), _entry("d"))
    project = make_project(config={}, files={_NOTES_REL: text})
    assert _run(script, project, "remove", "3", "1", "3") == 0
    assert [n["text"] for n in _notes(project)] == ["b", "d"]
    assert capsys.readouterr().out.splitlines() == [
        "removed note 1: a", "removed note 3: c", "1. b", "2. d"]


def test_remove_of_several_with_one_out_of_range_changes_nothing(script, make_project, capsys) -> None:
    text = _file(_entry("a"), _entry("b"))
    project = make_project(config={}, files={_NOTES_REL: text})
    assert _run(script, project, "remove", "1", "5") == 1
    assert "no note 5" in capsys.readouterr().err
    assert (project / _NOTES_REL).read_text(encoding="utf-8") == text
