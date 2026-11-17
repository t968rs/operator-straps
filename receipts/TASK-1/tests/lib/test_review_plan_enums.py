"""Behavioral tests for the review_plan lens enums and the roast slot's lens.

``PathBucket``, ``Lens`` and ``ScopeLens`` replace the module's bucket and lens tuples and name constants:
lookup accepts a member's value or name in any letter case and refuses anything else, the slot ids and the
reserved project-lens names derive from the members, and a roast slot always carries ``ScopeLens.ROAST``
whether it replaces OVERALL (small PR) or runs beside it (large PR). ``plan.json`` keeps each slot's
``roast`` key through ``Slot.record``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

import pytest

from harness_lib import review_plan as rp
from harness_lib.config import activate, load_config
from harness_lib.project import plugin_root
from harness_lib.review_plan import Lens, PathBucket, ScopeLens

_SHAPE = "overall-system-shape"


@pytest.fixture(autouse=True)
def project(make_project) -> Path:
    """A throwaway project with an empty config, activated for every test of the module."""
    root = make_project(config={"exclusions": None})
    activate(load_config(root))
    return root


def _buckets(**named: Tuple[str, ...]) -> Dict[PathBucket, Tuple[str, ...]]:
    """A full bucket mapping keyed by member; ``config`` names the config-or-registry bucket."""
    out: Dict[PathBucket, Tuple[str, ...]] = {bucket: () for bucket in PathBucket}
    for key, paths in named.items():
        out[PathBucket.CFG if key == "config" else PathBucket(key)] = paths
    return out


def _files(prefix: str, count: int) -> Tuple[str, ...]:
    """``count`` distinct paths under ``prefix``."""
    return tuple(f"{prefix}f{i}.py" for i in range(count))


def _three_bucket(per_bucket: int) -> Tuple[Dict[PathBucket, Tuple[str, ...]], Tuple[str, ...]]:
    """Runtime, tests and docs buckets with ``per_bucket`` runtime and test files; (buckets, reviewable)."""
    buckets = _buckets(runtime=_files("src/", per_bucket), tests=_files("tests/test_", per_bucket),
                       docs=("docs/a.md",))
    return buckets, buckets[PathBucket.RUNTIME] + buckets[PathBucket.TESTS] + buckets[PathBucket.DOCS]


class TestLookup:
    """A member resolves from its value or its name in any letter case; nothing else resolves."""

    @pytest.mark.parametrize("raw, member", [
        ("config-or-registry", PathBucket.CFG), ("CFG", PathBucket.CFG), ("Docs", PathBucket.DOCS),
        ("UNBUCKETED", PathBucket.UNBUCKETED), ("system_shape", Lens.SYSTEM_SHAPE),
        ("Per-Skill-Package", Lens.SKILL_PACKAGE), ("Roast", ScopeLens.ROAST), ("overall", ScopeLens.OVERALL),
    ])
    def test_value_or_name_in_any_case(self, raw: str, member: object) -> None:
        assert type(member)(raw) is member

    @pytest.mark.parametrize("enum, raw", [(PathBucket, "garbage"), (PathBucket, "overall"),
                                           (Lens, "cicd"), (ScopeLens, "docs"), (Lens, "")])
    def test_unknown_value_raises(self, enum: type, raw: str) -> None:
        with pytest.raises(ValueError):
            enum(raw)

    def test_members_are_their_strings(self) -> None:
        assert PathBucket.TESTS == "tests" and {PathBucket.CFG: 1}.get("config-or-registry") == 1
        encoded = json.dumps({PathBucket.CFG: [Lens.SYSTEM_SHAPE]})
        assert encoded == '{"config-or-registry": ["overall-system-shape"]}'


class TestSlotIds:
    """Slot ids and the reserved project-lens names come from the members."""

    def test_bucket_slot_ids_in_precedence_order(self) -> None:
        assert [b.slot_id for b in PathBucket.slotted()] == ["cicd", "config", "tests", "runtime", "docs"]
        assert PathBucket.UNBUCKETED not in PathBucket.slotted()

    def test_lens_and_scope_slot_ids(self) -> None:
        assert [lens.slot_id for lens in Lens] == ["skill_package", "multi_artifact", "system_shape"]
        assert [scope.slot_id for scope in ScopeLens] == ["overall", "roast"]

    def test_catalog_lenses_are_the_enum(self) -> None:
        path = plugin_root() / "schemas" / "catalogs" / rp.CATALOG_NAME
        catalog = json.loads(path.read_text(encoding="utf-8"))
        assert [lens["name"] for lens in catalog["lenses"]] == [lens.value for lens in Lens]

    @pytest.mark.parametrize("name", ["config-or-registry", "unbucketed", "overall", "skill-package"])
    def test_project_lens_named_like_a_member_is_rejected(self, make_project, name: str) -> None:
        lens = {"name": name, "summary": "s", "scope_template": "t",
                "trigger": {"description": "d", "path_globs": ["src/*"]}}
        root = make_project(config={"exclusions": None, "review": {"lenses": "lenses.json"}},
                            files={"lenses.json": {"lenses": [lens]}}, name="other")
        activate(load_config(root))
        with pytest.raises(ValueError, match="reserved"):
            rp.load_lens_catalog()


class TestConstantsRemoved:
    """The tuples and name constants the enums replace are gone."""

    @pytest.mark.parametrize("name", ["PATH_BUCKETS", "LENS_NAMES", "UNBUCKETED", "SKILL_PACKAGE",
                                      "MULTI_ARTIFACT", "SYSTEM_SHAPE", "_SLOT_IDS"])
    def test_name_is_gone(self, name: str) -> None:
        assert not hasattr(rp, name)


class TestSlotLens:
    """Every planned slot carries an enum member (a project lens its name); roast is always ROAST."""

    def test_small_pr_roast_slot_is_roast(self) -> None:
        buckets, reviewable = _three_bucket(2)
        slots = {s.id: s for s in rp.slot_plan(buckets, {}, True, reviewable)}
        assert "overall" not in slots and "system_shape" not in slots
        roast = slots["roast"]
        assert roast.lens is ScopeLens.ROAST and roast.roast
        assert roast.paths == reviewable and roast.templates == (_SHAPE,)

    def test_large_pr_roast_slot_is_roast(self) -> None:
        buckets, reviewable = _three_bucket(10)
        slots = {s.id: s for s in rp.slot_plan(buckets, {}, True, reviewable)}
        assert slots["roast"].lens is ScopeLens.ROAST and slots["roast"].roast
        assert slots["overall"].lens is ScopeLens.OVERALL and not slots["overall"].roast

    def test_bucket_lens_and_project_slots(self) -> None:
        schemas, docs = ("a.schema.json", "b.schema.json"), ("docs/a.md", "docs/b.md")
        buckets = _buckets(config=schemas, docs=docs)
        lenses = {"coordinated-multi-artifact": schemas, "geo-seam": ("docs/a.md",)}
        planned = rp.slot_plan(buckets, lenses, False, schemas + docs, extra_lenses=("geo-seam",))
        slots = {s.id: s for s in planned}
        assert slots["config"].lens is PathBucket.CFG and slots["docs"].lens is PathBucket.DOCS
        assert slots["multi_artifact"].lens is Lens.MULTI_ARTIFACT
        assert slots["geo_seam"].lens == "geo-seam"

    def test_string_lens_resolves_to_its_member(self) -> None:
        assert rp.Slot("cicd", "cicd", "sonnet", ("a.yml",), ()).lens is PathBucket.CICD
        assert rp.Slot("roast", "roast", "opus", ("a.py",), ()).roast

    def test_record_keeps_the_roast_key(self) -> None:
        buckets, reviewable = _three_bucket(2)
        roast = next(s for s in rp.slot_plan(buckets, {}, True, reviewable) if s.id == "roast")
        record = json.loads(json.dumps(roast.record()))
        assert record == {"id": "roast", "lens": "roast", "model": "opus", "paths": list(reviewable),
                          "templates": [_SHAPE], "roast": True}

    def test_sort_buckets_keys_are_members(self) -> None:
        out = rp.sort_buckets(["src/a.py", "x.lyrx"])
        assert set(out) == set(PathBucket)
        assert out[PathBucket.RUNTIME] == ("src/a.py",) and out[PathBucket.UNBUCKETED] == ("x.lyrx",)
