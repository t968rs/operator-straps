"""tools/select_tests.py: which CI work a diff needs, decided from imports, mentions and path rules."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, Iterator, List, Optional

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
    "tools/other.py": "T = 1\n",
    "scratch/other.py": "S = 1\n",
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


def _tests(sel: ModuleType, root: Path, *changed: str, deleted: Optional[List[str]] = None) -> List[str]:
    out = sel.plan(root, list(changed), list(deleted or []))
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


def test_deleted_file_outside_docs_reaches_the_tree_walk(sel: ModuleType, tree: Path) -> None:
    got = _tests(sel, tree, deleted=["plugins/harness/skills/demo/SKILL.md"])
    assert got == ["tests/contract/test_walk.py"]


def test_deleted_file_named_by_a_test_selects_it(sel: ModuleType, tree: Path) -> None:
    _write(tree, {"tests/hooks/test_fixture.py": "FIXTURE = 'fixtures/sample.json'\n"})
    got = _tests(sel, tree, "docs/notes.md", deleted=["tests/hooks/fixtures/sample.json"])
    assert "tests/hooks/test_fixture.py" in got


def test_data_file_selects_tests_of_the_module_that_reads_it(sel: ModuleType, tree: Path) -> None:
    _write(tree, {
        "plugins/harness/lib/harness_lib/solo.py": "PATH = 'defaults.json'\n",
        "plugins/harness/config/defaults.json": "{}\n",
    })
    got = _tests(sel, tree, "plugins/harness/config/defaults.json")
    assert "tests/lib/test_solo.py" in got
    assert "tests/lib/test_helped.py" in got
    assert "tests/lib/test_mid.py" not in got


def test_relative_imports_are_followed(sel: ModuleType, tree: Path) -> None:
    _write(tree, {
        "plugins/harness/lib/harness_lib/rel_pkg.py": "from . import solo\n",
        "plugins/harness/lib/harness_lib/rel_mod.py": "from .base import Y\n",
        "tests/lib/test_rel.py": "import harness_lib.rel_pkg\nimport harness_lib.rel_mod\n",
    })
    assert "tests/lib/test_rel.py" in _tests(sel, tree, "plugins/harness/lib/harness_lib/solo.py")
    assert "tests/lib/test_rel.py" in _tests(sel, tree, "plugins/harness/lib/harness_lib/base.py")


def test_pyproject_without_pythonpath_falls_back_to_defaults(sel: ModuleType, tree: Path) -> None:
    _write(tree, {"pyproject.toml": "[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n"})
    assert sel.pythonpath_roots(tree) == list(sel.DEFAULT_PYTHONPATH)
    assert "tests/lib/test_solo.py" in _tests(sel, tree, "plugins/harness/lib/harness_lib/solo.py")


def test_unsafe_path_characters_force_full(sel: ModuleType, tree: Path) -> None:
    out = sel.plan(tree, ["docs/with space.md"], [])
    assert out.pytest == "full"
    assert out.ruff == "full"


def test_syntax_error_in_a_test_forces_full(sel: ModuleType, tree: Path) -> None:
    _write(tree, {"tests/lib/test_broken.py": "def (:\n"})
    out = sel.plan(tree, ["plugins/harness/lib/harness_lib/solo.py"], [])
    assert out.pytest == "full"


def test_ruff_lists_changed_python_under_linted_roots(sel: ModuleType, tree: Path) -> None:
    changed = ["plugins/harness/hooks/guard.py", "tools/other.py", "scratch/other.py", "docs/notes.md"]
    out = sel.plan(tree, changed, [])
    assert out.ruff == "subset"
    assert out.ruff_files == ["plugins/harness/hooks/guard.py", "tools/other.py"]


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


def _cli(root: Path, *args: str, env_out: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Run the script without the runner's ``GITHUB_OUTPUT``; ``env_out`` sets it explicitly."""
    cmd = [sys.executable, str(_SCRIPT), "--root", str(root), *args]
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}
    if env_out is not None:
        env["GITHUB_OUTPUT"] = str(env_out)
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_cli_full_flag_writes_lists_and_github_outputs(
    sel: ModuleType, tree: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    out_dir = tmp_path_factory.mktemp("out")
    gh = out_dir / "gh_output.txt"
    done = _cli(tree, "--full", "--out-dir", str(out_dir), env_out=gh)
    assert done.returncode == 0, done.stderr
    outputs = dict(line.split("=", 1) for line in gh.read_text(encoding="utf-8").splitlines())
    assert outputs["pytest"] == "full" and outputs["ruff"] == "full" and outputs["plugins"] == "true"
    assert json.loads(done.stdout)["pytest"] == "full"
    listed = (out_dir / "selected-tests.txt").read_text(encoding="utf-8").splitlines()
    assert listed == sel.list_tests(tree)
    assert (out_dir / "ruff-files.txt").read_text(encoding="utf-8") == ""


def test_cli_subset_writes_the_selected_test_list(
    tree: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
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


def test_cli_unreadable_diff_runs_everything(tree: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    git(tree, "init", "-q", "-b", "main")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "base")
    done = _cli(tree, "--base", "no-such-ref", "--out-dir", str(tmp_path_factory.mktemp("out")))
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["pytest"] == "full"
    assert "diff unreadable" in result["reasons"][0]


def test_cli_without_base_or_full_is_a_usage_error(
    tree: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    done = _cli(tree, "--out-dir", str(tmp_path_factory.mktemp("out")))
    assert done.returncode == 2
    assert "--base is required" in done.stderr


def test_real_repo_has_no_unparsable_test(sel: ModuleType) -> None:
    every = sel.list_tests(REPO_ROOT)
    out = sel.plan(REPO_ROOT, every, [])
    assert out.pytest == "subset", out.reasons
    assert out.tests == every
