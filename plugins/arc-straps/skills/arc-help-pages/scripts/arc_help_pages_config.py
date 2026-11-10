"""arc-help-pages paths: the ``plugins.arc-straps.arc_help_pages`` section resolved against one project.

The section resolves by the same rules as ``arc_meta`` but on its own: its own defaults, its own type checks
(also without ``jsonschema``) and its own archive lookup. ``root`` is the checkout the call runs in;
``checkout_root`` is the main checkout of its repository, so an href written against the main checkout
still matches when the checks run from a linked worktree.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union
from urllib.parse import quote

from harness_lib.config import ConfigError, active, load_config
from harness_lib.plugin_config import plugin_section
from harness_lib.project import main_worktree, project_root

__all__ = ["HelpPaths", "RepoLike", "paths"]

PLUGIN = "arc-straps"
_CONFIG = Path(__file__).resolve().parents[3] / "config"
_KEYS = ("atbx", "tool_dir", "help_dir")
_OPTIONAL = ("atbx",)
RepoLike = Optional[Union[str, Path]]


@dataclass(frozen=True)
class HelpPaths:
    """Absolute locations arc-help-pages reads and writes in one project."""

    root: Path
    atbx: Path
    tool_dir: Path
    help_dir: Path
    checkout_root: Path

    @property
    def prefix(self) -> str:
        """The ``file:`` URI prefix of the main checkout, ending in a slash."""
        return self.checkout_root.as_uri() + "/"

    def page_href(self, page: str) -> str:
        """The development href of ``<page>.html``: the checkout URI plus its percent-encoded repo path."""
        return self.prefix + quote((self.help_dir / f"{page}.html").relative_to(self.root).as_posix())


def paths(repo: RepoLike = None) -> HelpPaths:
    """Resolve the section for ``repo`` (default: the active project); refuses an ambiguous archive.

    ``repo`` may be any folder inside the project. A location that resolves outside the project root
    raises ConfigError.
    """
    cfg = active() if repo is None else load_config(project_root(Path(repo)))
    section = plugin_section(PLUGIN, _CONFIG / "defaults.json", _CONFIG / "arc-straps.schema.json", cfg)
    pages, root = _section(section), cfg.project_root
    atbx = root / pages["atbx"] if pages["atbx"] else _only_archive(root)
    tool_dir, help_dir = root / pages["tool_dir"], root / pages["help_dir"]
    _inside(root, {"atbx": atbx, "tool_dir": tool_dir, "help_dir": help_dir})
    return HelpPaths(root, atbx, tool_dir, help_dir, main_worktree(root))


def _section(section: Dict[str, Any]) -> Dict[str, Any]:
    """The ``arc_help_pages`` object checked for keys, types and empty paths, also without ``jsonschema``."""
    pages = section.get("arc_help_pages")
    if not isinstance(pages, dict):
        raise ConfigError(f"plugins.{PLUGIN}.arc_help_pages: must be an object")
    unknown = sorted(set(pages) - set(_KEYS))
    if unknown:
        raise ConfigError(f"plugins.{PLUGIN}.arc_help_pages: unknown keys {unknown}")
    for key in _KEYS:
        kinds = (str, type(None)) if key in _OPTIONAL else (str,)
        if not isinstance(pages.get(key), kinds):
            what = "a string or null" if key in _OPTIONAL else "a string"
            raise ConfigError(f"plugins.{PLUGIN}.arc_help_pages.{key}: must be {what}")
        if pages[key] == "":
            raise ConfigError(f"plugins.{PLUGIN}.arc_help_pages.{key}: must not be empty")
    return pages


def _inside(root: Path, found: Dict[str, Path]) -> None:
    """Refuse any resolved location that is not under the project root."""
    base = root.resolve()
    for key, path in found.items():
        if not path.resolve().is_relative_to(base):
            raise ConfigError(f"plugins.{PLUGIN}.arc_help_pages.{key}: resolves outside the project root")


def _only_archive(root: Path) -> Path:
    found = sorted(root.glob("*.atbx"))
    if len(found) != 1:
        what = "no .atbx" if not found else f"{len(found)} .atbx files"
        raise ConfigError(f"{what} at {root.as_posix()}; "
                          f"set plugins.{PLUGIN}.arc_help_pages.atbx in .claude/harness.json")
    return found[0]
