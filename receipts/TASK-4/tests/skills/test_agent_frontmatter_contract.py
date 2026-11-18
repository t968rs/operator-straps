"""Harness agent frontmatter uses known keys; the agents that omit CLAUDE.md restate the rules they need.

`claude plugin validate --strict` does not check agent frontmatter keys, so a misspelled `omitClaudeMd` loads
silently and the agent keeps the CLAUDE.md block. An agent that omits it no longer receives the instruction
files, so its own body must carry the shell and wording rules those files would have supplied.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

import pytest

WALK_ROOTS = ("plugins/harness/agents/",)

_KNOWN_KEYS = {"name", "description", "model", "tools", "omitClaudeMd"}
_OMITTING = ("bubble-memo-investigator", "bubble-memo-reviewer", "messenger", "strap-judge")
_RESTATED_RULES = ("One command per Bash call (no `&&`, `;`)", "No AI vendor names")


def _agent_files(repo_root: Path) -> List[Path]:
    files = sorted((repo_root / "plugins" / "harness" / "agents").glob("*.md"))
    assert files, "no agent files found"
    return files


def _front(text: str) -> Dict[str, str]:
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
    assert match is not None, "no frontmatter"
    found: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            found[key.strip()] = value.strip()
    return found


def test_every_frontmatter_key_is_known(repo_root: Path) -> None:
    unknown = {
        path.name: sorted(set(_front(path.read_text(encoding="utf-8"))) - _KNOWN_KEYS)
        for path in _agent_files(repo_root)
    }
    assert {name: keys for name, keys in unknown.items() if keys} == {}


def test_omit_claude_md_is_set_on_exactly_the_listed_agents(repo_root: Path) -> None:
    fronts = {path.stem: _front(path.read_text(encoding="utf-8")) for path in _agent_files(repo_root)}
    omitting = {name for name, front in fronts.items() if "omitClaudeMd" in front}
    assert omitting == set(_OMITTING)
    assert {fronts[name]["omitClaudeMd"] for name in _OMITTING} == {"true"}


@pytest.mark.parametrize("name", _OMITTING)
def test_an_omitting_agent_restates_its_rules(repo_root: Path, name: str) -> None:
    body = (repo_root / "plugins" / "harness" / "agents" / f"{name}.md").read_text(encoding="utf-8")
    flat = " ".join(body.split())
    missing = [rule for rule in _RESTATED_RULES if rule not in flat]
    assert missing == []
