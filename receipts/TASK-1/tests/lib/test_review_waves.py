"""Behavioral tests for harness_lib.review_waves (pr-review fix-wave planning).

The PR #1558 fixture (``fixtures/pr1558_issues.json``) carries the real issue/file list of that review, with
each issue's primary file, other files, lines and a mechanical/judgment guess.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

import pytest

from harness_lib import review_waves as rwv

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pr1558_issues.json"


def _issue(issue_id: str, file: str = "a.py", **extra: object) -> Dict[str, object]:
    """A schema issue dict."""
    return {"id": issue_id, "name": f"n {issue_id}", "file": file, "reviewer": "runtime",
            "fix_kind": "mechanical", "summary": "s", "fix": ["f"], **extra}


def _fixture_issues() -> List[Dict[str, object]]:
    """PR #1558 issues as schema issue dicts (``files`` when the issue has other files)."""
    out: List[Dict[str, object]] = []
    for raw in json.loads(_FIXTURE.read_text(encoding="utf-8"))["issues"]:
        issue = _issue(raw["id"], raw["file"], fix_kind=raw["fix_kind"], name=raw["name"])
        if raw["also"]:
            issue["files"] = [raw["file"], *raw["also"]]
        out.append(issue)
    return out


def _files_of(issue: Mapping[str, object]) -> set:
    """Full file set of a schema issue."""
    return set(issue.get("files") or [issue["file"]])


def _is_split(issue: Mapping[str, object]) -> bool:
    """True when ``issue`` is mechanical and spans more than one file (planned as per-file parts)."""
    return issue["fix_kind"] == "mechanical" and len(_files_of(issue)) > 1


def _units_of(fixer: Mapping[str, object], by_id: Mapping[str, Mapping[str, object]]) -> int:
    """Units a fixer holds: one per part of a split issue, one per whole issue."""
    return sum(len(files) if _is_split(by_id[i]) else 1 for i, files in fixer["parts"].items())


def _assigned(waves: Sequence[Sequence[Mapping[str, object]]]) -> List[tuple]:
    """Every (issue id, file) pair named by any fixer's parts, with repeats."""
    return [(i, f) for wave in waves for fixer in wave for i, files in fixer["parts"].items() for f in files]


def _check_fixer(fixer: Mapping[str, object], by_id: Mapping[str, Mapping[str, object]], number: int) -> None:
    """Per-fixer invariants: id, cap in units (one over the cap for a judgment-only fixer, the stretch rule),
    parts keys and order, files and model."""
    kinds = {by_id[i]["fix_kind"] for i in fixer["issue_ids"]}
    limit = rwv.MAX_ISSUES_PER_FIXER + (1 if kinds == {"judgment"} else 0)
    assert fixer["id"].startswith(f"w{number}_fix_")
    assert 1 <= _units_of(fixer, by_id) <= limit
    assert list(fixer["parts"]) == fixer["issue_ids"]
    assert fixer["issue_ids"] == sorted(fixer["issue_ids"], key=lambda i: ("MIC".index(i[0]), int(i[1:])))
    for issue_id, files in fixer["parts"].items():
        assert set(files) <= _files_of(by_id[issue_id])
        if not _is_split(by_id[issue_id]):
            assert set(files) == _files_of(by_id[issue_id])
    assert set(fixer["files"]) == {f for files in fixer["parts"].values() for f in files}
    assert fixer["model"] == ("haiku" if kinds == {"mechanical"} else "opus")


class TestPlanWaves:
    @pytest.mark.parametrize("held", [["M20"], []])
    def test_pr1558_fixture(self, held: List[str]) -> None:
        issues = _fixture_issues()
        by_id = {i["id"]: i for i in issues}
        waves = rwv.plan_waves(issues, held=held, done=[])
        assert 1 <= len(waves) <= 2
        planned = {i for wave in waves for fixer in wave for i in fixer["issue_ids"]}
        assert planned == set(by_id) - set(held)
        for number, wave in enumerate(waves, start=1):
            seen: set = set()
            for fixer in wave:
                _check_fixer(fixer, by_id, number)
                assert not set(fixer["files"]) & seen
                seen |= set(fixer["files"])
        pairs = _assigned(waves)
        expected = [(i, f) for i in planned for f in _files_of(by_id[i])]
        assert sorted(pairs) == sorted(expected) and len(pairs) == len(set(pairs))

    def test_mechanical_multi_file_splits_into_parts(self) -> None:
        issues = [_issue(f"M{n}", "a.py") for n in range(1, 7)]
        issues.append(_issue("M7", "b.py", files=["b.py", "a.py"]))
        waves = rwv.plan_waves(issues, held=[], done=[])
        rows = [[(f["issue_ids"], f["parts"], f["files"]) for f in wave] for wave in waves]
        first = [f"M{n}" for n in range(1, 7)]
        assert rows == [
            [(first, {i: ["a.py"] for i in first}, ["a.py"]), (["M7"], {"M7": ["b.py"]}, ["b.py"])],
            [(["M7"], {"M7": ["a.py"]}, ["a.py"])],
        ]

    def test_parts_of_one_issue_in_one_fixer_merge(self) -> None:
        waves = rwv.plan_waves([_issue("M1", "a.py", files=["a.py", "b.py"])], held=[], done=[])
        assert [(f["issue_ids"], f["parts"]) for f in waves[0]] == [(["M1"], {"M1": ["a.py", "b.py"]})]

    def test_judgment_multi_file_stays_whole(self) -> None:
        issues = [_issue(f"M{n}", "a.py") for n in range(1, 6)]
        issues.append(_issue("I1", "b.py", files=["b.py", "a.py"], fix_kind="judgment"))
        waves = rwv.plan_waves(issues, held=[], done=[])
        holders = [f for wave in waves for f in wave if "I1" in f["parts"]]
        assert len(holders) == 1 and holders[0]["parts"]["I1"] == ["b.py", "a.py"]
        assert holders[0]["model"] == "opus"

    def test_cap_counts_parts(self) -> None:
        issues = [_issue(f"M{n}", f"f{n}.py", files=[f"f{n}.py", f"g{n}.py"]) for n in range(1, 5)]
        waves = rwv.plan_waves(issues, held=[], done=[])
        assert all(sum(len(v) for v in f["parts"].values()) <= rwv.MAX_ISSUES_PER_FIXER
                   for wave in waves for f in wave)

    def test_eight_on_one_file_split_across_waves(self) -> None:
        waves = rwv.plan_waves([_issue(f"M{n}") for n in range(1, 9)], held=[], done=[])
        assert [[len(f["issue_ids"]) for f in wave] for wave in waves] == [[6], [2]]

    def test_disjoint_chunks_get_their_own_fixers(self) -> None:
        waves = rwv.plan_waves([_issue("M1", "a.py"), _issue("M2", "b.py")], held=[], done=[])
        assert [f["issue_ids"] for f in waves[0]] == [["M1"], ["M2"]]

    def test_past_the_fixer_target_chunks_share_the_smallest(self) -> None:
        issues = [_issue("M1", "a.py"), _issue("M2", "a.py"), _issue("M3", "b.py"), _issue("M4", "c.py")]
        waves = rwv.plan_waves(issues, held=[], done=[], fixers=2)
        assert [f["issue_ids"] for f in waves[0]] == [["M1", "M2"], ["M3", "M4"]]

    def test_target_of_one_fills_a_fixer_to_the_cap(self) -> None:
        issues = [_issue(f"M{n}", f"f{n}.py") for n in range(1, 4)]
        waves = rwv.plan_waves(issues, held=[], done=[], fixers=1)
        assert [f["issue_ids"] for f in waves[0]] == [["M1", "M2", "M3"]]

    def test_overflow_chunk_prefers_a_fixer_of_its_own_kind(self) -> None:
        issues = [_issue("M1", "a.py", fix_kind="judgment"), _issue("M2", "b.py"), _issue("M3", "c.py")]
        waves = rwv.plan_waves(issues, held=[], done=[], fixers=2)
        assert [(f["issue_ids"], f["model"]) for f in waves[0]] == [(["M1"], "opus"), (["M2", "M3"], "haiku")]

    @staticmethod
    def _hub_and_leaves(leaves: int = 3) -> List[Dict[str, object]]:
        names = [f"{c}.py" for c in "abcdefgh"[:leaves]]
        hub = _issue("I1", names[0], fix_kind="judgment", files=names)
        return [hub, *(_issue(f"M{n}", name) for n, name in enumerate(names, start=1))]

    def test_over_cap_hub_waits_so_its_leaves_run_in_parallel(self) -> None:
        waves = rwv.plan_waves(self._hub_and_leaves(), held=[], done=[], cap=2)
        assert [[f["issue_ids"] for f in wave] for wave in waves] == [[["M1"], ["M2"], ["M3"]], [["I1"]]]

    @staticmethod
    def _heavy_pair(*extra: Dict[str, object]) -> List[Dict[str, object]]:
        """Two judgment importants over a.py and b.py, a mechanical leaf on each file, plus ``extra``."""
        pair = [_issue(i, "a.py", fix_kind="judgment", files=["a.py", "b.py"]) for i in ("I1", "I2")]
        return [*pair, _issue("M1", "a.py"), _issue("M2", "b.py"), *extra]

    def test_tied_estimates_keep_the_most_connected_cut(self) -> None:
        waves = rwv.plan_waves(self._heavy_pair(), held=[], done=[], cap=2)
        assert [[f["issue_ids"] for f in wave] for wave in waves] == [[["M1"], ["M2"]], [["I1", "I2"]]]

    def test_light_first_cut_wins_when_heavy_work_would_queue_behind_heavy_work(self) -> None:
        critical = _issue("C1", "z.py", fix_kind="judgment")
        waves = rwv.plan_waves(self._heavy_pair(critical), held=[], done=[], cap=2)
        lanes = [[f["issue_ids"] for f in wave] for wave in waves]
        assert lanes == [[["I1", "I2"], ["C1"]], [["M1"], ["M2"]]]

    def test_readmit_returns_a_unit_the_cut_no_longer_needs(self) -> None:
        spec = [("M1", ["b.py"], "mechanical"), ("I1", ["b.py", "c.py"], "judgment"),
                ("I2", ["d.py"], "judgment"), ("M2", ["c.py"], "judgment"),
                ("C1", ["c.py"], "mechanical"), ("C2", ["c.py", "d.py"], "judgment")]
        issues = [_issue(i, files[0], files=files, fix_kind=kind) for i, files, kind in spec]
        waves = rwv.plan_waves(issues, held=[], done=[], cap=2)
        lanes = [[f["issue_ids"] for f in wave] for wave in waves]
        assert lanes == [[["M2", "I1"], ["I2"]], [["C1", "C2"], ["M1"]]]

    def test_judgment_group_one_over_the_cap_runs_whole(self) -> None:
        issues = [_issue(f"M{n}", "a.py", fix_kind="judgment") for n in range(1, 8)]
        waves = rwv.plan_waves(issues, held=[], done=[])
        assert [[f["issue_ids"] for f in wave] for wave in waves] == [[[f"M{n}" for n in range(1, 8)]]]

    def test_mechanical_group_one_over_the_cap_is_still_cut(self) -> None:
        waves = rwv.plan_waves([_issue(f"M{n}") for n in range(1, 8)], held=[], done=[])
        assert [[len(f["issue_ids"]) for f in wave] for wave in waves] == [[6], [1]]

    def test_judgment_group_two_over_the_cap_is_still_cut(self) -> None:
        issues = [_issue(f"M{n}", "a.py", fix_kind="judgment") for n in range(1, 9)]
        waves = rwv.plan_waves(issues, held=[], done=[])
        assert all(len(f["issue_ids"]) <= rwv.MAX_ISSUES_PER_FIXER for wave in waves for f in wave)

    def test_all_heavy_group_defers_its_most_connected_unit(self) -> None:
        issues = [_issue("I1", "a.py", fix_kind="judgment", files=["a.py", "b.py"]),
                  _issue("I2", "a.py", fix_kind="judgment"), _issue("I3", "b.py", fix_kind="judgment")]
        waves = rwv.plan_waves(issues, held=[], done=[], cap=1)
        assert [[f["issue_ids"] for f in wave] for wave in waves] == [[["I2"], ["I3"]], [["I1"]]]

    def test_split_part_skips_a_fixer_holding_a_heavy_issue(self) -> None:
        issues = [_issue("M1", "a.py", files=["a.py", "b.py"]), _issue("I1", "a.py", fix_kind="judgment")]
        waves = rwv.plan_waves(issues, held=[], done=[])
        assert [(f["issue_ids"], f["parts"]) for f in waves[0]] == [
            (["M1", "I1"], {"M1": ["a.py"], "I1": ["a.py"]}), (["M1"], {"M1": ["b.py"]})]

    def test_overflow_chunk_avoids_a_fixer_holding_a_heavy_issue(self) -> None:
        pairs = (("I1", "a.py"), ("M2", "b.py"), ("M3", "c.py"))
        issues = [_issue(i, f, fix_kind="judgment") for i, f in pairs]
        waves = rwv.plan_waves(issues, held=[], done=[], fixers=2)
        assert [f["issue_ids"] for f in waves[0]] == [["I1"], ["M2", "M3"]]

    def test_overflow_judgment_chunk_prefers_a_haiku_fixer_over_a_heavy_one(self) -> None:
        issues = [_issue("C1", "a.py", fix_kind="judgment"), _issue("M1", "b.py"),
                  _issue("M2", "c.py", fix_kind="judgment")]
        waves = rwv.plan_waves(issues, held=[], done=[], fixers=2)
        assert [(f["model"], f["issue_ids"]) for f in waves[0]] == [("opus", ["C1"]), ("opus", ["M1", "M2"])]

    def test_group_within_the_cap_runs_whole_in_one_fixer(self) -> None:
        waves = rwv.plan_waves(self._hub_and_leaves(), held=[], done=[], cap=6)
        assert [f["issue_ids"] for f in waves[0]] == [["M1", "M2", "M3", "I1"]] and len(waves) == 1

    def test_cut_defers_the_least_severe_of_equally_connected_units(self) -> None:
        waves = rwv.plan_waves([_issue(f"M{n}") for n in range(1, 9)], held=[], done=[], cap=3)
        assert [[f["issue_ids"] for f in wave] for wave in waves] == [[["M1", "M2", "M3"]],
                                                                       [["M4", "M5", "M6"]], [["M7", "M8"]]]

    def test_cut_defers_the_less_severe_of_mixed_tier_units(self) -> None:
        issues = [_issue("C1", "a.py"), _issue("I1", "a.py"), _issue("M1", "a.py")]
        waves = rwv.plan_waves(issues, held=[], done=[], cap=2)
        assert [[sorted(f["issue_ids"]) for f in wave] for wave in waves] == [[["C1", "I1"]], [["M1"]]]

    def test_cut_recurses_until_every_group_fits(self) -> None:
        issues = [_issue(f"M{n}", "a.py") for n in range(1, 4)]
        issues += [_issue("I1", "a.py", fix_kind="judgment", files=["a.py", "b.py"]),
                   _issue("I2", "b.py", fix_kind="judgment", files=["b.py", "c.py"]),
                   _issue("M4", "c.py")]
        waves = rwv.plan_waves(issues, held=[], done=[], cap=2)
        assert all(len(f["issue_ids"]) <= 2 for wave in waves for f in wave)
        planned = sorted(i for wave in waves for f in wave for i in f["issue_ids"])
        assert planned == ["I1", "I2", "M1", "M2", "M3", "M4"]
        assert len(waves) == 2
        for wave in waves:
            seen: set = set()
            for fixer in wave:
                assert not set(fixer["files"]) & seen
                seen |= set(fixer["files"])

    def test_units_linked_through_a_widened_test_share_a_group(self) -> None:
        registry = {"tests/test_ab.py": ["a.py", "b.py"]}
        issues = [_issue("M1", "a.py"), _issue("M2", "b.py")]
        waves = rwv.plan_waves(issues, held=[], done=[], registry=registry)
        assert [f["issue_ids"] for f in waves[0]] == [["M1", "M2"]]

    def test_a_full_wave_still_opens_a_fixer_for_an_unrelated_chunk(self) -> None:
        issues = [_issue(f"M{n}", f"f{n}.py") for n in range(1, 4)]
        waves = rwv.plan_waves(issues, held=[], done=[], cap=1, fixers=1)
        assert [[f["issue_ids"] for f in wave] for wave in waves] == [[["M1"], ["M2"], ["M3"]]]

    def test_held_and_done_excluded(self) -> None:
        waves = rwv.plan_waves([_issue("M1"), _issue("M2"), _issue("M3")], held=["M1"], done=["M3"])
        assert [f["issue_ids"] for w in waves for f in w] == [["M2"]]

    def test_order_m_i_c(self) -> None:
        waves = rwv.plan_waves([_issue("C1"), _issue("I2"), _issue("M10"), _issue("M2")], held=[], done=[])
        assert waves[0][0]["issue_ids"] == ["M2", "M10", "I2", "C1"]

    def test_judgment_needs_opus(self) -> None:
        waves = rwv.plan_waves([_issue("M1"), _issue("M2", fix_kind="judgment")], held=[], done=[])
        assert waves[0][0]["model"] == "opus"

    def test_start_wave(self) -> None:
        assert rwv.plan_waves([_issue("M1")], [], [], start_wave=3)[0][0]["id"] == "w3_fix_1"

    def test_nothing_to_plan(self) -> None:
        assert rwv.plan_waves([], [], []) == []


_REGISTRY = {"tests/test_a.py": ["a.py"], "tests/test_b.py": ["b.py", "c.py"], "tests/test_x.py": ["x.py"]}


def _widened(issues: Sequence[Dict[str, object]], existing: Sequence[str] = ()) -> List[List[tuple]]:
    """``plan_waves`` over ``issues`` with ``_REGISTRY``: (issue ids, parts, files) per fixer per wave."""
    waves = rwv.plan_waves(issues, [], [], registry=_REGISTRY, existing=set(existing))
    return [[(f["issue_ids"], f["parts"], f["files"]) for f in wave] for wave in waves]


_TRACKING = ["docs/PLANS/*.md"]
_PLAN = "docs/PLANS/plan.md"


class TestTrackingPaths:
    def test_is_tracking_uses_fnmatch(self) -> None:
        assert rwv.is_tracking(_PLAN, _TRACKING) and rwv.is_tracking("docs/PLANS/a/b.md", _TRACKING)
        assert not rwv.is_tracking("docs/guide.md", _TRACKING) and not rwv.is_tracking(_PLAN, [])

    def test_tracking_only_issue_is_not_planned(self) -> None:
        issues = [_issue("M1", _PLAN), _issue("M2", "a.py")]
        waves = rwv.plan_waves(issues, [], [], tracking=_TRACKING)
        assert [f["issue_ids"] for w in waves for f in w] == [["M2"]]
        assert rwv.tracking_rows(issues, [], [], _TRACKING) == [("M1", [_PLAN])]

    def test_tracking_rows_skip_held_and_done_ids(self) -> None:
        issues = [_issue("M1", _PLAN), _issue("M2", _PLAN), _issue("M3", _PLAN)]
        assert rwv.tracking_rows(issues, ["M1"], ["M2"], _TRACKING) == [("M3", [_PLAN])]

    def test_mixed_issue_plans_only_its_other_files(self) -> None:
        issue = _issue("I1", "a.py", files=["a.py", _PLAN], fix_kind="judgment")
        waves = rwv.plan_waves([issue], [], [], tracking=_TRACKING)
        assert waves[0][0]["parts"] == {"I1": ["a.py"]} and waves[0][0]["files"] == ["a.py"]
        assert rwv.tracking_rows([issue], [], [], _TRACKING) == []
        assert rwv.mixed_tracking_rows([issue], [], [], _TRACKING) == [("I1", [_PLAN])]

    def test_mixed_tracking_rows_skip_pure_held_and_done_ids(self) -> None:
        issues = [_issue(n, "a.py", files=["a.py", _PLAN]) for n in ("I1", "I2", "I3")]
        issues += [_issue("M1", _PLAN), _issue("M2", "b.py")]
        assert rwv.mixed_tracking_rows(issues, ["I1"], ["I2"], _TRACKING) == [("I3", [_PLAN])]

    def test_named_tracking_path_never_widens(self) -> None:
        issue = _issue("M1", "a.py", fix=["record both in docs/PLANS/plan.md", "edit docs/a.md"])
        waves = rwv.plan_waves([issue], [], [], existing={_PLAN, "docs/a.md"}, tracking=_TRACKING)
        assert waves[0][0]["files"] == ["a.py", "docs/a.md"]

    def test_tracking_doc_no_longer_forces_a_second_wave(self) -> None:
        big = _issue("C1", "a.py", fix_kind="judgment", files=["a.py", "b.py"],
                     fix=["or record both in docs/PLANS/plan.md"])
        docs = [_issue(f"M{n}", _PLAN) for n in (1, 2, 3)]
        before = rwv.plan_waves([big, *docs], [], [], cap=2, existing={_PLAN})
        after = rwv.plan_waves([big, *docs], [], [], cap=2, existing={_PLAN}, tracking=_TRACKING)
        assert len(before) == 2 and len(after) == 1
        assert after[0][0]["issue_ids"] == ["C1"]


class TestSerialLocks:
    _LOCKS = {"tests/test_a.py": ("properties.arcpy",), "tests/test_b.py": ("properties.arcpy",),
              "tests/test_c.py": ("properties.slow",)}
    _REG = {"tests/test_a.py": ["a.py"], "tests/test_b.py": ["b.py"], "tests/test_c.py": ["c.py"],
            "tests/test_d.py": ["d.py"]}

    def _plan(self, issues: Sequence[Dict[str, object]], cap: int = 1) -> List[List[Dict[str, object]]]:
        return rwv.plan_waves(issues, [], [], cap=cap, registry=self._REG, test_locks=self._LOCKS)

    @staticmethod
    def _ids(waves: Sequence[Sequence[Dict[str, object]]]) -> List[List[List[str]]]:
        return [[f["issue_ids"] for f in wave] for wave in waves]

    def test_fixers_sharing_a_lock_go_to_different_waves(self) -> None:
        issues = [_issue("M1", "a.py"), _issue("M2", "b.py")]
        assert self._ids(self._plan(issues)) == [[["M1"]], [["M2"]]]

    def test_different_locks_share_a_wave(self) -> None:
        issues = [_issue("M1", "a.py"), _issue("M2", "c.py")]
        assert self._ids(self._plan(issues)) == [[["M1"], ["M2"]]]

    def test_lock_free_fixer_runs_beside_a_locked_one(self) -> None:
        issues = [_issue("M1", "a.py"), _issue("M2", "d.py")]
        assert self._ids(self._plan(issues)) == [[["M1"], ["M2"]]]

    def test_without_locks_the_same_issues_share_a_wave(self) -> None:
        issues = [_issue("M1", "a.py"), _issue("M2", "b.py")]
        plain = rwv.plan_waves(issues, [], [], cap=1, registry=self._REG)
        assert self._ids(plain) == [[["M1"], ["M2"]]]

    def test_test_file_in_the_issue_files_holds_its_lock(self) -> None:
        issues = [_issue("M1", "tests/test_a.py"), _issue("M2", "b.py")]
        assert self._ids(self._plan(issues)) == [[["M1"]], [["M2"]]]

    def test_lock_holder_with_room_takes_the_next_holder(self) -> None:
        issues = [_issue("M1", "a.py"), _issue("M2", "b.py"), _issue("M3", "d.py")]
        assert self._ids(self._plan(issues, cap=2)) == [[["M1", "M2"], ["M3"]]]

    def test_fixer_record_names_its_locks(self) -> None:
        issues = [_issue("M1", "a.py"), _issue("M2", "c.py"), _issue("M3", "d.py")]
        waves = rwv.plan_waves(issues, [], [], cap=6, fixers=1, registry=self._REG, test_locks=self._LOCKS)
        assert [(f["issue_ids"], f["locks"]) for w in waves for f in w] == [
            (["M1", "M2", "M3"], ["properties.arcpy", "properties.slow"])]
        assert all("locks" not in f for w in self._plan([_issue("M3", "d.py")]) for f in w)


class TestFixPaths:
    def test_tokens_in_fix_text(self) -> None:
        issue = _issue("M1", fix=["Edit docs/guide.md and `scripts/x/y.py:12`.",
                                  "see ./a/b.json, or http://h/z; end in docs/end.md."])
        assert rwv.fix_paths(issue) == ["docs/guide.md", "scripts/x/y.py", "a/b.json", "docs/end.md"]

    def test_no_paths(self) -> None:
        assert rwv.fix_paths(_issue("M1", fix=["rename the helper", "a/b without extension",
                                               "see ../outside/x.py"])) == []


class TestWidenedFileSets:
    def test_registry_tests_and_existing_fix_paths_join_files(self) -> None:
        issue = _issue("M1", "a.py", fix=["also update docs/a.md and docs/missing.md"])
        assert _widened([issue], existing=["docs/a.md"]) == [
            [(["M1"], {"M1": ["a.py"]}, ["a.py", "docs/a.md", "tests/test_a.py"])]]

    def test_widened_files_keep_wave_disjoint(self) -> None:
        issues = [_issue(f"M{n}", "a.py") for n in range(1, 7)] + [_issue("M7", "tests/test_a.py")]
        first = [f"M{n}" for n in range(1, 7)]
        assert _widened(issues) == [
            [(first, {i: ["a.py"] for i in first}, ["a.py", "tests/test_a.py"])],
            [(["M7"], {"M7": ["tests/test_a.py"]}, ["tests/test_a.py"])],
        ]

    def test_split_parts_widen_per_file(self) -> None:
        issues = [_issue(f"M{n}", "a.py") for n in range(1, 7)]
        issues.append(_issue("M7", "b.py", files=["b.py", "a.py"]))
        first = [f"M{n}" for n in range(1, 7)]
        assert _widened(issues) == [
            [(first, {i: ["a.py"] for i in first}, ["a.py", "tests/test_a.py"]),
             (["M7"], {"M7": ["b.py"]}, ["b.py", "tests/test_b.py"])],
            [(["M7"], {"M7": ["a.py"]}, ["a.py", "tests/test_a.py"])],
        ]

    def test_directory_target_covers_descendants(self) -> None:
        registry = {"tests/test_pkg.py": ["pkg"], "tests/test_slash.py": ["pkg/sub/"],
                    "tests/test_other.py": ["pkg_other"], "tests/test_file.py": ["pkg/sub/m.py"]}
        assert rwv.registry_tests(["pkg/sub/m.py"], registry) == [
            "tests/test_pkg.py", "tests/test_slash.py", "tests/test_file.py"]
        assert rwv.registry_tests(["pkg_other.py", "pkgx/m.py"], registry) == []
        waves = rwv.plan_waves([_issue("M1", "pkg/sub/m.py")], [], [],
                               registry={"tests/test_pkg.py": ["pkg"]})
        assert waves[0][0]["files"] == ["pkg/sub/m.py", "tests/test_pkg.py"]

    def test_issue_files_never_widen_twice(self) -> None:
        issue = _issue("I1", "a.py", files=["a.py", "tests/test_a.py"], fix_kind="judgment",
                       fix=["edit tests/test_a.py"])
        assert _widened([issue], existing=["tests/test_a.py"]) == [
            [(["I1"], {"I1": ["a.py", "tests/test_a.py"]}, ["a.py", "tests/test_a.py"])]]
