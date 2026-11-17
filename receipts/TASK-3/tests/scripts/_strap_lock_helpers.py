"""Fixtures and helpers shared by ``test_strap_lock.py`` and ``test_strap_relink_lock.py``.

The ``driver`` fixture loads ``strap.py``, ``strap`` runs it in-process through ``main`` with ``--repo``,
``prepared`` builds a new-mode spec whose mechanical B1 is red, implemented and committed, and ``frozen``
freezes it. A test module imports the fixtures by name to use them.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Tuple

import pytest
from conftest import git

Result = Tuple[int, str, str]
Strap = Callable[..., Result]
NAME = "demo-skill"
STEM = f"skill/{NAME}"
PLANS = "docs/PLANS"
SKILL = f"plugins/harness/skills/{NAME}/SKILL.md"
SPEC_REL = f"{PLANS}/strap/{NAME}/SkillSpec.json"
PLANNED_TEST = f"{PLANS}/strap/{NAME}/tests/tests/test_widget.py"
PLUGIN_FILES = {
    "plugins/harness/.claude-plugin/plugin.json": {"name": "harness"},
    "plugins/harness/reference/skill_arguments.md": "# Skill arguments\n",
}
ADD_PART = f'add_part(name, "skill_md", "{SKILL}")\n'
LOCKED = f"{NAME} is locked"


def _mechanical_code(statement: str, node: str) -> str:
    return (f'add_behavior(name, new_behavior(statement="{statement}", kind="mechanical",\n'
            f'    rationale="A file test pins it", tests=[new_test("{node}", "AssertionError")]))\n')


def _file_test(stem: str) -> str:
    return (f'"""Planned test: {stem}.txt exists at the project root."""\n'
            "from pathlib import Path\n\n\n"
            f"def test_{stem}_exists() -> None:\n"
            f'    assert (Path(__file__).resolve().parents[1] / "{stem}.txt").is_file()\n')


def skill_text(body: str) -> str:
    return f"---\nname: {NAME}\ndescription: Use when testing the lock.\n---\n\n{body}\n"


@pytest.fixture(scope="module")
def driver(plugin_root: Path) -> ModuleType:
    path = plugin_root / "scripts" / "strap.py"
    assert path.is_file(), f"{path} does not exist"
    spec = importlib.util.spec_from_file_location("strap_lock_under_test", path)
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


def read_spec(project: Path) -> Dict[str, Any]:
    return json.loads((project / SPEC_REL).read_text(encoding="utf-8"))


def ok(result: Result) -> str:
    code, out, err = result
    assert code == 0, err
    return out


def refused(result: Result) -> str:
    code, _, err = result
    lines = [line for line in err.splitlines() if line.strip()]
    assert code == 1 and lines and all(line.startswith("problem: ") for line in lines), err
    return err


def write(project: Path, rel: str, text: str) -> None:
    target = project / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def commit_all(project: Path) -> str:
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "work")
    return git(project, "rev-parse", "HEAD")


def peeled(project: Path, tag: str, kind: str) -> str:
    """The object ``tag`` peels to, as ``git rev-parse '<tag>^{<kind>}'``."""
    return git(project, "rev-parse", f"{tag}^{{{kind}}}")


def kind_of(entry: Any) -> str:
    return getattr(entry.kind, "value", entry.kind)


def ledger_folder(fl: ModuleType, project: Path) -> Path:
    return fl.ledger_dir(project / PLANS, fl.skill_stem(NAME))


def entries(fl: ModuleType, project: Path) -> List[Any]:
    return list(fl.load_entries(ledger_folder(fl, project)))


@pytest.fixture()
def prepared(strap: Strap, piped: Callable[..., Result], project: Path) -> Path:
    """A new-mode spec with mechanical B1 (widget) red, implemented and committed, not yet frozen."""
    ok(strap("new", NAME))
    ok(piped(_mechanical_code("Writes widget.txt", "tests/test_widget.py::test_widget_exists"), "api", NAME))
    write(project, SKILL, skill_text("Body."))
    ok(piped(ADD_PART, "api", NAME))
    write(project, PLANNED_TEST, _file_test("widget"))
    ok(strap("red", NAME))
    write(project, "tests/test_widget.py", _file_test("widget"))
    write(project, "widget.txt", "widget\n")
    commit_all(project)
    return project


@pytest.fixture()
def frozen(prepared: Path, strap: Strap) -> str:
    """``prepared`` frozen with the freeze committed; returns the frozen hash."""
    ok(strap("freeze", NAME))
    commit_all(prepared)
    return read_spec(prepared)["frozen"]["skill_hash"]
