"""review_edit closeout batch: idempotent ``resolve-file``, bubble-up mirroring, string-only evidence and the
CLI's verdict guards."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict

import pytest

from harness_lib import review_edit as red
from harness_lib.config import activate, load_config

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "review_edit"
_SHA = "3333333ccccccc"
_GOOD = [{"id": "I1", "status": "RESOLVED", "evidence": "bound added", "date": "2026-10-02"},
         {"id": "M1", "status": "RESOLVED", "evidence": "typo fixed", "date": "2026-10-02"}]
_SIDECAR = {"run_id": "pr19_20261016T205358Z",
            "items": [{"id": "M2", "classification": "fixer_failed", "reason": "fixer FAIL: test red"}]}


@pytest.fixture
def project(make_project) -> Path:
    """An activated throwaway project (the plugin's schema governs)."""
    root = make_project(config={})
    activate(load_config(root))
    return root


@pytest.fixture
def doc() -> Dict[str, object]:
    return red.load_review(_FIXTURES / "open_review.json")


def test_resolve_all_twice_adds_one_entry_per_id(doc: Dict[str, object]) -> None:
    once = red.resolve_all(doc, _GOOD, _SHA)
    twice = red.resolve_all(once, _GOOD, _SHA)
    assert [e["id"] for e in twice["post_review_resolutions"]] == ["I1", "M1"]  # type: ignore[union-attr]
    assert twice == once


def test_resolve_all_appends_a_changed_status(doc: Dict[str, object]) -> None:
    once = red.resolve_all(doc, _GOOD, _SHA)
    reopened = red.resolve_all(once, [{"id": "M1", "status": "DOWNGRADED_TO_MINOR", "evidence": "x"}], _SHA)
    assert [e["id"] for e in reopened["post_review_resolutions"]] == ["I1", "M1", "M1"]  # type: ignore


@pytest.mark.parametrize("evidence", [True, ["a"], {"k": "v"}, 7, None])
def test_resolve_all_refuses_non_string_evidence(doc: Dict[str, object], evidence: object) -> None:
    with pytest.raises(ValueError, match="entry 1 \\(I1\\): evidence must be a string"):
        red.resolve_all(doc, [{"id": "I1", "status": "RESOLVED", "evidence": evidence}], _SHA)


def test_mirrored_bubble_settles_a_failed_minor(doc: Dict[str, object]) -> None:
    out = red.resolve_all(doc, _GOOD, _SHA, _SIDECAR["items"])  # type: ignore[arg-type]
    assert out["verdict"] == "READY TO MERGE - 2 of 3 findings resolved, 1 bubbled"
    again = red.resolve_all(out, _GOOD, _SHA, _SIDECAR["items"])  # type: ignore[arg-type]
    assert again == out


def test_mirror_replaces_in_place_and_refuses_bad_items(doc: Dict[str, object]) -> None:
    out = red.add_bubble_up(red.add_bubble_up(doc, "M1", "out_of_scope", "a"), "M2", "out_of_scope", "b")
    swapped = red.mirror_bubble_ups(out, [{"id": "M1", "classification": "needs_follow_up", "reason": "c"}])
    assert [(b["id"], b["classification"]) for b in swapped["bubble_up"]] == [  # type: ignore[union-attr]
        ("M1", "needs_follow_up"), ("M2", "out_of_scope")]
    with pytest.raises(ValueError, match="bubble-up item 1"):
        red.mirror_bubble_ups(doc, [{"id": "M1", "classification": "x", "reason": 3}])
    with pytest.raises(ValueError, match="bubble-up item 1 \\(M9\\)"):
        red.mirror_bubble_ups(doc, [{"id": "M9", "classification": "out_of_scope", "reason": "r"}])


def _cli(project: Path, plugin_root: Path, target: Path, *args: str) -> subprocess.CompletedProcess:
    script = str(plugin_root / "scripts" / "review_edit.py")
    return subprocess.run([sys.executable, script, str(target), "--repo", str(project), *args],
                          capture_output=True, text=True, timeout=60)


def _copy(project: Path) -> Path:
    target = project / "review.json"
    shutil.copyfile(_FIXTURES / "open_review.json", target)
    return target


def test_cli_resolve_file_rerun_and_bubble_ups(project: Path, plugin_root: Path) -> None:
    target = _copy(project)
    proposed = project / "proposed_resolutions.json"
    sidecar = project / "bubble_ups.json"
    proposed.write_text(json.dumps(_GOOD), "utf-8")
    sidecar.write_text(json.dumps(_SIDECAR), "utf-8")
    args = ("resolve-file", str(proposed), "--sha", _SHA, "--bubble-ups", str(sidecar))
    for _ in range(2):
        done = _cli(project, plugin_root, target, *args)
        assert done.returncode == 0, done.stderr
        assert "verdict: READY TO MERGE - 2 of 3 findings resolved, 1 bubbled" in done.stdout
    doc = red.load_review(target)
    assert [e["id"] for e in doc["post_review_resolutions"]] == ["I1", "M1"]  # type: ignore[union-attr]
    assert [b["id"] for b in doc["bubble_up"]] == ["M2"]  # type: ignore[union-attr]


def test_cli_non_string_evidence_leaves_review_unchanged(project: Path, plugin_root: Path) -> None:
    target = _copy(project)
    proposed = project / "proposed_resolutions.json"
    proposed.write_text(json.dumps([{"id": "I1", "status": "RESOLVED", "evidence": True}]), "utf-8")
    done = _cli(project, plugin_root, target, "resolve-file", str(proposed), "--sha", _SHA)
    assert done.returncode == 1 and "evidence must be a string" in done.stderr
    assert target.read_bytes() == (_FIXTURES / "open_review.json").read_bytes()


def test_cli_rejects_top_level_recompute_with_verdict(project: Path, plugin_root: Path) -> None:
    target = _copy(project)
    done = _cli(project, plugin_root, target, "--recompute", "verdict", "--text", "NOT READY TO MERGE - hold")
    assert done.returncode == 1 and "conflicts with verdict" in done.stderr
    assert target.read_bytes() == (_FIXTURES / "open_review.json").read_bytes()


def test_cli_refuses_stale_ready(project: Path, plugin_root: Path) -> None:
    target = _copy(project)
    entries = [*_GOOD, {"id": "M2", "status": "RESOLVED", "evidence": "x"}]
    ready = red.resolve_all(red.load_review(target), entries, _SHA)
    target.write_bytes(red.dumps_review(ready).encode("utf-8"))
    before = target.read_bytes()
    done = _cli(project, plugin_root, target, "resolve", "I1", "DOWNGRADED_TO_MINOR", "minor", "--sha", _SHA)
    assert done.returncode == 1 and "stale READY verdict" in done.stderr, done.stderr
    assert target.read_bytes() == before
    done = _cli(project, plugin_root, target, "--recompute", "resolve", "I1", "DOWNGRADED_TO_MINOR", "minor",
                "--sha", _SHA)
    assert done.returncode == 0, done.stderr
    assert red.load_review(target)["verdict"] == "NOT READY TO MERGE - important: I1"
