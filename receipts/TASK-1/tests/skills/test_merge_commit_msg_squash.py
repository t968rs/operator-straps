"""Squash mode of ``merge_commit_msg.py``: ``--squash``, ``-s`` or a bare ``squash`` after the PR number.

A squash-merge lands one ordinary commit on the base branch, so its subject is GitHub's squash form
``<title> (#N)`` and the title must parse as a Conventional-Commit subject. Capture states the mode as a fact
in both modes; without a mode token it prints what it printed before the mode existed plus ``- Mode: merge``
(``GOLDEN``, taken from the driver at the plan's base), and build accepts either exact subject, so a saved
squash TXT rebuilds without the flag.

``gh`` is the one seam, swapped for a canned PR as in ``test_merge_commit_msg.py``.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from typing import List, Optional

import pytest

from conftest import git

WALK_ROOTS = ()  # walks only the commit-message folder of a make_project repo
TITLE = "Fix(workers): pool crash on spawn"
LEGACY_TITLE = "[BUG] Worker pool crash on spawn"
SQUASH = f"{TITLE} (#7)"
MERGE = f"Merge PR #7 -- {TITLE}"
FORMS = (["--squash"], ["-s"], ["squash"])
BODY = [
    "",
    "Fixes a BrokenProcessPool failure in the export pool.",
    "",
    "  - workers/export.py: add a stdio guard at worker entry",
    "  - tests/test_export.py: cover the spawn path",
    "",
    "Branch lineage: `dev` -> `7-fix-workers`",
]
GOLDEN = "\n".join([
    "# PR #7 merge message",
    "",
    "Facts and the diff are script-owned. Fill the placeholders of the skeleton under Message from them, "
    "keep its subject, lineage and review lines, and pass the message to `build` on stdin.",
    "",
    "## Facts",
    "",
    f"- Title: {TITLE}",
    "- Mode: merge",
    "- Branch: `7-fix-workers` into `dev`",
    "- Size: +40 -3 across 2 files",
    "- Canned message: none",
    "",
    "## Changed files",
    "",
    "- workers/export.py",
    "- tests/test_export.py",
    "",
    "## Diff",
    "",
    *[line for name in ("workers/export.py", "tests/test_export.py") for line in (
        f"diff --git a/{name} b/{name}", f"--- a/{name}", f"+++ b/{name}",
        "@@ -1 +1 @@", "-old", "+guard = True")],
    "",
    "## Commits",
    "",
    "- Fix(workers): guard stdio",
    "- Test(workers): spawn path",
    "",
    "## Branch commit subjects",
    "",
    "- none",
    "",
    "## Message",
    "",
    "```text",
    MERGE,
    "",
    "<Prose: what changed and why, 2-3 short paragraphs; lead with the action.>",
    "",
    "  - <file>: <key change; 4-7 representative files>",
    "",
    "Branch lineage: `dev` -> `7-fix-workers`",
    "```",
    "",
])


@pytest.fixture(scope="module")
def module(plugin_root: Path):
    path = plugin_root / "skills" / "merge-commit-msg" / "commands" / "merge_commit_msg.py"
    spec = importlib.util.spec_from_file_location("merge_commit_msg_squash", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gh(title: str = TITLE):
    shape = {"number": 7, "title": title, "headRefName": "7-fix-workers", "baseRefName": "dev",
             "additions": 40, "deletions": 3, "changedFiles": 2, "body": "", "state": "OPEN"}
    names = ["workers/export.py", "tests/test_export.py"]
    head = "diff --git a/{n} b/{n}\n--- a/{n}\n+++ b/{n}\n@@ -1 +1 @@\n-old\n"
    patch = "".join(head.format(n=n) + "+guard = True\n" for n in names)

    def fake(repo: Path, *args: str) -> str:
        if args[:2] == ("pr", "view"):
            return json.dumps(shape)
        if args[:2] == ("pr", "diff"):
            return "\n".join(names) + "\n" if "--name-only" in args else patch
        if args[0] == "api":
            return "Fix(workers): guard stdio\nTest(workers): spawn path\n"
        raise AssertionError(f"unexpected gh call: {args}")

    return fake


def _project(make_project) -> Path:
    root = make_project(None, files={})
    git(root, "checkout", "-q", "-b", "7-fix-workers")
    return root


def _run(module, root: Path, *argv: str) -> int:
    """The exit code of ``main``; an argparse refusal (``SystemExit``) counts as its code."""
    try:
        return module.main(["--repo", str(root), *argv])
    except SystemExit as exc:
        return int(exc.code or 0)


def _capture(module, root: Path, monkeypatch, capsys, *mode: str, title: str = TITLE):
    monkeypatch.setattr(module, "gh", _gh(title))
    code = _run(module, root, "capture", "7", *mode)
    return code, capsys.readouterr()


def _build(module, root: Path, monkeypatch, capsys, subject: str, *mode: str, title: str = TITLE):
    monkeypatch.setattr(module, "gh", _gh(title))
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join([subject, *BODY]) + "\n"))
    code = _run(module, root, "build", "7", *mode)
    return code, capsys.readouterr()


def _fence(text: str) -> List[str]:
    lines = text.splitlines()
    start = lines.index("```text")
    return lines[start + 1:lines.index("```", start + 1)]


def _txt(root: Path) -> Optional[str]:
    path = root / "docs" / "_commit_messages" / "PR7_merge.txt"
    return path.read_text(encoding="utf-8") if path.is_file() else None


class TestSquashCapture:
    def test_squash_subject_line(self, module) -> None:
        assert module.subject_line(7, TITLE, squash=True) == SQUASH
        assert module.subject_line(7, TITLE) == MERGE

    def test_three_forms_capture_identically(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)
        outs = []
        for form in FORMS:
            code, captured = _capture(module, root, monkeypatch, capsys, *form)
            assert code == 0, (form, captured.err)
            outs.append(captured.out)
        assert outs[0] == outs[1] == outs[2]
        assert _fence(outs[0])[0] == SQUASH

    def test_squash_capture_states_the_mode(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)
        code, captured = _capture(module, root, monkeypatch, capsys, "--squash")
        assert code == 0, captured.err
        assert captured.out.splitlines()[0] == "# PR #7 squash message"
        assert "- Mode: squash" in captured.out
        assert "pass the message to `build --squash` on stdin" in captured.out

    def test_unknown_mode_token_is_a_problem(self, module, make_project, monkeypatch, capsys) -> None:
        root = _project(make_project)
        code, captured = _capture(module, root, monkeypatch, capsys, "rebase")
        assert code == 1
        assert "problem:" in captured.err and "'rebase'" in captured.err and not captured.out

    def test_squash_capture_refuses_a_non_conventional_title(self, module, make_project, monkeypatch,
                                                             capsys) -> None:
        root = _project(make_project)
        code, captured = _capture(module, root, monkeypatch, capsys, "-s", title=LEGACY_TITLE)
        assert code == 1
        assert "problem:" in captured.err and "Conventional-Commit" in captured.err and not captured.out

    def test_squash_capture_refuses_a_title_without_a_summary(self, module, make_project, monkeypatch,
                                                              capsys) -> None:
        root = _project(make_project)
        code, captured = _capture(module, root, monkeypatch, capsys, "-s", title="Fix(workers):")
        assert code == 1
        assert "problem:" in captured.err and "Conventional-Commit" in captured.err and not captured.out

    def test_default_capture_adds_only_the_merge_mode_line(self, module, make_project, monkeypatch,
                                                           capsys) -> None:
        root = _project(make_project)
        code, captured = _capture(module, root, monkeypatch, capsys)
        assert code == 0, captured.err
        assert captured.out == GOLDEN


class TestSquashBuild:
    def test_squash_build_writes_the_squash_subject(self, module, make_project, monkeypatch, capsys) -> None:
        for form in FORMS:
            root = _project(make_project)
            code, captured = _build(module, root, monkeypatch, capsys, SQUASH, *form)
            assert code == 0, (form, captured.err)
            assert _txt(root) == "\n".join([SQUASH, *BODY]) + "\n"
            out = captured.out.splitlines()
            assert out[0] == "Saved: docs/_commit_messages/PR7_merge.txt - squash message for PR #7"
            assert out[1] == f"Subject: {SQUASH}"

    def test_build_without_a_flag_accepts_either_exact_subject(self, module, make_project, monkeypatch,
                                                               capsys) -> None:
        for subject, kind in ((SQUASH, "squash"), (MERGE, "merge")):
            root = _project(make_project)
            code, captured = _build(module, root, monkeypatch, capsys, subject)
            assert code == 0, (subject, captured.err)
            assert f"- {kind} message for PR #7" in captured.out.splitlines()[0]

    def test_squash_build_rejects_a_paraphrased_subject(self, module, make_project, monkeypatch,
                                                        capsys) -> None:
        root = _project(make_project)
        code, captured = _build(module, root, monkeypatch, capsys, "Fix(workers): crash on spawn (#7)",
                                "--squash")
        assert code == 1 and _txt(root) is None
        assert f"subject must be exactly {SQUASH!r}" in captured.err

    def test_squash_build_names_the_flag_on_a_merge_subject(self, module, make_project, monkeypatch,
                                                            capsys) -> None:
        root = _project(make_project)
        code, captured = _build(module, root, monkeypatch, capsys, MERGE, "--squash")
        assert code == 1 and _txt(root) is None
        assert "subject is the merge form" in captured.err and repr(SQUASH) in captured.err

    def test_squash_build_refuses_a_merge_subject_before_the_title_check(self, module, make_project,
                                                                         monkeypatch, capsys) -> None:
        root = _project(make_project)
        code, captured = _build(module, root, monkeypatch, capsys, f"Merge PR #7 -- {LEGACY_TITLE}",
                                "--squash", title=LEGACY_TITLE)
        assert code == 1 and _txt(root) is None
        assert "subject is the merge form" in captured.err
        assert "Conventional-Commit" not in captured.err

    def test_squash_subject_without_a_flag_still_needs_a_conventional_title(self, module, make_project,
                                                                            monkeypatch, capsys) -> None:
        root = _project(make_project)
        code, captured = _build(module, root, monkeypatch, capsys, f"{LEGACY_TITLE} (#7)",
                                title=LEGACY_TITLE)
        assert code == 1 and _txt(root) is None
        assert "Conventional-Commit" in captured.err

    def test_unknown_mode_token_is_a_problem_in_build(self, module, make_project, monkeypatch,
                                                      capsys) -> None:
        root = _project(make_project)
        code, captured = _build(module, root, monkeypatch, capsys, SQUASH, "fast")
        assert code == 1 and _txt(root) is None
        assert "problem:" in captured.err and "'fast'" in captured.err
