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
_FILL_STMTS = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Import, ast.ImportFrom, ast.Expr)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_FORK_NODES = (ast.If, ast.IfExp, ast.ExceptHandler, ast.Raise, ast.Assert)


# --- forks and size ---------------------------------------------------------------------------------------

def _own_nodes(func: ast.AST) -> Iterator[ast.AST]:
    """Walks ``func``'s body without entering nested functions, classes or lambdas."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _is_lazy_guard(node: ast.AST) -> bool:
    """True for ``if x is None:`` / ``if not x:`` with no ``else`` whose body only fills a value (a cache)."""
    if not isinstance(node, ast.If) or node.orelse:
        return False
    test = node.test
    is_none = (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Is)
               and isinstance(test.comparators[0], ast.Constant) and test.comparators[0].value is None)
    is_not = isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
    return (is_none or is_not) and all(isinstance(stmt, _FILL_STMTS) for stmt in node.body)


def count_forks(func: ast.AST) -> int:
    """Counts branch points: ``if``/``elif``, ``x if c else y``, ``except`` handlers, ``raise``/``assert``,
    and returns before the last statement. Comprehension filters and lazy-initialization guards are not
    forks."""
    last = func.body[-1] if func.body else None
    forks = 0
    for node in _own_nodes(func):
        if _is_lazy_guard(node):
            continue
        if isinstance(node, _FORK_NODES) or (isinstance(node, ast.Return) and node is not last):
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
    """Names the layout of an existing (cleaned) docstring; ``Layout.NONE`` when there is none."""
    if doc is None:
        return Layout.NONE
    if _SEPARATORS_ONLY.match(doc):
        return Layout.BLANK
    if _DASHES.search(doc):
        return Layout.FULL
    if _LABEL.search(doc):
        return Layout.COMPACT
    text = doc.strip()
    if len(text.split()) <= PLACEHOLDER_WORDS and not _SINGLE_TICK.search(text) and "``" not in text:
        return Layout.PLACEHOLDER
    return Layout.BRIEF if len(text.splitlines()) <= 2 else Layout.PROSE


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
    """Yields ``(qualname, node)`` for every module-level function and method, nested classes included."""
    def walk(node: ast.AST, prefix: str) -> Iterator[Tuple[str, ast.AST]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f"{prefix}{child.name}", child
    yield from walk(tree, "")


def _wanted(qualname: str, wanted: Sequence[str]) -> bool:
    """True when ``wanted`` is empty or names ``qualname`` or its last part."""
    return not wanted or qualname in wanted or qualname.rsplit(".", 1)[-1] in wanted


def report(path: Path, wanted: Sequence[str], max_line: int) -> List[SymbolReport]:
    """One row per function in ``path``, filtered to ``wanted`` names or qualnames when given.

    Raises ``OSError`` for an unreadable file and ``SyntaxError`` for source that does not parse.
    """
    source = Path(path).read_text(encoding="utf-8-sig")
    source_lines = source.splitlines(keepends=True)
    rows = []
    for qualname, func in iter_functions(ast.parse(source, filename=str(path))):
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
