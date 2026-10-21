"""Behavioral tests for harness_lib.min_viz_sentinel: sentinel location, arming and clearing."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from conftest import git
from harness_lib.config import load_config
from harness_lib.min_viz_sentinel import arm, clear, sentinel_dir_under, sentinel_path
from harness_lib.validation.artifact_names import phase5_sentinel_dir


def test_directory_sits_beside_the_phase5_one(make_project: Callable[..., Path]) -> None:
    cfg = load_config(make_project())
    assert sentinel_path(cfg, 41).parent == phase5_sentinel_dir(cfg).parent / "pr-sum"
    assert sentinel_path(cfg, 41).name == ".minviz_pending_41"


def test_arm_writes_pr_time_session_and_minimum(
        make_project: Callable[..., Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
    path = arm(load_config(make_project()), 41, 3, now=1700000000)
    assert path.read_text(encoding="utf-8") == "41\n1700000000\nsess-1\n3\n"


def test_arm_without_a_session_id_leaves_line_three_blank(
        make_project: Callable[..., Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    path = arm(load_config(make_project()), 41, 3, now=1700000000)
    assert path.read_text(encoding="utf-8").split("\n") == ["41", "1700000000", "", "3", ""]


def test_rearming_replaces_the_file(make_project: Callable[..., Path]) -> None:
    cfg = load_config(make_project())
    arm(cfg, 41, 3, now=1)
    path = arm(cfg, 41, 5, now=2)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert (lines[1], lines[3]) == ("2", "5")


def test_clear_removes_and_reports(make_project: Callable[..., Path]) -> None:
    cfg = load_config(make_project())
    path = arm(cfg, 41, 3)
    assert clear(cfg, 41) is True
    assert not path.exists()
    assert clear(cfg, 41) is False


def test_linked_worktree_arms_the_main_checkout(make_project: Callable[..., Path], tmp_path: Path) -> None:
    main = make_project()
    git(main, "worktree", "add", str(tmp_path / "linked"), "-b", "linked")
    linked = tmp_path / "linked"
    assert sentinel_dir_under(linked, ".claude/state/harness") == sentinel_dir_under(main, ".claude/state/harness")
