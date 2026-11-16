"""Decisions on the HTML PIP: a block per decision with Chosen and Unchosen lists, a themed page (plan 1020).

A decision is a ``<section class="decision">`` headed by its id and question, then a ``Chosen`` marker line
and its option, then an ``Unchosen`` marker line and the other options, each list one bullet per option
(``<code>`` id, then the summary as written, D3), then the rationale. An open decision shows an ``Open``
marker line and lists its options. A marker is a pill drawn like a task's status badge; Chosen is bold
green and Open bold red (D5). The shared style colors headings and ``<code>`` in both the light and the
dark scheme.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from harness_lib import plan_render_html as prh
from harness_lib.plan_models import ActionPlan

WALK_ROOTS = ()
NAME = "0001_Add_operators_ActionPlan.json"
FROZEN = {"commit": "a" * 40, "tree": "b" * 40, "date": "2026-11-10", "digest": "d" * 64,
          "records": "receipts"}
OPTIONS = [{"id": "D1A", "summary": "one tool; the old entry retires"},
           {"id": "D1C", "summary": "two <entries> & one pipeline"},
           {"id": "D1D", "summary": "no change"}]


def page(chosen: Optional[str] = "D1A", rationale: Optional[str] = "Developer, 2026-11-12.") -> str:
    raw: Dict[str, Any] = {
        "plan_id": "0001", "plan_created": "2026-11-10", "execution_model": "serial", "base_commit": "e" * 40,
        "frozen": FROZEN,
        "decisions": [{"id": "D1", "question": "Entry shape?", "chosen": chosen, "rationale": rationale,
                       "options": OPTIONS}],
        "items": [{"id": "TASK-1", "title": "Add sub", "action": "Add sub.", "status": "PENDING",
                   "evidence": "not started", "files": ["src/calc.py"]}],
    }
    return prh.render_pip_html(ActionPlan.model_validate(raw), NAME)


def block(text: str) -> str:
    start = text.find('<section class="decision" id="decision-D1">')
    assert start >= 0, "no decision block for D1"
    return text[start:text.index("</section>", start)]


def test_a_decision_is_a_block_headed_by_its_id_and_question() -> None:
    text = page()
    assert "<h3>D1 Entry shape?</h3>" in block(text)
    assert "<h2>Decisions</h2>\n<ul>" not in text


CHOSEN_LINE = '<p class="pick"><span class="mark chosen">Chosen</span></p>'
UNCHOSEN_LINE = '<p class="pick"><span class="mark unchosen">Unchosen</span></p>'
OPEN_LINE = '<p class="pick"><span class="mark open">Open</span></p>'


def test_chosen_and_unchosen_sit_on_lines_of_their_own_above_their_lists() -> None:
    body = block(page())
    chosen = '<ul class="options chosen"><li><code>D1A</code> one tool; the old entry retires</li></ul>'
    unchosen = ('<ul class="options unchosen">'
                '<li><code>D1C</code> two &lt;entries&gt; &amp; one pipeline</li>'
                '<li><code>D1D</code> no change</li></ul>')
    assert chosen in body and unchosen in body
    order = [body.index(CHOSEN_LINE), body.index(chosen), body.index(UNCHOSEN_LINE), body.index(unchosen)]
    assert order == sorted(order)
    assert "Rejected" not in body


def test_a_summary_with_a_semicolon_stays_one_bullet() -> None:
    assert block(page()).count("<li><code>D1A</code>") == 1
    assert "<li>the old entry retires" not in page()


def test_the_rationale_follows_the_options() -> None:
    body = block(page())
    assert '<p class="why">Developer, 2026-11-12.</p>' in body
    assert body.index("options unchosen") < body.index('class="why"')
    assert 'class="why"' not in block(page(rationale=None))


def test_an_open_decision_lists_every_option() -> None:
    body = block(page(chosen=None))
    assert OPEN_LINE in body and "options chosen" not in body and "Unchosen" not in body
    assert body.count("<li><code>") == 3
    assert body.index(OPEN_LINE) < body.index('<ul class="options open">')


def style() -> str:
    return page().split("<style>", 1)[1].split("</style>", 1)[0]


def shared_style() -> str:
    return (prh.PAGES / "styles" / "shared.css").read_text(encoding="utf-8")


def test_the_theme_defines_accent_colors_for_both_schemes() -> None:
    css = shared_style()
    start = css.index("prefers-color-scheme: dark")
    dark = css[start:css.index("} }", start)]
    for name in ("--accent:", "--code-fg:"):
        assert name in css[:start] and name in dark


def test_headings_and_code_take_the_accent_colors() -> None:
    css = shared_style()
    assert re.search(r"h2[^{}]*\{[^}]*(?:^|[{;\s])color:\s*var\(--accent\)", css)
    assert re.search(r"(^|[}\s])code[^{}]*\{[^}]*(?:^|[{;\s])color:\s*var\(--code-fg\)", css)


def rule(css: str, selector: str) -> str:
    found = re.search(re.escape(selector) + r"[^{}]*\{([^}]*)\}", css)
    assert found, f"no rule for {selector}"
    return found.group(1)


def test_chosen_and_unchosen_options_are_told_apart_by_color() -> None:
    css = style()
    assert "var(--ok)" in rule(css, ".options.chosen")
    assert "var(--muted)" in rule(css, ".options.unchosen")


def test_a_marker_is_a_pill_like_the_status_badge() -> None:
    css = style()
    shared = re.search(r"\.status\s*,\s*\.mark\s*\{([^}]*)\}", css)
    assert shared, "the status badge and the decision markers share one rule"
    assert "border-radius" in shared.group(1) and "currentColor" in shared.group(1)


def test_the_chosen_marker_is_bold_green_and_the_open_marker_bold_red() -> None:
    css = style()
    chosen, opened = rule(css, ".mark.chosen"), rule(css, ".mark.open")
    assert "var(--muted)" in rule(css, ".mark.unchosen")
    assert "var(--ok)" in chosen and re.search(r"font-weight:\s*(700|bold)", chosen)
    assert "var(--bad)" in opened and re.search(r"font-weight:\s*(700|bold)", opened)
