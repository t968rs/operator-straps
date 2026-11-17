"""The page theme toggle: ``pages/components/theme.js`` and the dark scheme of ``pages/styles/shared.css``.

Both renderers (the plan page and the TODO snapshot) inline the toggle script in ``<head>``, so the stored
theme applies before the body draws. The toggle cycles auto, light and dark: auto leaves ``data-theme`` off
``<html>`` and follows ``prefers-color-scheme``; light and dark set it. The choice lives in
``localStorage``, so a page that reloads itself after a render keeps it. The dark values (neutral gray
surfaces and text, Catppuccin Macchiato accents and pill colors) are the same in the media block and the
``[data-theme="dark"]`` override. Headings take ``--heading``, and every pill whose state has no color of
its own (a badge, a decision marker, the toggle) takes ``--chip``, so retuning the text colors leaves them
alone. Every page opens its body with
the fixed upper-right corner: the ``operator-straps`` brand, with the toggle placed under it.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any, Dict

import pytest

from harness_lib import plan_render_html as prh
from harness_lib.plan_models import ActionPlan
from harness_lib.todo_sync import snapshot_html as sh
from harness_lib.todo_sync.report import snapshot_header

WALK_ROOTS = ()
NODE = shutil.which("node")
#: The dark scheme: the neutral gray surfaces and text of the VS Code Dark Modern theme, with Catppuccin
#: Macchiato (https://catppuccin.com/palette) accents and pill colors.
DARK = {"--fg": "#d4d4d4", "--bg": "#1f1f1f", "--muted": "#9d9d9d", "--heading": "#ececec",
        "--line": "#3c3c3c", "--code": "#181818", "--ok": "#a6da95", "--run": "#eed49f", "--bad": "#ed8796",
        "--accent": "#8aadf4", "--code-fg": "#c6a0f6", "--chip": "#a5adcb"}
#: The light scheme keeps its look: headings in the accent blue, pills in the muted gray.
LIGHT = {"--heading": "#0550ae", "--chip": "#59636e"}
# Runs theme.js against stubbed browser globals. ``stored`` seeds localStorage (null: empty), ``corner``
# says whether the page has a ``.corner`` element, ``clicks`` presses the button that many times; the output
# is the data-theme after load and after each click, the button labels, the stored value at the end and the
# element the button went into.
THEME_HARNESS = r"""
const data = JSON.parse(require("fs").readFileSync(0, "utf8"));
const store = data.stored === null ? {} : {"harness-page-theme": data.stored};
const attrs = {};
const root = {setAttribute(k, v) { attrs[k] = v; }, removeAttribute(k) { delete attrs[k]; }};
let button = null;
let parent = null;
const body = {appendChild(el) { button = el; parent = "body"; }};
const corner = {appendChild(el) { button = el; parent = "corner"; }};
const document = {documentElement: root, body: body,
                  querySelector(sel) { return sel === ".corner" && data.corner ? corner : null; },
                  createElement() { return {}; }, addEventListener() { throw new Error("no body"); }};
const window = {localStorage: {getItem(k) { return k in store ? store[k] : null; },
                               setItem(k, v) { store[k] = String(v); }}};
new Function("window", "document", data.source)(window, document);
const themes = [attrs["data-theme"] || "auto"];
const labels = [button.textContent];
for (let i = 0; i < data.clicks; i += 1) {
  button.onclick();
  themes.push(attrs["data-theme"] || "auto");
  labels.push(button.textContent);
}
process.stdout.write(JSON.stringify({themes, labels, stored: store["harness-page-theme"] || null,
                                     id: button.id, parent}));
"""


def _theme_js() -> str:
    return (prh.PAGES / "components" / "theme.js").read_text(encoding="utf-8")


def _shared() -> str:
    return (prh.PAGES / "styles" / "shared.css").read_text(encoding="utf-8")


def _vars(block: str) -> Dict[str, str]:
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", block))


def _plan(frozen: bool) -> ActionPlan:
    raw: Dict[str, Any] = {
        "plan_id": "0001", "plan_created": "2026-11-10", "execution_model": "serial", "base_commit": "e" * 40,
        "items": [{"id": "TASK-1", "title": "Add sub", "action": "Add sub.", "status": "PENDING",
                   "evidence": "not started", "files": ["src/calc.py"]}],
    }
    if frozen:
        raw["frozen"] = {"commit": "a" * 40, "tree": "b" * 40, "date": "2026-11-10", "digest": "d" * 64,
                         "records": "receipts"}
    return ActionPlan.model_validate(raw)


def _todo_page() -> str:
    item = {"id": "todo-k7qf", "rank": 1, "title": "Title", "status": "OPEN"}
    page = sh.SnapshotPage(header=snapshot_header("docs/TODO/RepoToDo.json", 10, "0" * 64, "2026-11-17"),
                           catalog={"items": [item]}, top=[item], top_n=10, rendered="2026-11-17",
                           source="docs/TODO/RepoToDo.json")
    return sh.render_page(page)


def _head(page: str) -> str:
    return page.split("<head>", 1)[1].split("</head>", 1)[0]


def test_the_dark_media_block_applies_unless_light_is_chosen() -> None:
    css = _shared()
    start = css.index("prefers-color-scheme: dark")
    dark = css[start:css.index("} }", start)]
    assert ':root:not([data-theme="light"])' in dark
    assert _vars(dark) == DARK


def test_the_dark_override_carries_the_same_values() -> None:
    match = re.search(r':root\[data-theme="dark"\]\s*\{([^}]*)\}', _shared())
    assert match, "no :root[data-theme=dark] rule"
    assert _vars(match.group(1)) == DARK
    assert "color-scheme: dark" in match.group(1)
    assert re.search(r':root\[data-theme="light"\]\s*\{[^}]*color-scheme: light', _shared())


def test_the_light_scheme_defines_heading_and_chip_as_before() -> None:
    css = _shared()
    light = _vars(css[:css.index("prefers-color-scheme: dark")])
    assert {k: light.get(k) for k in LIGHT} == LIGHT
    assert light["--accent"] == LIGHT["--heading"] and light["--muted"] == LIGHT["--chip"]


def _rule(css: str, selector: str) -> str:
    found = re.search(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", css, re.M)
    assert found, f"no rule for {selector}"
    return found.group(1)


def test_headings_take_the_heading_color() -> None:
    assert "color: var(--heading)" in _rule(_shared(), "h1, h2, h3")
    todo = (sh.PAGES / "styles" / "todo.css").read_text(encoding="utf-8")
    assert "color: var(--heading)" in _rule(todo, "table.top th")


def test_pills_without_a_state_color_take_the_chip_color() -> None:
    plan = (prh.PAGES / "styles" / "plan.css").read_text(encoding="utf-8")
    todo = (sh.PAGES / "styles" / "todo.css").read_text(encoding="utf-8")
    assert "color: var(--chip)" in _rule(plan, ".status, .mark")
    assert "color: var(--chip)" in _rule(plan, ".mark.unchosen")
    assert "color: var(--chip)" in _rule(todo, ".badge")
    assert "color: var(--chip)" in _rule(_shared(), "#theme-toggle")


def test_the_corner_is_fixed_and_the_brand_and_toggle_have_shared_rules() -> None:
    css = _shared()
    assert re.search(r"\.corner\s*\{[^}]*position: fixed", css)
    assert re.search(r"\.brand\s*\{", css) and re.search(r"#theme-toggle\s*\{", css)


@pytest.mark.parametrize("page", [
    pytest.param(lambda: prh.render_pip_html(_plan(True), "0001_x_ActionPlan.json"), id="plan-frozen"),
    pytest.param(lambda: prh.render_pip_html(_plan(False), "0001_x_ActionPlan.json"), id="plan-draft"),
    pytest.param(_todo_page, id="todo"),
])
def test_every_page_inlines_the_toggle_in_its_head(page: Any) -> None:
    head = _head(page())
    assert f"<script>\n{_theme_js()}</script>" in head
    assert head.index("<style>") < head.index(_theme_js())


@pytest.mark.parametrize("page", [
    pytest.param(lambda: prh.render_pip_html(_plan(True), "0001_x_ActionPlan.json"), id="plan-frozen"),
    pytest.param(lambda: prh.render_pip_html(_plan(False), "0001_x_ActionPlan.json"), id="plan-draft"),
    pytest.param(_todo_page, id="todo"),
])
def test_every_page_opens_its_body_with_the_brand_corner(page: Any) -> None:
    body = page().split("<body>", 1)[1]
    corner = ('<div class="corner"><a class="brand" href="https://github.com/t968rs/operator-straps">'
              "<b>operator</b>-straps</a></div>")
    assert body.lstrip().startswith(corner)


def test_the_todo_stamp_still_reads_from_the_trailing_script() -> None:
    text = _todo_page()
    stamp = sh.page_stamp(text)
    assert stamp is not None and re.fullmatch(r"[0-9a-f]{64}", stamp)


def _run(stored: Any, clicks: int, corner: bool = True) -> Dict[str, Any]:
    feed = json.dumps({"source": _theme_js(), "stored": stored, "clicks": clicks, "corner": corner})
    done = subprocess.run([NODE, "-e", THEME_HARNESS], input=feed, capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_toggle_cycles_auto_light_dark_and_stores_the_choice() -> None:
    out = _run(None, 3)
    assert out["id"] == "theme-toggle"
    assert out["themes"] == ["auto", "light", "dark", "auto"]
    assert [label.split()[-1].lower() for label in out["labels"]] == ["auto", "light", "dark", "auto"]
    assert out["stored"] == "auto"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_stored_choice_applies_at_load_and_junk_reads_as_auto() -> None:
    assert _run("dark", 0)["themes"] == ["dark"]
    assert _run("light", 1)["themes"] == ["light", "dark"]
    assert _run("purple", 0)["themes"] == ["auto"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_toggle_goes_under_the_brand_else_into_the_body() -> None:
    assert _run(None, 0)["parent"] == "corner"
    assert _run(None, 0, corner=False)["parent"] == "body"
