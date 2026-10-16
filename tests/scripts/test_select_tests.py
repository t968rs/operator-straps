"""tools/select_tests.py: which CI work a diff needs, decided from imports, mentions and path rules."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, Iterator, List

import pytest

from conftest import REPO_ROOT, git

_SCRIPT = REPO_ROOT / "tools" / "select_tests.py"

PYPROJECT = '[tool.pytest.ini_options]\npythonpath = ["plugins/harness/lib", "tests"]\n'

TREE: Dict[str, str] = {
    "pyproject.toml": PYPROJECT,
    "requirements-dev.txt": "pytest\n",
    "tests/conftest.py": "def _fixture():\n    from harness_lib.config import deactivate\n",
    "plugins/harness/lib/harness_lib/__init__.py": "",
    "plugins/harness/lib/harness_lib/config.py": "X = 1\n",
    "plugins/harness/lib/harness_lib/base.py": "Y = 1\n",
    "plugins/harness/lib/harness_lib/mid.py": "from harness_lib import base\n",
    "plugins/harness/lib/harness_lib/solo.py": "Z = 1\n",
    "plugins/harness/hooks/guard.py": "print('hook')\n",
    "plugins/harness/skills/demo/SKILL.md": "# demo\n",
    "tests/lib/test_mid.py": "from harness_lib.mid import thing\n",
    "tests/lib/test_solo.py": "import harness_lib.solo\n",
    "tests/lib/_helpers.py": "from harness_lib.solo import Z\n",
    "tests/lib/test_helped.py": "from _helpers import Z\n",
    "tests/hooks/test_guard.py": "HOOK = 'plugins/harness/hooks/guard.py'\n",
    "tests/contract/test_walk.py": "def t(root):\n    return list(root.rglob('*.md'))\n",
    "docs/notes.md": "notes\n",
}


@pytest.fixture(scope="module")
def sel() -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location("select_tests_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _write(root: Path, files: Dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    _write(tmp_path, TREE)
    return tmp_path


def _tests(sel: ModuleType, root: Path, *changed: str, deleted: List[str] = ()) -> List[str]:
    out = sel.plan(root, list(changed), list(deleted))
    assert out.pytest == "subset", (out.pytest, out.reasons)
    return out.tests


def test_import_selects_only_its_dependents(sel: ModuleType, tree: Path) -> None:
    got = _tests(sel, tree, "plugins/harness/lib/harness_lib/solo.py")
    assert "tests/lib/test_solo.py" in got
    assert "tests/lib/test_mid.py" not in got
    assert "tests/hooks/test_guard.py" not in got


def test_transitive_import_is_followed(sel: ModuleType, tree: Path) -> None:
    got = _tests(sel, tree, "plugins/harness/lib/harness_lib/base.py")
    assert "tests/lib/test_mid.py" in got


def test_helper_beside_the_test_resolves(sel: ModuleType, tree: Path) -> None:
    got = _tests(sel, tree, "plugins/harness/lib/harness_lib/solo.py")
    assert "tests/lib/test_helped.py" in got


def test_changed_test_selects_itself(sel: ModuleType, tree: Path) -> None:
    assert "tests/hooks/test_guard.py" in _tests(sel, tree, "tests/hooks/test_guard.py")


def test_path_loaded_hook_is_found_by_mention(sel: ModuleType, tree: Path) -> None:
    assert "tests/hooks/test_guard.py" in _tests(sel, tree, "plugins/harness/hooks/guard.py")


def test_imports_of_a_path_loaded_script_count(sel: ModuleType, tree: Path) -> None:
    _write(tree, {
        "plugins/harness/scripts/drv.py": "from harness_lib import solo\n",
        "tests/scripts/test_drv.py": "SCRIPT = 'plugins/harness/scripts/drv.py'\n",
    })
    got = _tests(sel, tree, "plugins/harness/lib/harness_lib/solo.py")
    assert "tests/scripts/test_drv.py" in got


def test_tree_walking_test_runs_on_any_non_docs_change(sel: ModuleType, tree: Path) -> None:
    got = _tests(sel, tree, "plugins/harness/skills/demo/SKILL.md")
    assert got == ["tests/contract/test_walk.py"]


def test_docs_only_change_runs_no_pytest(sel: ModuleType, tree: Path) -> None:
    out = sel.plan(tree, ["docs/notes.md"], [])
    assert out.pytest == "none"
    assert out.tests == []
    assert out.plugins is False


@pytest.mark.parametrize("path", ["tests/conftest.py", "pyproject.toml", "requirements-dev.txt",
                                  ".github/workflows/ci.yml", "tools/select_tests.py"])
def test_shared_files_force_the_full_suite(sel: ModuleType, tree: Path, path: str) -> None:
    out = sel.plan(tree, [path], [])
    assert out.pytest == "full"
    assert out.ruff == "full"
    assert out.plugins is True


def test_conftest_dependency_reaches_every_test(sel: ModuleType, tree: Path) -> None:
    got = _tests(sel, tree, "plugins/harness/lib/harness_lib/config.py")
    assert set(got) == set(sel.list_tests(tree))


def test_deleted_python_file_forces_full(sel: ModuleType, tree: Path) -> None:
    out = sel.plan(tree, [], ["plugins/harness/lib/harness_lib/gone.py"])
    assert out.pytest == "full"


def test_unsafe_path_characters_force_full(sel: ModuleType, tree: Path) -> None:
    out = sel.plan(tree, ["docs/with space.md"], [])
    assert out.pytest == "full"
    assert out.ruff == "full"


def test_syntax_error_in_a_test_forces_full(sel: ModuleType, tree: Path) -> None:
    _write(tree, {"tests/lib/test_broken.py": "def (:\n"})
    out = sel.plan(tree, ["plugins/harness/lib/harness_lib/solo.py"], [])
    assert out.pytest == "full"


def test_ruff_lists_changed_python_under_linted_roots(sel: ModuleType, tree: Path) -> None:
    out = sel.plan(tree, ["plugins/harness/hooks/guard.py", "tools/other.py", "docs/notes.md"], [])
    assert out.ruff == "subset"
    assert out.ruff_files == ["plugins/harness/hooks/guard.py"]


def test_ruff_skipped_without_python_changes(sel: ModuleType, tree: Path) -> None:
    assert sel.plan(tree, ["docs/notes.md"], []).ruff == "none"


def test_plugins_flag_follows_plugin_and_marketplace_paths(sel: ModuleType, tree: Path) -> None:
    assert sel.plan(tree, ["plugins/harness/skills/demo/SKILL.md"], []).plugins is True
    assert sel.plan(tree, [".claude-plugin/marketplace.json"], []).plugins is True
    assert sel.plan(tree, ["docs/notes.md"], []).plugins is False


def test_changed_files_reads_the_merge_base_diff(sel: ModuleType, tree: Path) -> None:
    git(tree, "init", "-q", "-b", "main")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "base")
    git(tree, "checkout", "-q", "-b", "feature")
    (tree / "plugins/harness/lib/harness_lib/solo.py").write_text("Z = 2\n", encoding="utf-8")
    (tree / "docs/notes.md").unlink()
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "work")
    changed, deleted = sel.changed_files(tree, "main", "HEAD")
    assert changed == ["plugins/harness/lib/harness_lib/solo.py"]
    assert deleted == ["docs/notes.md"]


def _cli(root: Path, *args: str, env_out: Path = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_SCRIPT), "--root", str(root), *args]
    env = None
    if env_out is not None:
        import os
        env = {**os.environ, "GITHUB_OUTPUT": str(env_out)}
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_cli_full_flag_writes_lists_and_github_outputs(tree: Path, tmp_path_factory) -> None:
    out_dir = tmp_path_factory.mktemp("out")
    gh = out_dir / "gh_output.txt"
    done = _cli(tree, "--full", "--out-dir", str(out_dir), env_out=gh)
    assert done.returncode == 0, done.stderr
    outputs = dict(line.split("=", 1) for line in gh.read_text(encoding="utf-8").splitlines())
    assert outputs["pytest"] == "full" and outputs["ruff"] == "full" and outputs["plugins"] == "true"
    assert json.loads(done.stdout)["pytest"] == "full"


def test_cli_subset_writes_the_selected_test_list(tree: Path, tmp_path_factory) -> None:
    git(tree, "init", "-q", "-b", "main")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "base")
    git(tree, "checkout", "-q", "-b", "feature")
    (tree / "plugins/harness/lib/harness_lib/solo.py").write_text("Z = 2\n", encoding="utf-8")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "work")
    out_dir = tmp_path_factory.mktemp("out")
    done = _cli(tree, "--base", "main", "--out-dir", str(out_dir))
    assert done.returncode == 0, done.stderr
    assert b"\r" not in (out_dir / "selected-tests.txt").read_bytes()  # bash splits `$(cat ...)` on LF only
    listed = (out_dir / "selected-tests.txt").read_text(encoding="utf-8").split()
    assert "tests/lib/test_solo.py" in listed
    assert "tests/lib/test_mid.py" not in listed


def test_real_repo_has_no_unparsable_or_unresolvable_test(sel: ModuleType) -> None:
    out = sel.plan(REPO_ROOT, ["plugins/harness/lib/harness_lib/shell_scan.py"], [])
    assert out.pytest == "subset", out.reasons
    assert "tests/lib/test_shell_scan.py" in out.tests
