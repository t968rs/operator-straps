"""Edge cases of a-w's staged attach onto a dirty target, found in review.

Each behavioral test builds a throwaway repository under ``tmp_path``: ``main`` has branch ``feature`` checked
out and ``wt`` is a detached worktree cut from its one commit, the way ``d-w`` cuts one.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import pytest

pytestmark = pytest.mark.cross_os

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t"}
WALK_ROOTS = ()  # walks only the tmp_path checkout
_BODY = "".join(f"line {n}\n" for n in range(20))


def _git(cwd: Path, *args: str, stdin: str = "") -> str:
    env = {**os.environ, **_GIT_ENV}
    done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env=env, input=stdin)
    return done.stdout.strip("\n")


def _write(repo: Path, name: str, text: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read(repo: Path, name: str) -> str:
    return (repo / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script_path(plugin_root: Path) -> Path:
    return plugin_root / "skills" / "a-w" / "commands" / "attach_worktree.py"


def _repos(tmp_path: Path, files: Dict[str, str]) -> Dict[str, Path]:
    """``main`` on ``feature`` holding ``files`` in one commit; ``wt`` cut from it."""
    main, wt = tmp_path / "main", tmp_path / "wt"
    _git(tmp_path, "init", "-q", "-b", "feature", str(main))
    for name, text in files.items():
        _write(main, name, text)
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "base")
    _git(main, "worktree", "add", "--quiet", "--detach", str(wt), "HEAD")
    return {"main": main, "wt": wt}


def _attach(script_path: Path, repos: Dict[str, Path], *flags: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(script_path), "feature", "--worktree", str(repos["wt"]), *flags]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=repos["main"],
                          env={**os.environ, **_GIT_ENV})


def _undo_commands(stdout: str) -> List[List[str]]:
    return [shlex.split(line[len("undo: "):]) for line in stdout.splitlines() if line.startswith("undo: ")]


def test_an_untracked_file_on_a_parent_of_a_written_path_refuses_before_any_write(script_path: Path,
                                                                                tmp_path: Path) -> None:
    repos = _repos(tmp_path, {"m.txt": "m\n", "z.txt": "z\n"})
    main, wt = repos["main"], repos["wt"]
    _write(main, "q", "untracked plain file\n")
    _write(wt, "m.txt", "m2\n")
    _write(wt, "q/inner.txt", "new\n")
    _write(wt, "z.txt", "z2\n")
    done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "q" in done.stderr and "untracked" in done.stderr
    assert _git(main, "status", "--porcelain") == "?? q"
    assert (_read(main, "m.txt"), _read(main, "z.txt")) == ("m\n", "z\n")
    assert wt.exists()


def test_a_target_rename_onto_a_dirty_path_refuses_and_keeps_the_staged_edit(script_path: Path,
                                                                             tmp_path: Path) -> None:
    repos = _repos(tmp_path, {"A.txt": _BODY})
    main, wt = repos["main"], repos["wt"]
    _git(main, "mv", "A.txt", "C.txt")
    _git(main, "commit", "-q", "-m", "rename")
    _write(main, "C.txt", _BODY.replace("line 2\n", "STAGED EDIT\n"))
    _git(main, "add", "C.txt")
    _write(wt, "A.txt", _BODY.replace("line 15\n", "WORKTREE EDIT\n"))
    done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "C.txt" in done.stderr
    staged = _git(main, "show", ":C.txt")
    assert "STAGED EDIT" in staged and "WORKTREE EDIT" not in staged
    assert wt.exists()


def test_diff_noprefix_in_the_target_still_lands_on_the_right_file(script_path: Path, tmp_path: Path) -> None:
    repos = _repos(tmp_path, {"sub/x.txt": "same\n", "x.txt": "same\n"})
    main, wt = repos["main"], repos["wt"]
    _git(main, "config", "diff.noprefix", "true")
    _git(main, "config", "diff.mnemonicPrefix", "true")
    _write(wt, "sub/x.txt", "edited\n")
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    assert _git(main, "diff", "--cached", "--name-only") == "sub/x.txt"
    assert (_read(main, "sub/x.txt"), _read(main, "x.txt")) == ("edited\n", "same\n")


def test_a_failed_worktree_removal_still_prints_the_backup_and_the_undo(script_path: Path,
                                                                        tmp_path: Path) -> None:
    repos = _repos(tmp_path, {"a.txt": "base\n"})
    main, wt = repos["main"], repos["wt"]
    _write(main, "a.txt", "dirty\n")
    _write(wt, "a.txt", "worktree\n")
    _git(main, "worktree", "lock", str(wt))
    try:
        done = _attach(script_path, repos, "--auto-resolve", "a.txt=worktree")
    finally:
        _git(main, "worktree", "unlock", str(wt))
    assert done.returncode == 1
    assert "removing the worktree failed" in done.stderr
    assert re.search(r"backup\b.*\b[0-9a-f]{40}\b", done.stdout), done.stdout
    assert re.search(r"--source=[0-9a-f]{40} --worktree -- a\.txt", done.stdout), done.stdout
    assert _read(main, "a.txt") == "worktree\n"


def test_the_printed_undo_matches_paths_literally(script_path: Path, tmp_path: Path) -> None:
    repos = _repos(tmp_path, {"a[1].txt": "a\n", "a1.txt": "keep\n"})
    main, wt = repos["main"], repos["wt"]
    _write(main, "a1.txt", "dirty unrelated\n")
    _write(wt, "a[1].txt", "changed\n")
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    commands = _undo_commands(done.stdout)
    assert commands, done.stdout
    for argv in commands:
        subprocess.run(argv, check=True, capture_output=True, env={**os.environ, **_GIT_ENV})
    assert _read(main, "a1.txt") == "dirty unrelated\n"
    assert _read(main, "a[1].txt") == "a\n"


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell to parse the printed lines")
def test_the_printed_undo_survives_shell_metacharacters(script_path: Path, tmp_path: Path) -> None:
    names = ("notes(old).md", "a$b.txt", "it's.md")
    repos = _repos(tmp_path, {**{name: "base\n" for name in names}, "keep.txt": "keep\n"})
    main, wt = repos["main"], repos["wt"]
    _write(main, "keep.txt", "dirty unrelated\n")
    for name in names:
        _write(wt, name, "changed\n")
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    lines = [line[len("undo: "):] for line in done.stdout.splitlines() if line.startswith("undo: ")]
    assert lines, done.stdout
    for line in lines:
        ran = subprocess.run(["sh", "-c", line], capture_output=True, text=True,
                             env={**os.environ, **_GIT_ENV})
        assert ran.returncode == 0, (line, ran.stderr)
    assert _read(main, "keep.txt") == "dirty unrelated\n"
    assert [_read(main, name) for name in names] == ["base\n"] * len(names)


def _load_merge(plugin_root: Path, monkeypatch: pytest.MonkeyPatch):
    commands = plugin_root / "skills" / "a-w" / "commands"
    monkeypatch.syspath_prepend(str(plugin_root / "lib"))
    monkeypatch.syspath_prepend(str(commands))
    spec = importlib.util.spec_from_file_location("attach_merge_under_test", commands / "attach_merge.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tree_entry_reads_a_top_level_name_that_looks_like_pathspec_magic(plugin_root: Path, tmp_path: Path,
                                                                         monkeypatch: pytest.MonkeyPatch
                                                                         ) -> None:
    merge = _load_merge(plugin_root, monkeypatch)
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-q", str(repo))
    magic = _git(repo, "hash-object", "-w", "--stdin", stdin="magic\n")
    plain = _git(repo, "hash-object", "-w", "--stdin", stdin="plain\n")
    tree = _git(repo, "mktree", "-z", stdin=f"100644 blob {magic}\t:foo\0" f"100644 blob {plain}\tfoo\0")
    assert merge.tree_entry(repo, tree, ":foo") == ("100644", magic)


def test_a_dirty_overlap_ruled_for_the_branch_is_reported_as_kept(script_path: Path, tmp_path: Path) -> None:
    repos = _repos(tmp_path, {"report.json": "{}\n"})
    main, wt = repos["main"], repos["wt"]
    _write(wt, "report.json", '{"run": 2}\n')
    _write(wt, "a.txt", "a\n")
    _write(main, "report.json", "dirty\n")
    done = _attach(script_path, repos, "--auto-resolve", "report.json=branch")
    assert done.returncode == 0, done.stderr
    assert re.search(r"kept the target's dirty copy of report\.json", done.stdout), done.stdout
    assert "dropped" in done.stdout


def test_a_worktree_ruled_dirty_path_the_worktree_deletes_is_reported_as_removed(script_path: Path,
                                                                                 tmp_path: Path) -> None:
    repos = _repos(tmp_path, {"report.json": "{}\n", "keep.txt": "k\n"})
    main, wt = repos["main"], repos["wt"]
    (wt / "report.json").unlink()
    _write(wt, "a.txt", "a\n")
    _write(main, "report.json", "dirty\n")
    done = _attach(script_path, repos, "--auto-resolve", "report.json=worktree")
    assert done.returncode == 0, done.stderr
    assert not (main / "report.json").exists()
    assert re.search(r"removed dirty path report\.json", done.stdout), done.stdout
    assert "overwrote" not in done.stdout


def _state(main: Path) -> tuple:
    """Status, index and every file's bytes in the checkout, for a before/after comparison."""
    files = {path.relative_to(main).as_posix(): path.read_bytes() for path in sorted(main.rglob("*"))
             if path.is_file() and ".git" not in path.relative_to(main).parts}
    return _git(main, "status", "--porcelain", "-uall"), _git(main, "ls-files", "-s"), files


def _run_undo(stdout: str) -> None:
    for argv in _undo_commands(stdout):
        subprocess.run(argv, check=True, capture_output=True, env={**os.environ, **_GIT_ENV})


@pytest.fixture()
def driver(script_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The driver loaded in process, with git identity set and the harness config forgotten afterwards."""
    for key, value in _GIT_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.syspath_prepend(str(script_path.parent))
    spec = importlib.util.spec_from_file_location("attach_worktree_edges_under_test", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    sys.modules["harness_lib.config"].deactivate()


def _main(driver, repos: Dict[str, Path], capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch,
          *flags: str) -> tuple:
    monkeypatch.chdir(repos["main"])
    code = driver.main(["feature", "--worktree", str(repos["wt"]), *flags])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _three_file_move(tmp_path: Path) -> Dict[str, Path]:
    """A move that edits ``a.txt`` and ``z.txt`` and adds ``n.txt``, onto a target dirty on ``m.txt``."""
    repos = _repos(tmp_path, {"a.txt": "a\n", "z.txt": "z\n", "m.txt": "m\n"})
    _write(repos["main"], "m.txt", "dirty\n")
    _write(repos["wt"], "a.txt", "a2\n")
    _write(repos["wt"], "n.txt", "new\n")
    _write(repos["wt"], "z.txt", "z2\n")
    return repos


def test_the_recovery_lines_after_a_partial_apply_restore_the_target(driver, tmp_path: Path,
                                                                    capsys: pytest.CaptureFixture,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    repos = _three_file_move(tmp_path)
    main = repos["main"]
    before = _state(main)

    def partial(target: Path, patch: bytes, final: str, overwritten) -> None:
        _write(target, "a.txt", "a2\n")
        _write(target, "n.txt", "new\n")
        raise driver.AttachError("git apply --index failed: simulated")

    monkeypatch.setattr(driver.merge, "write_land", partial)
    code, out, err = _main(driver, repos, capsys, monkeypatch)
    assert code == 1 and "simulated" in err
    assert re.search(r"backup\b.*\b[0-9a-f]{40}\b", out), out
    _run_undo(out)
    assert _state(main) == before


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows refuses to replace a file held open")
def test_a_real_apply_failure_prints_recovery_lines_that_restore_the_target(script_path: Path,
                                                                           tmp_path: Path) -> None:
    repos = _three_file_move(tmp_path)
    main = repos["main"]
    before = _state(main)
    with open(main / "z.txt", "rb"):
        done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "apply" in done.stderr, done.stderr
    assert re.search(r"backup\b.*\b[0-9a-f]{40}\b", done.stdout), done.stdout
    assert _undo_commands(done.stdout), done.stdout
    _run_undo(done.stdout)
    assert _state(main) == before


def test_an_overwrite_failure_prints_recovery_lines_that_restore_the_target(driver, tmp_path: Path,
                                                                           capsys: pytest.CaptureFixture,
                                                                           monkeypatch: pytest.MonkeyPatch
                                                                           ) -> None:
    repos = _repos(tmp_path, {"report.json": "{}\n", "a.txt": "a\n"})
    main, wt = repos["main"], repos["wt"]
    _write(main, "report.json", '{"run": "staged"}\n')
    _git(main, "add", "report.json")
    _write(main, "report.json", '{"run": "dirty"}\n')
    _write(wt, "report.json", '{"run": 2}\n')
    _write(wt, "a.txt", "a2\n")
    _write(wt, "n.txt", "new\n")
    before = _state(main)

    def fail(target: Path, final: str, path: str) -> None:
        _write(target, path, "half written\n")
        raise PermissionError("simulated")

    monkeypatch.setattr(driver.merge, "overwrite", fail)
    code, out, err = _main(driver, repos, capsys, monkeypatch, "--auto-resolve", "report.json=worktree")
    assert code == 1 and "simulated" in err
    _run_undo(out)
    assert _state(main) == before


@pytest.mark.parametrize("side", ["branch", "worktree"])
def test_a_ruled_dirty_file_the_worktree_turns_into_a_folder_refuses(script_path: Path, tmp_path: Path,
                                                                     side: str) -> None:
    repos = _repos(tmp_path, {"q": "file\n", "a.txt": "a\n"})
    main, wt = repos["main"], repos["wt"]
    _write(main, "q", "dirty q\n")
    (wt / "q").unlink()
    _write(wt, "q/inner.txt", "new\n")
    _write(wt, "a.txt", "a2\n")
    before = _state(main)
    done = _attach(script_path, repos, "--auto-resolve", f"q={side}")
    assert done.returncode == 1
    assert "q" in done.stderr and "folder" in done.stderr
    assert _state(main) == before
    assert wt.exists()


def test_tree_entry_gives_none_for_a_folder(plugin_root: Path, tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    merge = _load_merge(plugin_root, monkeypatch)
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-q", str(repo))
    blob = _git(repo, "hash-object", "-w", "--stdin", stdin="x\n")
    inner = _git(repo, "mktree", "-z", stdin=f"100644 blob {blob}\tinner.txt\0")
    tree = _git(repo, "mktree", "-z", stdin=f"040000 tree {inner}\tq\0")
    assert merge.tree_entry(repo, tree, "q") is None


def _folder_to_file(tmp_path: Path) -> Dict[str, Path]:
    """A move that deletes the tracked ``sub/x.txt`` and adds a file named ``sub``."""
    repos = _repos(tmp_path, {"sub/x.txt": "x\n", "m.txt": "m\n"})
    (repos["wt"] / "sub" / "x.txt").unlink()
    (repos["wt"] / "sub").rmdir()
    _write(repos["wt"], "sub", "now a file\n")
    return repos


def test_a_folder_the_move_turns_into_a_file_lands(script_path: Path, tmp_path: Path) -> None:
    repos = _folder_to_file(tmp_path)
    main = repos["main"]
    _write(main, "m.txt", "dirty\n")
    done = _attach(script_path, repos)
    assert done.returncode == 0, done.stderr
    assert _git(main, "diff", "--cached", "--name-status").splitlines() == ["A\tsub", "D\tsub/x.txt"]
    assert _read(main, "sub") == "now a file\n"


def test_untracked_content_in_a_folder_the_move_turns_into_a_file_refuses(script_path: Path,
                                                                          tmp_path: Path) -> None:
    repos = _folder_to_file(tmp_path)
    main = repos["main"]
    _write(main, "sub/loose.txt", "untracked\n")
    before = _state(main)
    done = _attach(script_path, repos)
    assert done.returncode == 1
    assert "sub" in done.stderr
    assert _state(main) == before


def test_a_failed_chdir_before_removal_still_prints_the_report(driver, tmp_path: Path,
                                                               capsys: pytest.CaptureFixture,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    repos = _repos(tmp_path, {"a.txt": "a\n"})
    _write(repos["wt"], "a.txt", "a2\n")
    monkeypatch.chdir(repos["main"])

    def refuse(path: object) -> None:
        raise PermissionError("simulated chdir failure")

    monkeypatch.setattr(driver.os, "chdir", refuse)
    code = driver.main(["feature", "--worktree", str(repos["wt"])])
    captured = capsys.readouterr()
    assert code == 1 and "simulated chdir failure" in captured.err
    assert "staged 1 file(s) on feature" in captured.out
    assert "undo: " in captured.out
