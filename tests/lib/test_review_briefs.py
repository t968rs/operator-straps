"""Behavioral tests for harness_lib.review_briefs (reviewer brief composition) and the driver's split.

The reviewer brief is composed in the library from a ``BriefContext`` and a planned ``Slot``: the role line
follows the slot's planned kind (bucket, catalog or project lens, OVERALL, roast), the rules carry the
test-design clause for test paths and the roast voice for the roast slot only. The driver keeps no brief
composition of its own and compares no slot lens against a hard-coded bucket or lens name.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Set

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _review_ctx import brief_ctx as _ctx  # noqa: E402
from harness_lib import review_briefs as rb  # noqa: E402
from harness_lib import review_plan as rp  # noqa: E402
from harness_lib.config import activate, load_config  # noqa: E402
from harness_lib.review_plan import Lens, PathBucket, ScopeLens  # noqa: E402

_DRIVER = Path("scripts") / "pr_review.py"
_MOVED = ("BriefContext", "header_lines", "record_heredoc", "_draft_json", "target_label", "key_literal",
          "brief_header", "scope_section", "lens_section", "rules_section", "record_section",
          "reviewer_brief", "TOO_LONG_RULE", "TEST_DESIGN_CLAUSE", "ROAST_VOICE", "OVERALL_SCOPE",
          "BUCKET_SCOPE", "SEVERITY_RULES", "PROSE_GAP_RULE", "REMOVAL_DEFECTS", "_role", "_scope_text")
# The driver's private names that the library exposes without the underscore.
_RENAMED = {"_draft_json": "draft_json", "_role": "role", "_scope_text": "scope_text"}


@pytest.fixture(autouse=True)
def project(make_project) -> Path:
    """A throwaway project with an empty config, activated for every test of the module."""
    root = make_project(config={"exclusions": None})
    activate(load_config(root))
    return root


def _slot(sid: str, lens: str, paths=("src/a.py",), templates=()) -> rp.Slot:
    """A planned slot with ``lens`` resolved by the planner."""
    return rp.Slot(sid, lens, "opus", tuple(paths), tuple(templates))


class TestRole:
    """The role line follows the slot's planned kind."""

    @pytest.mark.parametrize("sid, lens, role", [
        ("docs", "docs", "`docs` bucket reviewer"),
        ("config", "config-or-registry", "`config-or-registry` bucket reviewer"),
        ("overall", "overall", "OVERALL reviewer"),
        ("roast", "roast", "roast reviewer covering the OVERALL scope"),
        ("skill_package", "per-skill-package", "`per-skill-package` cross-cutting lens reviewer"),
        ("geo_seam", "geo-seam", "`geo-seam` cross-cutting lens reviewer"),
    ])
    def test_role_line(self, sid: str, lens: str, role: str) -> None:
        assert rb.role(_slot(sid, lens)) == role


class TestPlannedKind:
    """The planner, not the brief, says what kind of slot it is."""

    def test_bucket_and_overall_scope(self) -> None:
        assert _slot("docs", "docs").bucket is PathBucket.DOCS
        assert _slot("overall", "overall").bucket is None and _slot("overall", "overall").overall_scope
        assert _slot("roast", "roast").overall_scope and not _slot("docs", "docs").overall_scope
        assert not _slot("geo_seam", "geo-seam").overall_scope

    def test_skill_list_only_for_the_skill_package_lens(self) -> None:
        assert _slot("skill_package", Lens.SKILL_PACKAGE).lists_skills
        assert not _slot("overall", ScopeLens.OVERALL).lists_skills


class TestBrief:
    """The composed brief: sections in order, scope sentences and the conditional rules."""

    def test_sections_in_order(self, project: Path) -> None:
        brief = rb.reviewer_brief(_ctx(project), _slot("runtime", "runtime"), project / "d.diff", ())
        heads = [line for line in brief.splitlines() if line.startswith("## ")]
        assert heads == ["## Scope", "## Lens", "## Rules", "## Record (once, after the analysis)"]
        assert "Role: `runtime` bucket reviewer, model `opus`." in brief

    def test_scope_sentences(self, project: Path) -> None:
        ctx = _ctx(project)
        assert rb.BUCKET_SCOPE.format(bucket="runtime") in rb.lens_section(ctx, _slot("runtime", "runtime"))
        for sid in ("overall", "roast"):
            assert rb.OVERALL_SCOPE in rb.lens_section(ctx, _slot(sid, sid))
        lens = rb.lens_section(ctx, _slot("multi_artifact", "coordinated-multi-artifact",
                                          templates=("coordinated-multi-artifact",)))
        assert rb.OVERALL_SCOPE not in lens and "### coordinated-multi-artifact" in lens

    def test_roast_voice_only_for_roast(self) -> None:
        assert rb.ROAST_VOICE in rb.rules_section(_slot("roast", "roast"))
        assert rb.ROAST_VOICE not in rb.rules_section(_slot("overall", "overall"))

    def test_test_design_clause_follows_test_paths(self) -> None:
        assert rb.TEST_DESIGN_CLAUSE in rb.rules_section(_slot("tests", "tests", ("tests/test_a.py",)))
        assert rb.TEST_DESIGN_CLAUSE not in rb.rules_section(_slot("docs", "docs", ("docs/a.md",)))


def _driver_tree(plugin_root: Path) -> ast.Module:
    """The parsed driver source."""
    return ast.parse((plugin_root / _DRIVER).read_text(encoding="utf-8"))


def _member_values() -> Set[str]:
    """Every bucket, lens and scope value."""
    return {m.value for enum in (PathBucket, Lens, ScopeLens) for m in enum}


class TestDriverSplit:
    """The driver neither composes reviewer briefs nor names a bucket or lens in a comparison."""

    def test_moved_names_live_in_the_library(self, plugin_root: Path) -> None:
        tree = _driver_tree(plugin_root)
        defined = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        defined |= {t.id for node in tree.body if isinstance(node, ast.Assign) for t in node.targets
                    if isinstance(t, ast.Name)}
        assert not defined & set(_MOVED)
        assert [name for name in _MOVED if not hasattr(rb, _RENAMED.get(name, name))] == []

    def test_no_comparison_with_a_lens_literal(self, plugin_root: Path) -> None:
        values = _member_values()
        hits = []
        for node in ast.walk(_driver_tree(plugin_root)):
            if not isinstance(node, ast.Compare):
                continue
            for side in (node.left, *node.comparators):
                items = side.elts if isinstance(side, (ast.Tuple, ast.List, ast.Set)) else [side]
                hits += [f"line {node.lineno}: {item.value!r}" for item in items
                         if isinstance(item, ast.Constant) and item.value in values]
        assert hits == []
