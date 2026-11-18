"""Stable TODO ids: the ``todo-xxxx`` format, the generator, resolution of what a person types, and the guard
against catalogs that still carry rank-tied ``TODO-NNN`` ids."""
from __future__ import annotations

import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness_lib.todo_sync as todo_sync  # noqa: E402
from _todo_helpers import Scripted  # noqa: E402
from harness_lib.todo_sync import errors, ids  # noqa: E402
from harness_lib.todo_sync.ids import (CODE_LENGTH, PREFIX, canonical, is_id, is_legacy, mentions,  # noqa: E402
                                       new_id, require_stable, resolve_ids, taken_ids)


def _catalog(item_ids: Sequence[str], retired: Sequence[str] = (),
             legacy: Optional[Dict[str, str]] = None,
             split: Optional[Dict[str, Sequence[str]]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"items": [{"id": i, "rank": n, "title": f"Item {n}"}
                                     for n, i in enumerate(item_ids, 1)],
                           "retired_ids": list(retired)}
    if legacy is not None:
        out["legacy_ids"] = {"migrated": "2026-11-09", "map": legacy}
    if split is not None:
        out["split_ids"] = {orig: list(parts) for orig, parts in split.items()}
    return out


def test_new_ids_match_the_format_and_avoid_taken() -> None:
    rng = random.Random(243)
    taken = {"todo-p4rs"}
    drawn = []
    for _ in range(300):
        code = new_id(taken, rng)
        assert is_id(code) and code.startswith(PREFIX) and len(code) == len(PREFIX) + CODE_LENGTH
        assert code not in taken
        taken.add(code)
        drawn.append(code)
    assert len(set(drawn)) == 300


def test_new_id_redraws_codes_without_a_digit_or_letter_and_taken_codes() -> None:
    script = "sync" + "2345" + "p4rs" + "k7qf"
    assert new_id({"todo-p4rs"}, Scripted(script)) == "todo-k7qf"


@pytest.mark.parametrize("text", ["todo-sync", "todo-2345", "todo-k7q", "todo-k7qf2", "todo-k7qo",
                                  "todo-k1qf", "todo-k0qf", "todo-kiqf", "todo-klqf", "TODO-K7QF", "TODO-017",
                                  "k7qf", "todo-k7-f", ""])
def test_is_id_rejects_words_numbers_lookalikes_and_case(text: str) -> None:
    assert not is_id(text)


def test_is_id_accepts_stable_codes() -> None:
    assert is_id("todo-k7qf") and is_id("todo-2a2a") and is_id("todo-z9zz")


@pytest.mark.parametrize("raw", ["todo-k7qf", "TODO-K7QF", "k7qf", "K7QF", "  Todo-K7qf  ", "k7qf,", "K7QF;"])
def test_canonical_accepts_any_case_and_a_bare_code(raw: str) -> None:
    assert canonical(raw) == "todo-k7qf"


def test_canonical_rejects_words_numbers_and_empty() -> None:
    assert canonical("todo-sync") is None and canonical("7") is None and canonical("") is None


def test_id_re_finds_ids_in_prose_only_on_word_bounds() -> None:
    text = "See todo-k7qf, not todo-k7qfx, todo-sync or xtodo-k7qf; then todo-2a2a."
    assert ids.ID_RE.findall(text) == ["todo-k7qf", "todo-2a2a"]
    assert ids.LEGACY_RE.findall("TODO-017 and TODO-1000 but not TODO-01") == ["TODO-017", "TODO-1000"]


def test_resolve_names_the_legacy_mapping() -> None:
    catalog = _catalog(["todo-k7qf", "todo-m3x9"], retired=["todo-2a2a"],
                       legacy={"TODO-017": "todo-k7qf", "TODO-018": "todo-2a2a"})
    assert resolve_ids(catalog, ["K7QF", "todo-m3x9", "k7qf"]) == ["todo-k7qf", "todo-m3x9"]
    with pytest.raises(todo_sync.TodoSyncError) as caught:
        resolve_ids(catalog, ["17", "TODO-018", "019"])
    message = str(caught.value)
    assert "TODO-017 is a rank-tied id from before migrate-ids" in message
    assert "it meant todo-k7qf (Item 1) as of 2026-11-09; older references may name another item" in message
    assert re.search(r"TODO-018 .*it meant todo-2a2a \(retired\) as of 2026-11-09", message)
    assert "TODO-019" in message and "no legacy_ids entry" in message


@pytest.mark.parametrize("raws", [["k7qf,todo-m3x9"], ["k7qf, todo-m3x9"], ["K7QF;", "m3x9"],
                                  ["k7qf todo-m3x9,"], [",k7qf,,m3x9,"]])
def test_resolve_splits_a_joined_id_list(raws: Sequence[str]) -> None:
    catalog = _catalog(["todo-k7qf", "todo-m3x9"])
    assert resolve_ids(catalog, raws) == ["todo-k7qf", "todo-m3x9"]


def test_resolve_names_the_parts_of_a_split_id() -> None:
    catalog = _catalog(["todo-k7qf", "todo-m3x9"], retired=["todo-2a2a"],
                       split={"todo-2a2a": ["todo-k7qf", "todo-m3x9"]})
    with pytest.raises(todo_sync.TodoSyncError, match="todo-2a2a was split into todo-k7qf, todo-m3x9"):
        resolve_ids(catalog, ["2A2A"])


def test_mentions_match_any_case_on_word_bounds() -> None:
    text = "After TODO-K7QF and todo-m3x9x; not xtodo-2a2a."
    assert mentions(text, ["todo-k7qf", "todo-m3x9", "todo-2a2a"]) == ["todo-k7qf"]
    assert mentions("Both todo-m3x9 and Todo-K7qf.", ["todo-k7qf", "todo-m3x9"]) == ["todo-k7qf", "todo-m3x9"]
    assert mentions("nothing here", []) == []


def test_resolve_refuses_retired_unknown_and_malformed_ids() -> None:
    catalog = _catalog(["todo-k7qf"], retired=["todo-2a2a"])
    with pytest.raises(todo_sync.TodoSyncError) as caught:
        resolve_ids(catalog, ["todo-2a2a", "todo-m3x9", "nonsense"])
    message = str(caught.value)
    assert "todo-2a2a was retired" in message
    assert "no such item(s) in the catalog: todo-m3x9" in message
    assert "not a TODO id: 'nonsense' (use todo-k7qf or k7qf)" in message
    with pytest.raises(todo_sync.TodoSyncError, match="name at least one TODO id"):
        resolve_ids(catalog, [])


def test_taken_ids_hold_live_and_retired() -> None:
    assert taken_ids(_catalog(["todo-k7qf"], retired=["todo-2a2a"])) == {"todo-k7qf", "todo-2a2a"}
    assert taken_ids({"items": [{"id": "todo-k7qf"}]}) == {"todo-k7qf"}


def test_taken_ids_hold_ids_the_legacy_map_and_split_ids_record() -> None:
    catalog = _catalog(["todo-k7qf"], legacy={"TODO-001": "todo-k7qf", "TODO-002": "todo-z9zz"},
                       split={"todo-2a2a": ["todo-m3x9", "todo-p4rs"]})
    assert taken_ids(catalog) == {"todo-k7qf", "todo-z9zz", "todo-2a2a", "todo-m3x9", "todo-p4rs"}


def test_require_stable_names_migrate_ids() -> None:
    legacy = {"items": [{"id": "TODO-001", "rank": 1}, {"id": "TODO-002", "rank": 2}]}
    assert is_legacy(legacy) and not is_legacy(_catalog(["todo-k7qf"]))
    require_stable(_catalog(["todo-k7qf"]), "retire")
    with pytest.raises(todo_sync.TodoSyncError, match=r"^retire: .*migrate-ids --dry-run"):
        require_stable(legacy, "retire")


def test_todo_sync_error_is_one_class() -> None:
    assert todo_sync.TodoSyncError is errors.TodoSyncError
    assert "TodoSyncError" in todo_sync.__all__
