"""Behavioral tests for the plugin's ``scripts/txt_to_commit_dict.py``: TXT parsing and the .ps1 render.

Bucket and BranchCommitDocument behavior is covered by ``tests/lib/test_branch_commits.py``; the TXT
grammar by ``tests/lib/test_commit_txt.py``. The script is loaded by absolute path.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable

import pytest

from harness_lib.branch_commits import BranchCommitDocument, Bucket
from harness_lib.config import activate, active, load_config


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> ModuleType:
    """Import txt_to_commit_dict.py by absolute path."""
    path = plugin_root / "scripts" / "txt_to_commit_dict.py"
    spec = importlib.util.spec_from_file_location("txt_to_commit_dict_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _default_project(make_project: Callable[..., Path]) -> None:
    """Buckets derive from the plugin defaults (``src/`` runtime, ``tests/`` tests)."""
    activate(load_config(make_project()))

_HYPHEN_TXT = """Branch: `9999-demo`
Merge base: abc123
Messaged-through: def456
Split: none - small branch

===

Commit 1 - Runtime+Test (9 files)
"src/demo.py",
"tests/test_demo.py",

Feature(demo): add demo module

Demo module did not exist.

Second paragraph survives.
  - demo.py: new module
---

Commit 2 - Artifact (1 files)
"docs/PR_SUMMARIES/9999_demo.md",

Chore: refresh offline artifacts

Branch: `9999-demo`
"""


def _write(tmp_path: Path, text: str) -> Path:
    """Write ``text`` to a TXT under ``tmp_path`` and return its path."""
    path = tmp_path / "9999-demo.txt"
    path.write_text(text, encoding="utf-8")
    return path


class TestTxtToCommitDict:
    def test_returns_document(self, script: ModuleType, tmp_path: Path) -> None:
        document = script.txt_to_commit_dict(_write(tmp_path, _HYPHEN_TXT))
        assert isinstance(document, BranchCommitDocument)
        assert document.branch == "9999-demo"
        assert document.merge_base == "abc123"

    def test_hyphen_header_parses(self, script: ModuleType, tmp_path: Path) -> None:
        document = script.txt_to_commit_dict(_write(tmp_path, _HYPHEN_TXT))
        assert sorted(document.commits) == [1, 2]
        assert document.commits[1].bucket is Bucket.RUNTIME_TEST

    def test_reexports(self, script: ModuleType) -> None:
        assert (script.BranchCommitDocument, script.Bucket) == (BranchCommitDocument, Bucket)


class TestDocumentToPs1:
    def test_header_and_files(self, script: ModuleType, tmp_path: Path) -> None:
        rendered = script.document_to_ps1(script.txt_to_commit_dict(_write(tmp_path, _HYPHEN_TXT)))
        assert "Header  = 'Feature(demo): add demo module'" in rendered
        assert "'src/demo.py'" in rendered

    def test_message_keeps_paragraphs_and_adds_footer(self, script: ModuleType, tmp_path: Path) -> None:
        rendered = script.document_to_ps1(script.txt_to_commit_dict(_write(tmp_path, _HYPHEN_TXT)))
        expected = (
            "Feature(demo): add demo module\n\nDemo module did not exist.\n\nSecond paragraph survives.\n"
            "  - demo.py: new module\n\nBranch: `9999-demo`\n'@"
        )
        assert expected in rendered


class TestProjectFolder:
    def test_folder_is_the_configured_commit_messages_dir(
            self, script: ModuleType, make_project: Callable[..., Path],
    ) -> None:
        root = make_project(config={"artifacts": {"commit_messages": "notes/commits"}})
        activate(load_config(root))
        assert script.commit_messages_dir() == root.resolve() / "notes" / "commits"

    def test_bare_branch_resolves_in_folder(self, script: ModuleType) -> None:
        expected = active().path(active().artifacts.commit_messages) / "9999-demo.txt"
        assert script._resolve_path("9999-demo") == expected

    def test_cli_batch_writes_ps1_in_repo_folder(
            self, script: ModuleType, make_project: Callable[..., Path],
    ) -> None:
        root = make_project(files={"docs/_commit_messages/9999-demo.txt": _HYPHEN_TXT}, name="cli")
        assert script.main(["--repo", str(root)]) == 0
        assert active().project_root == root.resolve()
        assert (root / "docs" / "_commit_messages" / "9999-demo.ps1").is_file()

    def test_a_message_with_a_double_quote_is_skipped_not_written(
            self, script: ModuleType, make_project: Callable[..., Path], capsys: pytest.CaptureFixture,
    ) -> None:
        quoted = _HYPHEN_TXT.replace("new module", 'new "demo" module')
        root = make_project(files={
            "docs/_commit_messages/9999-demo.txt": quoted,
            "docs/_commit_messages/9998-ok.txt": _HYPHEN_TXT.replace("9999-demo", "9998-ok"),
        }, name="quoted")
        assert script.main(["--repo", str(root)]) == 1
        err = capsys.readouterr().err
        assert "skipped 9999-demo.txt" in err and "double quote" in err and "line 6" in err
        assert not (root / "docs" / "_commit_messages" / "9999-demo.ps1").exists()
        assert (root / "docs" / "_commit_messages" / "9998-ok.ps1").is_file()

    def test_invalid_project_config_is_a_problem_line(
            self, script: ModuleType, make_project: Callable[..., Path], capsys: pytest.CaptureFixture,
    ) -> None:
        root = make_project(files={".claude/harness.json": "{not json"}, name="broken")
        assert script.main(["--repo", str(root)]) == 1
        err = capsys.readouterr().err
        assert err.startswith("problem: ") and "harness.json" in err

    def test_runs_as_a_standalone_script(self, plugin_root: Path, make_project: Callable[..., Path]) -> None:
        root = make_project(files={"docs/_commit_messages/9999-demo.txt": _HYPHEN_TXT}, name="standalone")
        done = subprocess.run([sys.executable, str(plugin_root / "scripts" / "txt_to_commit_dict.py"),
                               "9999-demo", "--json"], cwd=root, capture_output=True, text=True,
                              encoding="utf-8")
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout)["branch"] == "9999-demo"
