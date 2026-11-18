"""The repository README describes TODO sync with stable ids: no structural edit renumbers items, and the
one-time ``migrate-ids`` switch is documented with its dry run, its map and the history it leaves alone."""
from __future__ import annotations

import re
from typing import List

from conftest import REPO_ROOT

README = REPO_ROOT / "README.md"
#: Names that mark a README paragraph as TODO sync text.
_TODO_MARKERS = ("todo_sync.py", "todo-edit", "add-todo", "sync-gh-todo", "RepoToDo")


def _paragraphs() -> List[str]:
    return [p for p in re.split(r"\n\s*\n", README.read_text(encoding="utf-8")) if p.strip()]


def _todo_paragraphs() -> List[str]:
    """README paragraphs that name a TODO sync script, skill or catalog."""
    return [p for p in _paragraphs() if any(marker in p for marker in _TODO_MARKERS)]


def test_readme_todo_text_never_renumbers() -> None:
    paragraphs = _todo_paragraphs()
    assert paragraphs, "no README paragraph names the TODO sync tooling"
    hits = [p.strip()[:80] for p in paragraphs if re.search(r"[Rr]enumber", p)]
    assert hits == []


def test_readme_documents_migrate_ids() -> None:
    found = [p for p in _paragraphs() if "todo_sync.py migrate-ids" in p]
    assert len(found) == 1, f"{len(found)} README paragraphs name todo_sync.py migrate-ids"
    phrases = ("--dry-run", "legacy_ids", "--exclude", "history", "RepoToDo.schema.json", "every install")
    for phrase in phrases:
        assert phrase in found[0], phrase
    assert any("retired_ids" in p for p in _paragraphs() if "todo_sync.py retire" in p)


def test_readme_has_no_rank_number_examples() -> None:
    text = README.read_text(encoding="utf-8")
    assert not re.search(r"--(retire|split) +0*\d+\b(?!-)", text), "examples name stable todo-xxxx ids"
    assert re.search(r"--retire todo-[2-9a-hjkmnp-z]{4}\b", text)
