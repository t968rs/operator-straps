"""TODO snapshot page: ``snapshot_html.render_page`` draws the catalog's top-N table as one themed HTML page.

The page opens with the T2 header line, carries a Summary block of catalog counts above the table, keeps the
Rank / Item / Status / Kind / Blast / LoE / Score / GH columns, folds each item's prose into a ``<details>``
in its Item cell, and inlines the shared theme, its own CSS and a loader that reloads the page when the
``todo_live.js`` stamp beside it changes.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from harness_lib.todo_sync import snapshot_html as sh
from harness_lib.todo_sync.report import snapshot_header
from harness_lib.todo_sync.sources import parse_header

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


def _item(ident: Any, rank: int, **extra: Any) -> Dict[str, Any]:
    item = {"id": ident, "rank": rank, "title": f"Title {rank}", "kind": "bug", "status": "OPEN",
            "blast_radius": {"level": "S"}, "loe": {"size": "M"}, "priority": {"score": 2.7577},
            "gh_issues": [], "sources": []}
    item.update(extra)
    return item


def _items() -> List[Dict[str, Any]]:
    return [_item(ident, n) for n, ident in enumerate(IDS, 1)]


def _page(items: Sequence[Dict[str, Any]], links: Sequence[Sequence[str]] = (), gh_repo: Optional[str] = None,
          top_n: int = 10, **catalog_extra: Any) -> str:
    catalog = {"items": list(items), "trackers": [], "close_candidates": [], **catalog_extra}
    page = sh.SnapshotPage(header=snapshot_header(SOURCE, top_n, SHA, DAY), catalog=catalog,
                           top=list(items)[:top_n], top_n=top_n, rendered=DAY, source=SOURCE, links=links,
                           gh_repo=gh_repo)
    return sh.render_page(page)


def _rows(text: str) -> List[str]:
    return re.findall(r'<tr class="row".*?</tr>', text, re.S)


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


def test_title_names_top_n_and_the_render_date() -> None:
    text = _page(_items())
    assert f"<title>TODO Snapshot: Top 10 ({DAY})</title>" in text
    assert "<h1>TODO Snapshot: Top 10</h1>" in text
    assert DAY in _text(text.split("<h1>", 1)[1].split("<table", 1)[0])


def test_the_table_keeps_its_columns() -> None:
    heads = re.findall(r"<th[^>]*>(.*?)</th>", _page(_items()))
    assert heads == ["Rank", "Item", "Status", "Kind", "Blast", "LoE", "Score", "GH"]


def test_one_row_per_top_item_in_rank_order() -> None:
    rows = _rows(_page(_items(), top_n=2))
    assert len(rows) == 2
    assert [_text(_cells(r)[0]) for r in rows] == ["1", "2"]
    assert IDS[0] in rows[0] and IDS[1] in rows[1]


def test_cells_carry_badges_sizes_and_score() -> None:
    [row] = _rows(_page([_item(IDS[0], 1, status="NEEDS_DECISION", kind="feature")]))
    cells = _cells(row)
    assert len(cells) == 8
    assert 'data-status="NEEDS_DECISION"' in cells[2] and _text(cells[2]) == "NEEDS_DECISION"
    assert 'data-kind="feature"' in cells[3] and _text(cells[3]) == "feature"
    assert [_text(c) for c in cells[4:7]] == ["S", "M", "2.76"]


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


def test_stub_links_wrap_the_id_and_number_the_extras() -> None:
    rows = _rows(_page(_items()[:2], links=[[ALPHA, BETA], []]))
    assert f'<a class="id" href="{ALPHA}">{IDS[0]}</a>' in rows[0]
    assert f'href="{BETA}"' in rows[0] and ">2</a>" in rows[0]
    assert '<a class="id"' not in rows[1] and f'<span class="id">{IDS[1]}</span>' in rows[1]


def test_links_follow_row_position_not_id() -> None:
    items = [_item(IDS[0], 1), _item(IDS[0], 2)]
    rows = _rows(_page(items, links=[[ALPHA], [BETA]]))
    assert f'href="{ALPHA}"' in rows[0] and BETA not in rows[0]
    assert f'href="{BETA}"' in rows[1] and ALPHA not in rows[1]


def _gh(item: Dict[str, Any], gh_repo: Optional[str] = None) -> str:
    [row] = _rows(_page([item], gh_repo=gh_repo))
    return _cells(row)[7]


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
    item_cell = _cells(row)[1]
    assert "<details" in item_cell and "<summary" in item_cell
    for text in ("Summary text", "Proposal text", "Which one?", "Ranked text"):
        assert text in item_cell


def test_malformed_fields_render_without_raising() -> None:
    item = {"id": [IDS[0]], "rank": "x", "title": None, "kind": 5, "status": None, "priority": "x",
            "blast_radius": 5, "loe": None, "gh_issues": "x", "sources": 5, "summary": 5, "tracker": "t"}
    rows = _rows(_page([item], links=[[ALPHA]]))
    assert len(rows) == 1
    assert '<a class="id"' not in rows[0] and f'href="{ALPHA}"' not in rows[0]
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
    for needle in ("<link", "http://", "https://", "@import", "url("):
        assert needle not in text
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


def test_the_loader_reloads_only_on_a_new_stamp() -> None:
    loader = (sh.PAGES / "components" / "todo.js").read_text(encoding="utf-8")
    for needle in ("TODO_LIVE", "TODO_PAGE.stamp", "location.reload", "setInterval", "TODO_PAGE.src"):
        assert needle in loader
    assert LIVE_GUARD.search(loader), "reload is not guarded by a new, non-empty live stamp"
    assert RELOAD_ONCE.search(loader), "reloadFor does not skip a stamp it already reloaded for"
    assert loader.count("location.reload") == 1, "location.reload is reachable outside reloadFor"
    assert loader.count("reloadFor(") == 2, "reloadFor is called outside the stamp guard"


def test_status_and_kind_badges_have_theme_rules() -> None:
    css = (sh.PAGES / "styles" / "todo.css").read_text(encoding="utf-8")
    assert '[data-status="NEEDS_DECISION"]' in css and '[data-status="OPEN"]' in css
    assert ".kind" in css and "details" in css
