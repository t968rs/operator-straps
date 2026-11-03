"""The writing-docstrings dispatch API: scope resolution, dispatch rows and the parallel probe files.

Each test but the model check builds a ``make_project`` repo and calls ``writing_docstrings_api`` directly;
the last test validates the row models alone. The probe record is a file the caller names (the driver passes
``<state_dir>/writing-docstrings/probes.txt``).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from harness_lib.writing_docstrings_api import (
    DispatchError,
    clear_probes,
    first_path,
    plan_rows,
    probe_row,
    resolve_scope,
    write_probes,
)
from harness_lib.writing_docstrings_models import (
    AGENT,
    PROBE_MODEL,
    PROBE_NAME,
    PROBE_RECORD,
    PROBE_SOURCE,
    WORK_MODEL,
    DispatchRow,
    FileScope,
)

A = "def f():\n    return 1\n\n\ndef g():\n    return 2\n"
B = "class C:\n    def h(self):\n        return 3\n"


def _p(path: Path) -> str:
    return path.resolve().as_posix()


def _project(make_project) -> Path:
    return make_project(files={"src/a.py": A, "src/b.py": B, "src/notes.md": "# notes\n"})


def _record(root: Path) -> Path:
    return root / ".claude" / "state" / "harness" / PROBE_RECORD


def _problems(root: Path, *tokens: str) -> list:
    with pytest.raises(DispatchError) as caught:
        resolve_scope(root, list(tokens), cwd=root)
    return caught.value.problems


def test_bare_path_scopes_every_function(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["src/a.py"], cwd=root)
    assert scopes == [FileScope(path=_p(root / "src" / "a.py"), names=[])]
    assert scopes[0].line() == f"Scope: {_p(root / 'src' / 'a.py')}: all"


def test_double_colon_narrows_its_file_only(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["src/a.py::f", "src/b.py"], cwd=root)
    assert [(s.path, s.names) for s in scopes] == [(_p(root / "src" / "a.py"), ["f"]),
                                                  (_p(root / "src" / "b.py"), [])]
    assert scopes[0].line().endswith(": f")


@pytest.mark.cross_os
def test_absolute_token_with_double_colon_keeps_the_drive(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, [f"{root / 'src' / 'a.py'}::g"], cwd=root)
    assert [(s.path, s.names) for s in scopes] == [(_p(root / "src" / "a.py"), ["g"])]


def test_bare_symbols_narrow_a_single_file(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["src/a.py", "f", "g"], cwd=root)
    assert scopes == [FileScope(path=_p(root / "src" / "a.py"), names=["f", "g"])]
    assert scopes[0].line().endswith(": f, g")


@pytest.mark.cross_os
def test_relative_tokens_resolve_against_cwd(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["a.py"], cwd=root / "src")
    assert scopes[0].path == _p(root / "src" / "a.py")


def test_bare_symbols_with_two_files_are_refused(make_project) -> None:
    root = _project(make_project)
    problems = _problems(root, "src/a.py", "src/b.py", "zz_sym")
    assert len(problems) == 1 and "zz_sym" in problems[0]


def test_one_file_named_bare_and_narrowed_is_refused(make_project) -> None:
    root = _project(make_project)
    problems = _problems(root, "src/a.py", "src/a.py::f")
    assert len(problems) == 1 and "a.py" in problems[0]


def test_a_file_named_twice_is_one_scope(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["src/a.py", "./src/a.py"], cwd=root)
    assert scopes == [FileScope(path=_p(root / "src" / "a.py"), names=[])]


def test_double_colon_names_of_one_file_merge(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["src/a.py::f", "src/a.py::g", "src/a.py::f"], cwd=root)
    assert scopes == [FileScope(path=_p(root / "src" / "a.py"), names=["f", "g"])]


def test_a_directory_and_a_file_in_it_are_one_scope_per_file(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["src", "src/a.py"], cwd=root)
    assert [(s.path, s.names) for s in scopes] == [(_p(root / "src" / "a.py"), []),
                                                  (_p(root / "src" / "b.py"), [])]


def test_a_directory_and_a_narrowed_file_in_it_are_refused(make_project) -> None:
    root = _project(make_project)
    problems = _problems(root, "src", "src/a.py::f")
    assert len(problems) == 1 and "a.py" in problems[0]


def test_scopes_come_in_path_order(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["src/b.py", "src/a.py"], cwd=root)
    assert [s.path for s in scopes] == [_p(root / "src" / "a.py"), _p(root / "src" / "b.py")]


@pytest.mark.cross_os
def test_directory_expands_to_tracked_python_files_recursively(make_project) -> None:
    root = make_project(files={"src/a.py": A, "src/b.py": B, "src/sub/c.py": A, "src/notes.md": "# n\n"})
    (root / "src" / "untracked.py").write_text(A, encoding="utf-8")
    scopes = resolve_scope(root, ["src"], cwd=root)
    assert [s.path for s in scopes] == [_p(root / "src" / "a.py"), _p(root / "src" / "b.py"),
                                        _p(root / "src" / "sub" / "c.py")]


def test_directory_without_tracked_python_files_is_refused(make_project) -> None:
    root = make_project(files={"docs/readme.md": "# readme\n"})
    problems = _problems(root, "docs")
    assert len(problems) == 1 and "docs" in problems[0]


def test_a_bare_symbol_named_like_a_folder_is_refused(make_project) -> None:
    root = make_project(files={"src/a.py": "def pkg():\n    return 1\n", "pkg/b.py": B})
    problems = _problems(root, "src/a.py", "pkg")
    assert len(problems) == 1 and "pkg" in problems[0]
    scopes = resolve_scope(root, ["src/a.py", "pkg/"], cwd=root)
    assert [s.path for s in scopes] == [_p(root / "pkg" / "b.py"), _p(root / "src" / "a.py")]


def test_unknown_symbol_is_refused_before_any_row(make_project) -> None:
    root = _project(make_project)
    problems = _problems(root, "src/a.py::nope")
    assert len(problems) == 1 and "nope" in problems[0]


def test_method_name_or_qualname_matches(make_project) -> None:
    root = _project(make_project)
    by_name = resolve_scope(root, ["src/b.py::h"], cwd=root)
    by_qualname = resolve_scope(root, ["src/b.py::C.h"], cwd=root)
    assert by_name[0].names == ["h"] and by_qualname[0].names == ["C.h"]


def test_unparsable_file_is_refused(make_project) -> None:
    root = make_project(files={"src/bad.py": "def broken(:\n"})
    problems = _problems(root, "src/bad.py")
    assert len(problems) == 1 and "bad.py" in problems[0]


def test_missing_path_is_refused(make_project) -> None:
    root = _project(make_project)
    problems = _problems(root, "src/zzz.py")
    assert len(problems) == 1 and "zzz.py" in problems[0]


def test_missing_path_with_a_bare_symbol_reports_only_the_path(make_project) -> None:
    root = _project(make_project)
    problems = _problems(root, "src/zzz.py", "f")
    assert len(problems) == 1 and "zzz.py" in problems[0]


def test_non_python_file_is_refused(make_project) -> None:
    root = _project(make_project)
    problems = _problems(root, "src/notes.md")
    assert len(problems) == 1 and "notes.md" in problems[0]


@pytest.mark.cross_os
def test_path_outside_the_project_is_refused(make_project, tmp_path: Path) -> None:
    root = _project(make_project)
    outside = tmp_path / "elsewhere.py"
    outside.write_text(A, encoding="utf-8")
    problems = _problems(root, str(outside))
    assert len(problems) == 1 and "elsewhere.py" in problems[0]


def test_every_defect_is_reported_together(make_project) -> None:
    root = _project(make_project)
    problems = _problems(root, "src/zzz.py", "src/a.py::nope")
    assert len(problems) == 2


def test_first_path_skips_bare_symbols_and_strips_names(make_project) -> None:
    root = _project(make_project)
    assert first_path(["f", "src/a.py::f", "src/b.py"], cwd=root) == (root / "src" / "a.py").resolve()
    assert first_path(["f", "g"], cwd=root) is None


def test_one_row_without_parallel(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["src/a.py", "src/b.py"], cwd=root)
    rows = plan_rows(root, scopes, new_docstrings=False, parallel=False)
    assert len(rows) == 1
    assert rows[0].model == WORK_MODEL and rows[0].scopes == scopes and not rows[0].probe


def test_one_row_per_file_with_parallel(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["src/a.py", "src/b.py"], cwd=root)
    rows = plan_rows(root, scopes, new_docstrings=True, parallel=True)
    assert [row.scopes for row in rows] == [[scopes[0]], [scopes[1]]]
    assert all(row.new_docstrings and row.model == WORK_MODEL for row in rows)


def test_parallel_over_one_file_is_one_row(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["src/a.py"], cwd=root)
    assert len(plan_rows(root, scopes, new_docstrings=False, parallel=True)) == 1


@pytest.mark.cross_os
def test_row_text_is_the_header_then_the_prompt_lines(make_project) -> None:
    root = _project(make_project)
    scopes = resolve_scope(root, ["src/a.py::f", "src/b.py"], cwd=root)
    row = plan_rows(root, scopes, new_docstrings=False, parallel=False)[0]
    assert row.text() == "\n".join([
        f"agent={AGENT} model={WORK_MODEL}",
        f"Project root: {_p(root)}",
        "New docstrings: no",
        f"Scope: {_p(root / 'src' / 'a.py')}: f",
        f"Scope: {_p(root / 'src' / 'b.py')}: all",
    ])


def test_probes_go_beside_each_folder(make_project) -> None:
    root = make_project(files={"src/a.py": A, "src/b.py": A, "pkg/c.py": B})
    scopes = resolve_scope(root, ["src/a.py", "src/b.py", "pkg/c.py"], cwd=root)
    probes = write_probes(root, scopes, _record(root))
    assert probes == [root.resolve() / "pkg" / PROBE_NAME, root.resolve() / "src" / PROBE_NAME]
    assert all(probe.read_text(encoding="utf-8") == PROBE_SOURCE for probe in probes)
    assert _record(root).is_file()


def test_probe_beside_an_unrecorded_untracked_file_of_that_name_is_refused(make_project) -> None:
    root = make_project(files={"src/a.py": A, "pkg/c.py": B})
    scopes = resolve_scope(root, ["src/a.py", "pkg/c.py"], cwd=root)
    (root / "src" / PROBE_NAME).write_text("mine = True\n", encoding="utf-8")
    with pytest.raises(DispatchError) as caught:
        write_probes(root, scopes, _record(root))
    assert caught.value.problems == [f"{(root.resolve() / 'src' / PROBE_NAME).as_posix()}: a file named "
                                     f"{PROBE_NAME} exists here; remove it or run without -p"]
    assert (root / "src" / PROBE_NAME).read_text(encoding="utf-8") == "mine = True\n"
    assert not (root / "pkg" / PROBE_NAME).exists()
    assert not _record(root).exists()


def test_probe_beside_a_tracked_file_of_that_name_is_refused(make_project) -> None:
    root = make_project(files={"src/a.py": A, "src/b.py": A, f"src/{PROBE_NAME}": "kept = 1\n"})
    scopes = resolve_scope(root, ["src/a.py", "src/b.py"], cwd=root)
    with pytest.raises(DispatchError) as caught:
        write_probes(root, scopes, _record(root))
    assert PROBE_NAME in caught.value.problems[0]
    assert (root / "src" / PROBE_NAME).read_text(encoding="utf-8") == "kept = 1\n"
    assert not _record(root).exists()


def test_probe_row_asks_for_a_new_docstring_on_each_probe_file(make_project) -> None:
    root = make_project(files={"src/a.py": A, "pkg/c.py": B})
    probes = write_probes(root, resolve_scope(root, ["src/a.py", "pkg/c.py"], cwd=root), _record(root))
    row = probe_row(root, probes)
    assert row.model == PROBE_MODEL and row.new_docstrings and row.probe
    assert row.scopes == [FileScope(path=_p(probe), names=[]) for probe in probes]
    assert row.text().splitlines()[-1] == "Probe: yes"


def test_clear_probes_removes_only_recorded_probes_under_the_project(make_project, tmp_path: Path) -> None:
    root = _project(make_project)
    probes = write_probes(root, resolve_scope(root, ["src/a.py", "src/b.py"], cwd=root), _record(root))
    outside = tmp_path / PROBE_NAME
    outside.write_text("x = 1\n", encoding="utf-8")
    with _record(root).open("a", encoding="utf-8") as handle:
        handle.write(f"{outside.as_posix()}\n{(root / 'src' / 'a.py').as_posix()}\n")
    assert clear_probes(root, _record(root)) == probes
    assert not any(probe.exists() for probe in probes)
    assert outside.is_file() and (root / "src" / "a.py").is_file()
    assert not _record(root).exists()
    assert clear_probes(root, _record(root)) == []


def test_clear_probes_keeps_a_recorded_tracked_probe_named_file(make_project) -> None:
    root = make_project(files={"src/a.py": A, f"src/{PROBE_NAME}": "kept = 1\n"})
    tracked = root / "src" / PROBE_NAME
    _record(root).parent.mkdir(parents=True, exist_ok=True)
    _record(root).write_text(f"{_p(tracked)}\n", encoding="utf-8")
    assert clear_probes(root, _record(root)) == []
    assert tracked.read_text(encoding="utf-8") == "kept = 1\n"
    assert not _record(root).exists()


def test_dispatch_models_forbid_extra_keys() -> None:
    scope = {"path": "C:/p/a.py", "names": []}
    FileScope.model_validate(scope)
    with pytest.raises(ValidationError):
        FileScope.model_validate({**scope, "unexpected": 1})
    row = {"model": WORK_MODEL, "project_root": "C:/p", "new_docstrings": False, "scopes": [scope]}
    DispatchRow.model_validate(row)
    with pytest.raises(ValidationError):
        DispatchRow.model_validate({**row, "unexpected": 1})
    with pytest.raises(ValidationError):
        DispatchRow.model_validate({**row, "scopes": []})
