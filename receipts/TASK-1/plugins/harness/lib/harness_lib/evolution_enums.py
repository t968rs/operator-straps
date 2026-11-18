"""Closed vocabularies of a DesignEvolution catalog, standard library only.

``evolution_models`` builds the pydantic models on these. Each member's value is the JSON string stored in a
catalog file, and ``str()`` of a member is that value; the member names swap the hyphen for an underscore.
"""
from __future__ import annotations

from enum import StrEnum


class ChangePhase(StrEnum):
    """The lifecycle phase in which a design change was discovered."""

    spec_review = "spec-review"
    pr_bot_review = "pr-bot-review"
    plan_review = "plan-review"
    post_exec_start = "post-exec-start"


class IssueCategory(StrEnum):
    """What kind of problem a design change found in the original."""

    correctness = "correctness"
    reference_accuracy = "reference-accuracy"
    path_arithmetic = "path-arithmetic"
    signature_mismatch = "signature-mismatch"
    tdd_discipline = "tdd-discipline"
    bash_discipline = "bash-discipline"
    dyad_drift = "dyad-drift"
    merge_conflict_risk = "merge-conflict-risk"
    spec_coverage = "spec-coverage"
    fail_open_semantics = "fail-open-semantics"
    spec_plan_drift = "spec-plan-drift"
    yagni = "yagni"


class OutcomeCategory(StrEnum):
    """Why the new direction replaced the original."""

    factual_correction = "factual-correction"
    execution_blocker = "execution-blocker"
    merge_conflict_avoidance = "merge-conflict-avoidance"
    spec_source_alignment = "spec-source-alignment"
    discoverability = "discoverability"
    mechanical_fix = "mechanical-fix"
    convention_compliance = "convention-compliance"
    yagni = "yagni"
    review_pin_update = "review-pin-update"
