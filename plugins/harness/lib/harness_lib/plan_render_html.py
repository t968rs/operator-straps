"""The HTML PIP of a receipts plan: one self-contained page that redraws itself from a ``live.js`` sidecar.

The page carries the frozen plan (header, status, decisions, values, formats, sweeps, items) as escaped
HTML with inline CSS and JS and no network address, so it opens from disk. The CSS and the loader script
are asset files under ``PAGES`` (``pages/styles/shared.css``, ``pages/styles/plan.css``,
``pages/components/plan.js`` in the plugin root), read when a page renders: the CSS is always inlined, the
loader script only on a plan frozen with receipts. Its script adds
``<script src="<plan_id>/live.js?t=<ms>">`` and re-adds it every ``RELOAD_MS`` with a fresh ``t``; the
sidecar sets ``window.PLAN_LIVE`` (receipts, the DesignEvolution catalog, the build time). Each load redraws
only the live parts: every item's status (drawn into both its heading badge and its Status-block badge)
and receipt, the DesignEvolution entries linked from the items they
name, and the build time. Without ``PLAN_LIVE`` every item reads PENDING and the page names
``plan.py render <plan_id>``, the command that writes the sidecar (and refreshes one left stale by a pull).
Only a plan frozen with receipts has a sidecar: the page of a plan not frozen yet carries neither the loader
nor that note, only a note that the live parts appear after ``plan.py freeze``.
A ``{base}`` in a command is printed as the plan's full ``base_commit``, as in the markdown PIP.
``write_pip`` picks the format (``uses_html``) and writes the sidecar for a frozen receipts plan; it is what
``plan.py new``, ``plan_api.write`` and ``freeze`` write. ``refresh_pip`` is what ``plan.py render`` writes.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from harness_lib import plan_live, plan_receipts, plan_record
from harness_lib.plan_doc import pip_html_path, pip_path
from harness_lib.plan_enums import ItemStatus, OutcomeKind, RecordScheme
from harness_lib.plan_models import (ActionItem, ActionPlan, Blocked, Closed, Completed, Decision,
                                     DecisionOption, Started)
from harness_lib.plan_render import _NAME, _expand_base, render_pip
from harness_lib.project import plugin_root

RELOAD_MS = 3000
PAGES = plugin_root() / "pages"
_PENDING = ItemStatus.PENDING.value
# Outcome kind -> the item status it implies, read from the outcome models so the page cannot drift.
_KIND_STATUS: Dict[str, str] = {
    OutcomeKind.complete.value: Completed.status.value, OutcomeKind.started.value: Started.status.value,
    OutcomeKind.blocked.value: Blocked.status.value, OutcomeKind.closed.value: Closed.status.value,
}


def uses_html(plan: ActionPlan) -> bool:
    """The plan's PIP is HTML: frozen with receipts, or never frozen and bound for receipts (D6)."""
    if plan.frozen is not None:
        return plan.frozen.records == RecordScheme.receipts
    return plan_record.scheme_for(plan) == RecordScheme.receipts


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _code(text: object) -> str:
    return f"<code>{_e(text)}</code>"


def _asset(folder: str, name: str) -> str:
    """The text of ``pages/<folder>/<name>``, read when called."""
    return (PAGES / folder / name).read_text(encoding="utf-8")


def _style() -> str:
    """The page CSS: the shared theme, then the plan page rules."""
    return _asset("styles", "shared.css") + _asset("styles", "plan.css")


def _title(plan: ActionPlan, plan_name: str) -> str:
    match = _NAME.match(plan_name)
    head = f"Plan {plan.plan_id}"
    return f"{head}: {match['title'].replace('_', ' ')}" if match else head


def _live_note(plan: ActionPlan) -> str:
    """The sidecar note of a frozen receipts plan; on any other plan, the note that live parts come later."""
    if not plan_receipts.uses_receipts(plan):
        return (f'<p class="note">Not frozen yet: every item reads PENDING. Receipts and design changes '
                f"appear after {_code(f'plan.py freeze {plan.plan_id}')} writes live.js.</p>")
    render = _code(f"plan.py render {plan.plan_id}")
    return (f'<p class="note"><span id="live-missing">No live.js beside this page, so every item reads '
            f"PENDING: run {render} to write it.</span>"
            f'<span id="live-built" hidden>live.js built <code id="live-built-at"></code>; '
            f"after a pull, run {render}.</span></p>")


def _origin_note(plan_name: str) -> str:
    writers = ", ".join(_code(w) for w in ("plan.py new", "plan_api.write", "plan.py freeze"))
    return (f'<p class="note">Written by {writers} from {_code(plan_name)}; {_code("plan.py render")} '
            "restores a missing page and its live.js. Change the JSON through the driver; edits to this file "
            "are overwritten.</p>")


def _header(plan: ActionPlan, plan_name: str) -> List[str]:
    frozen = plan.frozen
    # A legacy stamp names its commit; a ledger stamp has only the tree.
    at = (frozen.commit or frozen.tree or "")[:7] if frozen else ""
    frozen_text = f"{_e(frozen.date)} at {_code(at)}" if frozen else "no"
    rows = [("Plan created", _e(plan.plan_created)),
            ("Spec", _code(plan.source_document) if plan.source_document else "none"),
            ("Branch", f"{_e(plan.branch or 'none')} -&gt; {_e(plan.base_branch or 'none')}"),
            ("Base commit", _code(plan.base_commit[:7]) if plan.base_commit else "none"),
            ("Frozen", frozen_text), ("Execution model", _e(plan.execution_model))]
    cells = "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in rows)
    return [f"<h1>{_e(_title(plan, plan_name))}</h1>", _origin_note(plan_name),
            _live_note(plan), f'<dl class="head">{cells}</dl>']


def _options(options: Iterable[DecisionOption], kind: str) -> str:
    """One marker line, then one bullet per option: its id, then its summary as written."""
    label = kind.capitalize()
    items = "".join(f"<li>{_code(o.id)} {_e(o.summary)}</li>" for o in options)
    return (f'<p class="pick"><span class="mark {kind}">{label}</span></p>'
            f'<ul class="options {kind}">{items}</ul>')


def _decision(d: Decision) -> str:
    """A decision block: its id and question, the option lists under their markers, then the rationale."""
    if d.chosen is None:
        lists = _options(d.options, "open")
    else:
        lists = (_options([o for o in d.options if o.id == d.chosen], "chosen")
                 + _options([o for o in d.options if o.id != d.chosen], "unchosen"))
    why = f'<p class="why">{_e(d.rationale)}</p>' if d.rationale else ""
    return (f'<section class="decision" id="decision-{_e(d.id)}">'
            f"<h3>{_e(d.id)} {_e(d.question)}</h3>{lists}{why}</section>")


def _section(title: str, rows: List[str], tag: Optional[str] = "ul") -> List[str]:
    """A titled section of ``rows`` inside ``tag``, or bare when ``tag`` is None; nothing without rows."""
    if not rows:
        return []
    wrapped = rows if tag is None else [f"<{tag}>", *rows, f"</{tag}>"]
    return [f"<h2>{title}</h2>", *wrapped]


def _values(plan: ActionPlan) -> List[str]:
    rows = [f"<tr><td>{_e(v.name)}</td><td>{_e(v.value)}</td><td>{_e(v.source)}</td>"
            f"<td>{_e(', '.join(v.assumes) or '-')}</td></tr>" for v in plan.values]
    head = "<tr><th>Name</th><th>Value</th><th>Source</th><th>Assumes</th></tr>"
    return _section("Values", [head, *rows] if rows else [], "table")


def _formats(plan: ActionPlan) -> List[str]:
    return _section("Formats", [f"<li><strong>{_e(f.name)}</strong>: {_code(f.example)}, copied from "
                                f"{_code(f.source.at)}</li>" for f in plan.formats])


def _sweeps(plan: ActionPlan) -> List[str]:
    rows = []
    for s in plan.sweeps:
        hits = ", ".join(f"{_code(p)} ({_e(c)})" for p, c in sorted(s.hits.items())) or "no hits"
        rows.append(f"<li><strong>{_e(s.id)}</strong> {_code(s.pattern)}: {hits}</li>")
    return _section("Sweeps", rows)


def _item_meta(item: ActionItem) -> List[str]:
    deps = ", ".join(_e(d) for d in item.dependencies or []) or "none"
    files = ", ".join(_code(f) for f in item.files) or "none"
    lines = [f'<p class="meta"><strong>Model:</strong> {_e(item.model)} | <strong>Depends on:</strong> '
             f"{deps}</p>", f"<p><strong>Files:</strong> {files}</p>"]
    anchors = [f"<li>{_code(a.at)} holds {_code(a.expect)}</li>" for a in item.anchors]
    return lines + (["<p><strong>Anchors:</strong></p>", "<ul>", *anchors, "</ul>"] if anchors else [])


def _steps(plan: ActionPlan, item: ActionItem) -> List[str]:
    steps = [f"<li>Test {_code(t.node)} fails with {_e(t.red)}, then passes</li>" for t in item.tests]
    steps += [f"<li>Run {_code(_expand_base(plan, c.run))}: {_e(c.expect)}</li>" for c in item.commands]
    record = f"plan.py record {plan.plan_id} {item.id} --sha <sha>"
    steps.append(f"<li>Record it: {_code(record)} or {_code('--staged')}</li>")
    return ["<ul>", *steps, "</ul>"]


def _badge(ident: str) -> str:
    """The pending status badge of the item with id ``ident``, escaped here; the loader redraws it."""
    return f'<span class="status" data-status-for="{_e(ident)}" data-status="{_PENDING}">{_PENDING}</span>'


def _summary(plan: ActionPlan) -> List[str]:
    """The Status block: one linked heading and live badge per item in plan order; nothing without items."""
    rows = []
    for item in plan.items:
        ident = _e(item.id)
        rows.append(f'<li><a href="#item-{ident}">{ident}: {_e(item.title)}</a> {_badge(item.id)}</li>')
    if not rows:
        return []
    return ['<h2 id="status">Status</h2>', '<ul class="summary">', *rows, "</ul>"]


def _item(plan: ActionPlan, item: ActionItem) -> List[str]:
    ident = _e(item.id)
    return [f'<section class="item" id="item-{ident}" data-item="{ident}">',
            f"<h3>{ident}: {_e(item.title)} {_badge(item.id)}</h3>",
            *_item_meta(item), f'<p class="action">{_e(item.action)}</p>', *_steps(plan, item),
            '<div class="receipt"><p class="note">No receipt.</p></div>',
            '<p class="changes" hidden></p>', "</section>"]


def _evolution() -> List[str]:
    return ['<h2 id="evolution">Design evolution</h2>',
            '<div id="evolution-entries"><p class="note">No DesignEvolution catalog in live.js.</p></div>']


def _script(plan: ActionPlan) -> str:
    """The page script: the plan's sidecar address, reload interval and status table, then the loader."""
    config = {"src": f"{plan.plan_id}/live.js?t=", "reloadMs": RELOAD_MS, "kinds": _KIND_STATUS,
              "pending": _PENDING}
    text = json.dumps(config, sort_keys=True).replace("<", "\\u003c")
    return f"<script>\nvar PIP = {text};\n{_asset('components', 'plan.js')}</script>"


def render_pip_html(plan: ActionPlan, plan_name: str) -> str:
    """The HTML PIP of ``plan``; ``plan_name`` is the plan file's name, shown in the header.

    The loader script that polls ``live.js`` is added only on a plan frozen with receipts.
    """
    body = _header(plan, plan_name) + _summary(plan)
    body += _section("Decisions", [_decision(d) for d in plan.decisions], tag=None)
    body += _values(plan) + _formats(plan) + _sweeps(plan) + ["<h2>Tasks</h2>"]
    for item in plan.items:
        body += _item(plan, item)
    body += _evolution()
    script = [_script(plan)] if plan_receipts.uses_receipts(plan) else []
    return "\n".join(["<!DOCTYPE html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
                      f"<title>{_e(_title(plan, plan_name))}</title>", f"<style>\n{_style()}</style>",
                      "</head>", "<body>", *body, *script, "</body>", "</html>"]) + "\n"


def _keeps_markdown(plan_file: Path, plan: ActionPlan) -> bool:
    """A plan not frozen yet whose ``documentation`` names its markdown PIP: that PIP stays the one written
    until the first freeze moves ``documentation`` to the HTML page."""
    doc = plan.documentation
    return plan.frozen is None and doc is not None and Path(doc).name == pip_path(plan_file).name


def write_pip(plan_file: Path, plan: ActionPlan) -> Path:
    """Write the PIP beside ``plan_file``; the path written.

    The HTML page when ``uses_html``, plus ``live.js`` once the plan is frozen with receipts; else the
    markdown PIP, which a plan not frozen yet whose ``documentation`` names it also keeps.
    """
    if not uses_html(plan) or _keeps_markdown(plan_file, plan):
        target = pip_path(plan_file)
        target.write_text(render_pip(plan, plan_file.name), encoding="utf-8")
        return target
    target = pip_html_path(plan_file)
    target.write_text(render_pip_html(plan, plan_file.name), encoding="utf-8")
    if plan_receipts.uses_receipts(plan):
        plan_live.write_live(plan_file.parent, plan.plan_id)
    return target


def refresh_pip(plan_file: Path, plan: ActionPlan) -> Path:
    """What ``plan.py render`` writes; the PIP's path.

    On a frozen receipts plan ``live.js`` is rebuilt and the page is written only when it is missing:
    ``freeze``, ``freeze --refreeze`` and ``plan_api.write`` (both through ``write_pip``) stay the writers
    of an existing page. Otherwise ``write_pip``.
    """
    page = pip_html_path(plan_file)
    if plan_receipts.uses_receipts(plan) and page.exists():
        plan_live.write_live(plan_file.parent, plan.plan_id)
        return page
    return write_pip(plan_file, plan)
