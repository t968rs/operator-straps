"""Key, range and label parsing for the review-local skill (``harness_lib.review_local_models``).

A run key is either a PR number or ``local-<label>``; every run-state path, file name and sentinel name is
built from it, so an unsafe key must never parse.
"""
from __future__ import annotations

import pytest

from harness_lib.review_local_models import (
    LABEL_MAX,
    LocalRange,
    branch_label,
    is_local_key,
    parse_key,
    parse_range,
    review_file_name,
)


def test_parse_key_accepts_a_pr_number_and_a_local_key() -> None:
    assert parse_key("1170") == 1170
    assert parse_key(42) == 42
    assert parse_key("local-1110-bubbles") == "local-1110-bubbles"
    assert is_local_key("local-a") and not is_local_key(1170) and not is_local_key("1170")
    assert review_file_name("local-1110-bubbles", "Fix_bubbles") == "LOCAL_1110-bubbles_Fix_bubbles.json"


@pytest.mark.parametrize("value", ["", "0", "-3", "local-", "local-Upper", "local-a_b", "local-a/b",
                                   "local--a", "local-a-", "feature-x", "local-" + "a" * (LABEL_MAX + 1)])
def test_parse_key_refuses_an_unsafe_key(value: str) -> None:
    with pytest.raises(ValueError):
        parse_key(value)


def test_parse_range_needs_two_dots_and_both_ends() -> None:
    assert parse_range("main..HEAD") == LocalRange(base="main", head="HEAD")
    assert parse_range("origin/dev..feature/x") == LocalRange(base="origin/dev", head="feature/x")
    for bad in ("main", "main...HEAD", "..HEAD", "main..", "a..b..c", "main ..HEAD", "-x..HEAD", "main..--y"):
        with pytest.raises(ValueError):
            parse_range(bad)


def test_branch_label_slugs_a_branch_name() -> None:
    sha = "0123456789abcdef0123456789abcdef01234567"
    assert branch_label("1110-bubbles", sha) == "1110-bubbles"
    assert branch_label("Feature/Local_Review", sha) == "feature-local-review"
    assert branch_label(None, sha) == "head-0123456"
    assert branch_label("___", sha) == "head-0123456"
    long = branch_label("x" * 100, sha)
    assert len(long) <= LABEL_MAX and parse_key("local-" + long)
