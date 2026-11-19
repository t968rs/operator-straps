"""Behavioral tests for the harness working command ``skills/working/commands/working.py`` (plan 2025).

The command keeps the per-branch override of the working refs the working-refs mod shows: ``set`` writes the
current branch's TODO ids and issues, ``clear`` drops them, ``list`` prints every branch's. Each test runs it
against a throwaway project built by ``make_project`` and reads the file the mod reads.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Optional

from conftest import git

WALK_ROOTS = ()  # walks nothing; files live under a make_project repo
_STORE_REL = ".claude/state/harness/working-refs/overrides.json"
_BRANCH = "1168-todo-banner"


def _script(plugin_root: Path) -> ModuleType:
    path = plugin_root / "skills" / "working" / "commands" / "working.py"
    assert path.is_file(), f"missing {path}"
    spec = importlib.util.spec_from_file_location("working_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _project(make_project, config: Optional[Dict[str, Any]] = None) -> Path:
    project = make_project(config=config or {})
    git(project, "checkout", "-q", "-b", _BRANCH)
    return project


def _branches(project: Path, rel: str = _STORE_REL) -> Dict[str, Any]:
    return json.loads((project / rel).read_text(encoding="utf-8"))["branches"]


def test_set_writes_the_override_for_the_current_branch(plugin_root, make_project, capsys) -> None:
    script, project = _script(plugin_root), _project(make_project)
    assert script.main(["--repo", str(project), "set", "TODO-K69M", "#301"]) == 0
    entry = _branches(project)[_BRANCH]
    assert (entry["todo_ids"], entry["issues"]) == (["todo-k69m"], [301])
    assert "todo-k69m (301)" in capsys.readouterr().out


def test_a_detached_head_keys_its_override_as_detached(plugin_root, make_project) -> None:
    script, project = _script(plugin_root), _project(make_project)
    git(project, "checkout", "-q", "--detach")
    assert script.main(["--repo", str(project), "set", "#315"]) == 0
    assert _branches(project)["(detached)"]["issues"] == [315]


def test_clear_drops_only_the_current_branch(plugin_root, make_project, capsys) -> None:
    script, project = _script(plugin_root), _project(make_project)
    script.main(["--repo", str(project), "set", "#301"])
    git(project, "checkout", "-q", "-b", "other")
    script.main(["--repo", str(project), "set", "#7"])
    assert script.main(["--repo", str(project), "clear"]) == 0
    assert sorted(_branches(project)) == [_BRANCH]
    assert "cleared" in capsys.readouterr().out


def test_list_prints_every_branch_with_its_refs(plugin_root, make_project, capsys) -> None:
    script, project = _script(plugin_root), _project(make_project)
    script.main(["--repo", str(project), "set", "todo-k69m", "#301"])
    capsys.readouterr()
    assert script.main(["--repo", str(project), "list"]) == 0
    assert f"{_BRANCH}: todo-k69m (301)" in capsys.readouterr().out


def test_list_on_an_empty_store_says_no_overrides(plugin_root, make_project, capsys) -> None:
    script, project = _script(plugin_root), _project(make_project)
    assert script.main(["--repo", str(project), "list"]) == 0
    assert capsys.readouterr().out.strip() == "no overrides"


def test_clear_with_no_override_says_so_and_writes_nothing(plugin_root, make_project, capsys) -> None:
    script, project = _script(plugin_root), _project(make_project)
    assert script.main(["--repo", str(project), "clear"]) == 0
    assert f"no override for {_BRANCH}" in capsys.readouterr().out
    assert not (project / _STORE_REL).exists()


def test_a_bad_ref_exits_1_and_writes_nothing(plugin_root, make_project, capsys) -> None:
    script, project = _script(plugin_root), _project(make_project)
    assert script.main(["--repo", str(project), "set", "banana!"]) == 1
    assert capsys.readouterr().err.startswith("working:")
    assert not (project / _STORE_REL).exists()


def test_state_dir_comes_from_the_project_config(plugin_root, make_project) -> None:
    script, project = _script(plugin_root), _project(make_project, {"state_dir": "var/state"})
    script.main(["--repo", str(project), "set", "#301"])
    assert _branches(project, "var/state/working-refs/overrides.json")[_BRANCH]["issues"] == [301]


def _with_catalog(project: Path) -> None:
    """Write the TODO catalog that maps todo-k69m to issue 301 under the folder the config names."""
    folder = project / "docs" / "TODO"
    folder.mkdir(parents=True, exist_ok=True)
    catalog = {"items": [{"id": "todo-k69m", "gh_issues": [301]}]}
    (folder / "RepoToDo.json").write_text(json.dumps(catalog), encoding="utf-8")


def test_set_fills_issues_from_the_todo_catalog(plugin_root, make_project, capsys) -> None:
    script = _script(plugin_root)
    project = _project(make_project, {"todo": {"folder": "docs/TODO"}})
    _with_catalog(project)
    assert script.main(["--repo", str(project), "set", "todo-k69m"]) == 0
    entry = _branches(project)[_BRANCH]
    assert (entry["todo_ids"], entry["issues"]) == (["todo-k69m"], [301])
    assert "todo-k69m (301)" in capsys.readouterr().out


def test_a_separator_only_set_exits_1_and_writes_nothing(plugin_root, make_project, capsys) -> None:
    script, project = _script(plugin_root), _project(make_project)
    assert script.main(["--repo", str(project), "set", ","]) == 1
    assert capsys.readouterr().err.startswith("working:")
    assert not (project / _STORE_REL).exists()
