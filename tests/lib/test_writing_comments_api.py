"""The writing-comments section API: divider recognition, flags and the canonical divider lines.

Each test hands ``writing_comments_api.sections`` a source text and a divider width and reads the report;
the expected lines are built by hand from the convention (a rule is ``# `` plus dashes to the width, a minor
divider is ``# -- <title> `` plus dashes to the width, indentation counted).
"""
from __future__ import annotations

import pytest

from harness_lib.writing_comments_api import minor_line, report_lines, rule_line, sections
from harness_lib.writing_comments_models import CommentFlag, Divider, DividerLevel, FlagKind

RULE_88 = "# " + "-" * 86
MINOR_ROW_HELPERS_88 = "# -- row helpers " + "-" * 71


def test_major_banner_is_one_divider_at_its_first_rule() -> None:
    source = f"import os\n\n{RULE_88}\n# Immutable ranking\n{RULE_88}\n\nx = 1\n"
    report = sections(source, 88)
    assert report.dividers == [Divider(line=3, level=DividerLevel.MAJOR, title="Immutable ranking")]
    assert report.flags == []


def test_a_banner_may_carry_lines_below_its_title() -> None:
    source = f"{RULE_88}\n# dev_commit hardening\n#  * legacy: freetext rows\n{RULE_88}\n"
    report = sections(source, 88)
    assert report.dividers == [Divider(line=1, level=DividerLevel.MAJOR, title="dev_commit hardening")]
    assert report.flags == []


def test_a_rule_and_title_without_a_closing_rule_is_a_banner_flag() -> None:
    report = sections(f"{RULE_88}\n# Branch scope\n\n\ndef f():\n    return 1\n", 88)
    assert report.dividers == []
    assert report.flags == [CommentFlag(line=1, kind=FlagKind.BANNER, text=RULE_88)]


def test_minor_divider_carries_its_title() -> None:
    report = sections(f"{MINOR_ROW_HELPERS_88}\ndef f():\n    return 1\n", 88)
    assert report.dividers == [Divider(line=1, level=DividerLevel.MINOR, title="row helpers")]
    assert report.flags == []


def test_a_divider_short_of_the_width_is_kept_and_flagged() -> None:
    short = "# -- row helpers " + "-" * 69
    report = sections(f"{short}\n", 88)
    assert report.dividers == [Divider(line=1, level=DividerLevel.MINOR, title="row helpers")]
    assert report.flags == [CommentFlag(line=1, kind=FlagKind.WIDTH, text=short)]


def test_a_banner_rule_past_the_width_is_flagged_on_its_own_line() -> None:
    long_rule = "# " + "-" * 90
    source = f"{RULE_88}\n# Core attribution logic\n{long_rule}\n"
    report = sections(source, 88)
    assert report.dividers == [Divider(line=1, level=DividerLevel.MAJOR, title="Core attribution logic")]
    assert report.flags == [CommentFlag(line=3, kind=FlagKind.WIDTH, text=long_rule)]


def test_hash_and_equals_banner_is_a_style_flag() -> None:
    line = "### ======= PROCESSING CLASSES ============ ###"
    report = sections(f"{line}\n", 88)
    assert report.dividers == []
    assert report.flags == [CommentFlag(line=1, kind=FlagKind.STYLE, text=line)]


def test_title_after_the_dash_run_is_a_style_flag() -> None:
    line = "# " + "-" * 64 + " scaffold"
    report = sections(f"{line}\n", 88)
    assert report.dividers == []
    assert report.flags == [CommentFlag(line=1, kind=FlagKind.STYLE, text=line)]


def test_a_rule_without_a_title_and_closing_rule_is_a_banner_flag() -> None:
    report = sections(f"{RULE_88}\nx = 1\n", 88)
    assert report.dividers == []
    assert report.flags == [CommentFlag(line=1, kind=FlagKind.BANNER, text=RULE_88)]


def test_double_dash_inside_prose_is_not_a_divider() -> None:
    source = (
        "def f(method):\n"
        "    # An explicit method wins over tier selection -- only AUTO defers to the tiers.\n"
        "    return method\n"
    )
    report = sections(source, 88)
    assert report.dividers == []
    assert report.flags == []


def test_indentation_counts_toward_the_width() -> None:
    line = "    # -- helpers " + "-" * 71
    source = f"class C:\n{line}\n    def f(self):\n        return 1\n"
    report = sections(source, 88)
    assert report.dividers == [Divider(line=2, level=DividerLevel.MINOR, title="helpers")]
    assert report.flags == []


def test_dashed_underlines_inside_a_docstring_are_not_comments() -> None:
    source = (
        "def f(x):\n"
        '    """Return x.\n'
        "\n"
        "    Parameters\n"
        "    ----------\n"
        "    x\n"
        "        The value.\n"
        '    """\n'
        "    return x\n"
    )
    report = sections(source, 88)
    assert report.dividers == []
    assert report.flags == []


def test_a_trailing_comment_after_code_is_never_a_divider() -> None:
    report = sections("x = 1  # ----------------\n", 88)
    assert report.dividers == []
    assert report.flags == []


def test_unparsable_source_raises_value_error() -> None:
    with pytest.raises(ValueError):
        sections('x = """never closed\n', 88)


def test_canonical_lines_fill_the_width_exactly() -> None:
    assert rule_line("", 88) == RULE_88
    assert minor_line("row helpers", "", 88) == MINOR_ROW_HELPERS_88
    assert minor_line("helpers", "    ", 88) == "    # -- helpers " + "-" * 71


def test_report_lines_list_dividers_and_flags_in_line_order() -> None:
    style = "### ===== OLD ===== ###"
    source = f"{RULE_88}\n# Ranking\n{RULE_88}\n{style}\n{MINOR_ROW_HELPERS_88}\n"
    assert report_lines("src/mod.py", sections(source, 88)) == [
        "src/mod.py:1: major Ranking",
        f"src/mod.py:4: flag style: {style}",
        "src/mod.py:5: minor row helpers",
    ]


def test_report_lines_name_a_file_without_dividers() -> None:
    assert report_lines("src/a.py", sections("x = 1\n", 88)) == ["src/a.py: no dividers"]
