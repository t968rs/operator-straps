"""Adversarial review models in ``review_models``: the workflow references, the code refuter's
``AttackFinding`` / ``CodeRefuterReport``, the ``adv_code`` id rule on every record and load call, the
content keys (``finding_key``, ``report_digest``) and the findings refuter's ``RefutationReport``."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, List

import pytest

from harness_lib import review_models as rm
from harness_lib.config import activate, load_config

_PR = 77
_RUN_ID = "pr77_20261112T000000Z"
_SCRATCH = "build/runs"
_CTX = {"root": "/repo"}
_KEY = re.compile(r"^[0-9a-f]{12}$")


def _finding(**overrides: object) -> Dict[str, object]:
    """A valid finding mapping; ``overrides`` replace or add keys."""
    base: Dict[str, object] = {"severity": "minor", "name": "Off by one", "summary": "s", "fix": ["f"],
                               "file": "src/a.py", "lines": "3", "fix_kind": "mechanical"}
    base.update(overrides)
    return base


def _refusal(call: Callable[[], object]) -> str:
    """Message of the refusal ``call`` raises; AssertionError when ``call`` accepts its input."""
    try:
        call()
    except (ValueError, FileNotFoundError) as exc:
        return str(exc)
    raise AssertionError("call accepted input it must refuse")


def _verdict(entry: rm.Refutation) -> str:
    """A refutation entry's verdict as plain text (enum or string)."""
    return str(getattr(entry.verdict, "value", entry.verdict))


@pytest.fixture
def run(make_project) -> Path:
    """An activated project with a started run for ``_PR``."""
    root = make_project(config={"artifacts": {"scratch": _SCRATCH}}, files={"src/a.py": "x = 1\n"})
    activate(load_config(root))
    rm.start_run(_PR, _RUN_ID, repo=root)
    return root


def _findings_file(repo: Path, agent: str) -> Path:
    return rm.run_dir(_PR, repo) / "findings" / f"{agent}.json"


def _target(repo: Path) -> rm.ReviewerReport:
    """The ``runtime`` slot recorded with two findings, read back."""
    rm.record(_PR, "runtime", [_finding(), _finding(name="Second", lines="40")], repo=repo)
    return rm.load_report(_findings_file(repo, "runtime"))


def _entries(report: rm.ReviewerReport, *verdicts: str) -> List[Dict[str, str]]:
    """One ``{key, verdict, evidence}`` entry per finding of ``report``."""
    return [{"key": rm.finding_key(f), "verdict": v, "evidence": f"{f.file}:{f.lines} shows it"}
            for f, v in zip(report.findings, verdicts)]


# --- constants and models ------------------------------------------------------------------------------


def test_workflow_references_name_the_script_the_agent_and_the_model() -> None:
    assert rm.ADVERSARIAL_WORKFLOW == "workflows/adversarial-review.js"
    assert rm.ADVERSARIAL_AGENT == "harness:adversarial-reviewer"
    assert rm.REFUTER_MODEL == "opus"


def test_attack_finding_requires_a_non_empty_attack() -> None:
    assert issubclass(rm.AttackFinding, rm.Finding)
    built = rm.AttackFinding.model_validate(_finding(attack="f(-1) returns 0"), context=_CTX)
    assert built.attack == "f(-1) returns 0"
    _refusal(lambda: rm.AttackFinding.model_validate(_finding(), context=_CTX))
    _refusal(lambda: rm.AttackFinding.model_validate(_finding(attack=""), context=_CTX))


def test_code_refuter_report_holds_attack_findings() -> None:
    assert issubclass(rm.CodeRefuterReport, rm.ReviewerReport)
    data = {"reviewer": "adv_code", "findings": [_finding(attack="f(-1) returns 0")]}
    report = rm.CodeRefuterReport.model_validate(data, context=_CTX)
    assert isinstance(report.findings[0], rm.AttackFinding)
    bare = {"reviewer": "adv_code", "findings": [_finding()]}
    _refusal(lambda: rm.CodeRefuterReport.model_validate(bare, context=_CTX))


# --- the adv_code id rule on record and load ------------------------------------------------------------


def test_record_validates_an_adv_code_id_as_a_code_refuter_report(run: Path) -> None:
    assert "attack" in _refusal(lambda: rm.record(_PR, "adv_code", [_finding()], repo=run))


def test_record_add_validates_an_adv_code_id(run: Path) -> None:
    assert "attack" in _refusal(lambda: rm.record_add(_PR, "adv_code_tests", [_finding()], repo=run))


def test_record_draft_validates_an_adv_code_id(run: Path) -> None:
    draft = rm.draft_path(_PR, "adv_code", run)
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(json.dumps({"findings": [_finding()]}), encoding="utf-8")
    assert "attack" in _refusal(lambda: rm.record_draft(_PR, "adv_code", repo=run))


def test_load_report_validates_an_adv_code_file(run: Path) -> None:
    path = _findings_file(run, "adv_code")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"reviewer": "adv_code", "findings": [_finding()], "strengths": []}),
                    encoding="utf-8")
    assert "attack" in _refusal(lambda: rm.load_report(path))


def test_record_attacks_round_trips_through_load_report(run: Path) -> None:
    rm.record_attacks(_PR, "adv_code", [_finding(attack="f(-1) returns 0")], repo=run)
    report = rm.load_report(_findings_file(run, "adv_code"))
    assert isinstance(report, rm.CodeRefuterReport)
    assert report.findings[0].attack == "f(-1) returns 0"


def test_record_attacks_refuses_an_id_outside_adv_code(run: Path) -> None:
    findings = [_finding(attack="f(-1) returns 0")]
    _refusal(lambda: rm.record_attacks(_PR, "runtime", findings, repo=run))
    assert not _findings_file(run, "runtime").exists()


def test_record_attacks_draft_reads_the_draft_file(run: Path) -> None:
    draft = rm.draft_path(_PR, "adv_code", run)
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(json.dumps({"findings": [_finding(attack="f(-1) returns 0")]}), encoding="utf-8")
    rm.record_attacks_draft(_PR, "adv_code", repo=run)
    assert rm.load_report(_findings_file(run, "adv_code")).findings[0].attack == "f(-1) returns 0"


# --- content keys ---------------------------------------------------------------------------------------


def test_finding_key_is_stable_and_content_sensitive() -> None:
    one = rm.Finding.model_validate(_finding(), context=_CTX)
    same = rm.Finding.model_validate(_finding(), context=_CTX)
    other = rm.Finding.model_validate(_finding(summary="another claim"), context=_CTX)
    assert _KEY.match(rm.finding_key(one))
    assert rm.finding_key(one) == rm.finding_key(same)
    assert rm.finding_key(one) != rm.finding_key(other)


def test_report_digest_follows_the_findings_list() -> None:
    def report(*findings: Dict[str, object], strengths: tuple = ()) -> rm.ReviewerReport:
        data = {"reviewer": "runtime", "findings": list(findings), "strengths": list(strengths)}
        return rm.ReviewerReport.model_validate(data, context=_CTX)

    base = rm.report_digest(report(_finding()))
    assert _KEY.match(base)
    assert rm.report_digest(report(_finding(), strengths=("clean seams",))) == base
    assert rm.report_digest(report(_finding(), _finding(name="Second", lines="40"))) != base


# --- refutations ----------------------------------------------------------------------------------------


def test_refutation_needs_evidence_when_refuted() -> None:
    upheld = rm.Refutation(key="0123456789ab", verdict="upheld", evidence="src/a.py:3 shows it")
    assert _verdict(upheld) == "upheld"
    assert _verdict(rm.Refutation(key="0123456789ab", verdict="upheld", evidence="")) == "upheld"
    _refusal(lambda: rm.Refutation(key="0123456789ab", verdict="refuted", evidence=""))
    _refusal(lambda: rm.Refutation(key="0123456789ab", verdict="maybe", evidence="e"))


def test_record_refutations_writes_the_target_report_digest(run: Path) -> None:
    target = _target(run)
    rm.record_refutations(_PR, "adv_refute_runtime", "runtime", _entries(target, "refuted", "upheld"),
                          repo=run)
    report = rm.load_refutations(rm.run_dir(_PR, run) / "refutations" / "runtime.json")
    assert (report.refuter, report.target) == ("adv_refute_runtime", "runtime")
    assert report.report_digest == rm.report_digest(target)
    assert [(e.key, _verdict(e)) for e in report.refutations] == [
        (rm.finding_key(target.findings[0]), "refuted"), (rm.finding_key(target.findings[1]), "upheld")]
    assert not _findings_file(run, "adv_refute_runtime").exists()


@pytest.mark.parametrize("shape", ["missing", "extra", "duplicate"])
def test_record_refutations_refuses_a_bad_key_set(run: Path, shape: str) -> None:
    entries = _entries(_target(run), "upheld", "upheld")
    bogus = {"key": "000000000000", "verdict": "upheld", "evidence": "e"}
    bad = {"missing": entries[:1], "extra": [*entries, bogus], "duplicate": [*entries, entries[0]]}[shape]
    _refusal(lambda: rm.record_refutations(_PR, "adv_refute_runtime", "runtime", bad, repo=run))
    assert not (rm.run_dir(_PR, run) / "refutations" / "runtime.json").exists()


def test_record_refutations_refuses_a_target_without_a_report(run: Path) -> None:
    entries = [{"key": "0123456789ab", "verdict": "upheld", "evidence": "e"}]
    _refusal(lambda: rm.record_refutations(_PR, "adv_refute_overall", "overall", entries, repo=run))


def test_record_refutations_draft_reads_the_draft_file(run: Path) -> None:
    entries = _entries(_target(run), "upheld", "refuted")
    draft = rm.draft_path(_PR, "adv_refute_runtime", run)
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(json.dumps({"refutations": entries}), encoding="utf-8")
    rm.record_refutations_draft(_PR, "adv_refute_runtime", "runtime", repo=run)
    report = rm.load_refutations(rm.run_dir(_PR, run) / "refutations" / "runtime.json")
    assert [_verdict(e) for e in report.refutations] == ["upheld", "refuted"]


def test_load_refutations_round_trips(tmp_path: Path) -> None:
    entries = (rm.Refutation(key="0123456789ab", verdict="refuted", evidence="src/a.py:3 is guarded"),)
    report = rm.RefutationReport(refuter="adv_refute_runtime", target="runtime",
                                 report_digest="abcdef012345", refutations=entries)
    path = tmp_path / "runtime.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    assert rm.load_refutations(path) == report
