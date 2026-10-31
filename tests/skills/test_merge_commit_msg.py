"""Behavioral tests for the merge-commit-msg skill command ``commands/merge_commit_msg.py``.

``gh`` is the one seam: each test swaps ``module.gh`` for a function answering from a canned PR. Everything
else (config, review JSON, commit-message TXT, the message on stdin, the TXT on disk) is real.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from conftest import git

TITLE = "[BUG] Worker pool crash on spawn"
SUBJECT = f"Merge PR #7 — {TITLE}"
MESSAGE = [
    SUBJECT,
    "",
    "Fixes a BrokenProcessPool failure in the export pool.",
    "Spawned children attach to invalid stdio handles.",
    "",
    "  - workers/export.py: add a stdio guard at worker entry",
    "  - tests/test_export.py: cover the spawn path",
    "",
    "Branch lineage: `main` -> `7-bug-worker`",
]


@pytest.fixture(scope="module")
def module(plugin_root: Path):
    path = plugin_root / "skills" / "merge-commit-msg" / "commands" / "merge_commit_msg.py"
    spec = importlib.util.spec_from_file_location("merge_commit_msg", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gh(view: Optional[dict] = None, files: Optional[List[str]] = None, commits: Optional[List[str]] = None):
    shape = {"number": 7, "title": TITLE, "headRefName": "7-bug-worker", "baseRefName": "main",
             "additions": 40, "deletions": 3, "changedFiles": 2, "body": "", "state": "OPEN", **(view or {})}
    names = files if files is not None else ["workers/export.py", "tests/test_export.py"]
    heads = commits if commits is not None else ["Fix(workers): guard stdio", "Test(workers): spawn path"]

    def fake(repo: Path, *args: str) -> str:
        if args[:2] == ("pr", "view"):
            return json.dumps(shape)
        if args[:2] == ("pr", "diff"):
            return "\n".join(names) + "\n"
        if args[0] == "api":
            return "\n".join(heads) + "\n"
        raise AssertionError(f"unexpected gh call: {args}")

    return fake


def _project(make_project, files: Optional[Dict[str, str]] = None, config: Optional[dict] = None) -> Path:
    root = make_project(config, files=files or {})
    git(root, "checkout", "-q", "-b", "7-bug-worker")
    return root


def _run(module, root: Path, *argv: str) -> int:
    return module.main(["--repo", str(root), *argv])


def _folder(root: Path) -> Path:
    return root / "docs" / "_commit_messages"


def _txt(root: Path, pr: int = 7) -> Path:
    return _folder(root) / f"PR{pr}_merge.txt"


def _fence(text: str) -> List[str]:
    lines = text.splitlines()
    assert "```text" in lines, "capture printed no message skeleton"
    start = lines.index("```text")
    return lines[start + 1:lines.index("```", start + 1)]


def _capture(module, root: Path, monkeypatch, capsys, view: Optional[dict] = None,
             files: Optional[List[str]] = None, commits: Optional[List[str]] = None) -> str:
    monkeypatch.setattr(module, "gh", _gh(view, files, commits))
    assert _run(module, root, "capture", "7") == 0
    return capsys.readouterr().out


def _build(module, root: Path, monkeypatch, message: List[str], view: Optional[dict] = None) -> int:
    monkeypatch.setattr(module, "gh", _gh(view))
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(message) + "\n"))
    return _run(module, root, "build", "7")


class TestCapture:
    def test_prints_the_facts_and_writes_no_file(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)
        out = _capture(module, root, monkeypatch, capsys)
        headings = ("## Facts", "## Changed files", "## Commits", "## Branch commit subjects", "## Message")
        assert all(heading in out for heading in headings)
        assert f"- Title: {TITLE}" in out and "- `workers/export.py`" not in out
        assert "- workers/export.py" in out and "- Fix(workers): guard stdio" in out
        assert not (root / "docs").exists()

    def test_fence_holds_subject_placeholders_and_lineage(self, module, make_project, monkeypatch,
                                                          capsys) -> None:
        root = _project(make_project)
        fence = _fence(_capture(module, root, monkeypatch, capsys))
        assert fence[0] == SUBJECT and fence[1] == ""
        assert module.PROSE_HINT in fence and module.BULLET_HINT in fence
        assert "Branch lineage: `main` -> `7-bug-worker`" in fence

    def test_lineage_comes_from_the_pr_body(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)
        body = "Notes\n[main]-->[1007-parent]-->[7-bug-worker]\n"
        fence = _fence(_capture(module, root, monkeypatch, capsys, view={"body": body}))
        assert "Branch lineage: `main` -> `1007-parent` -> `7-bug-worker`" in fence

    def test_canned_set_prefills_the_prose(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)
        canned_set = ["docs/PR_REVIEWS/0007_x.json", "docs/PR_SUMMARIES/7.md"]
        out = _capture(module, root, monkeypatch, capsys, files=canned_set)
        assert any(line.startswith("Chore(reviews): record PR review") for line in _fence(out))
        assert module.PROSE_HINT not in _fence(out)
        assert "- Canned message: yes" in out

    def test_review_json_adds_the_trailer_with_fix_counts(self, module, make_project, monkeypatch,
                                                          capsys) -> None:
        review = {"issues": {"critical": [{"id": "C1"}], "important": [{"id": "I1"}, {"id": "I2"}],
                             "minor": [{"id": "M1"}]},
                  "post_review_resolutions": [{"id": "C1", "status": "RESOLVED"},
                                              {"id": "I1", "status": "RESOLVED"},
                                              {"id": "I2", "status": "CLOSED_NO_ACTION"},
                                              {"id": "M1", "status": "RESOLVED"}]}
        root = _project(make_project, {"docs/PR_REVIEWS/0007_Bug_worker.json": json.dumps(review)})
        fence = _fence(_capture(module, root, monkeypatch, capsys))
        assert "Review artifacts: docs/PR_REVIEWS/0007_Bug_worker.json." in fence
        assert "Includes 3 review fixes (Critical: 1, Important: 1, Minor: 1)." in fence

    def test_long_review_path_moves_to_its_own_line(self, module, make_project, monkeypatch, capsys) -> None:
        name = "0007_" + "A_long_title_" * 6 + "end.json"
        root = _project(make_project, {f"docs/PR_REVIEWS/{name}": json.dumps({"issues": {}})})
        fence = _fence(_capture(module, root, monkeypatch, capsys))
        at = fence.index("Review artifacts:")
        assert fence[at + 1] == f"docs/PR_REVIEWS/{name}."
        assert max(len(line) for line in fence) <= module.LINE_WIDTH

    def test_no_review_json_means_no_trailer(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)
        fence = _fence(_capture(module, root, monkeypatch, capsys))
        assert not any(line.startswith(("Review artifacts", "Includes")) for line in fence)

    def test_branch_ledger_subjects_are_listed(self, module, make_project, monkeypatch, capsys) -> None:
        ledger = ("Branch: `7-bug-worker`\nMerge base: abc\n\n===\n\n"
                  'Commit 1 - Runtime (1 files)\n"workers/export.py",\n\n'
                  "Fix(workers): guard stdio\n\nBody.\n  - export.py: guard\n"
                  "\nBranch: `7-bug-worker`\n")
        root = _project(make_project, {"docs/_commit_messages/7-bug-worker.txt": ledger})
        out = _capture(module, root, monkeypatch, capsys, commits=["wip"])
        section = out.split("## Branch commit subjects")[1]
        assert "- Fix(workers): guard stdio" in section.split("## Message")[0]

    def test_a_closed_pr_is_a_problem(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)
        monkeypatch.setattr(module, "gh", _gh({"state": "MERGED"}))
        assert _run(module, root, "capture", "7") == 1
        captured = capsys.readouterr()
        assert "problem: PR #7 is MERGED" in captured.err and not captured.out
        assert not (root / "docs").exists()

    def test_gh_failure_is_a_problem(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)

        def failing(repo: Path, *args: str) -> str:
            raise module.MergeMessageError("gh pr view failed: not found")

        monkeypatch.setattr(module, "gh", failing)
        assert _run(module, root, "capture", "7") == 1
        assert "problem: gh pr view failed" in capsys.readouterr().err


class TestBuild:
    def test_writes_the_stdin_message_as_the_txt_and_prints_the_receipt(self, module, make_project,
                                                                        monkeypatch, capsys) -> None:
        root = _project(make_project)
        assert _build(module, root, monkeypatch, MESSAGE) == 0
        assert _txt(root).read_text(encoding="utf-8") == "\n".join(MESSAGE) + "\n"
        out = capsys.readouterr().out.splitlines()
        assert out[0] == "Saved: docs/_commit_messages/PR7_merge.txt - merge message for PR #7"
        assert out[1] == f"Subject: {SUBJECT}"
        assert out[2].startswith("Final as saved:") and "stdin" in out[2] and "_merge.md" not in out[2]

    def test_writes_only_the_txt(self, module, make_project, monkeypatch) -> None:
        root = _project(make_project)
        assert _build(module, root, monkeypatch, MESSAGE) == 0
        assert sorted(path.name for path in _folder(root).iterdir()) == ["PR7_merge.txt"]

    def test_capture_then_fill_then_build_round_trips(self, module, make_project, monkeypatch,
                                                      capsys) -> None:
        root = _project(make_project)
        skeleton = _fence(_capture(module, root, monkeypatch, capsys))
        fills = {module.PROSE_HINT: "Fixes the spawn crash.",
                 module.BULLET_HINT: "  - workers/export.py: add a stdio guard"}
        assert _build(module, root, monkeypatch, [fills.get(line, line) for line in skeleton]) == 0
        assert _txt(root).read_text(encoding="utf-8").startswith(SUBJECT + "\n\nFixes the spawn crash.")

    def test_trailing_blank_lines_are_dropped(self, module, make_project, monkeypatch) -> None:
        root = _project(make_project)
        assert _build(module, root, monkeypatch, [*MESSAGE, "", ""]) == 0
        assert _txt(root).read_text(encoding="utf-8") == "\n".join(MESSAGE) + "\n"

    def test_replaced_txt_is_backed_up(self, module, make_project, monkeypatch) -> None:
        root = _project(make_project)
        assert _build(module, root, monkeypatch, MESSAGE) == 0
        assert _build(module, root, monkeypatch, [*MESSAGE[:2], "Reworded prose.", *MESSAGE[3:]]) == 0
        backup = _txt(root).with_name("PR7_merge.txt.bak")
        assert "BrokenProcessPool" in backup.read_text(encoding="utf-8")
        assert "Reworded prose." in _txt(root).read_text(encoding="utf-8")

    def test_empty_stdin_is_a_problem(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)
        monkeypatch.setattr(module, "gh", _gh())
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert _run(module, root, "build", "7") == 1
        assert "no message on stdin" in capsys.readouterr().err
        assert not _txt(root).exists()

    def test_defective_messages_are_refused_and_write_nothing(self, module, make_project, monkeypatch,
                                                              capsys) -> None:
        defects = {
            "wrong subject": (["Merge PR #7 — other", *MESSAGE[1:]], "subject must be exactly"),
            "placeholder prose": ([*MESSAGE[:2], "<Prose: fill me>", *MESSAGE[3:]], "unfilled placeholder"),
            "placeholder bullet": ([*MESSAGE[:5], "  - <file>: <change>", *MESSAGE[6:]],
                                   "unfilled placeholder"),
            "indented prose": ([*MESSAGE[:2], "  indented", *MESSAGE[3:]], "indented text"),
            "fence line": ([*MESSAGE[:2], "```text", *MESSAGE[3:]], "markdown fence"),
            "vendor name": ([*MESSAGE[:2], "Written with Claude.", *MESSAGE[3:]], "vendor name '"),
            "filler": ([*MESSAGE[:2], "A robust fix.", *MESSAGE[3:]], "filler '"),
            "sha": ([*MESSAGE[:2], "Reverts 1a2b3c4d5e6.", *MESSAGE[3:]], "commit SHA '1a2b3c4d5e6'"),
            "sign-off": ([*MESSAGE, "Signed-off-by: x"], "sign-off line"),
            "wide line": ([*MESSAGE[:2], "x" * 111, *MESSAGE[3:]], "wider than 110"),
            "no bullet": ([m for m in MESSAGE if not m.startswith("  - ")], "no '  - file: change' bullet"),
            "no blank line 2": ([MESSAGE[0], *MESSAGE[2:]], "line 2 must be blank"),
            "lineage first": ([*MESSAGE[:2], MESSAGE[-1], *MESSAGE[2:-1]], "must come after the bullets"),
            "no lineage": (MESSAGE[:-1], "exactly one 'Branch lineage:'"),
        }
        root = _project(make_project)
        for name, (message, expected) in defects.items():
            assert _build(module, root, monkeypatch, message) == 1, name
            err = capsys.readouterr().err
            assert expected in err, name
            assert not _txt(root).exists(), name

    def test_the_subject_is_checked_against_the_gh_title(self, module, make_project, monkeypatch,
                                                         capsys) -> None:
        root = _project(make_project)
        assert _build(module, root, monkeypatch, MESSAGE, view={"title": "Renamed since capture"}) == 1
        assert "subject must be exactly 'Merge PR #7 — Renamed since capture'" in capsys.readouterr().err

    def test_a_vendor_name_in_the_title_is_not_flagged(self, module, make_project, monkeypatch) -> None:
        title = "Claude hook fix"
        root = _project(make_project)
        message = [f"Merge PR #7 — {title}", *MESSAGE[1:]]
        assert _build(module, root, monkeypatch, message, view={"title": title}) == 0

    def test_a_failed_build_leaves_the_existing_txt(self, module, make_project, monkeypatch) -> None:
        root = _project(make_project)
        assert _build(module, root, monkeypatch, MESSAGE) == 0
        assert _build(module, root, monkeypatch, [*MESSAGE[:2], "<Prose: fill me>", *MESSAGE[3:]]) == 1
        assert "BrokenProcessPool" in _txt(root).read_text(encoding="utf-8")

    def test_a_closed_pr_is_a_problem(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)
        assert _build(module, root, monkeypatch, MESSAGE, view={"state": "MERGED"}) == 1
        assert "problem: PR #7 is MERGED" in capsys.readouterr().err
        assert not _txt(root).exists()

    def test_gh_failure_is_a_problem(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)

        def failing(repo: Path, *args: str) -> str:
            raise module.MergeMessageError("gh pr view failed: not found")

        monkeypatch.setattr(module, "gh", failing)
        monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(MESSAGE) + "\n"))
        assert _run(module, root, "build", "7") == 1
        assert "problem: gh pr view failed" in capsys.readouterr().err
        assert not _txt(root).exists()

    def test_configured_directory_is_used(self, module, make_project, monkeypatch) -> None:
        root = _project(make_project, config={"artifacts": {"commit_messages": "notes/commits/"}})
        assert _build(module, root, monkeypatch, MESSAGE) == 0
        assert (root / "notes" / "commits" / "PR7_merge.txt").is_file()
        assert not (root / "docs").exists()

    def test_invalid_config_is_a_problem(self, module, make_project, capsys) -> None:
        root = _project(make_project)
        (root / ".claude").mkdir(exist_ok=True)
        (root / ".claude" / "harness.json").write_text("{not json", encoding="utf-8")
        assert _run(module, root, "build", "7") == 1
        assert "problem:" in capsys.readouterr().err
