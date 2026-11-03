"""Writing-docstrings: measures each function of a Python file against the docstring convention.

``report`` parses a file and returns one ``SymbolReport`` per function or method: body lines, forks, the
suggested tier, the current layout and the format flags. The line limit is a parameter; the tier command
reads it from ``docstrings.line_length``. The suggestion is a starting point: the convention's decision rule,
applied by reading the body and the current docstring, has the final say.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

from harness_lib.writing_docstrings_models import (
    KNOWN_LABELS,
    PLACEHOLDER_WORDS,
    SECTION_ORDER,
    Layout,
    SymbolReport,
    suggest_tier,
)

__all__ = ["count_forks", "body_lines", "current_layout", "docstring_flags", "iter_functions", "report",
           "unmatched"]

_DASHES = re.compile(r"^\s*-{3,}\s*$", re.MULTILINE)
_LABEL = re.compile(r"^\s*[A-Z][A-Za-z ]*:\s*$", re.MULTILINE)
_SINGLE_TICK = re.compile(r"(?<!`)`(?!`)[^`\n]+?(?<!`)`(?!`)")
_CITATION = re.compile(r"report Section|PR #\d+|\(Section \d|\b[ICM]\d{1,2}\b:")
#: A line, or a whole docstring, holding nothing but whitespace and separator characters.
_SEPARATORS_ONLY = re.compile(r"^[\s\-=_*#~+.:;|]*$")
_ASSIGNS = (ast.Assign, ast.AnnAssign)
_IMPORTS = (ast.Import, ast.ImportFrom)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_FORK_NODES = (ast.If, ast.IfExp, ast.ExceptHandler, ast.match_case, ast.Raise, ast.Assert)
_TRIES = (ast.Try, ast.TryStar)


# --- forks and size ---------------------------------------------------------------------------------------

def _own_nodes(func: ast.AST) -> Iterator[ast.AST]:
    """Walks ``func``'s body without entering nested functions, classes or lambdas.

    Decorators, parameter defaults and annotations sit outside the body and are not walked.
    """
    stack = list(func.body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _ref(node: ast.AST) -> Optional[str]:
    """The dotted name of a ``Name`` or ``Attribute`` chain (``self._cache``); ``None`` for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _ref(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _guarded(test: ast.expr) -> Optional[str]:
    """The ``x`` that ``x is None`` or ``not x`` tests, when ``x`` is a name or attribute."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _ref(test.operand)
    if (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Is)
            and isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value is None):
        return _ref(test.left)
    return None


def _fills(stmt: ast.stmt, name: str) -> bool:
    """True for an import, or an assignment whose every target is ``name``."""
    if isinstance(stmt, _IMPORTS):
        return True
    if not isinstance(stmt, _ASSIGNS):
        return False
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
    return all(_ref(target) == name for target in targets)


def _is_lazy_guard(node: ast.AST) -> bool:
    """True for ``if x is None:`` / ``if not x:`` with no ``else``, ``x`` a name or attribute, whose body only
    assigns ``x`` (a cache), imports aside."""
    if not isinstance(node, ast.If) or node.orelse:
        return False
    name = _guarded(node.test)
    return (name is not None and all(_fills(stmt, name) for stmt in node.body)
            and any(isinstance(stmt, _ASSIGNS) for stmt in node.body))


def _tail_returns(block: Sequence[ast.stmt]) -> Iterator[ast.Return]:
    """Yields each ``return`` that ends ``block``: its last statement, or the last statement of each branch of
    a final ``if``, ``with``, ``try`` or ``match``, followed down recursively."""
    last = block[-1] if block else None
    if isinstance(last, ast.Return):
        yield last
    elif isinstance(last, ast.If):
        yield from _tail_returns(last.body)
        yield from _tail_returns(last.orelse)
    elif isinstance(last, (ast.With, ast.AsyncWith)):
        yield from _tail_returns(last.body)
    elif isinstance(last, _TRIES):
        yield from _tail_returns(last.orelse or last.body)
        for handler in last.handlers:
            yield from _tail_returns(handler.body)
        yield from _tail_returns(last.finalbody)
    elif isinstance(last, ast.Match):
        for case in last.cases:
            yield from _tail_returns(case.body)


def count_forks(func: ast.AST) -> int:
    """Counts branch points: ``if``/``elif``, ``x if c else y``, ``except`` handlers, ``match`` cases,
    ``raise``/``assert``, and each ``return`` that does not end the function. A return ends it as the last
    statement or as the last statement of a branch of a final ``if``, ``with``, ``try`` or ``match``.
    Comprehension filters and lazy-initialization guards are not forks."""
    tail = set(_tail_returns(func.body))
    forks = 0
    for node in _own_nodes(func):
        if _is_lazy_guard(node) or node in tail:
            continue
        if isinstance(node, (*_FORK_NODES, ast.Return)):
            forks += 1
    return forks


def body_lines(func: ast.AST) -> int:
    """Lines from the first statement after the docstring to the end of the function."""
    body = func.body[1:] if ast.get_docstring(func) is not None else func.body
    if not body:
        return 0
    return func.end_lineno - body[0].lineno + 1


# --- layouts ----------------------------------------------------------------------------------------------

def current_layout(doc: Optional[str]) -> Layout:
    """Names the layout of an existing (cleaned) docstring; ``Layout.NONE`` when there is none.

    Unlabeled text is a placeholder by ``_is_placeholder``, brief on one line and prose on more.
    """
    if doc is None:
        return Layout.NONE
    if _SEPARATORS_ONLY.match(doc):
        return Layout.BLANK
    if _DASHES.search(doc):
        return Layout.FULL
    if _LABEL.search(doc):
        return Layout.COMPACT
    text = doc.strip()
    if _is_placeholder(text):
        return Layout.PLACEHOLDER
    return Layout.BRIEF if len(text.splitlines()) == 1 else Layout.PROSE


def _is_placeholder(text: str) -> bool:
    """True for ``PLACEHOLDER_WORDS`` words or fewer, without backticks, that are one word or do not open with
    a third-person verb (``Push.``, ``Get desc.``); a guess, hence ``placeholder?``."""
    words = text.split()
    if len(words) > PLACEHOLDER_WORDS or _SINGLE_TICK.search(text) or "``" in text:
        return False
    return len(words) < 2 or not words[0].endswith("s")


# --- flags ------------------------------------------------------------------------------------------------

def docstring_flags(func: ast.AST, source_lines: Sequence[str], max_line: int) -> List[str]:
    """Format issues inside the docstring's own source lines; empty when there is no docstring."""
    if ast.get_docstring(func) is None:
        return []
    node = func.body[0]
    raw = list(source_lines[node.lineno - 1:node.end_lineno])
    text = "".join(raw)
    labels = _LABEL.findall(text)
    flags = []
    long_lines = [node.lineno + i for i, line in enumerate(raw) if len(line.rstrip("\r\n")) > max_line]
    if long_lines:
        flags.append(f"long-lines={long_lines}")
    if _SINGLE_TICK.search(text):
        flags.append("single-backticks")
    if _CITATION.search(text):
        flags.append("citation")
    if not _DASHES.search(text) and not _in_section_order(labels):
        flags.append("section-order")
    unknown = _unknown_labels(labels)
    if unknown:
        flags.append(f"unknown-label={','.join(unknown)}")
    if _misaligned(raw):
        flags.append("misaligned")
    return flags + _separator_flags(ast.get_docstring(func, clean=False))


def _separator_flags(doc: str) -> List[str]:
    """``blank`` for a docstring of separators alone, else ``separator-line`` for a stray separator line."""
    if _SEPARATORS_ONLY.match(doc):
        return ["blank"]
    return ["separator-line"] if _stray_separator_lines(doc) else []


def _stray_separator_lines(doc: str) -> bool:
    """True when a non-empty separator-only line is not the underline directly under a section label."""
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        if not line.strip() or not _SEPARATORS_ONLY.match(line):
            continue
        if i == 0 or not _LABEL.match(lines[i - 1]):
            return True
    return False


def _label_names(labels: Iterable[str]) -> List[str]:
    return [label.strip().rstrip(":") for label in labels]


def _in_section_order(labels: Iterable[str]) -> bool:
    """True when the known compact labels appear in ``SECTION_ORDER`` order."""
    ranks = [SECTION_ORDER.index(name) for name in _label_names(labels) if name in SECTION_ORDER]
    return ranks == sorted(ranks)


def _unknown_labels(labels: Iterable[str]) -> List[str]:
    """Names each label outside ``KNOWN_LABELS``, in order of appearance."""
    return [name for name in _label_names(labels) if name not in KNOWN_LABELS]


def _misaligned(raw: Sequence[str]) -> bool:
    """True when a non-empty docstring line sits left of the line holding the opening quotes."""
    indent = len(raw[0]) - len(raw[0].lstrip())
    return any(line.strip() and len(line) - len(line.lstrip()) < indent for line in raw[1:])


# --- report -----------------------------------------------------------------------------------------------

def iter_functions(tree: ast.Module) -> Iterator[Tuple[str, ast.AST]]:
    """Yields ``(qualname, node)`` for every module-level function and method, nested classes included.

    Functions under a module- or class-level compound statement (``if TYPE_CHECKING:``, ``try:``/``except``,
    ``with``, loops, ``match``) count too; function bodies are not entered.
    """
    def walk(node: ast.AST, prefix: str) -> Iterator[Tuple[str, ast.AST]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f"{prefix}{child.name}", child
            elif isinstance(child, (ast.stmt, ast.excepthandler, ast.match_case)):
                yield from walk(child, prefix)
    yield from walk(tree, "")


def _wanted(qualname: str, wanted: Sequence[str]) -> bool:
    """True when ``wanted`` is empty or names ``qualname`` or its last part."""
    return not wanted or qualname in wanted or qualname.rsplit(".", 1)[-1] in wanted


def _read_source(path: Path) -> str:
    """The UTF-8 text of ``path`` with newlines translated as ``read_text`` does; a byte sequence that does
    not decode raises ``SyntaxError``."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        lineno = raw.count(b"\n", 0, exc.start) + 1
        raise SyntaxError(f"not UTF-8 source ({exc.reason})", (str(path), lineno, None, None)) from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _parse(source: str, path: Path) -> ast.Module:
    """``ast.parse`` with the ``ValueError`` for a null byte (Python 3.11) raised as ``SyntaxError``."""
    try:
        return ast.parse(source, filename=str(path))
    except ValueError as exc:
        lineno = source.count("\n", 0, source.find("\0")) + 1 if "\0" in source else None
        raise SyntaxError(str(exc), (str(path), lineno, None, None)) from exc


def report(path: Path, wanted: Sequence[str], max_line: int) -> List[SymbolReport]:
    """One row per function in ``path``, filtered to ``wanted`` names or qualnames when given.

    Raises ``OSError`` for an unreadable file and ``SyntaxError`` for source that does not parse, including
    source that is not UTF-8 or holds a null byte.
    """
    source = _read_source(path)
    source_lines = source.splitlines(keepends=True)
    rows = []
    for qualname, func in iter_functions(_parse(source, path)):
        if not _wanted(qualname, wanted):
            continue
        lines, forks = body_lines(func), count_forks(func)
        rows.append(SymbolReport(
            line=func.lineno, qualname=qualname, lines=lines, forks=forks, suggest=suggest_tier(lines, forks),
            current=current_layout(ast.get_docstring(func)),
            flags=docstring_flags(func, source_lines, max_line),
        ))
    return rows


def unmatched(rows: Sequence[SymbolReport], wanted: Sequence[str]) -> List[str]:
    """Each name in ``wanted`` that no row's qualname, or its last part, matches."""
    names = {row.qualname for row in rows} | {row.qualname.rsplit(".", 1)[-1] for row in rows}
    return [name for name in wanted if name not in names]
