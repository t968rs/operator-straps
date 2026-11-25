"""The lap-stamp mod is registered where every mod is (plan 2031).

Its own manifest, hooks file and engine scaffolding (TASK-1); the marketplace, CI, README, CLAUDE.md, its own
README and the proposed release's notes (TASK-6).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Tuple

WALK_ROOTS = ("docs/RELEASES/",)

_MOD = "plugins/lap-stamp"


def _text(repo_root: Path, rel: str) -> str:
    path = repo_root / rel
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def _version(text: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in json.loads(text)["version"].split("."))


def test_the_mod_manifest_and_hooks(repo_root: Path) -> None:
    manifest = json.loads(_text(repo_root, f"{_MOD}/.claude-plugin/plugin.json"))
    assert manifest["name"] == "lap-stamp"
    assert manifest["types"] == "./types/index.d.ts"
    assert _version(json.dumps(manifest)) >= (0, 1, 0)
    hooks = json.loads(_text(repo_root, f"{_MOD}/hooks/hooks.json"))
    assert hooks == {"modules": ["./register.ts"]}


def test_engine_scaffolding(repo_root: Path) -> None:
    missing = [rel for rel in (f"{_MOD}/tsconfig.json", f"{_MOD}/.gitignore", f"{_MOD}/types/index.d.ts")
               if not (repo_root / rel).is_file()]
    assert not missing, f"missing: {missing}"


def test_the_marketplace_lists_the_mod(repo_root: Path) -> None:
    plugins = json.loads(_text(repo_root, ".claude-plugin/marketplace.json"))["plugins"]
    entry = next((p for p in plugins if p["name"] == "lap-stamp"), None)
    assert entry is not None and entry["source"] == "./plugins/lap-stamp"


def test_ci_runs_the_mod_tests(repo_root: Path) -> None:
    assert "plugins/lap-stamp" in _text(repo_root, ".github/workflows/ci.yml")


def test_the_readme_documents_and_installs_the_mod(repo_root: Path) -> None:
    readme = _text(repo_root, "README.md")
    assert "claude plugin install lap-stamp@operator-straps" in readme
    assert re.search(r"\|[^|\n]*\|\s*`lap-stamp`\s*\|", readme)


def test_claude_md_names_and_counts_the_mod(repo_root: Path) -> None:
    text = _text(repo_root, "CLAUDE.md")
    assert "`lap-stamp`" in text
    assert "tests/mods/test_lap_stamp_config_mirror.py" in text


def test_the_mod_has_a_readme(repo_root: Path) -> None:
    text = _text(repo_root, f"{_MOD}/README.md")
    assert "lap-stamp" in text
    assert "laps.jsonl" in text


def _release_rows(repo_root: Path) -> List[str]:
    """Every lap-stamp row of the release-notes tables under docs/RELEASES/."""
    rows: List[str] = []
    for path in sorted((repo_root / "docs" / "RELEASES").glob("v*.md")):
        rows += re.findall(r"^\|\s*lap-stamp\s*\|.*$", path.read_text(encoding="utf-8"), re.MULTILINE)
    return rows


def test_the_release_notes_list_the_mod(repo_root: Path) -> None:
    manifest = json.loads(_text(repo_root, f"{_MOD}/.claude-plugin/plugin.json"))
    version = re.escape(manifest["version"])
    rows = _release_rows(repo_root)
    assert any(re.search(rf"\|\s*{version}\s*\|\s*$", row) for row in rows), rows
