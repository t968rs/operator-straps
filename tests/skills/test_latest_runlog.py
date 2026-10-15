"""Behavioral tests for the harness check-runlogs skill command ``commands/latest_runlog.py``.

Each test builds a throwaway project with ``make_project``, seeds log files under the configured run-log
folder and runs ``main`` in-process with ``--repo``.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Dict, List, Optional

import pytest

LOGS = "logs/_RUN_TESTS"


@pytest.fixture(scope="module")
def module(plugin_root: Path):
    path = plugin_root / "skills" / "check-runlogs" / "commands" / "latest_runlog.py"
    spec = importlib.util.spec_from_file_location("latest_runlog", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _project(make_project, names: List[str], config: Optional[dict] = None) -> Path:
    """A project whose run-log folder holds one small file per name (paths relative to the folder)."""
    files: Dict[str, str] = {f"{LOGS}/{name}": f"log {name}\n" for name in names}
    return make_project({"runlogs": {"dir": LOGS}} if config is None else config, files=files)


def _run(module, root: Path, capsys, *extra: str):
    rc = module.main(["--repo", str(root), *extra])
    captured = capsys.readouterr()
    return rc, captured.out.splitlines(), captured.err


def _names(lines: List[str]) -> List[str]:
    return [Path(line).name for line in lines]


class TestNewest:
    def test_prints_only_the_newest_path(self, module, make_project, capsys) -> None:
        root = _project(make_project, ["_RUN_TESTS_2026-10-13_120000.txt", "_RUN_TESTS_2026-10-14_090000.txt",
                                       "_RUN_TESTS_2026-10-13_235959.txt"])
        rc, out, _ = _run(module, root, capsys)
        assert rc == 0
        expected = (root / LOGS / "_RUN_TESTS_2026-10-14_090000.txt").resolve().as_posix()
        assert out == [expected]

    def test_date_only_name_sorts_as_midnight(self, module, make_project, capsys) -> None:
        root = _project(make_project, ["_RUN_TESTS_2026-10-14.txt", "_RUN_TESTS_2026-10-13_235959.txt",
                                       "_RUN_TESTS_2026-10-14_000001.txt"])
        rc, out, _ = _run(module, root, capsys, "--count", "3")
        assert rc == 0
        assert _names(out) == ["_RUN_TESTS_2026-10-14_000001.txt", "_RUN_TESTS_2026-10-14.txt",
                               "_RUN_TESTS_2026-10-13_235959.txt"]

    def test_archived_subfolder_logs_are_found(self, module, make_project, capsys) -> None:
        root = _project(make_project, ["2026-10-12/_RUN_TESTS_2026-10-12_080000.txt",
                                       "_RUN_TESTS_2026-10-11_080000.txt"])
        rc, out, _ = _run(module, root, capsys, "--count", "5")
        assert rc == 0
        assert _names(out) == ["_RUN_TESTS_2026-10-12_080000.txt", "_RUN_TESTS_2026-10-11_080000.txt"]

    def test_count_caps_at_the_logs_present(self, module, make_project, capsys) -> None:
        root = _project(make_project, ["run_2026-10-13_120000.log"])
        rc, out, _ = _run(module, root, capsys, "--count", "4")
        assert rc == 0
        assert _names(out) == ["run_2026-10-13_120000.log"]

    def test_equal_stamps_break_ties_by_mtime(self, module, make_project, capsys) -> None:
        root = _project(make_project, ["a_2026-10-13_120000.txt", "b_2026-10-13_120000.txt"])
        older, newer = root / LOGS / "b_2026-10-13_120000.txt", root / LOGS / "a_2026-10-13_120000.txt"
        os.utime(older, (1_000_000, 1_000_000))
        os.utime(newer, (2_000_000, 2_000_000))
        rc, out, _ = _run(module, root, capsys)
        assert rc == 0
        assert _names(out) == ["a_2026-10-13_120000.txt"]

    def test_stderr_names_the_count_and_newest_stamp(self, module, make_project, capsys) -> None:
        root = _project(make_project, ["_RUN_TESTS_2026-10-13_120000.txt",
                                       "_RUN_TESTS_2026-10-14_090000.txt"])
        _, _, err = _run(module, root, capsys)
        assert "2 run logs" in err
        assert "2026-10-14 09:00:00" in err


class TestNameFilter:
    @pytest.mark.parametrize("stray", [
        "_RUN_TESTS_2026-10-13_notes.txt",
        "_RUN_TESTS_2026-13-01_120000.txt",
        "_RUN_TESTS_2026-10-13_256000.txt",
        "_RUN_TESTS_2026-10-13_120000.json",
        "_RUN_TESTS_2026-10-13_120000.txt.bak",
        "README.txt",
    ])
    def test_stray_names_are_never_picked(self, module, make_project, capsys, stray: str) -> None:
        root = _project(make_project, [stray, "_RUN_TESTS_2026-01-01_000000.txt"])
        rc, out, _ = _run(module, root, capsys, "--count", "5")
        assert rc == 0
        assert _names(out) == ["_RUN_TESTS_2026-01-01_000000.txt"]

    def test_configured_pattern_replaces_the_default(self, module, make_project, capsys) -> None:
        config = {"runlogs": {"dir": LOGS, "name_pattern": r"pytest-(?P<date>\d{4}-\d{2}-\d{2})\.log"}}
        root = _project(make_project, ["pytest-2026-10-12.log", "run_2026-10-14_120000.txt"], config)
        rc, out, _ = _run(module, root, capsys, "--count", "5")
        assert rc == 0
        assert _names(out) == ["pytest-2026-10-12.log"]

    def test_pattern_without_a_date_group_is_a_problem(self, module, make_project, capsys) -> None:
        config = {"runlogs": {"dir": LOGS, "name_pattern": r"run_\d+\.txt"}}
        root = _project(make_project, ["run_1.txt"], config)
        rc, out, err = _run(module, root, capsys)
        assert rc == 1
        assert out == []
        assert "problem:" in err and "date" in err


class TestFolder:
    def test_unset_dir_is_a_problem_naming_the_key(self, module, make_project, capsys) -> None:
        root = make_project(None, files={f"{LOGS}/_RUN_TESTS_2026-10-13_120000.txt": "x\n"})
        rc, out, err = _run(module, root, capsys)
        assert rc == 1
        assert out == []
        assert "problem:" in err and "runlogs.dir" in err

    def test_dir_flag_overrides_the_config(self, module, make_project, capsys) -> None:
        root = make_project(None, files={"other/run_2026-10-13_120000.txt": "x\n"})
        rc, out, _ = _run(module, root, capsys, "--dir", "other")
        assert rc == 0
        assert _names(out) == ["run_2026-10-13_120000.txt"]

    def test_missing_folder_is_a_problem(self, module, make_project, capsys) -> None:
        root = make_project({"runlogs": {"dir": "nowhere"}})
        rc, _, err = _run(module, root, capsys)
        assert rc == 1
        assert "problem:" in err and "nowhere" in err

    def test_folder_without_logs_is_a_problem(self, module, make_project, capsys) -> None:
        root = _project(make_project, ["README.txt"])
        rc, out, err = _run(module, root, capsys)
        assert rc == 1
        assert out == []
        assert "problem:" in err and "no run log" in err

    def test_nothing_is_moved_or_written(self, module, make_project, capsys) -> None:
        names = [f"_RUN_TESTS_2026-10-{d:02d}_120000.txt" for d in range(1, 15)]
        root = _project(make_project, names)
        before = sorted(p.relative_to(root).as_posix() for p in (root / LOGS).rglob("*"))
        assert _run(module, root, capsys)[0] == 0
        after = sorted(p.relative_to(root).as_posix() for p in (root / LOGS).rglob("*"))
        assert after == before
