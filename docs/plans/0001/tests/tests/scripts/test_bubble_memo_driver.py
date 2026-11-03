"""Behavioral tests of ``scripts/bubble_memo.py`` against throwaway git projects.

The driver runs in-process through ``main`` with ``--repo``; the memo, scratch reports and output are read back.
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Optional, Tuple

import pytest

from harness_lib import bubble_memo as bm

Result = Tuple[int, str, str]
RUN_ID = "pr1514_20261029T000000Z"
LINES = "".join(f"x = {n}\n" for n in range(1, 31))


def _issue(issue_id: str, name: str, **extra: Any) -> Dict[str, Any]:
    return {"id": issue_id, "name": name, "summary": f"{name} summary", "fix": ["fix one", "fix two"], **extra}


REVIEW = {
    "pr": 1514, "pr_title": "Feature x", "branch": "feat", "base_branch": "main",
    "base_sha": "aaaaaaa", "head_sha": "bbbbbbb", "bubbles": ["I2"],
    "bubble_up": [{"id": "I2", "classification": "architectural_ambiguity", "reason": "two fixes"}],
    "post_review_resolutions": [],
    "issues": {"critical": [], "minor": [], "important": [
        _issue("I2", "Stale cache", file="src/a.py", lines="10-12"),
        _issue("I3", "Two files", files=["src/a.py", "src/b.py"]),
    ]},
}
FIXER = {"fixer": "fixer_a", "fixed": [], "bubbled": [
    {"id": "I3", "classification": "needs_follow_up", "reason": "needs a follow-up"}]}
REVIEW_PATH = "docs/PR_REVIEWS/1514_Feature_x.json"
MEMO_PATH = "docs/PR_REVIEWS/PR_1514_Bubbles.md"
SCRATCH = "docs/_scratch/pr_review"


@pytest.fixture(scope="module")
def driver(plugin_root: Path) -> ModuleType:
    path = plugin_root / "scripts" / "bubble_memo.py"
    assert path.is_file(), f"{path} does not exist"
    spec = importlib.util.spec_from_file_location("bubble_memo_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _files(with_run: bool = True) -> Dict[str, Any]:
    files: Dict[str, Any] = {"src/a.py": LINES, "src/b.py": LINES, REVIEW_PATH: REVIEW}
    if with_run:
        files[f"{SCRATCH}/1514/current"] = RUN_ID + "\n"
        files[f"{SCRATCH}/1514/{RUN_ID}/fixes/fixer_a.json"] = FIXER
    return files


@pytest.fixture()
def project(make_project: Callable[..., Path]) -> Path:
    return make_project({"base_branch": "main"}, files=_files())


@pytest.fixture()
def run(driver: ModuleType, project: Path, capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch) -> Callable[..., Result]:
    def _run(*args: str, stdin: Optional[str] = None) -> Result:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin or ""))
        code = driver.main(["--repo", str(project), *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    return _run


def _memo(project: Path) -> str:
    return (project / MEMO_PATH).read_text(encoding="utf-8")


def _fill_all(project: Path) -> None:
    text = _memo(project).replace(f":{bm.STUB}", ":1").replace(bm.STUB, "filled")
    (project / MEMO_PATH).write_text(text, encoding="utf-8")


def test_scaffold_covers_bubbles_and_pending_fixer_bubbles(run: Callable[..., Result], project: Path) -> None:
    code, out, _ = run("scaffold", "--pr", "1514")
    assert code == 0
    assert [r.id for r in bm.parse_index(_memo(project))] == ["I2", "I3"]
    assert "I2" in out and "I3" in out


def test_scaffold_prints_one_investigator_row_per_flagged_id(run: Callable[..., Result]) -> None:
    _, out, _ = run("scaffold", "--pr", "1514")
    rows = out.count("agent=harness:bubble-memo-investigator model=opus")
    assert rows == 1
    tail = out[out.index("agent=harness:bubble-memo-investigator"):].splitlines()
    assert tail[1:4] == ["PR: 1514", "ISSUE: I3", "FILES: src/a.py, src/b.py"]
    assert tail[4].startswith("CONTEXT: ") and len(tail[4]) <= len("CONTEXT: ") + 300


def test_scaffold_rerun_changes_nothing(run: Callable[..., Result], project: Path) -> None:
    run("scaffold", "--pr", "1514")
    before = _memo(project)
    code, out, _ = run("scaffold", "--pr", "1514")
    assert code == 0 and _memo(project) == before
    assert "agent=" not in out


def test_scaffold_without_anything_bubbled_writes_no_memo(
        driver: ModuleType, make_project: Callable[..., Path], capsys: pytest.CaptureFixture) -> None:
    doc = {**REVIEW, "bubbles": []}
    root = make_project({"base_branch": "main"}, files={**_files(with_run=False), REVIEW_PATH: doc})
    assert driver.main(["--repo", str(root), "scaffold", "--pr", "1514"]) == 0
    assert "nothing currently bubbled" in capsys.readouterr().out
    assert not (root / MEMO_PATH).exists()


def test_a_missing_review_is_a_problem(driver: ModuleType, make_project: Callable[..., Path],
                                       capsys: pytest.CaptureFixture) -> None:
    root = make_project({"base_branch": "main"}, files={"src/a.py": LINES})
    assert driver.main(["--repo", str(root), "scaffold", "--pr", "1514"]) == 1
    assert capsys.readouterr().err.startswith("problem: ")


def test_check_fails_on_stubs_and_passes_once_filled(run: Callable[..., Result], project: Path) -> None:
    run("scaffold", "--pr", "1514")
    code, _, err = run("check", "--pr", "1514")
    assert code == 1 and "I2: " in err
    _fill_all(project)
    code, out, _ = run("check", "--pr", "1514")
    assert code == 0 and "check [ok]" in out


def test_check_prints_the_reviewer_row_with_the_model_rule(run: Callable[..., Result], project: Path) -> None:
    run("scaffold", "--pr", "1514")
    _fill_all(project)
    _, out, _ = run("check", "--pr", "1514")
    assert "agent=harness:bubble-memo-reviewer model=opus" in out
    assert f"Memo: {(project / MEMO_PATH).resolve().as_posix()}" in out


def test_init_prints_the_brief_and_saves_it(run: Callable[..., Result], project: Path) -> None:
    run("scaffold", "--pr", "1514")
    (project / "src" / "a.py").write_text(LINES + "x = 31\n", encoding="utf-8")
    head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    code, out, _ = run("init", "--pr", "1514", "--id", "I2", "--role", "investigator")
    assert code == 0
    assert "fix one" in out and "fix two" in out and head[:7] in out
    assert "x = 10" in out and "x = 12" in out and "x = 30" not in out
    assert "M src/a.py" in out
    assert "bubble_memo.py" in out and "--role investigator" in out
    saved = project / SCRATCH / "bubble_memo" / "1514" / "briefs" / "I2.md"
    assert saved.read_text(encoding="utf-8") == out


def _facts(**over: Any) -> str:
    base = {"id": "I3", "current_behavior": "reads a stale value", "when": "the cache is warm",
            "chain": ["a reads", "b trusts it"], "flow": "a -> b",
            "references": [{"at": "src/a.py:3-5", "note": "read"}, {"at": "src/b.py:2", "note": "use"}],
            "fix_effects": [{"option": "fix one", "effect": "refreshes first"},
                            {"option": "fix two", "effect": "drops the cache"}], "confidence": "high"}
    return json.dumps({**base, **over})


def test_record_writes_facts_and_prints_the_return_block(run: Callable[..., Result], project: Path) -> None:
    run("scaffold", "--pr", "1514")
    code, out, _ = run("record", "--pr", "1514", "--id", "I3", "--role", "investigator", stdin=_facts())
    assert code == 0 and "SIGNAL: DONE" in out and out.lstrip().startswith("---")
    saved = project / SCRATCH / "bubble_memo" / "1514" / "facts" / "I3.json"
    assert json.loads(saved.read_text(encoding="utf-8"))["id"] == "I3"


def test_record_refuses_a_reference_off_disk(run: Callable[..., Result], project: Path) -> None:
    run("scaffold", "--pr", "1514")
    bad = _facts(references=[{"at": "src/a.py:99", "note": "past the end"}])
    code, _, err = run("record", "--pr", "1514", "--id", "I3", "--role", "investigator", stdin=bad)
    assert code == 1 and err.startswith("problem: ")
    assert not (project / SCRATCH / "bubble_memo" / "1514" / "facts" / "I3.json").exists()


def test_apply_writes_facts_into_the_entry_and_leaves_prose_stubs(run: Callable[..., Result], project: Path) -> None:
    run("scaffold", "--pr", "1514")
    run("record", "--pr", "1514", "--id", "I3", "--role", "investigator", stdin=_facts())
    code, _, _ = run("apply", "--pr", "1514")
    block = bm.entry_blocks(_memo(project))["I3"]
    assert code == 0 and "reads a stale value" in block and "- (a) fix one -> refreshes first" in block
    assert f"- **Description:** {bm.STUB}" in block


def test_reviewer_init_lists_every_entry(run: Callable[..., Result], project: Path) -> None:
    run("scaffold", "--pr", "1514")
    _fill_all(project)
    code, out, _ = run("init", "--pr", "1514", "--role", "reviewer")
    assert code == 0 and "I2" in out and "I3" in out and "--role reviewer" in out


def test_reviewer_record_validates_findings(run: Callable[..., Result], project: Path) -> None:
    run("scaffold", "--pr", "1514")
    good = json.dumps({"findings": [{"id": "I2", "kind": "clarity", "what": "wordy", "suggested": "shorter"}]})
    code, out, _ = run("record", "--pr", "1514", "--role", "reviewer", stdin=good)
    assert code == 0 and "SIGNAL: DONE" in out
    bad = json.dumps({"findings": [{"id": "I2", "kind": "tone", "what": "x", "suggested": "y"}]})
    code, _, err = run("record", "--pr", "1514", "--role", "reviewer", stdin=bad)
    assert code == 1 and err.startswith("problem: ")
