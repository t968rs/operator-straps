"""Behavioral tests for ``harness_lib.commit_regroup``: moving paths and bullets between skeleton blocks."""
from __future__ import annotations

import copy
from typing import Dict

import pytest

from harness_lib.branch_capture import CaptureError
from harness_lib.commit_regroup import bullet_problems, move_paths

_SRC = "Fix(io): read a\n\nReader failed.\n  - a.py: handle empty file\n  - test_a.py: cover empty file"
_DOCS = "Docs: notes\n\nNotes.\n  - new.md: add notes"


def _payload() -> Dict[str, object]:
    return {
        "commits": {
            "1": [["src/a.py", "tests/test_a.py"], _SRC],
            "2": [["docs/new.md"], _DOCS],
            "3": [["docs/PR_REVIEWS/*.json"], "Chore: reviews"],
        },
        "captured": [
            {"status": "M", "path": "src/a.py", "old_path": None},
            {"status": "R", "path": "src/b.py", "old_path": "src/old_b.py"},
        ],
    }


def _moved(paths, to, payload=None):
    return move_paths(payload or _payload(), paths, to)


class TestMovePaths:
    def test_path_and_bullet_join_an_existing_block(self) -> None:
        payload, _ = _moved(["tests/test_a.py"], 2)
        assert payload["commits"]["1"][0] == ["src/a.py"]
        assert payload["commits"]["2"][0] == ["docs/new.md", "tests/test_a.py"]
        assert payload["commits"]["2"][1].splitlines()[-1] == "  - test_a.py: cover empty file"

    def test_bullet_leaves_the_source_message(self) -> None:
        payload, _ = _moved(["tests/test_a.py"], 2)
        assert "test_a.py" not in payload["commits"]["1"][1]
        assert "a.py: handle empty file" in payload["commits"]["1"][1]

    def test_bullet_lands_after_the_last_target_bullet(self) -> None:
        payload = _payload()
        payload["commits"]["2"][1] = _DOCS + "\n  - extra.md: add extras\nConclusion line"
        moved, _ = _moved(["tests/test_a.py"], 2, payload)
        lines = moved["commits"]["2"][1].splitlines()
        assert lines.index("  - test_a.py: cover empty file") == lines.index("  - extra.md: add extras") + 1

    def test_to_new_inserts_a_block_after_the_source(self) -> None:
        payload, notes = _moved(["tests/test_a.py"], "new")
        assert [paths for paths, _ in payload["commits"].values()] == [
            ["src/a.py"], ["tests/test_a.py"], ["docs/new.md"], ["docs/PR_REVIEWS/*.json"],
        ]
        assert payload["commits"]["2"][1] == ""
        assert any("  - test_a.py: cover empty file" in note for note in notes)

    def test_emptied_source_block_is_dropped(self) -> None:
        payload, _ = _moved(["docs/new.md"], 1)
        assert [paths for paths, _ in payload["commits"].values()] == [
            ["src/a.py", "tests/test_a.py", "docs/new.md"], ["docs/PR_REVIEWS/*.json"],
        ]

    def test_rename_old_side_follows_the_new_path(self) -> None:
        payload = _payload()
        payload["commits"]["1"][0] = ["src/a.py", "src/old_b.py", "src/b.py"]
        moved, _ = _moved(["src/b.py"], 2, payload)
        assert moved["commits"]["2"][0] == ["docs/new.md", "src/b.py", "src/old_b.py"]
        assert moved["commits"]["1"][0] == ["src/a.py"]

    def test_ambiguous_basename_keeps_the_bullet_and_says_so(self) -> None:
        payload = _payload()
        message = "Chore: pkgs\n\nP.\n  - __init__.py: x"
        payload["commits"]["1"] = [["a/__init__.py", "b/__init__.py"], message]
        moved, notes = _moved(["a/__init__.py"], 2, payload)
        assert "__init__.py: x" in moved["commits"]["1"][1]
        assert any("__init__.py" in note and "ambiguous" in note for note in notes)

    def test_path_without_a_bullet_moves_with_a_note(self) -> None:
        payload = _payload()
        payload["commits"]["1"][1] = "Fix(io): read a\n\nReader failed."
        moved, notes = _moved(["tests/test_a.py"], 2, payload)
        assert "tests/test_a.py" in moved["commits"]["2"][0]
        assert any("no bullet" in note for note in notes)

    def test_continuation_lines_move_with_their_bullet(self) -> None:
        payload = _payload()
        payload["commits"]["1"][1] = _SRC + "\n    second line of the test bullet"
        moved, _ = _moved(["tests/test_a.py"], 2, payload)
        assert moved["commits"]["2"][1].splitlines()[-1] == "    second line of the test bullet"
        assert "second line" not in moved["commits"]["1"][1]

    def test_glob_entry_takes_the_bullet_naming_a_concrete_file(self) -> None:
        payload = _payload()
        payload["commits"]["3"] = [
            ["docs/PR_REVIEWS/*.json", "src/c.py"], "Chore: r\n\nR.\n  - 0078_x.json: add\n  - c.py: x",
        ]
        moved, notes = _moved(["docs/PR_REVIEWS/*.json"], 2, payload)
        assert moved["commits"]["2"][1].splitlines()[-1] == "  - 0078_x.json: add"
        assert "0078_x.json" not in moved["commits"]["3"][1]
        assert notes == []
        commits = {int(key): (paths, message) for key, (paths, message) in moved["commits"].items()}
        assert bullet_problems(commits) == []

    def test_partial_path_bullet_moves_with_its_entry(self) -> None:
        payload = _payload()
        payload["commits"]["1"] = [["src/io/a.py", "src/b.py"], "Fix: io\n\nI.\n  - io/a.py: x\n  - b.py: y"]
        moved, notes = _moved(["src/io/a.py"], 2, payload)
        assert moved["commits"]["2"][1].splitlines()[-1] == "  - io/a.py: x"
        assert notes == []

    def test_rename_bullet_naming_the_old_file_moves(self) -> None:
        payload = _payload()
        message = "Refactor: b\n\nB.\n  - a.py: x\n  - old_b.py: rename to b.py"
        payload["commits"]["1"] = [["src/a.py", "src/old_b.py", "src/b.py"], message]
        moved, notes = _moved(["src/b.py"], 2, payload)
        assert moved["commits"]["2"][1].splitlines()[-1] == "  - old_b.py: rename to b.py"
        assert "old_b.py" not in moved["commits"]["1"][1]
        assert notes == []

    def test_several_paths_to_new_follow_the_lowest_source(self) -> None:
        moved, notes = _moved(["tests/test_a.py", "docs/new.md"], "new")
        assert [paths for paths, _ in moved["commits"].values()] == [
            ["src/a.py"], ["tests/test_a.py", "docs/new.md"], ["docs/PR_REVIEWS/*.json"],
        ]
        assert [("test_a.py" in note, "new.md" in note) for note in notes] == [(True, False), (False, True)]

    def test_old_side_in_another_block_stays(self) -> None:
        payload = _payload()
        payload["commits"]["1"][0] = ["src/a.py", "tests/test_a.py", "src/b.py"]
        payload["commits"]["2"][0] = ["docs/new.md", "src/old_b.py"]
        moved, _ = _moved(["src/b.py"], 3, payload)
        assert moved["commits"]["2"][0] == ["docs/new.md", "src/old_b.py"]
        assert moved["commits"]["3"][0] == ["docs/PR_REVIEWS/*.json", "src/b.py"]

    def test_input_is_not_mutated(self) -> None:
        payload = _payload()
        before = copy.deepcopy(payload)
        _moved(["tests/test_a.py"], 2, payload)
        assert payload == before

    @pytest.mark.parametrize(
        ("paths", "to", "fragment"),
        [
            (["nope.py"], 2, "nope.py"),
            (["tests/test_a.py"], 9, "block 9"),
            (["tests/test_a.py"], 1, "already in block 1"),
            ([], 2, "no path"),
        ],
    )
    def test_bad_requests_are_problems(self, paths, to, fragment) -> None:
        with pytest.raises(CaptureError) as excinfo:
            _moved(paths, to)
        assert fragment in "\n".join(excinfo.value.problems)


class TestBulletProblems:
    def test_matching_bullets_pass(self) -> None:
        commits = {1: (["src/a.py", "tests/test_a.py"], _SRC)}
        assert bullet_problems(commits) == []

    def test_foreign_bullet_is_a_problem(self) -> None:
        commits = {
            1: (["tests/test_a.py"], "Test: a\n\nA.\n  - test_a.py: cover empty file"),
            2: (["docs/new.md"], _DOCS + "\n  - test_a.py: cover empty file"),
        }
        assert bullet_problems(commits) == ["commit 2: bullet names test_a.py, which is in commit 1"]

    def test_bullet_naming_no_entry_passes(self) -> None:
        commits = {
            1: (["README.md", "src/config.py"], "Docs: r\n\nR.\n  - README: x\n  - config.py, x.py: y"),
            2: (["tests/test_a.py"], "Test: a\n\nA.\n  - tests: z"),
        }
        assert bullet_problems(commits) == []

    def test_full_path_and_glob_entries_match(self) -> None:
        commits = {
            1: (["src/a.py"], "Fix: a\n\nA.\n  - src/a.py: x"),
            2: (["docs/PR_REVIEWS/*.json"], "Chore: r\n\nR.\n  - 0078_x.json: add"),
        }
        assert bullet_problems(commits) == []

    def test_message_without_bullets_passes(self) -> None:
        assert bullet_problems({1: (["src/a.py"], "Chore: a")}) == []
