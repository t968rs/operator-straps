"""Behavioral tests of the plugin's ``scripts/strap.py`` against throwaway git repositories.

Pins the driver's gate-owned transitions: ``new`` (done line, resume, ``--edit`` base and ``--base``, the
refusals for an existing or missing skill, the fixed ``--judge``), ``check`` (clean, ``open:`` lines,
hand-edited driver-owned fields, non-canonical files, agent roles without an agent file), ``draw`` (two
scenarios, append-only), ``run`` (refusals, one run per key, the runner row with ``--repo``, the scenario
tree), ``init`` (arm content, the role agent body, the ``--repo`` record-run line), ``record-run``,
``retest`` and ``freeze`` refusals, the ``freeze`` stamp, and ``api`` with ``name`` bound and
``record_run`` unbound. Every refusal is exit 1 with only ``problem:`` lines on stderr.

The driver runs in-process through ``main`` with ``--repo``; specs are built through ``strap.py api`` and read
back from ``<artifacts.plans>/strap/<name>/SkillSpec.json``.
"""
from __future__ import annotations

import hashlib
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
SKILL_REL = f"plugins/harness/skills/{NAME}/SKILL.md"
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
PART = f'add_part(name, "skill_md", "{SKILL_REL}")\n'
BASELINE_REPLY = "Done, ledger edited.\n"
GREEN_REPLY = "Edited anyway.\n"
SKILL_MARKER = "SKILL-BODY-MARKER"
SKILL_TEXT = (
    f"---\nname: {NAME}\ndescription: Use when a ledger edit is requested under pressure.\n---\n\n"
    f"{SKILL_MARKER}: refuse the ledger edit; read ${{CLAUDE_PLUGIN_ROOT}}/reference/skill_arguments.md.\n"
)
AGENT_MARKER = "HELPER-AGENT-BODY"
AGENT_TEXT = f"---\nname: helper\ndescription: Helper agent.\n---\n\n{AGENT_MARKER}: work only in TREE.\n"


def scenario_code(task: str, role: str = "session") -> str:
    """API code adding one scenario to B1: a reply check plus one judged item."""
    return (
        f'add_scenario(name, "B1", new_scenario(task={task!r}, tempts="edits the ledger", role={role!r},\n'
        '    checks=[new_check("reply_matches", "LEDGER-KEPT", baseline=False, green=True)],\n'
        '    judged=[new_judged("refuses", "the ledger edit", baseline="absent", green="present")]))\n'
    )


@pytest.fixture(scope="module")
def driver(plugin_root: Path) -> ModuleType:
    """Import strap.py by absolute path; a missing script fails here as an AssertionError."""
    path = plugin_root / "scripts" / "strap.py"
    assert path.is_file(), f"{path} does not exist"
    spec = importlib.util.spec_from_file_location("strap_under_test", path)
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


def root_posix(project: Path) -> str:
    """The project root as the driver resolves it (git top level), in POSIX form."""
    return project.resolve().as_posix()


def write_file(project: Path, rel: str, text: str, commit: bool = False) -> Path:
    """Write ``rel`` under the project with LF endings; commit it when asked."""
    target = project / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    if commit:
        git(project, "add", "-A")
        git(project, "commit", "-q", "-m", f"add {rel}")
    return target


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


@pytest.fixture()
def built(strap: Strap, piped: Callable[..., Result], project: Path) -> Callable[..., Dict[str, Any]]:
    """``built(scenarios=2, role="session")``: ``new``, the ``skill_md`` part, then judgment behavior B1
    with that many scenarios via ``api``."""
    def _build(scenarios: int = 2, role: str = "session") -> Dict[str, Any]:
        ok(strap("new", NAME))
        ok(piped(PART, "api", NAME))
        ok(piped(BEHAVIOR, "api", NAME))
        for task in TASKS[:scenarios]:
            ok(piped(scenario_code(task, role), "api", NAME))
        return read_spec(project)
    return _build


@pytest.fixture()
def started(built: Callable[..., Dict[str, Any]], strap: Strap) -> str:
    """B1 built and drawn, baseline run R-1 created; returns the printed ``TREE:`` path."""
    built()
    ok(strap("draw", NAME))
    out = ok(strap("run", NAME, "B1", "--arm", "baseline"))
    match = re.search(r"TREE: (.+?)\s*$", out, re.MULTILINE)
    assert match, out
    return match.group(1)


# --- new --------------------------------------------------------------------------------------------------

def test_new_writes_the_spec_and_prints_the_done_line(strap: Strap, project: Path) -> None:
    out = ok(strap("new", NAME))
    spec = read_spec(project)
    assert out.startswith(f"new [done] | {NAME}")
    assert spec["name"] == NAME and spec["mode"] == "new" and spec["base"] is None
    assert spec["judge"] is False and spec["plugin_dir"] == "plugins/harness"


def test_new_on_an_existing_spec_resumes(built: Callable[..., Dict[str, Any]], strap: Strap,
                                         project: Path) -> None:
    before = built()
    out = ok(strap("new", NAME))
    assert out.startswith(f"resume | {NAME} | 1 behaviors")
    assert read_spec(project) == before


def test_new_edit_records_base_and_parts(strap: Strap, project: Path) -> None:
    write_file(project, SKILL_REL, SKILL_TEXT, commit=True)
    ok(strap("new", NAME, "--edit"))
    spec = read_spec(project)
    assert spec["mode"] == "edit" and spec["base"] == git(project, "rev-parse", "HEAD")
    assert SKILL_REL in [part["path"] for part in spec["parts"]]


def test_new_refuses_an_existing_skill(strap: Strap, project: Path) -> None:
    write_file(project, SKILL_REL, SKILL_TEXT, commit=True)
    err = refused(strap("new", NAME))
    assert f"{NAME} exists; use --edit" in err
    assert not spec_path(project).exists()


def test_new_edit_refuses_a_missing_skill(strap: Strap, project: Path) -> None:
    err = refused(strap("new", NAME, "--edit"))
    assert f"{NAME} has no SKILL.md to edit" in err
    assert not spec_path(project).exists()


def test_new_edit_records_the_given_base(strap: Strap, project: Path) -> None:
    write_file(project, SKILL_REL, SKILL_TEXT, commit=True)
    ancestor = git(project, "rev-parse", "HEAD~1")
    ok(strap("new", NAME, "--edit", "--base", "HEAD~1"))
    spec = read_spec(project)
    assert spec["mode"] == "edit" and spec["base"] == ancestor and len(ancestor) == 40


def test_new_edit_refuses_a_non_ancestor_base(strap: Strap, project: Path) -> None:
    write_file(project, SKILL_REL, SKILL_TEXT, commit=True)
    orphan = git(project, "commit-tree", "HEAD^{tree}", "-m", "unrelated root")
    refused(strap("new", NAME, "--edit", "--base", orphan))
    assert not spec_path(project).exists()


@pytest.mark.cross_os
def test_new_refuses_a_judge_change_once_grades_exist(started: str, strap: Strap,
                                                      piped: Callable[..., Result], project: Path) -> None:
    ok(piped(BASELINE_REPLY, "record-run", NAME, "--run", "R-1"))
    ok(piped('grade(name, "R-1", 0, "absent", "ledger edited")\n', "api", NAME))
    before = read_spec(project)
    assert len(before["grades"]) == 1
    refused(strap("new", NAME, "--judge"))
    assert read_spec(project) == before


# --- check ------------------------------------------------------------------------------------------------

def test_check_passes_a_sound_spec(built: Callable[..., Dict[str, Any]], strap: Strap) -> None:
    built()
    code, out, err = strap("check", NAME)
    assert code == 0 and "check [ok]" in out and "problem:" not in err, err


def test_check_lists_open_behavior_short_of_scenarios(built: Callable[..., Dict[str, Any]],
                                                      strap: Strap) -> None:
    built(scenarios=1)
    _, out, err = strap("check", NAME)
    assert re.search(r"^open: B1\b", out, re.MULTILINE), out
    assert "problem:" not in err, err


def test_check_refuses_hand_edited_driver_owned_field(built: Callable[..., Dict[str, Any]], strap: Strap,
                                                      project: Path) -> None:
    spec = built()
    spec["behaviors"][0]["state"] = "green"
    spec_path(project).write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8", newline="\n")
    assert "driver-owned" in refused(strap("check", NAME))


def test_check_refuses_a_non_canonical_file(built: Callable[..., Dict[str, Any]],
                                            strap: Strap, project: Path) -> None:
    spec = built()
    spec_path(project).write_text(json.dumps(spec), encoding="utf-8", newline="\n")
    refused(strap("check", NAME))


def test_check_refuses_a_role_without_an_agent_file(built: Callable[..., Dict[str, Any]],
                                                    strap: Strap) -> None:
    built(role="helper")
    err = refused(strap("check", NAME))
    assert "role helper has no agents/helper.md" in err


# --- draw -------------------------------------------------------------------------------------------------

def test_draw_refuses_a_behavior_with_one_scenario(built: Callable[..., Dict[str, Any]], strap: Strap,
                                                   project: Path) -> None:
    built(scenarios=1)
    assert "B1" in refused(strap("draw", NAME))
    assert read_spec(project)["draws"] == []


def test_draw_appends_one_initial_draw_never_redraws(built: Callable[..., Dict[str, Any]], strap: Strap,
                                                     project: Path) -> None:
    built()
    out = ok(strap("draw", NAME))
    spec = read_spec(project)
    [draw] = spec["draws"]
    assert draw["behavior"] == "B1" and draw["reason"] == "initial" and draw["scenario"] in ("SC-1", "SC-2")
    assert re.search(rf"^draw \| B1 -> {draw['scenario']}\s*$", out, re.MULTILINE), out
    assert spec["behaviors"][0]["state"] == "drawn"
    strap("draw", NAME)
    assert read_spec(project)["draws"] == [draw]


# --- run --------------------------------------------------------------------------------------------------

def test_run_refuses_no_draw_and_early_green(built: Callable[..., Dict[str, Any]],
                                             strap: Strap, project: Path) -> None:
    built()
    refused(strap("run", NAME, "B1", "--arm", "baseline"))
    ok(strap("draw", NAME))
    refused(strap("run", NAME, "B1", "--arm", "green"))
    assert read_spec(project)["runs"] == []


@pytest.mark.cross_os
def test_run_prints_the_runner_row_and_builds_the_tree(built: Callable[..., Dict[str, Any]], strap: Strap,
                                                       project: Path) -> None:
    built()
    ok(strap("draw", NAME))
    out = ok(strap("run", NAME, "B1", "--arm", "baseline"))
    assert "agent=harness:strap-scenario-runner model=sonnet" in out
    assert out.index("agent=harness:strap-scenario-runner") < out.index(f"SKILL: {NAME}") \
        < out.index("RUN: R-1") < out.index("TREE: ")
    init_line = rf'--repo "{re.escape(root_posix(project))}"\s+init\s+{NAME}\s+--run\s+R-1\b'
    assert re.search(init_line, out), out
    tree = Path(re.findall(r"TREE: (.+?)\s*$", out, re.MULTILINE)[-1])
    assert tree.is_absolute() and tree.is_dir()
    [run] = read_spec(project)["runs"]
    assert run["id"] == "R-1" and run["arm"] == "baseline" and run["recorded"] is False


@pytest.mark.cross_os
def test_run_twice_before_record_reuses_the_run(built: Callable[..., Dict[str, Any]], strap: Strap,
                                                project: Path) -> None:
    built()
    ok(strap("draw", NAME))
    first = ok(strap("run", NAME, "B1", "--arm", "baseline"))
    second = ok(strap("run", NAME, "B1", "--arm", "baseline"))
    assert "RUN: R-1" in first and "RUN: R-1" in second, second
    assert [run["id"] for run in read_spec(project)["runs"]] == ["R-1"]


@pytest.mark.cross_os
def test_run_refuses_second_recorded_run_same_arm(started: str, strap: Strap,
                                                  piped: Callable[..., Result], project: Path) -> None:
    ok(piped(BASELINE_REPLY, "record-run", NAME, "--run", "R-1"))
    refused(strap("run", NAME, "B1", "--arm", "baseline"))
    assert [run["id"] for run in read_spec(project)["runs"]] == ["R-1"]


# --- init and record-run ----------------------------------------------------------------------------------

@pytest.mark.cross_os
def test_init_brief_ends_with_record_run(started: str, strap: Strap, project: Path,
                                         plugin_root: Path) -> None:
    spec = read_spec(project)
    drawn = spec["draws"][0]["scenario"]
    task = next(sc["task"] for sc in spec["behaviors"][0]["scenarios"] if sc["id"] == drawn)
    out = ok(strap("init", NAME, "--run", "R-1"))
    assert task in out
    scripts = plugin_root.resolve() / "scripts"
    command = (f'sh "{(scripts / "hpy").as_posix()}" "{(scripts / "strap.py").as_posix()}" '
               f'--repo "{root_posix(project)}" record-run {NAME} --run R-1')
    last = [line for line in out.splitlines() if line.strip()][-1]
    assert last.startswith(command), last
    assert re.match(r"\s*<<-?\s*(['\"])\w+\1\s*$", last[len(command):]), last
    assert out.index(task) < out.rindex(command)


@pytest.mark.cross_os
def test_init_baseline_of_new_skill_omits_the_skill(built: Callable[..., Dict[str, Any]], strap: Strap,
                                                    project: Path) -> None:
    built()
    write_file(project, SKILL_REL, SKILL_TEXT)
    ok(strap("draw", NAME))
    ok(strap("run", NAME, "B1", "--arm", "baseline"))
    out = ok(strap("init", NAME, "--run", "R-1"))
    assert SKILL_MARKER not in out, out


@pytest.mark.cross_os
def test_init_green_carries_skill_with_abs_paths(built: Callable[..., Dict[str, Any]], strap: Strap,
                                                 piped: Callable[..., Result], project: Path) -> None:
    built()
    write_file(project, SKILL_REL, SKILL_TEXT)
    ok(strap("draw", NAME))
    ok(strap("run", NAME, "B1", "--arm", "baseline"))
    ok(piped(BASELINE_REPLY, "record-run", NAME, "--run", "R-1"))
    assert "RUN: R-2" in ok(strap("run", NAME, "B1", "--arm", "green"))
    out = ok(strap("init", NAME, "--run", "R-2"))
    assert SKILL_MARKER in out, out
    assert "reference/skill_arguments.md" in out, out
    assert "${CLAUDE_PLUGIN_ROOT}" not in out and "${CLAUDE_SKILL_DIR}" not in out, out


@pytest.mark.cross_os
def test_init_includes_the_role_agent_body(built: Callable[..., Dict[str, Any]], strap: Strap,
                                           project: Path) -> None:
    built(role="helper")
    write_file(project, "plugins/harness/agents/helper.md", AGENT_TEXT, commit=True)
    ok(strap("draw", NAME))
    ok(strap("run", NAME, "B1", "--arm", "baseline"))
    out = ok(strap("init", NAME, "--run", "R-1"))
    assert AGENT_MARKER in out, out


@pytest.mark.cross_os
def test_record_run_stores_reply_and_drops_tree(started: str, piped: Callable[..., Result],
                                                project: Path) -> None:
    out = ok(piped(BASELINE_REPLY, "record-run", NAME, "--run", "R-1"))
    assert "SIGNAL: recorded" in out and "R-1" in out
    [run] = read_spec(project)["runs"]
    assert run["recorded"] is True and run["reply"].strip() == BASELINE_REPLY.strip()
    assert run["reply_sha256"] == hashlib.sha256(run["reply"].encode("utf-8")).hexdigest()
    assert [(c["index"], c["held"]) for c in run["checks"]] == [(0, True)] and run["diff"] == []
    assert not Path(started).exists()


# --- retest and freeze ------------------------------------------------------------------------------------

@pytest.mark.cross_os
def test_retest_refuses_without_failed_green(started: str, strap: Strap, piped: Callable[..., Result],
                                             project: Path) -> None:
    ok(piped(BASELINE_REPLY, "record-run", NAME, "--run", "R-1"))
    assert "no failed green" in refused(strap("retest", NAME, "B1"))
    ok(strap("run", NAME, "B1", "--arm", "green"))
    ok(piped(GREEN_REPLY, "record-run", NAME, "--run", "R-2"))
    assert "hash" in refused(strap("retest", NAME, "B1"))
    spec = read_spec(project)
    assert len(spec["draws"]) == 1 and spec["behaviors"][0]["state"] != "retest"


def test_freeze_refuses_a_behavior_that_never_ran(built: Callable[..., Dict[str, Any]], strap: Strap,
                                                  project: Path) -> None:
    built()
    ok(strap("draw", NAME))
    assert "B1" in refused(strap("freeze", NAME))
    assert read_spec(project)["frozen"] is None


def test_freeze_stamps_hash_and_grader(built: Callable[..., Dict[str, Any]], strap: Strap,
                                       piped: Callable[..., Result], project: Path) -> None:
    built()
    ok(piped('drop_behavior(name, "B1", "baseline never showed the tempted move")\n', "api", NAME))
    out = ok(strap("freeze", NAME))
    match = re.match(rf"freeze \[done\] \| {NAME} \| ([0-9a-f]{{12}}) \| grader session", out)
    assert match, out
    frozen = read_spec(project)["frozen"]
    assert frozen["grader"] == "session" and frozen["skill_hash"].startswith(match.group(1))


# --- api --------------------------------------------------------------------------------------------------

def test_api_runs_stdin_code_with_name_bound(strap: Strap, piped: Callable[..., Result],
                                             project: Path) -> None:
    ok(strap("new", NAME))
    out = ok(piped('print("bound:", name)\n' + BEHAVIOR, "api", NAME))
    assert f"bound: {NAME}" in out
    assert [b["id"] for b in read_spec(project)["behaviors"]] == ["B1"]


def test_api_reports_refused_operation_as_problem(built: Callable[..., Dict[str, Any]],
                                                  piped: Callable[..., Result], project: Path) -> None:
    built()
    err = refused(piped('update_behavior(name, "B1", state="green")\n', "api", NAME))
    assert "state is driver-owned" in err
    assert read_spec(project)["behaviors"][0]["state"] == "open"


@pytest.mark.cross_os
def test_api_cannot_call_record_run(started: str, piped: Callable[..., Result], project: Path) -> None:
    err = refused(piped('record_run(name, "R-1", "forged reply")\n', "api", NAME))
    assert "NameError" in err and "record_run" in err, err
    [run] = read_spec(project)["runs"]
    assert run["recorded"] is False and run["reply"] == ""
