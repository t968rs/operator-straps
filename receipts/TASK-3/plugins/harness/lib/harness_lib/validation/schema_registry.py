"""Schema loading and ``$ref`` resolution for review and plan artifacts.

Every schema resolves through ``schema_path``: a copy pinned under the project's ``schemas_dir`` wins,
else the plugin's canonical copy. Sibling schemas register under their bare filename, matching the
relative ``$ref`` form (``"$ref": "Child.schema.json"``) a schema uses to point at a sibling. The plan schema
is generated from the plan models and refers to no sibling.
``referencing`` is imported lazily so this module loads without it installed.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict, List

from harness_lib.project import plugin_root, schema_path

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig
    from referencing import Registry

_SCHEMA_GLOB = "*.schema.json"


def load_schema(name: str, cfg: HarnessConfig) -> Dict[str, Any]:
    """Parsed JSON of schema ``name`` (pinned project copy first, else the plugin copy)."""
    return json.loads(schema_path(name, cfg).read_text(encoding="utf-8"))


def schema_names(cfg: HarnessConfig) -> List[str]:
    """Sorted top-level ``*.schema.json`` names across the plugin schemas and the pinned directory."""
    dirs = (plugin_root() / "schemas", cfg.path(cfg.schemas_dir))
    names = {p.name for d in dirs if d.is_dir() for p in d.glob(_SCHEMA_GLOB)}
    return sorted(names)


def schema_registry(cfg: HarnessConfig) -> Registry:
    """A ``referencing.Registry`` mapping each schema's bare filename to its resolved contents.

    A schema without a ``$schema`` keyword is read as draft 2020-12, the validator default.
    """
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    registry = Registry()
    for name in schema_names(cfg):
        resource = Resource.from_contents(load_schema(name, cfg), default_specification=DRAFT202012)
        registry = registry.with_resource(uri=name, resource=resource)
    return registry
