"""Behavioral tests for the harness merge-commit skill command ``commands/merge_body.py``.

Each test builds a throwaway project with ``make_project``, checks out a feature branch, seeds commit-message
TXT files and runs ``main`` in-process with ``--repo``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Dict, Optional

import pytest

from conftest import git


@pytest.fixture(scope="module")
def module(plugin_root: Path):
    path = plugin_root / "skills" / "merge-commit" / "commands" / "merge_body.py"
    spec = importlib.util.spec_from_file_location("merge_body", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _project(make_project, branch: str, files: Dict[str, str], config: Optional[dict] = None) -> Path:
    """A project on ``branch`` holding ``files`` (committed on main before the branch is cut)."""
    root = make_project(config, files=files)
    git(root, "checkout", "-q", "-b", branch)
    return root


def _run(module, root: Path, *extra: str) -> int:
    return module.main(["--repo", str(root), *extra])


class TestOutput:
    def test_writes_into_default_dir_and_prints_only_the_path(self, module, make_project, capsys) -> None:
        root = _project(make_project, "0042-demo", {"docs/_commit_messages/0042-demo.txt": "Feature(x): y\n"})
        assert _run(module, root) == 0
        out = capsys.readouterr().out
        target = root / "docs" / "_commit_messages" / "merge-body-0042-demo.md"
        assert target.is_file()
        assert out.strip() == target.resolve().as_posix()
        assert "Feature(x): y" not in out

    def test_uses_configured_dir_with_trailing_slash(self, module, make_project) -> None:
        config = {"artifacts": {"commit_messages": "notes/commits/"}}
        root = _project(make_project, "0042-demo", {"notes/commits/0042-demo.txt": "m\n"}, config)
        assert _run(module, root) == 0
        target = root / "notes" / "commits" / "merge-body-0042-demo.md"
        assert "`notes/commits/`" in target.read_text(encoding="utf-8")
        assert not (root / "docs").exists()

    def test_overwrites_existing_output(self, module, make_project) -> None:
        root = _project(make_project, "b1", {"docs/_commit_messages/b1.txt": "new\n",
                                             "docs/_commit_messages/merge-body-b1.md": "stale\n"})
        assert _run(module, root) == 0
        text = (root / "docs" / "_commit_messages" / "merge-body-b1.md").read_text(encoding="utf-8")
        assert "stale" not in text and "new" in text


class TestSelection:
    def test_branch_files_only_sorted_by_name(self, module, make_project) -> None:
        files = {"docs/_commit_messages/b1_pending.txt": "p\n", "docs/_commit_messages/b1.txt": "a\n",
                 "docs/_commit_messages/other.txt": "o\n"}
        root = _project(make_project, "b1", files)
        assert _run(module, root) == 0
        text = (root / "docs" / "_commit_messages" / "merge-body-b1.md").read_text(encoding="utf-8")
        assert "other.txt" not in text
        assert text.index("`b1.txt`") < text.index("`b1_pending.txt`")

    def test_markdown_inputs_are_ignored(self, module, make_project) -> None:
        files = {"docs/_commit_messages/b1.txt": "a\n", "docs/_commit_messages/b1-notes.md": "md\n"}
        root = _project(make_project, "b1", files)
        assert _run(module, root) == 0
        text = (root / "docs" / "_commit_messages" / "merge-body-b1.md").read_text(encoding="utf-8")
        assert "b1-notes.md" not in text

    def test_no_branch_file_is_a_problem_without_all(self, module, make_project, capsys) -> None:
        root = _project(make_project, "b1", {"docs/_commit_messages/other.txt": "o\n"})
        assert _run(module, root) == 1
        assert "problem:" in capsys.readouterr().err
        assert not (root / "docs" / "_commit_messages" / "merge-body-b1.md").exists()

    def test_all_flag_takes_every_txt(self, module, make_project) -> None:
        root = _project(make_project, "b1", {"docs/_commit_messages/other.txt": "o\n"})
        assert _run(module, root, "--all") == 0
        text = (root / "docs" / "_commit_messages" / "merge-body-b1.md").read_text(encoding="utf-8")
        assert "`other.txt`" in text

    def test_slash_branch_is_sanitized_for_match_and_output(self, module, make_project) -> None:
        root = _project(make_project, "feat/x", {"docs/_commit_messages/feat_x.txt": "a\n"})
        assert _run(module, root) == 0
        assert (root / "docs" / "_commit_messages" / "merge-body-feat_x.md").is_file()


class TestBody:
    def test_contents_survive_verbatim_inside_a_longer_fence(self, module, make_project) -> None:
        body = "Docs(x): y\n\n```python\nprint(1)\n```\n"
        root = _project(make_project, "b1", {"docs/_commit_messages/b1.txt": body})
        assert _run(module, root) == 0
        text = (root / "docs" / "_commit_messages" / "merge-body-b1.md").read_text(encoding="utf-8")
        assert "````text\n" + body.rstrip() + "\n````\n" in text

    def test_fence_outgrows_a_four_backtick_run(self, module, make_project) -> None:
        body = "a\n````\nb\n````\n"
        root = _project(make_project, "b1", {"docs/_commit_messages/b1.txt": body})
        assert _run(module, root) == 0
        text = (root / "docs" / "_commit_messages" / "merge-body-b1.md").read_text(encoding="utf-8")
        assert "`````text\n" + body.rstrip() + "\n`````\n" in text

    def test_sections_and_dir_label(self, module, make_project) -> None:
        root = _project(make_project, "b1", {"docs/_commit_messages/b1.txt": "a\n"})
        assert _run(module, root) == 0
        text = (root / "docs" / "_commit_messages" / "merge-body-b1.md").read_text(encoding="utf-8")
        for heading in ("## Merge Summary", "## Source Files", "## Commit Messages", "### `b1.txt`"):
            assert heading in text
        assert "`docs/_commit_messages/`" in text
        assert "- `b1.txt`" in text


class TestProblems:
    def test_missing_dir(self, module, make_project, capsys) -> None:
        root = _project(make_project, "b1", {})
        assert _run(module, root) == 1
        assert "problem: commit-message directory does not exist" in capsys.readouterr().err

    def test_detached_head(self, module, make_project, capsys) -> None:
        root = _project(make_project, "b1", {"docs/_commit_messages/b1.txt": "a\n"})
        git(root, "checkout", "-q", "--detach")
        assert _run(module, root) == 1
        assert "detached HEAD" in capsys.readouterr().err

    def test_repo_must_be_a_git_repo(self, module, tmp_path: Path, capsys,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        plain = tmp_path / "plain"
        (plain / "docs" / "_commit_messages").mkdir(parents=True)
        (plain / "docs" / "_commit_messages" / "x.txt").write_text("a\n", encoding="utf-8")
        assert module.main(["--repo", str(plain)]) == 1
        assert "problem: not a git repository" in capsys.readouterr().err
        assert not list((plain / "docs" / "_commit_messages").glob("*.md"))

    def test_invalid_config(self, module, make_project, capsys) -> None:
        root = _project(make_project, "b1", {"docs/_commit_messages/b1.txt": "a\n"})
        (root / ".claude").mkdir(exist_ok=True)
        (root / ".claude" / "harness.json").write_text("{not json", encoding="utf-8")
        assert _run(module, root) == 1
        assert "problem:" in capsys.readouterr().err
