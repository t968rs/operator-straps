"""``write_atomic`` retries ``os.replace`` on ``PermissionError``, which Windows raises while another process
(an IDE indexer, a reader) holds the target open; the last failure propagates and leaves no temp file."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness_lib.todo_sync import report

WALK_ROOTS = ()


def _flaky_replace(monkeypatch: pytest.MonkeyPatch, failures: int) -> list:
    calls: list = []
    real = os.replace

    def replace(src, dst) -> None:
        calls.append(dst)
        if len(calls) <= failures:
            raise PermissionError(13, "in use", str(dst))
        real(src, dst)

    monkeypatch.setattr(report.os, "replace", replace)
    monkeypatch.setattr(report, "REPLACE_DELAY_SECONDS", 0)
    return calls


def test_a_transient_permission_error_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "RepoToDo.json"
    target.write_text("old\n", encoding="utf-8")
    calls = _flaky_replace(monkeypatch, failures=2)
    report.write_atomic(target, "new\n")
    assert target.read_text(encoding="utf-8") == "new\n"
    assert len(calls) == 3
    assert [p.name for p in tmp_path.iterdir()] == ["RepoToDo.json"]


def test_a_persistent_permission_error_propagates_and_cleans_up(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "RepoToDo.json"
    target.write_text("old\n", encoding="utf-8")
    calls = _flaky_replace(monkeypatch, failures=10_000)
    with pytest.raises(PermissionError):
        report.write_atomic(target, "new\n")
    assert len(calls) == report.REPLACE_ATTEMPTS
    assert target.read_text(encoding="utf-8") == "old\n"
    assert [p.name for p in tmp_path.iterdir()] == ["RepoToDo.json"]


def test_other_os_errors_are_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []

    def replace(src, dst) -> None:
        calls.append(dst)
        raise FileNotFoundError(2, "gone", str(dst))

    monkeypatch.setattr(report.os, "replace", replace)
    monkeypatch.setattr(report, "REPLACE_DELAY_SECONDS", 0)
    with pytest.raises(FileNotFoundError):
        report.write_atomic(tmp_path / "x.json", "{}\n")
    assert len(calls) == 1
