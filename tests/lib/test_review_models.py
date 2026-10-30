"""Behavioral tests for harness_lib.review_models (pr-review findings, fix reports and the recording API).

Covers each model validator (pass and fail), severity coercion, repo path normalization, the run directory
helpers, the ``record`` / ``record_fixes`` writers with their printed return blocks, and the optional
``fix_kind`` enum on ``PR_REVIEW.schema.json``'s issue definition.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Dict, Iterator

import jsonschema
import pytest

from harness_lib import review_models as rm
from harness_lib.config import activate, load_config
from harness_lib.project import schema_path

_PR = 1558
_RUN_ID = "pr1558_20261010T120000Z"
_SCRATCH = "build/review_scratch"


def _finding(**overrides: object) -> Dict[str, object]:
    """A valid finding mapping; ``overrides`` replace or add keys."""
    base: Dict[str, object] = {
        "severity": "important", "name": "Strict decode", "summary": "git output decoded as UTF-8.",
        "fix": ["Add errors='replace'."], "file": "src/pkg/branch_capture.py",
        "lines": "30-31", "fix_kind": "mechanical",
    }
    base.update(overrides)
    return base


@pytest.fixture
def project(make_project) -> Path:
    """An activated throwaway project whose review scratch directory is ``_SCRATCH``."""
    root = make_project(config={"artifacts": {"scratch": _SCRATCH}})
    activate(load_config(root))
    return root


@pytest.fixture
def run_repo(project: Path) -> Iterator[Path]:
    """The activated project with a started run for ``_PR``."""
    rm.start_run(_PR, _RUN_ID, repo=project)
    yield project


class TestSeverity:
    @pytest.mark.parametrize("raw, expected", [
        ("C", rm.Severity.critical), ("i", rm.Severity.important), ("m", rm.Severity.minor),
        ("CRITICAL", rm.Severity.critical), ("Important", rm.Severity.important),
        ("minor", rm.Severity.minor),
    ])
    def test_coerces(self, raw: str, expected: rm.Severity) -> None:
        assert rm.Finding(**_finding(severity=raw)).severity is expected

    def test_unknown_rejected(self) -> None:
        with pytest.raises(ValueError):
            rm.Finding(**_finding(severity="blocker"))


class TestRepoPath:
    def test_backslashes(self) -> None:
        assert rm.repo_path("a\\b.py") == "a/b.py"

    def test_strips_repo_root(self) -> None:
        assert rm.repo_path("E:/repo/x.py", root="E:/repo") == "x.py"

    def test_strips_repo_root_case_and_slash_insensitive(self) -> None:
        assert rm.repo_path("e:\\Repo\\dir\\x.py", root="E:/repo") == "dir/x.py"

    def test_posix_root_is_case_sensitive(self) -> None:
        with pytest.raises(ValueError):
            rm.repo_path("/HOME/REPO/x.py", root="/home/repo")

    def test_posix_root_exact_case_stripped(self) -> None:
        assert rm.repo_path("/home/repo/dir/x.py", root="/home/repo") == "dir/x.py"

    def test_strips_leading_dot_slash(self) -> None:
        assert rm.repo_path("./src/x.py", root="E:/repo") == "src/x.py"

    @pytest.mark.parametrize("bad", ["../x", "a/../../x", "", "   ", "C:/elsewhere/x.py", "/abs/x.py"])
    def test_rejects(self, bad: str) -> None:
        with pytest.raises(ValueError):
            rm.repo_path(bad, root="E:/repo")


class TestFinding:
    @pytest.mark.parametrize("field, value", [
        ("name", "x" * 120), ("lines", "9,146-155"), ("lines", "12"), ("lines", "1-2, 5"), ("lines", None),
        ("also", ["docs/a.md"]), ("fix_kind", "judgment"),
    ])
    def test_valid(self, field: str, value: object) -> None:
        rm.Finding(**_finding(**{field: value}))

    @pytest.mark.parametrize("field, value", [
        ("name", ""), ("name", "x" * 121), ("summary", " "), ("fix", []), ("fix", ["ok", " "]),
        ("file", "../x.py"), ("lines", "pr_sum.py:9"), ("lines", "~10"), ("lines", "20-10"),
        ("lines", "1-2, 9-8"), ("also", ["../y"]),
        ("also", ["src/pkg/branch_capture.py"]), ("fix_kind", "easy"),
    ])
    def test_invalid(self, field: str, value: object) -> None:
        with pytest.raises(ValueError):
            rm.Finding(**_finding(**{field: value}))

    def test_extra_key_rejected(self) -> None:
        with pytest.raises(ValueError):
            rm.Finding(**_finding(id="I1"))

    def test_fix_kind_required(self) -> None:
        data = _finding()
        del data["fix_kind"]
        with pytest.raises(ValueError):
            rm.Finding(**data)

    def test_name_whitespace_collapsed(self) -> None:
        assert rm.Finding(**_finding(name="  a \n b  ")).name == "a b"

    def test_frozen(self) -> None:
        finding = rm.Finding(**_finding())
        with pytest.raises(ValueError):
            finding.name = "other"  # type: ignore[misc]


class TestFixModels:
    @pytest.mark.parametrize("data", [
        {"id": "C1", "what": "done", "files": ["a.py"]},
        {"id": "M12", "what": "two\nlines", "files": ["a.py", "b\\c.py"]},
        {"id": "M3", "what": "cited only", "no_change": ["a.py"]},
        {"id": "M4", "what": "edited a, b cited only", "files": ["a.py"], "no_change": ["b.py"]},
    ])
    def test_entry_valid(self, data: Dict[str, object]) -> None:
        rm.FixEntry(**data)

    @pytest.mark.parametrize("data", [
        {"id": "X1", "what": "done", "files": ["a.py"]},
        {"id": "C1", "what": " ", "files": ["a.py"]},
        {"id": "C1", "what": "done", "files": []},
        {"id": "C1", "what": "done", "files": ["../a.py"]},
        {"id": "C1", "what": "done", "files": [], "no_change": []},
        {"id": "C1", "what": "done", "files": ["a.py"], "no_change": ["a.py"]},
        {"id": "C1", "what": "done", "no_change": ["../a.py"]},
    ])
    def test_entry_invalid(self, data: Dict[str, object]) -> None:
        with pytest.raises(ValueError):
            rm.FixEntry(**data)

    def test_bubble_valid(self) -> None:
        bubble = rm.FixBubble(id="I3", classification="out_of_scope", reason="belongs elsewhere")
        assert bubble.classification is rm.BubbleClass.out_of_scope

    @pytest.mark.parametrize("data", [
        {"id": "I3", "classification": "nope", "reason": "r"},
        {"id": "I3", "classification": "out_of_scope", "reason": ""},
        {"id": "I3", "classification": "out_of_scope", "reason": "r" * 201},
    ])
    def test_bubble_invalid(self, data: Dict[str, object]) -> None:
        with pytest.raises(ValueError):
            rm.FixBubble(**data)

    def test_report_rejects_bad_fixer_id(self) -> None:
        with pytest.raises(ValueError):
            rm.FixReport(fixer="W1-fix", fixed=(), bubbled=())

    def test_report_rejects_duplicate_ids(self) -> None:
        entry = rm.FixEntry(id="M1", what="w", files=("a.py",))
        bubble = rm.FixBubble(id="M1", classification="out_of_scope", reason="r")
        with pytest.raises(ValueError):
            rm.FixReport(fixer="w1_fix_1", fixed=(entry,), bubbled=(bubble,))


class TestRunDir:
    def test_start_run_writes_current(self, project: Path) -> None:
        path = rm.start_run(_PR, _RUN_ID, repo=project)
        assert path == project.resolve() / _SCRATCH / "1558" / _RUN_ID
        assert path.is_dir()
        assert rm.run_dir(_PR, repo=project) == path

    def test_run_root_is_the_configured_scratch(self, project: Path) -> None:
        assert rm.run_root() == Path(_SCRATCH)

    def test_default_repo_is_the_active_project(self, project: Path) -> None:
        path = rm.start_run(_PR, _RUN_ID)
        assert path == project.resolve() / _SCRATCH / "1558" / _RUN_ID
        assert rm.run_dir(_PR) == path

    def test_explicit_repo_config_governs(self, project: Path, make_project) -> None:
        other = make_project(config={"artifacts": {"scratch": "elsewhere/runs"}}, name="other")
        path = rm.start_run(_PR, _RUN_ID, repo=other)
        assert path == other.resolve() / "elsewhere" / "runs" / "1558" / _RUN_ID
        assert rm.run_root() == Path(_SCRATCH) and rm.run_root(other) == Path("elsewhere/runs")

    def test_default_root_strips_the_active_project(self, project: Path) -> None:
        assert rm.repo_path(f"{project.resolve().as_posix()}/src/x.py") == "src/x.py"

    def test_explicit_run_id(self, project: Path) -> None:
        assert rm.run_dir(_PR, repo=project, run_id=_RUN_ID).name == _RUN_ID

    def test_missing_current_raises(self, project: Path) -> None:
        with pytest.raises(FileNotFoundError):
            rm.run_dir(_PR, repo=project)

    def test_bad_run_id_rejected(self, project: Path) -> None:
        with pytest.raises(ValueError):
            rm.start_run(_PR, "pr1558-now", repo=project)

    def test_existing_run_directory_rejected(self, project: Path) -> None:
        rm.start_run(_PR, _OTHER_RUN, repo=project)
        rm.start_run(_PR, _RUN_ID, repo=project)
        with pytest.raises(ValueError, match="already exists"):
            rm.start_run(_PR, _OTHER_RUN, repo=project)
        assert rm.run_dir(_PR, repo=project).name == _RUN_ID

    @pytest.mark.parametrize("bad", ["../other_run", "pr1558_20261010T120000Z/../x", "current"])
    def test_explicit_traversal_run_id_rejected(self, project: Path, bad: str) -> None:
        with pytest.raises(ValueError):
            rm.run_dir(_PR, repo=project, run_id=bad)

    def test_corrupted_current_rejected(self, project: Path) -> None:
        rm.start_run(_PR, _RUN_ID, repo=project)
        (project / _SCRATCH / "1558" / "current").write_text("../../escape\n", encoding="utf-8")
        with pytest.raises(ValueError):
            rm.run_dir(_PR, repo=project)


class TestRecord:
    def test_zero_findings_materializes_report(self, run_repo: Path, capsys: pytest.CaptureFixture) -> None:
        block = rm.record(_PR, "runtime", repo=run_repo)
        path = rm.run_dir(_PR, repo=run_repo) / "findings" / "runtime.json"
        assert path.is_file()
        assert "COUNTS: findings=0 critical=0 important=0 minor=0" in block.splitlines()
        assert capsys.readouterr().out.strip() == block.strip()

    def test_block_shape(self, run_repo: Path) -> None:
        findings = [_finding(), _finding(severity="C", lines="40"), _finding(severity="m", lines=None)]
        block = rm.record(_PR, "runtime", findings, ["clean seams"], repo=run_repo)
        lines = block.strip().splitlines()
        assert lines[:4] == ["---", "SIGNAL: DONE", "AGENT_ROLE: reviewer",
                             "COUNTS: findings=3 critical=1 important=1 minor=1"]
        assert lines[4] == f"OUTPUT: {_SCRATCH}/1558/{_RUN_ID}/findings/runtime.json"
        assert lines[5] == "---"

    def test_report_round_trips(self, run_repo: Path) -> None:
        rm.record(_PR, "docs", [_finding(also=["docs/a.md"])], ["s1"], repo=run_repo)
        report = rm.load_report(rm.run_dir(_PR, repo=run_repo) / "findings" / "docs.json")
        assert report.reviewer == "docs"
        assert report.findings[0].also == ("docs/a.md",)
        assert report.strengths == ("s1",)

    def test_record_twice_replaces(self, run_repo: Path) -> None:
        rm.record(_PR, "runtime", [_finding(), _finding()], repo=run_repo)
        rm.record(_PR, "runtime", [_finding()], repo=run_repo)
        report = rm.load_report(rm.run_dir(_PR, repo=run_repo) / "findings" / "runtime.json")
        assert len(report.findings) == 1

    def test_bad_finding_leaves_file_unchanged(self, run_repo: Path) -> None:
        rm.record(_PR, "runtime", [_finding()], repo=run_repo)
        path = rm.run_dir(_PR, repo=run_repo) / "findings" / "runtime.json"
        before = path.read_bytes()
        with pytest.raises(ValueError, match=r"finding\[1\]"):
            rm.record(_PR, "runtime", [_finding(), _finding(lines="bad")], repo=run_repo)
        assert path.read_bytes() == before

    def test_repo_root_prefix_normalized(self, run_repo: Path) -> None:
        absolute = f"{run_repo.resolve().as_posix()}/src/x.py"
        rm.record(_PR, "runtime", [_finding(file=absolute)], repo=run_repo)
        report = rm.load_report(rm.run_dir(_PR, repo=run_repo) / "findings" / "runtime.json")
        assert report.findings[0].file == "src/x.py"

    @pytest.mark.parametrize("bad", ["Runtime", "run-time", "", "run time", "_x"])
    def test_reviewer_id_validated(self, run_repo: Path, bad: str) -> None:
        with pytest.raises(ValueError):
            rm.record(_PR, bad, repo=run_repo)


class TestRecordFixes:
    def test_done_block(self, run_repo: Path, capsys: pytest.CaptureFixture) -> None:
        fixed = [{"id": "M2", "what": "wrapped lines", "files": ["a.py", "b.py"]},
                 {"id": "I1", "what": "guarded\ndecode", "files": ["a.py"]}]
        bubbled = [{"id": "C1", "classification": "architectural_ambiguity", "reason": "two options"}]
        block = rm.record_fixes(_PR, "w1_fix_1", fixed, bubbled, repo=run_repo)
        assert block.strip().splitlines() == [
            "---", "SIGNAL: DONE", "AGENT_ROLE: fixer", "FIXED: M2,I1", "BUBBLED: C1", "EDITED: 2",
            f"OUTPUT: {_SCRATCH}/1558/{_RUN_ID}/fixes/w1_fix_1.json",
            "EVIDENCE:", "  M2: wrapped lines", "  I1: guarded decode", "---",
        ]
        assert capsys.readouterr().out.strip() == block.strip()

    def test_fail_block(self, run_repo: Path) -> None:
        bubbled = [{"id": "C1", "classification": "fixer_failed", "reason": "file missing"}]
        lines = rm.record_fixes(_PR, "w1_fix_2", (), bubbled, repo=run_repo).strip().splitlines()
        assert lines[:3] == ["---", "SIGNAL: FAIL", "AGENT_ROLE: fixer"]
        assert lines[3].startswith("REASON: ") and "C1" in lines[3] and len(lines[3]) <= 208
        assert lines[4].startswith("PARTIAL_OUTPUT: ")
        assert lines[-1] == "---"

    def test_load_fix_reports(self, run_repo: Path) -> None:
        rm.record_fixes(_PR, "w1_fix_2", [{"id": "M1", "what": "w", "files": ["a.py"]}], repo=run_repo)
        rm.record_fixes(_PR, "w1_fix_1", [{"id": "M2", "what": "w", "files": ["b.py"]}], repo=run_repo)
        reports = rm.load_fix_reports(rm.run_dir(_PR, repo=run_repo) / "fixes")
        assert [r.fixer for r in reports] == ["w1_fix_1", "w1_fix_2"]

    def test_load_fix_reports_missing_dir(self, tmp_path: Path) -> None:
        assert rm.load_fix_reports(tmp_path / "nope") == ()

    def test_bad_entry_names_index(self, run_repo: Path) -> None:
        with pytest.raises(ValueError, match=r"fixed\[0\]"):
            rm.record_fixes(_PR, "w1_fix_1", [{"id": "Z9", "what": "w", "files": ["a.py"]}], repo=run_repo)


def _write_draft(path: Path, data: object) -> None:
    """``data`` as JSON at ``path``, parents created."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestRecordDraft:
    def test_draft_path_sits_in_the_run(self, run_repo: Path) -> None:
        path = rm.draft_path(_PR, "runtime", repo=run_repo, run_id=_RUN_ID)
        assert path == rm.run_dir(_PR, run_repo, _RUN_ID) / "drafts" / "runtime.json"

    def test_record_draft_round_trips(self, run_repo: Path, capsys: pytest.CaptureFixture) -> None:
        draft = rm.draft_path(_PR, "docs", repo=run_repo)
        _write_draft(draft, {"findings": [_finding(), _finding(severity="m")], "strengths": ["s1"]})
        block = rm.record_draft(_PR, "docs", repo=run_repo)
        assert "COUNTS: findings=2 critical=0 important=1 minor=1" in block.splitlines()
        assert capsys.readouterr().out.strip() == block.strip()
        report = rm.load_report(rm.run_dir(_PR, repo=run_repo) / "findings" / "docs.json")
        assert report.strengths == ("s1",)

    def test_missing_draft_names_the_path(self, run_repo: Path) -> None:
        with pytest.raises(ValueError, match=r"drafts[/\\]docs\.json"):
            rm.record_draft(_PR, "docs", repo=run_repo)

    @pytest.mark.parametrize("data", [[], {"findings": [], "extra": 1}, {"findings": {}}])
    def test_bad_draft_shape_rejected(self, run_repo: Path, data: object) -> None:
        _write_draft(rm.draft_path(_PR, "docs", repo=run_repo), data)
        with pytest.raises(ValueError):
            rm.record_draft(_PR, "docs", repo=run_repo)

    def test_invalid_json_rejected(self, run_repo: Path) -> None:
        path = rm.draft_path(_PR, "docs", repo=run_repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"findings": [', encoding="utf-8")
        with pytest.raises(ValueError, match="JSON"):
            rm.record_draft(_PR, "docs", repo=run_repo)

    def test_bad_finding_names_index(self, run_repo: Path) -> None:
        data = {"findings": [_finding(), _finding(lines="x")]}
        _write_draft(rm.draft_path(_PR, "docs", repo=run_repo), data)
        with pytest.raises(ValueError, match=r"finding\[1\]"):
            rm.record_draft(_PR, "docs", repo=run_repo)

    def test_record_fixes_draft(self, run_repo: Path) -> None:
        data = {"fixed": [{"id": "M2", "what": "w", "files": ["a.py"]}],
                "bubbled": [{"id": "C1", "classification": "architectural_ambiguity", "reason": "r"}]}
        _write_draft(rm.draft_path(_PR, "w1_fix_1", repo=run_repo, run_id=_RUN_ID), data)
        block = rm.record_fixes_draft(_PR, "w1_fix_1", repo=run_repo, run_id=_RUN_ID)
        assert "FIXED: M2" in block.splitlines() and "BUBBLED: C1" in block.splitlines()


class TestRecordAdd:
    def _report(self, repo: Path) -> rm.ReviewerReport:
        return rm.load_report(rm.run_dir(_PR, repo=repo) / "findings" / "runtime.json")

    def test_first_add_creates_the_report(self, run_repo: Path) -> None:
        block = rm.record_add(_PR, "runtime", [_finding()], repo=run_repo)
        assert "COUNTS: findings=1 critical=0 important=1 minor=0" in block.splitlines()

    def test_adds_append(self, run_repo: Path) -> None:
        rm.record_add(_PR, "runtime", [_finding()], ["s1"], repo=run_repo)
        block = rm.record_add(_PR, "runtime", [_finding(name="Second", severity="C")], ["s2"], repo=run_repo)
        assert "COUNTS: findings=2 critical=1 important=1 minor=0" in block.splitlines()
        assert self._report(run_repo).strengths == ("s1", "s2")

    def test_add_after_record_appends(self, run_repo: Path) -> None:
        rm.record(_PR, "runtime", [_finding()], repo=run_repo)
        rm.record_add(_PR, "runtime", [_finding(name="Second")], repo=run_repo)
        assert len(self._report(run_repo).findings) == 2

    def test_identical_items_skipped(self, run_repo: Path) -> None:
        rm.record_add(_PR, "runtime", [_finding()], ["s1"], repo=run_repo)
        rm.record_add(_PR, "runtime", [_finding()], ["s1"], repo=run_repo)
        report = self._report(run_repo)
        assert len(report.findings) == 1 and report.strengths == ("s1",)

    def test_bad_finding_leaves_file_unchanged(self, run_repo: Path) -> None:
        rm.record_add(_PR, "runtime", [_finding()], repo=run_repo)
        path = rm.run_dir(_PR, repo=run_repo) / "findings" / "runtime.json"
        before = path.read_bytes()
        with pytest.raises(ValueError, match=r"finding\[0\]"):
            rm.record_add(_PR, "runtime", [_finding(lines="bad")], repo=run_repo)
        assert path.read_bytes() == before

    def test_named_run(self, run_repo: Path) -> None:
        rm.start_run(_PR, _OTHER_RUN, repo=run_repo)
        rm.record_add(_PR, "runtime", [_finding()], repo=run_repo, run_id=_RUN_ID)
        assert (rm.run_dir(_PR, run_repo, _RUN_ID) / "findings" / "runtime.json").is_file()


_OTHER_RUN = "pr1558_20261011T080000Z"


class TestRecordRunId:
    def test_record_writes_under_named_run(self, run_repo: Path) -> None:
        rm.start_run(_PR, _OTHER_RUN, repo=run_repo)
        block = rm.record(_PR, "runtime", [], [], repo=run_repo, run_id=_RUN_ID)
        assert f"/{_RUN_ID}/findings/runtime.json" in block
        assert (rm.run_dir(_PR, run_repo, _RUN_ID) / "findings" / "runtime.json").is_file()
        assert not (rm.run_dir(_PR, run_repo) / "findings").exists()

    def test_record_fixes_writes_under_named_run(self, run_repo: Path) -> None:
        rm.start_run(_PR, _OTHER_RUN, repo=run_repo)
        fixed = [{"id": "M1", "what": "w", "files": ["a.py"]}]
        rm.record_fixes(_PR, "w1_fix_1", fixed, repo=run_repo, run_id=_RUN_ID)
        assert (rm.run_dir(_PR, run_repo, _RUN_ID) / "fixes" / "w1_fix_1.json").is_file()
        assert not (rm.run_dir(_PR, run_repo) / "fixes").exists()


class _NoReconfigure:
    """A cp1252 text stream without ``reconfigure``, over a bytes buffer."""

    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def write(self, text: str) -> int:
        return self.buffer.write(text.encode("cp1252"))

    def flush(self) -> None:
        """No-op flush."""


class TestEncodingSafeBlock:
    def test_cp1252_stream_is_reconfigured(self, run_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")
        monkeypatch.setattr(sys, "stdout", stream)
        fixed = [{"id": "M1", "what": "a → b", "files": ["a.py"]}]
        block = rm.record_fixes(_PR, "w1_fix_1", fixed, repo=run_repo)
        stream.flush()
        assert "a → b" in block and "a → b".encode("utf-8") in raw.getvalue()

    def test_stream_without_reconfigure_gets_utf8_bytes(self, run_repo: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
        stream = _NoReconfigure()
        monkeypatch.setattr(sys, "stdout", stream)
        fixed = [{"id": "M1", "what": "x → y", "files": ["a.py"]}]
        rm.record_fixes(_PR, "w1_fix_1", fixed, repo=run_repo)
        written = stream.buffer.getvalue()
        assert b"SIGNAL: DONE" in written and "x → y".encode("utf-8") in written


def _schema_validator(project: Path) -> jsonschema.protocols.Validator:
    """PR_REVIEW validator built from the schema ``schema_path`` resolves for ``project``."""
    path = schema_path("PR_REVIEW.schema.json", load_config(project))
    schema = json.loads(path.read_text(encoding="utf-8"))
    return jsonschema.validators.validator_for(schema)(schema)


class TestSchemaFixKind:
    @staticmethod
    def _issue_errors(project: Path, fix_kind: object) -> list:
        issue = {"id": "M1", "name": "n", "summary": "s", "fix": ["f"], "file": "a.py", "fix_kind": fix_kind}
        validator = _schema_validator(project)
        schema = validator.schema
        definitions = schema["definitions"]
        issue_validator = type(validator)({**definitions["issue"], "definitions": definitions})
        return list(issue_validator.iter_errors(issue))

    @pytest.mark.parametrize("value", ["mechanical", "judgment"])
    def test_accepted(self, project: Path, value: str) -> None:
        assert self._issue_errors(project, value) == []

    def test_unknown_rejected(self, project: Path) -> None:
        errors = self._issue_errors(project, "easy")
        assert any(list(err.path)[-1:] == ["fix_kind"] for err in errors)
