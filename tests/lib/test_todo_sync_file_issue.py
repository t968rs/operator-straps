"""Filing a GitHub issue for an added item: ``add --file-issue``.

Every spec item without ``issue`` gets one issue filed through ``gh issue create`` (the ``gh.run_gh`` seam is
replaced here), and the item records it as its ``gh_issue`` source. The whole spec is validated before the
first ``gh`` call, so a bad spec files nothing, and a dry run never calls ``gh``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _todo_helpers import CATALOG_REL, TODO_DIR, build, config  # noqa: E402
from conftest import GIT_ENV, PLUGIN_ROOT  # noqa: E402
from harness_lib.todo_sync import TodoSyncError, gh, reshape  # noqa: E402
from harness_lib.todo_sync.issues import file_issue, issue_body  # noqa: E402
from harness_lib.todo_sync.reshape import apply_add, summary_lines  # noqa: E402

DAY = "2026-11-06"
URL = "https://github.com/example/widgets/issues/{n}"


def _note(**over: Any) -> Dict[str, Any]:
    base = {"title": "Parser skips a row", "kind": "bug", "summary": "src/parse.py:12: the loop stops early.",
            "proposed_change": "Read every row.", "impact": "silent_wrong_output", "severity": 4,
            "files": ["src/parse.py"],
            "blast_radius": {"level": "S", "reasoning": "One module.", "consumers": []},
            "loe": {"size": "S", "reasoning": "Small."}, "why_ranked": "Computed from ranking_method."}
    return {**base, **over}


class FakeGh:
    """Records each ``gh`` call; ``issue create`` answers with the next issue URL, from #42."""

    def __init__(self) -> None:
        self.calls: List[List[str]] = []
        self.stdins: List[Optional[str]] = []

    def __call__(self, cwd: Path, args: List[str], stdin: Optional[str] = None) -> str:
        self.calls.append(list(args))
        self.stdins.append(stdin)
        return URL.format(n=41 + len(self.calls)) + "\n"


def _spec_file(cfg: Any, items: List[Dict[str, Any]]) -> Path:
    path = cfg.project_root / "add.json"
    path.write_text(json.dumps({"items": items}), encoding="utf-8")
    return path


def test_file_issue_returns_number_and_url(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    fake = FakeGh()
    monkeypatch.setattr(gh, "run_gh", fake)
    assert file_issue(cfg, "Title", "Body") == (42, URL.format(n=42))
    assert fake.calls == [["issue", "create", "--title", "Title", "--body-file", "-"]]
    assert fake.stdins == ["Body"]


def test_run_gh_feeds_stdin_to_the_subprocess(monkeypatch) -> None:
    seen: Dict[str, Any] = {}

    def fake_run(argv: List[str], **kwargs: Any) -> subprocess.CompletedProcess:
        seen.update(kwargs, argv=argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(gh.subprocess, "run", fake_run)
    assert gh.run_gh(Path("."), ["issue", "create", "--body-file", "-"], stdin="x" * 40000) == "ok\n"
    assert seen["argv"] == ["gh", "issue", "create", "--body-file", "-"]
    assert seen["input"] == "x" * 40000


def test_file_issue_honors_the_configured_repo(make_project, monkeypatch) -> None:
    cfg = build(make_project, cfg=config(todo={"folder": TODO_DIR, "gh": {"repo": "example/widgets"}}))
    fake = FakeGh()
    monkeypatch.setattr(gh, "run_gh", fake)
    file_issue(cfg, "Title", "Body")
    assert fake.calls[0][-2:] == ["--repo", "example/widgets"]


def test_file_issue_refuses_output_without_an_issue_url(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    monkeypatch.setattr(gh, "run_gh", lambda cwd, args, stdin=None: "created\n")
    with pytest.raises(TodoSyncError, match="no issue URL"):
        file_issue(cfg, "Title", "Body")


def test_issue_body_carries_the_item_prose() -> None:
    body = issue_body(_note())
    for text in ("src/parse.py:12: the loop stops early.", "Read every row.", "- src/parse.py"):
        assert text in body


def test_filed_issue_becomes_the_item_source(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    fake = FakeGh()
    monkeypatch.setattr(gh, "run_gh", fake)
    done = apply_add(cfg, _spec_file(cfg, [_note()]), file_issues=True, today=DAY)
    written = json.loads((cfg.project_root / CATALOG_REL).read_text(encoding="utf-8"))
    item = next(i for i in written["items"] if i["title"] == "Parser skips a row")
    assert item["sources"] == [{"type": "gh_issue", "ref": "#42", "url": URL.format(n=42)}]
    assert item["gh_issues"] == [42]
    assert f"filed #42 {URL.format(n=42)}" in summary_lines(done, False)


def test_bad_spec_files_nothing(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    fake = FakeGh()
    monkeypatch.setattr(gh, "run_gh", fake)
    before = (cfg.project_root / CATALOG_REL).read_bytes()
    with pytest.raises(TodoSyncError, match="item 2: kind"):
        apply_add(cfg, _spec_file(cfg, [_note(), _note(title="Other", kind="chore")]), file_issues=True,
                  today=DAY)
    assert fake.calls == []
    assert (cfg.project_root / CATALOG_REL).read_bytes() == before


def test_dry_run_files_nothing_and_says_what_it_would_file(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    fake = FakeGh()
    monkeypatch.setattr(gh, "run_gh", fake)
    before = (cfg.project_root / CATALOG_REL).read_bytes()
    dry = apply_add(cfg, _spec_file(cfg, [_note()]), dry_run=True, file_issues=True, today=DAY)
    assert fake.calls == []
    assert "would file 1 issue(s)" in summary_lines(dry, True)
    assert (cfg.project_root / CATALOG_REL).read_bytes() == before


def test_a_gh_failure_names_the_issues_already_filed(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    fake = FakeGh()

    def flaky(cwd: Path, args: List[str], stdin: Optional[str] = None) -> str:
        if fake.calls:
            raise TodoSyncError("gh issue create failed: rate limited")
        return fake(cwd, args, stdin)

    monkeypatch.setattr(gh, "run_gh", flaky)
    before = (cfg.project_root / CATALOG_REL).read_bytes()
    with pytest.raises(TodoSyncError, match=r"already filed: #42 "):
        apply_add(cfg, _spec_file(cfg, [_note(), _note(title="Other")]), file_issues=True, today=DAY)
    assert (cfg.project_root / CATALOG_REL).read_bytes() == before


def test_a_write_failure_after_filing_names_the_filed_issues(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    monkeypatch.setattr(gh, "run_gh", FakeGh())

    def locked(*args: Any, **kwargs: Any) -> None:
        raise OSError("catalog is locked")

    monkeypatch.setattr(reshape, "write_edits", locked)
    with pytest.raises(TodoSyncError, match=r"catalog is locked; already filed: #42 "):
        apply_add(cfg, _spec_file(cfg, [_note()]), file_issues=True, today=DAY)


def test_dry_run_labels_the_item_to_file(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    monkeypatch.setattr(gh, "run_gh", FakeGh())
    dry = apply_add(cfg, _spec_file(cfg, [_note()]), dry_run=True, file_issues=True, today=DAY)
    head = summary_lines(dry, True)[0]
    assert "(issue to file)" in head
    assert "(note)" not in head


def test_cli_dry_run_takes_the_file_issue_flag(make_project) -> None:
    cfg = build(make_project)
    spec = _spec_file(cfg, [_note()])
    env = {**os.environ, **GIT_ENV}
    env.pop("CLAUDE_PROJECT_DIR", None)
    for name in ("GH_REPO", "GH_HOST", "GH_TOKEN"):
        env.pop(name, None)
    done = subprocess.run([sys.executable, str(PLUGIN_ROOT / "scripts" / "todo_sync.py"), "--project",
                           str(cfg.project_root), "add", "--spec", str(spec), "--file-issue", "--dry-run"],
                          capture_output=True, text=True, encoding="utf-8", env=env)
    assert done.returncode == 0, done.stderr
    assert "would file 1 issue(s)" in done.stdout.splitlines()


def test_items_that_name_an_issue_are_not_filed_again(make_project, monkeypatch) -> None:
    cfg = build(make_project)
    fake = FakeGh()
    monkeypatch.setattr(gh, "run_gh", fake)
    known = _note(title="Known", issue=9, url=URL.format(n=9))
    apply_add(cfg, _spec_file(cfg, [known, _note()]), file_issues=True, today=DAY)
    assert len(fake.calls) == 1
    assert fake.calls[0][3] == "Parser skips a row"
    written = json.loads((cfg.project_root / CATALOG_REL).read_text(encoding="utf-8"))
    by_title = {i["title"]: i for i in written["items"]}
    assert by_title["Known"]["sources"] == [{"type": "gh_issue", "ref": "#9", "url": URL.format(n=9)}]
    filed = [{"type": "gh_issue", "ref": "#42", "url": URL.format(n=42)}]
    assert by_title["Parser skips a row"]["sources"] == filed
