"""The plan page's CSS and JS live as asset files under ``plugins/harness/pages`` (plan 1020, D1 and D2).

``plan_render_html`` reads ``pages/styles/shared.css``, ``pages/styles/plan.css`` and
``pages/components/plan.js`` from the plugin root when it renders, and inlines them, so the page stays
self-contained and opens from disk. The module holds no ``_STYLE`` or ``_LOADER`` literal.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from harness_lib import plan_render_html as prh
from harness_lib.plan_models import ActionPlan
from harness_lib.project import plugin_root

WALK_ROOTS = ()
NAME = "0001_Add_operators_ActionPlan.json"
FROZEN = {"commit": "a" * 40, "tree": "b" * 40, "date": "2026-11-10", "digest": "d" * 64,
          "records": "receipts"}


def plan() -> ActionPlan:
    raw: Dict[str, Any] = {
        "plan_id": "0001", "plan_created": "2026-11-10", "execution_model": "serial", "base_commit": "e" * 40,
        "frozen": FROZEN,
        "items": [{"id": "TASK-1", "title": "Add sub", "action": "Add sub.", "status": "PENDING",
                   "evidence": "not started", "files": ["src/calc.py"]}],
    }
    return ActionPlan.model_validate(raw)


def asset(folder: str, name: str) -> str:
    return (prh.PAGES / folder / name).read_text(encoding="utf-8")


def style_of(page: str) -> str:
    return page.split("<style>", 1)[1].split("</style>", 1)[0]


def test_pages_sit_under_the_plugin_root() -> None:
    assert prh.PAGES == plugin_root() / "pages"


def test_the_page_inlines_the_shared_style_then_the_plan_style() -> None:
    shared, own = asset("styles", "shared.css"), asset("styles", "plan.css")
    style = style_of(prh.render_pip_html(plan(), NAME))
    assert shared.strip() and own.strip()
    assert shared.strip() in style and own.strip() in style
    assert style.index(shared.strip()) < style.index(own.strip())


def test_the_shared_style_holds_the_theme_and_the_plan_style_the_page_rules() -> None:
    shared, own = asset("styles", "shared.css"), asset("styles", "plan.css")
    assert "prefers-color-scheme: dark" in shared and "--fg:" in shared
    assert ".status" in own and ".receipt" in own
    assert ".status" not in shared


def test_the_page_inlines_the_loader() -> None:
    loader = asset("components", "plan.js")
    assert "PLAN_LIVE" in loader and "PIP.src" in loader
    assert loader.strip() in prh.render_pip_html(plan(), NAME)


def test_the_module_holds_no_asset_literals() -> None:
    assert not hasattr(prh, "_STYLE") and not hasattr(prh, "_LOADER")
    source = Path(prh.__file__).read_text(encoding="utf-8")
    assert "prefers-color-scheme" not in source and "querySelectorAll" not in source


def test_no_views_folder_ships() -> None:
    assert prh.PAGES.is_dir() and not (prh.PAGES / "views").exists()


def test_the_literal_ban_scans_page_assets() -> None:
    from contract import test_no_repo_literals as literals
    scanned = {p.relative_to(literals.REPO_ROOT).as_posix() for p in literals.FILES}
    assert {"plugins/harness/pages/styles/shared.css", "plugins/harness/pages/styles/plan.css",
            "plugins/harness/pages/components/plan.js"} <= scanned
