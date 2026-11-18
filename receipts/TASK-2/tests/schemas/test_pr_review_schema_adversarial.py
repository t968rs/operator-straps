"""PR_REVIEW.schema.json under ``--adversarial``: payload version 2.3.0, the REFUTED, BUBBLED and NOT_RESOLVED
resolution statuses and the optional ``adversarial_check`` entry of ``verification_log.dispatch_time``."""
from __future__ import annotations

import json
from typing import Dict

import jsonschema

from conftest import PLUGIN_ROOT
from harness_lib import review_merge as rmg

_SCHEMA_FILE = PLUGIN_ROOT / "schemas" / "PR_REVIEW.schema.json"


def _schema() -> dict:
    return json.loads(_SCHEMA_FILE.read_text(encoding="utf-8"))


def _resolution_validator() -> jsonschema.Draft202012Validator:
    definitions = _schema()["definitions"]
    return jsonschema.Draft202012Validator({"$ref": "#/definitions/post_review_resolution",
                                            "definitions": definitions})


def _dispatch_time() -> dict:
    canonical = _schema()["properties"]["verification_log"]["oneOf"][1]
    return canonical["properties"]["dispatch_time"]


def _dispatch(**extra: object) -> Dict[str, object]:
    base = {"pr_metadata_check": {"command": "gh pr view 1", "stdout": "{}", "result": "OK (state=OPEN)"},
            "structural_guards_check": {"applies": False, "command": "", "stdout_tail": "",
                                        "result": "SKIPPED (no CICD/test-infra paths in PR)"}}
    return {**base, **extra}


def _check(built: bool = True) -> Dict[str, object]:
    """An ``adversarial_check`` with the S29 fields; ``built`` adds the fields ``build`` writes."""
    out: Dict[str, object] = {
        "applies": True, "workflow": "workflows/adversarial-review.js", "code_slots": ["adv_code"],
        "refute_slots": ["adv_refute_runtime", "adv_refute_adv_code"], "result": "OK (2 checked, 1 refuted)"}
    if built:
        out.update(counts={"findings_checked": 2, "findings_refuted": 1, "findings_upheld": 1,
                           "code_findings": 1},
                   refuted_ids=["I1"], unrefuted_ids=[])
    return out


def test_schema_version_matches_the_merge_constant_and_is_at_least_2_3_0() -> None:
    version = _schema()["$version"]
    assert version == rmg.SCHEMA_VERSION
    assert tuple(int(part) for part in version.split(".")) >= (2, 3, 0), version


def test_refuted_bubbled_and_not_resolved_are_resolution_statuses() -> None:
    validator = _resolution_validator()
    for status in ("REFUTED", "BUBBLED", "NOT_RESOLVED"):
        entry = {"id": "M1", "status": status, "date": "2026-11-12", "evidence": "src/a.py:3 is guarded"}
        assert validator.is_valid(entry), status
    assert not validator.is_valid({"id": "M1", "status": "MAYBE", "date": "2026-11-12", "evidence": "e"})


def test_adversarial_check_is_optional() -> None:
    block = _dispatch_time()
    assert "adversarial_check" in block["properties"]
    assert "adversarial_check" not in block.get("required", [])
    assert jsonschema.Draft202012Validator(block).is_valid(_dispatch())


def test_adversarial_check_declares_and_accepts_the_s29_fields() -> None:
    block = _dispatch_time()
    declared = set(block["properties"].get("adversarial_check", {}).get("properties", {}))
    assert set(_check()) <= declared
    validator = jsonschema.Draft202012Validator(block)
    assert validator.is_valid(_dispatch(adversarial_check=_check()))
    assert validator.is_valid(_dispatch(adversarial_check=_check(built=False)))
    required = set(block["properties"]["adversarial_check"].get("required", []))
    assert required == {"applies", "workflow", "code_slots", "refute_slots", "result"}, required
    assert not validator.is_valid(_dispatch(adversarial_check={"applies": True}))
