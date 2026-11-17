"""TODO snapshot page: ``snapshot_html.render_page`` draws the catalog as one themed HTML page.

The page opens with the T2 header line, carries a Summary block of catalog counts above the top-N table and,
folded closed below it, a table of the remaining items; both keep the
Rank / Id / Item / Status / Kind / Blast / LoE / Score / GH columns, fold each item's prose into a
``<details>`` in its Item cell, and inlines the shared theme, its own CSS and a loader that reloads the page
when the ``todo_live.js`` stamp beside it changes.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Sequence

import pytest

from harness_lib.todo_sync import snapshot_html as sh
from harness_lib.todo_sync.report import snapshot_header
from harness_lib.todo_sync.sources import parse_header, ranked_items, top_items

SHA = "0" * 64
SOURCE = "docs/TODO/RepoToDo.json"
DAY = "2026-11-17"
IDS = ("todo-k7qf", "todo-m3x9", "todo-p4rs")
ALPHA = "../../Alpha/_IMPL_TODO.md"
BETA = "../../Beta/_IMPL_TODO.md"
# The loader reloads only when the live stamp is set and differs from the page's own stamp.
LIVE_GUARD = re.compile(
    r"var (\w+) = window\.TODO_LIVE;\s*"
    r"if \(\s*\1 && \1\.stamp && \1\.stamp !== TODO_PAGE\.stamp\s*\)\s*\{\s*reloadFor\(\1\.stamp\);\s*\}")
# One reload per live stamp: a stamp already reloaded for returns before ``location.reload``.
RELOAD_ONCE = re.compile(
    r"function reloadFor\((\w+)\) \{.*?getItem\(KEY\) === \1\) \{ return; \}.*?location\.reload\(\);",
    re.DOTALL)
NODE = shutil.which("node")
# Runs todo.js with stubbed browser globals: each fed stamp is one todo_live.js load (null leaves TODO_LIVE
# unset), and the output is the running reload count after each load.
LOADER_HARNESS = r"""
const data = JSON.parse(require("fs").readFileSync(0, "utf8"));
const store = {};
const tags = [];
let reloads = 0;
let tick = null;
const document = {head: {appendChild(tag) { tags.push(tag); }},
                  getElementById() { return null; }, createElement() { return {}; }};
const window = {
  location: {pathname: "/TODO_Snapshot.html", reload() { reloads += 1; }},
  sessionStorage: {getItem(k) { return k in store ? store[k] : null; },
                   setItem(k, v) { store[k] = String(v); }},
  setInterval(fn) { tick = fn; },
};
const page = {src: "todo_live.js?t=", stamp: data.page, reloadMs: 1000};
new Function("window", "document", "TODO_PAGE", data.source)(window, document, page);
const counts = data.stamps.map((stamp, i) => {
  if (i > 0) { tick(); }
  window.TODO_LIVE = stamp === null ? undefined : {stamp: stamp};
  tags[tags.length - 1].onload();
  return reloads;
});
process.stdout.write(JSON.stringify(counts));
"""


def _item(ident: Any, rank: int, **extra: Any) -> Dict[str, Any]:
    item = {"id": ident, "rank": rank, "title": f"Title {rank}", "kind": "bug", "status": "OPEN",
            "blast_radius": {"level": "S"}, "loe": {"size": "M"}, "priority": {"score": 2.7577},
            "gh_issues": [], "sources": []}
    item.update(extra)
    return item


def _items() -> List[Dict[str, Any]]:
    return [_item(ident, n) for n, ident in enumerate(IDS, 1)]


def _page(items: Sequence[Dict[str, Any]], links: Sequence[Sequence[str]] = (), gh_repo: Optional[str] = None,
          top_n: int = 10, repo: Optional[str] = None, rest: Sequence[Dict[str, Any]] = (),
          rest_links: Sequence[Sequence[str]] = (), **catalog_extra: Any) -> str:
    catalog = {"items": list(items), "trackers": [], "close_candidates": [], **catalog_extra}
    page = sh.SnapshotPage(header=snapshot_header(SOURCE, top_n, SHA, DAY), catalog=catalog,
                           top=list(items)[:top_n], top_n=top_n, rendered=DAY, source=SOURCE, links=links,
                           gh_repo=gh_repo, repo=repo, rest=rest, rest_links=rest_links)
    return sh.render_page(page)


def _two(top_n: int = 1, **kwargs: Any) -> str:
    """The three helper items split after ``top_n``: the rest goes to the second table."""
    items = _items()
    return _page(items, top_n=top_n, rest=items[top_n:], **kwargs)


def _rows(text: str) -> List[str]:
    return re.findall(r'<tr class="row".*?</tr>', text, re.S)


def _table_html(text: str, cls: str) -> str:
    """The ``<table class="items <cls>">`` element of the page, or empty when it has none."""
    found = re.search(rf'<table class="items {cls}">.*?</table>', text, re.S)
    return found.group(0) if found else ""


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


def _cells(row: str) -> List[str]:
    return re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)


def _script_config(text: str) -> Dict[str, Any]:
    """The loader config of the trailing script: the last ``var TODO_PAGE = {...};`` match, after the body."""
    return json.loads(re.findall(r"var TODO_PAGE = (\{.*?\});", text)[-1])


def test_first_line_is_the_t2_header_then_the_doctype() -> None:
    lines = _page(_items()).splitlines()
    header = parse_header(lines[0])
    assert header is not None and (header.source, header.top, header.rendered) == (SOURCE, 10, DAY)
    assert lines[1] == "<!DOCTYPE html>"


def test_title_and_heading_name_the_snapshot_without_a_row_count() -> None:
    text = _page(_items())
    assert f"<title>TODO Snapshot ({DAY})</title>" in text
    assert "<h1>TODO Snapshot</h1>" in text


def test_the_render_date_sits_right_under_the_heading() -> None:
    after = _page(_items()).split("</h1>", 1)[1].lstrip()
    assert after.startswith(f'<p class="rendered">Rendered {DAY}</p>')


def test_the_render_info_is_its_own_block_under_a_small_heading() -> None:
    text = _page(_items())
    block = re.search(r'<section id="render-info">(.*?)</section>', text, re.S)
    assert block, "no render-info section"
    assert block.group(1).startswith("<h5>Render info</h5>")
    info = _text(block.group(1))
    assert SOURCE in info and "todo_live.js" in info and "overwritten" in info and DAY not in info
    assert text.index('class="rendered"') < text.index('id="render-info"') < text.index('id="summary"')


def test_the_render_info_puts_writers_and_non_writers_on_their_own_lines() -> None:
    block = re.search(r'<section id="render-info">(.*?)</section>', _page(_items()), re.S).group(1)
    lines = [_text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", block, re.S)]
    assert ";" not in "".join(lines)
    writes = [ln for ln in lines if ln.startswith("Rewritten by")]
    keeps = [ln for ln in lines if ln.startswith("Not rewritten by")]
    assert len(writes) == 1 and "todo_sync.py render" in writes[0] and "add --inbox" in writes[0]
    assert len(keeps) == 1 and "add --spec" in keeps[0] and "migrate-ids" in keeps[0]


def test_title_and_heading_open_with_the_repo_name() -> None:
    text = _page(_items(), repo="widgets")
    assert f"<title>widgets | TODO Snapshot ({DAY})</title>" in text
    assert '<h1><span class="repo">widgets</span>TODO Snapshot</h1>' in text


def test_the_header_block_rules() -> None:
    css = (sh.PAGES / "styles" / "todo.css").read_text(encoding="utf-8")
    assert re.search(r"h1 \.repo\s*\{[^}]*display: block", css), "repo name not on its own line"
    assert re.search(r"\.rendered\s*\{[^}]*font-size", css)
    assert re.search(r"#render-info h5\s*\{[^}]*font-size", css)


def test_the_repo_name_is_escaped() -> None:
    text = _page(_items(), repo="<w>")
    assert "<title>&lt;w&gt; | " in text and '<span class="repo">&lt;w&gt;</span>' in text


def test_the_table_keeps_its_columns() -> None:
    heads = re.findall(r"<th[^>]*>(.*?)</th>", _page(_items()))
    assert heads == ["Rank", "Id", "Item", "Status", "Kind", "Blast", "LoE", "Score", "GH"]


def test_the_top_table_sits_under_its_own_heading() -> None:
    assert '<h2>Top 3</h2>\n<table class="items top">' in _page(_items())
    assert '<h2>Top 1</h2>\n<table class="items top">' in _two()


def test_the_rest_table_draws_the_remaining_items_in_rank_order_folded_closed() -> None:
    text = _two()
    assert re.findall(r'data-rank="(\d+)"', _table_html(text, "top")) == ["1"]
    rest = _table_html(text, "rest")
    assert re.findall(r'data-rank="(\d+)"', rest) == ["2", "3"]
    assert re.findall(r"<th[^>]*>(.*?)</th>", rest) == list(sh.COLUMNS)
    assert ('<details id="rest"><summary><h2>Remaining 2 items</h2></summary>\n<table class="items rest">'
            in text)
    assert text.index('class="items top"') < text.index('id="rest"')


def test_one_remaining_item_is_named_in_the_singular() -> None:
    assert "<h2>Remaining 1 item</h2>" in _two(top_n=2)


def test_rest_rows_link_their_stubs_by_position() -> None:
    text = _two(links=[[ALPHA]], rest_links=[[], [BETA]])
    rows = _rows(_table_html(text, "rest"))
    assert '<a class="stub"' not in rows[0]
    assert f'<a class="stub" href="{BETA}">1</a>' in rows[1]
    assert f'<a class="stub" href="{ALPHA}">1</a>' in _table_html(text, "top")


def test_no_remaining_items_draws_no_second_table() -> None:
    text = _page(_items())
    assert 'id="rest"' not in text and 'class="items rest"' not in text


def test_ranked_items_put_items_without_an_int_rank_last() -> None:
    items = [{**_item("todo-c", 9), "rank": None}, _item("todo-b", 2), _item("todo-a", 1)]
    assert [i["id"] for i in ranked_items(items)] == ["todo-a", "todo-b", "todo-c"]
    assert top_items(items, 2) == ranked_items(items)[:2]


def test_one_row_per_top_item_in_rank_order() -> None:
    rows = _rows(_page(_items(), top_n=2))
    assert len(rows) == 2
    assert [_text(_cells(r)[0]) for r in rows] == ["1", "2"]
    assert IDS[0] in rows[0] and IDS[1] in rows[1]


def test_cells_carry_badges_sizes_and_score() -> None:
    [row] = _rows(_page([_item(IDS[0], 1, status="NEEDS_DECISION", kind="feature")]))
    cells = _cells(row)
    assert len(cells) == 9
    assert 'data-status="NEEDS_DECISION"' in cells[3] and _text(cells[3]) == "NEEDS_DECISION"
    assert 'data-kind="feature"' in cells[4] and _text(cells[4]) == "feature"
    assert [_text(c) for c in cells[5:8]] == ["S", "M", "2.76"]


def test_text_is_escaped() -> None:
    [row] = _rows(_page([_item(IDS[0], 1, title='<b>&"x"</b>')]))
    assert "&lt;b&gt;&amp;&quot;x&quot;&lt;/b&gt;" in row
    assert "<b>" not in row


def test_attribute_values_are_escaped() -> None:
    [row] = _rows(_page([_item(IDS[0], 1, status='" onclick="x')]))
    assert 'data-status="&quot; onclick=&quot;x"' in row
    assert ' onclick="x"' not in row


def test_code_spans_become_code_elements() -> None:
    [row] = _rows(_page([_item(IDS[0], 1, title="Split `load()` and ``a`b<c>``")]))
    assert "<code>load()</code>" in row
    assert "<code>a`b&lt;c&gt;</code>" in row
    assert "`load()`" not in row


def test_id_cell_holds_the_bare_id_for_copying() -> None:
    rows = _rows(_page(_items()[:2], links=[[ALPHA, BETA], []]))
    for row, ident in zip(rows, IDS):
        assert re.search(r'<td class="c-id"><span class="id">([^<]*)</span></td>', row).group(1) == ident
        assert "<a" not in _cells(row)[1]
        assert ident not in _text(_cells(row)[2])


def test_stub_links_follow_the_title_numbered_from_one() -> None:
    rows = _rows(_page(_items()[:2], links=[[ALPHA, BETA], []]))
    item_cell = _cells(rows[0])[2]
    assert f'<a class="stub" href="{ALPHA}">1</a>' in item_cell
    assert f'<a class="stub" href="{BETA}">2</a>' in item_cell
    assert item_cell.index("Title 1") < item_cell.index(ALPHA)
    assert '<a class="stub"' not in rows[1]


def test_links_follow_row_position_not_id() -> None:
    items = [_item(IDS[0], 1), _item(IDS[0], 2)]
    rows = _rows(_page(items, links=[[ALPHA], [BETA]]))
    assert f'href="{ALPHA}"' in rows[0] and BETA not in rows[0]
    assert f'href="{BETA}"' in rows[1] and ALPHA not in rows[1]


def _gh(item: Dict[str, Any], gh_repo: Optional[str] = None) -> str:
    [row] = _rows(_page([item], gh_repo=gh_repo))
    return _cells(row)[8]


def test_gh_issue_links_to_its_source_url() -> None:
    url = "https://github.com/o/r/issues/133"
    item = _item(IDS[0], 1, gh_issues=[133], sources=[{"type": "gh_issue", "ref": "#133", "url": url}])
    assert f'<a href="{url}">#133</a>' in _gh(item)


def test_gh_issue_without_a_source_url_uses_the_configured_repo() -> None:
    item = _item(IDS[0], 1, gh_issues=[7])
    assert '<a href="https://github.com/o/r/issues/7">#7</a>' in _gh(item, gh_repo="o/r")
    plain = _gh(item)
    assert "<a " not in plain and _text(plain) == "#7"


def test_gh_issue_source_url_must_be_https() -> None:
    item = _item(IDS[0], 1, gh_issues=[7],
                 sources=[{"type": "gh_issue", "ref": "#7", "url": "javascript:alert(1)"}])
    plain = _gh(item)
    assert "javascript:" not in plain and "<a " not in plain


def test_gh_cell_falls_back_to_tracker_related_then_none() -> None:
    assert _text(_gh(_item(IDS[0], 1, tracker=101))) == "tracker #101"
    assert _text(_gh(_item(IDS[0], 1, related_gh_issues=[5, 6]))) == "related #5, #6"
    assert _text(_gh(_item(IDS[0], 1))) == "none"


def test_details_carry_summary_proposal_decision_and_ranking() -> None:
    item = _item(IDS[0], 1, status="NEEDS_DECISION", summary="Summary text", proposed_change="Proposal text",
                 decision_question="Which one?", why_ranked="Ranked text")
    [row] = _rows(_page([item]))
    item_cell = _cells(row)[2]
    assert "<details" in item_cell and "<summary" in item_cell
    for text in ("Summary text", "Proposal text", "Which one?", "Ranked text"):
        assert text in item_cell


def test_malformed_fields_render_without_raising() -> None:
    item = {"id": [IDS[0]], "rank": "x", "title": None, "kind": 5, "status": None, "priority": "x",
            "blast_radius": 5, "loe": None, "gh_issues": "x", "sources": 5, "summary": 5, "tracker": "t"}
    rows = _rows(_page([item], links=[[ALPHA]]))
    assert len(rows) == 1
    assert f'href="{ALPHA}">1</a>' in rows[0]
    assert '<span class="id">' in rows[0] and '<td class="c-rank">x</td>' in rows[0]
    assert "[&#x27;todo-k7qf&#x27;]" in rows[0]


def test_summary_block_counts_the_whole_catalog_above_the_table() -> None:
    statuses = ["OPEN", "OPEN", "OPEN", "NEEDS_DECISION", "NEEDS_DECISION"]
    kinds = ["bug", "bug", "feature", "feature", "feature"]
    items = [_item(f"todo-{n}aaa", n, status=s, kind=k) for n, (s, k) in enumerate(zip(statuses, kinds), 1)]
    text = _page(items, top_n=2, trackers=[{"number": 1}], close_candidates=[{"number": 2}, {"number": 3}])
    assert text.index('id="summary"') < text.index("<table")
    summary = _text(re.search(r'<section id="summary">(.*?)</section>', text, re.S).group(1))
    for part in ("Items 5", "OPEN 3", "NEEDS_DECISION 2", "feature 3", "bug 2", "Trackers 1",
                 "Close candidates 2"):
        assert part in summary, summary


def test_an_empty_catalog_draws_a_note_and_no_rows() -> None:
    text = _page([])
    assert _rows(text) == []
    assert "No items" in _text(text)


def test_theme_and_loader_are_inlined_with_no_network_address() -> None:
    text = _page(_items())
    for folder, name in (("styles", "shared.css"), ("styles", "todo.css"), ("components", "todo.js")):
        assert (sh.PAGES / folder / name).read_text(encoding="utf-8").strip() in text
    loads = re.sub(r'<a [^>]*href="https://[^"]*"', "", text)
    for needle in ("<link", "http://", "https://", "@import", "url("):
        assert needle not in loads
    config = _script_config(text)
    assert config == {"src": f"{sh.LIVE_NAME}?t=", "reloadMs": sh.RELOAD_MS, "stamp": sh.page_stamp(text)}


def test_stamp_is_stable_and_follows_the_content() -> None:
    first, again = sh.page_stamp(_page(_items())), sh.page_stamp(_page(_items()))
    assert first is not None and re.fullmatch(r"[0-9a-f]{64}", first)
    assert first == again
    changed = _items()
    changed[0]["title"] = "Another title"
    assert sh.page_stamp(_page(changed)) != first
    assert sh.page_stamp("<html></html>") is None


def test_stamp_is_read_from_the_trailing_script_not_the_body() -> None:
    item = _item(IDS[0], 1, title="Rename var TODO_PAGE = {}; in the loader",
                 summary='reads `var TODO_PAGE = {"stamp": "abc"};` at load')
    text = _page([item])
    stamp = sh.page_stamp(text)
    assert stamp is not None and re.fullmatch(r"[0-9a-f]{64}", stamp)
    assert stamp == _script_config(text)["stamp"]


def test_live_script_carries_the_stamp_and_date() -> None:
    text = sh.live_script("a" * 64, DAY)
    assert text.startswith(sh.LIVE_HEAD) and text.endswith(";\n")
    assert json.loads(text[len(sh.LIVE_HEAD):-2]) == {"stamp": "a" * 64, "rendered": DAY}


def _without_comments(js: str) -> str:
    """``js`` with its ``//`` and ``/* */`` comments removed (todo.js holds no ``//`` inside a string)."""
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", js, flags=re.S)


def test_the_loader_reloads_only_on_a_new_stamp() -> None:
    """Source-level fallback for the node-run case: the checks read code only, never comments."""
    loader = _without_comments((sh.PAGES / "components" / "todo.js").read_text(encoding="utf-8"))
    for needle in ("TODO_LIVE", "TODO_PAGE.stamp", "location.reload", "setInterval", "TODO_PAGE.src"):
        assert needle in loader
    assert LIVE_GUARD.search(loader), "reload is not guarded by a new, non-empty live stamp"
    assert RELOAD_ONCE.search(loader), "reloadFor does not skip a stamp it already reloaded for"
    assert loader.count("location.reload") == 1, "location.reload is reachable outside reloadFor"
    assert loader.count("reloadFor(") == 2, "reloadFor is called outside the stamp guard"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_loader_reloads_once_per_new_stamp_when_run() -> None:
    """Equal or missing stamp: no reload; a new stamp: one reload; the same stamp again: none."""
    source = (sh.PAGES / "components" / "todo.js").read_text(encoding="utf-8")
    feed = json.dumps({"source": source, "page": "a", "stamps": ["a", None, "b", "b", "c", "c"]})
    done = subprocess.run([NODE, "-e", LOADER_HARNESS], input=feed, capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [0, 0, 1, 1, 2, 2]


def test_status_and_kind_badges_have_theme_rules() -> None:
    css = (sh.PAGES / "styles" / "todo.css").read_text(encoding="utf-8")
    assert '[data-status="NEEDS_DECISION"]' in css and '[data-status="OPEN"]' in css
    assert ".kind" in css and "details" in css
    assert re.search(r"td\.c-id[^{]*\{[^}]*user-select: all", css)
