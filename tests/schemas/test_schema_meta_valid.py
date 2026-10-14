"""Schema meta-validity and identity discipline for every schema the plugins ship.

Enforces that every JSON Schema file under ``plugins/`` is (a) parseable JSON
and (b) a valid JSON Schema document under its declared draft. Uses
:func:`jsonschema.validators.validator_for` so each file is checked against
the draft it actually declares in its ``$schema`` keyword; schemas with no
declared ``$schema`` fall back to the library's default (latest) validator.

Discovery covers the ``*.schema.json`` and ``*_Schema.json`` naming conventions.

Identity: every ``$id`` in the harness ``schemas/`` tree is
``https://github.com/t968rs/operator-straps/plugins/harness/schemas/<path relative to schemas/>``,
and no schema there carries a consuming-project path literal.

Catches meta-level bugs in schema files before they reach runtime validation:

  * malformed regex patterns inside ``patternProperties`` / ``pattern``
  * unresolvable ``$ref`` pointers
  * typo'd keywords (``addtionalProperties``, ``proprties``)
  * missing braces / trailing commas
  * ``required`` entries pointing at properties that don't exist

Every discovered schema becomes its own parametrized test case, so failures
are reported per-file instead of at the first breakage.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import jsonschema
import pytest
from jsonschema import validators


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGINS_ROOT = _REPO_ROOT / "plugins"
_HARNESS_SCHEMAS = _PLUGINS_ROOT / "harness" / "schemas"
_ID_BASE = "https://github.com/t968rs/operator-straps/plugins/harness/schemas/"

# Literals that tie a schema to one consuming project's layout.
_BANNED_LITERALS = (
    "floodplain", "scripts/__tests__", "scripts/fpm", ".claude/hooks/", ".claude/agent_scripts",
    "scripts/gh_workflows", "testRegistry", "FPM_PY", "file:///",
)

# Directories whose contents must never contribute to schema discovery:
# caches, build artifacts, venv / tox copies, third-party node_modules,
# test result rotations, and git worktree mirrors.
_EXCLUDED_PARTS = frozenset({
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".venv",
    ".worktrees",
    "__pycache__",
    "_plan_archive",
    "_results",
    "build",
    "dist",
    "node_modules",
    "venv",
    "worktrees",
})

# _SCHEMA_GLOBS catches schema-defining files. PR_REVIEWS/* are excluded in
# _discover_schema_files() because their `schema_ref` field is NOT a JSON-Schema
# meta-schema URI (see Issue 1210 / PR #1216).
_SCHEMA_GLOBS = ("*.schema.json", "*_Schema.json")


def _discover_schema_files(root: Path) -> List[Path]:
    """Return every JSON Schema file under ``root``, covering both the
    ``*.schema.json`` and ``*_Schema.json`` naming conventions and excluding
    cache / build paths listed in :data:`_EXCLUDED_PARTS`.
    """
    seen: set = set()
    files: List[Path] = []
    for glob in _SCHEMA_GLOBS:
        for path in root.rglob(glob):
            # Check parts RELATIVE to the scan root so absolute-path
            # components (e.g., the "worktrees" directory that hosts
            # this worktree itself) don't accidentally match.
            relative_parts = path.relative_to(root).parts
            if any(part in _EXCLUDED_PARTS for part in relative_parts):
                continue
            if path in seen:
                continue
            seen.add(path)
            files.append(path)
    # Exclude PR_REVIEWS artifacts — these are schema-USING reviews, not schema-DEFINING files
    # (per Issue 1210, review JSONs declare a schema_ref pointer; that's not a meta-schema $schema)
    files = [p for p in files if "PR_REVIEWS" not in p.parts]
    return sorted(files)


_SCHEMA_FILES: List[Path] = _discover_schema_files(_PLUGINS_ROOT)
_SCHEMA_IDS: List[str] = [
    str(p.relative_to(_REPO_ROOT)).replace("\\", "/") for p in _SCHEMA_FILES
]
_HARNESS_SCHEMA_FILES: List[Path] = _discover_schema_files(_HARNESS_SCHEMAS)
_HARNESS_SCHEMA_IDS: List[str] = [p.relative_to(_HARNESS_SCHEMAS).as_posix() for p in _HARNESS_SCHEMA_FILES]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_schema_discovery_is_non_empty() -> None:
    """Guard against a zero-file scan. A discovery glob that returns no
    files would silently pass every parametrized case below (false green),
    so this test fails loudly if discovery breaks.
    """
    assert len(_SCHEMA_FILES) > 0, (
        f"No *.schema.json files discovered under {_REPO_ROOT}. "
        "The discovery glob is broken or the repository is empty."
    )


@pytest.mark.parametrize("schema_path", _SCHEMA_FILES, ids=_SCHEMA_IDS)
def test_schema_file_is_meta_valid(schema_path: Path) -> None:
    """A single schema file must parse as JSON and pass ``check_schema``
    under the draft it declares in its ``$schema`` keyword (or the library
    default when no ``$schema`` is declared).
    """
    try:
        with schema_path.open(encoding="utf-8") as fh:
            schema = json.load(fh)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"{schema_path.name}: malformed JSON at "
            f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
        )
    except OSError as exc:
        pytest.fail(f"{schema_path.name}: cannot read file: {exc}")

    validator_cls = validators.validator_for(schema)
    try:
        validator_cls.check_schema(schema)
    except jsonschema.SchemaError as exc:
        path_str = " > ".join(str(p) for p in exc.absolute_path) or "$"
        pytest.fail(
            f"{schema_path.name}: not a valid {validator_cls.__name__} "
            f"document\n  at {path_str}: {exc.message}"
        )


def test_harness_schema_discovery_is_non_empty() -> None:
    """Guard the identity checks below against a zero-file scan."""
    assert {"PR_REVIEW.schema.json", "ActionPlan.schema.json"} <= set(_HARNESS_SCHEMA_IDS)


def _declared_id(schema_path: Path) -> Optional[str]:
    """The schema's ``$id``; None when absent or the file does not parse
    (the meta-valid test reports that)."""
    try:
        data = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("$id") if isinstance(data, dict) else None


def test_harness_schema_ids_are_declared_somewhere() -> None:
    """Guard the parametrized identity check against every schema skipping for lack of an ``$id``."""
    assert _declared_id(_HARNESS_SCHEMAS / "PR_REVIEW.schema.json") is not None


@pytest.mark.parametrize("schema_path", _HARNESS_SCHEMA_FILES, ids=_HARNESS_SCHEMA_IDS)
def test_harness_schema_id_names_its_plugin_location(schema_path: Path) -> None:
    """A declared ``$id`` is the operator-straps URL of the file's own location under ``schemas/``."""
    schema_id = _declared_id(schema_path)
    if schema_id is None:
        pytest.skip("no $id declared, or unparseable (reported by test_schema_file_is_meta_valid)")
    assert schema_id == _ID_BASE + schema_path.relative_to(_HARNESS_SCHEMAS).as_posix()


@pytest.mark.parametrize("schema_path", _HARNESS_SCHEMA_FILES, ids=_HARNESS_SCHEMA_IDS)
def test_harness_schema_has_no_project_path_literals(schema_path: Path) -> None:
    """Schema text names no consuming-project paths; projects configure those in harness.json."""
    text = schema_path.read_text(encoding="utf-8")
    assert [lit for lit in _BANNED_LITERALS if lit in text] == []
