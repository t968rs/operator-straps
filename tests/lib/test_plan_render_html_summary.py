"""The Status block of the HTML PIP: every task heading and its live badge, above Decisions (plan 1020, D4).

One row per item in plan order: a link to the item's section, the id and title, and a ``.status`` badge.
Every badge names its item in ``data-status-for``, the summary's and the item heading's alike, and the
loader in ``pages/components/plan.js`` draws every badge that names an item from that item's receipt.
"""
from __future__ import annotations

from typing import Any, Dict

from harness_lib import plan_render_html as prh
from harness_lib.plan_enums import ItemStatus
from harness_lib.plan_models import ActionPlan

WALK_ROOTS = ()
NAME = "0001_Add_operators_ActionPlan.json"
FROZEN = {"commit": "a" * 40, "tree": "b" * 40, "date": "2026-11-10", "digest": "d" * 64,
          "records": "receipts"}
STATUS_HEAD = '<h2 id="status">Status</h2>'


def item(ident: str, title: str) -> Dict[str, Any]:
    return {"id": ident, "title": title, "action": "Do it.", "status": "PENDING", "evidence": "not started",
            "files": ["src/calc.py"]}


def page() -> str:
    raw: Dict[str, Any] = {
        "plan_id": "0001", "plan_created": "2026-11-10", "execution_model": "serial", "base_commit": "e" * 40,
        "frozen": FROZEN,
        "decisions": [{"id": "D1", "question": "Which first?", "chosen": "sub",
                       "options": [{"id": "sub", "summary": "subtraction"},
                                   {"id": "mul", "summary": "product"}]}],
        "items": [item("TASK-2", "Add <sub> & keep add"), item("TASK-1", "Add mul"),
                  item("TASK-1.1", "Add div")],
    }
    return prh.render_pip_html(ActionPlan.model_validate(raw), NAME)


def summary(text: str) -> str:
    start = text.find(STATUS_HEAD)
    assert start >= 0, "no Status block"
    return text[start:text.index("</ul>", start)]


def test_the_status_block_sits_above_decisions() -> None:
    text = page()
    assert 0 <= text.find(STATUS_HEAD) < text.find("<h2>Decisions</h2>")


def test_the_status_block_lists_every_item_in_plan_order() -> None:
    rows = summary(page())
    links = ['<a href="#item-TASK-2">TASK-2: Add &lt;sub&gt; &amp; keep add</a>',
             '<a href="#item-TASK-1">TASK-1: Add mul</a>', '<a href="#item-TASK-1.1">TASK-1.1: Add div</a>']
    assert all(link in rows for link in links)
    assert [rows.index(link) for link in links] == sorted(rows.index(link) for link in links)


def test_every_badge_names_its_item_once_in_the_summary_and_once_in_its_heading() -> None:
    text, pending = page(), ItemStatus.PENDING.value
    for ident in ("TASK-2", "TASK-1", "TASK-1.1"):
        badge = f'<span class="status" data-status-for="{ident}" data-status="{pending}">{pending}</span>'
        assert text.count(badge) == 2
        assert badge in summary(text)


def test_the_loader_draws_every_badge_that_names_an_item() -> None:
    loader = (prh.PAGES / "components" / "plan.js").read_text(encoding="utf-8")
    assert 'querySelectorAll(".status[data-status-for]")' in loader
    assert 'getAttribute("data-status-for") === id' in loader
    assert 'querySelector(".status")' not in loader


def test_the_summary_style_ships_in_the_plan_style() -> None:
    css = (prh.PAGES / "styles" / "plan.css").read_text(encoding="utf-8")
    assert ".summary" in css
