"""The writing-comments section API: divider recognition, flags and the canonical lines a width flag offers.

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
    assert report.flags == [CommentFlag(line=1, kind=FlagKind.WIDTH, text=short, fix=MINOR_ROW_HELPERS_88)]


@pytest.mark.parametrize("short", ["# -- writers ---", "# -- writers --", "# -- writers -"])
def test_a_minor_with_a_short_dash_run_is_a_divider_with_a_width_flag(short: str) -> None:
    report = sections(f"{short}\nx = 1\n", 88)
    assert report.dividers == [Divider(line=1, level=DividerLevel.MINOR, title="writers")]
    assert report.flags == [
        CommentFlag(line=1, kind=FlagKind.WIDTH, text=short, fix="# -- writers " + "-" * 75),
    ]


def test_a_minor_opening_without_a_dash_run_is_a_style_flag() -> None:
    report = sections("# -- helpers\nx = 1\n", 88)
    assert report.dividers == []
    assert report.flags == [CommentFlag(line=1, kind=FlagKind.STYLE, text="# -- helpers")]


def test_an_indented_width_flag_fix_fills_the_width_at_its_indentation() -> None:
    short = "# -- helpers --"
    report = sections(f"class C:\n    {short}\n    x = 1\n", 88)
    assert report.flags == [
        CommentFlag(line=2, kind=FlagKind.WIDTH, text=short, fix="# -- helpers " + "-" * 71),
    ]


def test_a_banner_rule_past_the_width_is_flagged_on_its_own_line() -> None:
    long_rule = "# " + "-" * 90
    source = f"{RULE_88}\n# Core attribution logic\n{long_rule}\n"
    report = sections(source, 88)
    assert report.dividers == [Divider(line=1, level=DividerLevel.MAJOR, title="Core attribution logic")]
    assert report.flags == [CommentFlag(line=3, kind=FlagKind.WIDTH, text=long_rule, fix=RULE_88)]


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


def test_a_banner_title_at_another_indentation_is_a_banner_flag() -> None:
    report = sections(f"{RULE_88}\n    # Title\n{RULE_88}\n", 88)
    assert report.dividers == []
    assert report.flags == [
        CommentFlag(line=1, kind=FlagKind.BANNER, text=RULE_88),
        CommentFlag(line=3, kind=FlagKind.BANNER, text=RULE_88),
    ]


def test_a_rule_titled_by_another_rule_is_a_banner_flag() -> None:
    report = sections(f"{RULE_88}\n{RULE_88}\n", 88)
    assert report.dividers == []
    assert report.flags == [
        CommentFlag(line=1, kind=FlagKind.BANNER, text=RULE_88),
        CommentFlag(line=2, kind=FlagKind.BANNER, text=RULE_88),
    ]


def test_an_empty_hash_title_is_a_banner_flag() -> None:
    report = sections(f"{RULE_88}\n#\n{RULE_88}\n", 88)
    assert report.dividers == []
    assert report.flags == [
        CommentFlag(line=1, kind=FlagKind.BANNER, text=RULE_88),
        CommentFlag(line=3, kind=FlagKind.BANNER, text=RULE_88),
    ]


def test_a_major_opening_rule_past_the_width_is_flagged_on_its_own_line() -> None:
    short_rule = "# " + "-" * 82
    report = sections(f"{short_rule}\n# T\n{RULE_88}\n", 88)
    assert report.dividers == [Divider(line=1, level=DividerLevel.MAJOR, title="T")]
    assert report.flags == [CommentFlag(line=1, kind=FlagKind.WIDTH, text=short_rule, fix=RULE_88)]


def test_an_indented_flagged_comment_loses_its_indentation_in_the_flag_text() -> None:
    report = sections("class C:\n    ### ===== X ===== ###\n    pass\n", 88)
    assert report.flags == [CommentFlag(line=2, kind=FlagKind.STYLE, text="### ===== X ===== ###")]


def test_a_leading_byte_order_mark_does_not_hide_a_banner_on_line_one() -> None:
    report = sections(f"\ufeff{RULE_88}\n# Title\n{RULE_88}\n", 88)
    assert report.dividers == [Divider(line=1, level=DividerLevel.MAJOR, title="Title")]
    assert report.flags == []


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


def test_report_lines_put_a_divider_before_a_flag_on_the_same_line() -> None:
    short = "# -- row helpers " + "-" * 69
    assert report_lines("src/mod.py", sections(f"{short}\n", 88)) == [
        "src/mod.py:1: minor row helpers",
        f"src/mod.py:1: flag width: {short} -> {MINOR_ROW_HELPERS_88}",
    ]


def test_report_lines_name_a_file_without_dividers() -> None:
    assert report_lines("src/a.py", sections("x = 1\n", 88)) == ["src/a.py: no dividers"]
