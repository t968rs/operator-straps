"""``strap.py rename``: a frozen spec follows its skill to a new name.

``rename`` moves the skill folder and every part made from the old name (a tree the developer already moved
by hand is accepted), swaps the old name's kebab, snake and title forms inside the moved parts, moves each
test file a planned node cites whose name is made from the old name, reports the old name where it lingers in
other tracked files, then moves the spec folder and the ledger folder to the new name, re-points the parts
and the planned test copies, names each text field the name swap rewrote, writes a ``rename`` entry naming
the old name and tags the base under the new stem. Entries written before the rename keep their tags under
the old stem, so ``check`` reports nothing untagged, and the next refreeze tags under the new stem.
``--dry-run`` prints the moves and changes nothing; ``--from <old-name>`` finishes an earlier rename.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import git

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _strap_lock_helpers as helpers  # noqa: E402
from _strap_lock_helpers import (ADD_PART, LOCKED, NAME, PLANS, PLANNED_TEST, SKILL, STEM,  # noqa: E402
                                 Strap, _file_test, _mechanical_code, commit_all, kind_of, ok, peeled,
                                 refused, skill_text, write)

# the shared fixtures, by name
driver, project, strap, piped = helpers.driver, helpers.project, helpers.strap, helpers.piped
prepared, frozen = helpers.prepared, helpers.frozen

NEW = "renamed-skill"
NEW_STEM = f"skill/{NEW}"
NEW_SKILL = f"plugins/harness/skills/{NEW}/SKILL.md"
NEW_SPEC = f"{PLANS}/strap/{NEW}/SkillSpec.json"
OLD_FOLDER = f"plugins/harness/skills/{NAME}"
NEW_FOLDER = f"plugins/harness/skills/{NEW}"


def _safe(strap: Strap, *args: str):
    """``strap`` with an argparse exit (an unknown flag or a missing argument) returned as its exit code."""
    try:
        return strap(*args)
    except SystemExit as exc:
        return int(exc.code or 0), "", ""


def _tracked(project: Path, rel: str) -> bool:
    return bool(git(project, "ls-files", "--", rel))


def _freeze_with_extra(strap: Strap, piped, project: Path, extra: str) -> None:
    """A frozen spec whose B1 (widget) and B2 cite ``tests/test_widget.py`` and ``extra``; committed."""
    ok(strap("new", NAME))
    ok(piped(_mechanical_code("Writes widget.txt", "tests/test_widget.py::test_widget_exists"), "api", NAME))
    ok(piped(_mechanical_code("Writes extra.txt", f"{extra}::test_extra_exists"), "api", NAME))
    write(project, SKILL, skill_text("Body."))
    ok(piped(ADD_PART, "api", NAME))
    write(project, PLANNED_TEST, _file_test("widget"))
    write(project, f"{PLANS}/strap/{NAME}/tests/{extra}", _file_test("extra"))
    ok(strap("red", NAME))
    write(project, "tests/test_widget.py", _file_test("widget"))
    write(project, extra, _file_test("extra"))
    write(project, "widget.txt", "widget\n")
    write(project, "extra.txt", "extra\n")
    commit_all(project)
    ok(strap("freeze", NAME))
    commit_all(project)


def _move_skill(project: Path) -> None:
    """The developer's half of a rename: the skill folder under its new name, frontmatter included."""
    git(project, "mv", f"plugins/harness/skills/{NAME}", f"plugins/harness/skills/{NEW}")
    write(project, NEW_SKILL, f"---\nname: {NEW}\ndescription: Use when testing the lock.\n---\n\nBody.\n")


def _new_entries(project: Path):
    from harness_lib import freeze_ledger as fl
    return list(fl.load_entries(fl.ledger_dir(project / PLANS, NEW_STEM)))


def test_rename_moves_the_spec_and_the_ledger(frozen: str, strap: Strap, project: Path) -> None:
    from harness_lib import freeze_ledger as fl
    _move_skill(project)
    out = ok(strap("rename", NAME, NEW))
    assert out.startswith(f"rename [done] | {NAME} -> {NEW}"), out
    assert not (project / PLANS / "strap" / NAME).exists()
    assert not fl.ledger_dir(project / PLANS, STEM).exists()
    spec = json.loads((project / NEW_SPEC).read_text(encoding="utf-8"))
    assert spec["name"] == NEW
    assert [part["path"] for part in spec["parts"]] == [NEW_SKILL]
    found = _new_entries(project)
    assert [kind_of(e) for e in found] == ["freeze", "rename"]
    assert found[-1].from_name == NAME and found[-1].round == 1 and found[-1].seq == 2


def test_rename_repoints_the_parts_at_the_old_names_planned_paths(frozen: str, strap: Strap, piped,
                                                                   project: Path) -> None:
    """The contract test sits at a path made from the name; it follows the rename like the skill folder."""
    old_test = "tests/skills/test_demo_skill_skill_contract.py"
    new_test = "tests/skills/test_renamed_skill_skill_contract.py"
    write(project, old_test, '"""Contract."""\n')
    ok(piped(f'add_part(name, "contract_test", "{old_test}")\n', "api", NAME))
    commit_all(project)
    _move_skill(project)
    git(project, "mv", old_test, new_test)
    out = ok(strap("rename", NAME, NEW))
    assert "| 2 part(s) re-pointed |" in out, out
    spec = json.loads((project / NEW_SPEC).read_text(encoding="utf-8"))
    assert [part["path"] for part in spec["parts"]] == [NEW_SKILL, new_test]


def test_rename_carries_the_name_into_scenario_text(frozen: str, strap: Strap, driver) -> None:
    """A check that pins the invocation (``usage: /harness:<name>``) must expect the new name; a longer
    name that merely contains the old one is left alone."""
    from harness_lib import strap_models as sm
    ok(strap("check", NAME))
    scenario = sm.Scenario(id="SC-1", task=f"Run /harness:{NAME} --lsit, then {NAME}-extra.",
                           tempts=f"stores the flag through {NAME}",
                           pressures=["time", "authority", "pragmatic"],
                           checks=[sm.Check(kind="reply_matches", target=f"usage: /harness:{NAME}",
                                            expect_baseline=False, expect_green=True)],
                           judged=[sm.JudgedItem(act="refuses", of=f"the {NAME} note",
                                                 expect_baseline="absent", expect_green="present")])
    behavior = sm.Behavior(id="B9", statement=f"{NAME} prints its usage line", kind="judgment",
                           type="discipline", rationale="r", scenarios=[scenario])
    spec = driver.load(NAME)
    renamed = driver._renamed(spec.model_copy(update={"behaviors": [*spec.behaviors, behavior]}), NEW)
    moved = renamed.behaviors[-1]
    assert moved.statement == f"{NEW} prints its usage line"
    assert moved.scenarios[0].task == f"Run /harness:{NEW} --lsit, then {NAME}-extra."
    assert moved.scenarios[0].tempts == f"stores the flag through {NEW}"
    assert moved.scenarios[0].checks[0].target == f"usage: /harness:{NEW}"
    assert moved.scenarios[0].judged[0].of == f"the {NEW} note"


def test_rename_repoints_planned_test_nodes_and_path_check_targets(frozen: str, strap: Strap,
                                                                   driver) -> None:
    """A planned node in the contract test and a check on the api module follow the moved files, so the
    refreeze's mechanical gate runs the node at its new path; the snake form never matches the text swap."""
    from harness_lib import strap_models as sm
    ok(strap("check", NAME))
    spec = driver.load(NAME)
    old_paths, new_paths = driver.named_paths(spec), driver.named_paths(spec.model_copy(update={"name": NEW}))
    node = sm.PlannedTest(node=f"{old_paths[-1]}::test_b1", red="AssertionError")
    mechanical = sm.Behavior(id="B8", statement="s", kind="mechanical", rationale="r", tests=[node])
    scenario = sm.Scenario(id="SC-1", task="t", tempts="x", pressures=["time", "authority", "pragmatic"],
                           checks=[sm.Check(kind="file_unchanged", target=old_paths[2],
                                            expect_baseline=True, expect_green=True)])
    judgment = sm.Behavior(id="B9", statement="s", kind="judgment", type="discipline", rationale="r",
                           scenarios=[scenario])
    renamed = driver._renamed(spec.model_copy(update={"behaviors": [*spec.behaviors, mechanical, judgment]}),
                              NEW)
    assert renamed.behaviors[-2].tests[0].node == f"{new_paths[-1]}::test_b1"
    assert renamed.behaviors[-1].scenarios[0].checks[0].target == new_paths[2]


def test_rename_leaves_path_check_targets_to_the_repoint_and_names_each_swap(frozen: str, strap: Strap,
                                                                            driver) -> None:
    """A path check whose file stem is the old name names another file, so only the re-point touches it;
    each text field the swap rewrote gets a ``swapped:`` line for the developer's review."""
    from harness_lib import strap_models as sm
    ok(strap("check", NAME))
    other = f"plugins/session-x/hooks/{NAME}.ts"
    checks = [sm.Check(kind="path_present", target=other, expect_baseline=False, expect_green=True),
              sm.Check(kind="reply_matches", target=f"usage: /harness:{NAME}",
                       expect_baseline=False, expect_green=True)]
    scenario = sm.Scenario(id="SC-1", task=f"Run /harness:{NAME}.", tempts="x",
                           pressures=["time", "authority", "pragmatic"], checks=checks)
    behavior = sm.Behavior(id="B9", statement="s", kind="judgment", type="discipline", rationale="r",
                           scenarios=[scenario])
    spec = driver.load(NAME)
    spec = spec.model_copy(update={"behaviors": [*spec.behaviors, behavior]})
    renamed = driver._renamed(spec, NEW)
    moved = renamed.behaviors[-1].scenarios[0].checks
    assert [check.target for check in moved] == [other, f"usage: /harness:{NEW}"]
    swaps = [line for line in driver.swapped_lines(spec, renamed) if " B9" in line]
    assert swaps == ["swapped: B9/SC-1 task", "swapped: B9/SC-1 checks[1].target"]


def test_rename_moves_a_planned_test_copy_with_its_node(frozen: str, strap: Strap, driver,
                                                        project: Path) -> None:
    """A planned copy at the old contract test path follows the node, so ``red`` still finds it."""
    from harness_lib import strap_models as sm
    ok(strap("check", NAME))
    spec = driver.load(NAME)
    old_test = driver.named_paths(spec)[-1]
    new_test = driver.named_paths(spec.model_copy(update={"name": NEW}))[-1]
    node = sm.PlannedTest(node=f"{old_test}::test_b1", red="AssertionError")
    mechanical = sm.Behavior(id="B8", statement="s", kind="mechanical", rationale="r", tests=[node])
    spec = spec.model_copy(update={"behaviors": [*spec.behaviors, mechanical]})
    renamed = driver._renamed(spec, NEW)
    tests = project / PLANS / "strap" / NEW / "tests"
    write(project, f"{PLANS}/strap/{NEW}/tests/{old_test}", '"""Planned."""\n')
    moves = driver._planned_test_moves(spec, renamed)
    assert [(a.resolve(), b.resolve()) for a, b in moves] == [((tests / old_test).resolve(),
                                                               (tests / new_test).resolve())]
    done: list = []
    driver._move_planned_tests(moves, done)
    assert done == moves
    assert (tests / new_test).is_file() and not (tests / old_test).exists()


def test_rename_tags_the_base_under_the_new_stem(frozen: str, strap: Strap, project: Path) -> None:
    ok(strap("reopen", NAME))
    base = git(project, "rev-parse", "HEAD")
    ok(strap("freeze", NAME))
    commit_all(project)
    _move_skill(project)
    out = ok(strap("rename", NAME, NEW))
    assert f"tag: base/{NEW_STEM}/r2 -> {base[:7]}" in out, out
    assert peeled(project, f"base/{NEW_STEM}/r2", "commit") == base


def test_a_renamed_spec_checks_clean_and_refreezes_under_the_new_stem(frozen: str, strap: Strap,
                                                                      project: Path) -> None:
    frozen_commit = git(project, "rev-parse", "HEAD")
    _move_skill(project)
    ok(strap("rename", NAME, NEW))
    commit_all(project)
    out = ok(strap("check", NEW))
    assert "stale: " in out, out
    assert not [line for line in out.splitlines() if line.strip().startswith("untagged: ")], out
    assert peeled(project, f"freeze/{STEM}/r1.1-commit", "commit") == frozen_commit
    ok(strap("freeze", NEW, "--refreeze"))
    found = _new_entries(project)
    assert [kind_of(e) for e in found] == ["freeze", "rename", "freeze"]
    assert git(project, "tag", "--list", f"freeze/{NEW_STEM}/r1.3-tree") == f"freeze/{NEW_STEM}/r1.3-tree"


def test_the_rename_entry_commit_tag_names_the_commit_that_added_it(frozen: str, strap: Strap,
                                                                     project: Path) -> None:
    """A small rename entry resembles the moved reopen entry; only an exact move is followed, so its commit
    tag lands on the rename commit, not on the reopen's."""
    ok(strap("reopen", NAME))
    ok(strap("freeze", NAME))
    commit_all(project)
    _move_skill(project)
    ok(strap("rename", NAME, NEW))
    commit_all(project)
    rename_commit = git(project, "rev-parse", "HEAD")
    ok(strap("check", NEW))
    entry = _new_entries(project)[-1]
    assert kind_of(entry) == "rename"
    tag = f"rename/{NEW_STEM}/r{entry.round}.{entry.seq}-commit"
    assert peeled(project, tag, "commit") == rename_commit


def test_rename_moves_a_skill_folder_not_yet_moved(frozen: str, strap: Strap, project: Path) -> None:
    """The skill folder moves with git, and the frontmatter name follows the swap."""
    out = ok(strap("rename", NAME, NEW))
    assert out.startswith(f"rename [done] | {NAME} -> {NEW}"), out
    assert not (project / OLD_FOLDER).exists()
    assert _tracked(project, NEW_SKILL) and not _tracked(project, SKILL)
    assert (project / NEW_SKILL).read_text(encoding="utf-8").startswith(f"---\nname: {NEW}\n")


def test_rename_refuses_a_spec_never_frozen(prepared: Path, strap: Strap) -> None:
    _move_skill(prepared)
    assert f"{NAME} is not frozen" in refused(strap("rename", NAME, NEW))


def test_rename_refuses_a_locked_spec(frozen: str, strap: Strap, project: Path) -> None:
    ok(strap("lock", NAME))
    commit_all(project)
    _move_skill(project)
    assert LOCKED in refused(strap("rename", NAME, NEW))


def test_rename_refuses_a_name_that_already_has_a_ledger(frozen: str, strap: Strap, project: Path) -> None:
    _move_skill(project)
    write(project, f"{PLANS}/freezes/{NEW_STEM}/r1.1-freeze.json", "{}\n")
    err = refused(strap("rename", NAME, NEW))
    assert f"freezes/{NEW_STEM}" in err, err
    assert (project / PLANS / "strap" / NAME / "SkillSpec.json").is_file()


def test_rename_refuses_a_bad_name(frozen: str, strap: Strap, project: Path) -> None:
    assert "'Renamed' is not a skill name" in refused(strap("rename", NAME, "Renamed"))


def test_rename_names_an_old_folder_left_behind(frozen: str, strap: Strap, project: Path) -> None:
    """Untracked leftovers that ``git mv`` leaves under the old folder are named, not a missing SKILL.md."""
    _move_skill(project)
    write(project, f"plugins/harness/skills/{NAME}/commands/__pycache__/add_note.pyc", "")
    err = refused(strap("rename", NAME, NEW))
    assert "still exists" in err, err
    assert "does not exist" not in err, err


def test_rename_moves_a_part_not_yet_moved(frozen: str, strap: Strap, piped, project: Path) -> None:
    old_test = "tests/skills/test_demo_skill_skill_contract.py"
    new_test = "tests/skills/test_renamed_skill_skill_contract.py"
    write(project, old_test, '"""Contract for demo_skill."""\n')
    ok(piped(f'add_part(name, "contract_test", "{old_test}")\n', "api", NAME))
    commit_all(project)
    _move_skill(project)
    out = ok(strap("rename", NAME, NEW))
    assert "| 2 part(s) re-pointed |" in out, out
    assert _tracked(project, new_test) and not (project / old_test).exists()
    assert (project / new_test).read_text(encoding="utf-8") == '"""Contract for renamed_skill."""\n'


def test_rename_dry_run_prints_each_move_and_changes_nothing(frozen: str, strap: Strap,
                                                              project: Path) -> None:
    out = ok(_safe(strap, "rename", NAME, NEW, "--dry-run"))
    assert f"move: {OLD_FOLDER} -> {NEW_FOLDER}" in out.splitlines(), out
    assert (project / SKILL).is_file() and not (project / NEW_FOLDER).exists()
    assert (project / PLANS / "strap" / NAME / "SkillSpec.json").is_file()
    assert not (project / NEW_SPEC).exists()
    assert git(project, "status", "--porcelain") == ""


def test_rename_refuses_before_any_move_when_a_target_exists(frozen: str, strap: Strap,
                                                              project: Path) -> None:
    write(project, f"{NEW_FOLDER}/notes.md", "Someone else's skill.\n")
    err = refused(strap("rename", NAME, NEW))
    assert f"move target {NEW_FOLDER} already exists" in err, err
    assert (project / SKILL).is_file()
    assert (project / f"{NEW_FOLDER}/notes.md").is_file() and not (project / NEW_SKILL).exists()
    assert (project / PLANS / "strap" / NAME / "SkillSpec.json").is_file()


def test_rename_swaps_the_old_name_forms_inside_the_moved_parts(frozen: str, strap: Strap,
                                                                 project: Path) -> None:
    write(project, SKILL, skill_text(f"# Demo Skill\n\nRun /harness:{NAME}; see demo_skill_api and "
                                      f"{NAME}-extra."))
    commit_all(project)
    out = ok(strap("rename", NAME, NEW))
    text = (project / NEW_SKILL).read_text(encoding="utf-8")
    assert text == (f"---\nname: {NEW}\ndescription: Use when testing the lock.\n---\n\n# Renamed Skill\n\n"
                    f"Run /harness:{NEW}; see renamed_skill_api and {NAME}-extra.\n"), text
    lines = out.splitlines()
    assert f"swapped-file: {NEW_SKILL}:2" in lines, out
    assert f"swapped-file: {NEW_SKILL}:6" in lines and f"swapped-file: {NEW_SKILL}:8" in lines, out


def test_a_renamed_skill_checks_with_no_name_problem(frozen: str, strap: Strap, project: Path) -> None:
    ok(strap("rename", NAME, NEW))
    commit_all(project)
    out = ok(strap("check", NEW))
    assert "check [ok]" in out, out


def test_rename_moves_a_test_file_a_planned_node_cites(strap: Strap, piped, project: Path) -> None:
    """A test file named from the old name that a planned node cites moves, swapped, and the node follows;
    its planned copy follows too."""
    _freeze_with_extra(strap, piped, project, "tests/test_demo_skill_extra.py")
    out = ok(strap("rename", NAME, NEW))
    move = "move: tests/test_demo_skill_extra.py -> tests/test_renamed_skill_extra.py"
    assert move in out.splitlines(), out
    assert _tracked(project, "tests/test_renamed_skill_extra.py")
    assert not (project / "tests/test_demo_skill_extra.py").exists()
    spec = json.loads((project / NEW_SPEC).read_text(encoding="utf-8"))
    nodes = [test["node"] for behavior in spec["behaviors"] for test in behavior["tests"]]
    assert nodes == ["tests/test_widget.py::test_widget_exists",
                     "tests/test_renamed_skill_extra.py::test_extra_exists"]
    assert (project / PLANS / "strap" / NEW / "tests/tests/test_renamed_skill_extra.py").is_file()


def test_rename_reports_an_old_name_outside_the_parts(frozen: str, strap: Strap, project: Path) -> None:
    write(project, "README.md", f"# Project\n\nUse {NAME} for the demo.\n")
    commit_all(project)
    out = ok(strap("rename", NAME, NEW))
    assert "stale-name: README.md:3" in out.splitlines(), out
    assert (project / "README.md").read_text(encoding="utf-8") == f"# Project\n\nUse {NAME} for the demo.\n"


def test_rename_from_finishes_an_earlier_rename(strap: Strap, piped, project: Path) -> None:
    """A spec renamed before the moves existed keeps an old-named test file; ``--from`` moves it and its
    node under the spec's current name, writing no ledger entry."""
    from harness_lib import freeze_ledger as fl
    _freeze_with_extra(strap, piped, project, "tests/test_old_skill_extra.py")
    before = list(fl.load_entries(fl.ledger_dir(project / PLANS, STEM)))
    out = ok(_safe(strap, "rename", NAME, "--from", "old-skill"))
    assert "move: tests/test_old_skill_extra.py -> tests/test_demo_skill_extra.py" in out.splitlines(), out
    assert _tracked(project, "tests/test_demo_skill_extra.py")
    spec = json.loads((project / PLANS / "strap" / NAME / "SkillSpec.json").read_text(encoding="utf-8"))
    assert spec["name"] == NAME
    assert spec["behaviors"][1]["tests"][0]["node"] == "tests/test_demo_skill_extra.py::test_extra_exists"
    assert list(fl.load_entries(fl.ledger_dir(project / PLANS, STEM))) == before


def test_rename_refuses_a_name_that_already_has_a_spec(frozen: str, strap: Strap, project: Path) -> None:
    _move_skill(project)
    write(project, NEW_SPEC, "{}\n")
    err = refused(strap("rename", NAME, NEW))
    assert f"{NEW} already has a spec" in err, err
    assert (project / PLANS / "strap" / NAME / "SkillSpec.json").is_file()


def test_rename_moves_both_folders_back_when_the_commit_fails(frozen: str, strap: Strap, driver,
                                                              project: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure after the spec folder moved leaves the spec, its bytes and its ledger under the old name."""
    from harness_lib import freeze_ledger as fl
    _move_skill(project)
    spec_file = project / PLANS / "strap" / NAME / "SkillSpec.json"
    before = spec_file.read_bytes()
    ledger = fl.ledger_dir(project / PLANS, STEM)

    def _fail(*_args, **_kwargs):
        raise driver.sl.LockRefused(["entry write failed"])

    monkeypatch.setattr(driver.sl, "commit", _fail)
    assert "entry write failed" in refused(strap("rename", NAME, NEW))
    assert spec_file.read_bytes() == before
    assert [kind_of(e) for e in fl.load_entries(ledger)] == ["freeze"]
    assert not (project / NEW_SPEC).parent.exists()
    assert not fl.ledger_dir(project / PLANS, NEW_STEM).exists()


def test_rename_moves_everything_back_when_the_commit_fails(frozen: str, strap: Strap, driver,
                                                             project: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure after the moves leaves the skill folder, its swapped text and the spec as they were."""
    write(project, SKILL, skill_text(f"Run /harness:{NAME}."))
    commit_all(project)
    skill_before = (project / SKILL).read_bytes()

    def _fail(*_args, **_kwargs):
        raise driver.sl.LockRefused(["entry write failed"])

    monkeypatch.setattr(driver.sl, "commit", _fail)
    assert "entry write failed" in refused(strap("rename", NAME, NEW))
    assert (project / SKILL).read_bytes() == skill_before
    assert not (project / NEW_FOLDER).exists()
    assert git(project, "status", "--porcelain") == ""
