"""Drift guard for the generated ``SkillSpec.schema.json``.

Pins that the committed ``plugins/harness/schemas/SkillSpec.schema.json`` equals
``strap_models.schema_text()`` byte for byte (after CRLF -> LF, since ``text=auto`` with ``core.autocrlf``
checks JSON out with CRLF on Windows), that its ``$schema`` / ``$id`` follow the harness schemas convention,
that ``tools/gen_skillspec_schema.py`` writes the schema and its ``--check`` mode exits 0 in sync and 1 on
drift, and that a ``dump_spec`` document validates against the committed schema under Draft 2020-12.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from jsonschema import Draft202012Validator

from harness_lib import strap_models as sm

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "plugins" / "harness" / "schemas" / "SkillSpec.schema.json"
_TOOL = _REPO_ROOT / "tools" / "gen_skillspec_schema.py"
_ID = "https://github.com/t968rs/operator-straps/plugins/harness/schemas/SkillSpec.schema.json"
_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _lf(data: bytes) -> bytes:
    """Bytes with CRLF line endings folded to LF."""
    return data.replace(b"\r\n", b"\n")


def _committed() -> Dict[str, Any]:
    assert _SCHEMA.is_file(), f"missing {_SCHEMA}"
    return json.loads(_SCHEMA.read_text(encoding="utf-8"))


def _tool(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run the generator by path with the current interpreter."""
    assert _TOOL.is_file(), f"missing {_TOOL}"
    return subprocess.run([sys.executable, str(_TOOL), *args], cwd=str(cwd), capture_output=True, text=True)


def _sample_spec() -> sm.SkillSpec:
    """A spec with one mechanical and one judgment behavior, every nested model represented."""
    mech = sm.Behavior(
        id="B1", statement="writes the spec", kind=sm.BehaviorKind.MECHANICAL, rationale="state on disk",
        tests=[sm.PlannedTest(node="tests/x/test_a.py::test_a", red=sm.RedException.IMPORT_ERROR)],
    )
    check = sm.Check(kind=sm.CheckKind.FILE_UNCHANGED, target="src/a.py", expect_baseline=False,
                     expect_green=True)
    judged = sm.JudgedItem(act=sm.ReplyAct.ASKS_DEVELOPER, of="merge", expect_baseline=sm.GradeValue.ABSENT,
                           expect_green=sm.GradeValue.PRESENT)
    scenario = sm.Scenario(id="SC-1", task="merge it", tempts="merging unasked",
                           pressures=[sm.Pressure.TIME], checks=[check], judged=[judged])
    judge = sm.Behavior(id="B2", statement="asks first", kind=sm.BehaviorKind.JUDGMENT,
                        type=sm.JudgmentType.TECHNIQUE, rationale="developer owns merges",
                        scenarios=[scenario])
    return sm.SkillSpec(name="demo-skill", mode=sm.SpecMode.NEW, plugin_dir="plugins/demo",
                        behaviors=[mech, judge])


def _errors(document: Dict[str, Any]) -> List[str]:
    validator = Draft202012Validator(_committed())
    return [err.message for err in validator.iter_errors(document)]


def test_committed_schema_equals_schema_text() -> None:
    """The committed file is exactly the generator's text: no hand edits, no stale regeneration."""
    assert _SCHEMA.is_file(), f"missing {_SCHEMA}; run tools/gen_skillspec_schema.py"
    assert _lf(_SCHEMA.read_bytes()) == sm.schema_text().encode("utf-8")


def test_schema_text_leads_with_draft_and_id() -> None:
    """``$schema`` then ``$id`` come first, naming Draft 2020-12 and the file's harness schemas URL."""
    data = json.loads(sm.schema_text())
    assert list(data)[:2] == ["$schema", "$id"]
    assert data["$schema"] == _DRAFT
    assert data["$id"] == _ID


def test_committed_schema_id_names_its_location() -> None:
    """The committed ``$id`` matches the harness convention: base URL plus the path under ``schemas/``."""
    base = "https://github.com/t968rs/operator-straps/plugins/harness/schemas/"
    assert _committed()["$id"] == base + _SCHEMA.name


def test_schema_text_is_indented_json_with_trailing_newline() -> None:
    """Two-space indented JSON ending in exactly one newline, the same layout ``dump_spec`` uses."""
    text = sm.schema_text()
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert text == json.dumps(json.loads(text), indent=2) + "\n"


def test_schema_text_is_meta_valid_draft_2020_12() -> None:
    """The generated schema passes the Draft 2020-12 meta-schema."""
    Draft202012Validator.check_schema(json.loads(sm.schema_text()))


def test_schema_marks_driver_owned_top_fields() -> None:
    """Top-level properties flagged ``driver_owned`` are exactly ``DRIVER_OWNED_TOP``."""
    props = json.loads(sm.schema_text())["properties"]
    flagged = {key for key, value in props.items() if value.get("driver_owned") is True}
    assert flagged == set(sm.DRIVER_OWNED_TOP)


def test_dump_spec_validates_against_committed_schema() -> None:
    """A model-valid spec, dumped by ``dump_spec``, has no Draft 2020-12 error against the committed file."""
    assert _errors(json.loads(sm.dump_spec(_sample_spec()))) == []


@pytest.mark.parametrize("field, value", [("bogus", 1), ("mode", "rewrite")])
def test_committed_schema_rejects_invalid_document(field: str, value: Any) -> None:
    """An unknown key (``extra="forbid"``) or a non-enum ``mode`` fails schema validation."""
    document = json.loads(sm.dump_spec(_sample_spec()))
    document[field] = value
    assert _errors(document) != []


def test_tool_check_exits_zero_for_in_sync_copy(tmp_path: Path) -> None:
    """``--check --path`` on an exact copy of ``schema_text()`` exits 0."""
    target = tmp_path / "SkillSpec.schema.json"
    target.write_bytes(sm.schema_text().encode("utf-8"))
    assert _tool("--check", "--path", str(target), cwd=tmp_path).returncode == 0


def test_tool_check_accepts_crlf_checkout(tmp_path: Path) -> None:
    """A CRLF copy (a Windows ``autocrlf`` checkout) counts as in sync."""
    target = tmp_path / "SkillSpec.schema.json"
    target.write_bytes(sm.schema_text().replace("\n", "\r\n").encode("utf-8"))
    assert _tool("--check", "--path", str(target), cwd=tmp_path).returncode == 0


def test_tool_check_exits_one_on_drift_and_leaves_file(tmp_path: Path) -> None:
    """A differing copy exits 1 and ``--check`` never rewrites it."""
    target = tmp_path / "SkillSpec.schema.json"
    drifted = sm.schema_text().replace("\n", "\n ", 1).encode("utf-8")
    target.write_bytes(drifted)
    assert _tool("--check", "--path", str(target), cwd=tmp_path).returncode == 1
    assert target.read_bytes() == drifted


def test_tool_check_exits_one_on_missing_file(tmp_path: Path) -> None:
    """A missing target is drift, not a crash: exit 1."""
    missing = tmp_path / "absent.schema.json"
    assert _tool("--check", "--path", str(missing), cwd=tmp_path).returncode == 1


def test_tool_writes_schema_text(tmp_path: Path) -> None:
    """Without ``--check`` the tool writes ``schema_text()`` to ``--path`` with LF endings and exits 0."""
    target = tmp_path / "out" / "SkillSpec.schema.json"
    target.parent.mkdir()
    assert _tool("--path", str(target), cwd=tmp_path).returncode == 0
    assert target.read_bytes() == sm.schema_text().encode("utf-8")


def test_tool_check_defaults_to_committed_schema(tmp_path: Path) -> None:
    """``--check`` alone checks the committed file, resolved from the tool's location, not the cwd."""
    result = _tool("--check", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
