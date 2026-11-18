"""CLAUDE.md counts the marketplace's TypeScript mods.

A TypeScript mod is a local marketplace plugin whose `hooks/hooks.json` lists engine `modules`; the
number word in CLAUDE.md's "<n> TypeScript mods" must match how many the marketplace holds.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

NUMBER_WORDS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty",
)


def _is_ts_mod(repo_root: Path, source: object) -> bool:
    if not isinstance(source, str):
        return False
    hooks = repo_root / source / "hooks" / "hooks.json"
    return hooks.is_file() and "modules" in json.loads(hooks.read_text(encoding="utf-8"))


def _ts_mods(repo_root: Path) -> List[str]:
    marketplace = json.loads((repo_root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    return [p["name"] for p in marketplace["plugins"] if _is_ts_mod(repo_root, p.get("source"))]


def test_claude_md_counts_the_marketplace_mods(repo_root: Path) -> None:
    mods = _ts_mods(repo_root)
    text = (repo_root / "CLAUDE.md").read_text(encoding="utf-8")
    match = re.search(r"\b([a-z]+) TypeScript mods\b", text)
    assert match is not None, "CLAUDE.md does not count its TypeScript mods"
    word = match.group(1)
    assert word in NUMBER_WORDS, f"{word!r} is not a known number word"
    assert NUMBER_WORDS.index(word) == len(mods), f"CLAUDE.md says {word}, marketplace: {mods}"


def test_claude_md_names_every_marketplace_mod(repo_root: Path) -> None:
    text = (repo_root / "CLAUDE.md").read_text(encoding="utf-8")
    missing = [name for name in _ts_mods(repo_root) if f"`{name}`" not in text]
    assert not missing, f"CLAUDE.md does not name {missing}"
