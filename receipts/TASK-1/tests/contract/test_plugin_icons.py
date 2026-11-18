"""Every local marketplace plugin ships ``.claude-plugin/icon.png`` that the plugin validator accepts.

The validator wants a square PNG or JPEG of 512 to 2048 px per side under 2 MB, and the listing icon is fixed
the first time a plugin is saved, so a missing or undersized file has to fail here rather than in the portal.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import List, Tuple

import pytest

from conftest import REPO_ROOT

MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MIN_SIDE, MAX_SIDE = 512, 2048
MAX_BYTES = 2 * 1024 * 1024


def _local_plugins() -> List[Tuple[str, Path]]:
    entries = json.loads(MARKETPLACE.read_text(encoding="utf-8"))["plugins"]
    return [(e["name"], REPO_ROOT / e["source"]) for e in entries if isinstance(e["source"], str)]


def _png_size(path: Path) -> Tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == PNG_SIGNATURE, f"{path} is not a PNG"
    return struct.unpack(">II", head[16:24])


PLUGINS = _local_plugins()


def test_marketplace_lists_local_plugins() -> None:
    assert PLUGINS, f"no local plugin source found in {MARKETPLACE}"


@pytest.mark.parametrize("name,root", PLUGINS, ids=[p[0] for p in PLUGINS])
def test_plugin_ships_an_icon(name: str, root: Path) -> None:
    icon = root / ".claude-plugin" / "icon.png"
    assert icon.is_file(), f"{name}: {icon.relative_to(REPO_ROOT).as_posix()} is missing"


@pytest.mark.parametrize("name,root", PLUGINS, ids=[p[0] for p in PLUGINS])
def test_icon_is_a_square_png_the_validator_accepts(name: str, root: Path) -> None:
    icon = root / ".claude-plugin" / "icon.png"
    width, height = _png_size(icon)
    assert width == height, f"{name}: icon is {width}x{height}, not square"
    assert MIN_SIDE <= width <= MAX_SIDE, f"{name}: icon side {width} px is outside {MIN_SIDE}-{MAX_SIDE}"
    assert icon.stat().st_size < MAX_BYTES, f"{name}: icon is {icon.stat().st_size} bytes, over 2 MB"
