"""The PIP markdown of a plan, rendered from its ActionPlan JSON and never edited by hand.

One ``### <ID>: <title>`` section per item. The plan rules (``todo_sync.rules_plans``) look a section up
only through the item's ``markdown_section`` and skip an item without one; the heading starts with the item
id, so a ``markdown_section`` equal to the id finds it. Each section holds one box per test node, one per
command and one for recording the commit; the boxes are checked exactly when the item is COMPLETE or
CLOSED_NO_ACTION, so the PIP always agrees with the JSON. A ``{base}`` in a command is printed as the
plan's full ``base_commit``, so a copied command runs as written.
"""
from __future__ import annotations

import re
from typing import Iterable, List

from harness_lib.plan_doc import PLAN_SUFFIX
from harness_lib.plan_enums import DONE
from harness_lib.plan_models import ActionItem, ActionPlan, Decision, DecisionOption

_NAME = re.compile(r"^\d{4}_(?P<title>.+)" + re.escape(PLAN_SUFFIX) + "$")


def code(text: str) -> str:
    """``text`` as a markdown code span, fenced past any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    if not longest:
        return f"`{text}`"
    fence = "`" * (longest + 1)
    return f"{fence} {text} {fence}"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _title(plan: ActionPlan, plan_name: str) -> str:
    match = _NAME.match(plan_name)
    head = f"# Plan {plan.plan_id}"
    return f"{head}: {match['title'].replace('_', ' ')}" if match else head


def _header(plan: ActionPlan, plan_name: str) -> List[str]:
    frozen = plan.frozen
    frozen_text = f"{frozen.date} at {code(frozen.commit[:7])}" if frozen else "no"
    base = plan.base_commit
    return [
        _title(plan, plan_name), "",
        f"> Rendered by `plan.py render` from {code(plan_name)}. Change the JSON through the driver, "
        "then render again; edits to this file are overwritten.", "",
        f"**Plan created:** {plan.plan_created}",
        f"**Spec:** {code(plan.source_document) if plan.source_document else 'none'}",
        f"**Branch:** {plan.branch or 'none'} -> {plan.base_branch or 'none'}",
        f"**Base commit:** {code(base[:7]) if base else 'none'}",
        f"**Frozen:** {frozen_text}",
        f"**Execution model:** {plan.execution_model}", "",
    ]


def _options(options: Iterable[DecisionOption]) -> str:
    return ", ".join(f"{code(o.id)} ({o.summary})" for o in options)


def _decision_line(d: Decision) -> str:
    head = f"- **{d.id}** {d.question}"
    if d.chosen is None:
        return f"{head} **Open.** Options: {_options(d.options)}."
    chosen = [o for o in d.options if o.id == d.chosen]
    rejected = [o for o in d.options if o.id != d.chosen]
    why = f" {d.rationale}" if d.rationale else ""
    return f"{head} Chosen: {_options(chosen)}. Rejected: {_options(rejected)}.{why}"


def _decisions(plan: ActionPlan) -> List[str]:
    rows = [_decision_line(d) for d in plan.decisions]
    return ["## Decisions", "", *rows, ""] if rows else []


def _values(plan: ActionPlan) -> List[str]:
    if not plan.values:
        return []
    rows = [f"| {_cell(v.name)} | {_cell(v.value)} | {_cell(v.source)} | "
            f"{_cell(', '.join(v.assumes) or '-')} |" for v in plan.values]
    return ["## Values", "", "| Name | Value | Source | Assumes |", "|---|---|---|---|", *rows, ""]


def _formats(plan: ActionPlan) -> List[str]:
    rows = [f"- **{f.name}**: {code(f.example)}, copied from {code(f.source.at)}" for f in plan.formats]
    return ["## Formats", "", *rows, ""] if rows else []


def _sweeps(plan: ActionPlan) -> List[str]:
    rows = []
    for s in plan.sweeps:
        hits = ", ".join(f"{code(p)} ({c})" for p, c in sorted(s.hits.items())) or "no hits"
        rows.append(f"- **{s.id}** {code(s.pattern)}: {hits}")
    return ["## Sweeps", "", *rows, ""] if rows else []


def _expand_base(plan: ActionPlan, run: str) -> str:
    """``run`` with each ``{base}`` replaced by the plan's ``base_commit``, when one is recorded."""
    return run.replace("{base}", plan.base_commit) if plan.base_commit else run


def _boxes(plan: ActionPlan, item: ActionItem) -> List[str]:
    mark = "x" if item.status in DONE else " "
    steps = [f"Test {code(t.node)} fails with {t.red}, then passes" for t in item.tests]
    steps += [f"Run {code(_expand_base(plan, c.run))}: {c.expect}" for c in item.commands]
    record = f"plan.py record {plan.plan_id} {item.id} --sha <sha>"
    steps.append(f"Record the commit: {code(record)}")
    return [f"- [{mark}] {step}" for step in steps]


def _item_meta(item: ActionItem) -> List[str]:
    deps = ", ".join(item.dependencies or []) or "none"
    lines = [f"**Status:** {item.status} | **Model:** {item.model} | **Depends on:** {deps}"]
    files = ", ".join(code(f) for f in item.files)
    lines.append(f"**Files:** {files or 'none'}")
    anchors = [f"- {code(a.at)} holds {code(a.expect)}" for a in item.anchors]
    return lines + (["", "**Anchors:**", *anchors] if anchors else [])


def _item(plan: ActionPlan, item: ActionItem) -> List[str]:
    out = [f"### {item.id}: {item.title}", "", *_item_meta(item), ""]
    out += [item.action, ""]
    out += [*_boxes(plan, item), "", f"**Evidence:** {item.evidence}", ""]
    refs = item.verification_references
    return out + ([*(f"- {code(r)}" for r in refs), ""] if refs else [])


def render_pip(plan: ActionPlan, plan_name: str) -> str:
    """The PIP text of ``plan``; ``plan_name`` is the plan file's name, shown in the header."""
    body = _header(plan, plan_name) + _decisions(plan) + _values(plan) + _formats(plan) + _sweeps(plan)
    body += ["## Tasks", ""]
    for item in plan.items:
        body += _item(plan, item)
    return "\n".join(body).rstrip("\n") + "\n"
