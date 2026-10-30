"""Lint for plugin skills and Python parts: skill frontmatter and body rules, person words in comments.

``lint_skill`` returns one problem string per defect of ``<plugin_dir>/skills/<name>/SKILL.md``, each prefixed
``"<name>: "``. ``lint_python`` returns the first and second person words found in the comments and docstrings
of one Python file; code and string literals are never scanned. Both return an empty list for a clean input.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from harness_lib.skill_parts import skill_parts
from harness_lib.strap_models import DESCRIPTION_MAX

_POINTER = "${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md"
_PREFIX = "Use when"
_PERSON = re.compile(r"\b(?:I|we|you|your)\b", re.IGNORECASE)
_PY_PERSON = re.compile(r"\b(?:we|you|your|our)\b", re.IGNORECASE)
_PY_UPPER_I = re.compile(r"\bI\b")
_PLUGIN_PATH = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/((?:scripts|skills)/[\w./-]++)(?![<*{$\[])")
_AGENT = re.compile(r"\bharness:([a-z][a-z0-9-]*[a-z0-9])")
_LIB_MODULE = re.compile(r"\bharness_lib\.([A-Za-z_][A-Za-z0-9_]*)")
_BARE_PYTHON = re.compile(r"^\s*(?:\w+=\S+\s+)*python3?(?=\s|$)|[|;&(]\s*python3?(?=\s|$)")
_VENDOR = re.compile(r"\b(?:Anthropic|OpenAI|ChatGPT|Gemini)\b|\bClaude\b(?! Code)")
_VENDOR_SAFE = re.compile(r"\$\{CLAUDE_\w+\}|CLAUDE\.md")


def _unquote(value: str) -> str:
    """``value`` without one pair of matching surrounding quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def is_invocable(frontmatter: Dict[str, str], body: str) -> bool:
    """True when the body carries ``$ARGUMENTS`` or the frontmatter has an ``argument-hint`` key."""
    return "$ARGUMENTS" in body or "argument-hint" in frontmatter


def _fenced_lines(body: str) -> List[str]:
    """The lines of ``body`` that sit inside fenced code blocks."""
    inside, lines = False, []
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
        elif inside:
            lines.append(line)
    return lines


def _description_problems(keys: Dict[str, str]) -> List[str]:
    """Defects of the ``description`` value, without the skill-name prefix."""
    description = keys.get("description")
    if not description:
        return ["description is missing"]
    problems = []
    if not description.startswith(_PREFIX):
        problems.append(f"description does not start with '{_PREFIX}'")
    if len(description) > DESCRIPTION_MAX:
        problems.append(f"description is {len(description)} characters, over {DESCRIPTION_MAX}")
    found = sorted({word.lower() for word in _PERSON.findall(description)})
    if found:
        problems.append(f"description uses first or second person: {', '.join(found)}")
    return problems


def _argument_problems(keys: Dict[str, str], body: str) -> List[str]:
    """Defects of an invocable skill's argument hint, split-rule pointer and fenced ``$ARGUMENTS``."""
    if not is_invocable(keys, body):
        return []
    problems = []
    if "-- <" not in keys.get("argument-hint", ""):
        problems.append("argument-hint is missing or lacks the '-- <guidance>' tail")
    if _POINTER not in body:
        problems.append(f"body never cites {_POINTER}")
    holders = [line.strip() for line in _fenced_lines(body) if "$ARGUMENTS" in line]
    problems.extend(f"fenced line carries $ARGUMENTS: {line}" for line in holders)
    return problems


def _reference_problems(plugin_dir: Path, body: str) -> List[str]:
    """Scripts, skills, agents and ``harness_lib`` modules the body names that do not exist."""
    problems = []
    for rel in sorted({match.rstrip(".") for match in _PLUGIN_PATH.findall(body)}):
        if not (plugin_dir / rel).exists():
            problems.append(f"names ${{CLAUDE_PLUGIN_ROOT}}/{rel}, which does not exist")
    for agent in sorted(set(_AGENT.findall(body))):
        if not _agent_exists(plugin_dir, agent):
            problems.append(f"dispatches harness:{agent}, which has no agent or skill file")
    for module in sorted(set(_LIB_MODULE.findall(body))):
        lib = plugin_dir / "lib" / "harness_lib"
        if not ((lib / f"{module}.py").is_file() or (lib / module).is_dir()):
            problems.append(f"names harness_lib.{module}, which does not exist")
    return problems


def _agent_exists(plugin_dir: Path, agent: str) -> bool:
    """True when ``agent`` is an agent file or a skill folder of the plugin."""
    return (plugin_dir / "agents" / f"{agent}.md").is_file() or (
        plugin_dir / "skills" / agent / "SKILL.md").is_file()


def _text_problems(body: str) -> List[str]:
    """Bare interpreter calls in fences and vendor names in ``body``."""
    problems = [f"fenced line runs python directly instead of through hpy: {line.strip()}"
                for line in _fenced_lines(body) if _BARE_PYTHON.search(line)]
    cleaned = _VENDOR_SAFE.sub("", body)
    for name in sorted({match.group(0) for match in _VENDOR.finditer(cleaned)}):
        problems.append(f"names the vendor '{name}'")
    return problems


def lint_skill(plugin_dir: Path, name: str) -> List[str]:
    """One problem string per defect of skill ``name`` under ``plugin_dir``, each prefixed ``"<name>: "``."""
    path = plugin_dir / "skills" / name / "SKILL.md"
    if not path.is_file():
        return [f"{name}: no SKILL.md"]
    try:
        raw, body = skill_parts(path)
    except AssertionError:
        return [f"{name}: SKILL.md has no frontmatter"]
    keys = {key: _unquote(value) for key, value in raw.items()}
    problems = []
    if keys.get("name") != name:
        problems.append(f"frontmatter name {keys.get('name')!r} does not match the folder name")
    problems.extend(_description_problems(keys))
    problems.extend(_argument_problems(keys, body))
    problems.extend(_reference_problems(plugin_dir, body))
    problems.extend(_text_problems(body))
    return [f"{name}: {problem}" for problem in problems]


def _person_words(text: str) -> List[str]:
    """First and second person words found in ``text``, in order of appearance."""
    return [match.group(0).lower() for match in _PY_PERSON.finditer(text)] + _PY_UPPER_I.findall(text)


def _comments(source: str) -> Iterator[Tuple[int, str]]:
    """``(line, text)`` of every comment token in ``source``."""
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            yield token.start[0], token.string.lstrip("#")


def _docstrings(tree: ast.AST) -> Iterator[Tuple[int, str]]:
    """``(line, text)`` of the module, class and function docstrings of ``tree``."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            text = ast.get_docstring(node, clean=False)
            if text is not None:
                yield node.body[0].lineno, text


def lint_python(path: Path) -> List[str]:
    """First and second person words in the comments and docstrings of ``path``; code is never scanned."""
    source = path.read_text(encoding="utf-8")
    try:
        found = list(_comments(source)) + list(_docstrings(ast.parse(source)))
    except (SyntaxError, tokenize.TokenError) as exc:
        return [f"{path.name}: cannot parse: {exc}"]
    problems = []
    for line, text in sorted(found):
        for offset, row in enumerate(text.splitlines() or [""]):
            words = _person_words(row)
            if words:
                problems.append(f"{path.name}:{line + offset}: first or second person in comment: "
                                f"{', '.join(sorted(set(words)))}")
    return problems
