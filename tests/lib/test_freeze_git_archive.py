"""``harness_lib.freeze_git`` archive plumbing (plan 2021, TASK-1; issue 284).

``archive_tag`` names ``archive/<stem>/r<N>`` and ``archive/<stem>/r<N>-<m>``. ``mktree`` builds a tree of
named subtrees and feeds ``git mktree -z`` bytes, so no entry name gains a ``\\r`` on Windows.
``commit_tree`` writes a commit over a tree with every distinct parent, in order. ``archive_tips`` lists
the commits the archive tags of one stem peel to; ``reaches`` and ``tree_held`` answer whether an archive
keeps a commit or a tree reachable. ``delete_tags`` removes the named local tags only.

Every repository is a throwaway one under ``tmp_path``.
"""
from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any, List, Tuple

import pytest
from conftest import GIT_ENV, git

STEM = "plan/0021-archive"
OTHER = "plan/0022-other"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _freeze_git(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The module under test, with a fixed git identity for the git calls it makes."""
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    import harness_lib.freeze_git as freeze_git
    return freeze_git


def _commit_file(repo: Path, rel: str, text: str) -> str:
    """Write ``rel``, commit everything and return the new HEAD."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"add {rel}")
    return git(repo, "rev-parse", "HEAD")


def _tags(repo: Path) -> List[str]:
    return sorted(line for line in git(repo, "tag", "--list").splitlines() if line)


def test_archive_tag_names(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project(files={"a.txt": "a\n"})
    assert fg.archive_tag(STEM, 1) == "archive/plan/0021-archive/r1"
    assert fg.archive_tag(STEM, 1, 2) == "archive/plan/0021-archive/r1-2"
    for name in (fg.archive_tag(STEM, 1), fg.archive_tag(STEM, 1, 3)):
        git(repo, "check-ref-format", f"refs/tags/{name}")


@pytest.mark.cross_os
def test_mktree_feeds_bytes_and_keeps_names_exact(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project(files={"a.txt": "a\n", "b/c.txt": "c\n"})
    root = git(repo, "rev-parse", "HEAD^{tree}")
    sub = git(repo, "rev-parse", "HEAD:b")
    seen: List[Tuple[List[str], Any]] = []
    real = fg.subprocess.run

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append((list(args[0]), kwargs.get("input")))
        return real(*args, **kwargs)

    monkeypatch.setattr(fg.subprocess, "run", spy)
    built = fg.mktree(repo, {"TASK-2.2": sub, "TASK-1": root})
    feeds = [given for argv, given in seen if "mktree" in argv]
    assert feeds and all(isinstance(given, bytes) for given in feeds), feeds
    assert git(repo, "ls-tree", "--name-only", built).splitlines() == ["TASK-1", "TASK-2.2"]
    assert git(repo, "rev-parse", f"{built}:TASK-1") == root
    assert git(repo, "rev-parse", f"{built}:TASK-2.2") == sub
    assert git(repo, "cat-file", "-t", f"{built}:TASK-1") == "tree"


def test_mktree_of_nothing_is_the_empty_tree(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project(files={"a.txt": "a\n"})
    assert fg.mktree(repo, {}) == EMPTY_TREE


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\0b"])
def test_mktree_refuses_bad_entry_names_before_any_git_call(
        make_project, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project(files={"a.txt": "a\n"})
    root = git(repo, "rev-parse", "HEAD^{tree}")
    calls: List[List[str]] = []
    real = fg.subprocess.run

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(list(args[0]))
        return real(*args, **kwargs)

    monkeypatch.setattr(fg.subprocess, "run", spy)
    with pytest.raises(fg.FreezeGitError):
        fg.mktree(repo, {bad: root})
    assert calls == []


def test_archived_names_keeps_folded_lines_and_skips_previous(
        make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project(files={"a.txt": "a\n"})
    head = git(repo, "rev-parse", "HEAD")
    folded = f"receipt/{STEM}/TASK-1-tree"
    message = (f"Archive of {STEM}\n\nbase/{STEM}/r1 {head}\n{folded} {head}\n"
               f"previous: archive/{STEM}/r1 {head}\n")
    tip = fg.commit_tree(repo, fg.mktree(repo, {}), [], message)
    assert fg.archived_names(repo, [tip]) == {f"base/{STEM}/r1", folded}
    assert fg.archived_names(repo, []) == set()


def test_commit_tree_takes_each_parent_once_in_order(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project(files={"a.txt": "a\n"})
    first = git(repo, "rev-parse", "HEAD")
    second = _commit_file(repo, "b.txt", "b\n")
    tree = fg.mktree(repo, {"r": git(repo, "rev-parse", "HEAD^{tree}")})
    commit = fg.commit_tree(repo, tree, [second, first, second], "Archive of x\n\nfreeze/x/r1.1-tree abc\n")
    assert git(repo, "cat-file", "-t", commit) == "commit"
    assert git(repo, "rev-list", "--parents", "-n", "1", commit).split()[1:] == [second, first]
    assert git(repo, "rev-parse", f"{commit}^{{tree}}") == tree
    assert git(repo, "log", "-1", "--format=%B", commit).startswith("Archive of x")


def test_archive_tips_reaches_and_tree_held(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project(files={"a.txt": "a\n"})
    base = git(repo, "rev-parse", "HEAD")
    tested = _commit_file(repo, "b.txt", "b\n")
    kept = git(repo, "rev-parse", "HEAD^{tree}")
    orphan = git(repo, "commit-tree", kept, "-m", "orphan")
    inner = fg.mktree(repo, {"TASK-1": kept})
    archive = fg.commit_tree(repo, fg.mktree(repo, {"receipts": inner}), [tested], "archive")
    assert fg.archive_tips(repo, STEM) == []
    git(repo, "tag", "-a", "-m", "other", fg.archive_tag(OTHER, 1), orphan)
    git(repo, "tag", "-a", "-m", "first", fg.archive_tag(STEM, 1), archive)
    later = fg.commit_tree(repo, fg.mktree(repo, {}), [archive], "archive again")
    git(repo, "tag", "-a", "-m", "second", fg.archive_tag(STEM, 1, 2), later)
    tips = fg.archive_tips(repo, STEM)
    assert tips == [archive, later]
    assert fg.reaches(repo, tips, base) and fg.reaches(repo, tips, tested)
    assert not fg.reaches(repo, tips, orphan)
    assert not fg.reaches(repo, tips, kept)
    assert fg.tree_held(repo, tips, kept) and fg.tree_held(repo, tips, inner)
    assert not fg.tree_held(repo, tips, fg.mktree(repo, {"elsewhere": kept}))
    assert not fg.tree_held(repo, [], kept) and not fg.reaches(repo, [], base)
    root = git(repo, "rev-parse", f"{archive}^{{tree}}")
    assert not fg.tree_held(repo, tips, root)


def test_archive_tips_orders_rounds_and_m_numerically(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project(files={"a.txt": "a\n"})
    tree = fg.mktree(repo, {})
    made = {}
    for name in ("r10", "r1-10", "r2", "r1-2", "r1"):
        made[name] = fg.commit_tree(repo, tree, [], f"archive {name}\n")
        git(repo, "tag", "-a", "-m", name, f"archive/{STEM}/{name}", made[name])
    expected = [made[name] for name in ("r1", "r1-2", "r1-10", "r2", "r10")]
    assert fg.archive_tips(repo, STEM) == expected


def test_delete_tags_removes_only_the_named(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project(files={"a.txt": "a\n"})
    for name in ("base/plan/0021-archive/r1", "receipt/plan/0021-archive/TASK-1-tree", "keep"):
        git(repo, "tag", "-a", "-m", name, name, "HEAD")
    fg.delete_tags(repo, [])
    fg.delete_tags(repo, ["missing/plan/0021-archive/gone"])
    fg.delete_tags(repo, ["base/plan/0021-archive/r1", "missing/plan/0021-archive/gone",
                          "receipt/plan/0021-archive/TASK-1-tree"])
    assert _tags(repo) == ["keep"]
