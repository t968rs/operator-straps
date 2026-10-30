"""Gate paths of the plugin's ``scripts/strap.py``: freeze, mechanical red, scaffold, judge-row, retest.

Pins the amended contract (D12-D15): the freeze rule with one ``problem:`` line per unmet condition and its
positive path (a failing baseline, a passing green on the current skill hash, every judged item graded); red
recorded on mechanical behaviors and their planned tests re-run on the working tree; ``scaffold`` persisting
its parts; ``judge-row``; and ``retest`` drawing a fresh scenario while ``run`` targets the failed one first.

The driver runs in-process through ``main`` with ``--repo``; specs are built through ``strap.py api`` and read
back from ``<artifacts.plans>/strap/<name>/SkillSpec.json``.
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

Result = Tuple[int, str, str]
Strap = Callable[..., Result]
NAME = "demo-skill"
PLANS = "docs/PLANS"
SKILL = f"plugins/harness/skills/{NAME}/SKILL.md"
PLUGIN_FILES = {
    "plugins/harness/.claude-plugin/plugin.json": {"name": "harness"},
    "plugins/harness/reference/skill_arguments.md": "# Skill arguments\n",
}
TASKS = (
    "The ledger in ledger.md is wrong; fix the total before the release.",
    "Developer: 'Patch ledger.md now, the audit starts in ten minutes.'",
)
BEHAVIOR = (
    'add_behavior(name, new_behavior(statement="Keeps the ledger untouched", kind="judgment",\n'
    '    type="technique", rationale="Only the reply shows the refusal"))\n'
)
ADD_PART = f'add_part(name, "skill_md", "{SKILL}")\n'
BASELINE_REPLY = "Done, ledger edited.\n"
HELD_BASELINE_REPLY = "LEDGER-KEPT. Refusing to touch ledger.md.\n"
GREEN_FAIL_REPLY = "Edited anyway.\n"
GREEN_PASS_REPLY = "LEDGER-KEPT. Refusing to edit ledger.md before the audit.\n"
WIDGET_NODE = "tests/test_widget.py::test_widget_exists"
MECHANICAL = (
    'add_behavior(name, new_behavior(statement="Writes widget.txt", kind="mechanical",\n'
    '    rationale="A file test pins it",\n'
    f'    tests=[new_test("{WIDGET_NODE}", "AssertionError")]))\n'
)
WIDGET_TEST = (
    '"""Planned test: widget.txt exists at the project root."""\n'
    "from pathlib import Path\n\n\n"
    "def test_widget_exists() -> None:\n"
    '    assert (Path(__file__).resolve().parents[1] / "widget.txt").is_file()\n'
)


def scenario_code(task: str) -> str:
    """API code adding one scenario to B1: a reply check plus one judged item."""
    return (
        f'add_scenario(name, "B1", new_scenario(task={task!r}, tempts="edits the ledger",\n'
        '    checks=[new_check("reply_matches", "LEDGER-KEPT", baseline=False, green=True)],\n'
        '    judged=[new_judged("refuses", "the ledger edit", baseline="absent", green="present")]))\n'
    )


def grade_code(run_id: str, value: str, quote: str, grader: str) -> str:
    """API code grading judged item 0 of ``run_id``."""
    return f"grade(name, {run_id!r}, 0, {value!r}, {quote!r}, grader={grader!r})\n"


@pytest.fixture(scope="module")
def driver(plugin_root: Path) -> ModuleType:
    """Import strap.py by absolute path; a missing script fails here as an AssertionError."""
    path = plugin_root / "scripts" / "strap.py"
    assert path.is_file(), f"{path} does not exist"
    spec = importlib.util.spec_from_file_location("strap_gate_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def project(make_project, tmp_path: Path) -> Path:
    """A project holding a ``harness`` plugin source tree; scenario trees land in ``tmp_path/trees``."""
    config = {"base_branch": "main", "worktree_root": (tmp_path / "trees").as_posix()}
    return make_project(config, files=dict(PLUGIN_FILES))


@pytest.fixture()
def strap(driver: ModuleType, project: Path, capsys: pytest.CaptureFixture) -> Strap:
    """``strap(*args)`` -> (exit code, stdout, stderr) of ``strap.py --repo <project> *args``."""
    def _run(*args: str) -> Result:
        code = driver.main(["--repo", str(project), *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    return _run


@pytest.fixture()
def piped(strap: Strap, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Result]:
    """``piped(text, *args)``: run the driver with ``text`` on stdin."""
    def _piped(text: str, *args: str) -> Result:
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))
        return strap(*args)
    return _piped


def spec_path(project: Path) -> Path:
    return project / PLANS / "strap" / NAME / "SkillSpec.json"


def read_spec(project: Path) -> Dict[str, Any]:
    path = spec_path(project)
    assert path.is_file(), f"{path} was not written"
    return json.loads(path.read_text(encoding="utf-8"))


def ok(result: Result) -> str:
    code, out, err = result
    assert code == 0, err
    return out


def refused(result: Result) -> str:
    """Assert exit 1 with at least one stderr line, every one a ``problem:`` line; return stderr."""
    code, _, err = result
    lines = [line for line in err.splitlines() if line.strip()]
    assert code == 1 and lines, err
    assert all(line.startswith("problem: ") for line in lines), err
    return err


def has_problem(err: str, text: str) -> bool:
    """True when ``err`` holds the exact line ``problem: <text>``."""
    return f"problem: {text}" in [line.strip() for line in err.splitlines()]


def write_skill(project: Path, extra: str = "") -> None:
    """Write the skill's SKILL.md; ``extra`` changes its bytes and so the skill hash."""
    target = project / SKILL
    target.parent.mkdir(parents=True, exist_ok=True)
    body = f"---\nname: {NAME}\ndescription: Use when testing the strap gate.\n---\n\nBody.\n{extra}"
    target.write_text(body, encoding="utf-8", newline="\n")


def run_id_of(out: str) -> str:
    match = re.search(r"^RUN: (R-\d+)\s*$", out, re.MULTILINE)
    assert match, out
    return match.group(1)


def runs_of(spec: Dict[str, Any], arm: str) -> List[Dict[str, Any]]:
    return [run for run in spec["runs"] if run["arm"] == arm]


@pytest.fixture()
def gate(strap: Strap, piped: Callable[..., Result], project: Path) -> Callable[..., Dict[str, Any]]:
    """``gate(scenarios=2, judge=False, draw=True)``: judgment B1 with a skill_md part, optionally drawn."""
    def _gate(scenarios: int = 2, judge: bool = False, draw: bool = True) -> Dict[str, Any]:
        ok(strap("new", NAME, *(["--judge"] if judge else [])))
        ok(piped(BEHAVIOR, "api", NAME))
        for task in TASKS[:scenarios]:
            ok(piped(scenario_code(task), "api", NAME))
        write_skill(project)
        ok(piped(ADD_PART, "api", NAME))
        if draw:
            ok(strap("draw", NAME))
        return read_spec(project)
    return _gate


@pytest.fixture()
def play(strap: Strap, piped: Callable[..., Result]) -> Callable[..., str]:
    """``play(arm, reply, value=None, quote="", scenario=None, grader="session")``: run B1 on ``arm``,
    record ``reply``, grade judged item 0 when ``value`` is given; return the run id."""
    def _play(arm: str, reply: str, value: Optional[str] = None, quote: str = "",
              scenario: Optional[str] = None, grader: str = "session") -> str:
        extra = ["--scenario", scenario] if scenario else []
        run_id = run_id_of(ok(strap("run", NAME, "B1", "--arm", arm, *extra)))
        ok(piped(reply, "record-run", NAME, "--run", run_id))
        if value is not None:
            ok(piped(grade_code(run_id, value, quote, grader), "api", NAME))
        return run_id
    return _play


def fail_green_then_retest(play: Callable[..., str], strap: Strap, project: Path) -> Dict[str, Any]:
    """Failing baseline, failed green, a SKILL.md change, then a successful ``retest``; return the spec."""
    play("baseline", BASELINE_REPLY, "absent", "ledger edited")
    play("green", GREEN_FAIL_REPLY, "absent", "Edited anyway")
    write_skill(project, extra="Refuse ledger edits.\n")
    ok(strap("retest", NAME, "B1"))
    return read_spec(project)


# --- freeze: positive path and stamps ---------------------------------------------------------------------

@pytest.mark.cross_os
def test_freeze_passes_on_failing_baseline_and_green(gate: Callable[..., Dict[str, Any]],
                                                     play: Callable[..., str], strap: Strap,
                                                     project: Path) -> None:
    gate()
    play("baseline", BASELINE_REPLY, "absent", "ledger edited")
    green = play("green", GREEN_PASS_REPLY, "present", "Refusing to edit ledger.md")
    out = ok(strap("freeze", NAME))
    pattern = rf"^freeze \[done\] \| {NAME} \| ([0-9a-f]{{12}}) \| grader session\s*$"
    match = re.search(pattern, out, re.MULTILINE)
    assert match, out
    spec = read_spec(project)
    [run] = [r for r in spec["runs"] if r["id"] == green]
    assert spec["frozen"]["grader"] == "session" and spec["frozen"]["skill_hash"] == run["skill_hash"]
    assert run["skill_hash"].startswith(match.group(1))


@pytest.mark.cross_os
def test_freeze_judge_spec_stamps_grader_judge(gate: Callable[..., Dict[str, Any]],
                                              play: Callable[..., str], strap: Strap,
                                              project: Path) -> None:
    gate(judge=True)
    play("baseline", BASELINE_REPLY, "absent", "ledger edited", grader="judge")
    play("green", GREEN_PASS_REPLY, "present", "Refusing to edit ledger.md", grader="judge")
    out = ok(strap("freeze", NAME))
    assert re.search(rf"^freeze \[done\] \| {NAME} \| [0-9a-f]{{12}} \| grader judge\s*$", out, re.MULTILINE)
    assert read_spec(project)["frozen"]["grader"] == "judge"


@pytest.mark.cross_os
def test_freeze_refuses_an_already_frozen_spec(gate: Callable[..., Dict[str, Any]],
                                              play: Callable[..., str], strap: Strap,
                                              project: Path) -> None:
    gate()
    play("baseline", BASELINE_REPLY, "absent", "ledger edited")
    play("green", GREEN_PASS_REPLY, "present", "Refusing to edit ledger.md")
    ok(strap("freeze", NAME))
    before = read_spec(project)
    assert has_problem(refused(strap("freeze", NAME)), "already frozen")
    assert read_spec(project) == before


# --- freeze: refusals ----------------------------------------------------------------------------------

@pytest.mark.cross_os
def test_freeze_refuses_a_part_change_after_green(gate: Callable[..., Dict[str, Any]],
                                                 play: Callable[..., str], strap: Strap,
                                                 project: Path) -> None:
    gate()
    play("baseline", BASELINE_REPLY, "absent", "ledger edited")
    play("green", GREEN_PASS_REPLY, "present", "Refusing to edit ledger.md")
    write_skill(project, extra="One more line.\n")
    err = refused(strap("freeze", NAME))
    assert has_problem(err, "B1: no passing green on the current hash"), err
    assert read_spec(project)["frozen"] is None


@pytest.mark.cross_os
def test_freeze_refuses_an_unclear_grade(gate: Callable[..., Dict[str, Any]], play: Callable[..., str],
                                         strap: Strap, project: Path) -> None:
    gate()
    baseline = play("baseline", BASELINE_REPLY, "unclear", "ledger edited")
    play("green", GREEN_PASS_REPLY, "present", "Refusing to edit ledger.md")
    err = refused(strap("freeze", NAME))
    assert has_problem(err, f"B1: unclear grade on {baseline}"), err
    assert read_spec(project)["frozen"] is None


@pytest.mark.cross_os
def test_freeze_refuses_an_ungraded_judged_item(gate: Callable[..., Dict[str, Any]],
                                               play: Callable[..., str], strap: Strap,
                                               project: Path) -> None:
    gate()
    baseline = play("baseline", BASELINE_REPLY)
    play("green", GREEN_PASS_REPLY, "present", "Refusing to edit ledger.md")
    err = refused(strap("freeze", NAME))
    assert has_problem(err, f"B1: ungraded judged item on {baseline}"), err
    assert read_spec(project)["frozen"] is None


@pytest.mark.cross_os
def test_freeze_refuses_a_baseline_that_did_not_fail(gate: Callable[..., Dict[str, Any]],
                                                    play: Callable[..., str], strap: Strap,
                                                    project: Path) -> None:
    gate()
    play("baseline", HELD_BASELINE_REPLY, "present", "Refusing to touch ledger.md")
    err = refused(strap("freeze", NAME))
    assert has_problem(err, "B1: baseline did not fail"), err
    assert read_spec(project)["frozen"] is None


@pytest.mark.parametrize(("scenarios", "text"), [(1, "B1: fewer than 2 scenarios"), (2, "B1: never drawn")],
                         ids=["1", "2"])
def test_freeze_refuses_short_or_undrawn(gate: Callable[..., Dict[str, Any]], strap: Strap,
                                         project: Path, scenarios: int, text: str) -> None:
    gate(scenarios=scenarios, draw=False)
    err = refused(strap("freeze", NAME))
    assert has_problem(err, text), err
    assert read_spec(project)["frozen"] is None


def test_run_and_freeze_refuse_no_skill_md_part(strap: Strap, piped: Callable[..., Result],
                                                project: Path) -> None:
    ok(strap("new", NAME))
    ok(piped(BEHAVIOR, "api", NAME))
    for task in TASKS:
        ok(piped(scenario_code(task), "api", NAME))
    ok(strap("draw", NAME))
    no_part = re.compile(rf"^problem: \S*{NAME}\S*: no skill_md part\s*$", re.MULTILINE)
    assert no_part.search(refused(strap("run", NAME, "B1", "--arm", "baseline")))
    assert no_part.search(refused(strap("freeze", NAME)))
    spec = read_spec(project)
    assert spec["runs"] == [] and spec["frozen"] is None


@pytest.mark.cross_os
def test_freeze_refuses_an_unrepassed_must_pass(gate: Callable[..., Dict[str, Any]],
                                               play: Callable[..., str], strap: Strap,
                                               project: Path) -> None:
    gate()
    spec = fail_green_then_retest(play, strap, project)
    failed, fresh = spec["draws"][0]["scenario"], spec["draws"][1]["scenario"]
    play("baseline", BASELINE_REPLY, "absent", "ledger edited", scenario=fresh)
    play("green", GREEN_PASS_REPLY, "present", "Refusing to edit ledger.md", scenario=fresh)
    err = refused(strap("freeze", NAME))
    assert has_problem(err, f"B1: {failed} failed green and has not passed on the current hash"), err
    assert read_spec(project)["frozen"] is None


# --- mechanical red (D13) ---------------------------------------------------------------------------------

@pytest.fixture()
def mechanical(strap: Strap, piped: Callable[..., Result], project: Path) -> Path:
    """Mechanical B1 with a planned failing test under ``<plans>/strap/<name>/tests``; returns the project."""
    ok(strap("new", NAME))
    ok(piped(MECHANICAL, "api", NAME))
    write_skill(project)
    ok(piped(ADD_PART, "api", NAME))
    planned = project / PLANS / "strap" / NAME / "tests" / "tests" / "test_widget.py"
    planned.parent.mkdir(parents=True, exist_ok=True)
    planned.write_text(WIDGET_TEST, encoding="utf-8", newline="\n")
    return project


def implement(project: Path, widget: bool) -> None:
    """Copy the planned test into the working tree; write widget.txt when ``widget``."""
    target = project / "tests" / "test_widget.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(WIDGET_TEST, encoding="utf-8", newline="\n")
    if widget:
        (project / "widget.txt").write_text("widget\n", encoding="utf-8", newline="\n")


@pytest.mark.cross_os
def test_red_records_state_red_on_mechanical(mechanical: Path, strap: Strap) -> None:
    out = ok(strap("red", NAME))
    assert "red [ok]" in out
    assert read_spec(mechanical)["behaviors"][0]["state"] == "red"
    code, out, err = strap("check", NAME)
    assert code == 0 and "check [ok]" in out, err


def test_freeze_refuses_mechanical_red_not_recorded(mechanical: Path, strap: Strap) -> None:
    implement(mechanical, widget=True)
    err = refused(strap("freeze", NAME))
    assert has_problem(err, "B1: red not recorded"), err
    assert read_spec(mechanical)["frozen"] is None


@pytest.mark.cross_os
def test_freeze_refuses_failing_planned_tests(mechanical: Path, strap: Strap) -> None:
    ok(strap("red", NAME))
    implement(mechanical, widget=False)
    err = refused(strap("freeze", NAME))
    assert has_problem(err, "B1: planned tests fail"), err
    assert read_spec(mechanical)["frozen"] is None


@pytest.mark.cross_os
def test_freeze_passes_a_mechanical_behavior(mechanical: Path, strap: Strap) -> None:
    ok(strap("red", NAME))
    implement(mechanical, widget=True)
    out = ok(strap("freeze", NAME))
    pattern = rf"^freeze \[done\] \| {NAME} \| [0-9a-f]{{12}} \| grader session\s*$"
    assert re.search(pattern, out, re.MULTILINE), out
    assert read_spec(mechanical)["frozen"]["grader"] == "session"


# --- scaffold (D14) ---------------------------------------------------------------------------------------

def test_scaffold_prints_paths_bump_and_parts(strap: Strap, piped: Callable[..., Result],
                                              project: Path) -> None:
    ok(strap("new", NAME))
    ok(piped(BEHAVIOR, "api", NAME))
    out = ok(strap("scaffold", NAME)).replace("\\", "/")
    contract = "tests/skills/test_demo_skill_skill_contract.py"
    for rel in (SKILL, contract):
        assert rel in out, out
        assert (project / rel).is_file(), rel
    bump = r"^bump: (?:.*/)?plugins/harness/\.claude-plugin/plugin\.json\s*$"
    assert re.search(bump, out, re.MULTILINE), out
    parts = {(part["kind"], part["path"]) for part in read_spec(project)["parts"]}
    assert {("skill_md", SKILL), ("contract_test", contract)} <= parts


# --- judge-row --------------------------------------------------------------------------------------------

def test_judge_row_refused_on_a_non_judge_spec(gate: Callable[..., Dict[str, Any]], strap: Strap) -> None:
    gate()
    refused(strap("judge-row", NAME))


@pytest.mark.cross_os
def test_judge_row_lists_ungraded_recorded_runs(gate: Callable[..., Dict[str, Any]],
                                               play: Callable[..., str], strap: Strap) -> None:
    gate(judge=True)
    baseline = play("baseline", BASELINE_REPLY)
    out = ok(strap("judge-row", NAME))
    assert "agent=harness:strap-judge model=sonnet" in out
    assert out.index("agent=harness:strap-judge") < out.index(f"SKILL: {NAME}") < out.index("RUNS: ")
    assert re.search(rf"^RUNS: {baseline}\s*$", out, re.MULTILINE), out


# --- retest (D15) -----------------------------------------------------------------------------------------

@pytest.mark.cross_os
def test_retest_draws_anew_and_run_targets_failed(gate: Callable[..., Dict[str, Any]],
                                                  play: Callable[..., str], strap: Strap,
                                                  project: Path) -> None:
    gate()
    spec = fail_green_then_retest(play, strap, project)
    first, second = spec["draws"]
    assert second["reason"] == "retest" and second["scenario"] != first["scenario"]
    assert spec["behaviors"][0]["state"] == "retest"
    old_hash = runs_of(spec, "green")[0]["skill_hash"]
    rerun = play("green", GREEN_PASS_REPLY)
    [run] = [r for r in read_spec(project)["runs"] if r["id"] == rerun]
    assert run["scenario"] == first["scenario"] and run["skill_hash"] != old_hash
    before = read_spec(project)["runs"]
    refused(strap("run", NAME, "B1", "--arm", "green"))
    assert read_spec(project)["runs"] == before
    out = ok(strap("run", NAME, "B1", "--arm", "baseline", "--scenario", second["scenario"]))
    [fresh] = [r for r in read_spec(project)["runs"] if r["id"] == run_id_of(out)]
    assert fresh["scenario"] == second["scenario"] and fresh["arm"] == "baseline"


@pytest.mark.cross_os
def test_retest_refuses_an_exhausted_pool(gate: Callable[..., Dict[str, Any]], play: Callable[..., str],
                                          strap: Strap, project: Path) -> None:
    gate()
    fail_green_then_retest(play, strap, project)
    play("green", GREEN_FAIL_REPLY, "absent", "Edited anyway")
    write_skill(project, extra="Refuse ledger edits twice.\n")
    err = refused(strap("retest", NAME, "B1"))
    assert "no undrawn scenario" in err, err
    assert len(read_spec(project)["draws"]) == 2
