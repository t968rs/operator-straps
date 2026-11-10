"""The HTML PIP and its ``live.js`` sidecar.

The page is rendered from the plan at freeze and is self-contained: inline CSS and JS, no network address.
It loads ``<plan_id>/live.js`` (``window.PLAN_LIVE``: the receipts and the DesignEvolution) and reloads it on a
timer with a cache-busting query; without the sidecar it shows every item PENDING and names ``plan.py render``,
which also refreshes a sidecar left stale by a pull. A plan frozen with receipts, or never frozen and bound for
receipts, renders HTML; plans frozen as sealed or legacy keep the markdown PIP. ``write_pip`` writes the
sidecar only for a frozen receipts plan.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from harness_lib import plan_record
from harness_lib import plan_render_html as prh
from harness_lib.plan_enums import RecordScheme
from harness_lib.plan_models import ActionPlan

WALK_ROOTS = ()  # walks only tmp_path
NAME = "0001_Add_operators_ActionPlan.json"
NODE = "tests/test_calc_sub.py::test_sub"
FROZEN = {"commit": "a" * 40, "tree": "b" * 40, "date": "2026-11-10", "digest": "d" * 64}


def plan(records: Optional[str] = "receipts", frozen: bool = True, first: str = "PENDING") -> ActionPlan:
    raw: Dict[str, Any] = {
        "plan_id": "0001", "plan_created": "2026-11-10", "execution_model": "serial", "base_commit": "e" * 40,
        "decisions": [{"id": "D1", "question": "Which operator first?", "chosen": "sub",
                       "options": [{"id": "sub", "summary": "subtraction"}, {"id": "mul", "summary": "product"}]}],
        "items": [{"id": "TASK-1", "title": "Add <sub> & keep add", "action": "Add sub beside add.",
                   "status": first, "evidence": "not started", "files": ["src/calc.py"],
                   "tests": [{"node": NODE, "red": "ImportError"}]},
                  {"id": "TASK-2", "title": "Add mul", "action": "Add mul.", "status": "PENDING",
                   "evidence": "not started", "files": ["src/calc.py"],
                   "commands": [{"run": "git diff {base} -- src", "expect": "a diff"}]}],
    }
    if frozen:
        raw["frozen"] = dict(FROZEN, **({"records": records} if records else {}))
    return ActionPlan.model_validate(raw)


def page() -> str:
    return prh.render_pip_html(plan(), NAME)


def test_the_page_is_self_contained() -> None:
    text = page()
    assert text.startswith("<!DOCTYPE html>")
    assert "http://" not in text and "https://" not in text
    assert "<style>" in text and "<script>" in text


def test_the_page_loads_its_sidecar_and_reloads_it() -> None:
    text = page()
    assert "0001/live.js" in text and "PLAN_LIVE" in text
    assert str(prh.RELOAD_MS) in text and "live.js?t=" in text


def test_the_page_renders_every_item_and_decision() -> None:
    text = page()
    for needle in ("TASK-1", "TASK-2", "Add mul", "D1", "Which operator first?", NODE, "src/calc.py"):
        assert needle in text


def test_plan_text_is_escaped() -> None:
    text = page()
    assert "Add &lt;sub&gt; &amp; keep add" in text and "<sub>" not in text


def test_a_command_shows_the_full_base_commit() -> None:
    assert "git diff " + "e" * 40 in page()


def test_without_the_sidecar_the_page_names_the_render_command() -> None:
    assert "plan.py render 0001" in page()


def test_the_page_says_how_to_refresh_a_stale_sidecar() -> None:
    assert "after a pull" in page()


def test_the_format_follows_the_record_scheme() -> None:
    assert prh.uses_html(plan())
    assert not prh.uses_html(plan(records="sealed"))
    assert not prh.uses_html(plan(records=None))


def test_a_never_frozen_plan_renders_html_only_when_bound_for_receipts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_record, "scheme_for", lambda _plan: RecordScheme.receipts)
    assert prh.uses_html(plan(frozen=False))
    monkeypatch.setattr(plan_record, "scheme_for", lambda _plan: RecordScheme.sealed)
    assert not prh.uses_html(plan(frozen=False))


def test_a_never_frozen_plan_with_a_status_stays_markdown() -> None:
    assert not prh.uses_html(plan(frozen=False, first="COMPLETE"))


def test_write_pip_writes_html_and_the_sidecar_for_a_receipts_plan(tmp_path: Path) -> None:
    written = prh.write_pip(tmp_path / NAME, plan())
    assert written == tmp_path / "0001_Add_operators_PIP.html" and written.is_file()
    assert (tmp_path / "0001" / "live.js").is_file()


def test_write_pip_writes_no_sidecar_for_a_plan_not_yet_frozen(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_record, "scheme_for", lambda _plan: RecordScheme.receipts)
    written = prh.write_pip(tmp_path / NAME, plan(frozen=False))
    assert written.suffix == ".html" and not (tmp_path / "0001").exists()


def test_write_pip_keeps_markdown_for_a_sealed_plan(tmp_path: Path) -> None:
    written = prh.write_pip(tmp_path / NAME, plan(records="sealed"))
    assert written == tmp_path / "0001_Add_operators_PIP.md"
    assert written.read_text(encoding="utf-8").startswith("# Plan 0001")
    assert not (tmp_path / "0001" / "live.js").exists()
