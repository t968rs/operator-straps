"""Writing-docstrings: measures each function of a Python file against the docstring convention.

``report`` parses a file and returns one ``SymbolReport`` per function or method: body lines, forks, the
suggested tier, the current layout and the format flags. The line limit is a parameter; the tier command
reads it from ``docstrings.line_length``. The suggestion is a starting point: the convention's decision rule,
applied by reading the body and the current docstring, has the final say.

The dispatch section turns command-line tokens into ``FileScope`` entries (``resolve_scope``), groups them
into ``DispatchRow`` values (``plan_rows``), and writes, lists and removes the tool-probe files of a parallel
run (``write_probes``, ``probe_row``, ``clear_probes``).
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

from harness_lib.writing_docstrings_models import (
    KNOWN_LABELS,
    PLACEHOLDER_WORDS,
    PROBE_MODEL,
    PROBE_NAME,
    PROBE_SOURCE,
    SECTION_ORDER,
    WORK_MODEL,
    DispatchRow,
    FileScope,
    Layout,
    SymbolReport,
    suggest_tier,
)

__all__ = ["count_forks", "body_lines", "current_layout", "docstring_flags", "iter_functions", "report",
           "unmatched", "DispatchError", "first_path", "resolve_scope", "plan_rows", "write_probes",
           "probe_row", "clear_probes"]

_DASHES = re.compile(r"^\s*-{3,}\s*$", re.MULTILINE)
_LABEL = re.compile(r"^\s*[A-Z][A-Za-z ]*:\s*$", re.MULTILINE)
_SINGLE_TICK = re.compile(r"(?<!`)`(?!`)[^`\n]+?(?<!`)`(?!`)")
#: A full-layout ``Parameters`` header, colon or not (a dashed underline must follow it).
_PARAMS_HEADER = re.compile(r"^\s*Parameters:?\s*$")
#: The start of a ``name: (type) Description`` item, up to the opening parenthesis of the type.
_PARAM_ITEM = re.compile(r"^( *)(\*{0,2}[A-Za-z_]\w*): \(")
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
    return flags + _separator_flags(ast.get_docstring(func, clean=False)) + _full_flags(raw, node.lineno)


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


def _full_flags(raw: Sequence[str], first: int) -> List[str]:
    """``underline-width`` and ``param-format``, each with the source lines it applies to.

    ``raw`` holds the docstring's source lines and ``first`` the line number of ``raw[0]``.
    """
    lines = _strip_closing(raw)
    flags = []
    widths = [first + i for i in _short_underlines(lines)]
    if widths:
        flags.append(f"underline-width={widths}")
    params = [first + i for header, section in _param_sections(lines)
              for i in _bad_param_lines(lines, section, _indent(lines[header]) + 4)]
    if params:
        flags.append(f"param-format={params}")
    return flags


def _strip_closing(raw: Sequence[str]) -> List[str]:
    """The lines of ``raw`` without line endings, the closing quotes cut from the last one."""
    lines = [line.rstrip("\r\n") for line in raw]
    last = lines[-1].rstrip()
    if last.endswith(('"""', "'''")):
        lines[-1] = last[:-3]
    return lines


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _short_underlines(lines: Sequence[str]) -> List[int]:
    """Index of each dashed underline below a label whose width differs from the label's, colon included."""
    return [i for i in range(1, len(lines)) if _DASHES.match(lines[i]) and _LABEL.match(lines[i - 1])
            and len(lines[i].strip()) != len(lines[i - 1].strip())]


def _is_header(lines: Sequence[str], i: int) -> bool:
    """True when ``lines[i]`` is a label (colon or not) with a dashed underline below it."""
    return i + 1 < len(lines) and bool(lines[i].strip()) and bool(_DASHES.match(lines[i + 1]))


def _param_sections(lines: Sequence[str]) -> Iterator[Tuple[int, List[int]]]:
    """``(header, items)`` per dashed ``Parameters`` section, colon or not: the header's index and the
    indexes below its underline up to a blank line, a label, another header or the end."""
    for i in range(len(lines) - 1):
        if not (_PARAMS_HEADER.match(lines[i]) and _DASHES.match(lines[i + 1])):
            continue
        section = []
        for j in range(i + 2, len(lines)):
            if not lines[j].strip() or _LABEL.match(lines[j]) or _is_header(lines, j):
                break
            section.append(j)
        yield i, section


def _close_paren(line: str, start: int) -> Optional[int]:
    """Index of the ``)`` matching the ``(`` at ``start``; ``None`` when it is never closed."""
    depth = 0
    for k in range(start, len(line)):
        depth += {"(": 1, ")": -1}.get(line[k], 0)
        if depth == 0:
            return k
    return None


def _item_column(line: str, indent: int) -> Optional[int]:
    """The description column of a ``name: (type) Description`` item at ``indent``; ``None`` for any other
    line."""
    head = _PARAM_ITEM.match(line)
    if head is None or len(head.group(1)) != indent:
        return None
    end = _close_paren(line, head.end() - 1)
    rest = line[end + 1:] if end is not None else ""
    if not rest.startswith(" ") or not rest.strip():
        return None
    return end + 1 + _indent(rest)


def _bad_param_lines(lines: Sequence[str], section: Sequence[int], indent: int) -> List[int]:
    """Indexes in ``section`` off the ``name: (type) Description`` shape or off the description column.

    Rules:
        an item sits at ``indent``, its description on the same line,
        a continuation line starts at the description column of the item above it,
        a line after an off-shape line has no column to continue, so it is off-shape too,
        every item is flagged when the items' descriptions start in different columns
    """
    bad: List[int] = []
    items: Dict[int, int] = {}
    column: Optional[int] = None
    for k in section:
        found = _item_column(lines[k], indent)
        if found is not None:
            items[k] = column = found
        elif column is None or _indent(lines[k]) != column:
            bad.append(k)
            column = None
    if len(set(items.values())) > 1:
        bad.extend(items)
    return sorted(bad)


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


# --- dispatch ---------------------------------------------------------------------------------------------

#: A line limit no source line reaches: scope resolution parses files and checks names, not format.
_NO_LIMIT = 1 << 30


class DispatchError(ValueError):
    """Every defect found in a dispatch request, collected before raising; ``problems`` holds one per line."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = list(problems)


_GIT_TIMEOUT_SECONDS = 30


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    """Runs git in ``root``; a missing git, a failed launch or a timed-out call returns a failed
    CompletedProcess whose stderr names the cause, with stdin closed so a child cannot stall the caller."""
    argv = ["git", "-C", str(root), *args]
    try:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, timeout=_GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr=str(exc))


def _posix(path: Path) -> str:
    return Path(path).resolve().as_posix()


def _inside(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def _tracked(root: Path, path: Path) -> bool:
    """True when git tracks ``path`` in the repository at ``root``."""
    done = _git(root, "ls-files", "--", str(path))
    return done.returncode == 0 and bool(done.stdout.strip())


def _split(token: str) -> Tuple[str, Optional[str]]:
    """``(path, name)`` for ``path::name`` (split at the last ``::``, so a drive colon survives), else
    ``(token, None)``."""
    if "::" in token:
        path, name = token.rsplit("::", 1)
        return path, name
    return token, None


def _bare(token: str) -> bool:
    """True for a token with no ``::``, separator or ``.py`` ending: a symbol unless it names a path."""
    return not ("::" in token or "/" in token or "\\" in token or token.endswith(".py"))


def _path_shaped(token: str, cwd: Path) -> bool:
    """True when ``token`` names a path: ``::``, a separator, a ``.py`` ending, or an existing file or
    directory under ``cwd``."""
    return not _bare(token) or (Path(cwd) / token).exists()


def first_path(tokens: Sequence[str], cwd: Path) -> Optional[Path]:
    """The resolved path of the first path-shaped token, ``::name`` stripped; ``None`` when there is none."""
    for token in tokens:
        if _path_shaped(token, cwd):
            return (Path(cwd) / _split(token)[0]).resolve()
    return None


def _tracked_python(root: Path, folder: Path) -> Tuple[List[Path], Optional[str]]:
    """The git-tracked ``.py`` files under ``folder``, recursively, that exist in the working tree and
    resolve inside ``root`` (a symlink leading out is skipped), and the first line of git's stderr when
    ``git ls-files`` fails (``None`` otherwise)."""
    rel = folder.relative_to(root).as_posix()
    done = _git(root, "ls-files", "-z", "--", rel)
    if done.returncode != 0:
        detail = (done.stderr or "").strip().splitlines()
        return [], f"git ls-files failed: {detail[0] if detail else f'exit {done.returncode}'}"
    names = [name for name in done.stdout.split("\0") if name.endswith(".py")]
    paths = ((root / name).resolve() for name in names)
    return [path for path in paths if path.is_file() and _inside(path, root)], None


def _token_files(root: Path, token: str, cwd: Path, problems: List[str]) -> List[Path]:
    """The files a path token reaches; a defect appends a problem and reaches nothing."""
    raw, name = _split(token)
    path = (Path(cwd) / raw).resolve()
    if not _inside(path, root):
        problems.append(f"{token}: outside the project {root.as_posix()}")
    elif not path.exists():
        problems.append(f"{token}: no such file or directory")
    elif path.is_dir():
        if name is not None:
            problems.append(f"{token}: '::' needs a file, not a folder")
            return []
        files, failure = _tracked_python(root, path)
        if failure is not None:
            problems.append(f"{token}: {failure}")
        elif not files:
            problems.append(f"{token}: no git-tracked .py files under it")
        return files
    elif path.suffix != ".py":
        problems.append(f"{token}: not a .py file")
    else:
        return [path]
    return []


def _collect(root: Path, tokens: Sequence[str], cwd: Path,
             problems: List[str]) -> Tuple[Dict[Path, List[str]], Set[Path], List[str], List[str]]:
    """Sorts tokens into narrowed files (path -> names), whole files, bare symbols and bare folder tokens."""
    narrowed: Dict[Path, List[str]] = {}
    whole: Set[Path] = set()
    symbols: List[str] = []
    folders: List[str] = []
    for token in tokens:
        if not _path_shaped(token, cwd):
            symbols.append(token)
            continue
        name = _split(token)[1]
        if _bare(token) and (Path(cwd) / token).is_dir():
            folders.append(token)
        for path in _token_files(root, token, cwd, problems):
            if name is None:
                whole.add(path)
            elif name not in narrowed.setdefault(path, []):
                narrowed[path].append(name)
    return narrowed, whole, symbols, folders


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _merge(root: Path, narrowed: Dict[Path, List[str]], whole: Set[Path], symbols: List[str],
           problems: List[str]) -> Dict[Path, List[str]]:
    """One entry per file (empty names: all); a file both whole and narrowed is a problem, and bare symbols
    narrow the one file in scope."""
    for path in sorted(whole & set(narrowed)):
        problems.append(f"{_rel(root, path)}: named whole and with '::'; name it one way")
    scopes = {path: [] for path in whole} | {path: names for path, names in narrowed.items()}
    if not symbols or (not scopes and problems):
        return scopes
    if len(scopes) != 1:
        problems.append(f"bare symbols {', '.join(symbols)} need exactly one file in scope; write "
                        "<file>::<name>")
        return scopes
    path = next(iter(scopes))
    scopes[path] = list(dict.fromkeys([*scopes[path], *symbols]))
    return scopes


def _check_names(root: Path, scopes: Dict[Path, List[str]], folders: List[str], explicit: Set[Path],
                 problems: List[str]) -> None:
    """Parses every file, checks each named symbol, and refuses a bare folder token that also names a
    function in an explicitly named file."""
    found: Set[str] = set()
    for path in sorted(scopes):
        try:
            rows = report(path, [], _NO_LIMIT)
        except (OSError, SyntaxError) as exc:
            problems.append(f"{_rel(root, path)}: does not parse ({exc})")
            continue
        missing = unmatched(rows, scopes[path])
        problems.extend(f"{_rel(root, path)}: no function named {name}" for name in missing)
        if path in explicit:
            found |= {row.qualname.rsplit(".", 1)[-1] for row in rows}
    problems.extend(f"{token}: names a folder and a function; write {token}/ for the folder or "
                    f"<file>::{token} for the function" for token in folders if token in found)


def resolve_scope(root: Path, tokens: Sequence[str], cwd: Path) -> List[FileScope]:
    """The file scopes ``tokens`` name, sorted by path; raises ``DispatchError`` listing every defect.

    Rules:
        A token is a path when it holds ``::``, a separator or a ``.py`` ending, or names an existing file
        or folder under ``cwd``; any other token is a bare symbol. A folder reaches its git-tracked ``.py``
        files. A file reached twice is one scope; the ``::`` names of one file merge.
    """
    root = Path(root).resolve()
    problems: List[str] = []
    narrowed, whole, symbols, folders = _collect(root, tokens, cwd, problems)
    explicit = {(Path(cwd) / _split(t)[0]).resolve() for t in tokens
                if _path_shaped(t, cwd) and t not in folders}
    scopes = _merge(root, narrowed, whole, symbols, problems)
    if not tokens or not (scopes or problems):
        problems.append("no file in scope")
    _check_names(root, scopes, folders, explicit, problems)
    if problems:
        raise DispatchError(problems)
    return [FileScope(path=path.as_posix(), names=scopes[path])
            for path in sorted(scopes, key=lambda p: p.as_posix())]


def plan_rows(root: Path, scopes: Sequence[FileScope], *, new_docstrings: bool,
              parallel: bool) -> List[DispatchRow]:
    """One work row over every scope, or one per scope when ``parallel``."""
    groups = [[scope] for scope in scopes] if parallel else [list(scopes)]
    return [DispatchRow(model=WORK_MODEL, project_root=_posix(root), new_docstrings=new_docstrings,
                        scopes=group) for group in groups]


def _probe_clash(root: Path, probe: Path) -> Optional[str]:
    """The problem line for a file already at ``probe``'s path, tracked or not; ``None`` when it is free.

    The driver clears recorded probes first, so a file still there belongs to the developer.
    """
    if _tracked(root, probe):
        return f"{probe.as_posix()}: git tracks a file named {PROBE_NAME} here; run without -p"
    if probe.exists():
        return f"{probe.as_posix()}: a file named {PROBE_NAME} exists here; remove it or run without -p"
    return None


def _drop(paths: Iterable[Path]) -> None:
    """Removes each of ``paths``, ignoring a file that is gone or cannot be removed."""
    for path in paths:
        try:
            path.unlink()
        except OSError:
            pass


def write_probes(root: Path, scopes: Sequence[FileScope], record: Path) -> List[Path]:
    """Writes one probe file per distinct folder of ``scopes``, in scope order, and appends each path to
    ``record``.

    Raises ``DispatchError`` before writing anything when a file of the probe's name exists in a target
    folder (tracked or not), and when a folder or the record cannot be written; the probes already written
    are then removed.
    """
    folders = dict.fromkeys(Path(scope.path).resolve().parent for scope in scopes)
    probes = [folder / PROBE_NAME for folder in folders]
    clashes = [line for line in (_probe_clash(root, probe) for probe in probes) if line is not None]
    if clashes:
        raise DispatchError(clashes)
    written: List[Path] = []
    try:
        record.parent.mkdir(parents=True, exist_ok=True)
        with record.open("a", encoding="utf-8") as handle:
            for probe in probes:
                written.append(probe)
                probe.write_text(PROBE_SOURCE, encoding="utf-8")
                handle.write(probe.as_posix() + "\n")
    except OSError as exc:
        _drop(written)
        raise DispatchError([f"cannot write probe files under {root.as_posix()}: {exc}"]) from exc
    return probes


def probe_row(root: Path, probes: Sequence[Path]) -> DispatchRow:
    """The probe row: the probe model, new docstrings on, one ``all`` scope per probe file."""
    return DispatchRow(model=PROBE_MODEL, project_root=_posix(root), new_docstrings=True, probe=True,
                       scopes=[FileScope(path=_posix(probe)) for probe in probes])


def clear_probes(root: Path, record: Path) -> List[Path]:
    """Removes each recorded probe that sits under ``root``, carries the probe name and is untracked, then
    deletes ``record``; returns the removed paths in record order (none without a record)."""
    if not record.is_file():
        return []
    removed: List[Path] = []
    for line in record.read_text(encoding="utf-8").splitlines():
        path = Path(line.strip()) if line.strip() else None
        if (path is None or path.name != PROBE_NAME or not _inside(path, root) or not path.is_file()
                or _tracked(root, path)):
            continue
        path.unlink()
        removed.append(path)
    record.unlink()
    return removed
