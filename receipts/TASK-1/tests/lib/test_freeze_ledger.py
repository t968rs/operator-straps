"""``harness_lib.freeze_ledger``: the per-entry freeze ledger (plan 1015, LED-1).

One JSON file per entry, named ``r<N>.<k>-<kind>.json`` under ``ledger_dir(plans_dir, stem)``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

WALK_ROOTS = ()

_TREE = "a" * 40
_BASE = "b" * 40
_BLOB = "e" * 40
_DIGEST = "c" * 64
_IGNORED_HASH = "d" * 64
_PLANS_REL = "docs/plans"
_STEM = "plan/1015-freeze-tags-and-locking"


def _fields(kind: str, seq: int = 1, round_: int = 1, at: str = "2026-11-11T10:00:00Z",
            files: Optional[List[str]] = None,
            ignored: Optional[List[str]] = None) -> Dict[str, Any]:
    """Entry fields; only freeze and lock carry a tree, a digest and file maps."""
    has_tree = kind in ("freeze", "lock")
    fields: Dict[str, Any] = {
        "kind": kind, "round": round_, "seq": seq, "tree": _TREE if has_tree else None,
        "files": {p: _BLOB for p in (files or [])},
        "ignored": {p: _IGNORED_HASH for p in (ignored or [])},
        "at": at, "base": _BASE, "digest": _DIGEST if has_tree else None,
    }
    if kind == "arm":
        fields["reason"] = "design change"
    if kind == "relink":
        fields.update(old_base=_BASE, new_base="f" * 40, match="patch-id")
    return fields


def _make(mod: Any, kind: str, **opts: Any) -> Any:
    return mod.LedgerEntry.model_validate(_fields(kind, **opts))


def _ledger(mod: Any, kinds: List[str]) -> List[Any]:
    """Entries of round 1, one per kind, with seq counting up from 1."""
    return [_make(mod, kind, seq=i + 1) for i, kind in enumerate(kinds)]


def test_write_and_load_entries_round_trip(tmp_path: Path) -> None:
    from harness_lib import freeze_ledger as fl

    assert fl.plan_stem("1015", "freeze-tags-and-locking") == _STEM
    assert fl.skill_stem("write-plan") == "skill/write-plan"
    folder = fl.ledger_dir(tmp_path, _STEM)
    assert folder == tmp_path / "freezes" / "plan" / "1015-freeze-tags-and-locking"
    assert fl.ledger_dir(tmp_path, "skill/write-plan") == tmp_path / "freezes" / "skill" / "write-plan"
    assert fl.load_entries(folder) == []

    first = _make(fl, "freeze", seq=1)
    assert fl.entry_name(first) == "r1.1-freeze.json"
    written = fl.write_entry(folder, first)
    assert written == folder / "r1.1-freeze.json"
    text = written.read_bytes().decode("utf-8")
    assert text.endswith("\n") and "\r" not in text
    assert text == json.dumps(json.loads(text), indent=2) + "\n"

    fl.write_entry(folder, _make(fl, "lock", seq=10))
    fl.write_entry(folder, _make(fl, "freeze", seq=1, round_=2))
    fl.write_entry(folder, _make(fl, "lock", seq=2))
    loaded = fl.load_entries(folder)
    assert [(e.round, e.seq) for e in loaded] == [(1, 1), (1, 2), (1, 10), (2, 1)]
    assert loaded[0] == first
    assert sorted(p.name for p in folder.iterdir()) == [
        "r1.1-freeze.json", "r1.10-lock.json", "r1.2-lock.json", "r2.1-freeze.json"]
    _check_bad_files_refused(fl, tmp_path / "bad")


def _check_bad_files_refused(fl: Any, root: Path) -> None:
    """A name that disagrees with its content, and an unknown field, both raise LedgerError."""
    folder = fl.ledger_dir(root, _STEM)
    fl.write_entry(folder, _make(fl, "freeze", seq=1))
    (folder / "r1.9-freeze.json").write_text(
        (folder / "r1.1-freeze.json").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(fl.LedgerError):
        fl.load_entries(folder)

    (folder / "r1.9-freeze.json").unlink()
    data = json.loads((folder / "r1.1-freeze.json").read_text(encoding="utf-8"))
    data["surprise"] = True
    (folder / "r1.1-freeze.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(fl.LedgerError):
        fl.load_entries(folder)


def test_write_entry_refuses_existing_file(tmp_path: Path) -> None:
    from harness_lib import freeze_ledger as fl

    folder = fl.ledger_dir(tmp_path, _STEM)
    path = fl.write_entry(folder, _make(fl, "freeze", seq=1, at="2026-11-11T10:00:00Z"))
    before = path.read_bytes()

    with pytest.raises(fl.LedgerError):
        fl.write_entry(folder, _make(fl, "freeze", seq=1, at="2026-11-12T10:00:00Z"))
    assert path.read_bytes() == before
    assert [p.name for p in folder.iterdir()] == ["r1.1-freeze.json"]


def test_state_tracks_lock_arm_and_unlock() -> None:
    from harness_lib import freeze_ledger as fl

    assert fl.state([]) == fl.LedgerState.none
    assert fl.last_freeze([]) is None
    assert fl.current_round([]) == 1
    steps = [("freeze", "frozen"), ("lock", "locked"), ("arm", "armed"), ("unlock", "unlocked"),
             ("freeze", "frozen"), ("lock", "locked"), ("relink", "locked")]
    kinds: List[str] = []
    for kind, expected in steps:
        kinds.append(kind)
        entries = _ledger(fl, kinds)
        assert fl.state(entries) == fl.LedgerState[expected], kinds
    assert fl.last_freeze(entries) == entries[4]

    reopened = _ledger(fl, ["freeze"]) + [_make(fl, "reopen", seq=1, round_=2)]
    assert fl.state(reopened) == fl.LedgerState.frozen
    assert fl.current_round(reopened) == 2
    assert fl.current_round(entries) == 1
    assert {s.value for s in fl.LedgerState} == {"none", "frozen", "locked", "armed", "unlocked"}
    assert {k.value for k in fl.EntryKind} == {"freeze", "lock", "unlock", "arm", "reopen", "relink"}


def test_next_seq_counts_past_taken_tag_seqs() -> None:
    from harness_lib import freeze_ledger as fl

    entries = _ledger(fl, ["freeze", "lock"])
    assert fl.next_seq([], 1, []) == 1
    assert fl.next_seq(entries, 1, []) == 3
    assert fl.next_seq(entries, 1, [1, 2]) == 3
    assert fl.next_seq(entries, 1, [3, 5]) == 6
    assert fl.next_seq(entries, 1, iter({4})) == 5
    assert fl.next_seq([], 3, [2]) == 3
    assert fl.next_seq(entries, 2, []) == 1
    assert fl.next_seq(entries, 2, [4]) == 5


def test_locked_files_only_under_plans_folder() -> None:
    from harness_lib import freeze_ledger as fl

    files = ["docs/plans/1015/plan.json", "docs/plans/1015/tests/tests/lib/test_a.py",
             "docs/plans-old/1015/plan.json", "plugins/harness/lib/harness_lib/other.py"]
    ignored = ["docs/plans/1015/tests/tests/lib/test_b.py", "elsewhere/test_c.py"]
    freeze = _make(fl, "freeze", seq=1, files=files, ignored=ignored)
    lock = _make(fl, "lock", seq=2, files=files, ignored=ignored)
    expected = ["docs/plans/1015/plan.json", "docs/plans/1015/tests/tests/lib/test_a.py",
                "docs/plans/1015/tests/tests/lib/test_b.py"]

    assert fl.locked_files([], _PLANS_REL) == []
    assert fl.locked_files([freeze], _PLANS_REL) == []
    assert fl.locked_files([freeze, lock], _PLANS_REL) == expected
    arm = _make(fl, "arm", seq=3)
    assert fl.locked_files([freeze, lock, arm], _PLANS_REL) == expected
    unlock = _make(fl, "unlock", seq=4)
    assert fl.locked_files([freeze, lock, arm, unlock], _PLANS_REL) == []

    refreeze = _make(fl, "freeze", seq=5, files=["docs/plans/1015/plan.json"])
    relock = _make(fl, "lock", seq=6, files=["docs/plans/1015/plan.json"])
    assert fl.locked_files([freeze, lock, arm, unlock, refreeze, relock], _PLANS_REL) == [
        "docs/plans/1015/plan.json"]


def test_schema_file_matches_model() -> None:
    from harness_lib import freeze_ledger as fl

    schema_path = (Path(__file__).resolve().parents[2] / "plugins" / "harness" / "schemas"
                   / "FreezeLedgerEntry.schema.json")
    text = schema_path.read_text(encoding="utf-8")
    assert json.loads(text) == fl.LedgerEntry.model_json_schema()
    assert text.endswith("\n") and "\r" not in text
