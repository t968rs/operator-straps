"""The DesignEvolution models: a plan-bound catalog of design changes, every nested shape its own class.

``DesignChange.issue`` is a ``ChangeIssue``, ``original`` a ``ChangeOriginal`` and so on; nothing is a dict
with a type name. The catalog refuses duplicate change ids, a ``doc`` key missing from ``primary_documents``
and a summary finding that names no change; ``counts()`` computes the tallies the old schema stored.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest
from pydantic import ValidationError

from harness_lib.evolution_enums import ChangePhase, IssueCategory, OutcomeCategory
from harness_lib.evolution_models import (ChangeIssue, ChangeOriginal, DesignChange, DesignEvolution,
                                          EvolutionSummary, FindingRef, IdConventions, NewOutcome,
                                          WhyNewOutcome)

ISSUE_VALUES = ["correctness", "reference-accuracy", "path-arithmetic", "signature-mismatch", "tdd-discipline",
                "bash-discipline", "dyad-drift", "merge-conflict-risk", "spec-coverage", "fail-open-semantics",
                "spec-plan-drift", "yagni"]
OUTCOME_VALUES = ["factual-correction", "execution-blocker", "merge-conflict-avoidance", "spec-source-alignment",
                  "discoverability", "mechanical-fix", "convention-compliance", "yagni", "review-pin-update"]


def change(ident: str = "EX1", **over: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "id": ident, "discovered_by": "implementer", "phase": "post-exec-start", "items": ["TASK-1"],
        "original": {"doc": "plan", "location": "TASK-1 files", "indicated": "src/calc.py only"},
        "issue": {"category": "spec-coverage", "why_categorical": "a helper module is needed",
                  "why_free_form": "sub needs a shared minus helper"},
        "new_outcome": {"doc": "plan", "indicated": "TASK-1 also writes src/helper.py"},
        "why_new_outcome": {"category": "execution-blocker", "free_form": "the test imports the helper"},
        "date": "2026-11-10",
    }
    raw.update(over)
    return raw


def catalog(*changes: Dict[str, Any], **over: Any) -> Dict[str, Any]:
    raw: Dict[str, Any] = {
        "plan_id": "0001", "feature": "Add operators", "branch_lineage": "main-->feat-x",
        "primary_documents": {"plan": "docs/PLANS/0001_Add_operators_ActionPlan.json", "spec": "docs/spec.md"},
        "changes": list(changes),
    }
    raw.update(over)
    return raw


def test_the_enums_carry_the_old_schema_values() -> None:
    assert [m.value for m in ChangePhase] == ["spec-review", "pr-bot-review", "plan-review", "post-exec-start"]
    assert [m.value for m in IssueCategory] == ISSUE_VALUES
    assert [m.value for m in OutcomeCategory] == OUTCOME_VALUES


def test_every_nested_shape_parses_to_its_own_class() -> None:
    parsed = DesignEvolution.model_validate(catalog(change()))
    entry = parsed.changes[0]
    assert isinstance(entry, DesignChange)
    assert isinstance(entry.issue, ChangeIssue) and entry.issue.category == IssueCategory.spec_coverage
    assert isinstance(entry.original, ChangeOriginal)
    assert isinstance(entry.new_outcome, NewOutcome)
    assert isinstance(entry.why_new_outcome, WhyNewOutcome)
    assert entry.phase == ChangePhase.post_exec_start


@pytest.mark.parametrize("model", [ChangeOriginal, ChangeIssue, NewOutcome, WhyNewOutcome, DesignChange,
                                   FindingRef, EvolutionSummary, IdConventions, DesignEvolution])
def test_every_model_is_closed(model: type) -> None:
    assert model.model_config.get("extra") == "forbid"


def test_an_unknown_issue_category_is_refused() -> None:
    bad = change(issue={"category": "vibes", "why_categorical": "x", "why_free_form": "y"})
    with pytest.raises(ValidationError):
        DesignEvolution.model_validate(catalog(bad))


@pytest.mark.parametrize("ident", ["EX1", "CX12", "S3", "PR104", "P7"])
def test_a_change_id_takes_a_known_prefix_and_any_number(ident: str) -> None:
    assert DesignChange.model_validate(change(ident)).id == ident


@pytest.mark.parametrize("ident", ["X1", "EX", "ex1", "EX1a"])
def test_a_change_id_without_a_known_prefix_is_refused(ident: str) -> None:
    with pytest.raises(ValidationError):
        DesignChange.model_validate(change(ident))


def test_a_change_date_defaults_to_today() -> None:
    raw = change()
    raw.pop("date")
    assert len(DesignChange.model_validate(raw).date) == len("2026-11-10")


def test_duplicate_change_ids_are_refused() -> None:
    with pytest.raises(ValidationError, match="EX1"):
        DesignEvolution.model_validate(catalog(change("EX1"), change("EX1")))


def test_a_doc_key_outside_the_primary_documents_is_refused() -> None:
    bad = change(original={"doc": "primer", "location": "s1", "indicated": "x"})
    with pytest.raises(ValidationError, match="primer"):
        DesignEvolution.model_validate(catalog(bad))


def test_the_plan_is_always_a_primary_document() -> None:
    with pytest.raises(ValidationError, match="plan"):
        DesignEvolution.model_validate(catalog(primary_documents={"spec": "docs/spec.md"}))


def test_a_summary_finding_must_name_a_change() -> None:
    summary = {"highest_impact_finding": {"id": "EX9", "rationale": "x"}}
    with pytest.raises(ValidationError, match="EX9"):
        DesignEvolution.model_validate(catalog(change(), summary=summary))


def test_a_catalog_needs_a_plan_id() -> None:
    raw = catalog()
    raw.pop("plan_id")
    with pytest.raises(ValidationError):
        DesignEvolution.model_validate(raw)


def test_pr_and_summary_are_optional() -> None:
    parsed = DesignEvolution.model_validate(catalog())
    assert parsed.pr is None and parsed.summary is None and parsed.changes == []


def test_id_conventions_is_a_class_with_a_prefix_map() -> None:
    raw = catalog(id_conventions={"comment": "sparse", "prefixes": {"EX": "self-sweep"}})
    conventions = DesignEvolution.model_validate(raw).id_conventions
    assert isinstance(conventions, IdConventions) and conventions.prefixes == {"EX": "self-sweep"}


def test_counts_tally_phase_issue_and_outcome() -> None:
    second = change("P1", phase="plan-review",
                    issue={"category": "yagni", "why_categorical": "x", "why_free_form": "y"})
    counts = DesignEvolution.model_validate(catalog(change(), second)).counts()
    assert counts.by_phase == {"post-exec-start": 1, "plan-review": 1}
    assert counts.by_issue == {"spec-coverage": 1, "yagni": 1}
    assert counts.by_outcome == {"execution-blocker": 2}


def test_a_change_is_found_by_id() -> None:
    parsed = DesignEvolution.model_validate(catalog(change("EX1"), change("EX2")))
    assert parsed.find("EX2").id == "EX2" and parsed.find("EX9") is None


def test_a_change_digest_follows_its_text() -> None:
    entry = DesignChange.model_validate(change())
    assert len(entry.digest()) == 64 and entry.digest() == DesignChange.model_validate(change()).digest()
    edited = change(why_new_outcome={"category": "execution-blocker", "free_form": "reworded later"})
    assert DesignChange.model_validate(edited).digest() != entry.digest()


def test_the_generated_evolution_schema_has_no_category_enums() -> None:
    from harness_lib import evolution_models as em
    body = em.schema_dict()
    assert "category_enums" not in body["properties"] and "plan_id" in body["required"]
