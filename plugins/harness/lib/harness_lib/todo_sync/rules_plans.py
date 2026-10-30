"""Plan rules P1-P4: ``*_ActionPlan.json`` items against their ``*_PIP.md`` sections.

Pairs are the top-level files of ``artifacts.plans``, matched by filename prefix. A plan JSON that does not
parse is reported once, by the first P rule that reaches it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from harness_lib.plan_enums import DONE, RULES_OPEN, ItemStatus
from harness_lib.todo_sync.pip_sections import find_section, section_key
from harness_lib.todo_sync.report import Finding
from harness_lib.todo_sync.sources import PlanPair, Sources, posix

# A run of 7-40 hex characters with at least one letter: all-digit tokens (CI run ids, dates, ticket
# numbers) are not commit SHAs.
SHA = re.compile(r"\b(?=[0-9]*[a-f])[0-9a-f]{7,40}\b", re.IGNORECASE)


def _plan_items(src: Sources, rule: str, pair: PlanPair,
                out: List[Finding]) -> Optional[List[Dict[str, Any]]]:
    """The plan's items, or None (with a one-time finding when the plan does not parse)."""
    plan = pair.plan
    if plan is None:
        return None
    if not plan.ok:
        if src.claim(plan.rel):
            out.append(Finding(rule, "error", plan.rel, f"plan JSON {plan.error}", fix="Repair the JSON."))
        return None
    items = plan.data.get("items") if isinstance(plan.data, dict) else None
    return [i for i in items or [] if isinstance(i, dict)]


def _p1_item(pair: PlanPair, item: Dict[str, Any]) -> List[Finding]:
    raw = item.get("markdown_section")
    if not isinstance(raw, str) or not raw.strip():
        return []
    item_id, status = str(item.get("id")), item.get("status")
    section = find_section(pair.pip, section_key(raw))
    if section is None:
        return [Finding("P1", "warn", pair.pip_rel, f"section not found: {raw}", subject=item_id,
                        fix="Fix markdown_section or add the heading.")]
    if not section.boxes:
        return []
    if status in DONE and section.unchecked:
        n = len(section.unchecked)
        return [Finding("P1", "error", pair.pip_rel, f"{status} item has {n} unchecked box(es)",
                        line=section.unchecked[0].line, subject=item_id,
                        fix="Check the boxes, or reopen the item.")]
    if status in RULES_OPEN and not section.unchecked:
        return [Finding("P1", "error", pair.pip_rel, f"{status} item has every box checked",
                        line=section.heading.line, subject=item_id,
                        fix="Mark the item COMPLETE with evidence, or reopen a box.")]
    return []


def _p1_pair(src: Sources, pair: PlanPair, out: List[Finding], rule: str = "P1") -> List[Finding]:
    """P1 findings of one pair; an unparseable plan is reported into ``out`` under ``rule``."""
    items = _plan_items(src, rule, pair, out)
    if items is None or pair.pip is None:
        return []
    return [f for item in items for f in _p1_item(pair, item)]


def p1_checkboxes(src: Sources) -> List[Finding]:
    """P1: a done item's PIP section has every box checked; a pending one has at least one open box."""
    out: List[Finding] = []
    for pair in src.plan_pairs():
        out.extend(_p1_pair(src, pair, out))
    return out


def _names_sha(item: Dict[str, Any]) -> bool:
    """True when ``evidence`` or any ``verification_references`` string carries a 7-40 hex SHA with at
    least one hex letter."""
    refs = item.get("verification_references")
    texts = [item.get("evidence"), *(refs if isinstance(refs, list) else [])]
    return any(isinstance(t, str) and SHA.search(t) for t in texts)


def p2_evidence_sha(src: Sources) -> List[Finding]:
    """P2: a ``COMPLETE`` item names a 7-40 hex commit SHA in ``evidence`` or ``verification_references``."""
    out: List[Finding] = []
    for pair in src.plan_pairs():
        for item in _plan_items(src, "P2", pair, out) or []:
            if item.get("status") == ItemStatus.COMPLETE and not _names_sha(item):
                out.append(Finding("P2", "error", pair.plan.rel, "COMPLETE item names no commit SHA",
                                   subject=str(item.get("id")),
                                   fix="Add the commit SHA to evidence or verification_references."))
    return out


def _p3_documentation(src: Sources, pair: PlanPair) -> List[Finding]:
    doc = pair.plan.data.get("documentation") if isinstance(pair.plan.data, dict) else None
    if not isinstance(doc, str) or not doc or src.cfg.path(doc).exists():
        return []
    return [Finding("P3", "warn", pair.plan.rel, f"documentation {posix(doc)} does not exist",
                    fix="Point documentation at the PIP, or write it.")]


def p3_pair_files(src: Sources) -> List[Finding]:
    """P3 (warn): a plan's ``documentation`` exists; every PIP has a plan with the same prefix."""
    out: List[Finding] = []
    for pair in src.plan_pairs():
        if pair.plan is None:
            out.append(Finding("P3", "warn", pair.pip_rel, f"no {pair.prefix}_ActionPlan.json beside the PIP",
                               fix="Add the plan JSON, or rename the PIP to its plan's prefix."))
        elif _plan_items(src, "P3", pair, out) is not None:
            out.extend(_p3_documentation(src, pair))
    return out


def p4_sync_claim(src: Sources) -> List[Finding]:
    """P4: ``markdown_sync_status: in_sync`` is not claimed while P1 has an error for the plan."""
    out: List[Finding] = []
    for pair in src.plan_pairs():
        p1_errors = [f for f in _p1_pair(src, pair, out, "P4") if f.severity == "error"]
        status = pair.plan.data.get("markdown_sync_status") if p1_errors else None
        if status == "in_sync":
            out.append(Finding("P4", "error", pair.plan.rel,
                               f"markdown_sync_status is in_sync but P1 has {len(p1_errors)} error(s)",
                               fix="Sync the PIP, or set markdown_sync_status to pending_markdown_sync."))
    return out
