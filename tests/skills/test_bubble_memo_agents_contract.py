"""The two bubble-memo agents: read-only, script-bootstrapped, one standard return block, usage-logged."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

import pytest

from mods._mods_helpers import ts_string_array

_AGENTS = ("bubble-memo-investigator", "bubble-memo-reviewer")
# The file names are spelled out so tools/select_tests.py selects this test when an agent file changes.
_AGENT_FILES = ("bubble-memo-investigator.md", "bubble-memo-reviewer.md")
_CONTRACT_REL = "plugins/pr-review-watch/hooks/contract.ts"


def _agent(repo_root: Path, name: str) -> Path:
    file_name = f"{name}.md"
    assert file_name in _AGENT_FILES, f"{file_name} is not a listed agent file"
    path = repo_root / "plugins" / "harness" / "agents" / file_name
    assert path.is_file(), f"{path} does not exist"
    return path


def _front(text: str) -> Dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match is not None, "no frontmatter"
    found: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            found[key.strip()] = value.strip()
    return found


@pytest.mark.parametrize("name", _AGENTS)
def test_frontmatter_is_read_only(repo_root: Path, name: str) -> None:
    front = _front(_agent(repo_root, name).read_text(encoding="utf-8"))
    assert front["name"] == name
    assert front["tools"] == "Read, Grep, Glob, Bash"
    assert front["model"] in {"opus", "sonnet"}


@pytest.mark.parametrize("name", _AGENTS)
def test_init_comes_first_record_last(repo_root: Path, name: str) -> None:
    body = _agent(repo_root, name).read_text(encoding="utf-8")
    assert "bubble_memo.py" in body and "hpy" in body
    assert body.index("`init`") < body.index("`record`")
    assert "exactly once" in body


@pytest.mark.parametrize("name", _AGENTS)
def test_reply_is_the_record_block(repo_root: Path, name: str) -> None:
    body = _agent(repo_root, name).read_text(encoding="utf-8")
    assert "verbatim" in body and "problem:" in body


@pytest.mark.parametrize("name", _AGENTS)
def test_never_writes_read_only_git(repo_root: Path, name: str) -> None:
    body = _agent(repo_root, name).read_text(encoding="utf-8")
    assert "Never write files" in body and "Read-only git" in body


def test_the_reviewer_names_both_lenses(repo_root: Path) -> None:
    body = _agent(repo_root, "bubble-memo-reviewer").read_text(encoding="utf-8")
    assert "accuracy" in body and "clarity and simplicity" in body


def test_the_investigator_reports_facts_not_prose(repo_root: Path) -> None:
    body = _agent(repo_root, "bubble-memo-investigator").read_text(encoding="utf-8")
    assert "current behavior" in body.lower()
    assert "No recommendation and no memo prose" in body


@pytest.mark.parametrize("name", _AGENTS)
def test_usage_log_knows_the_agent(repo_root: Path, name: str) -> None:
    contract = (repo_root / _CONTRACT_REL).read_text(encoding="utf-8")
    assert f"harness:{name}" in ts_string_array(contract, "DEFINED_AGENTS")
