"""Behavioral tests for harness_lib.diff_delta: the filtered and full deltas, the machine-generated rule, the
project pattern lookup, the payload shape and the two-ref git read.

Every test builds a throwaway project with ``make_project`` and activates its configuration, so the
machine-generated rule never reads the checkout the suite runs from.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from conftest import git
from harness_lib import review_plan as rp
from harness_lib.commit_diff import DiffStat
from harness_lib.config import activate, active, load_config
from harness_lib.default_exclusions import harness_patterns
from harness_lib.diff_delta import (
    DeltaError,
    DiffDelta,
    active_patterns,
    between,
    delta_payload,
    from_patterns,
    from_stats,
    is_machine_generated,
    project_patterns,
)

_STATS = (
    DiffStat("src/a.py", 3, 1),
    DiffStat("gen/report.json", 40, 0),
    DiffStat("src/b.py", 0, 2),
)
_EXCLUSIONS = {"exclusions": [{"pattern": "gen/*", "reason": "generated report"}]}


def _activate(make_project: Callable[..., Path], **kwargs: object) -> Path:
    root = make_project(**kwargs)
    activate(load_config(root))
    return root


def test_from_stats_splits_source_and_full() -> None:
    delta = from_stats(_STATS, lambda path: path.startswith("gen/"))
    assert (delta.adds, delta.subs, delta.files, delta.excluded) == (3, 3, 2, ("gen/report.json",))
    assert delta.net == 0
    assert delta.full is not None
    assert (delta.full.adds, delta.full.subs, delta.full.files, delta.full.excluded) == (43, 3, 3, ())
    assert delta.full.net == 40
    assert delta.full.full is None


def test_nothing_excluded_keeps_equal_counts() -> None:
    delta = from_stats([DiffStat("a.py", 1, 5)], lambda path: False)
    assert (delta.adds, delta.subs, delta.files, delta.net) == (1, 5, 1, -4)
    assert delta.full == DiffDelta(1, 5, 1)


def test_excluded_paths_are_sorted() -> None:
    stats = [DiffStat("gen/z.json", 1, 0), DiffStat("gen/a.json", 1, 0), DiffStat("src/m.py", 1, 0)]
    assert from_stats(stats, lambda path: path.startswith("gen/")).excluded == ("gen/a.json", "gen/z.json")


def test_delta_is_frozen() -> None:
    delta = DiffDelta(1, 2, 3)
    with pytest.raises(AttributeError):
        delta.adds = 5  # type: ignore[misc]


def test_machine_generated_by_pattern_or_artifact_bucket(make_project: Callable[..., Path]) -> None:
    _activate(make_project)
    assert is_machine_generated("docs/PR_REVIEWS/0001_x.json", ())
    assert is_machine_generated("gen/out.json", ("gen/*",))
    assert not is_machine_generated("src/a.py", ("gen/*",))


def test_review_plan_is_excluded_matches_the_shared_rule(make_project: Callable[..., Path]) -> None:
    _activate(make_project)
    probes = ("docs/PR_REVIEWS/0001_x.json", "gen/out.json", "src/a.py", "docs/PR_SUMMARIES/1.md")
    for path in probes:
        assert rp.is_excluded(path, ("gen/*",)) == is_machine_generated(path, ("gen/*",))


def test_from_patterns_uses_the_shared_rule(make_project: Callable[..., Path]) -> None:
    _activate(make_project)
    delta = from_patterns(_STATS, ("gen/*",))
    assert delta.excluded == ("gen/report.json",)
    assert (delta.adds, delta.subs) == (3, 3)


def test_project_patterns_read_the_configured_file(make_project: Callable[..., Path]) -> None:
    root = _activate(make_project, config={"exclusions": "config/ex.json"},
                     files={"config/ex.json": _EXCLUSIONS})
    patterns = project_patterns(root)
    assert patterns[0] == "gen/*"
    assert set(harness_patterns(active())) <= set(patterns)


def test_project_patterns_missing_file_falls_back_to_harness_patterns(
        make_project: Callable[..., Path]) -> None:
    root = _activate(make_project, config={"exclusions": "config/absent.json"})
    assert project_patterns(root) == tuple(harness_patterns(active()))


def test_project_patterns_null_exclusions_is_empty(make_project: Callable[..., Path]) -> None:
    root = _activate(make_project, config={"exclusions": None})
    assert project_patterns(root) == ()


def test_active_patterns_follow_the_file_on_disk(make_project: Callable[..., Path]) -> None:
    root = _activate(make_project, config={"exclusions": "config/ex.json"},
                     files={"config/ex.json": _EXCLUSIONS})
    assert "gen/*" in active_patterns()
    (root / "config" / "ex.json").write_text('{"exclusions": [{"pattern": "out/*"}]}\n', encoding="utf-8")
    patterns = active_patterns()
    assert "out/*" in patterns and "gen/*" not in patterns


def test_delta_payload_shape() -> None:
    payload = delta_payload(from_stats(_STATS, lambda path: path.startswith("gen/")))
    assert payload == {
        "adds": 3, "subs": 3, "net": 0, "files": 2, "excluded": ["gen/report.json"],
        "full": {"adds": 43, "subs": 3, "net": 40, "files": 3, "excluded": [], "full": None},
    }


def test_between_reads_two_refs(make_project: Callable[..., Path]) -> None:
    root = _activate(make_project, config={"exclusions": "config/ex.json"},
                     files={"config/ex.json": _EXCLUSIONS, "src/a.py": "x\n"})
    (root / "src" / "a.py").write_text("x\ny\nz\nw\n", encoding="utf-8")
    (root / "gen").mkdir()
    (root / "gen" / "out.json").write_text("".join(f"{n}\n" for n in range(10)), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "second")
    delta = between(root, "HEAD~1", "HEAD")
    assert (delta.adds, delta.subs, delta.files, delta.excluded) == (3, 0, 1, ("gen/out.json",))
    assert delta.full is not None and (delta.full.adds, delta.full.files) == (13, 2)


def test_between_bad_ref_raises_delta_error(make_project: Callable[..., Path]) -> None:
    root = _activate(make_project)
    with pytest.raises(DeltaError):
        between(root, "HEAD", "no-such-ref")
