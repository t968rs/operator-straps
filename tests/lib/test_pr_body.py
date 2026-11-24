"""Behavioral tests for harness_lib.pr_body: the marked pr-sum block in a PR description, and its gh calls.

``merge_block`` is pure and is checked against hand-written bodies. ``publish`` runs ``gh`` through
``subprocess.run``; the tests replace that one call with a fake that answers ``gh pr view`` from a stored
body and records each ``gh pr edit`` with its stdin, so the read, the merge and the write are real.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Sequence

import pytest

from harness_lib import pr_body
from harness_lib.pr_body import BodyError, merge_block, publish

START = "<!-- pr-sum:start -->"
END = "<!-- pr-sum:end -->"


class TestMergeBlock:
    def test_empty_body_becomes_the_block(self) -> None:
        assert merge_block("", "# PR #7: x\n") == (f"{START}\n# PR #7: x\n{END}", False)

    def test_block_is_appended_after_text_written_by_hand(self) -> None:
        assert merge_block("Hand text.\n", "S") == (f"Hand text.\n\n{START}\nS\n{END}", False)

    def test_block_between_markers_is_replaced_and_the_rest_kept(self) -> None:
        body = f"Intro\n\n{START}\nold summary\n{END}\n\nOutro"
        assert merge_block(body, "new summary") == (f"Intro\n\n{START}\nnew summary\n{END}\n\nOutro", True)

    def test_crlf_body_keeps_its_text_outside_the_block(self) -> None:
        body = f"Intro\r\n\r\n{START}\r\nold\r\n{END}\r\nOutro"
        assert merge_block(body, "new") == (f"Intro\r\n\r\n{START}\nnew\n{END}\r\nOutro", True)

    @pytest.mark.parametrize("body", [
        f"{START}\nold",
        f"old\n{END}",
        f"{END}\nold\n{START}",
        f"{START}\na\n{END}\n{START}\nb\n{END}",
    ])
    def test_unpaired_markers_are_refused(self, body: str) -> None:
        with pytest.raises(BodyError, match="pr-sum markers"):
            merge_block(body, "S")

    def test_a_body_over_the_github_limit_is_refused(self) -> None:
        with pytest.raises(BodyError, match="65536"):
            merge_block("", "x" * 65_536)


class _Gh:
    """Fake ``subprocess.run`` for gh: ``pr view`` returns ``body`` as JSON, ``pr edit`` stores its stdin."""

    def __init__(self, body: str, fail: Optional[str] = None) -> None:
        self.body, self.fail = body, fail
        self.calls: List[List[str]] = []
        self.edits: List[str] = []

    def __call__(self, argv: Sequence[str], **kwargs: object) -> object:
        self.calls.append(list(argv))
        verb = argv[2]
        if verb == self.fail:
            return _Done(1, "", "HTTP 403: forbidden")
        if verb == "view":
            return _Done(0, json.dumps({"body": self.body}), "")
        self.edits.append(str(kwargs["input"]))
        return _Done(0, "", "")


class _Done:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class TestPublish:
    def _install(self, monkeypatch: pytest.MonkeyPatch, gh: _Gh) -> _Gh:
        monkeypatch.setattr(pr_body.subprocess, "run", gh)
        return gh

    def test_adds_the_block_with_one_read_and_one_edit(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        gh = self._install(monkeypatch, _Gh("Hand text."))
        assert publish(7, tmp_path, "S\n") == "Published to PR #7 description: block added"
        assert gh.calls == [
            ["gh", "pr", "view", "7", "--json", "body"],
            ["gh", "pr", "edit", "7", "--body-file", "-"],
        ]
        assert gh.edits == [f"Hand text.\n\n{START}\nS\n{END}"]

    def test_replaces_an_earlier_block(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        gh = self._install(monkeypatch, _Gh(f"{START}\nold\n{END}"))
        assert publish(7, tmp_path, "new") == "Published to PR #7 description: block replaced"
        assert gh.edits == [f"{START}\nnew\n{END}"]

    def test_an_unchanged_block_is_not_written(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        gh = self._install(monkeypatch, _Gh(f"Intro\n\n{START}\nS\n{END}"))
        assert publish(7, tmp_path, "S") == "PR #7 description already holds this summary"
        assert gh.edits == []

    @pytest.mark.parametrize("verb", ["view", "edit"])
    def test_a_gh_failure_is_a_body_error(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, verb: str,
    ) -> None:
        self._install(monkeypatch, _Gh("", fail=verb))
        with pytest.raises(BodyError, match=f"gh pr {verb} 7 failed: HTTP 403"):
            publish(7, tmp_path, "S")

    def test_missing_gh_is_a_body_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        def missing(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError("gh")

        monkeypatch.setattr(pr_body.subprocess, "run", missing)
        with pytest.raises(BodyError, match="gh is not installed"):
            publish(7, tmp_path, "S")

    def test_unparseable_view_output_is_a_body_error(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(pr_body.subprocess, "run", lambda *_a, **_k: _Done(0, "not json", ""))
        with pytest.raises(BodyError, match="gh pr view 7 output does not parse"):
            publish(7, tmp_path, "S")
