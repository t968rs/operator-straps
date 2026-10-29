"""Bubble memos are point-in-time snapshots: the default exclusions skip ``*_Bubbles.md`` in any folder."""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Callable, Sequence

from harness_lib.config import load_config
from harness_lib.default_exclusions import (
    DEFAULT_EXCLUSIONS,
    default_patterns,
    ensure_default_exclusions,
    with_harness_patterns,
)
from harness_lib.git_status_filter_excluded import load_exclusions

_MakeProject = Callable[..., Path]
PATTERN = "*_Bubbles.md"


def _hit(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def test_default_patterns_carry_the_memo_pattern(make_project: _MakeProject) -> None:
    cfg = load_config(make_project(config={}))
    assert PATTERN in default_patterns(cfg)


def test_the_pattern_matches_a_memo_in_any_folder(make_project: _MakeProject) -> None:
    cfg = load_config(make_project(config={"artifacts": {"reviews": "ci/reviews"}}))
    patterns = default_patterns(cfg)
    assert _hit("notes/decisions/PR_9_Bubbles.md", patterns)
    assert _hit("ci/reviews/PR_1514_Bubbles.md", patterns)


def test_a_seeded_file_holds_the_pattern(make_project: _MakeProject) -> None:
    root = make_project(config={})
    ensure_default_exclusions(load_config(root))
    assert PATTERN in load_exclusions(root / DEFAULT_EXCLUSIONS)


def test_an_older_seeded_list_gains_it_in_memory(make_project: _MakeProject) -> None:
    root = make_project(config={}, files={DEFAULT_EXCLUSIONS: {"exclusions": [{"pattern": "only/this/*"}]}})
    merged = with_harness_patterns(load_config(root), ["only/this/*"])
    assert merged[0] == "only/this/*"
    assert PATTERN in merged


def test_other_markdown_stays_reviewable(make_project: _MakeProject) -> None:
    cfg = load_config(make_project(config={}))
    patterns = default_patterns(cfg)
    for name in ("docs/Bubbles.md", "docs/guide_Bubbles.txt", "docs/PR_1_Bubbles.md.bak", "docs/guide.md"):
        assert not _hit(name, patterns), name
