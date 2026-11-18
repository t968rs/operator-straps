"""Behavioral tests for harness_lib.branch_capture: working-tree and commit-range captures."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Tuple

import pytest

from harness_lib import branch_capture
from harness_lib.commit_grouping import CapturedPath

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "false",
}


def _git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd`` with a fixed identity; return stdout."""
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env={**os.environ, **_GIT_ENV},
    )
    return result.stdout.strip()


def _write(root: Path, rel: str, text: str = "x\n") -> None:
    """Write ``text`` to ``root/rel``, creating parents."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def repo(make_project: Callable[..., Path]) -> Tuple[Path, str, str]:
    """``main`` base commit; branch ``feat`` with one commit (edit + rename).

    The working tree also holds an unstaged edit and an untracked file.

    Returns (repo, base SHA, feat head SHA).
    """
    root = make_project(files={"a.py": "x\n", "docs/old.md": "same\n" * 5})
    base = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-b", "feat")
    _write(root, "a.py", "changed\n")
    _git(root, "mv", "docs/old.md", "docs/new.md")
    _git(root, "commit", "-am", "feat work")
    head = _git(root, "rev-parse", "HEAD")
    _write(root, "a.py", "uncommitted\n")
    _write(root, "b.py")
    return root, base, head


class TestCapturePaths:
    def test_working_tree_includes_uncommitted_and_untracked(self, repo: Tuple[Path, str, str]) -> None:
        root, base, _ = repo
        assert [c.path for c in branch_capture.capture_paths(root, base)] == ["a.py", "b.py", "docs/new.md"]

    def test_head_ref_is_committed_only(self, repo: Tuple[Path, str, str]) -> None:
        root, base, head = repo
        assert branch_capture.capture_paths(root, base, head) == [
            CapturedPath("M", "a.py"), CapturedPath("R", "docs/new.md", "docs/old.md"),
        ]


class TestCaptureStats:
    def test_head_ref_counts_committed_lines(self, repo: Tuple[Path, str, str]) -> None:
        root, base, head = repo
        stats = branch_capture.capture_stats(root, base, branch_capture.capture_paths(root, base, head), head)
        assert (stats["a.py"].added, stats["a.py"].deleted) == (1, 1)
        assert (stats["docs/new.md"].added, stats["docs/new.md"].deleted) == (0, 0)

    def test_working_tree_counts_untracked_lines(self, repo: Tuple[Path, str, str]) -> None:
        root, base, _ = repo
        stats = branch_capture.capture_stats(root, base, branch_capture.capture_paths(root, base))
        assert stats["b.py"].added == 1


class TestPathDiff:
    def test_head_ref_diff_ignores_working_tree(self, repo: Tuple[Path, str, str]) -> None:
        root, base, head = repo
        text = branch_capture.path_diff(root, base, "a.py", None, untracked=False, head=head)
        assert "+changed" in text
        assert "uncommitted" not in text

    def test_untracked_reads_as_additions(self, repo: Tuple[Path, str, str]) -> None:
        root, base, _ = repo
        assert branch_capture.path_diff(root, base, "b.py", None, untracked=True) == "+x"


class TestNonUtf8Tracked:
    def test_tracked_cp1252_diff_does_not_raise(self, repo: Tuple[Path, str, str]) -> None:
        root, _, _ = repo
        (root / "caf.txt").write_bytes(b"caf\xe9\n")
        _git(root, "add", "caf.txt")
        _git(root, "commit", "-m", "cp1252")
        base = _git(root, "rev-parse", "HEAD~1")
        (root / "caf.txt").write_bytes(b"caf\xe9 au lait\n")
        text = branch_capture.path_diff(root, base, "caf.txt", None, untracked=False)
        assert "caf" in text


class TestResolveMergeBase:
    def test_named_base_without_fetch(self, repo: Tuple[Path, str, str]) -> None:
        root, base, _ = repo
        _git(root, "update-ref", "refs/remotes/origin/main", base)
        assert branch_capture.resolve_merge_base(root, "main", fetch=False) == base

    def test_local_base_ahead_of_origin_wins(self, repo: Tuple[Path, str, str]) -> None:
        root, base, head = repo
        _git(root, "update-ref", "refs/remotes/origin/main", base)
        _git(root, "update-ref", "refs/heads/main", head)
        assert branch_capture.resolve_merge_base(root, "main", fetch=False) == head

    def test_origin_ahead_of_local_base_wins(self, repo: Tuple[Path, str, str]) -> None:
        root, base, head = repo
        _git(root, "update-ref", "refs/remotes/origin/trunk", head)
        _git(root, "update-ref", "refs/heads/trunk", base)
        assert branch_capture.resolve_merge_base(root, "trunk", fetch=False) == head

    def test_without_remote_ref_uses_local_base(self, repo: Tuple[Path, str, str]) -> None:
        root, base, _ = repo
        _git(root, "update-ref", "refs/heads/trunk", base)
        assert branch_capture.resolve_merge_base(root, "trunk", fetch=False) == base

    def test_fetch_failure_names_the_base(self, repo: Tuple[Path, str, str]) -> None:
        root, _, _ = repo
        with pytest.raises(branch_capture.CaptureError, match="fetch origin trunk"):
            branch_capture.resolve_merge_base(root, "trunk")


class TestGitOut:
    def test_failure_raises_capture_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
        with pytest.raises(branch_capture.CaptureError, match="git rev-parse"):
            branch_capture.git_out(tmp_path, "rev-parse", "HEAD")
