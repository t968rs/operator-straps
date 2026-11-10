"""Tier analysis of the writing-docstrings skill: fork counts, tier suggestions, layouts and format flags.

Every case parses a synthetic function source; nothing reads a project file.
"""
from __future__ import annotations

import ast
from typing import List

import pytest

from harness_lib import writing_docstrings_api as api
from harness_lib.writing_docstrings_models import FLAG_NAMES, Layout, Tier, suggest_tier


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


_NOT_GUARD = '''def f():
    global _C
    if not _C:
        _C = load()
    return _C
'''


@pytest.mark.parametrize("source, forks", [
    ("def f(x):\n    return a if x else b\n", 1),
    ("def f(x):\n    assert x\n    return x\n", 1),
    (_NOT_GUARD, 0),
    (_NOT_GUARD.replace("    return _C\n", "    else:\n        _C = None\n    return _C\n"), 1),
    ("def f(ok):\n    if not ok:\n        sys.exit(1)\n    return ok\n", 1),
    ("def f(ok):\n    status = None\n    if not ok:\n        status = 'failed'\n    return status\n", 1),
    ("def f(x):\n    if x is None:\n        log(x)\n    return x\n", 1),
], ids=["ifexp", "assert", "not-guard", "guard-with-else", "guard-calls", "guard-fills-other-name",
        "is-none-guard-calls"])
def test_fork_kinds_and_guard_forms(source: str, forks: int) -> None:
    assert api.count_forks(_func(source)) == forks


@pytest.mark.parametrize("source, forks", [
    ("def f(p):\n    with open(p) as fh:\n        return fh.read()\n", 0),
    ("def f(c):\n    if c:\n        return 1\n    else:\n        return 2\n", 1),
    ("def f(k):\n    try:\n        return a(k)\n    except KeyError:\n        return None\n", 1),
    ("def f(c):\n    if c:\n        return 1\n    return 2\n", 2),
], ids=["with-tail", "if-else-tail", "try-except-tail", "early-return"])
def test_a_return_that_ends_the_function_is_not_a_fork(source: str, forks: int) -> None:
    assert api.count_forks(_func(source)) == forks


def test_each_match_case_is_a_fork() -> None:
    source = ("def f(x):\n    match x:\n        case 1:\n            return 'a'\n"
              "        case _:\n            return 'b'\n")
    assert api.count_forks(_func(source)) == 2


def test_decorator_and_default_conditionals_are_not_forks() -> None:
    source = "@wrap(a if c else b)\ndef f(x=a if c else b) -> (a if c else b):\n    return x\n"
    assert api.count_forks(ast.parse(source).body[0]) == 0


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
        x: (int)                            The value.
        name: (Optional[str], default None) The label, when one is given (its
                                            casing kept).

    Returns:
    --------
    int: ``x``.

    Example:
    --------
        f(1)
    """
    return x
'''

#: The docstring of issue 246: numpy-style items, the description on the line below each name.
_NUMPY_PARAMS = '''def rasterize(vector_path, output_file, target_crs):
    """
         Rasterize a polygon.
         Parameters
         ----------
         vector_path: list or str
         Path(s) to the input file(s).
         output_file: str
         Path to the output file.
         target_crs: str or int
         Target coordinate system (EPSG code or WKT).
    """
    return output_file
'''

_UNALIGNED_PARAMS = '''def f(vector_path, out):
    """
    Writes a raster.

    Parameters:
    -----------
        vector_path: (list or str) Path(s) to the input file(s).
        out: (str) Path to the output file.
    """
    return out
'''

_ALIGNED_PARAMS = '''def f(vector_path, out, target_crs):
    """
    Writes a raster.

    Parameters:
    -----------
        vector_path: (list or str)     Path(s) to the input file(s).
        out: (str)                     Path to the output file.
        target_crs: (str or int)       Target coordinate system (EPSG code or WKT).
                                       Without one, the snap spec's reference gives it.
    """
    return out
'''

_OFF_COLUMN = '''def f(out, target_crs):
    """
    Writes a raster.

    Parameters:
    -----------
        out: (str)                Path to the output file.
        target_crs: (str or int)  Target coordinate system.
            Without one, the snap spec's reference gives it.
    """
    return out
'''

_SHORT_UNDERLINE = '''def f(out):
    """
    Writes a raster.

    Parameters:
    ----------
        out: (str) Path to the output file.
    """
    return out
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


def test_numpy_style_parameter_items_are_flagged_by_line() -> None:
    flags = _flags(_NUMPY_PARAMS)
    assert "param-format=[6, 7, 8, 9, 10, 11]" in flags
    assert "separator-line" in flags


def test_parameter_descriptions_in_different_columns_are_flagged() -> None:
    assert _flags(_UNALIGNED_PARAMS) == ["param-format=[7, 8]"]


def test_aligned_parameter_items_and_continuations_have_no_flags() -> None:
    assert _flags(_ALIGNED_PARAMS) == []


def test_a_continuation_off_the_description_column_is_flagged() -> None:
    assert _flags(_OFF_COLUMN) == ["param-format=[9]"]


def test_an_underline_narrower_than_its_label_is_flagged() -> None:
    assert _flags(_SHORT_UNDERLINE) == ["underline-width=[6]"]


def test_a_parameter_type_with_nested_parentheses_and_a_parenthesized_description() -> None:
    source = ('def f(x):\n    """\n    Sets it.\n\n    Parameters:\n    -----------\n'
              '        x: (Tuple[int, int] (pair)) The value (in m) then more.\n    """\n    return x\n')
    assert _flags(source) == []


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


def test_a_short_third_person_brief_is_not_a_placeholder() -> None:
    assert _layout('def f():\n    """Closes the pool."""\n') == Layout.BRIEF
    assert _layout('def f():\n    """Get desc."""\n') == Layout.PLACEHOLDER


def test_a_two_line_summary_is_prose_not_brief() -> None:
    source = ('def f():\n    """Opens the file named by the caller.\n'
              '    Reads every row of it into a list.\n    """\n')
    assert _layout(source) == Layout.PROSE


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


_SINGLE_TICK = 'def f():\n    """Returns `x`."""\n'

_OUT_OF_ORDER = '''def f(x):
    """Sets a flag.

    Returns:
        ``x``
    Rules:
        fails when missing
    """
    return x
'''


def test_single_backticks_are_flagged() -> None:
    assert "single-backticks" in _flags(_SINGLE_TICK)


def test_compact_labels_out_of_order_are_flagged() -> None:
    assert "section-order" in _flags(_OUT_OF_ORDER)


def test_the_emitted_flags_are_exactly_the_listed_flag_names() -> None:
    fixtures = (_MISALIGNED, _ALIGNED, _FULL, _ARGS, _SINGLE_TICK, _OUT_OF_ORDER, _NUMPY_PARAMS,
                _SHORT_UNDERLINE,
                'def f():\n    """I2: keeps the order stable."""\n',
                'def f():\n    """Sets a flag.\n\n    ======\n    """\n', 'def f():\n    """ """\n')
    names = {flag.split("=", 1)[0] for source in fixtures for flag in _flags(source, max_line=20)}
    assert names == set(FLAG_NAMES)


def test_report_filters_by_name_or_qualname(tmp_path) -> None:
    path = tmp_path / "m.py"
    source = "class A:\n    def run(self):\n        return 1\n\ndef run():\n    return 2\n"
    path.write_text(source, encoding="utf-8")
    assert [row.qualname for row in api.report(path, ["run"], 110)] == ["A.run", "run"]
    assert [row.qualname for row in api.report(path, ["A.run"], 110)] == ["A.run"]


def test_report_finds_functions_under_compound_statements(tmp_path) -> None:
    path = tmp_path / "m.py"
    source = ("if TYPE_CHECKING:\n    def typed():\n        return 1\n"
              "try:\n    import fast\nexcept ImportError:\n    def fallback():\n        return 2\n"
              "class A:\n    if True:\n        def run(self):\n"
              "            def inner():\n                return 3\n            return inner\n")
    path.write_text(source, encoding="utf-8")
    assert [row.qualname for row in api.report(path, [], 110)] == ["typed", "fallback", "A.run"]


def test_report_raises_syntax_error_for_non_utf8_source(tmp_path) -> None:
    path = tmp_path / "m.py"
    path.write_bytes("def f():\n    return 'caf\u00e9'\n".encode("latin-1"))
    with pytest.raises(SyntaxError) as info:
        api.report(path, [], 110)
    assert info.value.lineno == 2


def test_report_raises_syntax_error_for_a_null_byte(tmp_path) -> None:
    path = tmp_path / "m.py"
    path.write_bytes(b"def f():\n    return 1\x00\n")
    with pytest.raises(SyntaxError):
        api.report(path, [], 110)
