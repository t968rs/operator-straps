"""The optional ``keyword`` of a TODO catalog item (plan 2028): one word that names what the item is about,
shown beside its id on the working-refs line. ``$defs/item`` accepts it, refuses a value that is not one
word, and still accepts an item without it (a catalog written before the field, or an item the migration
could not guess).
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

import pytest

from conftest import FIXTURES, PLUGIN_ROOT

SCHEMA_PATH = PLUGIN_ROOT / "schemas" / "catalogs" / "TodoCatalog.schema.json"
MIN_CATALOG = json.loads((FIXTURES / "todo_sync" / "TodoCatalog.min.json").read_text(encoding="utf-8"))


def _errors(item: Dict[str, Any]) -> List[Any]:
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/item"})
    return list(validator.iter_errors(item))


def _item(**over: Any) -> Dict[str, Any]:
    return {**copy.deepcopy(MIN_CATALOG["items"][0]), **over}


def test_an_item_without_a_keyword_validates() -> None:
    assert _errors(_item()) == []


@pytest.mark.parametrize("word", ["stop_gates", "merge-commit-msg", "TodoCatalog", "plan.py", "x7"])
def test_an_item_with_a_one_word_keyword_validates(word: str) -> None:
    assert _errors(_item(keyword=word)) == []


@pytest.mark.parametrize("word", ["two words", "", "-leading-dash", "a" * 33, "tab\there"])
def test_a_keyword_that_is_not_one_word_is_refused_by_its_pattern(word: str) -> None:
    validators = {e.validator for e in _errors(_item(keyword=word))}
    assert validators & {"pattern", "maxLength", "minLength"}, validators


def test_a_null_keyword_is_refused_absent_is_the_null() -> None:
    validators = {e.validator for e in _errors(_item(keyword=None))}
    assert "type" in validators, validators
