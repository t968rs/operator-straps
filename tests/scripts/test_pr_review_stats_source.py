"""Behavioral tests for the source-only line counts of the pr-review document: ``stats.source``.

``review_meta`` and ``plan_document`` of the plugin's ``scripts/pr_review.py`` (loaded by absolute path) write
the full totals plus a ``source`` sub-object without the machine-generated paths; ``PR_REVIEW.schema.json``
pins the sub-object's shape; ``review_edit.set_stats`` keeps an existing ``source`` when it resets the totals.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from types import ModuleType
from typing import Dict, Iterator, List

import pytest
from jsonschema.validators import validator_for

from conftest import PLUGIN_ROOT
from harness_lib import review_edit as red
from harness_lib import review_plan as rp
from harness_lib.pr_summary import PrFacts, PrFile

_SCRIPT = PLUGIN_ROOT / "scripts" / "pr_review.py"
_SCHEMA = PLUGIN_ROOT / "schemas" / "PR_REVIEW.schema.json"
_SOURCE = {"additions": 3, "deletions": 1, "files_changed": 1}


@pytest.fixture(scope="module")
def script() -> Iterator[ModuleType]:
    """pr_review.py imported by absolute path, registered in ``sys.modules`` so annotations resolve."""
    spec = importlib.util.spec_from_file_location("pr_review_stats_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _facts() -> PrFacts:
    files = (PrFile("M", "src/a.py", None, 3, 1), PrFile("A", "gen/out.json", None, 40, 0))
    return PrFacts(number=7, pr_title="t", head="7-x", base="main", head_sha="h" * 40, merge_base="m" * 40,
                   date="2026-11-06", commits=("abc1234 Fix: x",), files=files)


def test_review_meta_writes_totals_and_source(script: ModuleType) -> None:
    stats = script.review_meta(_facts(), ("gen/out.json",))["stats"]
    assert stats == {"additions": 43, "deletions": 1, "files_changed": 2, "source": _SOURCE}


def test_plan_document_meta_uses_the_scope_exclusions(script: ModuleType) -> None:
    guards = rp.GuardDecision(applies=False, local=False, registry=False, reasons=(), suite=())
    scope = script.Scope(reviewable=("src/a.py",), excluded=("gen/out.json",), buckets={}, notes=(),
                         lenses={}, skills=(), guards=guards, slots=())
    plan = script.plan_document("run", {"state": "OPEN"}, _facts(), scope, {}, True, False)
    assert plan["meta"]["stats"].get("source") == _SOURCE


def _stats_errors(stats: Dict[str, object]) -> List[str]:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))["properties"]["stats"]
    return [err.message for err in validator_for(schema)(schema).iter_errors(stats)]


def test_schema_accepts_a_source_sub_object() -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))["properties"]["stats"]
    assert "source" in schema["properties"]
    assert _stats_errors({"additions": 43, "deletions": 1, "files_changed": 2, "source": _SOURCE}) == []


_MALFORMED = {
    "missing-key": {"additions": 3, "deletions": 1},
    "negative": {"additions": -1, "deletions": 1, "files_changed": 1},
    "string": {"additions": "3", "deletions": 1, "files_changed": 1},
    "extra-key": {**_SOURCE, "excluded": 1},
}


def test_schema_rejects_a_malformed_source() -> None:
    """A source missing a key, holding a negative or string count, or carrying an extra key fails."""
    accepted = [name for name, source in _MALFORMED.items()
                if not _stats_errors({"additions": 43, "deletions": 1, "files_changed": 2, "source": source})]
    assert accepted == []


def test_set_stats_keeps_an_existing_source() -> None:
    doc = {"stats": {"additions": 43, "deletions": 1, "files_changed": 2, "source": dict(_SOURCE)}}
    assert red.set_stats(doc, 50, 2, 3)["stats"] == {
        "additions": 50, "deletions": 2, "files_changed": 3, "source": _SOURCE,
    }


def test_set_stats_drops_a_source_above_the_new_totals() -> None:
    """A totals edit below the kept source counts (source.additions 3 > additions 1) drops the stale source."""
    doc = {"stats": {"additions": 43, "deletions": 1, "files_changed": 2, "source": dict(_SOURCE)}}
    assert red.set_stats(doc, 1, 0, 1)["stats"] == {"additions": 1, "deletions": 0, "files_changed": 1}
