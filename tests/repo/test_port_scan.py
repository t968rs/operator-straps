"""Behavior of .claude/skills/porting-into-straps/port_scan.py, the pre-port decoupling worklist."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / ".claude" / "skills" / "porting-into-straps" / "port_scan.py"


@pytest.fixture(scope="module")
def scan() -> ModuleType:
    spec = importlib.util.spec_from_file_location("port_scan_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def active(scan: ModuleType) -> list:
    return scan.rules(scan.load_contract())


def _labels(scan: ModuleType, active: list, line: str, name: str = "x.md") -> list:
    hits = scan.scan_text(Path(name), line, active)
    return [h.split("[", 1)[1].split("]", 1)[0] for h in hits]


def test_rules_carry_every_contract_ban(scan: ModuleType, active: list) -> None:
    contract = scan.load_contract()
    labels = [label for label, _ in active]
    for label, _ in contract.BANNED:
        assert f"banned: {label}" in labels
    assert len(active) == len(contract.BANNED) + 1 + len(scan.SMELLS)


@pytest.mark.parametrize("line,label", [
    ('"$FPM_PY" -m pytest x', "banned: project interpreter variable"),
    ('subagent_type: "pr-fixer"', "banned: bare agent id (use harness:<id>)"),
    ("```powershell", "inline PowerShell"),
    ("run `python -c \"print(1)\"` first", "bare interpreter"),
    ("pytest tests/test_x.py -q", "bare interpreter"),
    ("see .claude/skills/other/SKILL.md", "project path under .claude/"),
    ("write to docs/PR_REVIEWS/x.json", "hard-coded docs folder"),
    ("git log origin/dev..HEAD", "branch literal"),
    ("gh api repos/o/r/pulls/7/files", "gh api list without --paginate"),
    ('subagent_type: "explore-helper"', "dispatch without a plugin namespace"),
    ('sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))', "sys.path depth"),
    ("exec $PY \"$@\"", "unquoted variable after exec"),
])
def test_each_rule_fires(scan: ModuleType, active: list, line: str, label: str) -> None:
    assert any(found.startswith(label) for found in _labels(scan, active, line))


@pytest.mark.parametrize("line", [
    "gh api --paginate repos/o/r/pulls/7/files",
    'subagent_type: "harness:pr-fixer"',
    "the dev-pipeline skill",
    "developer devices",
    'exec "$PY" "$@"',
    'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/x.py"',
])
def test_clean_lines_stay_clean(scan: ModuleType, active: list, line: str) -> None:
    assert _labels(scan, active, line) == []


@pytest.mark.parametrize("text,expected", [
    ("# Title\n", "no YAML frontmatter"),
    ("---\nname: x\n---\n# Title\n", "frontmatter lacks description"),
    ("---\nname: x\ndescription: Use when y.\n---\n", None),
])
def test_skill_frontmatter(scan: ModuleType, text: str, expected: str) -> None:
    problem = scan.frontmatter_problem(Path("skills/x/SKILL.md"), text)
    assert (problem is None) if expected is None else problem.startswith(expected)


def test_frontmatter_checks_agents_but_not_other_markdown(scan: ModuleType) -> None:
    assert scan.frontmatter_problem(Path("agents/a.md"), "# A\n") is not None
    assert scan.frontmatter_problem(Path("docs/notes.md"), "# A\n") is None


def test_frontmatter_skips_non_markdown_under_agents(scan: ModuleType) -> None:
    assert scan.frontmatter_problem(Path("agents/helper.py"), "import os\n") is None


def _tree(root: Path, *rels: str) -> None:
    for rel in rels:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n", encoding="utf-8")


def _found(scan: ModuleType, root: Path) -> list:
    return [p.relative_to(root).as_posix() for p in scan.iter_files([root], [".py", ".md", ".ts"])]


def test_iter_files_filters_and_skips(scan: ModuleType, tmp_path: Path) -> None:
    _tree(tmp_path, "a.py", "b.md", "c.png", "node_modules/d.ts", "__pycache__/e.py", "scripts/hpy")
    assert _found(scan, tmp_path) == ["a.py", "b.md", "scripts/hpy"]


def test_iter_files_keeps_path_sorted_order(scan: ModuleType, tmp_path: Path) -> None:
    _tree(tmp_path, "c.md", "b/x.md", "a.md")
    assert _found(scan, tmp_path) == ["a.md", "b/x.md", "c.md"]


def test_iter_files_never_lists_a_skipped_directory(scan: ModuleType, tmp_path: Path, monkeypatch) -> None:
    _tree(tmp_path, "a.md", "node_modules/pkg/d.ts", ".git/objects/x.py", "src/__pycache__/e.py")
    listed = []
    real = os.scandir

    def spy(path="."):
        listed.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(os, "scandir", spy)
    assert _found(scan, tmp_path) == ["a.md"]
    assert not set(listed) & scan.SKIP_DIRS


def test_main_prints_hits_and_exits_zero(scan: ModuleType, tmp_path: Path, capsys) -> None:
    skill = tmp_path / "skills" / "s" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# S\nRun \"$FPM_PY\" x.py\n", encoding="utf-8")
    assert scan.main([str(tmp_path)]) == 0
    out, err = capsys.readouterr()
    assert "SKILL.md:1: [no YAML frontmatter" in out
    assert "SKILL.md:2: [banned: project interpreter variable]" in out
    assert "2 hit(s) in 1 file(s)" in err


def test_main_survives_a_narrow_console_encoding(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "s" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# S\nRun \"$FPM_PY\" x.py ❌\n", encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    done = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True,
                          encoding="cp1252", env=env)
    assert done.returncode == 0, done.stderr
    assert "SKILL.md:2: [banned: project interpreter variable]" in done.stdout


@pytest.mark.parametrize("argv,code", [([], 2), (["--help"], 0), (["no/such/path"], 2)])
def test_main_usage_codes(scan: ModuleType, argv: list, code: int) -> None:
    assert scan.main(argv) == code
