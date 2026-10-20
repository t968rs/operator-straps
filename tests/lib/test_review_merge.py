"""Behavioral tests for harness_lib.review_merge (pr-review merge, verdict, document, waves and closeout).

The PR #1558 fixture (``fixtures/pr1558_issues.json``) carries the real issue/file list of that review, with
each issue's primary file, other files, lines and a mechanical/judgment guess. Review documents are checked
against the ``PR_REVIEW.schema.json`` that ``schema_path`` resolves for a throwaway project (the project's
pinned copy, else the plugin's) and ``harness_lib.validation.pr_json_validation.validate_issue_counts``.
"""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Mapping, Optional, Sequence

import pytest

from harness_lib import review_merge as rmg
from harness_lib.config import activate, load_config
from harness_lib.project import plugin_root, schema_path
from harness_lib.review_models import FixReport, ReviewerReport

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pr1558_issues.json"
_SCHEMA = "PR_REVIEW.schema.json"
_HEAD = "a9630b7"
_TODAY = "2026-10-10"


@pytest.fixture
def project(make_project) -> Path:
    """An activated throwaway project without a pinned schema copy (the plugin's schema governs)."""
    root = make_project(config={})
    activate(load_config(root))
    return root


@pytest.fixture
def hook_validation() -> ModuleType:
    """The schema hook's issue-count module, ``harness_lib.validation.pr_json_validation``."""
    return importlib.import_module("harness_lib.validation.pr_json_validation")


def _finding(file: str = "pr_sum.py", lines: Optional[str] = None, **overrides: object) -> Dict[str, object]:
    """A finding mapping on ``file``; ``overrides`` replace keys."""
    base: Dict[str, object] = {
        "severity": "important", "name": "Budget hides sources", "summary": "s", "fix": ["f"],
        "file": file, "lines": lines, "fix_kind": "mechanical",
    }
    base.update(overrides)
    return base


def _report(slot: str, *findings: Mapping[str, object], strengths: Sequence[str] = ()) -> ReviewerReport:
    """A ``ReviewerReport`` for ``slot``."""
    data = {"reviewer": slot, "findings": list(findings), "strengths": strengths}
    return ReviewerReport.model_validate(data)


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


class TestLineRanges:
    @pytest.mark.parametrize("raw, expected", [
        ("9,146-155", ((9, 9), (146, 155))), ("12", ((12, 12),)), (None, ()), ("8-5", ((5, 8),)),
        ("1-2, 5", ((1, 2), (5, 5))),
    ])
    def test_parse(self, raw: Optional[str], expected: tuple) -> None:
        assert rmg.line_ranges(raw) == expected

    def test_malformed_raises(self) -> None:
        with pytest.raises(ValueError):
            rmg.line_ranges("pr_sum.py:9")


class TestMergeFindings:
    def test_three_reviewers_one_issue(self) -> None:
        issues = rmg.merge_findings([
            _report("runtime", _finding(lines="146-155", fix=["a"])),
            _report("overall", _finding(lines="150", fix=["b", "a"])),
            _report("roast", _finding(lines="152-158")),
        ])
        assert len(issues) == 1
        issue = issues[0]
        assert issue["id"] == "I1" and issue["both_reviewers"] is True
        assert issue["reviewer"] == "runtime, overall, roast"
        assert issue["lines"] == "146-158"
        assert issue["fix"] == ["a", "b", "f"]

    def test_pairwise_ranges_not_span(self) -> None:
        issues = rmg.merge_findings([
            _report("runtime", _finding(lines="9,146-155")),
            _report("overall", _finding(lines="86-92,196-198")),
        ])
        assert len(issues) == 2

    def test_window_edge(self) -> None:
        near = rmg.merge_findings([_report("a", _finding(lines="10")), _report("b", _finding(lines="13"))])
        far = rmg.merge_findings([_report("a", _finding(lines="10")), _report("b", _finding(lines="14"))])
        assert (len(near), len(far)) == (1, 2)

    def test_chain_does_not_merge_transitively(self) -> None:
        issues = rmg.merge_findings([
            _report("a", _finding(lines="10")), _report("b", _finding(lines="13")),
            _report("c", _finding(lines="16")),
        ])
        assert [(i["lines"], i["reviewer"]) for i in issues] == [("10,13", "a, b"), ("16", "c")]

    def test_no_lines_never_merge_but_are_candidates(self) -> None:
        issues = rmg.merge_findings([_report("a", _finding()), _report("b", _finding())])
        assert len(issues) == 2
        assert rmg.merge_candidates(issues) == [("I1", "I2")]

    def test_different_file_never_merges(self) -> None:
        issues = rmg.merge_findings([
            _report("a", _finding("x.py", "10")), _report("b", _finding("y.py", "10")),
        ])
        assert len(issues) == 2

    def test_highest_severity_wins(self) -> None:
        issues = rmg.merge_findings([
            _report("a", _finding(lines="5", severity="minor", name="minor name")),
            _report("b", _finding(lines="6", severity="critical", name="critical name")),
        ])
        assert [i["id"] for i in issues] == ["C1"]
        assert issues[0]["name"] == "critical name"

    def test_judgment_wins(self) -> None:
        issues = rmg.merge_findings([
            _report("a", _finding(lines="5")), _report("b", _finding(lines="5", fix_kind="judgment")),
        ])
        assert issues[0]["fix_kind"] == "judgment"

    def test_same_reviewer_merge_is_not_both_reviewers(self) -> None:
        issues = rmg.merge_findings([_report("a", _finding(lines="5"), _finding(lines="6"))])
        assert len(issues) == 1 and "both_reviewers" not in issues[0]

    def test_ids_ordered_by_file_line_name(self) -> None:
        issues = rmg.merge_findings([_report(
            "a", _finding("b.py", "5", name="z"), _finding("a.py", None, name="a"),
            _finding("a.py", "50", name="m"), _finding("a.py", "1", severity="minor"),
        )])
        assert [(i["id"], i["file"], i.get("lines")) for i in issues] == [
            ("I1", "a.py", "50"), ("I2", "a.py", None), ("I3", "b.py", "5"), ("M1", "a.py", "1"),
        ]

    def test_also_emits_files_with_file_first(self) -> None:
        issue = rmg.merge_findings([_report("a", _finding(lines="5", also=["docs/x.md"]))])[0]
        assert issue["file"] == issue["files"][0] == "pr_sum.py"
        assert issue["files"] == ["pr_sum.py", "docs/x.md"]

    def test_no_also_emits_no_files(self) -> None:
        assert "files" not in rmg.merge_findings([_report("a", _finding(lines="5"))])[0]


class TestMergeCandidates:
    def test_shared_also_file_counts(self) -> None:
        issues = [_issue("I1", "a.py", name="pr sum budget"),
                  _issue("I2", "b.py", name="pr sum budget order", files=["b.py", "a.py"])]
        assert rmg.merge_candidates(issues) == [("I1", "I2")]

    def test_low_jaccard_not_candidate(self) -> None:
        issues = [_issue("I1", name="alpha beta gamma"), _issue("I2", name="delta beta epsilon")]
        assert rmg.merge_candidates(issues) == []

    def test_disjoint_files_not_candidate(self) -> None:
        assert rmg.merge_candidates([_issue("I1", "a.py"), _issue("I2", "b.py")]) == []


class TestAppendFindings:
    def test_ids_continue_per_tier_in_merge_order(self) -> None:
        existing = [_issue("C1"), _issue("I1"), _issue("I4"), _issue("M2")]
        report = _report("ext", _finding("b.py", "5", name="z"), _finding("a.py", None, name="a"),
                         _finding("a.py", "50", name="m"), _finding("a.py", "1", severity="minor"),
                         _finding("c.py", "1", severity="critical"))
        added = rmg.append_findings(existing, report)
        assert [(i["id"], i["file"], i.get("lines")) for i in added] == [
            ("C2", "c.py", "1"), ("I5", "a.py", "50"), ("I6", "a.py", None), ("I7", "b.py", "5"),
            ("M3", "a.py", "1"),
        ]
        assert {i["reviewer"] for i in added} == {"ext"}

    def test_conversion_matches_merge_when_nothing_groups(self) -> None:
        report = _report("ext", _finding(lines="5", also=["docs/x.md"]), _finding(lines="50", fix=["g"]))
        assert rmg.append_findings([], report) == rmg.merge_findings([report])

    def test_same_lines_findings_stay_separate(self) -> None:
        report = _report("ext", _finding(lines="5", name="Beta", summary="second"),
                         _finding(lines="5", name="Alpha", summary="first"))
        assert len(rmg.merge_findings([report])) == 1
        added = rmg.append_findings([], report)
        assert [(i["id"], i["name"], i["summary"]) for i in added] == [
            ("I1", "Alpha", "first"), ("I2", "Beta", "second"),
        ]
        assert all(i["lines"] == "5" for i in added)

    def test_empty_tier_starts_at_one_and_existing_untouched(self) -> None:
        existing = [_issue("I2")]
        before = copy.deepcopy(existing)
        added = rmg.append_findings(existing, _report("ext", _finding(severity="minor")))
        assert [i["id"] for i in added] == ["M1"] and existing == before

    def test_cross_candidates_pair_existing_with_new_only(self) -> None:
        existing = [_issue("I1", "a.py", name="pr sum budget"), _issue("I2", "a.py", name="pr sum budget x")]
        new = [_issue("I3", "a.py", name="pr sum budget order"), _issue("I4", "a.py", name="pr sum budget y")]
        assert rmg.cross_candidates(existing, new) == [("I1", "I3"), ("I2", "I3"), ("I1", "I4"), ("I2", "I4")]


def _tiers(*ids: str) -> Dict[str, List[Dict[str, object]]]:
    """Issues keyed by tier for ``ids``."""
    return rmg.issues_by_severity([_issue(i) for i in ids])


def _res(issue_id: str, status: str = "RESOLVED") -> Dict[str, str]:
    """A resolution entry."""
    return {"id": issue_id, "status": status, "date": _TODAY, "evidence": f"{_HEAD} - x"}


class TestVerdict:
    def test_critical(self) -> None:
        verdict = rmg.compute_verdict(_tiers("C1", "C2", "I1"), [], [], [])
        assert verdict == "NOT READY TO MERGE - critical: C1, C2"

    def test_important(self) -> None:
        verdict = rmg.compute_verdict(_tiers("C1", "I1", "I4", "M1"), [_res("C1")], [], [])
        assert verdict == "NOT READY TO MERGE - important: I1, I4"

    def test_minor_pending(self) -> None:
        verdict = rmg.compute_verdict(_tiers("I1", "M1", "M2", "M3"), [_res("I1"), _res("M2")], [], [])
        assert verdict == "NOT READY TO MERGE - minor findings pending Phase 5: M1, M3"

    def test_ready(self) -> None:
        bubble_up = [{"id": "M2", "classification": "out_of_scope", "reason": "r"}]
        verdict = rmg.compute_verdict(
            _tiers("I1", "M1", "M2"), [_res("I1"), _res("M1", "CLOSED_NO_ACTION")], ["M2"], bubble_up,
        )
        assert verdict == "READY TO MERGE - 2 of 3 findings resolved, 1 bubbled"

    def test_downgraded_is_unresolved(self) -> None:
        verdict = rmg.compute_verdict(_tiers("I1"), [_res("I1", "DOWNGRADED_TO_MINOR")], [], [])
        assert verdict == "NOT READY TO MERGE - important: I1"

    def test_downgraded_only_minor_is_pending(self) -> None:
        resolutions = [_res("I1"), _res("M1", "DOWNGRADED_TO_MINOR")]
        verdict = rmg.compute_verdict(_tiers("I1", "M1"), resolutions, [], [])
        assert verdict == "NOT READY TO MERGE - minor findings pending Phase 5: M1"

    def test_downgraded_then_closed_minor_is_ready(self) -> None:
        resolutions = [_res("M1", "DOWNGRADED_TO_MINOR"), _res("M1", "CLOSED_NO_ACTION")]
        verdict = rmg.compute_verdict(_tiers("M1"), resolutions, [], [])
        assert verdict == "READY TO MERGE - 1 of 1 findings resolved, 0 bubbled"

    def test_ready_verdict_passes_hook_count_check(self, hook_validation: ModuleType) -> None:
        resolutions = [_res("I1"), _res("M1", "DOWNGRADED_TO_MINOR"), _res("M1")]
        doc = {"issues": _tiers("I1", "M1", "M2"), "post_review_resolutions": resolutions,
               "bubbles": ["M2"], "bubble_up": []}
        doc["verdict"] = rmg.compute_verdict(doc["issues"], resolutions, ["M2"], [])
        assert doc["verdict"].startswith("READY TO MERGE")
        hook_validation.validate_issue_counts(doc)

    def test_bubbled_important_is_unresolved(self) -> None:
        assert rmg.compute_verdict(_tiers("I1"), [], ["I1"], []).startswith("NOT READY TO MERGE - important")

    def test_natural_id_order(self) -> None:
        verdict = rmg.compute_verdict(_tiers("C10", "C2"), [], [], [])
        assert verdict == "NOT READY TO MERGE - critical: C2, C10"

    def test_no_issues(self) -> None:
        verdict = rmg.compute_verdict(_tiers(), [], [], [])
        assert verdict == "READY TO MERGE - 0 of 0 findings resolved, 0 bubbled"

    @pytest.mark.parametrize("resolutions, bubbles, bubble_up", [
        ([_res("I9")], [], []), ([], ["M7"], []),
        ([], [], [{"id": "C3", "classification": "out_of_scope", "reason": "r"}]),
    ])
    def test_orphan_raises(self, resolutions: list, bubbles: list, bubble_up: list) -> None:
        with pytest.raises(ValueError, match="orphan"):
            rmg.compute_verdict(_tiers("I1"), resolutions, bubbles, bubble_up)

    def test_orphan_without_tier_prefix_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="orphan.*X9"):
            rmg.compute_verdict(_tiers("I1"), [_res("X9"), _res("M2")], ["Q1"], [])


class TestRegrade:
    def test_moves_to_end_of_target_tier(self) -> None:
        issues = [_issue("I1"), _issue("I3"), _issue("M1"), _issue("M4")]
        out = rmg.regrade(issues, "I3", "minor")
        assert [i["id"] for i in out] == ["I1", "M1", "M4", "M5"]
        assert issues[1]["id"] == "I3"

    def test_coerces_letter(self) -> None:
        assert [i["id"] for i in rmg.regrade([_issue("M1")], "M1", "C")] == ["C1"]

    def test_unknown_or_same_tier_raises(self) -> None:
        with pytest.raises(ValueError):
            rmg.regrade([_issue("I1")], "I2", "minor")
        with pytest.raises(ValueError):
            rmg.regrade([_issue("I1")], "I1", "important")


class TestMergeIds:
    def test_absorbs_dropped(self) -> None:
        issues = [_issue("I1", "a.py", fix=["x"], lines="5"),
                  _issue("I3", "b.py", fix=["y", "x"], reviewer="docs"),
                  _issue("M2", "a.py", fix=["x"], lines="6-7", reviewer="roast", fix_kind="judgment")]
        out = rmg.merge_ids(issues, "I1", ["I3", "M2"])
        assert [i["id"] for i in out] == ["I1"]
        kept = out[0]
        assert kept["fix"] == ["x", "y"]
        assert kept["files"] == ["a.py", "b.py"]
        assert kept["lines"] == "5-7"
        assert kept["reviewer"] == "runtime, docs, roast" and kept["both_reviewers"] is True
        assert kept["fix_kind"] == "judgment"

    def test_dropping_higher_severity_raises(self) -> None:
        with pytest.raises(ValueError):
            rmg.merge_ids([_issue("I1"), _issue("C1")], "I1", ["C1"])

    @pytest.mark.parametrize("keep, drop", [("I9", ["I1"]), ("I1", ["I9"]), ("I1", ["I1"])])
    def test_bad_ids_raise(self, keep: str, drop: List[str]) -> None:
        with pytest.raises(ValueError):
            rmg.merge_ids([_issue("I1"), _issue("I2")], keep, drop)


class TestSlugify:
    @pytest.mark.parametrize("title, slug", [
        ("Skill-Add: `pr-review-boss`", "Skill-Add_pr-review-boss"),
        ("9058 skill pr summaries", "9058_skill_pr_summaries"),
        ("  a/b (c)\tv1.2  ", "ab_c_v1.2"),
        ("Fix: x!", "Fix_x"),
    ])
    def test_rule(self, title: str, slug: str) -> None:
        assert rmg.slugify_title(title) == slug


def _meta() -> Dict[str, object]:
    """Review metadata for ``review_document``."""
    return {"pr": 1558, "pr_title": "9058 skill pr summaries", "branch": "9058-SKILL-PrSummaries",
            "base_branch": "dev", "base_sha": "765e698eb", "head_sha": "a9630b78d", "review_date": _TODAY,
            "stats": {"additions": 10, "deletions": 2, "files_changed": 3},
            "scoped_review_files": ["inline:runtime"]}


def _dispatch_time() -> Dict[str, object]:
    """A Phase 1 dispatch_time block."""
    return {
        "pr_metadata_check": {"command": "gh pr view 1558", "stdout": "{\"state\":\"OPEN\"}",
                              "result": "OK (state=OPEN)"},
        "structural_guards_check": {"applies": False, "command": "", "stdout_tail": "",
                                    "result": "SKIPPED (no CICD/test-infra paths in PR)"},
    }


def _pre_fix_time() -> Dict[str, object]:
    """A populated Phase 4 pre_fix_time block."""
    return {
        "current_branch_check": {"command": "git rev-parse", "stdout": "b", "result": "OK"},
        "branch_match_check": {"assertion": "CURRENT_BRANCH == headRefName", "current_branch": "b",
                               "head_ref_name": "b", "result": "OK (match)"},
        "clean_tree_check": {"command": "git status --porcelain", "stdout": "", "result": "OK (empty)"},
        "sha_ancestry_check": {"base_sha": "x", "head_sha": "y", "base_ancestor_command": "c",
                               "base_ancestor_exit": 0, "head_ancestor_command": "c", "head_ancestor_exit": 0,
                               "result": "OK (both ancestors)"},
        "base_branch_recorded": {"source": "gh", "value": "dev", "result": "OK (recorded)"},
    }


def _draft(issues: Sequence[Dict[str, object]]) -> Dict[str, object]:
    """A draft as ``merge`` writes it."""
    return {"issues": list(issues), "strengths": ["clean seams"], "reviewers": ["runtime (opus)"],
            "amend": []}


class TestReviewDocument:
    def test_key_order_and_defaults(self) -> None:
        doc = rmg.review_document(_meta(), _draft([_issue("I1"), _issue("M1")]), _dispatch_time())
        assert list(doc) == [
            "schema_ref", "version", "pr", "pr_title", "branch", "base_branch", "base_sha", "head_sha",
            "review_date", "verdict", "stats", "reviewers", "scoped_review_files", "bubbles", "strengths",
            "issues", "bubble_up", "verification_log",
        ]
        assert doc["version"] == "2.1.0" and doc["bubbles"] == [] and doc["bubble_up"] == []
        assert doc["verification_log"]["pre_fix_time"] == rmg.PENDING
        assert doc["verdict"] == "NOT READY TO MERGE - important: I1"
        assert [i["id"] for i in doc["issues"]["minor"]] == ["M1"] and doc["issues"]["critical"] == []

    def test_valid_against_schema_and_counts(self, project: Path, hook_validation: ModuleType) -> None:
        issues = rmg.merge_findings([_report("runtime", _finding(lines="5", also=["docs/x.md"]))])
        doc = rmg.review_document(_meta(), _draft(issues), _dispatch_time())
        assert rmg.validate_review(doc, project) == []
        hook_validation.validate_issue_counts(doc)

    def test_pending_literal_matches_schema(self, project: Path) -> None:
        schema = json.loads(schema_path(_SCHEMA, load_config(project)).read_text("utf-8"))
        canonical = schema["properties"]["verification_log"]["oneOf"][1]
        assert canonical["properties"]["pre_fix_time"]["oneOf"][0]["const"] == rmg.PENDING


def _pin_schema(root: Path, extra_required: str) -> Path:
    """Pin a copy of the plugin's PR_REVIEW schema (and its siblings) in ``root``'s ``schemas_dir`` that
    also requires ``extra_required``; return the pinned schema path."""
    pinned_dir = root / load_config(root).schemas_dir
    pinned_dir.mkdir(parents=True, exist_ok=True)
    for sibling in (plugin_root() / "schemas").glob("*.schema.json"):
        (pinned_dir / sibling.name).write_text(sibling.read_text(encoding="utf-8"), encoding="utf-8")
    pinned = pinned_dir / _SCHEMA
    schema = json.loads(pinned.read_text(encoding="utf-8"))
    schema["required"] = [*schema["required"], extra_required]
    pinned.write_text(json.dumps(schema), encoding="utf-8")
    return pinned


class TestSchemaRef:
    def test_without_pinned_copy_is_the_plugin_id(self, project: Path) -> None:
        plugin_id = json.loads((plugin_root() / "schemas" / _SCHEMA).read_text("utf-8"))["$id"]
        cfg = load_config(project)
        assert rmg.schema_ref_for(project / "docs" / "PR_REVIEWS" / "0001_x.json", cfg) == plugin_id
        assert rmg.review_document(_meta(), _draft([]), _dispatch_time())["schema_ref"] == plugin_id

    def test_pinned_copy_is_relative_to_the_review_file(self, project: Path) -> None:
        _pin_schema(project, "pinned_marker")
        cfg = load_config(project)
        ref = rmg.schema_ref_for(project / "docs" / "PR_REVIEWS" / "0001_x.json", cfg)
        assert ref == f"../../{cfg.schemas_dir.strip('/')}/{_SCHEMA}"

    def test_review_document_takes_the_ref(self) -> None:
        doc = rmg.review_document(_meta(), _draft([]), _dispatch_time(), schema_ref="../x.json")
        assert doc["schema_ref"] == "../x.json"

    def test_validate_review_uses_the_pinned_copy(self, project: Path) -> None:
        doc = rmg.review_document(_meta(), _draft([_issue("M1")]), _dispatch_time())
        assert not any("pinned_marker" in p for p in rmg.validate_review(doc, project))
        _pin_schema(project, "pinned_marker")
        assert any("pinned_marker" in p for p in rmg.validate_review(doc, project))

    def test_default_repo_is_the_active_project(self, project: Path) -> None:
        _pin_schema(project, "pinned_marker")
        doc = rmg.review_document(_meta(), _draft([_issue("M1")]), _dispatch_time())
        assert any("pinned_marker" in p for p in rmg.validate_review(doc))


class TestValidateReview:
    @staticmethod
    def _doc() -> Dict[str, object]:
        return rmg.review_document(_meta(), _draft([_issue("M1")]), _dispatch_time())

    def test_schema_violation(self, project: Path) -> None:
        doc = self._doc()
        doc["issues"]["minor"][0]["fix_kind"] = "easy"
        assert any("fix_kind" in p for p in rmg.validate_review(doc, project))

    def test_pending_with_resolution(self, project: Path) -> None:
        doc = self._doc()
        doc["post_review_resolutions"] = [_res("M1")]
        assert any("pending" in p for p in rmg.validate_review(doc, project))

    def test_pending_with_ready(self, project: Path) -> None:
        doc = self._doc()
        doc["verdict"] = "READY TO MERGE - x"
        problems = rmg.validate_review(doc, project)
        assert any("pending" in p for p in problems)
        assert any("unaccounted" in p for p in problems)

    def test_orphan(self, project: Path) -> None:
        doc = self._doc()
        doc["bubbles"] = ["M9"]
        assert any("orphan" in p for p in rmg.validate_review(doc, project))


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
    """Per-fixer invariants: id, cap in units, parts keys and order, files and model."""
    assert fixer["id"].startswith(f"w{number}_fix_")
    assert 1 <= _units_of(fixer, by_id) <= rmg.MAX_ISSUES_PER_FIXER
    assert list(fixer["parts"]) == fixer["issue_ids"]
    assert fixer["issue_ids"] == sorted(fixer["issue_ids"], key=lambda i: ("MIC".index(i[0]), int(i[1:])))
    for issue_id, files in fixer["parts"].items():
        assert set(files) <= _files_of(by_id[issue_id])
        if not _is_split(by_id[issue_id]):
            assert set(files) == _files_of(by_id[issue_id])
    assert set(fixer["files"]) == {f for files in fixer["parts"].values() for f in files}
    kinds = {by_id[i]["fix_kind"] for i in fixer["issue_ids"]}
    assert fixer["model"] == ("haiku" if kinds == {"mechanical"} else "opus")


class TestPlanWaves:
    @pytest.mark.parametrize("held", [["M20"], []])
    def test_pr1558_fixture(self, held: List[str]) -> None:
        issues = _fixture_issues()
        by_id = {i["id"]: i for i in issues}
        waves = rmg.plan_waves(issues, held=held, done=[])
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
        waves = rmg.plan_waves(issues, held=[], done=[])
        rows = [[(f["issue_ids"], f["parts"], f["files"]) for f in wave] for wave in waves]
        first = [f"M{n}" for n in range(1, 7)]
        assert rows == [
            [(first, {i: ["a.py"] for i in first}, ["a.py"]), (["M7"], {"M7": ["b.py"]}, ["b.py"])],
            [(["M7"], {"M7": ["a.py"]}, ["a.py"])],
        ]

    def test_parts_of_one_issue_in_one_fixer_merge(self) -> None:
        waves = rmg.plan_waves([_issue("M1", "a.py", files=["a.py", "b.py"])], held=[], done=[])
        assert [(f["issue_ids"], f["parts"]) for f in waves[0]] == [(["M1"], {"M1": ["a.py", "b.py"]})]

    def test_judgment_multi_file_stays_whole(self) -> None:
        issues = [_issue(f"M{n}", "a.py") for n in range(1, 6)]
        issues.append(_issue("I1", "b.py", files=["b.py", "a.py"], fix_kind="judgment"))
        waves = rmg.plan_waves(issues, held=[], done=[])
        holders = [f for wave in waves for f in wave if "I1" in f["parts"]]
        assert len(holders) == 1 and holders[0]["parts"]["I1"] == ["b.py", "a.py"]
        assert holders[0]["model"] == "opus"

    def test_cap_counts_parts(self) -> None:
        issues = [_issue(f"M{n}", f"f{n}.py", files=[f"f{n}.py", f"g{n}.py"]) for n in range(1, 5)]
        waves = rmg.plan_waves(issues, held=[], done=[])
        assert all(sum(len(v) for v in f["parts"].values()) <= rmg.MAX_ISSUES_PER_FIXER
                   for wave in waves for f in wave)

    def test_eight_on_one_file_split_across_waves(self) -> None:
        waves = rmg.plan_waves([_issue(f"M{n}") for n in range(1, 9)], held=[], done=[])
        assert [[len(f["issue_ids"]) for f in wave] for wave in waves] == [[6], [2]]

    def test_disjoint_chunks_share_a_fixer(self) -> None:
        waves = rmg.plan_waves([_issue("M1", "a.py"), _issue("M2", "b.py")], held=[], done=[])
        assert [f["issue_ids"] for f in waves[0]] == [["M1", "M2"]]

    def test_held_and_done_excluded(self) -> None:
        waves = rmg.plan_waves([_issue("M1"), _issue("M2"), _issue("M3")], held=["M1"], done=["M3"])
        assert [f["issue_ids"] for w in waves for f in w] == [["M2"]]

    def test_order_m_i_c(self) -> None:
        waves = rmg.plan_waves([_issue("C1"), _issue("I2"), _issue("M10"), _issue("M2")], held=[], done=[])
        assert waves[0][0]["issue_ids"] == ["M2", "M10", "I2", "C1"]

    def test_judgment_needs_opus(self) -> None:
        waves = rmg.plan_waves([_issue("M1"), _issue("M2", fix_kind="judgment")], held=[], done=[])
        assert waves[0][0]["model"] == "opus"

    def test_start_wave(self) -> None:
        assert rmg.plan_waves([_issue("M1")], [], [], start_wave=3)[0][0]["id"] == "w3_fix_1"

    def test_nothing_to_plan(self) -> None:
        assert rmg.plan_waves([], [], []) == []


def _review(*issues: Dict[str, object], **extra: object) -> Dict[str, object]:
    """A post-Phase-4 review document holding ``issues``."""
    doc = rmg.review_document(_meta(), _draft(list(issues)), _dispatch_time())
    doc["verification_log"]["pre_fix_time"] = _pre_fix_time()
    doc.update(extra)
    return doc


def _fix(fixer: str, fixed: Sequence[Dict[str, object]] = (),
         bubbled: Sequence[Dict[str, object]] = ()) -> FixReport:
    """A ``FixReport``."""
    return FixReport.model_validate({"fixer": fixer, "fixed": list(fixed), "bubbled": list(bubbled)})


def _fixed(issue_id: str, *files: str, what: str = "w") -> FixReport:
    """``w1_fix_1`` report fixing ``issue_id`` in ``files``."""
    return _fix("w1_fix_1", [{"id": issue_id, "what": what, "files": list(files)}])


def _closeout(review: Dict[str, object], fixes: Sequence[FixReport], changed: Sequence[str] = (),
              created: Sequence[str] = (), closed: Optional[Mapping[str, str]] = None) -> tuple:
    """``apply_closeout`` with one fixer bin ``w1_fix_1`` over a.py and b.py."""
    return rmg.apply_closeout(review, fixes, {"w1_fix_1": ["a.py", "b.py"]}, set(changed), set(created),
                              _HEAD, _TODAY, closed or {})


class TestCloseout:
    def test_validated_fix_resolves(self, project: Path, hook_validation: ModuleType) -> None:
        review = _review(_issue("M1", "a.py"))
        doc, problems = _closeout(review, [_fixed("M1", "a.py", what="wrapped")], changed=["a.py"])
        assert problems == []
        entry = doc["post_review_resolutions"][0]
        assert entry["status"] == "RESOLVED" and entry["evidence"].startswith(f"{_HEAD} ")
        assert entry["evidence"].endswith("- wrapped")
        assert doc["verdict"] == "READY TO MERGE - 1 of 1 findings resolved, 0 bubbled"
        assert rmg.validate_review(doc, project) == []
        hook_validation.validate_issue_counts(doc)
        assert "post_review_resolutions" not in review

    def test_unchanged_file_is_problem(self) -> None:
        doc, problems = _closeout(_review(_issue("M1", "a.py")), [_fixed("M1", "a.py")])
        assert problems and "M1" in problems[0]
        assert doc.get("post_review_resolutions", []) == []

    def test_new_file_accepted(self) -> None:
        fix = _fixed("M1", "a.py", "new/c.py")
        doc, problems = _closeout(_review(_issue("M1", "a.py")), [fix], changed=["a.py", "new/c.py"],
                                  created=["new/c.py"])
        assert problems == [] and len(doc["post_review_resolutions"]) == 1

    def test_outside_bin_is_problem(self) -> None:
        fix = _fixed("M1", "a.py", "z.py")
        doc, problems = _closeout(_review(_issue("M1", "a.py")), [fix], changed=["a.py", "z.py"])
        assert problems and doc.get("post_review_resolutions", []) == []

    def test_entry_without_own_file_is_problem(self) -> None:
        review = _review(_issue("M1", "a.py"), _issue("M2", "b.py"))
        doc, problems = _closeout(review, [_fixed("M1", "b.py")], changed=["b.py"])
        assert any("M1 (w1_fix_1)" in p and "own files (a.py)" in p for p in problems)
        assert doc.get("post_review_resolutions", []) == []

    def test_entry_with_also_file_and_extra_resolves(self) -> None:
        review = _review(_issue("M1", "z.py", files=["z.py", "b.py"]))
        doc, problems = _closeout(review, [_fixed("M1", "a.py", "b.py")], changed=["a.py", "b.py"])
        assert problems == [] and [r["id"] for r in doc["post_review_resolutions"]] == ["M1"]

    def test_unknown_fixer_is_problem(self) -> None:
        fix = _fix("w9_fix_1", [{"id": "M1", "what": "w", "files": ["a.py"]}])
        doc, problems = _closeout(_review(_issue("M1", "a.py")), [fix], changed=["a.py"])
        assert problems and doc.get("post_review_resolutions", []) == []

    def test_existing_resolution_not_duplicated(self) -> None:
        review = _review(_issue("M1", "a.py"), post_review_resolutions=[_res("M1")])
        doc, problems = _closeout(review, [_fixed("M1", "a.py")], changed=["a.py"])
        assert problems == [] and len(doc["post_review_resolutions"]) == 1

    def test_closed(self) -> None:
        doc, problems = _closeout(_review(_issue("M1")), [], closed={"M1": "answered by squash-merge"})
        entry = doc["post_review_resolutions"][0]
        assert problems == [] and entry["status"] == "CLOSED_NO_ACTION"
        assert entry["evidence"].startswith(f"{_HEAD} ") and "answered by squash-merge" in entry["evidence"]

    def test_unknown_closed_id_is_problem(self) -> None:
        _, problems = _closeout(_review(_issue("M1")), [], closed={"M9": "x"})
        assert problems

    def test_fixer_bubble(self, project: Path) -> None:
        bubble = {"id": "I1", "classification": "architectural_ambiguity", "reason": "two options"}
        doc, problems = _closeout(_review(_issue("I1"), _issue("M1")), [_fix("w1_fix_1", bubbled=[bubble])])
        assert problems == []
        assert doc["bubbles"] == ["I1"] and doc["bubble_up"] == [bubble]
        assert rmg.validate_review(doc, project) == []

    def test_bubble_of_unassigned_id_rejected(self) -> None:
        bubble = {"id": "M2", "classification": "out_of_scope", "reason": "not mine"}
        review = _review(_issue("M1", "a.py"), _issue("M2", "b.py"))
        doc, problems = rmg.apply_closeout(review, [_fix("w1_fix_1", bubbled=[bubble])],
                                           {"w1_fix_1": ["a.py", "b.py"]}, set(), set(), _HEAD, _TODAY, {},
                                           parts={"w1_fix_1": {"M1": ["a.py"]}})
        assert problems and "M2" in problems[0] and "not assigned" in problems[0]
        assert doc["bubbles"] == [] and doc["bubble_up"] == []

    def test_bubble_from_unplanned_fixer_rejected(self) -> None:
        bubble = {"id": "M1", "classification": "out_of_scope", "reason": "r"}
        doc, problems = _closeout(_review(_issue("M1", "a.py")), [_fix("w9_fix_1", bubbled=[bubble])])
        assert problems and "w9_fix_1" in problems[0]
        assert doc["bubbles"] == []

    def test_resolved_ids_leave_bubbles(self, project: Path) -> None:
        bubble_up = [{"id": "M1", "classification": "needs_follow_up", "reason": "r"}]
        review = _review(_issue("M1", "a.py"), bubbles=["M1"], bubble_up=bubble_up)
        doc, problems = _closeout(review, [_fixed("M1", "a.py")], changed=["a.py"])
        assert problems == [] and doc["bubbles"] == [] and doc["bubble_up"] == bubble_up
        assert doc["verdict"] == "READY TO MERGE - 1 of 1 findings resolved, 0 bubbled"
        assert rmg.validate_review(doc, project) == []

    def test_input_not_mutated(self) -> None:
        review = _review(_issue("M1", "a.py"), bubbles=[])
        before = copy.deepcopy(review)
        _closeout(review, [_fixed("M1", "a.py")], changed=["a.py"])
        assert review == before


_SPLIT_FILES = {"w1_fix_1": ["a.py"], "w1_fix_2": ["b.py"]}
_SPLIT_PARTS = {"w1_fix_1": {"M1": ["a.py"]}, "w1_fix_2": {"M1": ["b.py"]}}


def _part(fixer: str, *files: str, what: str = "w") -> FixReport:
    """``fixer`` report fixing M1 in ``files``."""
    return _fix(fixer, [{"id": "M1", "what": what, "files": list(files)}])


def _no_change(fixer: str, *files: str) -> FixReport:
    """``fixer`` report marking its M1 part ``files`` as needing no edit."""
    what = f"{', '.join(files)} only cited as context"
    return _fix(fixer, [{"id": "M1", "what": what, "no_change": list(files)}])


def _split_closeout(fixes: Sequence[FixReport], issue: Optional[Dict[str, object]] = None,
                    parts: Optional[Mapping[str, Mapping[str, Sequence[str]]]] = None) -> tuple:
    """``apply_closeout`` over M1 (mechanical, a.py + b.py), one part per fixer; both files changed."""
    review = _review(issue or _issue("M1", "a.py", files=["a.py", "b.py"]))
    return rmg.apply_closeout(review, fixes, _SPLIT_FILES, {"a.py", "b.py"}, set(), _HEAD, _TODAY, {},
                              parts=_SPLIT_PARTS if parts is None else parts)


class TestCloseoutParts:
    def test_full_coverage_resolves(self, project: Path) -> None:
        fixes = [_part("w1_fix_1", "a.py", what="wrapped a"), _part("w1_fix_2", "b.py", what="wrapped b")]
        doc, problems = _split_closeout(fixes)
        assert problems == []
        [entry] = doc["post_review_resolutions"]
        assert entry["id"] == "M1" and entry["status"] == "RESOLVED"
        assert entry["evidence"].endswith("- wrapped a; wrapped b")
        assert rmg.validate_review(doc, project) == []

    def test_partial_coverage_is_problem(self) -> None:
        doc, problems = _split_closeout([_part("w1_fix_1", "a.py")])
        assert problems == ["M1 partially fixed: missing b.py"]
        assert doc["post_review_resolutions"] == []

    def test_part_recorded_by_wrong_fixer(self) -> None:
        doc, problems = _split_closeout([_part("w1_fix_1", "a.py"), _part("w1_fix_2", "a.py")])
        assert any("w1_fix_2" in p and "a.py" in p for p in problems)
        assert "M1 partially fixed: missing b.py" in problems
        assert doc["post_review_resolutions"] == []

    def test_fixer_without_a_part_is_not_assigned(self) -> None:
        parts = {"w1_fix_1": {"M1": ["a.py"]}, "w1_fix_2": {}}
        doc, problems = _split_closeout([_part("w1_fix_2", "b.py")], parts=parts)
        assert "M1 (w1_fix_2): not assigned to this fixer" in problems
        assert doc["post_review_resolutions"] == []

    def test_no_change_part_covers(self, project: Path) -> None:
        fixes = [_part("w1_fix_1", "a.py", what="wrapped a"), _no_change("w1_fix_2", "b.py")]
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]))
        doc, problems = rmg.apply_closeout(review, fixes, _SPLIT_FILES, {"a.py"}, set(), _HEAD, _TODAY, {},
                                           parts=_SPLIT_PARTS)
        assert problems == []
        [entry] = doc["post_review_resolutions"]
        assert entry["id"] == "M1" and entry["evidence"].endswith("- wrapped a; b.py only cited as context")
        assert rmg.validate_review(doc, project) == []

    def test_no_change_of_another_part_rejected(self) -> None:
        fix = _fix("w1_fix_1", [{"id": "M1", "what": "w", "files": ["a.py"], "no_change": ["b.py"]}])
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]))
        doc, problems = rmg.apply_closeout(review, [fix], _SPLIT_FILES, {"a.py"}, set(), _HEAD, _TODAY, {},
                                           parts=_SPLIT_PARTS)
        assert any("no_change files outside" in p and "b.py" in p for p in problems)
        assert doc["post_review_resolutions"] == []

    def test_every_part_no_change_is_problem(self) -> None:
        fixes = [_no_change("w1_fix_1", "a.py"), _no_change("w1_fix_2", "b.py")]
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]))
        doc, problems = rmg.apply_closeout(review, fixes, _SPLIT_FILES, set(), set(), _HEAD, _TODAY, {},
                                           parts=_SPLIT_PARTS)
        assert problems == ["M1: no fixed entry edited a file (only no_change files)"]
        assert doc["post_review_resolutions"] == []

    def test_one_fixer_owning_every_part_needs_full_coverage(self) -> None:
        parts = {"w1_fix_1": {"M1": ["a.py", "b.py"]}}
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]))
        fixer_files = {"w1_fix_1": ["a.py", "b.py"]}
        doc, problems = rmg.apply_closeout(review, [_part("w1_fix_1", "a.py")], fixer_files,
                                           {"a.py"}, set(), _HEAD, _TODAY, {}, parts=parts)
        assert problems == ["M1 partially fixed: missing b.py"]
        assert doc["post_review_resolutions"] == []

    def test_whole_issue_keeps_existing_rule(self) -> None:
        issue = _issue("I1", "a.py", files=["a.py", "b.py"], fix_kind="judgment")
        fix = _fix("w1_fix_1", [{"id": "I1", "what": "w", "files": ["a.py"]}])
        files = {"w1_fix_1": ["a.py", "b.py"]}
        review = _review(issue)
        doc, problems = rmg.apply_closeout(review, [fix], files, {"a.py"}, set(), _HEAD, _TODAY, {},
                                           parts={"w1_fix_1": {"I1": ["a.py", "b.py"]}})
        assert problems == [] and [r["id"] for r in doc["post_review_resolutions"]] == ["I1"]


class TestCloseoutAssignment:
    def test_held_important_cannot_be_resolved_by_another_fixer(self) -> None:
        bubble_up = [{"id": "I1", "classification": "architectural_ambiguity", "reason": "two options"}]
        review = _review(_issue("I1", "a.py"), _issue("M1", "a.py"), bubbles=["I1"], bubble_up=bubble_up)
        fix = _fix("w1_fix_1", [{"id": "I1", "what": "w", "files": ["a.py"]},
                                {"id": "M1", "what": "w", "files": ["a.py"]}])
        doc, problems = rmg.apply_closeout(review, [fix], {"w1_fix_1": ["a.py"]}, {"a.py"}, set(), _HEAD,
                                           _TODAY, {}, parts={"w1_fix_1": {"M1": ["a.py"]}})
        assert problems == ["I1 (w1_fix_1): not assigned to this fixer"]
        assert [r["id"] for r in doc["post_review_resolutions"]] == ["M1"]
        assert doc["bubbles"] == ["I1"] and doc["verdict"].startswith("NOT READY TO MERGE - important: I1")


class TestCloseoutSupersededRejection:
    def test_later_fixer_resolution_drops_rejected_entry_problem(self, project: Path) -> None:
        review = _review(_issue("M1", "a.py"))
        files = {"w1_fix_1": ["a.py"], "w2_fix_1": ["a.py"]}
        parts = {"w1_fix_1": {"M1": ["a.py"]}, "w2_fix_1": {"M1": ["a.py"]}}
        old = _fix("w1_fix_1", [{"id": "M1", "what": "w", "files": ["z.py"]}])
        new = _fix("w2_fix_1", [{"id": "M1", "what": "redone", "files": ["a.py"]}])
        doc, problems = rmg.apply_closeout(review, [old, new], files, {"a.py", "z.py"}, set(), _HEAD, _TODAY,
                                           {}, parts=parts)
        assert problems == []
        assert [r["id"] for r in doc["post_review_resolutions"]] == ["M1"]
        assert rmg.validate_review(doc, project) == []

    def test_closed_id_drops_rejected_entry_problem(self) -> None:
        doc, problems = _closeout(_review(_issue("M1", "a.py")), [_fixed("M1", "a.py")],
                                  closed={"M1": "not needed"})
        assert problems == []
        assert [r["status"] for r in doc["post_review_resolutions"]] == ["CLOSED_NO_ACTION"]

    def test_open_id_keeps_rejected_entry_problem(self) -> None:
        doc, problems = _closeout(_review(_issue("M1", "a.py"), _issue("M2", "a.py")),
                                  [_fixed("M1", "a.py")], closed={"M2": "not needed"})
        assert problems and problems[0].startswith("M1 (w1_fix_1): listed files not changed")


class TestCloseoutReopenedStatus:
    def test_downgraded_issue_can_be_resolved(self, project: Path) -> None:
        review = _review(_issue("I1", "a.py"), post_review_resolutions=[_res("I1", "DOWNGRADED_TO_MINOR")])
        doc, problems = _closeout(review, [_fixed("I1", "a.py")], changed=["a.py"])
        assert problems == []
        assert [r["status"] for r in doc["post_review_resolutions"]] == ["DOWNGRADED_TO_MINOR", "RESOLVED"]
        assert doc["verdict"] == "READY TO MERGE - 1 of 1 findings resolved, 0 bubbled"
        assert rmg.validate_review(doc, project) == []

    def test_downgraded_issue_can_be_closed(self) -> None:
        review = _review(_issue("I1"), post_review_resolutions=[_res("I1", "DOWNGRADED_TO_MINOR")])
        doc, problems = _closeout(review, [], closed={"I1": "not needed"})
        assert problems == []
        assert [r["status"] for r in doc["post_review_resolutions"]] == ["DOWNGRADED_TO_MINOR",
                                                                         "CLOSED_NO_ACTION"]


def _deferred(review: Dict[str, object], deferred: Mapping[str, str],
              fixes: Sequence[FixReport] = ()) -> tuple:
    """``apply_closeout`` with only ``deferred`` dispositions (fixer ``w1_fix_1`` over a.py)."""
    return rmg.apply_closeout(review, fixes, {"w1_fix_1": ["a.py"]}, set(), set(), _HEAD, _TODAY, {},
                              deferred=deferred)


class TestCloseoutDeferred:
    def test_defer_resolves_and_adds_bubble_up(self, project: Path) -> None:
        review = _review(_issue("I1", "a.py"), bubbles=["I1"])
        doc, problems = _deferred(review, {"I1": "keep as is; GH #12"})
        assert problems == []
        assert doc["post_review_resolutions"] == [{
            "id": "I1", "status": "RESOLVED", "date": _TODAY,
            "evidence": f"{_HEAD} (developer-confirmed defer) - keep as is; GH #12"}]
        assert doc["bubbles"] == []
        assert doc["bubble_up"] == [{"id": "I1", "classification": "needs_follow_up",
                                     "reason": "keep as is; GH #12"}]
        assert doc["verdict"] == "READY TO MERGE - 1 of 1 findings resolved, 0 bubbled"
        assert rmg.validate_review(doc, project) == []

    def test_existing_bubble_up_kept(self) -> None:
        bubble_up = [{"id": "I1", "classification": "architectural_ambiguity", "reason": "two options"}]
        review = _review(_issue("I1", "a.py"), bubbles=["I1"], bubble_up=bubble_up)
        doc, problems = _deferred(review, {"I1": "decided later"})
        assert problems == [] and doc["bubble_up"] == bubble_up and doc["bubbles"] == []

    def test_fixer_bubble_then_defer(self) -> None:
        bubble = {"id": "I1", "classification": "out_of_scope", "reason": "another PR"}
        doc, problems = _deferred(_review(_issue("I1", "a.py")), {"I1": "tracked"},
                                  [_fix("w1_fix_1", bubbled=[bubble])])
        assert problems == [] and doc["bubble_up"] == [bubble] and doc["bubbles"] == []

    def test_long_text_capped_in_bubble_up(self) -> None:
        doc, _ = _deferred(_review(_issue("I1", "a.py")), {"I1": "x" * 300})
        assert doc["bubble_up"][0]["reason"] == "x" * 200
        assert doc["post_review_resolutions"][0]["evidence"].endswith("x" * 300)

    def test_unknown_id_is_problem(self) -> None:
        doc, problems = _deferred(_review(_issue("I1", "a.py")), {"I9": "x"})
        assert problems == ["I9: deferred id matches no issue"]
        assert doc["post_review_resolutions"] == []


class TestRemainingParts:
    def test_split_partially_recorded(self) -> None:
        issues = [_issue("M1", "a.py", files=["a.py", "b.py"])]
        assert rmg.remaining_parts(issues, _SPLIT_PARTS, [_part("w1_fix_1", "a.py")]) == {"M1": ["b.py"]}

    def test_split_fully_recorded(self) -> None:
        issues = [_issue("M1", "a.py", files=["a.py", "b.py"])]
        fixes = [_part("w1_fix_1", "a.py"), _part("w1_fix_2", "b.py")]
        assert rmg.remaining_parts(issues, _SPLIT_PARTS, fixes) == {"M1": []}

    def test_no_change_part_counts_as_recorded(self) -> None:
        issues = [_issue("M1", "a.py", files=["a.py", "b.py"])]
        fixes = [_part("w1_fix_1", "a.py"), _no_change("w1_fix_2", "b.py")]
        assert rmg.remaining_parts(issues, _SPLIT_PARTS, fixes) == {"M1": []}
        out = rmg.remaining_parts(issues, _SPLIT_PARTS, fixes, fixer_files=_SPLIT_FILES, changed={"a.py"},
                                  created=set())
        assert out == {"M1": []}

    def test_no_change_only_is_not_recorded(self) -> None:
        issues = [_issue("M1", "a.py", files=["a.py", "b.py"])]
        fixes = [_no_change("w1_fix_1", "a.py"), _no_change("w1_fix_2", "b.py")]
        out = rmg.remaining_parts(issues, _SPLIT_PARTS, fixes, fixer_files=_SPLIT_FILES,
                                  changed=set(), created=set())
        assert "M1" not in out

    def test_no_change_only_matches_closeout_rejection(self) -> None:
        fixes = [_no_change("w1_fix_1", "a.py"), _no_change("w1_fix_2", "b.py")]
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]))
        doc, problems = rmg.apply_closeout(review, fixes, _SPLIT_FILES, set(), set(), _HEAD, _TODAY, {},
                                           parts=_SPLIT_PARTS)
        assert problems and doc["post_review_resolutions"] == []
        issues = [_issue("M1", "a.py", files=["a.py", "b.py"])]
        out = rmg.remaining_parts(issues, _SPLIT_PARTS, fixes, fixer_files=_SPLIT_FILES,
                                  changed=set(), created=set())
        assert "M1" not in out

    def test_fix_already_present_counts_as_covered(self) -> None:
        issues = [_issue("M1", "a.py", files=["a.py", "b.py"])]
        fixes = [_no_change("w1_fix_1", "a.py"), _no_change("w1_fix_2", "b.py")]
        out = rmg.remaining_parts(issues, _SPLIT_PARTS, fixes, fixer_files=_SPLIT_FILES,
                                  changed={"a.py"}, created=set())
        assert out == {"M1": []}

    def test_one_fixer_owning_every_part_leaves_missing_file(self) -> None:
        issues = [_issue("M1", "a.py", files=["a.py", "b.py"])]
        parts = {"w1_fix_1": {"M1": ["a.py", "b.py"]}}
        fixes = [_part("w1_fix_1", "a.py")]
        assert rmg.remaining_parts(issues, parts, fixes) == {"M1": ["b.py"]}
        out = rmg.remaining_parts(issues, parts, fixes, fixer_files={"w1_fix_1": ["a.py", "b.py"]},
                                  changed={"a.py"}, created=set())
        assert out == {"M1": ["b.py"]}

    def test_whole_issue_any_entry_covers(self) -> None:
        issues = [_issue("I1", "a.py", files=["a.py", "b.py"], fix_kind="judgment")]
        fix = _fix("w1_fix_1", [{"id": "I1", "what": "w", "files": ["a.py"]}])
        parts = {"w1_fix_1": {"I1": ["a.py", "b.py"]}}
        assert rmg.remaining_parts(issues, parts, [fix]) == {"I1": []}

    def test_unplanned_and_unrecorded(self) -> None:
        issues = [_issue("M1", "a.py"), _issue("M2", "b.py")]
        bubble = {"id": "M2", "classification": "out_of_scope", "reason": "r"}
        fixes = [_fixed("M1", "a.py"), _fix("w1_fix_2", bubbled=[bubble])]
        assert rmg.remaining_parts(issues, {}, fixes) == {"M1": []}

    def test_only_files(self) -> None:
        issue = _issue("M1", "a.py", files=["a.py", "b.py", "c.py"], lines="4")
        before = copy.deepcopy(issue)
        assert rmg.only_files(issue, ["b.py"]) == {k: v for k, v in issue.items()
                                                   if k not in ("files", "lines")} | {"file": "b.py"}
        kept = rmg.only_files(issue, ["a.py", "c.py"])
        assert kept["file"] == "a.py" and kept["files"] == ["a.py", "c.py"] and kept["lines"] == "4"
        assert issue == before


_REGISTRY = {"tests/test_a.py": ["a.py"], "tests/test_b.py": ["b.py", "c.py"], "tests/test_x.py": ["x.py"]}


def _widened(issues: Sequence[Dict[str, object]], existing: Sequence[str] = ()) -> List[List[tuple]]:
    """``plan_waves`` over ``issues`` with ``_REGISTRY``: (issue ids, parts, files) per fixer per wave."""
    waves = rmg.plan_waves(issues, [], [], registry=_REGISTRY, existing=set(existing))
    return [[(f["issue_ids"], f["parts"], f["files"]) for f in wave] for wave in waves]


class TestFixPaths:
    def test_tokens_in_fix_text(self) -> None:
        issue = _issue("M1", fix=["Edit docs/guide.md and `scripts/x/y.py:12`.",
                                  "see ./a/b.json, or http://h/z; end in docs/end.md."])
        assert rmg.fix_paths(issue) == ["docs/guide.md", "scripts/x/y.py", "a/b.json", "docs/end.md"]

    def test_no_paths(self) -> None:
        assert rmg.fix_paths(_issue("M1", fix=["rename the helper", "a/b without extension",
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
        assert rmg.registry_tests(["pkg/sub/m.py"], registry) == [
            "tests/test_pkg.py", "tests/test_slash.py", "tests/test_file.py"]
        assert rmg.registry_tests(["pkg_other.py", "pkgx/m.py"], registry) == []
        waves = rmg.plan_waves([_issue("M1", "pkg/sub/m.py")], [], [],
                               registry={"tests/test_pkg.py": ["pkg"]})
        assert waves[0][0]["files"] == ["pkg/sub/m.py", "tests/test_pkg.py"]

    def test_issue_files_never_widen_twice(self) -> None:
        issue = _issue("I1", "a.py", files=["a.py", "tests/test_a.py"], fix_kind="judgment",
                       fix=["edit tests/test_a.py"])
        assert _widened([issue], existing=["tests/test_a.py"]) == [
            [(["I1"], {"I1": ["a.py", "tests/test_a.py"]}, ["a.py", "tests/test_a.py"])]]

    def test_split_part_may_list_its_widened_file(self) -> None:
        files = {"w1_fix_1": ["a.py", "tests/test_a.py"], "w1_fix_2": ["b.py"]}
        fixes = [_part("w1_fix_1", "a.py", "tests/test_a.py"), _part("w1_fix_2", "b.py")]
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]))
        doc, problems = rmg.apply_closeout(review, fixes, files, {"a.py", "b.py", "tests/test_a.py"}, set(),
                                           _HEAD, _TODAY, {}, parts=_SPLIT_PARTS)
        assert problems == [] and [r["id"] for r in doc["post_review_resolutions"]] == ["M1"]

    def test_split_part_cannot_list_another_parts_file(self) -> None:
        files = {"w1_fix_1": ["a.py", "b.py"], "w2_fix_1": ["b.py"]}
        parts = {"w1_fix_1": {"M1": ["a.py"], "M2": ["b.py"]}, "w2_fix_1": {"M1": ["b.py"]}}
        fix = _fix("w1_fix_1", [{"id": "M1", "what": "w", "files": ["a.py", "b.py"]}])
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]), _issue("M2", "b.py"))
        _, problems = rmg.apply_closeout(review, [fix], files, {"a.py", "b.py"}, set(), _HEAD, _TODAY, {},
                                         parts=parts)
        assert any("M1 (w1_fix_1)" in p and "b.py" in p for p in problems)

    def test_remaining_parts_accepts_widened_entry(self) -> None:
        issues = [_issue("M1", "a.py", files=["a.py", "b.py"])]
        files = {"w1_fix_1": ["a.py", "tests/test_a.py"], "w1_fix_2": ["b.py"]}
        fixes = [_part("w1_fix_1", "a.py", "tests/test_a.py")]
        out = rmg.remaining_parts(issues, _SPLIT_PARTS, fixes, fixer_files=files,
                                  changed={"a.py", "tests/test_a.py"}, created=set())
        assert out == {"M1": ["b.py"]}

    def test_split_part_may_list_another_issues_file(self) -> None:
        files = {"w1_fix_1": ["a.py", "tests/test_a.py"], "w1_fix_2": ["b.py"]}
        parts = {"w1_fix_1": {"M1": ["a.py"], "I1": ["tests/test_a.py"]}, "w1_fix_2": {"M1": ["b.py"]}}
        fixes = [_fix("w1_fix_1", [{"id": "M1", "what": "a", "files": ["a.py", "tests/test_a.py"]},
                                   {"id": "I1", "what": "t", "files": ["tests/test_a.py"]}]),
                 _part("w1_fix_2", "b.py")]
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]),
                         _issue("I1", "tests/test_a.py", fix_kind="judgment"))
        doc, problems = rmg.apply_closeout(review, fixes, files, {"a.py", "b.py", "tests/test_a.py"}, set(),
                                           _HEAD, _TODAY, {}, parts=parts)
        assert problems == []
        assert sorted(r["id"] for r in doc["post_review_resolutions"]) == ["I1", "M1"]
        out = rmg.remaining_parts([_issue("M1", "a.py", files=["a.py", "b.py"])], parts, fixes[:1],
                                  fixer_files=files, changed={"a.py", "tests/test_a.py"}, created=set())
        assert out == {"M1": ["b.py"]}


def _present(fixes: Sequence[FixReport], changed: Sequence[str], *others: Dict[str, object]) -> tuple:
    """``apply_closeout`` over M1 on a.py plus ``others`` issues, fixer ``w1_fix_1`` over a.py and t.py."""
    review = _review(_issue("M1", "a.py"), *others)
    return rmg.apply_closeout(review, fixes, {"w1_fix_1": ["a.py", "t.py"]}, set(changed), set(), _HEAD,
                              _TODAY, {})


class TestCloseoutFixAlreadyPresent:
    def test_changed_own_file_under_no_change_resolves(self, project: Path) -> None:
        fix = _fix("w1_fix_1", [{"id": "M1", "what": "guard already at a.py:9", "no_change": ["a.py"]}])
        doc, problems = _present([fix], ["a.py"])
        assert problems == []
        [entry] = doc["post_review_resolutions"]
        assert entry["status"] == "RESOLVED" and entry["evidence"] == (
            f"{_HEAD} (working-tree snapshot; developer commits) - guard already at a.py:9 "
            f"(already present: a.py changed since build)")
        assert rmg.validate_review(doc, project) == []

    def test_unchanged_own_file_stays_a_problem(self) -> None:
        fix = _fix("w1_fix_1", [{"id": "M1", "what": "cited only", "no_change": ["a.py"]}])
        doc, problems = _present([fix], [])
        assert problems == ["M1: no fixed entry edited a file (only no_change files)"]
        assert doc["post_review_resolutions"] == []

    def test_changed_file_that_is_not_the_issues_own_is_not_enough(self) -> None:
        fix = _fix("w1_fix_1", [{"id": "M1", "what": "cited only", "no_change": ["t.py"]}])
        doc, problems = _present([fix], ["t.py"])
        assert problems == ["M1: no fixed entry edited a file (only no_change files)"]
        assert doc["post_review_resolutions"] == []

    def test_own_file_another_issue_edited_is_not_enough(self) -> None:
        fix = _fix("w1_fix_1", [{"id": "M2", "what": "m2 fix", "files": ["a.py"]},
                                {"id": "M1", "what": "cited only", "no_change": ["a.py"]}])
        doc, problems = _present([fix], ["a.py"], _issue("M2", "a.py"))
        assert problems == ["M1: no fixed entry edited a file (only no_change files)"]
        assert [r["id"] for r in doc["post_review_resolutions"]] == ["M2"]

    def test_split_entry_editing_only_another_issues_file_is_not_enough(self) -> None:
        files = {"w1_fix_1": ["a.py", "t.py"], "w1_fix_2": ["b.py"]}
        parts = {"w1_fix_1": {"M1": ["a.py"], "I1": ["t.py"]}, "w1_fix_2": {"M1": ["b.py"]}}
        fixes = [_fix("w1_fix_1", [{"id": "M1", "what": "m", "files": ["t.py"], "no_change": ["a.py"]},
                                   {"id": "I1", "what": "t", "files": ["t.py"]}]),
                 _no_change("w1_fix_2", "b.py")]
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]),
                         _issue("I1", "t.py", fix_kind="judgment"))
        doc, problems = rmg.apply_closeout(review, fixes, files, {"t.py"}, set(), _HEAD, _TODAY, {},
                                           parts=parts)
        assert problems == ["M1: no fixed entry edited a file (only no_change files)"]
        assert [r["id"] for r in doc["post_review_resolutions"]] == ["I1"]

    def test_split_issue_already_present_resolves(self) -> None:
        fixes = [_no_change("w1_fix_1", "a.py"), _no_change("w1_fix_2", "b.py")]
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]))
        doc, problems = rmg.apply_closeout(review, fixes, _SPLIT_FILES, {"a.py"}, set(), _HEAD, _TODAY, {},
                                           parts=_SPLIT_PARTS)
        assert problems == []
        [entry] = doc["post_review_resolutions"]
        assert entry["evidence"].endswith("(already present: a.py changed since build)")

    def test_pr1616_shape_resolves(self) -> None:
        """M3 split over code + ref files; wave 1 edits code and a test owned by its other issues, wave 2
        cites the ref file, wave 3 cites code and ref as no_change. Closeout resolves M3 through wave 1's
        edit (the any-file path), so the wave 3 no_change entry adds coverage but does not reach the
        ``(already present`` branch."""
        code, ref, test = "grids/annual.py", "ref/periods.py", "tests/test_annual.py"
        files = {"w1_fix_1": [code, test], "w2_fix_1": [ref], "w3_fix_1": [code, ref, test]}
        parts = {"w1_fix_1": {"M3": [code], "I2": [test, code]}, "w2_fix_1": {"M3": [ref]},
                 "w3_fix_1": {"M3": [code, ref]}}
        fixes = [_fix("w1_fix_1", [{"id": "M3", "what": "guard", "files": [code, test]},
                                   {"id": "I2", "what": "tests", "files": [test, code]}]),
                 _fix("w2_fix_1", [{"id": "M3", "what": "cited", "no_change": [ref]}]),
                 _fix("w3_fix_1", [{"id": "M3", "what": "already there", "no_change": [code, ref]}])]
        review = _review(_issue("M3", code, files=[code, ref]),
                         _issue("I2", test, files=[test, code], fix_kind="judgment"))
        doc, problems = rmg.apply_closeout(review, fixes, files, {code, test}, set(), _HEAD, _TODAY, {},
                                           parts=parts)
        assert problems == []
        assert sorted(r["id"] for r in doc["post_review_resolutions"]) == ["I2", "M3"]


class TestCloseoutLateDisposition:
    def test_resolved_flag_clears_coverage_problem(self) -> None:
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]))
        doc, problems = rmg.apply_closeout(review, [_part("w1_fix_1", "a.py")], _SPLIT_FILES, {"a.py"}, set(),
                                           _HEAD, _TODAY, {}, parts=_SPLIT_PARTS,
                                           resolved={"M1": "b.py part done by hand"})
        assert problems == []
        assert [(r["id"], r["status"]) for r in doc["post_review_resolutions"]] == [("M1", "RESOLVED")]

    def test_closed_flag_clears_coverage_problem(self) -> None:
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]))
        doc, problems = rmg.apply_closeout(review, [_part("w1_fix_1", "a.py")], _SPLIT_FILES, {"a.py"}, set(),
                                           _HEAD, _TODAY, {"M1": "b.py needs nothing"}, parts=_SPLIT_PARTS)
        assert problems == []
        statuses = [(r["id"], r["status"]) for r in doc["post_review_resolutions"]]
        assert statuses == [("M1", "CLOSED_NO_ACTION")]

    def test_open_issue_keeps_coverage_problem(self) -> None:
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]))
        _, problems = rmg.apply_closeout(review, [_part("w1_fix_1", "a.py")], _SPLIT_FILES, {"a.py"}, set(),
                                         _HEAD, _TODAY, {}, parts=_SPLIT_PARTS)
        assert problems == ["M1 partially fixed: missing b.py"]


class TestResolvableHints:
    def test_rejected_issue_with_changed_own_file_gets_hint(self) -> None:
        review = _review(_issue("M1", "a.py"))
        doc, problems = _closeout(review, [_fixed("M1", "a.py", "z.py")], changed=["a.py", "z.py"])
        hints = rmg.resolvable_hints(doc, problems, {"a.py", "z.py"})
        assert hints == ['hint: M1: a.py changed since build but no accepted fixer entry records it; if the fix '
                         'is in place, rerun closeout with --resolved M1="what changed"']

    def test_unplanned_fixer_problem_names_its_issue(self) -> None:
        review = _review(_issue("M1", "a.py"))
        fix = _fix("w9_fix_1", [{"id": "M1", "what": "w", "files": ["a.py"]}])
        doc, problems = _closeout(review, [fix], changed=["a.py"])
        assert problems == ["M1 (w9_fix_1): not a planned fixer; not resolved"]
        [hint] = rmg.resolvable_hints(doc, problems, {"a.py"})
        assert hint.startswith("hint: M1: a.py changed since build")

    def test_no_hint_without_changed_own_file(self) -> None:
        review = _review(_issue("M1", "a.py"))
        doc, problems = _closeout(review, [_fixed("M1", "a.py")])
        assert problems and rmg.resolvable_hints(doc, problems, set()) == []

    def test_no_hint_for_partially_fixed_or_closed_issue(self) -> None:
        review = _review(_issue("M1", "a.py", files=["a.py", "b.py"]), _issue("M2", "c.py"),
                         post_review_resolutions=[_res("M2")])
        doc, problems = rmg.apply_closeout(review, [_part("w1_fix_1", "a.py")], _SPLIT_FILES, {"a.py"}, set(),
                                           _HEAD, _TODAY, {}, parts=_SPLIT_PARTS)
        assert rmg.resolvable_hints(doc, [*problems, "M2: stale"], {"a.py", "c.py"}) == []


def _resolved(review: Dict[str, object], resolved: Mapping[str, str], changed: Sequence[str]) -> tuple:
    """``apply_closeout`` with only ``resolved`` (developer-directed) dispositions."""
    return rmg.apply_closeout(review, [], {}, set(changed), set(), _HEAD, _TODAY, {}, resolved=resolved)


class TestCloseoutResolvedOutsideWaves:
    def test_changed_file_resolves(self, project: Path) -> None:
        review = _review(_issue("I1", "a.py", files=["a.py", "b.py"], fix_kind="judgment"))
        doc, problems = _resolved(review, {"I1": "rewired the seam"}, ["b.py"])
        assert problems == []
        assert doc["post_review_resolutions"] == [{
            "id": "I1", "status": "RESOLVED", "date": _TODAY,
            "evidence": f"{_HEAD} (working-tree snapshot; developer commits) - rewired the seam "
                        f"(outside fixer waves)"}]
        assert doc["verdict"] == "READY TO MERGE - 1 of 1 findings resolved, 0 bubbled"
        assert rmg.validate_review(doc, project) == []

    def test_unchanged_files_are_a_problem(self) -> None:
        doc, problems = _resolved(_review(_issue("I1", "a.py")), {"I1": "w"}, ["z.py"])
        assert problems == ["I1: none of its files changed since build: a.py"]
        assert doc["post_review_resolutions"] == []

    def test_unknown_id_is_a_problem(self) -> None:
        doc, problems = _resolved(_review(_issue("I1", "a.py")), {"I9": "w"}, ["a.py"])
        assert problems == ["I9: resolved id matches no issue"]
        assert doc["post_review_resolutions"] == []

    def test_closed_id_not_duplicated(self) -> None:
        review = _review(_issue("M1", "a.py"), post_review_resolutions=[_res("M1")])
        doc, problems = _resolved(review, {"M1": "w"}, ["a.py"])
        assert problems == [] and len(doc["post_review_resolutions"]) == 1


class TestUndispositioned:
    def test_ids_without_resolution_or_bubble(self) -> None:
        bubble_up = [{"id": "M2", "classification": "out_of_scope", "reason": "r"}]
        review = _review(_issue("I1"), _issue("M1"), _issue("M2"), _issue("M10"),
                         post_review_resolutions=[_res("M1")], bubble_up=bubble_up)
        assert rmg.undispositioned_ids(review) == ["I1", "M10"]

    def test_downgraded_only_is_undispositioned(self) -> None:
        review = _review(_issue("M1"), _issue("M2"),
                         post_review_resolutions=[_res("M1", "DOWNGRADED_TO_MINOR"), _res("M2")])
        assert rmg.undispositioned_ids(review) == ["M1"]
