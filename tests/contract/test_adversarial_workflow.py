"""The plugin's adversarial review Workflow script and its agent.

The script sits where ``review_models`` names it, opens with a pure-literal ``meta`` whose phases match its
``phase`` calls, reads every slot from ``args`` (``guidance`` included), carries no clock, randomness,
module loading, process access, machine path or model literal, and names only plugin agents that exist. The
agent file is read-only on the repository except its draft, runs on opus, and states both refuter roles, the
``init`` start, its record calls and the ban on repository writes through Bash. The literal scan covers
``.js`` and agent-watcher's ``DEFINED_AGENTS`` lists the agent.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Set

from conftest import PLUGIN_ROOT, REPO_ROOT
from harness_lib import review_models as rm
from mods._mods_helpers import ts_string_array

# The file names are spelled out so tools/select_tests.py selects this test when either file changes.
_SCRIPT_NAME = "adversarial-review.js"
_AGENT_FILE = "adversarial-reviewer.md"
_AGENT = PLUGIN_ROOT / "agents" / _AGENT_FILE
_CONTRACT_REL = "plugins/agent-watcher/hooks/core/contract.ts"
_META_OPEN = "export const meta = {"
_STRING = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`")


def _script() -> Path:
    path = PLUGIN_ROOT / rm.ADVERSARIAL_WORKFLOW
    assert path.name == _SCRIPT_NAME and path.is_file(), path
    return path


def _agent_text() -> str:
    assert _AGENT.is_file(), _AGENT
    return _AGENT.read_text(encoding="utf-8")


def _text() -> str:
    return _script().read_text(encoding="utf-8")


def _code() -> str:
    """The script with every string literal emptied and every comment removed."""
    text = _STRING.sub("''", _text())
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)


def _meta(text: str) -> str:
    """The ``meta`` object literal, from its opening brace to the matching close (strings skipped)."""
    start = text.index(_META_OPEN) + len(_META_OPEN) - 1
    depth, pos = 0, start
    while pos < len(text):
        string = _STRING.match(text, pos)
        if string:
            pos = string.end()
            continue
        depth += {"{": 1, "}": -1}.get(text[pos], 0)
        pos += 1
        if depth == 0:
            return text[start:pos]
    raise AssertionError("meta object never closes")


def _front() -> Dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", _agent_text(), re.DOTALL)
    assert match is not None, "no frontmatter"
    found: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            found[key.strip()] = value.strip()
    return found


def _body() -> str:
    return _agent_text().split("\n---\n", 1)[1]


def test_script_sits_at_the_named_path() -> None:
    assert rm.ADVERSARIAL_WORKFLOW == f"workflows/{_SCRIPT_NAME}"
    assert _script().parent == PLUGIN_ROOT / "workflows"


def test_meta_is_the_first_statement_and_a_pure_literal() -> None:
    text = _text()
    assert re.sub(r"^(\s*//[^\n]*\n|\s*/\*.*?\*/)*\s*", "", text, flags=re.DOTALL).startswith(_META_OPEN)
    meta = _STRING.sub("''", _meta(text))
    assert "${" not in _meta(text) and "..." not in meta and "(" not in meta
    bare = re.sub(r"[A-Za-z_$][\w$]*\s*:", "", meta)
    bare = re.sub(r"\b(true|false|null)\b|''", "", bare)
    assert re.fullmatch(r"[\s{}\[\],:\d.\-]*", bare), bare


def test_meta_names_the_workflow() -> None:
    meta = _meta(_text())
    assert re.search(r"\bname:\s*['\"]", meta) and re.search(r"\bdescription:\s*['\"]", meta)


def _phase_titles(text: str) -> Set[str]:
    return set(re.findall(r"title:\s*['\"]([^'\"]+)['\"]", _meta(text)))


def _after_meta(text: str) -> str:
    return text[text.index(_meta(text)) + len(_meta(text)):]


def _called_phases(text: str) -> Set[str]:
    """Phase titles passed as literals to ``phase(...)`` or an agent's ``phase:`` option."""
    body = _after_meta(text)
    called = set(re.findall(r"\bphase\(\s*['\"]([^'\"]+)['\"]", body))
    return called | set(re.findall(r"\bphase:\s*['\"]([^'\"]+)['\"]", body))


def test_phases_match_the_meta_entries() -> None:
    text = _text()
    titles, called = _phase_titles(text), _called_phases(text)
    assert called and called <= titles, (called, titles)
    literals = {s[1:-1] for s in _STRING.findall(_after_meta(text))}
    assert titles <= literals, f"meta phases never named in the body: {sorted(titles - literals)}"


def test_agent_types_name_existing_plugin_agents() -> None:
    text = _text()
    assert "agentType" in _code()
    named = set(re.findall(r"['\"]harness:([a-z0-9-]+)['\"]", text))
    named |= {rm.ADVERSARIAL_AGENT.split(":", 1)[1], "pr-reviewer"}
    missing = [n for n in sorted(named) if not (PLUGIN_ROOT / "agents" / f"{n}.md").is_file()]
    assert not missing, missing
    assert rm.ADVERSARIAL_AGENT == "harness:adversarial-reviewer"


def test_script_reads_every_slot_and_the_guidance_from_args() -> None:
    code = _code()
    for field in ("args.reviewers", "args.code", "args.refute", "args.guidance"):
        assert field in code, field
    assert "Developer guidance: " in _text()


def test_script_uses_no_clock_randomness_modules_or_process() -> None:
    code = _code()
    banned = ("Date.now", "Math.random", "new Date(", "require(", "process.", "import(")
    hits = [b for b in banned if b in code]
    assert not hits, hits


def test_script_names_no_machine_path() -> None:
    hits = re.findall(r"\b[A-Za-z]:[\\/](?!/)|/Users/|/home/", _text())
    assert not hits, hits


def test_script_holds_no_model_literal() -> None:
    hits = re.findall(r"['\"`](opus|sonnet|haiku)['\"`]", _text())
    assert not hits, hits


def test_agent_frontmatter_names_the_agent_its_tools_and_opus() -> None:
    front = _front()
    assert front["name"] == "adversarial-reviewer"
    assert front["tools"] == "Read, Grep, Glob, Bash, Write"
    assert front["model"] == "opus"


def test_agent_body_names_both_roles_init_and_the_record_calls() -> None:
    body = _body()
    lowered = body.lower()
    assert "code refuter" in lowered and "findings refuter" in lowered
    assert re.search(r"\binit --pr\b", body), "the body never shows the init --pr call"
    for needle in ("record_attacks", "record_refutations_draft"):
        assert needle in body, needle


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n", text) if s.strip()]


def test_agent_body_bans_repository_writes_through_bash() -> None:
    body = _body()
    banned = [s for s in _sentences(body)
              if "Bash" in s and "repo" in s.lower() and re.search(r"(?i)\b(never|no|not)\b", s)]
    assert banned, "no sentence bans repository writes through Bash"
    assert "no:cacheprovider" in body and "run directory" in body


def test_the_literal_scan_reads_js_files() -> None:
    from contract import test_no_repo_literals as literals
    assert ".js" in literals.TEXT_SUFFIXES
    assert _script() in literals.FILES


def test_agent_watcher_knows_the_agent() -> None:
    contract = (REPO_ROOT / _CONTRACT_REL).read_text(encoding="utf-8")
    assert rm.ADVERSARIAL_AGENT in ts_string_array(contract, "DEFINED_AGENTS")
