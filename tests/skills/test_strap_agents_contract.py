"""The two strap-skills agents: frontmatter, the runner's init/TREE/record-run loop, the judge's grading rule.

Pins ``plugins/harness/agents/strap-scenario-runner.md`` and ``plugins/harness/agents/strap-judge.md``
against the Agents section of plan 0002's contract.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _skill_parts import skill_parts  # noqa: E402

_RUNNER = "strap-scenario-runner"
_JUDGE = "strap-judge"
_AGENTS = (_RUNNER, _JUDGE)
# The file names are spelled out so tools/select_tests.py selects this test when an agent file changes.
_AGENT_FILES = ("strap-scenario-runner.md", "strap-judge.md")
_TOOLS = {
    _RUNNER: "Read, Edit, Write, Grep, Glob, Bash",
    _JUDGE: "Read, Grep, Glob, Bash",
}
# Contract D21: agent bodies name agents only as harness:<id>.
_BARE_ID = re.compile(r"(?<![\w:/.-])strap-(?:scenario-runner|judge)\b(?![\w.-])")
# A driver command line: `strap.py` (optionally quote-closed), an optional `--repo DIR`, then the verb.
_COMMAND = re.compile(
    r'strap\.py"?\s+(?P<repo>--repo\s+(?:"[^"\n]*"|\S+)\s+)?(?P<verb>init|record-run)(?![\w-])'
)


def _parts(repo_root: Path, name: str) -> Tuple[Dict[str, str], str]:
    file_name = f"{name}.md"
    assert file_name in _AGENT_FILES, f"{file_name} is not a listed agent file"
    path = repo_root / "plugins" / "harness" / "agents" / file_name
    assert path.is_file(), f"{path} does not exist"
    return skill_parts(path)


@pytest.mark.parametrize("name", _AGENTS)
def test_frontmatter_matches_the_contract(repo_root: Path, name: str) -> None:
    front, _ = _parts(repo_root, name)
    assert front.get("name") == name
    assert front.get("model") == "sonnet"
    assert front.get("tools") == _TOOLS[name]


@pytest.mark.parametrize("name", _AGENTS)
def test_body_launches_the_driver_through_hpy(repo_root: Path, name: str) -> None:
    _, body = _parts(repo_root, name)
    assert "strap.py" in body and "hpy" in body
    assert "${CLAUDE_PLUGIN_ROOT}" in body


@pytest.mark.parametrize("name", _AGENTS)
def test_body_names_no_bare_agent_id(repo_root: Path, name: str) -> None:
    _, body = _parts(repo_root, name)
    bare = _BARE_ID.findall(body)
    assert not bare, f"{name} names an agent without the harness: prefix: {bare}"


def _commands(body: str, verb: str) -> List[re.Match]:
    return [match for match in _COMMAND.finditer(body) if match.group("verb") == verb]


def test_runner_inits_first_and_records_last(repo_root: Path) -> None:
    _, body = _parts(repo_root, _RUNNER)
    inits, records = _commands(body, "init"), _commands(body, "record-run")
    assert inits, "no `strap.py init` command line"
    assert records, "no `strap.py record-run` command line"
    assert inits[0].start() < records[0].start(), "record-run is shown before init"


@pytest.mark.parametrize("verb", ("init", "record-run"))
def test_runner_command_carries_repo(repo_root: Path, verb: str) -> None:
    _, body = _parts(repo_root, _RUNNER)
    lines = _commands(body, verb)
    assert lines, f"no `strap.py {verb}` command line"
    bare = [match.group(0) for match in lines if not match.group("repo")]
    assert not bare, f"`{verb}` without --repo: {bare}"


def test_runner_records_exactly_one_run_by_heredoc(repo_root: Path) -> None:
    _, body = _parts(repo_root, _RUNNER)
    assert re.search(r"(?i)exactly on(?:e|ce)\b", body), "no exactly-one record-run rule"
    assert "<<" in body, "record-run is not shown as a heredoc"


def test_runner_works_only_inside_the_tree(repo_root: Path) -> None:
    _, body = _parts(repo_root, _RUNNER)
    assert "TREE" in body


def test_runner_reply_is_the_printed_block_verbatim(repo_root: Path) -> None:
    _, body = _parts(repo_root, _RUNNER)
    assert "verbatim" in body.lower()


def test_runner_session_role_ends_at_agent_call(repo_root: Path) -> None:
    _, body = _parts(repo_root, _RUNNER)
    assert "Agent(" in body


def test_runner_states_stop_conditions(repo_root: Path) -> None:
    _, body = _parts(repo_root, _RUNNER)
    assert re.search(r"(?i)\bstop\b", body), "no stop conditions"


def test_judge_grades_through_the_api_as_judge(repo_root: Path) -> None:
    _, body = _parts(repo_root, _JUDGE)
    assert "api" in body and "grade(" in body
    assert 'grader="judge"' in body


def test_judge_quotes_each_item_verbatim(repo_root: Path) -> None:
    _, body = _parts(repo_root, _JUDGE)
    assert "verbatim" in body.lower() and "quote" in body.lower()


def test_judge_never_edits_files(repo_root: Path) -> None:
    front, body = _parts(repo_root, _JUDGE)
    assert "Edit" not in front.get("tools", "") and "Write" not in front.get("tools", "")
    assert re.search(r"(?i)never (?:edit|write|modif)", body), "no rule forbidding edits"
