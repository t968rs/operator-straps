"""Tests for the git_status_filter_excluded script: explicit exclusions files and the project default."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "plugins" / "harness" / "lib" / "harness_lib" / "git_status_filter_excluded.py"


def test_filters_matching_patterns(tmp_path: Path) -> None:
    """Lines whose paths match an exclusion pattern are filtered out."""
    excl_json = tmp_path / "exclusions.json"
    excl_json.write_text(
        json.dumps(
            {
                "exclusions": [
                    {"pattern": "*.md"},
                    {"pattern": "docs/PR_SUMMARIES/*"},
                ]
            }
        ),
        encoding="utf-8",
    )

    stdin = "M  README.md\nM  docs/PR_SUMMARIES/test.md\nM  scripts/foo.py\n"
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            str(excl_json),
        ],
        input=stdin,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == "M  scripts/foo.py\n"


def test_passes_non_matching_lines(tmp_path: Path) -> None:
    """Lines whose paths do not match are passed through verbatim."""
    excl_json = tmp_path / "exclusions.json"
    excl_json.write_text(
        json.dumps({"exclusions": [{"pattern": "docs/PR_REVIEWS/*_*.json"}]}),
        encoding="utf-8",
    )

    stdin = "M  scripts/fpm/foo.py\nM  tests/test_bar.py\n"
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            str(excl_json),
        ],
        input=stdin,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == stdin


def test_empty_input(tmp_path: Path) -> None:
    """Empty input produces empty output."""
    excl_json = tmp_path / "exclusions.json"
    excl_json.write_text(
        json.dumps({"exclusions": [{"pattern": "*.json"}]}), encoding="utf-8"
    )

    stdin = ""
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            str(excl_json),
        ],
        input=stdin,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_missing_json(tmp_path: Path) -> None:
    """Missing exclusions JSON exits non-zero and writes to stderr."""
    missing = tmp_path / "missing.json"

    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            str(missing),
        ],
        input="M  foo.py\n",
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Error" in result.stderr


def test_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON exits non-zero and writes to stderr."""
    excl_json = tmp_path / "bad.json"
    excl_json.write_text("{invalid json", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            str(excl_json),
        ],
        input="M  foo.py\n",
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Error" in result.stderr


def test_first_match_wins(tmp_path: Path) -> None:
    """Multiple patterns; filtering stops at first match."""
    excl_json = tmp_path / "exclusions.json"
    excl_json.write_text(
        json.dumps(
            {
                "exclusions": [
                    {"pattern": "*.json"},
                    {"pattern": "docs/*"},
                    {"pattern": "scripts/*"},
                ]
            }
        ),
        encoding="utf-8",
    )

    stdin = "M  config.json\nM  docs/file.md\nM  scripts/foo.py\nM  test.py\n"
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            str(excl_json),
        ],
        input=stdin,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == "M  test.py\n"


_EXCLUSIONS = {"exclusions": [{"pattern": "docs/PR_REVIEWS/*"}]}
_STATUS = "M  docs/PR_REVIEWS/1_x.json\nM  src/a.py\n"


def _run_default(cwd: Path, *args: str, stdin: str = _STATUS) -> subprocess.CompletedProcess:
    """Run the filter with no exclusions argument from ``cwd``."""
    return subprocess.run([sys.executable, str(_SCRIPT), *args], input=stdin, capture_output=True,
                          text=True, cwd=cwd)


def _project(make_project: Callable[..., Path], exclusions: Optional[str]) -> Path:
    """Project whose ``harness.json`` sets ``exclusions``, with the exclusions file committed."""
    return make_project(config={"exclusions": exclusions},
                        files={"meta/exclusions.json": _EXCLUSIONS})


class TestProjectDefault:
    def test_configured_exclusions_apply(self, make_project: Callable[..., Path]) -> None:
        root = _project(make_project, "meta/exclusions.json")
        result = _run_default(root)
        assert (result.returncode, result.stdout) == (0, "M  src/a.py\n")

    def test_repo_flag_selects_project(self, make_project: Callable[..., Path], tmp_path: Path) -> None:
        root = _project(make_project, "meta/exclusions.json")
        result = _run_default(tmp_path, "--repo", str(root), "--paths-only",
                              stdin="docs/PR_REVIEWS/1_x.json\nsrc/a.py\n")
        assert (result.returncode, result.stdout) == (0, "src/a.py\n")

    def test_null_exclusions_pass_everything(self, make_project: Callable[..., Path]) -> None:
        result = _run_default(_project(make_project, None))
        assert (result.returncode, result.stdout) == (0, _STATUS)

    def test_configured_file_missing_is_an_error(self, make_project: Callable[..., Path]) -> None:
        result = _run_default(_project(make_project, "meta/absent.json"))
        assert result.returncode == 1
        assert "absent.json" in result.stderr

    def test_malformed_project_config_is_an_error(self, make_project: Callable[..., Path]) -> None:
        root = make_project(files={".claude/harness.json": "{not json"})
        result = _run_default(root)
        assert result.returncode == 1
        assert result.stderr.startswith("Error: ")
        assert "Traceback" not in result.stderr


class TestConfiguredExclusionsInProcess:
    def test_returns_path_without_switching_active_project(self, make_project: Callable[..., Path]) -> None:
        from harness_lib.config import activate, active, load_config
        from harness_lib.git_status_filter_excluded import configured_exclusions

        first = make_project(config={"exclusions": None}, name="first")
        other = _project(make_project, "meta/exclusions.json")
        activate(load_config(first))
        found = configured_exclusions(other)
        assert found == load_config(other).path("meta/exclusions.json")
        assert active().project_root == load_config(first).project_root

    def test_disabled_exclusions_return_none(self, make_project: Callable[..., Path]) -> None:
        from harness_lib.git_status_filter_excluded import configured_exclusions

        assert configured_exclusions(_project(make_project, None)) is None
