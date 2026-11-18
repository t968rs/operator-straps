"""The TODO canned commit message covers the snapshot page and its stamp beside the legacy dated snapshots."""
from __future__ import annotations

from harness_lib.canned_messages import get_canned_message, has_canned_message

PAGE_FILES = ["docs/TODO/RepoToDo.json", "docs/TODO/Snapshots/TODO_Snapshot.html",
              "docs/TODO/Snapshots/todo_live.js"]


def test_the_page_and_its_stamp_take_the_todo_message() -> None:
    assert (get_canned_message(PAGE_FILES) or "").startswith("Chore(todo): ")


def test_a_legacy_dated_snapshot_still_matches() -> None:
    assert has_canned_message(["docs/TODO/Snapshots/TODO_Snapshot_2026_1116.md"])


def test_lookalikes_do_not_match() -> None:
    assert not has_canned_message(["TODO_Snapshot.htm"])
    assert not has_canned_message(["other_live.js"])
