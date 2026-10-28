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
from typing import Any, Dict, Iterable, List, Mapping

from harness_lib.plan_doc import DONE, PLAN_SUFFIX, items_of

_NAME = re.compile(r"^\d{4}_(?P<title>.+)" + re.escape(PLAN_SUFFIX) + "$")


def code(text: str) -> str:
    """``text`` as a markdown code span, fenced past any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    if not longest:
        return f"`{text}`"
    fence = "`" * (longest + 1)
    return f"{fence} {text} {fence}"


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _title(plan: Mapping[str, Any], plan_name: str) -> str:
    match = _NAME.match(plan_name)
    head = f"# Plan {plan.get('plan_id')}"
    return f"{head}: {match['title'].replace('_', ' ')}" if match else head


def _header(plan: Mapping[str, Any], plan_name: str) -> List[str]:
    frozen = plan.get("frozen")
    frozen_text = f"{frozen['date']} at {code(frozen['commit'][:7])}" if isinstance(frozen, dict) else "no"
    base = plan.get("base_commit")
    return [
        _title(plan, plan_name), "",
        f"> Rendered by `plan.py render` from {code(plan_name)}. Change the JSON through the driver, "
        "then render again; edits to this file are overwritten.", "",
        f"**Plan created:** {plan.get('plan_created')}",
        f"**Spec:** {code(plan['source_document']) if plan.get('source_document') else 'none'}",
        f"**Branch:** {plan.get('branch') or 'none'} -> {plan.get('base_branch') or 'none'}",
        f"**Base commit:** {code(base[:7]) if base else 'none'}",
        f"**Frozen:** {frozen_text}",
        f"**Execution model:** {plan.get('execution_model')}", "",
    ]


def _options(options: Iterable[Mapping[str, Any]]) -> str:
    return ", ".join(f"{code(str(o.get('id')))} ({o.get('summary')})" for o in options)


def _decision_line(d: Mapping[str, Any]) -> str:
    options = [o for o in d.get("options") or [] if isinstance(o, dict)]
    head = f"- **{d.get('id')}** {d.get('question')}"
    if d.get("chosen") is None:
        return f"{head} **Open.** Options: {_options(options)}."
    chosen = [o for o in options if o.get("id") == d.get("chosen")]
    rejected = [o for o in options if o.get("id") != d.get("chosen")]
    why = f" {d['rationale']}" if d.get("rationale") else ""
    return f"{head} Chosen: {_options(chosen)}. Rejected: {_options(rejected)}.{why}"


def _decisions(plan: Mapping[str, Any]) -> List[str]:
    rows = [_decision_line(d) for d in plan.get("decisions") or [] if isinstance(d, dict)]
    return ["## Decisions", "", *rows, ""] if rows else []


def _values(plan: Mapping[str, Any]) -> List[str]:
    values = [v for v in plan.get("values") or [] if isinstance(v, dict)]
    if not values:
        return []
    rows = [f"| {_cell(v.get('name'))} | {_cell(v.get('value'))} | {_cell(v.get('source'))} | "
            f"{_cell(', '.join(v.get('assumes') or []) or '-')} |" for v in values]
    return ["## Values", "", "| Name | Value | Source | Assumes |", "|---|---|---|---|", *rows, ""]


def _formats(plan: Mapping[str, Any]) -> List[str]:
    rows = [f"- **{f.get('name')}**: {code(str(f.get('example')))}, copied from {code(f['source']['at'])}"
            for f in plan.get("formats") or [] if isinstance(f, dict) and isinstance(f.get("source"), dict)]
    return ["## Formats", "", *rows, ""] if rows else []


def _sweeps(plan: Mapping[str, Any]) -> List[str]:
    rows = []
    for s in plan.get("sweeps") or []:
        hits = ", ".join(f"{code(p)} ({c})" for p, c in sorted((s.get("hits") or {}).items())) or "no hits"
        rows.append(f"- **{s.get('id')}** {code(str(s.get('pattern')))}: {hits}")
    return ["## Sweeps", "", *rows, ""] if rows else []


def _expand_base(plan: Mapping[str, Any], run: Any) -> str:
    """``run`` with each ``{base}`` replaced by the plan's ``base_commit``, when one is recorded."""
    base = plan.get("base_commit")
    return str(run).replace("{base}", base) if isinstance(base, str) and base else str(run)


def _boxes(plan: Mapping[str, Any], item: Mapping[str, Any]) -> List[str]:
    mark = "x" if item.get("status") in DONE else " "
    steps = [f"Test {code(str(t.get('node')))} fails with {t.get('red')}, then passes"
             for t in item.get("tests") or []]
    steps += [f"Run {code(_expand_base(plan, c.get('run')))}: {c.get('expect')}"
              for c in item.get("commands") or []]
    record = f"plan.py record {plan.get('plan_id')} {item.get('id')} --sha <sha>"
    steps.append(f"Record the commit: {code(record)}")
    return [f"- [{mark}] {step}" for step in steps]


def _item_meta(item: Mapping[str, Any]) -> List[str]:
    deps = ", ".join(item.get("dependencies") or []) or "none"
    lines = [f"**Status:** {item.get('status')} | **Model:** {item.get('model') or 'sonnet'} | "
             f"**Depends on:** {deps}"]
    files = ", ".join(code(f) for f in item.get("files") or [])
    lines.append(f"**Files:** {files or 'none'}")
    anchors = [f"- {code(str(a.get('at')))} holds {code(str(a.get('expect')))}"
               for a in item.get("anchors") or []]
    return lines + (["", "**Anchors:**", *anchors] if anchors else [])


def _item(plan: Mapping[str, Any], item: Mapping[str, Any]) -> List[str]:
    out = [f"### {item.get('id')}: {item.get('title')}", "", *_item_meta(item), ""]
    out += [str(item.get("action")), ""]
    out += [*_boxes(plan, item), "", f"**Evidence:** {item.get('evidence')}", ""]
    refs = item.get("verification_references") or []
    return out + ([*(f"- {code(str(r))}" for r in refs), ""] if refs else [])


def render_pip(plan: Dict[str, Any], plan_name: str) -> str:
    """The PIP text of ``plan``; ``plan_name`` is the plan file's name, shown in the header."""
    body = _header(plan, plan_name) + _decisions(plan) + _values(plan) + _formats(plan) + _sweeps(plan)
    body += ["## Tasks", ""]
    for item in items_of(plan):
        body += _item(plan, item)
    return "\n".join(body).rstrip("\n") + "\n"
