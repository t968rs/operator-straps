"""List what must change before source files can live in an operator-straps plugin.

Usage: port_scan.py PATH [PATH ...]

Each PATH is a file or directory in the source repository. Every hit prints as ``path:line: [label] text``:
the literals ``tests/contract/test_no_repo_literals.py`` bans in plugin files (loaded from that test, so the
lists never drift) plus porting smells the contract tests cannot see. The output is a decoupling worklist,
not a verdict: a smell can be a false positive, a banned literal never is. Exit 0 after a scan, 2 on a
missing path.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterator, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = REPO_ROOT / "tests" / "contract" / "test_no_repo_literals.py"
SKIP_DIRS = {"node_modules", "__pycache__", ".git"}
Rule = Tuple[str, "re.Pattern[str]"]

SMELLS: Tuple[Rule, ...] = (
    ("inline PowerShell: rewrite as Python run through hpy",
     re.compile(r"^\s*```+\s*(powershell|ps1|pwsh)\b", re.IGNORECASE)),
    ("bare interpreter: run code through hpy",
     re.compile(r"(^|[\s`\"'(])(python3?|pytest|py -3)\s+(-[cm]|\S+\.py)")),
    ("project path under .claude/: plugin-relative or a config key",
     re.compile(r"\.claude/(skills|agents|agent-schemas|mods|scripts|state)/")),
    ("hard-coded docs folder: a configured artifacts.* key?", re.compile(r"\bdocs/[A-Za-z_][\w-]*/")),
    ("branch literal: cfg.resolve_base_branch() or integration_branches",
     re.compile(r"\b(origin/)?dev\b(?![-\w])(?=[\s`\"'.)]|$)")),
    ("gh api list without --paginate",
     re.compile(r"gh api (?!.*--paginate).*(/pulls/|/commits|/files|/comments)")),
    ("dispatch without a plugin namespace",
     re.compile(r"subagent_type[\"'`]?\s*[:=]\s*[\"'`]?(?![\w-]+:)[\w-]+")),
    ("sys.path depth: parents[1] for scripts/hooks, parents[3] for skills/<s>/commands",
     re.compile(r"Path\(__file__\)\.resolve\(\)\.parents\[\d\]")),
    ("unquoted variable after exec: quote it", re.compile(r"\bexec \$\w")),
)


def load_contract(path: Path = CONTRACT) -> ModuleType:
    """Import the literal-ban contract test by path; ``tests/`` goes on sys.path for its conftest import."""
    tests_dir = str(path.parents[1])
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    spec = importlib.util.spec_from_file_location("_port_scan_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rules(contract: ModuleType) -> List[Rule]:
    """Banned literals first (labelled ``banned:``), then the smells."""
    banned = [(f"banned: {label}", pattern) for label, pattern in contract.BANNED]
    banned.append(("banned: bare agent id (use harness:<id>)", contract.BARE_AGENT))
    return banned + list(SMELLS)


def walk_files(root: Path) -> List[Path]:
    """Every file under ``root`` in path-sorted order; skipped directories are pruned, never listed."""
    found = []
    for parent, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        found.extend(Path(parent) / name for name in files)
    return sorted(found)


def iter_files(paths: Sequence[Path], suffixes: Sequence[str]) -> Iterator[Path]:
    """Text files under ``paths`` in sorted order, skipping caches and dependency folders."""
    for root in paths:
        for path in [root] if root.is_file() else walk_files(root):
            if path.suffix in suffixes or path.name == "hpy":
                yield path


def frontmatter_problem(path: Path, text: str) -> Optional[str]:
    """Why a skill or agent markdown file lacks the ``name`` / ``description`` frontmatter, else None."""
    is_agent = path.parent.name == "agents" and path.suffix == ".md"
    if path.name != "SKILL.md" and not is_agent:
        return None
    match = re.match(r"---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if match is None:
        return "no YAML frontmatter: add name and a 'Use when...' description"
    missing = [key for key in ("name", "description") if not re.search(rf"^{key}:", match.group(1), re.M)]
    return f"frontmatter lacks {', '.join(missing)}" if missing else None


def scan_text(path: Path, text: str, active: Sequence[Rule]) -> List[str]:
    """Every rule hit in ``text`` as ``path:line: [label] text``."""
    hits = []
    problem = frontmatter_problem(path, text)
    if problem:
        hits.append(f"{path.as_posix()}:1: [{problem}]")
    for n, line in enumerate(text.splitlines(), 1):
        for label, pattern in active:
            if pattern.search(line):
                hits.append(f"{path.as_posix()}:{n}: [{label}] {line.strip()[:110]}")
    return hits


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0 if args else 2
    paths = [Path(a) for a in args]
    missing = [p for p in paths if not p.exists()]
    if missing:
        print("port_scan: no such path: " + ", ".join(str(p) for p in missing), file=sys.stderr)
        return 2
    contract = load_contract()
    active = rules(contract)
    total, files = 0, 0
    for path in iter_files(paths, sorted(contract.TEXT_SUFFIXES)):
        hits = scan_text(path, path.read_text(encoding="utf-8", errors="replace"), active)
        files += 1
        total += len(hits)
        for hit in hits:
            print(hit)
    print(f"{total} hit(s) in {files} file(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
