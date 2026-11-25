"""Tests for the two-call ``c-msg`` flow of ``branch_commit_msg.py``.

``capture --pending --save --diff`` saves the skeleton and prints the block's budgeted diff from the same
capture, so the drafter needs no separate ``diff`` call; a canned block prints its message and no diff.
``message --block 1 --build`` sets the message and builds the TXT in one call, printing only the receipt.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "harness" / "lib"))

from conftest import git  # noqa: E402

_MESSAGE = "Fix(io): return early on an empty file\n\nThe reader raised on empty input.\n  - a.py: return []"


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> ModuleType:
    """Import branch_commit_msg.py by absolute path."""
    path = plugin_root / "scripts" / "branch_commit_msg.py"
    spec = importlib.util.spec_from_file_location("branch_commit_msg_pending_flow", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def repo(make_project: Callable[..., Path]) -> Path:
    """A project on branch ``0001-demo`` with one modified tracked file pending against HEAD."""
    root = make_project(config={}, files={"src/a.py": "def read():\n    return None\n"})
    git(root, "checkout", "-q", "-b", "0001-demo")
    (root / "src" / "a.py").write_text("def read():\n    return []\n", encoding="utf-8")
    return root


def _run(script: ModuleType, argv: List[str]) -> int:
    """``main`` with an argparse exit folded into its return code."""
    try:
        return script.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)


def _skeleton(root: Path) -> Path:
    return root / "docs" / "_commit_messages" / "0001-demo_pending.json"


def test_capture_diff_prints_the_block_diff_after_the_saved_path(
        script: ModuleType, repo: Path, capsys: pytest.CaptureFixture,
) -> None:
    assert _run(script, ["--repo", str(repo), "capture", "--pending", "--save", "--diff"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0] == f"wrote {_skeleton(repo).resolve().as_posix()}"
    assert lines[1] == "message: empty"
    assert "=== src/a.py [full, +1 -1] ===" in out
    assert "+    return []" in out


def test_capture_diff_on_a_canned_block_prints_the_message_and_no_diff(
        script: ModuleType, make_project: Callable[..., Path], capsys: pytest.CaptureFixture,
) -> None:
    root = make_project(config={}, files={})
    git(root, "checkout", "-q", "-b", "0001-demo")
    review = root / "docs" / "PR_REVIEWS" / "0001_demo.json"
    review.parent.mkdir(parents=True)
    review.write_text("{}\n", encoding="utf-8")
    assert _run(script, ["--repo", str(root), "capture", "--pending", "--save", "--diff"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    canned = json.loads(_skeleton(root).read_text(encoding="utf-8"))["commits"]["1"][1]
    assert lines[1] == "message: canned"
    assert canned
    assert lines[2] == canned.splitlines()[0]
    assert "===" not in out


def test_capture_diff_on_a_carried_message_prints_it_before_the_diff(
        script: ModuleType, repo: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _run(script, ["--repo", str(repo), "capture", "--pending", "--save"]) == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO(_MESSAGE))
    argv = ["--repo", str(repo), "message", str(_skeleton(repo)), "--block", "1", "--build"]
    assert _run(script, argv) == 0
    capsys.readouterr()
    assert _run(script, ["--repo", str(repo), "capture", "--pending", "--save", "--diff"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[1] == "message: carried"
    assert out.index("Fix(io): return early on an empty file") < out.index("=== src/a.py")


def test_capture_diff_needs_pending_and_save(
        script: ModuleType, repo: Path, capsys: pytest.CaptureFixture,
) -> None:
    assert _run(script, ["--repo", str(repo), "capture", "--save", "--diff", "--no-fetch"]) == 1
    assert _run(script, ["--repo", str(repo), "capture", "--pending", "--diff"]) == 1
    err = capsys.readouterr().err
    assert err.count("problem: --diff") == 2, err


def test_capture_diff_with_out_prints_the_block_diff_after_the_written_path(
        script: ModuleType, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    target = tmp_path / "s.json"
    assert _run(script, ["--repo", str(repo), "capture", "--pending", "--out", str(target), "--diff"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].startswith("wrote ")
    assert target.is_file()
    assert lines[1] == "message: empty"
    assert "=== src/a.py [full, +1 -1] ===" in out


def test_message_build_sets_the_message_and_prints_only_the_receipt(
        script: ModuleType, repo: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _run(script, ["--repo", str(repo), "capture", "--pending", "--save"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(sys, "stdin", io.StringIO(_MESSAGE + "\n"))
    code = _run(script, ["--repo", str(repo), "message", str(_skeleton(repo)), "--block", "1", "--build"])
    out = capsys.readouterr().out
    assert code == 0
    assert "set message of block" not in out
    assert "Fix(io): return early on an empty file" in out
    txt = _skeleton(repo).with_suffix(".txt")
    assert "return early on an empty file" in txt.read_text(encoding="utf-8")
    assert json.loads(_skeleton(repo).read_text(encoding="utf-8"))["commits"]["1"][1] == _MESSAGE


def test_message_build_keeps_the_message_when_build_refuses(
        script: ModuleType, repo: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _run(script, ["--repo", str(repo), "capture", "--pending", "--save"]) == 0
    bad = 'Fix(io): return "early"\n\nWhy.\n  - a.py: x'
    monkeypatch.setattr(sys, "stdin", io.StringIO(bad))
    code = _run(script, ["--repo", str(repo), "message", str(_skeleton(repo)), "--block", "1", "--build"])
    assert code == 1
    assert "problem:" in capsys.readouterr().err
    assert json.loads(_skeleton(repo).read_text(encoding="utf-8"))["commits"]["1"][1] == bad
    assert not _skeleton(repo).with_suffix(".txt").exists()
