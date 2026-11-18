"""Schema discipline for the three pr-review prose-table fixture JSONs.

Pins three contracts:
  1. Every fixture validates against its sibling schema.
  2. Row ids within each fixture are unique (no accidental duplicate IDs
     survive a copy-paste edit session).
  3. Adding an unknown key to any row is rejected: every sibling schema
     carries `additionalProperties: false` at the row level.

Fixtures + sibling schemas covered (all live in the plugin's
schemas/fixtures/pr-review/):
  - rationalization_table.json   + rationalization_table.schema.json
      top-level array key: "rationalizations"
  - red_flags.json               + red_flags.schema.json
      top-level array key: "flags"
  - troubleshooting.json         + troubleshooting.schema.json
      top-level array key: "items"

The ``plugin_root`` fixture comes from tests/conftest.py.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import List, Tuple

import jsonschema
import pytest


# (fixture_stem, array_key)
_FIXTURES: List[Tuple[str, str]] = [
    ("rationalization_table", "rationalizations"),
    ("red_flags", "flags"),
    ("troubleshooting", "items"),
]

_FIXTURE_IDS = [stem for stem, _ in _FIXTURES]


def _fixture_path(plugin_root: Path, stem: str) -> Path:
    return plugin_root / "schemas" / "fixtures" / "pr-review" / f"{stem}.json"


def _schema_path(plugin_root: Path, stem: str) -> Path:
    return plugin_root / "schemas" / "fixtures" / "pr-review" / f"{stem}.schema.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        pytest.fail(f"Required artifact missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Parametrize helpers
# ---------------------------------------------------------------------------

@pytest.fixture(params=_FIXTURES, ids=_FIXTURE_IDS)
def fixture_params(request):
    """Yield (fixture_stem, array_key) pairs for parametrized tests."""
    return request.param


# ---------------------------------------------------------------------------
# C2 / I5  schema-validation tests
# ---------------------------------------------------------------------------

def test_fixture_validates_against_schema(plugin_root: Path, fixture_params: Tuple[str, str]):
    """Every fixture JSON must validate against its sibling schema (C2).

    Fails if the fixture adds or removes fields that the schema does not
    describe, catching drift between schema and data.
    """
    stem, _array_key = fixture_params
    schema = _load_json(_schema_path(plugin_root, stem))
    data = _load_json(_fixture_path(plugin_root, stem))
    jsonschema.validate(data, schema)  # raises ValidationError on failure


def test_fixture_ids_are_unique(plugin_root: Path, fixture_params: Tuple[str, str]):
    """Row ids within each fixture are unique (I5).

    Duplicate IDs surface as silent overwrites when catalogs are keyed by ID
    and produce false-negative coverage in any test that iterates by ID.
    """
    stem, array_key = fixture_params
    data = _load_json(_fixture_path(plugin_root, stem))
    rows = data.get(array_key, [])
    assert rows, f"{stem}.json '{array_key}' array is empty — check the fixture"
    ids = [row.get("id") for row in rows if "id" in row]
    assert len(set(ids)) == len(ids), (
        f"{stem}.json has duplicate IDs in '{array_key}': "
        f"{[x for x in ids if ids.count(x) > 1]}"
    )


def test_extra_key_in_row_is_rejected(plugin_root: Path, fixture_params: Tuple[str, str]):
    """Adding an unknown key to any row must raise ValidationError.

    Fails when a sibling schema drops `additionalProperties: false` at the
    row-items level, so a typoed key can never validate silently.
    """
    stem, array_key = fixture_params
    schema = _load_json(_schema_path(plugin_root, stem))
    data = _load_json(_fixture_path(plugin_root, stem))
    rows = data.get(array_key, [])
    if not rows:
        pytest.skip(f"{stem}.json '{array_key}' array is empty — nothing to probe")

    # Build a copy of the full document with the first row mutated.
    mutated_data = copy.deepcopy(data)
    mutated_data[array_key][0]["xxx_typo_key"] = "z"

    with pytest.raises(jsonschema.ValidationError, match="xxx_typo_key"):
        jsonschema.validate(mutated_data, schema)
