"""Where arc-meta reads and writes: the ``plugins.arc-straps.arc_meta`` section resolved to absolute paths."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

from harness_lib.config import ConfigError, active, load_config
from harness_lib.plugin_config import plugin_section
from harness_lib.project import project_root

__all__ = ["ArcMetaPaths", "RepoLike", "paths"]

PLUGIN = "arc-straps"
_CONFIG = Path(__file__).resolve().parents[3] / "config"
_KEYS = ("atbx", "tool_dir", "toolbox_source", "registry")
_OPTIONAL = ("atbx", "toolbox_source", "registry")
RepoLike = Optional[Union[str, Path]]


@dataclass(frozen=True)
class ArcMetaPaths:
    """Absolute locations arc-meta reads and writes in one project."""

    root: Path
    atbx: Path
    tool_dir: Path
    toolbox_source: Path
    registry: Optional[Path]


def paths(repo: RepoLike = None) -> ArcMetaPaths:
    """Resolve the section for ``repo`` (default: the active project); refuses an ambiguous archive.

    ``repo`` may be any folder inside the project. A location that resolves outside the project root
    raises ConfigError.
    """
    cfg = active() if repo is None else load_config(project_root(Path(repo)))
    section = plugin_section(PLUGIN, _CONFIG / "defaults.json", _CONFIG / "arc-straps.schema.json", cfg)
    meta, root = _meta(section), cfg.project_root
    atbx = root / meta["atbx"] if meta["atbx"] else _only_archive(root)
    tool_dir = root / meta["tool_dir"]
    source = root / meta["toolbox_source"] if meta["toolbox_source"] else tool_dir.parent / f"{atbx.name}.xml"
    registry = root / meta["registry"] if meta["registry"] else None
    _inside(root, {"atbx": atbx, "tool_dir": tool_dir, "toolbox_source": source, "registry": registry})
    return ArcMetaPaths(root, atbx, tool_dir, source, registry)


def _meta(section: Dict[str, Any]) -> Dict[str, Any]:
    """The ``arc_meta`` object checked for keys, value types and empty paths, also without ``jsonschema``."""
    meta = section.get("arc_meta")
    if not isinstance(meta, dict):
        raise ConfigError(f"plugins.{PLUGIN}.arc_meta: must be an object")
    unknown = sorted(set(meta) - set(_KEYS))
    if unknown:
        raise ConfigError(f"plugins.{PLUGIN}.arc_meta: unknown keys {unknown}")
    if not isinstance(meta.get("tool_dir"), str):
        raise ConfigError(f"plugins.{PLUGIN}.arc_meta.tool_dir: must be a string")
    for key in _OPTIONAL:
        if not isinstance(meta.get(key), (str, type(None))):
            raise ConfigError(f"plugins.{PLUGIN}.arc_meta.{key}: must be a string or null")
    for key in ("tool_dir", *_OPTIONAL):
        if meta.get(key) == "":
            raise ConfigError(f"plugins.{PLUGIN}.arc_meta.{key}: must not be empty")
    return meta


def _inside(root: Path, found: Dict[str, Optional[Path]]) -> None:
    """Refuse any resolved location that is not under the project root."""
    base = root.resolve()
    for key, path in found.items():
        if path is not None and not path.resolve().is_relative_to(base):
            raise ConfigError(f"plugins.{PLUGIN}.arc_meta.{key}: resolves outside the project root")


def _only_archive(root: Path) -> Path:
    found = sorted(root.glob("*.atbx"))
    if len(found) != 1:
        what = "no .atbx" if not found else f"{len(found)} .atbx files"
        raise ConfigError(f"{what} at {root.as_posix()}; "
                          f"set plugins.{PLUGIN}.arc_meta.atbx in .claude/harness.json")
    return found[0]
