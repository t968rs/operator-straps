"""Tier analysis of the writing-docstrings skill: fork counts, tier suggestions, layouts and format flags.

Every case parses a synthetic function source; nothing reads a project file.
"""
from __future__ import annotations

import ast
from typing import List

from harness_lib import writing_docstrings_api as api
from harness_lib.writing_docstrings_models import Layout, Tier, suggest_tier


def _func(source: str) -> ast.AST:
    """The first function of ``source``."""
    return ast.parse(source).body[0]


def _flags(source: str, max_line: int = 110) -> List[str]:
    """The flags of the first function in ``source``."""
    return api.docstring_flags(_func(source), source.splitlines(keepends=True), max_line)


def _layout(source: str) -> Layout:
    return api.current_layout(ast.get_docstring(_func(source)))


# --- forks and tiers --------------------------------------------------------------------------------------

_LAZY = '''def settings():
    global _CACHE
    if _CACHE is None:
        _CACHE = load()
    return _CACHE
'''

_EARLY_RETURN = '''def pick(xs):
    for x in xs:
        if x:
            return x
    return None
'''

_FILTER = '''def evens(xs):
    return [x for x in xs if x % 2 == 0]
'''

_NESTED = '''def outer(x):
    def inner(y):
        if y:
            raise ValueError(y)
        return y
    return inner(x)
'''


def test_lazy_guard_is_not_a_fork() -> None:
    assert api.count_forks(_func(_LAZY)) == 0


def test_early_return_is_a_fork_and_the_last_return_is_not() -> None:
    assert api.count_forks(_func(_EARLY_RETURN)) == 2


def test_comprehension_filter_is_not_a_fork() -> None:
    assert api.count_forks(_func(_FILTER)) == 0


def test_nested_function_forks_are_not_counted() -> None:
    assert api.count_forks(_func(_NESTED)) == 0


def test_suggest_full_needs_length_and_two_forks() -> None:
    assert suggest_tier(10, 0) == Tier.BRIEF
    assert suggest_tier(80, 1) == Tier.COMPACT
    assert suggest_tier(50, 3) == Tier.COMPACT
    assert suggest_tier(51, 2) == Tier.FULL


# --- layouts and flags ------------------------------------------------------------------------------------

_MISALIGNED = '''def f(x):
    """Sets a flag.
 Logic:
 - fails when missing
    """
    return x
'''

_ALIGNED = '''def f(x):
    """Sets a flag.

    Rules:
        fails when missing
    Returns:
        ``x``
    """
    return x
'''

_FULL = '''def f(x):
    """
    Sets a flag.

    Parameters:
    -----------
    x : int
        The value.

    Returns:
    --------
    int
        ``x``

    Example:
    --------
    >>> f(1)
    """
    return x
'''

_ARGS = '''def f(x):
    """Sets a flag.

    Args:
        x: the value
    Returns:
        ``x``
    """
    return x
'''


def test_a_line_indented_left_of_the_opening_quotes_is_misaligned() -> None:
    assert "misaligned" in _flags(_MISALIGNED)


def test_an_aligned_compact_docstring_has_no_flags() -> None:
    assert _flags(_ALIGNED) == []


def test_the_full_layout_labels_are_known() -> None:
    assert _flags(_FULL) == []


def test_a_label_outside_the_convention_is_flagged() -> None:
    assert "unknown-label=Args" in _flags(_ARGS)


def test_a_misaligned_label_outside_the_convention_gets_both_flags() -> None:
    flags = _flags(_MISALIGNED)
    assert "misaligned" in flags
    assert "unknown-label=Logic" in flags


def test_current_layout_names_each_layout() -> None:
    assert _layout("def f():\n    return 1\n") == Layout.NONE
    assert _layout('def f():\n    """---"""\n') == Layout.BLANK
    assert _layout(_FULL) == Layout.FULL
    assert _layout(_ALIGNED) == Layout.COMPACT
    assert _layout('def f():\n    """Push."""\n') == Layout.PLACEHOLDER
    assert _layout('def f():\n    """Returns the ``x`` value of the cached record."""\n') == Layout.BRIEF
    prose = '"""Opens it.\n\n    It then reads the rows.\n    It closes the file at the end.\n    """'
    assert _layout(f"def f():\n    {prose}\n") == Layout.PROSE


def test_long_lines_follow_the_given_limit() -> None:
    source = 'def f():\n    """Returns the value of the cached record for the key."""\n'
    assert _flags(source, max_line=40) == ["long-lines=[2]"]
    assert _flags(source, max_line=110) == []


def test_crlf_line_endings_do_not_count_toward_length() -> None:
    line = '    """' + "x" * 32 + '"""'
    source = f"def f():\r\n{line}\r\n"
    assert len(line) == 42
    assert _flags(source, max_line=42) == []


def test_citation_is_flagged() -> None:
    source = 'def f():\n    """I2: keeps the order stable."""\n'
    assert "citation" in _flags(source)


def test_separator_line_outside_a_full_underline_is_flagged() -> None:
    source = 'def f():\n    """Sets a flag.\n\n    ======\n    """\n'
    assert "separator-line" in _flags(source)


def test_blank_docstring_is_flagged() -> None:
    assert "blank" in _flags('def f():\n    """ """\n')


def test_report_filters_by_name_or_qualname(tmp_path) -> None:
    path = tmp_path / "m.py"
    source = "class A:\n    def run(self):\n        return 1\n\ndef run():\n    return 2\n"
    path.write_text(source, encoding="utf-8")
    assert [row.qualname for row in api.report(path, ["run"], 110)] == ["A.run", "run"]
    assert [row.qualname for row in api.report(path, ["A.run"], 110)] == ["A.run"]
