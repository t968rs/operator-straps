"""tools/select_tests.py: which CI work a diff needs, decided from imports, mentions and path rules."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Dict, Iterator, List, Optional

import pytest

from conftest import REPO_ROOT, git

WALK_ROOTS = ("tests/",)  # the contract tests read every test file; the fixture walks are in strings
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


WALKER = "tests/contract/test_case.py"
WALK_BODY = "def test_w(root):\n    assert list(root.rglob('*'))\n"
UNRELATED = "tools/other.py"
UNDER_SKILLS = "plugins/harness/skills/demo/notes.txt"


def _reason(sel: ModuleType, root: Path, rel: str, *changed: str) -> Optional[str]:
    out = sel.plan(root, list(changed), [])
    return next((r.split(": ", 1)[1] for r in out.reasons if r.startswith(f"{rel}: ")), None)


@pytest.mark.parametrize("marker", ["('plugins/harness/skills/',)", "('plugins/harness/skills',)",
                                    "('tools/nowhere/', 'plugins/harness/skills/')"])
def test_walk_roots_select_only_for_changes_under_a_root(sel: ModuleType, tree: Path, marker: str) -> None:
    _write(tree, {WALKER: f"WALK_ROOTS = {marker}\n{WALK_BODY}"})
    want = f"walks plugins/harness/skills/, holding {UNDER_SKILLS}"
    assert _reason(sel, tree, WALKER, UNDER_SKILLS) == want
    assert _reason(sel, tree, WALKER, UNRELATED) is None
    assert _reason(sel, tree, WALKER, "plugins/harness/skillset/x.md") is None


def test_dot_root_stands_for_the_whole_repo(sel: ModuleType, tree: Path) -> None:
    _write(tree, {WALKER: f"WALK_ROOTS = ('.',)\n{WALK_BODY}"})
    assert _reason(sel, tree, WALKER, UNRELATED) == f"walks ./, holding {UNRELATED}"


def test_empty_walk_roots_never_select(sel: ModuleType, tree: Path) -> None:
    _write(tree, {WALKER: f"WALK_ROOTS = ()\n{WALK_BODY}"})
    assert _reason(sel, tree, WALKER, UNRELATED) is None
    assert _reason(sel, tree, WALKER, UNDER_SKILLS) is None


@pytest.mark.parametrize("marker", ["['plugins/']", "('/plugins/',)", "('../plugins/',)",
                                    "('plugins/../x/',)", "('plugins', 3)", "ROOTS", "('',)",
                                    "('C:/x/',)", "('plugins\\\\x',)", "'plugins/'"])
def test_invalid_walk_roots_keep_the_broad_rule(sel: ModuleType, tree: Path, marker: str) -> None:
    _write(tree, {WALKER: f"ROOTS = ('plugins/',)\nWALK_ROOTS = {marker}\n{WALK_BODY}"})
    assert sel.walk_roots(f"WALK_ROOTS = {marker}\n") is None
    assert _reason(sel, tree, WALKER, UNRELATED) == "walks the tree"


def test_unmarked_walker_runs_on_any_non_docs_change_only(sel: ModuleType, tree: Path) -> None:
    _write(tree, {WALKER: WALK_BODY})
    assert _reason(sel, tree, WALKER, UNRELATED) == "walks the tree"
    assert sel.plan(tree, ["docs/notes.md"], []).tests == []


def test_marked_walker_ignores_a_docs_change_outside_its_roots(sel: ModuleType, tree: Path) -> None:
    _write(tree, {WALKER: f"WALK_ROOTS = ('plugins/',)\n{WALK_BODY}"})
    assert sel.plan(tree, ["docs/notes.md"], []).tests == []


@pytest.mark.parametrize("source", [
    "import shutil\ndef test_c(a, b):\n    shutil.copytree(a, b)\n",
    "import os\ndef test_s(p):\n    assert list(os.scandir(p))\n",
    "import os\ndef test_l(p):\n    assert os.listdir(p)\n",
    "import glob\ndef test_i():\n    assert list(glob.iglob('x/*'))\n",
    "def test_p(p):\n    assert list(p.walk())\n",
    "import os\ndef test_o(p):\n    assert list(os.walk(p))\n",
])
def test_gate_covers_every_listed_walk(sel: ModuleType, tree: Path, source: str) -> None:
    _write(tree, {WALKER: source})
    assert _reason(sel, tree, WALKER, UNRELATED) == "walks the tree"


@pytest.mark.parametrize("source", [
    "import ast\ndef test_a():\n    assert list(ast.walk(ast.parse('x')))\n",
    "# root.rglob('*') is avoided here\ndef test_c():\n    assert True\n",
    '"""Never calls root.iterdir() on the repo."""\ndef test_d():\n    assert True\n',
    "def test_e():\n    '''No os.listdir(x) here either.'''\n",
])
def test_ast_walk_and_prose_are_not_walks(sel: ModuleType, tree: Path, source: str) -> None:
    _write(tree, {WALKER: source})
    assert _reason(sel, tree, WALKER, UNRELATED) is None


def test_helper_on_an_inserted_sys_path_is_in_the_closure(sel: ModuleType, tree: Path) -> None:
    _write(tree, {
        "tests/lib/_parts.py": "from harness_lib.solo import Z\n",
        "tests/skills/test_parts.py": "import sys\nfrom pathlib import Path\n"
                                      "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))\n"
                                      "from _parts import Z\n",
    })
    got = _reason(sel, tree, "tests/skills/test_parts.py", "plugins/harness/lib/harness_lib/solo.py")
    assert got == "imports plugins/harness/lib/harness_lib/solo.py"


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


@pytest.mark.parametrize("source", [
    '"""Reads nothing; the plugin dir holds ``defaults.json``."""\nZ = 1\n',
    "# defaults.json lives beside this module\nZ = 1\n",
])
def test_data_file_named_only_in_prose_selects_nothing(sel: ModuleType, tree: Path, source: str) -> None:
    _write(tree, {
        "plugins/harness/lib/harness_lib/solo.py": source,
        "plugins/harness/config/defaults.json": "{}\n",
    })
    got = _tests(sel, tree, "plugins/harness/config/defaults.json")
    assert got == ["tests/contract/test_walk.py"]


def test_data_file_built_in_an_fstring_selects_its_reader(sel: ModuleType, tree: Path) -> None:
    _write(tree, {
        "plugins/harness/lib/harness_lib/solo.py": 'def p(root):\n    return f"{root}/defaults.json"\n',
        "plugins/harness/config/defaults.json": "{}\n",
    })
    assert "tests/lib/test_solo.py" in _tests(sel, tree, "plugins/harness/config/defaults.json")


_TWO_SKILLS = {
    "plugins/harness/skills/other/SKILL.md": "# other\n",
    "tests/skills/test_demo_skill.py": 'SKILL = ROOT / "skills" / "demo" / "SKILL.md"\n',
    "tests/skills/test_other_skill.py": 'SKILL = ROOT / "skills" / "other" / "SKILL.md"\n',
}


@pytest.mark.parametrize("how", ["changed", "deleted"])
def test_shared_name_selects_only_tests_naming_its_folder(sel: ModuleType, tree: Path, how: str) -> None:
    _write(tree, _TWO_SKILLS)
    path = "plugins/harness/skills/demo/SKILL.md"
    got = _tests(sel, tree, path) if how == "changed" else _tests(sel, tree, deleted=[path])
    assert "tests/skills/test_demo_skill.py" in got
    assert "tests/skills/test_other_skill.py" not in got


def test_folder_name_matches_as_a_whole_word(sel: ModuleType, tree: Path) -> None:
    _write(tree, {
        "plugins/harness/skills/demo-two/SKILL.md": "# two\n",
        "tests/skills/test_two.py": 'SKILL = ROOT / "skills" / "demo-two" / "SKILL.md"\n',
    })
    assert "tests/skills/test_two.py" not in _tests(sel, tree, "plugins/harness/skills/demo/SKILL.md")


def test_unique_name_keeps_the_basename_rule(sel: ModuleType, tree: Path) -> None:
    _write(tree, {
        "plugins/harness/skills/demo/notes.json": "{}\n",
        "tests/skills/test_notes.py": "NOTES = 'notes.json'\n",
    })
    assert "tests/skills/test_notes.py" in _tests(sel, tree, "plugins/harness/skills/demo/notes.json")


def test_shared_name_with_no_telling_folder_keeps_the_basename_rule(sel: ModuleType, tree: Path) -> None:
    _write(tree, {
        "plugins/demo/README.md": "# demo\n",
        "tests/fixtures/plugins/demo/README.md": "# copy\n",
        "tests/skills/test_readme.py": "README = 'README.md'\n",
    })
    assert "tests/skills/test_readme.py" in _tests(sel, tree, "plugins/demo/README.md")


def test_shared_root_name_needs_a_root_name_on_its_line(sel: ModuleType, tree: Path) -> None:
    _write(tree, {
        "README.md": "# repo\n",
        "plugins/harness/README.md": "# harness\n",
        "tests/contract/test_root_readme.py": 'TEXT = (REPO_ROOT / "README.md").read_text()\n',
        "tests/contract/test_root_readme_call.py": 'TEXT = _text(repo_root, "README.md")\n',
        "tests/scripts/test_fixture_readme.py": 'FILES = {"README.md": "x\\n"}\n',
    })
    got = _tests(sel, tree, "README.md")
    assert "tests/contract/test_root_readme.py" in got
    assert "tests/contract/test_root_readme_call.py" in got
    assert "tests/scripts/test_fixture_readme.py" not in got


def test_module_naming_a_shared_name_reads_only_a_file_whose_folder_it_names(
        sel: ModuleType, tree: Path) -> None:
    _write(tree, {
        **_TWO_SKILLS,
        "plugins/harness/lib/harness_lib/solo.py": 'FALLBACK = "SKILL.md"\n',
        "plugins/harness/lib/harness_lib/base.py": 'SKILL = ("skills", "demo", "SKILL.md")\n',
    })
    got = _tests(sel, tree, "plugins/harness/skills/other/SKILL.md")
    assert "tests/lib/test_solo.py" not in got
    assert "tests/lib/test_mid.py" not in got
    assert "tests/lib/test_mid.py" in _tests(sel, tree, "plugins/harness/skills/demo/SKILL.md")


def test_module_inside_the_folder_reads_a_shared_name_by_basename(sel: ModuleType, tree: Path) -> None:
    _write(tree, {
        **_TWO_SKILLS,
        "plugins/harness/skills/demo/commands/run.py": 'SKILL = Path(__file__).parents[1] / "SKILL.md"\n',
        "tests/skills/test_run.py": "SCRIPT = 'run.py'\n",
    })
    assert "tests/skills/test_run.py" in _tests(sel, tree, "plugins/harness/skills/demo/SKILL.md")
    assert "tests/skills/test_run.py" not in _tests(sel, tree, "plugins/harness/skills/other/SKILL.md")


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


def test_every_walking_test_declares_existing_walk_roots(sel: ModuleType) -> None:
    """A walking test without a valid WALK_ROOTS runs on every pull request; a listed root that does not
    exist is a typo that would skip the test when its real root changes."""
    unmarked: List[str] = []
    absent: List[str] = []
    for rel in sel.list_tests(REPO_ROOT):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        if not sel.walks(text):
            continue
        roots = sel.walk_roots(text)
        if roots is None:
            unmarked.append(rel)
            continue
        absent.extend(f"{rel}: {r}" for r in roots if not (REPO_ROOT / r).is_dir())
    assert unmarked == [], "walking tests need a literal WALK_ROOTS tuple"
    assert absent == [], "WALK_ROOTS names a directory that does not exist"


def test_arc_meta_scripts_folder_is_an_import_root(sel: ModuleType) -> None:
    """A bare-stem skill module is reached through the pythonpath entry for its folder: the archive test
    never names the generator, yet imports it through the shared builder."""
    changed = "plugins/arc-straps/skills/arc-meta/scripts/arc_meta_format.py"
    chosen, reasons = sel.affected_tests(REPO_ROOT, [changed])
    assert "tests/arc/test_arc_meta_archive.py" in chosen, reasons
    why = next(r for r in reasons if r.startswith("tests/arc/test_arc_meta_archive.py:"))
    assert why.endswith(f"imports {changed}"), why


def test_default_pythonpath_mirrors_pyproject_and_the_pylint_hook(sel: ModuleType) -> None:
    """The fallback roots, pytest's ``pythonpath`` and pylint's ``init-hook`` name the same folders."""
    assert list(sel.DEFAULT_PYTHONPATH) == sel.pythonpath_roots(REPO_ROOT)
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    hook = data["tool"]["pylint"]["main"]["init-hook"]
    missing = [entry for entry in sel.DEFAULT_PYTHONPATH if f"'{entry}'" not in hook]
    assert missing == [], hook


def test_real_repo_has_no_unparsable_test(sel: ModuleType) -> None:
    every = sel.list_tests(REPO_ROOT)
    out = sel.plan(REPO_ROOT, every, [])
    assert out.pytest == "subset", out.reasons
    assert out.tests == every
