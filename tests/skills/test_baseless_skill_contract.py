"""Guard test: the ``baseless`` skill stands alone and carries the claim gate the session rules point at.

The skill is a port of an outside verification skill. A port that drifts back toward its source brings the
breaks this test catches: a trigger or pointer that assumes the source plugin, a gate that runs the whole
suite where the scoping rules hand that run to the developer, and a claim table without this repository's
own claims (a sealed plan record, a resolved review issue, a saved file, branch or PR state).

These checks pin structure other skills and the rules consume (frontmatter, the gate's steps, the claim
rows, the hedge list, the license and provenance) on a port that may drift toward its source.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _skill_parts import skill_parts  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_FOLDER = _REPO / "plugins" / "harness" / "skills" / "baseless"
_SKILL = _FOLDER / "SKILL.md"
_PROVENANCE = _REPO / "docs" / "PROVENANCE.md"
# Claim row -> a word its evidence cell must hold; "" asks only for a non-empty cell (the source's rows).
_CLAIMS = {
    "tests pass": "", "linter clean": "", "build succeeds": "", "bug fixed": "", "regression test works": "",
    "agent completed": "", "requirements met": "",
    "plan item complete": "plan.py", "review issue resolved": "commit sha", "file saved": "read back",
    "branch or pr state": "gh pr view",
}


def _parts() -> Tuple[Dict[str, str], str]:
    assert _SKILL.is_file(), "plugins/harness/skills/baseless/SKILL.md is missing"
    return skill_parts(_SKILL)


def _flat_body() -> str:
    return " ".join(_parts()[1].split()).lower()


def test_the_skill_triggers_on_its_own() -> None:
    meta = _parts()[0]
    assert meta["name"] == "baseless"
    assert meta["description"].startswith("Use when")
    assert "not installed" not in meta["description"], "the trigger waits on another plugin being absent"
    assert "argument-hint" not in meta, "a knowledge skill takes no arguments"


def test_no_text_names_the_source_plugin() -> None:
    meta, body = _parts()
    text = (meta["description"] + body).lower()
    assert "superpowers" not in text, "a pointer names the source plugin"
    assert "human partner" not in text, "the source's voice for the developer survived"


def test_the_gate_identifies_runs_reads_then_claims() -> None:
    steps = re.findall(r"^\d\. (IDENTIFY|RUN|READ|VERIFY|ONLY THEN):", _parts()[1], re.M)
    assert steps == ["IDENTIFY", "RUN", "READ", "VERIFY", "ONLY THEN"], f"the gate steps read {steps}"


def test_the_tests_pattern_claims_only_the_named_run() -> None:
    body = _parts()[1]
    pattern = re.search(r"^\*\*Tests:\*\*\n```\n(Do:.*)$", body, re.M)
    assert pattern, "the Tests key pattern has no Do line"
    claim = pattern.group(1).lower()
    assert "all tests pass" not in claim, "the Do line claims the whole suite from a by-name run"


def test_the_gate_runs_named_files_and_hands_the_suite_over() -> None:
    body = _flat_body()
    assert "name files or node ids, never a directory" in body, "no rule that a run names its files"
    assert "full-suite runs belong to the developer" in body, "no rule handing the full suite over"


def test_the_claim_table_maps_each_claim_to_its_evidence() -> None:
    rows = [line for line in _parts()[1].splitlines() if line.startswith("|") and line.count("|") >= 4]
    table = {cells[1].strip().replace("`", "").lower(): cells[2].strip().lower()
             for cells in (row.split("|") for row in rows)}
    for claim, marker in _CLAIMS.items():
        assert claim in table, f"the claim table has no {claim!r} row"
        assert table[claim], f"the {claim!r} row names no evidence"
        assert marker in table[claim], f"the {claim!r} row's evidence lacks {marker!r}"


def test_the_hedge_words_stop_a_claim() -> None:
    body = _flat_body()
    for word in ('"should"', '"probably"', '"seems to"'):
        assert word in body, f"the hedge list lacks {word}"


def test_a_subagent_success_report_is_unverified() -> None:
    assert "success report is unverified" in _flat_body(), "a subagent's report is taken as evidence"


def test_the_license_and_provenance_record_the_port() -> None:
    licence = _FOLDER / "LICENSE"
    assert licence.is_file(), "no LICENSE beside the skill"
    assert licence.read_text(encoding="utf-8").startswith("MIT License")
    provenance = _PROVENANCE.read_text(encoding="utf-8")
    row = re.search(r"^\| `plugins/harness/skills/baseless/\*\*` \|.*$", provenance, re.M)
    assert row, "docs/PROVENANCE.md has no row for the skill"
    assert "MIT" in row.group(0) and "Verbatim except" in row.group(0)
