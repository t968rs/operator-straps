"""The TODO inbox: ``put`` validates drafted items and writes one file per item under
``<scratch_folder>/todo-inbox/``; ``drain`` adds every inbox file to the catalog in one write, oldest first,
renders the snapshot, runs the check, deletes the accepted files and keeps each rejected one with its reason.

Projects come from ``_todo_helpers`` (issues 11, 101, 102 and 103 are recorded in its catalog).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, SNAP_DIR, build  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, gh, inbox  # noqa: E402
from harness_lib.todo_sync.ranking import RankingError  # noqa: E402

WALK_ROOTS = ()
DAY = dt.date(2026, 11, 13)
URL = "https://github.com/example/widgets/issues/{n}"


def _item(issue: Optional[int] = 9, **over: Any) -> Dict[str, Any]:
    base = {"title": f"New problem {issue}", "kind": "bug", "summary": "The parser skips a row.",
            "proposed_change": "Read every row.", "impact": "silent_wrong_output", "severity": 5,
            "blast_radius": {"level": "S", "reasoning": "One module.", "consumers": []},
            "loe": {"size": "S", "reasoning": "Small."}, "why_ranked": "Computed from ranking_method."}
    if issue is not None:
        base.update(issue=issue, url=URL.format(n=issue))
    return {**base, **over}


def _spec(tmp_path: Path, items: List[Dict[str, Any]]) -> Path:
    path = tmp_path / "add.json"
    path.write_text(json.dumps({"items": items}), encoding="utf-8")
    return path


def _queue(cfg, name: str, items: List[Dict[str, Any]]) -> Path:
    """An inbox file as ``put`` leaves it, written straight to the folder."""
    folder = inbox.inbox_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps({"items": items}), encoding="utf-8")
    return path


def _catalog(cfg) -> Dict[str, Any]:
    return json.loads(cfg.path(CATALOG_REL).read_text(encoding="utf-8"))


def _names(cfg) -> List[str]:
    return sorted(p.name for p in inbox.inbox_dir(cfg).iterdir())


def test_the_inbox_sits_under_the_scratch_folder(make_project) -> None:
    cfg = build(make_project)
    assert inbox.inbox_dir(cfg) == cfg.path("docs/_scratch/todo-inbox")


def test_put_writes_one_file_per_item_and_leaves_the_catalog(make_project, tmp_path: Path) -> None:
    cfg = build(make_project)
    before = cfg.path(CATALOG_REL).read_bytes()
    result = inbox.put(cfg, _spec(tmp_path, [_item(9), _item(None, title="A local note")]))
    assert len(result.paths) == 2 and result.filed == ()
    assert cfg.path(CATALOG_REL).read_bytes() == before
    bodies = [json.loads(p.read_text(encoding="utf-8")) for p in result.paths]
    assert [len(b["items"]) for b in bodies] == [1, 1]
    assert {b["items"][0]["title"] for b in bodies} == {"New problem 9", "A local note"}
    assert all(p.parent == inbox.inbox_dir(cfg) and p.suffix == ".json" for p in result.paths)


def test_put_refuses_an_item_the_catalog_rejects_and_writes_nothing(make_project, tmp_path: Path) -> None:
    cfg = build(make_project)
    with pytest.raises(TodoSyncError, match="issue #11"):
        inbox.put(cfg, _spec(tmp_path, [_item(9), _item(11)]))
    assert not inbox.inbox_dir(cfg).exists() or _names(cfg) == []


def test_put_files_the_issue_first_and_stores_it(make_project, tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[List[str]] = []

    def run_gh(cwd: Path, args: List[str], stdin: Optional[str] = None) -> str:
        calls.append(list(args))
        return URL.format(n=42) + "\n"

    monkeypatch.setattr(gh, "run_gh", run_gh)
    cfg = build(make_project)
    result = inbox.put(cfg, _spec(tmp_path, [_item(None)]), file_issues=True)
    assert result.filed == ((42, URL.format(n=42)),)
    [body] = [json.loads(p.read_text(encoding="utf-8")) for p in result.paths]
    assert (body["items"][0]["issue"], body["items"][0]["url"]) == (42, URL.format(n=42))
    assert len(calls) == 1


def test_put_names_sort_in_spec_order_on_a_repeated_stamp(make_project, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inbox, "_stamp", lambda: "20261113T000000000000Z")
    cfg = build(make_project)
    order = [9, *range(12, 22)]
    result = inbox.put(cfg, _spec(tmp_path, [_item(issue) for issue in order]))
    assert len(result.paths) == 11
    assert sorted(result.paths, key=lambda p: p.name) == list(result.paths)
    issues = [json.loads(p.read_text(encoding="utf-8"))["items"][0]["issue"] for p in result.paths]
    assert issues == order


def test_a_failed_rename_deletes_the_files_already_renamed(make_project, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = build(make_project)
    real = inbox._report._replace_with_retry
    calls: List[str] = []

    def second_fails(src: str, dst: Path) -> None:
        if not Path(dst).name.startswith("."):
            calls.append(src)
            if len(calls) == 2:
                raise OSError("rename refused")
        real(src, dst)

    monkeypatch.setattr(inbox._report, "_replace_with_retry", second_fails)
    with pytest.raises(OSError, match="rename refused"):
        inbox.put(cfg, _spec(tmp_path, [_item(9), _item(12)]))
    assert _names(cfg) == []


def test_a_failed_inbox_write_names_the_issue_already_filed(make_project, tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gh, "run_gh", lambda cwd, args, stdin=None: URL.format(n=42) + "\n")

    def refuse(path: Path, text: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(inbox, "write_atomic", refuse)
    cfg = build(make_project)
    with pytest.raises(TodoSyncError, match="#42"):
        inbox.put(cfg, _spec(tmp_path, [_item(None)]), file_issues=True)


def test_a_failed_render_after_the_write_never_adds_the_items_twice(make_project,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = build(make_project)
    _queue(cfg, "20261113T000001Z-00-aaaaaa.json", [_item(None, title="A local note")])

    def refuse(cfg, date: dt.date) -> Path:
        raise TodoSyncError("render refused")

    with monkeypatch.context() as patch:
        patch.setattr(inbox, "render_snapshot", refuse)
        with pytest.raises(TodoSyncError, match="render refused"):
            inbox.drain(cfg, today=DAY)
    assert _names(cfg) == []
    assert inbox.drain_lines(inbox.drain(cfg, today=DAY)) == ["inbox: empty"]
    titles = [i["title"] for i in _catalog(cfg)["items"]]
    assert titles.count("A local note") == 1


def _refuse_unlink(path: Path) -> None:
    raise PermissionError(13, "file in use")


def test_an_undeletable_accepted_file_is_named_and_never_added_twice(make_project,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = build(make_project)
    name = "20261113T000001Z-00-aaaaaa.json"
    _queue(cfg, name, [_item(None, title="A local note")])
    with monkeypatch.context() as patch:
        patch.setattr(inbox, "_unlink_with_retry", _refuse_unlink)
        with pytest.raises(TodoSyncError) as caught:
            inbox.drain(cfg, today=DAY)
    message = str(caught.value)
    assert message.startswith("inbox: added ") and "could not be deleted" in message and name in message
    assert inbox.queued(cfg) == []
    assert inbox.drain_lines(inbox.drain(cfg, today=DAY)) == ["inbox: empty"]
    titles = [i["title"] for i in _catalog(cfg)["items"]]
    assert titles.count("A local note") == 1


def test_a_file_that_cannot_be_claimed_stays_queued_for_a_later_drain(
        make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = build(make_project)
    held = _queue(cfg, "20261113T000001Z-00-aaaaaa.json", [_item(None, title="A held note")])
    _queue(cfg, "20261113T000002Z-00-bbbbbb.json", [_item(9)])
    real = inbox._report._replace_with_retry

    def hold(src: str, dst: Path) -> None:
        if Path(src) == held:
            raise PermissionError(13, "file in use")
        real(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(inbox._report, "_replace_with_retry", hold)
        result = inbox.drain(cfg, today=DAY)
    assert [issue for _, issue in result.added] == [9]
    assert inbox.queued(cfg) == [held]
    inbox.drain(cfg, today=DAY)
    titles = [i["title"] for i in _catalog(cfg)["items"]]
    assert titles.count("A held note") == 1


def test_a_failed_catalog_write_puts_every_claimed_file_back(make_project,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = build(make_project)
    before = cfg.path(CATALOG_REL).read_bytes()
    names = ["20261113T000001Z-00-aaaaaa.json", "20261113T000002Z-00-bbbbbb.json"]
    _queue(cfg, names[0], [_item(9)])
    _queue(cfg, names[1], [_item(11)])

    def refuse(cfg, text: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(inbox, "write_edits", refuse)
    with pytest.raises(OSError, match="disk full"):
        inbox.drain(cfg, today=DAY)
    assert _names(cfg) == names
    assert cfg.path(CATALOG_REL).read_bytes() == before


def test_a_catalog_that_cannot_be_ranked_leaves_the_inbox_untouched(make_project,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = build(make_project)
    before = cfg.path(CATALOG_REL).read_bytes()
    _queue(cfg, "20261113T000001Z-00-aaaaaa.json", [_item(9)])

    def broken(data: Dict[str, Any]) -> None:
        raise RankingError("ranking_method lacks a weight")

    monkeypatch.setattr(inbox.reshape, "refresh_items", broken)
    with pytest.raises(TodoSyncError, match="catalog cannot be ranked"):
        inbox.drain(cfg, today=DAY)
    assert _names(cfg) == ["20261113T000001Z-00-aaaaaa.json"]
    assert cfg.path(CATALOG_REL).read_bytes() == before


def test_a_refused_file_that_cannot_be_set_aside_is_reported_and_stays_queued(
        make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = build(make_project)
    name = "20261113T000001Z-00-aaaaaa.json"
    _queue(cfg, name, [_item(11)])

    def refuse(claim, reason: str) -> None:
        raise OSError("rename refused")

    monkeypatch.setattr(inbox, "_set_aside", refuse)
    with pytest.raises(TodoSyncError, match="could not be set aside") as caught:
        inbox.drain(cfg, today=DAY)
    assert name in str(caught.value)
    assert _names(cfg) == [name]


def test_drain_of_an_empty_inbox_writes_nothing(make_project) -> None:
    cfg = build(make_project)
    before = cfg.path(CATALOG_REL).read_bytes()
    result = inbox.drain(cfg, today=DAY)
    assert (result.added, result.rejected) == ((), ())
    assert inbox.drain_lines(result) == ["inbox: empty"]
    assert cfg.path(CATALOG_REL).read_bytes() == before


def test_drain_adds_every_file_in_one_write_and_deletes_them(make_project) -> None:
    cfg = build(make_project)
    _queue(cfg, "20261113T000001Z-aaaaaa.json", [_item(9)])
    _queue(cfg, "20261113T000002Z-bbbbbb.json", [_item(None, title="A local note")])
    result = inbox.drain(cfg, today=DAY)
    assert [issue for _, issue in result.added] == [9, None]
    ids = {i["id"] for i in _catalog(cfg)["items"]}
    assert {new for new, _ in result.added} <= ids
    assert _names(cfg) == []
    page = cfg.path(f"{SNAP_DIR}/TODO_Snapshot.html").read_text(encoding="utf-8")
    assert "rendered=2026-11-13" in page.splitlines()[0]
    assert result.drift is not None
    [line] = inbox.drain_lines(result)
    assert line.startswith("inbox: added 2 item(s): ") and f"check drift={result.drift}" in line


def test_drain_keeps_a_rejected_file_with_its_reason_and_lands_the_rest(make_project) -> None:
    cfg = build(make_project)
    _queue(cfg, "20261113T000001Z-aaaaaa.json", [_item(9)])
    _queue(cfg, "20261113T000002Z-bbbbbb.json", [_item(9, title="Same issue drafted twice")])
    _queue(cfg, "20261113T000003Z-cccccc.json", [_item(12)])
    result = inbox.drain(cfg, today=DAY)
    assert [issue for _, issue in result.added] == [9, 12]
    [(name, reason)] = result.rejected
    assert name == "20261113T000002Z-bbbbbb.json" and "#9" in reason
    assert _names(cfg) == ["20261113T000002Z-bbbbbb.reason.txt", "20261113T000002Z-bbbbbb.rejected.json"]
    reason_text = (inbox.inbox_dir(cfg) / "20261113T000002Z-bbbbbb.reason.txt").read_text(encoding="utf-8")
    assert "#9" in reason_text
    [line] = inbox.drain_lines(result)
    assert "rejected 1" in line


def test_drain_skips_temp_and_rejected_files(make_project) -> None:
    cfg = build(make_project)
    _queue(cfg, ".20261113T000001Z-aaaaaa.json.x1.tmp", [_item(9)])
    _queue(cfg, ".20261113T000001000000Z-01-aaaaaa.json", [_item(12)])
    _queue(cfg, "20261113T000000Z-zzzzzz.rejected.json", [_item(13)])
    assert inbox.queued(cfg) == []
    result = inbox.drain(cfg, today=DAY)
    assert (result.added, result.rejected) == ((), ())
    assert len(_names(cfg)) == 3


def test_drain_with_only_rejections_leaves_the_catalog(make_project) -> None:
    cfg = build(make_project)
    before = cfg.path(CATALOG_REL).read_bytes()
    _queue(cfg, "20261113T000001Z-aaaaaa.json", [_item(11)])
    result = inbox.drain(cfg, today=DAY)
    assert result.added == () and len(result.rejected) == 1
    assert cfg.path(CATALOG_REL).read_bytes() == before
