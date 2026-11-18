"""Per-plugin sections of ``.claude/harness.json``: another plugin's defaults merged under its section."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from harness_lib.config import ConfigError, HarnessConfig, active, deep_merge


def plugin_section(name: str, defaults_path: Path, schema_path: Optional[Path] = None,
                   cfg: Optional[HarnessConfig] = None) -> Dict[str, Any]:
    """``plugins.<name>`` of ``cfg`` (default: the active config) merged over the plugin's defaults.

    The merged section is validated against ``schema_path`` when given; a defect raises ConfigError
    naming ``plugins/<name>/<json path>``.
    """
    merged = deep_merge(_read(defaults_path), (cfg or active()).plugin(name))
    if schema_path is not None:
        _check(merged, _read(schema_path), name)
    return merged


def _read(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be an object")
    return data


def _check(data: Dict[str, Any], schema: Dict[str, Any], name: str) -> None:
    try:
        import jsonschema
    except ImportError:
        closed = schema.get("additionalProperties") is False
        unknown = sorted(set(data) - set(schema.get("properties", {}))) if closed else []
        if unknown:
            raise ConfigError(f"plugins/{name}: unknown keys {unknown}")
        return
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        where = "/".join(["plugins", name, *(str(p) for p in errors[0].absolute_path)])
        raise ConfigError(f"{where}: {errors[0].message}")
