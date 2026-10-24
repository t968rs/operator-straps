"""Shared parser for skill contract tests: a SKILL.md split into its frontmatter keys and its body."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Tuple

_PARTS = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_KEY = re.compile(r"^[a-z-]+:")


def skill_parts(path: Path) -> Tuple[Dict[str, str], str]:
    """The frontmatter of ``path`` as ``{key: raw value}`` and the body below it."""
    parts = _PARTS.match(path.read_text(encoding="utf-8"))
    assert parts, f"{path} has no frontmatter"
    pairs = (line.split(":", 1) for line in parts.group(1).splitlines() if _KEY.match(line))
    return {key.strip(): value.strip() for key, value in pairs}, parts.group(2)
