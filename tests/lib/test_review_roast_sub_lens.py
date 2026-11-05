"""Behavioral tests for the roast slot's default sub-lens cut (issue 203).

The plugin's linear docstring-vs-code pass runs in every reviewer slot except roast: the roast slot carries
the OVERALL scope, every bucketed path already gets the pass from its bucket slot, and the measured roast
and OVERALL slots spent about a quarter of their time on it. The catalog row names the lenses it skips
(``skip_lenses``); the planner filters each slot's sub-lenses by it, so a project's own default sub-lenses
still reach the roast slot unless their rows say otherwise. The brief follows the planner.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from harness_lib import review_briefs as rb
from harness_lib import review_plan as rp
from harness_lib.config import activate, load_config
from harness_lib.pr_summary import PrFacts, PrFile

_LINEAR = "linear docstring-vs-code pass"
_SUB_LENS_HEAD = "### Default sub-lens: "
_EXTRA = {"name": "project security pass", "scope_template": "Check each input boundary."}


@pytest.fixture(autouse=True)
def project(make_project) -> Path:
    """A project whose lens file adds one default sub-lens, activated for every test of the module."""
    root = make_project(config={"exclusions": None, "review": {"lenses": "lenses.json"}},
                        files={"lenses.json": {"lenses": [], "default_sub_lenses": [_EXTRA]}})
    activate(load_config(root))
    return root


def _ctx(root: Path) -> rb.BriefContext:
    """A brief context over a one-file PR at a fixed head."""
    facts = PrFacts(1234, "demo", "1234-demo", "main", "a" * 40, "b" * 40, "", (),
                    (PrFile("M", "src/a.py", None, 2, 1),))
    return rb.BriefContext(root.as_posix(), (root / "lib").as_posix(), 1234, "pr1234_20990101T000000Z",
                           facts, True, rp.load_lens_catalog(), ())


def _names(slot: rp.Slot) -> List[str]:
    """Names of the default sub-lenses the planner gives ``slot``."""
    return [str(sub["name"]) for sub in rp.sub_lenses_for(slot, rp.load_lens_catalog())]


def test_catalog_row_skips_roast() -> None:
    row = next(sub for sub in rp.load_lens_catalog()["default_sub_lenses"] if sub["name"] == _LINEAR)
    assert row.get("skip_lenses") == ["roast"]


@pytest.mark.parametrize("sid, lens, names", [
    ("roast", "roast", [_EXTRA["name"]]),
    ("overall", "overall", [_LINEAR, _EXTRA["name"]]),
    ("runtime", "runtime", [_LINEAR, _EXTRA["name"]]),
    ("multi_artifact", "coordinated-multi-artifact", [_LINEAR, _EXTRA["name"]]),
    ("geo_seam", "geo-seam", [_LINEAR, _EXTRA["name"]]),
])
def test_planner_filters_sub_lenses(sid: str, lens: str, names: List[str]) -> None:
    assert _names(rp.Slot(sid, lens, "opus", ("src/a.py",), ())) == names


@pytest.mark.parametrize("small", [True, False])
def test_roast_brief_drops_only_the_linear_pass(project: Path, small: bool) -> None:
    count = 2 if small else 10
    runtime = tuple(f"src/f{i}.py" for i in range(count))
    tests = tuple(f"tests/test_f{i}.py" for i in range(count))
    buckets = {bucket: () for bucket in rp.PathBucket}
    buckets.update({rp.PathBucket.RUNTIME: runtime, rp.PathBucket.TESTS: tests})
    slots = {s.id: s for s in rp.slot_plan(buckets, {}, True, runtime + tests)}
    ctx = _ctx(project)
    roast = rb.lens_section(ctx, slots["roast"])
    assert _SUB_LENS_HEAD + _LINEAR not in roast and _SUB_LENS_HEAD + _EXTRA["name"] in roast
    assert _SUB_LENS_HEAD + _LINEAR in rb.lens_section(ctx, slots["runtime"])
    if not small:
        assert _SUB_LENS_HEAD + _LINEAR in rb.lens_section(ctx, slots["overall"])
