"""The todo-editor agent drafts a ``keyword`` for every item it queues (plan 2028).

``inbox put`` refuses an item without one, so the **sync** and **add** steps that draft items name the field,
its one-word shape and ``todo_sync.py suggest-keyword``, which prints the script's guess before the put; the
**update** step lists ``keyword`` among the fields an update may set.
"""
from __future__ import annotations

import re

from conftest import PLUGIN_ROOT

AGENT = PLUGIN_ROOT / "agents" / "todo-editor.md"


def _section(name: str) -> str:
    text = AGENT.read_text(encoding="utf-8")
    match = re.search(rf"^## {name}\n(.*?)(?=^## )", text, re.MULTILINE | re.DOTALL)
    assert match is not None, f"no ## {name} section"
    return match.group(1)


def test_sync_drafts_a_keyword_from_the_suggestion() -> None:
    sync = _section("sync")
    assert "`keyword`" in sync and "suggest-keyword" in sync


def test_add_drafts_a_keyword_from_the_suggestion() -> None:
    add = _section("add")
    assert "`keyword`" in add and "suggest-keyword" in add


def test_sync_names_the_one_word_shape_and_the_refusal() -> None:
    sync = _section("sync")
    assert "one word" in sync and "lacks keyword" in sync


def test_update_lists_the_keyword() -> None:
    assert "`keyword`" in _section("update")
