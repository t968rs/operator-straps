"""``harness_lib.plan_lock.tagger`` supplies an author identity when git has none (plan 1021).

``git commit-tree`` (the archive commit) needs an author as well as a committer, so with no identity in
the environment or in any config, ``tagger`` sets ``FALLBACK_TAGGER`` and ``FALLBACK_AUTHOR`` for its block
and restores the environment afterwards. A configured identity is left alone.

Every repository is a throwaway one under ``tmp_path``, with an isolated global config.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import git

from harness_lib import freeze_git as fg
from harness_lib import plan_lock as pk

IDENTITY = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL")


def _no_identity(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every identity source: the variables, the global and system config, the guessed default."""
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    git(repo, "config", "user.useConfigOnly", "true")
    for key in IDENTITY:
        monkeypatch.delenv(key, raising=False)


def test_tagger_supplies_the_author_for_commit_tree(make_project, tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_project(files={"a.txt": "a\n"})
    head = git(repo, "rev-parse", "HEAD")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    _no_identity(repo, tmp_path, monkeypatch)
    assert pk.git(repo, "var", "GIT_AUTHOR_IDENT").returncode != 0
    with pk.tagger(repo):
        assert {key: os.environ.get(key) for key in pk.FALLBACK_AUTHOR} == pk.FALLBACK_AUTHOR
        commit = fg.commit_tree(repo, tree, [head], "archive")
    assert all(key not in os.environ for key in IDENTITY)
    assert git(repo, "log", "-1", "--format=%an <%ae>", commit) == "plan <plan@localhost>"
    assert git(repo, "log", "-1", "--format=%cn <%ce>", commit) == "plan <plan@localhost>"


def test_tagger_leaves_a_configured_identity_alone(make_project, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_project(files={"a.txt": "a\n"})
    _no_identity(repo, tmp_path, monkeypatch)
    git(repo, "config", "user.name", "dev")
    git(repo, "config", "user.email", "dev@example.com")
    with pk.tagger(repo):
        assert all(key not in os.environ for key in IDENTITY)
        commit = fg.commit_tree(repo, git(repo, "rev-parse", "HEAD^{tree}"), [], "archive")
    assert git(repo, "log", "-1", "--format=%an <%ae>", commit) == "dev <dev@example.com>"
