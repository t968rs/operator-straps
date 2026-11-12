"""``harness_lib.freeze_git`` (plan 1015, GIT-1): scoped git trees, freeze tag names, tagging and reconcile.

``members`` splits a path set into not-gitignored and gitignored files. ``build_tree`` hashes the
not-ignored set with working-tree content under a temporary index, so a new untracked file is in the tree
and the real index never moves; an empty set is refused. The tag-name builders produce names git accepts,
none a directory prefix of another. ``preflight`` and ``ensure_tag`` refuse a name on another object.
``reconcile`` tags the commit that added an entry file, adds a ``.N`` tag when a rewrite left no tagged
commit on HEAD's history, and never tags a history entry. ``patch_id_match`` finds a rewritten base.

Every repository is a throwaway one under ``tmp_path``.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Tuple

import pytest
from conftest import GIT_ENV, git

PLAN_STEM = "plan/0015-freeze-tags"
SKILL_STEM = "skill/write-plan"
FREEZES = f"docs/plans/freezes/{PLAN_STEM}"
ENTRY_1 = f"{FREEZES}/r1.1-freeze.json"
ENTRY_2 = f"{FREEZES}/r1.2-freeze.json"
ENTRY_3 = f"{FREEZES}/r1.3-lock.json"
STEM_1 = f"freeze/{PLAN_STEM}/r1.1"
STEM_2 = f"freeze/{PLAN_STEM}/r1.2"
STEM_3 = f"lock/{PLAN_STEM}/r1.3"

PLAN_JSON = "docs/plans/0015_freeze_tags_ActionPlan.json"
TRACKED_TEST = "docs/plans/0015/tests/test_a.txt"
NEW_TEST = "docs/plans/0015/tests/new.txt"
IGNORED_TEST = "docs/plans/0015/tests/ignored.log"
MISSING_TEST = "docs/plans/0015/tests/missing.txt"


def _freeze_git(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The module under test, with a fixed git identity for the git calls it makes."""
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    import harness_lib.freeze_git as freeze_git
    return freeze_git


def _commit_all(repo: Path, message: str) -> str:
    """Stage everything, commit and return the new HEAD."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def _peel(repo: Path, name: str) -> str:
    """The object a tag peels to."""
    return git(repo, "rev-parse", f"refs/tags/{name}^{{}}")


def _tags(repo: Path) -> List[str]:
    """Every tag name in ``repo``, sorted."""
    return sorted(line for line in git(repo, "tag", "--list").splitlines() if line)


def _write(repo: Path, rel: str, text: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _entry_text(kind: str, seq: int) -> str:
    """A minimal ledger entry body; reconcile reads only where the file was added."""
    return f'{{"kind": "{kind}", "round": 1, "seq": {seq}}}\n'


def _scoped_repo(make_project) -> Tuple[Path, List[str]]:
    """A repo with a modified tracked plan JSON, a tracked test, a new untracked test, a gitignored
    test written with CRLF and a path that does not exist; returns the repo and the path set."""
    repo = make_project(files={
        ".gitignore": "*.log\n",
        PLAN_JSON: '{"v": 1}\n',
        TRACKED_TEST: "committed\n",
    })
    _write(repo, PLAN_JSON, '{"v": 2}\n')
    _write(repo, NEW_TEST, "new, never added\n")
    (repo / IGNORED_TEST).write_bytes(b"ignored\r\nline two\r\n")
    return repo, [PLAN_JSON, TRACKED_TEST, NEW_TEST, IGNORED_TEST, MISSING_TEST]


def test_build_tree_holds_not_ignored_paths(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo, paths = _scoped_repo(make_project)
    expected = sorted([PLAN_JSON, TRACKED_TEST, NEW_TEST])
    not_ignored, ignored = fg.members(repo, paths)
    assert sorted(not_ignored) == expected
    assert list(ignored) == [IGNORED_TEST]
    status_before = git(repo, "status", "--porcelain")
    stage_before = git(repo, "ls-files", "--stage")
    tree, blobs = fg.build_tree(repo, paths)
    assert len(tree) == 40 and all(c in "0123456789abcdef" for c in tree)
    assert git(repo, "cat-file", "-t", tree) == "tree"
    assert git(repo, "ls-tree", "-r", "--name-only", tree).splitlines() == expected
    assert git(repo, "show", f"{tree}:{PLAN_JSON}") == '{"v": 2}'
    assert git(repo, "show", f"{tree}:{NEW_TEST}") == "new, never added"
    assert sorted(blobs) == expected
    for rel in expected:
        assert blobs[rel] == git(repo, "rev-parse", f"{tree}:{rel}") == git(repo, "hash-object", rel), rel
    assert git(repo, "ls-files", "--stage") == stage_before
    assert git(repo, "diff", "--cached", "--name-only") == ""
    assert git(repo, "status", "--porcelain") == status_before
    lf_digest = hashlib.sha256(b"ignored\nline two\n").hexdigest()
    assert fg.ignored_digests(repo, [IGNORED_TEST]) == {IGNORED_TEST: lf_digest}


def test_build_tree_refuses_empty_set(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project(files={".gitignore": "*.log\n*.pyc\n"})
    _write(repo, "docs/plans/0015/tests/a.log", "a\n")
    _write(repo, "docs/plans/0015/tests/b.pyc", "b\n")
    paths = ["docs/plans/0015/tests/a.log", "docs/plans/0015/tests/b.pyc"]
    not_ignored, ignored = fg.members(repo, paths)
    assert list(not_ignored) == [] and sorted(ignored) == paths
    stage_before = git(repo, "ls-files", "--stage")
    with pytest.raises(fg.FreezeGitError):
        fg.build_tree(repo, paths)
    assert git(repo, "ls-files", "--stage") == stage_before


def test_tag_names_pass_check_ref_format(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    base = fg.base_tag(PLAN_STEM, 1)
    relinked = fg.base_tag(PLAN_STEM, 1, m=2)
    tree = fg.entry_tag("freeze", PLAN_STEM, 1, 2, "tree")
    commit = fg.entry_tag("freeze", PLAN_STEM, 1, 2, "commit")
    lock_tree = fg.entry_tag("lock", PLAN_STEM, 1, 3, "tree")
    skill_tree = fg.entry_tag("freeze", SKILL_STEM, 3, 2, "tree")
    assert base == "base/plan/0015-freeze-tags/r1"
    assert relinked == "base/plan/0015-freeze-tags/r1-2"
    assert tree == "freeze/plan/0015-freeze-tags/r1.2-tree"
    assert commit == "freeze/plan/0015-freeze-tags/r1.2-commit"
    assert lock_tree == "lock/plan/0015-freeze-tags/r1.3-tree"
    assert skill_tree == "freeze/skill/write-plan/r3.2-tree"
    entry_stem = f"freeze/{PLAN_STEM}/r1.2"
    assert fg.commit_tag(entry_stem, 1) == commit
    assert fg.commit_tag(entry_stem, 2) == "freeze/plan/0015-freeze-tags/r1.2-commit.2"
    names = [base, relinked, tree, commit, lock_tree, skill_tree,
             fg.commit_tag(entry_stem, 2), fg.commit_tag(entry_stem, 3)]
    repo = make_project()
    for name in names:
        assert git(repo, "check-ref-format", f"refs/tags/{name}") == "", name
        assert not [other for other in names if other.startswith(name + "/")], name
    for name in names:
        git(repo, "tag", "-a", "-m", "names", name, "HEAD")
    assert _tags(repo) == sorted(names)
    assert sorted(set(fg.tag_seqs(repo, PLAN_STEM, 1))) == [2, 3]
    assert sorted(set(fg.tag_seqs(repo, SKILL_STEM, 3))) == [2]
    assert sorted(set(fg.tag_seqs(repo, SKILL_STEM, 1))) == []


def test_preflight_and_ensure_tag_refuse_other_target(make_project,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project(files={PLAN_JSON: "{}\n"})
    head = git(repo, "rev-parse", "HEAD")
    name = f"{STEM_1}-commit"
    message = "plan/0015-freeze-tags r1.1 freeze"
    assert list(fg.preflight(repo, {name: head})) == []
    assert fg.ensure_tag(repo, name, head, message) == name
    assert git(repo, "cat-file", "-t", f"refs/tags/{name}") == "tag"
    assert _peel(repo, name) == head
    assert list(fg.preflight(repo, {name: head})) == []
    assert fg.ensure_tag(repo, name, head, message) is None
    _write(repo, "README.md", "moved on\n")
    other = _commit_all(repo, "second")
    problems = list(fg.preflight(repo, {name: other}))
    assert len(problems) == 1
    assert name in problems[0] and head[:7] in problems[0] and other[:7] in problems[0]
    with pytest.raises(fg.FreezeGitError):
        fg.ensure_tag(repo, name, other, message)
    assert _peel(repo, name) == head
    tree, _ = fg.build_tree(repo, [PLAN_JSON])
    tree_name = f"{STEM_1}-tree"
    assert fg.ensure_tag(repo, tree_name, tree, message) == tree_name
    assert git(repo, "cat-file", "-t", f"refs/tags/{tree_name}") == "tag"
    assert _peel(repo, tree_name) == tree
    assert fg.ensure_tag(repo, tree_name, tree, message) is None
    mixed = list(fg.preflight(repo, {name: head, tree_name: other}))
    assert len(mixed) == 1 and tree_name in mixed[0]


def test_reconcile_tags_the_commit_adding_the_entry_file(make_project,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project()
    _write(repo, ENTRY_1, _entry_text("freeze", 1))
    first = _commit_all(repo, "freeze r1.1")
    _write(repo, "README.md", "unrelated\n")
    _commit_all(repo, "unrelated")
    _write(repo, ENTRY_1, _entry_text("freeze", 1) + "\n")
    _commit_all(repo, "touch r1.1 after it was added")
    _write(repo, ENTRY_2, _entry_text("freeze", 2))
    second = _commit_all(repo, "freeze r1.2")
    _write(repo, ENTRY_3, _entry_text("lock", 3))
    entries = [(STEM_1, ENTRY_1, False), (STEM_2, ENTRY_2, False), (STEM_3, ENTRY_3, False)]
    created, warns = fg.reconcile(repo, entries)
    assert sorted(created) == [f"{STEM_1}-commit", f"{STEM_2}-commit"]
    assert list(warns) == []
    assert _peel(repo, f"{STEM_1}-commit") == first
    assert _peel(repo, f"{STEM_2}-commit") == second
    assert git(repo, "cat-file", "-t", f"refs/tags/{STEM_1}-commit") == "tag"
    tags_after_first = _tags(repo)
    assert tags_after_first == sorted(created)
    again, again_warns = fg.reconcile(repo, entries)
    assert list(again) == [] and list(again_warns) == []
    assert _tags(repo) == tags_after_first


def test_reconcile_adds_second_tag_after_rewrite(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project()
    parent = git(repo, "rev-parse", "HEAD")
    _write(repo, ENTRY_1, _entry_text("freeze", 1))
    original = _commit_all(repo, "freeze r1.1")
    entries = [(STEM_1, ENTRY_1, False)]
    created, _ = fg.reconcile(repo, entries)
    assert list(created) == [f"{STEM_1}-commit"]
    git(repo, "checkout", "-q", "-b", "rewritten", parent)
    _write(repo, ENTRY_1, _entry_text("freeze", 1))
    rewritten = _commit_all(repo, "freeze r1.1, rewritten")
    assert rewritten != original
    created, warns = fg.reconcile(repo, entries)
    assert list(created) == [f"{STEM_1}-commit.2"] and list(warns) == []
    assert _peel(repo, f"{STEM_1}-commit.2") == rewritten
    assert _peel(repo, f"{STEM_1}-commit") == original
    expected: Dict[str, str] = {f"{STEM_1}-commit": original, f"{STEM_1}-commit.2": rewritten}
    assert {name: _peel(repo, name) for name in _tags(repo)} == expected
    assert list(fg.reconcile(repo, entries)[0]) == []
    git(repo, "checkout", "-q", "main")
    assert list(fg.reconcile(repo, entries)[0]) == []
    assert _tags(repo) == sorted(expected)


def test_reconcile_skips_history_entries(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project()
    _write(repo, ENTRY_1, _entry_text("freeze", 1))
    _commit_all(repo, "migrated history entry r1.1")
    _write(repo, ENTRY_2, _entry_text("freeze", 2))
    second = _commit_all(repo, "freeze r1.2")
    entries = [(STEM_1, ENTRY_1, True), (STEM_2, ENTRY_2, False)]
    created, warns = fg.reconcile(repo, entries)
    assert list(created) == [f"{STEM_2}-commit"] and list(warns) == []
    assert _tags(repo) == [f"{STEM_2}-commit"]
    assert _peel(repo, f"{STEM_2}-commit") == second
    history_only, _ = fg.reconcile(repo, [(STEM_1, ENTRY_1, True)])
    assert list(history_only) == []
    assert _tags(repo) == [f"{STEM_2}-commit"]


def test_patch_id_match_finds_rewritten_base(make_project, monkeypatch: pytest.MonkeyPatch) -> None:
    fg = _freeze_git(monkeypatch)
    repo = make_project()
    root = git(repo, "rev-parse", "HEAD")
    _write(repo, "src/base.txt", "the base change\n")
    old_base = _commit_all(repo, "base change")
    _write(repo, "src/later.txt", "dropped by the rewrite\n")
    dropped = _commit_all(repo, "later change")
    git(repo, "checkout", "-q", "-b", "rewritten", root)
    _write(repo, "src/upstream.txt", "landed upstream first\n")
    _commit_all(repo, "upstream change")
    git(repo, "cherry-pick", old_base)
    new_base = git(repo, "rev-parse", "HEAD")
    _write(repo, "src/after.txt", "work after the base\n")
    _commit_all(repo, "after the base")
    assert new_base != old_base
    assert fg.patch_id_match(repo, old_base) == new_base
    assert fg.patch_id_match(repo, dropped) is None
