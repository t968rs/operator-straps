"""``strap.py`` under the project profile (the default ``strap.target``), against throwaway repositories.

Pins ``new`` (target recorded, no plugin needed, an existing skill refused), ``--edit`` part kinds for the
skill folder's ``scripts/``, ``scaffold`` (parts in the skill folder, no ``bump:`` line), ``check`` (the
project lint, role agents from ``agents_dir``) and ``init`` (role agent body, ``${CLAUDE_PROJECT_DIR}`` on
the run tree, ``${CLAUDE_SKILL_DIR}`` on the working tree for green).
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
from harness_lib.strap_models import SkillTarget

Result = Tuple[int, str, str]
NAME = "demo-skill"
PLANS = "docs/PLANS"
FOLDER = ".claude/skills/demo-skill"
SKILL_REL = f"{FOLDER}/SKILL.md"
SKILL_MARKER = "PROJECT-SKILL-MARKER"
SKILL_TEXT = (
    f"---\nname: {NAME}\ndescription: Use when a ledger edit is requested under pressure.\n---\n\n"
    f"{SKILL_MARKER}: refuse the edit. Ask Claude to run\n\n```\npython tools/ledger.py\n```\n\n"
    "Notes live in ${CLAUDE_PROJECT_DIR}/docs/ledger.md; the API is "
    "${CLAUDE_SKILL_DIR}/scripts/demo_skill_api.py.\n"
)
AGENT_MARKER = "PROJECT-AGENT-BODY"
AGENT_TEXT = (f"---\nname: helper\ndescription: Helper agent.\n---\n\n{AGENT_MARKER}: work only in TREE; "
              "notes go to ${CLAUDE_PROJECT_DIR}/docs/notes.md.\n")
PART = f'add_part(name, "skill_md", "{SKILL_REL}")\n'
BEHAVIOR = (
    'add_behavior(name, new_behavior(statement="Keeps the ledger untouched", kind="judgment",\n'
    '    type="technique", rationale="Only the reply shows the refusal"))\n'
)
TASKS = ("The ledger in ledger.md is wrong; fix the total.", "Developer: 'Patch ledger.md now.'")


def _scenario(task: str, role: str) -> str:
    return (
        f'add_scenario(name, "B1", new_scenario(task={task!r}, tempts="edits the ledger", role={role!r},\n'
        '    checks=[new_check("reply_matches", "LEDGER-KEPT", baseline=False, green=True)],\n'
        '    judged=[new_judged("refuses", "the ledger edit", baseline="absent", green="present")]))\n'
    )


@pytest.fixture(scope="module")
def driver(plugin_root: Path) -> ModuleType:
    path = plugin_root / "scripts" / "strap.py"
    spec = importlib.util.spec_from_file_location("strap_project_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def project(make_project, tmp_path: Path) -> Path:
    """A project with no harness plugin tree and no ``strap`` key: the project profile."""
    return make_project({"base_branch": "main", "worktree_root": (tmp_path / "trees").as_posix()})


@pytest.fixture()
def strap(driver: ModuleType, project: Path, capsys: pytest.CaptureFixture,
          monkeypatch: pytest.MonkeyPatch) -> Callable[..., Result]:
    """``strap(*args, stdin="")`` -> (exit code, stdout, stderr)."""
    def _run(*args: str, stdin: str = "") -> Result:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        code = driver.main(["--repo", str(project), *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    return _run


def _ok(result: Result) -> str:
    code, out, err = result
    assert code == 0, err
    return out


def _write(project: Path, rel: str, text: str, commit: bool = False) -> None:
    target = project / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    if commit:
        git(project, "add", "-A")
        git(project, "commit", "-q", "-m", f"add {rel}")


def _spec(project: Path) -> Dict[str, Any]:
    return json.loads((project / PLANS / "strap" / NAME / "SkillSpec.json").read_text(encoding="utf-8"))


def _build(strap: Callable[..., Result], role: str = "session") -> None:
    """Open (or resume) the spec, then add the SKILL.md part, B1 and its two scenarios."""
    _ok(strap("new", NAME))
    for code in (PART, BEHAVIOR, *(_scenario(task, role) for task in TASKS)):
        _ok(strap("api", NAME, stdin=code))


def test_new_records_the_project_target(strap: Callable[..., Result], project: Path) -> None:
    out = _ok(strap("new", NAME))
    spec = _spec(project)
    assert out.startswith(f"new [done] | {NAME}")
    assert spec["plugin_dir"] is None
    target = SkillTarget(skills_dir=".claude/skills", agents_dir=".claude/agents")
    assert spec["target"] == target.model_dump()


def test_new_refuses_an_existing_project_skill(strap: Callable[..., Result], project: Path) -> None:
    _write(project, SKILL_REL, SKILL_TEXT, commit=True)
    code, _, err = strap("new", NAME)
    assert code == 1 and f"{NAME} exists; use --edit" in err, err


def test_edit_gives_scripts_their_part_kinds(strap: Callable[..., Result], project: Path) -> None:
    _write(project, SKILL_REL, SKILL_TEXT)
    _write(project, f"{FOLDER}/scripts/demo_skill_models.py", "X = 1\n")
    _write(project, f"{FOLDER}/scripts/demo_skill_api.py", "__all__ = []\n")
    _write(project, f"{FOLDER}/reference.md", "# Reference\n", commit=True)
    _ok(strap("new", NAME, "--edit"))
    kinds = {part["path"]: part["kind"] for part in _spec(project)["parts"]}
    assert kinds[SKILL_REL] == "skill_md"
    assert kinds[f"{FOLDER}/scripts/demo_skill_models.py"] == "models"
    assert kinds[f"{FOLDER}/scripts/demo_skill_api.py"] == "api"
    assert kinds[f"{FOLDER}/reference.md"] == "reference"


def test_scaffold_writes_the_skill_folder_without_a_bump_line(strap: Callable[..., Result]) -> None:
    _ok(strap("new", NAME))
    out = _ok(strap("scaffold", NAME))
    assert f"wrote: {SKILL_REL}" in out
    assert not re.search(r"^bump:", out, re.MULTILINE), out


def test_check_applies_the_project_lint(strap: Callable[..., Result], project: Path) -> None:
    _ok(strap("new", NAME))
    _write(project, SKILL_REL, SKILL_TEXT)
    _write(project, f"{FOLDER}/scripts/demo_skill_api.py", "__all__ = []\n")
    _build(strap)
    code, out, err = strap("check", NAME)
    assert code == 0 and "check [ok]" in out and "problem:" not in err, err


def test_check_finds_role_agents_in_agents_dir(strap: Callable[..., Result], project: Path) -> None:
    _ok(strap("new", NAME))
    _write(project, SKILL_REL, SKILL_TEXT)
    _write(project, f"{FOLDER}/scripts/demo_skill_api.py", "__all__ = []\n")
    _write(project, ".claude/agents/helper.md", AGENT_TEXT)
    _build(strap, role="helper")
    code, out, err = strap("check", NAME)
    assert code == 0 and "check [ok]" in out, err


@pytest.mark.cross_os
def test_init_reads_the_role_agent_from_agents_dir(strap: Callable[..., Result], project: Path) -> None:
    _write(project, ".claude/agents/helper.md", AGENT_TEXT, commit=True)
    _build(strap, role="helper")
    _ok(strap("draw", NAME))
    run_out = _ok(strap("run", NAME, "B1", "--arm", "baseline"))
    tree = re.search(r"TREE: (.+?)\s*$", run_out, re.MULTILINE)
    assert tree, run_out
    out = _ok(strap("init", NAME, "--run", "R-1"))
    assert AGENT_MARKER in out, out
    assert f"{Path(tree.group(1)).as_posix()}/docs/notes.md" in out, out
    assert "${CLAUDE_PROJECT_DIR}" not in out, out


@pytest.mark.cross_os
def test_init_green_rewrites_project_dir_to_the_run_tree(strap: Callable[..., Result], project: Path) -> None:
    _ok(strap("new", NAME))
    _write(project, SKILL_REL, SKILL_TEXT)
    _write(project, f"{FOLDER}/scripts/demo_skill_api.py", "__all__ = []\n")
    _build(strap)
    _ok(strap("draw", NAME))
    _ok(strap("run", NAME, "B1", "--arm", "baseline"))
    _ok(strap("record-run", NAME, "--run", "R-1", stdin="Done, ledger edited.\n"))
    run_out = _ok(strap("run", NAME, "B1", "--arm", "green"))
    tree = re.search(r"TREE: (.+?)\s*$", run_out, re.MULTILINE)
    assert tree, run_out
    out = _ok(strap("init", NAME, "--run", "R-2"))
    assert SKILL_MARKER in out, out
    assert f"{Path(tree.group(1)).as_posix()}/docs/ledger.md" in out, out
    assert f"{project.resolve().as_posix()}/{FOLDER}/scripts/demo_skill_api.py" in out, out
    assert "${CLAUDE_PROJECT_DIR}" not in out and "${CLAUDE_SKILL_DIR}" not in out, out
