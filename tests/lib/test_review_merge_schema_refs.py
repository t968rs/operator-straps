"""``review_merge.review_validator`` loads a sibling schema only when a ``$ref`` names it.

An unrelated sibling (one without ``$schema``, or one that is not even JSON) never breaks review validation,
and a referenced sibling without ``$schema`` is read as draft 2020-12. A ``$ref`` resolves by the sibling's
file name, both bare (a schema without ``$id``) and against the referring schema's ``$id``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from harness_lib import review_merge as rmg

_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_BASE = "https://example.invalid/schemas/"


def _write(folder: Path, name: str, body: Dict[str, object]) -> Path:
    path = folder / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _review_schema(folder: Path, ref: str, schema_id: Optional[str] = None) -> Path:
    """A review schema whose ``pr`` property is ``$ref: ref``."""
    body: Dict[str, object] = {"$schema": _DIALECT, "type": "object",
                               "properties": {"pr": {"$ref": ref}}, "required": ["pr"]}
    if schema_id:
        body["$id"] = schema_id
    return _write(folder, "PR_REVIEW.schema.json", body)


def _int_child(folder: Path) -> None:
    """``Child.schema.json``: an integer, with no ``$schema`` keyword."""
    _write(folder, "Child.schema.json", {"type": "integer"})


def test_an_unreferenced_sibling_without_dialect_is_never_loaded(tmp_path: Path) -> None:
    _write(tmp_path, "Loose.schema.json", {"type": "object"})
    (tmp_path / "Broken.schema.json").write_text("{not json", encoding="utf-8")
    schema = _write(tmp_path, "PR_REVIEW.schema.json",
                    {"$schema": _DIALECT, "type": "object", "required": ["pr"]})
    validator = rmg.review_validator(schema)
    assert validator.is_valid({"pr": 1})
    assert not validator.is_valid({})


def test_a_bare_ref_resolves_to_a_sibling_read_as_2020_12(tmp_path: Path) -> None:
    _int_child(tmp_path)
    validator = rmg.review_validator(_review_schema(tmp_path, "Child.schema.json"))
    assert validator.is_valid({"pr": 7})
    assert not validator.is_valid({"pr": "seven"})


def test_a_ref_relative_to_the_schema_id_resolves_to_the_sibling(tmp_path: Path) -> None:
    _int_child(tmp_path)
    schema = _review_schema(tmp_path, "Child.schema.json", schema_id=_BASE + "PR_REVIEW.schema.json")
    validator = rmg.review_validator(schema)
    assert validator.is_valid({"pr": 7})
    assert not validator.is_valid({"pr": "seven"})
