"""Behavioral tests for the roast slot's default sub-lens cut (issue 203).

The plugin's linear docstring-vs-code pass runs in every reviewer slot except roast: the roast slot carries
the OVERALL scope, every bucketed path already gets the pass from its bucket slot, and the measured roast
and OVERALL slots spent about a quarter of their time on it. The catalog row names the lenses it skips
(``skip_lenses``); the planner filters each slot's sub-lenses by it, so a project's own default sub-lenses
still reach the roast slot unless their rows say otherwise. The brief follows the planner.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _review_ctx import brief_ctx as _ctx  # noqa: E402
from harness_lib import review_briefs as rb  # noqa: E402
from harness_lib import review_plan as rp  # noqa: E402
from harness_lib.config import activate, load_config  # noqa: E402

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


@pytest.mark.parametrize("skip", [["runtime"], ["RUNTIME"]])
def test_project_row_skip_lenses_is_honored(skip: List[str]) -> None:
    row = {"name": "runtime-free pass", "scope_template": "t", "skip_lenses": skip}
    catalog = rp._merge_catalog(rp.load_lens_catalog(), {"default_sub_lenses": [row]})

    def names(sid: str) -> List[str]:
        """Sub-lens names the merged catalog gives the ``sid`` bucket slot."""
        return [str(s["name"]) for s in rp.sub_lenses_for(rp.Slot(sid, sid, "opus", ("a",), ()), catalog)]

    assert row["name"] not in names("runtime") and row["name"] in names("docs")


@pytest.mark.parametrize("entry", ["roasts", "config", "no-such-lens"])
def test_project_row_unknown_skip_lens_raises(entry: str) -> None:
    row = {"name": "typo pass", "scope_template": "t", "skip_lenses": [entry]}
    with pytest.raises(ValueError, match="skip_lenses"):
        rp._merge_catalog(rp.load_lens_catalog(), {"default_sub_lenses": [row]})


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
