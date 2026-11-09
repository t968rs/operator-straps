"""``--auto-title`` of ``merge_commit_msg.py``: a PR title the mode refuses no longer ends the run.

``capture N [--squash] --auto-title`` prints the facts with a ``- Title problem:`` line and a subject
placeholder when the title cannot head the subject of the mode, and exactly what it prints without the flag
when it can. ``retitle N [--squash] --title T`` replaces only a title the mode refuses: it runs
``change_pr_title`` (``gh pr edit``) and prints the subject to put on line 1.

``gh`` and ``change_pr_title`` are the seams, swapped for a canned PR and a recorder.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import List, Tuple

import pytest

from conftest import git
from harness_lib import pr_title

WALK_ROOTS = ()  # walks only the commit-message folder of a make_project repo
TITLE = "Fix(workers): pool crash on spawn"
LEGACY_TITLE = "[BUG] Worker pool crash on spawn"
HEAD = "7-fix-workers"


@pytest.fixture(scope="module")
def module(plugin_root: Path):
    path = plugin_root / "skills" / "merge-commit-msg" / "commands" / "merge_commit_msg.py"
    spec = importlib.util.spec_from_file_location("merge_commit_msg_auto_title", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gh(title: str):
    shape = {"number": 7, "title": title, "headRefName": HEAD, "baseRefName": "dev",
             "additions": 40, "deletions": 3, "changedFiles": 1, "body": "", "state": "OPEN"}

    def fake(repo: Path, *args: str) -> str:
        if args[:2] == ("pr", "view"):
            return json.dumps(shape)
        if args[:2] == ("pr", "diff"):
            if "--name-only" in args:
                return "workers/export.py\n"
            return "diff --git a/workers/export.py b/workers/export.py\n@@ -1 +1 @@\n-old\n+new\n"
        if args[0] == "api":
            return "Fix(workers): guard stdio\n"
        raise AssertionError(f"unexpected gh call: {args}")

    return fake


@pytest.fixture()
def root(make_project) -> Path:
    project = make_project(None, files={})
    git(project, "checkout", "-q", "-b", HEAD)
    return project


@pytest.fixture()
def edits(module, monkeypatch) -> List[Tuple[int, str, Path, str]]:
    """Calls ``retitle`` makes to ``change_pr_title``, recorded instead of run."""
    calls: List[Tuple[int, str, Path, str]] = []
    monkeypatch.setattr(module, "change_pr_title", lambda *args: calls.append(args))
    return calls


def _run(module, root: Path, monkeypatch, capsys, title: str, *argv: str):
    monkeypatch.setattr(module, "gh", _gh(title))
    try:
        code = module.main(["--repo", str(root), *argv])
    except SystemExit as exc:
        code = int(exc.code or 0)
    return code, capsys.readouterr()


def _fence(text: str) -> List[str]:
    lines = text.splitlines()
    start = lines.index("```text")
    return lines[start + 1:lines.index("```", start + 1)]


class TestCaptureAutoTitle:
    def test_usable_title_prints_what_capture_prints_without_the_flag(self, module, root, monkeypatch,
                                                                      capsys) -> None:
        plain = _run(module, root, monkeypatch, capsys, TITLE, "capture", "7", "--squash")
        auto = _run(module, root, monkeypatch, capsys, TITLE, "capture", "7", "--squash", "--auto-title")
        assert plain[0] == auto[0] == 0, auto[1].err
        assert auto[1].out == plain[1].out

    def test_refused_title_prints_facts_with_a_subject_placeholder(self, module, root, monkeypatch,
                                                                   capsys) -> None:
        code, captured = _run(module, root, monkeypatch, capsys, LEGACY_TITLE,
                              "capture", "7", "--squash", "--auto-title")
        assert code == 0, captured.err
        assert "- Title problem: is not a Word(scope): summary subject" in captured.out
        assert 'retitle 7 --squash --title "<title>"' in captured.out
        fence = _fence(captured.out)
        assert fence[0] == module.RETITLE_HINT and module.PLACEHOLDER.match(fence[0])
        assert "Branch lineage: `dev` -> `7-fix-workers`" in fence

    def test_merge_mode_keeps_a_loose_title(self, module, root, monkeypatch, capsys) -> None:
        code, captured = _run(module, root, monkeypatch, capsys, LEGACY_TITLE, "capture", "7", "--auto-title")
        assert code == 0, captured.err
        assert "Title problem" not in captured.out
        assert _fence(captured.out)[0] == f"Merge PR #7 -- {LEGACY_TITLE}"

    def test_without_the_flag_the_refusal_names_it(self, module, root, monkeypatch, capsys) -> None:
        code, captured = _run(module, root, monkeypatch, capsys, LEGACY_TITLE, "capture", "7", "--squash")
        assert code == 1 and not captured.out
        assert "--auto-title" in captured.err and "gh pr edit 7 --title" in captured.err


class TestRetitle:
    def test_retitle_sets_the_title_and_prints_the_squash_subject(self, module, root, monkeypatch, capsys,
                                                                   edits) -> None:
        code, captured = _run(module, root, monkeypatch, capsys, LEGACY_TITLE,
                              "retitle", "7", "--squash", "--title", TITLE)
        assert code == 0, captured.err
        assert edits == [(7, TITLE, root.resolve(), HEAD)]
        assert captured.out.splitlines() == [
            f"Retitled PR #7: {LEGACY_TITLE!r} -> {TITLE!r}", f"Subject: {TITLE} (#7)",
        ]

    def test_retitle_in_merge_mode_prints_the_merge_subject(self, module, root, monkeypatch, capsys,
                                                             edits) -> None:
        code, captured = _run(module, root, monkeypatch, capsys, "7 fix workers",
                              "retitle", "7", "--title", TITLE)
        assert code == 0, captured.err
        assert captured.out.splitlines()[-1] == f"Subject: Merge PR #7 -- {TITLE}"

    def test_retitle_keeps_a_usable_title(self, module, root, monkeypatch, capsys, edits) -> None:
        code, captured = _run(module, root, monkeypatch, capsys, TITLE,
                              "retitle", "7", "--squash", "--title", "Fix(workers): other")
        assert code == 1 and not edits
        assert "already heads the squash subject" in captured.err

    def test_retitle_refuses_a_new_title_with_a_defect(self, module, root, monkeypatch, capsys) -> None:
        real = pr_title.subprocess.run

        def guard(argv, *args, **kwargs):
            if argv[0] == "gh":
                pytest.fail("gh pr edit ran")
            return real(argv, *args, **kwargs)

        monkeypatch.setattr(pr_title.subprocess, "run", guard)
        code, captured = _run(module, root, monkeypatch, capsys, LEGACY_TITLE,
                              "retitle", "7", "--squash", "--title", "Worker pool fix")
        assert code == 1
        assert captured.err.startswith("problem: new title 'Worker pool fix' is not a Word(scope)")

    def test_retitle_needs_a_title(self, module, root, monkeypatch, capsys, edits) -> None:
        code, _ = _run(module, root, monkeypatch, capsys, LEGACY_TITLE, "retitle", "7", "--squash")
        assert code == 2 and not edits
