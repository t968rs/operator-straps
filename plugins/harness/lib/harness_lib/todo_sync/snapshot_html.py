"""The TODO snapshot page: one self-contained HTML page of the catalog's items, top N first.

``render_snapshot`` writes the page as ``TODO_Snapshot.html`` in ``todo.snapshots.dir``, and
``todo_live.js`` beside it, from ``todo_sync.py render``, ``init``, ``add --inbox`` and ``lease release``; a
bare ``add --spec``, ``retire``, ``split``, ``refresh`` or ``migrate-ids`` leaves the page for the next
render. A render that would draw the same page keeps the page and rewrites ``todo_live.js`` only when it is
missing or differs. Rule T2 flags a stale page only when
todo.top_n or the top-N ids, ranks, statuses or titles changed; the Summary counts, the other cells, the
folded prose and the remaining-items table can go stale with no finding. Line 1 of the page is the
``<!-- todo-snapshot ... -->`` header rule T2 reads back; then come a Summary block of catalog counts, the
top-N table and, folded closed below it, a second table of the remaining items in rank order. Both tables
share the columns (Rank, Id, Item, Status, Kind, Blast, LoE, Score, GH): the Id cell holds the bare id for
copying, and the Item cell links the item's stubs after its title and folds its prose into a
``<details>``. The CSS (``pages/styles/shared.css``, ``pages/styles/todo.css``), the theme toggle
(``pages/components/theme.js``) and the loader (``pages/components/todo.js``) are read from the plugin root
and inlined, so the page loads no network address: no ``<link>``, ``@import``, ``url()`` or remote script. Its
only https addresses are link targets (the brand and the usage document).

The page carries a stamp, the sha256 of the page rendered with an empty stamp, and ``todo_live.js`` sets
``window.TODO_LIVE`` to that stamp and the render date. The loader re-adds the sidecar every ``RELOAD_MS``
and reloads the page when the stamp it reads differs from its own, at most once per stamp (a page that still
disagrees after that reload waits for the next render), so an open page follows each render.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from harness_lib.page_chrome import HOME, PAGES, corner, theme_script

PAGE_NAME = "TODO_Snapshot.html"
LIVE_NAME = "todo_live.js"
LIVE_HEAD = "window.TODO_LIVE = "
RELOAD_MS = 3000
#: The GitHub copy of the driver's usage document; a link into the installed plugin would not resolve from a
#: consuming project's page.
USAGE = f"{HOME}/blob/main/plugins/harness/scripts/todo_sync.md"
COLUMNS = ("Rank", "Id", "Item", "Status", "Kind", "Blast", "LoE", "Score", "GH")
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)", re.S)
_CONFIG = re.compile(r"<script>\nvar TODO_PAGE = (\{.*?\});")
_STAMP = re.compile(r"[0-9a-f]{64}")
#: Item prose folded into the Item cell, in order: catalog key and its label (None: no label).
_PROSE: Tuple[Tuple[str, Optional[str]], ...] = (
    ("summary", None), ("proposed_change", "Proposed"), ("decision_question", "Decision"),
    ("why_ranked", "Ranked"),
)


@dataclass(frozen=True)
class SnapshotPage:
    """What one page draws: the T2 header line, the catalog, its top rows, the remaining rows and their stub
    link targets.

    ``links[k]`` holds the stub link targets of ``top[k]`` and ``rest_links[k]`` those of ``rest[k]`` (by
    position, so rows sharing an id never share links); ``rest`` is drawn as a second, folded table when it
    has rows. ``gh_repo`` (``owner/name``) builds an issue link when the item names no issue URL; ``repo``,
    the repository name, opens the title and the heading when set.
    """

    header: str
    catalog: Dict[str, Any]
    top: Sequence[Dict[str, Any]]
    top_n: int
    rendered: str
    source: str
    links: Sequence[Sequence[str]] = ()
    gh_repo: Optional[str] = None
    repo: Optional[str] = None
    rest: Sequence[Dict[str, Any]] = ()
    rest_links: Sequence[Sequence[str]] = ()


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def inline(value: Any) -> str:
    """``value`` as escaped HTML whose backtick code spans become ``<code>`` elements."""
    text = "" if value is None else str(value)
    out: List[str] = []
    pos = 0
    for span in _CODE_SPAN.finditer(text):
        fence = len(span.group(1))
        inner = span.group(0)[fence:-fence]
        if len(inner) > 2 and inner.startswith(" ") and inner.endswith(" "):
            inner = inner[1:-1]
        out += [_e(text[pos:span.start()]), f"<code>{_e(inner)}</code>"]
        pos = span.end()
    out.append(_e(text[pos:]))
    return "".join(out)


def _asset(folder: str, name: str) -> str:
    """The text of ``pages/<folder>/<name>``, read when called."""
    return (PAGES / folder / name).read_text(encoding="utf-8")


def _badge(kind: str, value: Any) -> str:
    """A pill naming ``value`` with ``data-<kind>`` set for the theme; empty for no value."""
    text = "" if value is None else str(value)
    return f'<span class="badge {kind}" data-{kind}="{_e(text)}">{_e(text)}</span>' if text else ""


def _sub(item: Dict[str, Any], key: str, field: str) -> Any:
    block = item.get(key)
    return block.get(field) if isinstance(block, dict) else None


def _numbers(value: Any) -> List[int]:
    if not isinstance(value, list):
        return []
    return [n for n in value if isinstance(n, int) and not isinstance(n, bool)]


def _issue_url(item: Dict[str, Any], number: int, repo: Optional[str]) -> Optional[str]:
    """The URL of the item's ``gh_issue`` source for ``#number``, else one built from ``repo``, else None."""
    sources = item.get("sources")
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict) or source.get("type") != "gh_issue":
            continue
        if source.get("ref") == f"#{number}":
            url = source.get("url")
            if isinstance(url, str) and url.startswith("https://"):
                return url
    return f"https://github.com/{repo}/issues/{number}" if repo else None


def _issue(item: Dict[str, Any], number: int, repo: Optional[str]) -> str:
    url = _issue_url(item, number, repo)
    return f'<a href="{_e(url)}">#{number}</a>' if url else f"#{number}"


def gh_html(item: Dict[str, Any], repo: Optional[str] = None) -> str:
    """Direct issues, else the tracker, else related issues, else ``none``; issue numbers link when known."""
    issues = _numbers(item.get("gh_issues"))
    if issues:
        return ", ".join(_issue(item, n, repo) for n in issues)
    tracker = item.get("tracker")
    if isinstance(tracker, int) and not isinstance(tracker, bool):
        return f"tracker {_issue(item, tracker, repo)}"
    related = _numbers(item.get("related_gh_issues"))
    if related:
        return "related " + ", ".join(_issue(item, n, repo) for n in related)
    return '<span class="none">none</span>'


def _prose(item: Dict[str, Any]) -> str:
    parts = []
    for key, label in _PROSE:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            head = f"<strong>{label}:</strong> " if label else ""
            parts.append(f'<p class="{key}">{head}{inline(value)}</p>')
    return "".join(parts)


def _id_cell(item: Dict[str, Any]) -> str:
    """The bare id, unlinked, so one click selects it whole for copying."""
    return f'<td class="c-id"><span class="id">{_e(item.get("id"))}</span></td>'


def _item_cell(item: Dict[str, Any], targets: Sequence[str]) -> str:
    """The title and its stub links numbered from 1, with the prose folded below."""
    head = inline(item.get("title"))
    head += "".join(f' <a class="stub" href="{_e(t)}">{n}</a>' for n, t in enumerate(targets, 1))
    prose = _prose(item)
    if not prose:
        return f'<td class="c-item">{head}</td>'
    return f'<td class="c-item"><details><summary>{head}</summary>{prose}</details></td>'


def _row(item: Dict[str, Any], targets: Sequence[str], repo: Optional[str]) -> str:
    score = _sub(item, "priority", "score")
    rank = _e(item.get("rank"))
    cells = [f'<td class="c-rank">{rank}</td>', _id_cell(item), _item_cell(item, targets),
             f'<td class="c-status">{_badge("status", item.get("status"))}</td>',
             f'<td class="c-kind">{_badge("kind", item.get("kind"))}</td>',
             f'<td class="c-size">{_e(_sub(item, "blast_radius", "level"))}</td>',
             f'<td class="c-size">{_e(_sub(item, "loe", "size"))}</td>',
             f'<td class="c-score">{f"{score:.2f}" if _number(score) else ""}</td>',
             f'<td class="c-gh">{gh_html(item, repo)}</td>']
    return f'<tr class="row" data-rank="{rank}">{"".join(cells)}</tr>'


def _table(cls: str, items: Sequence[Dict[str, Any]], links: Sequence[Sequence[str]],
           repo: Optional[str]) -> List[str]:
    """One ``<table class="items <cls>">`` of ``items``, row ``k`` linking the stubs of ``links[k]``."""
    links = list(links)
    head = "".join(f"<th>{name}</th>" for name in COLUMNS)
    rows = [_row(item, links[k] if k < len(links) else (), repo) for k, item in enumerate(items)]
    return [f'<table class="items {cls}">', f'<tr class="head">{head}</tr>', *rows, "</table>"]


def _tables(page: SnapshotPage) -> List[str]:
    """The top table under its heading when it has rows, then the remaining items folded closed below it; a
    note when neither list has rows."""
    if not page.top and not page.rest:
        return ['<p class="note">No items in the catalog.</p>']
    out: List[str] = []
    if page.top:
        out += [f"<h2>Top {len(page.top)}</h2>", *_table("top", page.top, page.links, page.gh_repo)]
    if page.rest:
        count = len(page.rest)
        label = f"Remaining {count} item{'' if count == 1 else 's'}"
        out += [f'<details id="rest"><summary><h2>{label}</h2></summary>',
                *_table("rest", page.rest, page.rest_links, page.gh_repo), "</details>"]
    return out


def _counted(values: Iterable[Any], kind: str) -> str:
    """One badge and count per distinct value, most frequent first, then by name; ``none`` without values."""
    counts = Counter(str(v) for v in values if v is not None and str(v))
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    parts = [f'<span class="count">{_badge(kind, name)} {n}</span>' for name, n in ordered]
    return " ".join(parts) or '<span class="none">none</span>'


def _summary(catalog: Dict[str, Any]) -> str:
    """The Summary block: item, status and kind counts, trackers and close candidates."""
    raw = catalog.get("items")
    items = [i for i in raw if isinstance(i, dict)] if isinstance(raw, list) else []

    def size(key: str) -> int:
        value = catalog.get(key)
        return len(value) if isinstance(value, list) else 0

    rows = [("Items", str(len(items))), ("Status", _counted((i.get("status") for i in items), "status")),
            ("Kind", _counted((i.get("kind") for i in items), "kind")),
            ("Trackers", str(size("trackers"))), ("Close candidates", str(size("close_candidates")))]
    cells = "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in rows)
    return f'<section id="summary"><h2>Summary</h2><dl class="summary">{cells}</dl></section>'


def _intro(page: SnapshotPage) -> List[str]:
    writers = ", ".join(f"<code>{w}</code>" for w in ("render", "init", "add --inbox", "lease release"))
    bare = ", ".join(f"<code>{w}</code>" for w in ("add --spec", "retire", "split", "refresh", "migrate-ids"))
    repo = f'<span class="repo">{_e(page.repo)}</span>' if page.repo else ""
    return [f"<h1>{repo}TODO Snapshot</h1>",
            f'<p class="rendered">Rendered {_e(page.rendered)}</p>',
            '<section id="render-info"><h5>Render info</h5>',
            f'<p class="note">Drawn from <code>{_e(page.source)}</code>. Edits to this file are '
            "overwritten.</p>",
            f'<p class="note">Rewritten by <a href="{USAGE}"><code>todo_sync.py</code></a> {writers}.</p>',
            f'<p class="note">Not rewritten by <code>todo_sync.py</code> {bare}: the page waits for the '
            "next render.</p>",
            f'<p class="note">An open page reloads itself when <code>{LIVE_NAME}</code> beside it '
            "changes.</p></section>"]


def _script(stamp: str) -> str:
    config = {"src": f"{LIVE_NAME}?t=", "reloadMs": RELOAD_MS, "stamp": stamp}
    text = json.dumps(config, sort_keys=True).replace("<", "\\u003c")
    return f"<script>\nvar TODO_PAGE = {text};\n{_asset('components', 'todo.js')}</script>"


def _document(page: SnapshotPage, stamp: str) -> str:
    body = [*_intro(page), _summary(page.catalog), *_tables(page)]
    style = _asset("styles", "shared.css") + _asset("styles", "todo.css")
    title = f"TODO Snapshot ({page.rendered})"
    if page.repo:
        title = f"{page.repo} | {title}"
    return "\n".join([page.header, "<!DOCTYPE html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
                      f"<title>{_e(title)}</title>", f"<style>\n{style}</style>", theme_script(), "</head>",
                      "<body>", corner(), *body,
                      _script(stamp), "</body>", "</html>"]) + "\n"


def render_page(page: SnapshotPage) -> str:
    """The whole page, stamped with the sha256 of the page rendered with an empty stamp."""
    stamp = hashlib.sha256(_document(page, "").encode("utf-8")).hexdigest()
    return _document(page, stamp)


def page_stamp(text: str) -> Optional[str]:
    """The stamp a rendered page carries, or None when ``text`` holds none."""
    match = _CONFIG.search(text)
    if not match:
        return None
    try:
        stamp = json.loads(match.group(1)).get("stamp")
    except (json.JSONDecodeError, AttributeError):
        return None
    return stamp if isinstance(stamp, str) and _STAMP.fullmatch(stamp) else None


def live_script(stamp: str, rendered: str) -> str:
    """The text of ``todo_live.js``: ``window.TODO_LIVE = {"stamp": ..., "rendered": ...};``."""
    return f"{LIVE_HEAD}{json.dumps({'stamp': stamp, 'rendered': rendered})};\n"
