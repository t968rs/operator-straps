"""``Round`` and ``SkillSpec.rounds`` of harness_lib.strap_models (plan 1014, MOD-1).

A reopened spec keeps each earlier freeze as a driver-owned ``Round``. A spec written before ``rounds``
existed must dump and digest byte for byte as before, so an empty ``rounds`` stays out of the dump and the
digests.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from harness_lib import strap_models as sm

_AT = "2026-11-10T00:00:00Z"
_HASH = "a" * 64


def _spec(**over: Any) -> sm.SkillSpec:
    """A frozen harness-profile edit spec with no behaviors."""
    body: Dict[str, Any] = {"name": "demo-skill", "mode": "edit", "base": "b" * 40,
                            "plugin_dir": "plugins/harness",
                            "frozen": {"skill_hash": _HASH, "grader": "session", "at": _AT}}
    return sm.SkillSpec.model_validate({**body, **over})


def _round() -> Dict[str, Any]:
    return {"base": "c" * 40, "frozen": {"skill_hash": _HASH, "grader": "session", "at": _AT},
            "behaviors": ["B1", "B2"]}


def _old_driver_digest(spec: sm.SkillSpec) -> str:
    """The driver digest as computed before ``rounds`` existed."""
    dumped = json.loads(sm.dump_spec(spec))
    owned: Dict[str, Any] = {name: dumped[name] for name in ("draws", "runs", "grades", "frozen")}
    owned["behavior_states"] = {b["id"]: {"state": b["state"]} for b in dumped["behaviors"]}
    text = json.dumps(owned, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_round_holds_base_stamp_and_behavior_ids() -> None:
    model = sm.Round.model_validate(_round())
    assert model.base == "c" * 40
    assert model.frozen.skill_hash == _HASH
    assert model.behaviors == ["B1", "B2"]


def test_rounds_is_a_driver_owned_list_before_frozen() -> None:
    assert sm.Round is not None
    fields = list(sm.SkillSpec.model_fields)
    assert "rounds" in sm.DRIVER_OWNED_TOP
    assert fields.index("rounds") < fields.index("frozen")
    assert _spec().rounds == []


def test_empty_rounds_keep_the_old_dump_and_digests() -> None:
    assert sm.Round is not None
    spec = _spec()
    assert "rounds" not in json.loads(sm.dump_spec(spec))
    assert sm.driver_digest(spec) == _old_driver_digest(spec)


def test_a_round_changes_the_driver_digest_but_not_the_authored_digest() -> None:
    bare = _spec()
    spec = _spec(rounds=[sm.Round.model_validate(_round()).model_dump(mode="json")])
    dumped = json.loads(sm.dump_spec(spec))
    assert dumped["rounds"][0]["behaviors"] == ["B1", "B2"]
    assert sm.driver_digest(spec) != sm.driver_digest(bare)
    assert sm.authored_digest(spec) == sm.authored_digest(bare)
    assert sm.SkillSpec.model_validate_json(sm.dump_spec(spec)) == spec
