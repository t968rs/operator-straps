"""The catalog lock file never shows up in the reference scan of the retire it guards.

A lease owner is free text and may name an item id, and the lock file lies under ``<state_dir>`` inside the
project, where ``git grep --untracked`` would find it. Projects come from ``tests/lib/_todo_helpers.py``;
``make_project`` builds them as committed git repositories, so the scan runs.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _todo_helpers import ID3, build  # noqa: E402
from conftest import PLUGIN_ROOT  # noqa: E402
from harness_lib import catalog_lock  # noqa: E402

WALK_ROOTS = ()


@pytest.fixture(scope="module")
def driver():
    script = PLUGIN_ROOT / "scripts" / "todo_sync.py"
    spec = importlib.util.spec_from_file_location("todo_sync_scan_driver", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def short_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog_lock, "WAIT_SECONDS", 0.2)


def _run(driver, cfg, capsys, *args: str):
    code = driver.main(["--project", str(cfg.project_root), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_a_lease_naming_the_retired_id_is_not_a_reference(driver, make_project, capsys) -> None:
    cfg = build(make_project)
    assert (cfg.project_root / ".git").exists()
    code, out, err = _run(driver, cfg, capsys, "lease", "acquire", "--owner", f"todo-editor retire {ID3}")
    assert code == 0, err
    found = re.search(r"^lease: (\S+)$", out, re.MULTILINE)
    assert found, out
    code, out, err = _run(driver, cfg, capsys, "retire", ID3, "--lease", found.group(1))
    assert code == 0, err
    lines = (out + err).splitlines()
    assert [line for line in lines if "reference" in line and "locks/" in line] == []
