"""``strap.py reopen`` (plan 1014, DRV-1): a second round of behaviors on a frozen spec.

``reopen`` moves the frozen stamp into ``rounds``, clears ``frozen`` and moves ``base``, so the spec takes new
behaviors again. ``red`` skips a behavior frozen green in an earlier round (its code already exists at the
new base), and the next ``freeze`` gates every live behavior and names the last round's hash.

The driver runs in-process through ``main`` with ``--repo``; specs are built through ``strap.py api``.
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Tuple

import pytest
from conftest import git

Result = Tuple[int, str, str]
Strap = Callable[..., Result]
NAME = "demo-skill"
PLANS = "docs/PLANS"
SKILL = f"plugins/harness/skills/{NAME}/SKILL.md"
PLUGIN_FILES = {
    "plugins/harness/.claude-plugin/plugin.json": {"name": "harness"},
    "plugins/harness/reference/skill_arguments.md": "# Skill arguments\n",
}
ADD_PART = f'add_part(name, "skill_md", "{SKILL}")\n'


def _mechanical_code(statement: str, node: str) -> str:
    return (f'add_behavior(name, new_behavior(statement="{statement}", kind="mechanical",\n'
            f'    rationale="A file test pins it", tests=[new_test("{node}", "AssertionError")]))\n')


def _file_test(stem: str) -> str:
    return (f'"""Planned test: {stem}.txt exists at the project root."""\n'
            "from pathlib import Path\n\n\n"
            f"def test_{stem}_exists() -> None:\n"
            f'    assert (Path(__file__).resolve().parents[1] / "{stem}.txt").is_file()\n')


@pytest.fixture(scope="module")
def driver(plugin_root: Path) -> ModuleType:
    path = plugin_root / "scripts" / "strap.py"
    assert path.is_file(), f"{path} does not exist"
    spec = importlib.util.spec_from_file_location("strap_reopen_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def project(make_project, tmp_path: Path) -> Path:
    config = {"base_branch": "main", "worktree_root": (tmp_path / "trees").as_posix(),
              "strap": {"target": "harness"}}
    return make_project(config, files=dict(PLUGIN_FILES))


@pytest.fixture()
def strap(driver: ModuleType, project: Path, capsys: pytest.CaptureFixture) -> Strap:
    def _run(*args: str) -> Result:
        code = driver.main(["--repo", str(project), *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    return _run


@pytest.fixture()
def piped(strap: Strap, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Result]:
    def _piped(text: str, *args: str) -> Result:
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))
        return strap(*args)
    return _piped


@pytest.fixture()
def reopen(driver: ModuleType, strap: Strap) -> Strap:
    """``reopen(*args)``: ``strap.py reopen NAME *args``; a driver without the command fails here."""
    assert "reopen" in driver.COMMANDS, "strap.py has no reopen command"
    return lambda *args: strap("reopen", NAME, *args)


def read_spec(project: Path) -> Dict[str, Any]:
    path = project / PLANS / "strap" / NAME / "SkillSpec.json"
    return json.loads(path.read_text(encoding="utf-8"))


def ok(result: Result) -> str:
    code, out, err = result
    assert code == 0, err
    return out


def refused(result: Result) -> str:
    code, _, err = result
    lines = [line for line in err.splitlines() if line.strip()]
    assert code == 1 and lines and all(line.startswith("problem: ") for line in lines), err
    return err


def has_problem(err: str, text: str) -> bool:
    return f"problem: {text}" in [line.strip() for line in err.splitlines()]


def write(project: Path, rel: str, text: str) -> None:
    target = project / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def plant(project: Path, stem: str) -> None:
    """The planned test of ``stem`` under the spec's tests folder."""
    write(project, f"{PLANS}/strap/{NAME}/tests/tests/test_{stem}.py", _file_test(stem))


def implement(project: Path, stem: str) -> None:
    write(project, f"tests/test_{stem}.py", _file_test(stem))
    write(project, f"{stem}.txt", f"{stem}\n")


def commit_all(project: Path) -> str:
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "work")
    return git(project, "rev-parse", "HEAD")


@pytest.fixture()
def frozen(strap: Strap, piped: Callable[..., Result], project: Path) -> str:
    """A new-mode spec with mechanical B1 (widget) frozen and committed; returns the frozen hash."""
    ok(strap("new", NAME))
    ok(piped(_mechanical_code("Writes widget.txt", "tests/test_widget.py::test_widget_exists"), "api", NAME))
    write(project, SKILL, f"---\nname: {NAME}\ndescription: Use when testing reopen.\n---\n\nBody.\n")
    ok(piped(ADD_PART, "api", NAME))
    plant(project, "widget")
    ok(strap("red", NAME))
    implement(project, "widget")
    ok(strap("freeze", NAME))
    commit_all(project)
    return read_spec(project)["frozen"]["skill_hash"]


def test_driver_docstring_names_reopen(driver: ModuleType) -> None:
    assert "``reopen <name> [--base REF]``" in (driver.__doc__ or "")


def test_reopen_refuses_an_unfrozen_spec(reopen: Strap, strap: Strap, project: Path) -> None:
    ok(strap("new", NAME))
    before = read_spec(project)
    err = refused(reopen())
    assert has_problem(err, f"{NAME} is not frozen; nothing to reopen"), err
    assert read_spec(project) == before


def test_reopen_moves_the_stamp_into_rounds(frozen: str, reopen: Strap, strap: Strap,
                                            project: Path) -> None:
    head = git(project, "rev-parse", "HEAD")
    out = ok(reopen())
    pattern = rf"^reopen \[done\] \| {NAME} \| round 2 \| base {head[:12]} \| was {frozen[:12]}\s*$"
    assert re.search(pattern, out, re.MULTILINE), out
    spec = read_spec(project)
    assert spec["frozen"] is None and spec["mode"] == "edit" and spec["base"] == head
    [done] = spec["rounds"]
    assert done["frozen"]["skill_hash"] == frozen and done["behaviors"] == ["B1"] and done["base"] is None
    assert spec["behaviors"][0]["state"] == "green"
    check = ok(strap("check", NAME))
    assert "check [ok]" in check and "stale:" not in check


def test_reopen_refuses_a_base_that_names_no_commit(frozen: str, reopen: Strap, project: Path) -> None:
    before = read_spec(project)
    err = refused(reopen("--base", "no-such-ref"))
    assert has_problem(err, "--base no-such-ref does not name a commit"), err
    assert read_spec(project) == before


def test_red_after_reopen_runs_only_the_new_behavior(frozen: str, reopen: Strap, strap: Strap,
                                                     piped: Callable[..., Result], project: Path) -> None:
    ok(reopen())
    ok(piped(_mechanical_code("Writes gadget.txt", "tests/test_gadget.py::test_gadget_exists"), "api", NAME))
    plant(project, "gadget")
    out = ok(strap("red", NAME))
    assert "1 nodes fail as planned" in out and "B2 " in out and "B1 " not in out, out
    states = {b["id"]: b["state"] for b in read_spec(project)["behaviors"]}
    assert states == {"B1": "green", "B2": "red"}


def test_freeze_after_reopen_gates_every_behavior(frozen: str, reopen: Strap, strap: Strap,
                                                  piped: Callable[..., Result], project: Path) -> None:
    ok(reopen())
    ok(piped(_mechanical_code("Writes gadget.txt", "tests/test_gadget.py::test_gadget_exists"), "api", NAME))
    plant(project, "gadget")
    ok(strap("red", NAME))
    implement(project, "gadget")
    (project / "widget.txt").unlink()
    err = refused(strap("freeze", NAME))
    assert has_problem(err, "B1: planned tests fail"), err
    write(project, "widget.txt", "widget\n")
    out = ok(strap("freeze", NAME))
    pattern = rf"^freeze \[done\] \| {NAME} \| [0-9a-f]{{12}} \| grader session \| was {frozen[:12]}\s*$"
    assert re.search(pattern, out, re.MULTILINE), out
    spec = read_spec(project)
    assert len(spec["rounds"]) == 1 and spec["frozen"] is not None
    assert {b["id"]: b["state"] for b in spec["behaviors"]} == {"B1": "green", "B2": "green"}
