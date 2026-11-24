"""Section dividers of a Python module: recognition, flags and the canonical lines.

A rule is ``# `` followed by dashes only. A major divider is a rule, a title comment, any further comment
lines, then a closing rule, all at one indentation; a minor divider is ``# -- <title> ----``. Each rule and
minor line fills the divider width exactly, indentation included; a ``width`` flag carries the canonical line
to paste in its place. Only full-line comments count, read through ``tokenize``, so a dashed docstring
underline or a trailing comment after code is never a divider.
"""
from __future__ import annotations

import io
import re
import tokenize
from typing import Dict, List, Optional, Tuple

from harness_lib.writing_comments_models import CommentFlag, Divider, DividerLevel, FlagKind, SectionReport

_RULE = re.compile(r"# -{4,}")
_MINOR = re.compile(r"# -- (?P<title>[^\s-].*?) -+")
# A comment opening like a minor divider but with no closing dash run, such as ``# -- helpers``.
_MINOR_START = re.compile(r"# -- [^\s-]")
_SEPARATOR_RUN = re.compile(r"[-=*~_#]{4,}")

# Line number -> (column, comment text) of every comment that stands alone on its line.
Comments = Dict[int, Tuple[int, str]]


def rule_line(indent: str, width: int) -> str:
    """The canonical rule at ``indent``: ``# `` and dashes to ``width``."""
    return f"{indent}# " + "-" * max(4, width - len(indent) - 2)


def minor_line(title: str, indent: str, width: int) -> str:
    """The canonical minor divider for ``title`` at ``indent``, padded with dashes to ``width``."""
    head = f"{indent}# -- {title} "
    return head + "-" * max(4, width - len(head))


def _full_line_comments(source: str) -> Comments:
    """Every full-line comment; raises ``ValueError`` when the source does not tokenize."""
    found: Comments = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT and not tok.line[:tok.start[1]].strip():
                found[tok.start[0]] = (tok.start[1], tok.string.rstrip())
    except (tokenize.TokenError, SyntaxError) as exc:
        raise ValueError(f"source does not tokenize: {exc}") from exc
    return found


def _banner_end(comments: Comments, start: int) -> Optional[int]:
    """The closing rule's line of a banner opened by the rule at ``start``, or None when the banner is
    incomplete (no title, a gap or an indentation change before the closing rule)."""
    col = comments[start][0]
    title = comments.get(start + 1)
    if title is None or title[0] != col or _RULE.fullmatch(title[1]) or not title[1][1:].strip():
        return None
    line = start + 2
    while line in comments and comments[line][0] == col:
        if _RULE.fullmatch(comments[line][1]):
            return line
        line += 1
    return None


class _Scan:
    """Accumulates the dividers and flags of one source text."""

    def __init__(self, comments: Comments, width: int) -> None:
        self.comments = comments
        self.width = width
        self.dividers: List[Divider] = []
        self.flags: List[CommentFlag] = []

    def flag(self, line: int, kind: FlagKind) -> None:
        self.flags.append(CommentFlag(line=line, kind=kind, text=self.comments[line][1]))

    def check_width(self, line: int, title: Optional[str] = None) -> None:
        """Flag the rule (``title`` None) or minor line at ``line`` when it misses the width, with the
        canonical line at its indentation as the fix."""
        col, text = self.comments[line]
        if col + len(text) == self.width:
            return
        room = self.width - col
        fix = rule_line("", room) if title is None else minor_line(title, "", room)
        self.flags.append(CommentFlag(line=line, kind=FlagKind.WIDTH, text=text, fix=fix))

    def rule(self, line: int) -> int:
        """Handle the rule at ``line``; returns the last line it consumed."""
        end = _banner_end(self.comments, line)
        if end is None:
            self.flag(line, FlagKind.BANNER)
            return line
        title = self.comments[line + 1][1][1:].strip()
        self.dividers.append(Divider(line=line, level=DividerLevel.MAJOR, title=title))
        self.check_width(line)
        self.check_width(end)
        return end

    def other(self, line: int) -> None:
        """Handle a comment that is not a rule: a minor divider, a style flag or plain prose."""
        text = self.comments[line][1]
        minor = _MINOR.fullmatch(text)
        if minor:
            self.dividers.append(Divider(line=line, level=DividerLevel.MINOR, title=minor["title"]))
            self.check_width(line, minor["title"])
        elif _MINOR_START.match(text) or _SEPARATOR_RUN.search(text):
            self.flag(line, FlagKind.STYLE)


def sections(source: str, width: int) -> SectionReport:
    """The dividers and flags of ``source`` at divider width ``width``; raises ``ValueError`` when the source
    does not tokenize."""
    scan = _Scan(_full_line_comments(source.removeprefix("﻿")), width)
    consumed = 0
    for line in sorted(scan.comments):
        if line <= consumed:
            continue
        if _RULE.fullmatch(scan.comments[line][1]):
            consumed = scan.rule(line)
        else:
            scan.other(line)
    return SectionReport(dividers=scan.dividers, flags=sorted(scan.flags, key=lambda f: f.line))


def _flag_line(label: str, flag: CommentFlag) -> str:
    """One flag's report line, with `` -> <fix>`` when the flag carries a canonical replacement."""
    line = f"{label}:{flag.line}: flag {flag.kind.value}: {flag.text}"
    return f"{line} -> {flag.fix}" if flag.fix else line


def report_lines(label: str, report: SectionReport) -> List[str]:
    """``<label>:<n>: major|minor <title>`` and ``<label>:<n>: flag <kind>: <text>`` in line order (a divider
    before a flag on its own line), a ``width`` flag ending `` -> <canonical line>``, or
    ``<label>: no dividers`` for a report with neither."""
    rows = [(d.line, 0, f"{label}:{d.line}: {d.level.value} {d.title}") for d in report.dividers]
    rows += [(f.line, 1, _flag_line(label, f)) for f in report.flags]
    if not rows:
        return [f"{label}: no dividers"]
    return [text for _, _, text in sorted(rows)]
