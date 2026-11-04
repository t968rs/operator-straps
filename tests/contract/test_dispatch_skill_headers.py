"""Every harness dispatch names its skill in the first header line (issue #193, plan 0006 D2, D4, D6).

agent-watcher reads ``SKILL:`` from the leading header block of an Agent prompt as the dispatching skill. The
row-printing drivers and the prompts written in skill prose put ``SKILL: <skill>`` first, right after the
``agent=`` line. strap names the skill under test ``TARGET:`` (its old ``SKILL:`` line), and both strap agents
read ``TARGET``. strap's ``record-run`` and the judge's reply end in the column-1 ``---`` return block.
Mixed-case prompt keys stay as they are (D4).
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

from conftest import PLUGIN_ROOT
from harness_lib.writing_docstrings_models import DispatchRow, FileScope

SCRIPTS = PLUGIN_ROOT / "scripts"
AGENTS = PLUGIN_ROOT / "agents"
SKILLS = PLUGIN_ROOT / "skills"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"{name}_headers_under_test", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_strap_runner_row_names_strap_skills_then_the_target() -> None:
    lines = _load("strap").runner_lines("retry-policy", "R-1", "/w/tree", "INIT_CMD")
    assert lines[0] == "agent=harness:strap-scenario-runner model=sonnet"
    assert lines[1:5] == ["SKILL: strap-skills", "TARGET: retry-policy", "RUN: R-1", "TREE: /w/tree"]
    assert lines[5] == "INIT: INIT_CMD"


def test_strap_judge_row_names_strap_skills_then_the_target() -> None:
    lines = _load("strap").judge_lines("retry-policy", ["R-1", "R-2"], "docs/strap/retry-policy.json")
    assert lines == ["agent=harness:strap-judge model=sonnet", "SKILL: strap-skills", "TARGET: retry-policy",
                     "RUNS: R-1,R-2", "SPEC: docs/strap/retry-policy.json"]


def test_strap_record_run_prints_a_dash_fenced_block() -> None:
    block = _load("strap").recorded_block("retry-policy", "R-1")
    assert block.splitlines() == ["---", "SIGNAL: recorded", "RUN: R-1", "TARGET: retry-policy", "---"]


def test_bubble_memo_rows_name_bubble_memo_first() -> None:
    header = _load("bubble_memo").row_header("harness:bubble-memo-reviewer", "sonnet")
    assert header == ["agent=harness:bubble-memo-reviewer model=sonnet", "SKILL: bubble-memo"]


def test_docstring_rows_name_writing_docstrings_first() -> None:
    scopes = [FileScope(path="/p/a.py")]
    row = DispatchRow(model="opus", project_root="/p", new_docstrings=False, scopes=scopes)
    lines = row.text().splitlines()
    assert lines[1] == "SKILL: writing-docstrings"
    assert lines[2] == "Project root: /p"


def _prompt_block(skill: str) -> list:
    text = _text(SKILLS / skill / "SKILL.md")
    blocks = re.findall(r"```[^\n]*\n(.*?)\n```", text, re.DOTALL)
    hits = [b.splitlines() for b in blocks if "Project root:" in b]
    assert hits, f"{skill}: no prompt block"
    return hits[0]


def test_skill_prose_prompts_name_their_skill_first() -> None:
    for skill in ("todo-edit", "sync-gh-todo", "check-runlogs"):
        assert _prompt_block(skill)[0] == f"SKILL: {skill}", skill
    assert _prompt_block("todo-edit")[1].startswith("Operation: ")


def test_strap_agents_read_the_target_line() -> None:
    runner, judge = _text(AGENTS / "strap-scenario-runner.md"), _text(AGENTS / "strap-judge.md")
    assert "record-run <TARGET> --run <RUN>" in runner and "init <TARGET> --run <RUN>" in runner
    assert "The prompt has no `TARGET`, `RUN` or `TREE` line." in runner
    assert "api <TARGET>" in judge and "The prompt has no `TARGET`, `RUNS` or `SPEC` line." in judge


def test_the_judge_reply_ends_in_a_dash_fenced_block() -> None:
    reply = _text(AGENTS / "strap-judge.md").split("## Reply", 1)[1]
    assert re.search(r"^---\nSIGNAL: graded\nRUNS: <run ids>\n---$", reply, re.MULTILINE), reply
