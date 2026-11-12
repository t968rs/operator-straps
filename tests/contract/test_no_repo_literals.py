"""No plugin file names a consuming project: its paths, interpreter variable, package or bare agent ids.

Every project-specific value reaches the plugins through ``.claude/harness.json``; a literal here means a
consumer's layout leaked back into shared code or skill text.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import pytest

from conftest import REPO_ROOT

WALK_ROOTS = ("plugins/",)
PLUGINS = REPO_ROOT / "plugins"
TEXT_SUFFIXES = {".py", ".md", ".json", ".jsonl", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".sh", ".txt",
                 ".yaml", ".yml", ".tmpl"}
SKIP_DIRS = {"node_modules", "__pycache__", ".claude-plugin-cache"}

BANNED: Tuple[Tuple[str, re.Pattern], ...] = (
    ("project interpreter variable", re.compile(r"\$\{?FPM_PY")),
    ("project agent scripts dir", re.compile(r"\.claude/agent_scripts")),
    ("project workflow lib", re.compile(r"scripts/gh_workflows")),
    ("project hooks dir", re.compile(r"\.claude/hooks/")),
    ("project test tree", re.compile(r"scripts/__tests__")),
    ("project package", re.compile(r"scripts/fpm\b|\bfpm\.[a-z_]")),
    ("project test registry", re.compile(r"testRegistry")),
    ("project name", re.compile(r"floodplain", re.IGNORECASE)),
    ("project domain library", re.compile(r"\barcpy\b", re.IGNORECASE)),
    ("machine path", re.compile(r"\b[A-Z]:[/\\](automation|Users[/\\]t968rs)", re.IGNORECASE)),
    ("owner handle outside the repo URL", re.compile(r"t968rs(?!/operator-straps)")),
)

# A ban a plugin may lift for its own files: its domain library, never a consumer's names or paths.
ALLOWED_UNDER: Dict[str, Tuple[str, ...]] = {"project domain library": ("plugins/arc-straps/",)}

# Agents ship namespaced; a dispatch naming the bare id resolves to nothing once installed.
BARE_AGENT = re.compile(
    r"(?:subagent_type|agentType)[\"'`]?\s*[:=]\s*[\"'`]?(?!harness:)"
    r"(pr-reviewer|pr-fixer|pr-team-orchestrator|pr-team-fixer|messenger|roast-my-code|strap-scenario-runner"
    r"|strap-judge|adversarial-reviewer)\b")


def _plugin_files() -> Iterator[Path]:
    for path in PLUGINS.rglob("*"):
        if path.is_file() and not SKIP_DIRS.intersection(path.parts):
            if path.suffix in TEXT_SUFFIXES or path.name == "hpy":
                yield path


def _hits(pattern: re.Pattern, files: List[Path]) -> List[str]:
    out = []
    for path in files:
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.search(line):
                out.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{n}: {line.strip()[:120]}")
    return out


def _allowed(label: str, path: Path) -> bool:
    """True when ``path`` sits under a folder that lifts the ban ``label``."""
    rel = path.relative_to(REPO_ROOT).as_posix()
    return any(rel.startswith(prefix) for prefix in ALLOWED_UNDER.get(label, ()))


FILES = sorted(_plugin_files())


def _scanned(label: str, files: Optional[List[Path]] = None) -> List[Path]:
    """The plugin files the ban ``label`` covers: ``files`` (default FILES) minus its exempt folders."""
    return [p for p in (FILES if files is None else files) if not _allowed(label, p)]


def test_scan_sees_the_plugins() -> None:
    assert len(FILES) > 100, f"only {len(FILES)} plugin files found under {PLUGINS}"


def test_templates_are_scanned() -> None:
    templates = [p for p in FILES if p.suffix == ".tmpl"]
    assert templates, f"no .tmpl file under {PLUGINS} reaches the literal scan"


@pytest.mark.parametrize("label,pattern", BANNED, ids=[b[0] for b in BANNED])
def test_no_consumer_literal(label: str, pattern: re.Pattern) -> None:
    hits = _hits(pattern, _scanned(label))
    assert not hits, f"{label} in plugin files:\n" + "\n".join(hits)


def test_agent_dispatches_are_namespaced() -> None:
    shipped = [p for p in FILES if not re.search(r"\.test\.tsx?$", p.name)]
    hits = _hits(BARE_AGENT, shipped)
    assert not hits, "bare agent ids (use harness:<id>):\n" + "\n".join(hits)


@pytest.mark.parametrize("bad", ["$FPM_PY -m pytest", "see scripts/fpm/geo", "E:/automation/x",
                                 "github.com/t968rs/other"])
def test_patterns_catch_known_leaks(bad: str) -> None:
    assert any(p.search(bad) for _label, p in BANNED)


def test_bare_agent_pattern() -> None:
    assert BARE_AGENT.search('subagent_type: "pr-fixer"')
    assert BARE_AGENT.search("subagent_type=`messenger`")
    assert not BARE_AGENT.search('subagent_type: "harness:pr-fixer"')


def test_bare_strap_agent_ids() -> None:
    assert BARE_AGENT.search('subagent_type: "strap-judge"')
    assert BARE_AGENT.search("subagent_type='strap-scenario-runner'")
    assert not BARE_AGENT.search('subagent_type: "harness:strap-judge"')
    assert not BARE_AGENT.search('subagent_type: "harness:strap-scenario-runner"')


def test_arcpy_is_allowed_only_under_arc_straps() -> None:
    pattern = dict(BANNED)["project domain library"]
    inside = REPO_ROOT / "plugins" / "arc-straps" / "x.md"
    outside = REPO_ROOT / "plugins" / "harness" / "x.md"
    assert not _allowed("project name", inside)
    assert _allowed("project domain library", inside)
    assert not _allowed("project domain library", outside)
    assert not _allowed("project domain library", REPO_ROOT / "plugins" / "arc-straps-x" / "x.md")
    assert pattern.search("import arcpy")


def test_scan_drops_only_exempt_paths() -> None:
    inside = REPO_ROOT / "plugins" / "arc-straps" / "x.md"
    outside = REPO_ROOT / "plugins" / "harness" / "x.md"
    assert _scanned("project domain library", [inside, outside]) == [outside]
    assert _scanned("project name", [inside, outside]) == [inside, outside]
    assert _scanned("project name") == FILES


def test_exemptions_name_existing_labels() -> None:
    assert set(ALLOWED_UNDER) <= {label for label, _ in BANNED}
