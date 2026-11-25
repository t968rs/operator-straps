"""The spec sheet API: the ``artifacts.specs`` key, where a sheet lands, and writing and reading it back."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from harness_lib.config import activate, load_config
from harness_lib.specsheet_lite_api import (
    SheetExists,
    load_sheet,
    new_sheet,
    next_step,
    sheet_path,
    write_sheet,
)

DAY = date(2026, 11, 25)


def _activate(root: Path) -> None:
    activate(load_config(root))


def _sheet():
    return new_sheet(title="Spec Sheet: lite!", request="A short brief before the plan.",
                     goals=["write-plan reads the brief as its spec."], day=DAY)


def test_specs_defaults_to_docs_specs_and_is_a_planning_prefix(make_project) -> None:
    cfg = load_config(make_project(config={}))
    assert cfg.artifacts.specs == "docs/SPECS"
    assert "docs/SPECS/" in cfg.artifacts.planning_prefixes


def test_specs_takes_the_project_value(make_project) -> None:
    cfg = load_config(make_project(config={"artifacts": {"specs": "docs/specs"}}))
    assert cfg.artifacts.specs == "docs/specs"


def test_specs_refuses_an_absolute_path(make_project) -> None:
    with pytest.raises(Exception):
        load_config(make_project(config={"artifacts": {"specs": "/abs/specs"}}))


def test_a_sheet_lands_under_specs_by_date_and_slug(make_project) -> None:
    root = make_project(config={"artifacts": {"specs": "docs/specs"}})
    _activate(root)
    assert sheet_path(_sheet()) == root / "docs/specs/2026-11-25-spec-sheet-lite.md"


def test_new_sheet_dates_today_by_default() -> None:
    sheet = new_sheet(title="T", request="R.", goals=["G holds."])
    assert sheet.day == date.today()


def test_write_then_load_round_trips(make_project) -> None:
    root = make_project(config={})
    _activate(root)
    path = write_sheet(_sheet())
    assert path.is_file() and path.parent == root / "docs/SPECS"
    assert load_sheet(path) == _sheet()


def test_write_refuses_an_existing_sheet_unless_replacing(make_project) -> None:
    _activate(make_project(config={}))
    path = write_sheet(_sheet())
    with pytest.raises(SheetExists):
        write_sheet(_sheet())
    changed = _sheet().model_copy(update={"goals": ["write-plan reads the brief first."]})
    assert write_sheet(changed, replace=True) == path
    assert load_sheet(path).goals == ["write-plan reads the brief first."]


def test_next_step_names_write_plan_with_the_sheet_as_spec(make_project) -> None:
    root = make_project(config={})
    _activate(root)
    path = write_sheet(_sheet())
    assert next_step(_sheet(), path) == (
        '/harness:write-plan "Spec Sheet: lite!" --spec docs/SPECS/2026-11-25-spec-sheet-lite.md')
