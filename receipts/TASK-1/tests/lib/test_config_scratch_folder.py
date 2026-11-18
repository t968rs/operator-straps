"""Contract tests for the ``scratch_folder`` config key and the TODO inbox under it: default, typed load,
the README row, and the inbox folder in the history paths and the seeded exclusions."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness_lib.config import ConfigError, load_config
from harness_lib.default_exclusions import default_patterns
from harness_lib.history import history_paths

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_scratch_folder_defaults_to_docs_scratch(make_project) -> None:
    cfg = load_config(make_project())
    assert cfg.scratch_folder == "docs/_scratch/"
    assert cfg.todo_inbox() == "docs/_scratch/todo-inbox"


def test_scratch_folder_loads_an_override(make_project) -> None:
    cfg = load_config(make_project({"scratch_folder": "tmp/agents"}))
    assert cfg.scratch_folder == "tmp/agents"
    assert cfg.todo_inbox() == "tmp/agents/todo-inbox"
    hash(cfg)


def test_the_inbox_folder_normalizes_slashes_like_the_mod(make_project) -> None:
    cfg = load_config(make_project({"scratch_folder": "tmp\\scratch\\"}))
    assert cfg.todo_inbox() == "tmp/scratch/todo-inbox"


@pytest.mark.parametrize("value", ["..", "../shared/", "docs/../../x", "..\\outside"])
def test_a_scratch_folder_above_the_root_is_refused(make_project, value: str) -> None:
    with pytest.raises(ConfigError, match="scratch_folder"):
        load_config(make_project({"scratch_folder": value}))


def test_a_scratch_folder_that_folds_inside_the_root_loads(make_project) -> None:
    cfg = load_config(make_project({"scratch_folder": "tmp/../agents/"}))
    assert cfg.scratch_folder == "tmp/../agents/"


def test_scratch_folder_is_independent_of_the_pr_review_scratch(make_project) -> None:
    cfg = load_config(make_project({"scratch_folder": "tmp/agents"}))
    assert cfg.artifacts.scratch == "docs/_scratch/pr_review"


def test_a_non_string_scratch_folder_is_refused(make_project) -> None:
    with pytest.raises(ConfigError, match="scratch_folder"):
        load_config(make_project({"scratch_folder": 3}))


def test_the_inbox_is_a_history_path(make_project) -> None:
    assert "docs/_scratch/todo-inbox" in history_paths(load_config(make_project()))


def test_the_inbox_is_a_seeded_exclusion(make_project) -> None:
    assert "docs/_scratch/todo-inbox/*" in default_patterns(load_config(make_project()))


def test_the_readme_key_table_names_the_key() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "| `scratch_folder`" in text
