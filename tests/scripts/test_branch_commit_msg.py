"""Behavioral tests for the plugin's ``scripts/branch_commit_msg.py`` (capture + build driver).

The script is loaded by absolute path (``scripts/`` is not on ``sys.path``). Git-backed tests get an
upstream project (floodplain-shaped ``harness.json``, base branch ``main``) and a clone carrying branch
work, both copied from a module template built once, then activate the clone's configuration. The
script's git capture runs through ``harness_lib.branch_capture``, so these tests also guard its
working-tree mode.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable, Dict, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from _commit_helpers import FPM_CONFIG, REGISTRY, activate_copy, fpm_template  # noqa: E402
from conftest import copy_project, project_factory  # noqa: E402
from harness_lib import commit_diff  # noqa: E402
from harness_lib.branch_commits import BranchCommitDocument, Bucket, CommitEntry  # noqa: E402
from harness_lib.config import activate, active, load_config  # noqa: E402

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "false",
}
_UNPARSEABLE_TXT = (
    "Branch: `9999-demo`\n\n===\n\n"
    "Commit 1 - Bogus (1 files)\n"
    "\"a\",\n"
)
_BASE_FILES = {"scripts/fpm/io/a.py": "x\n", "docs/old.md": "x\n", "README.md": "x\n"}
# Registry whose only entry pairs a test with a source its name does not match.
_ODD_REGISTRY = (
    '{"tests": [{"file": "scripts/__tests__/test_odd.py",'
    ' "properties": {"test_target_paths": ["scripts/fpm/io/a.py"]}}]}'
)


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> ModuleType:
    """Import branch_commit_msg.py by absolute path."""
    path = plugin_root / "scripts" / "branch_commit_msg.py"
    spec = importlib.util.spec_from_file_location("branch_commit_msg_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def _fpm_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return fpm_template(tmp_path_factory.mktemp("fpm"))


@pytest.fixture(autouse=True)
def _fpm_project(_fpm_template: Path, tmp_path: Path) -> None:
    """Tests without a clone run against a copy of the floodplain-shaped project."""
    activate_copy(_fpm_template, tmp_path)


def _git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd`` with a fixed identity; return stdout."""
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env={**os.environ, **_GIT_ENV},
    )
    return result.stdout.strip()


def _write(root: Path, rel: str, text: str = "x\n") -> None:
    """Write ``text`` to ``root/rel``, creating parents."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _clone(upstream: Path, tmp_path: Path) -> Path:
    """Clone ``upstream``, check out branch ``9999-demo`` and activate the clone's configuration."""
    clone = tmp_path / "work"
    _git(tmp_path, "clone", str(upstream), str(clone))
    _git(clone, "checkout", "-b", "9999-demo")
    activate(load_config(clone))
    return clone


def _build_work(parent: Path) -> str:
    """``parent/upstream`` and its clone ``parent/work`` as ``work`` describes; the upstream main SHA."""
    upstream = project_factory(parent)(config=FPM_CONFIG, files=dict(_BASE_FILES), name="upstream")
    clone = parent / "work"
    _git(parent, "clone", str(upstream), str(clone))
    _git(clone, "checkout", "-b", "9999-demo")
    _write(clone, "scripts/fpm/io/a.py", "changed\n")
    _git(clone, "commit", "-am", "wip")
    _git(clone, "mv", "docs/old.md", "docs/new.md")
    _write(clone, "scripts/__tests__/test_a.py")
    return _git(upstream, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def work_template(tmp_path_factory: pytest.TempPathFactory) -> Tuple[Path, str]:
    """The upstream and clone built once per module; ``work`` copies them and never writes here."""
    parent = tmp_path_factory.mktemp("work_template")
    return parent, _build_work(parent)


@pytest.fixture()
def work(work_template: Tuple[Path, str], tmp_path: Path) -> Tuple[Path, str]:
    """Clone of an upstream ``main`` with branch ``9999-demo`` holding committed, unstaged and untracked work.

    Both repos are copies of the template, with the clone's ``origin`` re-pointed at the copied upstream;
    the clone's configuration is activated. Returns (work tree, upstream main SHA).
    """
    template, base = work_template
    upstream = copy_project(template / "upstream", tmp_path)
    clone = copy_project(template / "work", tmp_path)
    _git(clone, "remote", "set-url", "origin", str(upstream))
    activate(load_config(clone))
    return clone, base


def _use_artifacts(commit_messages: str) -> None:
    """Re-activate the current configuration with another ``commit_messages`` directory."""
    cfg = active()
    artifacts = dataclasses.replace(cfg.artifacts, commit_messages=commit_messages)
    activate(dataclasses.replace(cfg, artifacts=artifacts))


def _filled(payload: Dict[str, object]) -> Dict[str, object]:
    """Give every skeleton commit a valid message."""
    commits = {
        key: [paths, f"Chore: commit {key}\n\nWhy.\n  - x: y"]
        for key, (paths, _) in payload["commits"].items()
    }
    return {**payload, "commits": commits}


class TestDocumentFromCommitDict:
    def test_renumbers_and_derives_buckets(self, script: ModuleType) -> None:
        commits = {
            5: (["docs/a.md"], "Docs: add a"),
            2: (["scripts/fpm/a.py", "scripts/__tests__/test_a.py"], "Feature(a): x"),
        }
        document = script.document_from_commit_dict(commits, "b", "m", ["Split: none"])
        assert sorted(document.commits) == [1, 2]
        assert document.commits[1].bucket is Bucket.RUNTIME_TEST
        assert document.commits[2].bucket is Bucket.DOCS
        assert document.commits[2].header == "Docs: add a"
        assert document.notes == ["Split: none"]

    def test_shared_path_reported_by_validate(self, script: ModuleType) -> None:
        commits = {1: (["a.py"], "Chore: a"), 2: (["a.py"], "Chore: b")}
        document = script.document_from_commit_dict(commits, "b", "m", [])
        with pytest.raises(ValueError, match="a.py"):
            document.validate()


class TestGitCapture:
    def test_merge_base_from_fetched_base(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, base = work
        assert script.resolve_merge_base(clone, "main", fetch=True) == base

    def test_capture_resolves_base_from_origin_head(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, base = work
        assert script.run_capture(clone, fetch=True)["merge_base"] == base

    def test_capture_uses_configured_base_branch(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        activate(dataclasses.replace(active(), base_branch="trunk"))
        with pytest.raises(script.BuildError, match="fetch origin trunk"):
            script.run_capture(clone, fetch=True)

    def test_capture_pairs_from_registry_targets(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        _write(clone, REGISTRY, _ODD_REGISTRY)
        _write(clone, "scripts/__tests__/test_odd.py")
        payload = script.run_capture(clone, fetch=False)
        assert [paths for paths, _ in payload["commits"].values()][:2] == [
            [REGISTRY],
            ["scripts/fpm/io/a.py", "scripts/__tests__/test_a.py", "scripts/__tests__/test_odd.py"],
        ]

    def test_unconfigured_registry_never_pairs(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        activate(dataclasses.replace(active(), tests=dataclasses.replace(active().tests, registry=None)))
        _write(clone, REGISTRY, _ODD_REGISTRY)
        _write(clone, "scripts/__tests__/test_odd.py")
        payload = script.run_capture(clone, fetch=False)
        assert ["scripts/__tests__/test_odd.py"] in [paths for paths, _ in payload["commits"].values()]

    def test_capture_payload(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, base = work
        payload = script.run_capture(clone, fetch=False)
        assert (payload["branch"], payload["merge_base"]) == ("9999-demo", base)
        assert list(payload["commits"].values()) == [
            [["scripts/fpm/io/a.py", "scripts/__tests__/test_a.py"], ""],
            [["docs/new.md", "docs/old.md"], ""],
        ]
        assert payload["split"].startswith("none")

    def test_capture_carries_existing_message(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = _filled(script.run_capture(clone, fetch=False))
        script.run_build(clone, payload)
        again = script.run_capture(clone, fetch=False)
        assert [message for _, message in again["commits"].values()] == [
            message for _, message in payload["commits"].values()
        ]


class TestCaptureFresh:
    def test_fresh_ignores_existing_message(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        script.run_build(clone, _filled(script.run_capture(clone, fetch=False)))
        again = script.run_capture(clone, fetch=False, fresh=True)
        assert [message for _, message in again["commits"].values()] == ["", ""]

    def test_fresh_replans_non_rule_grouping(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = script.run_capture(clone, fetch=False)
        everything = [path for paths, _ in payload["commits"].values() for path in paths]
        first = next(iter(payload["commits"]))
        one_block = {first: [everything, "Chore: one block\n\nWhy.\n  - x: y"]}
        script.run_build(clone, {**payload, "commits": one_block})
        carried = script.run_capture(clone, fetch=False)
        assert [paths for paths, _ in carried["commits"].values()] == [everything]
        fresh = script.run_capture(clone, fetch=False, fresh=True)
        assert list(fresh["commits"].values()) == list(payload["commits"].values())

    def test_fresh_ignores_unparseable_txt(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        _write(clone, "docs/_commit_messages/9999-demo.txt", _UNPARSEABLE_TXT)
        fresh = script.run_capture(clone, fetch=False, fresh=True)
        assert list(fresh["commits"].values()) == [
            [["scripts/fpm/io/a.py", "scripts/__tests__/test_a.py"], ""],
            [["docs/new.md", "docs/old.md"], ""],
        ]

    def test_cli_accepts_fresh_flag(self, script: ModuleType) -> None:
        args = script._parser().parse_args(["capture", "--fresh"])
        assert args.fresh is True


class TestCaptureBase:
    def _head(self, clone: Path) -> str:
        return _git(clone, "rev-parse", "HEAD")

    def test_base_ref_resolves_to_sha(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = script.run_capture(clone, base="HEAD", fetch=False)
        assert payload["merge_base"] == self._head(clone)

    def test_unknown_base_is_a_problem(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        with pytest.raises(script.BuildError, match="no-such-ref"):
            script.run_capture(clone, base="no-such-ref", fetch=False)

    def test_base_without_fresh_names_a_sibling_file(
            self, script: ModuleType, work: Tuple[Path, str],
    ) -> None:
        clone, _ = work
        payload = script.run_capture(clone, base="HEAD", fetch=False)
        assert payload["txt_suffix"] == f"_{self._head(clone)[:7]}"

    def test_base_with_fresh_still_names_a_sibling_file(
            self, script: ModuleType, work: Tuple[Path, str],
    ) -> None:
        clone, _ = work
        payload = script.run_capture(clone, base="HEAD", fetch=False, fresh=True)
        assert payload["txt_suffix"] == f"_{self._head(clone)[:7]}"

    def test_build_of_fresh_based_capture_spares_branch_txt(
            self, script: ModuleType, work: Tuple[Path, str],
    ) -> None:
        clone, _ = work
        script.run_build(clone, _filled(script.run_capture(clone, fetch=False)))
        ledger = clone / "docs" / "_commit_messages" / "9999-demo.txt"
        before = ledger.read_text(encoding="utf-8")
        payload = _filled(script.run_capture(clone, base="HEAD", fetch=False, fresh=True))
        out, _ = script.run_build(clone, payload)
        assert out == clone / "docs" / "_commit_messages" / f"9999-demo_{self._head(clone)[:7]}.txt"
        assert ledger.read_text(encoding="utf-8") == before

    def test_no_base_keeps_branch_name(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        assert "txt_suffix" not in script.run_capture(clone, fetch=False)

    def test_build_writes_sibling_txt_and_spares_branch_txt(
            self, script: ModuleType, work: Tuple[Path, str],
    ) -> None:
        clone, _ = work
        script.run_build(clone, _filled(script.run_capture(clone, fetch=False)))
        ledger = clone / "docs" / "_commit_messages" / "9999-demo.txt"
        before = ledger.read_text(encoding="utf-8")
        payload = _filled(script.run_capture(clone, base="HEAD", fetch=False))
        out, _ = script.run_build(clone, payload)
        assert out == clone / "docs" / "_commit_messages" / f"9999-demo_{self._head(clone)[:7]}.txt"
        assert ledger.read_text(encoding="utf-8") == before

    def test_based_capture_carries_branch_txt_messages(
            self, script: ModuleType, work: Tuple[Path, str],
    ) -> None:
        clone, _ = work
        script.run_build(clone, _filled(script.run_capture(clone, fetch=False)))
        payload = script.run_capture(clone, base="HEAD", fetch=False)
        docs = payload["commits"][str(_block_of(payload, "docs/new.md"))]
        assert docs[1].startswith("Chore: commit")

    def test_explicit_out_overrides_the_sibling_name(
            self, script: ModuleType, work: Tuple[Path, str], tmp_path: Path,
    ) -> None:
        clone, _ = work
        target = tmp_path / "chosen.txt"
        payload = _filled(script.run_capture(clone, base="HEAD", fetch=False))
        out, _ = script.run_build(clone, payload, target)
        assert out == target

    @pytest.mark.parametrize("abbrev", [40, 9])
    def test_upstream_sha_base_captures_committed_work(
            self, script: ModuleType, work: Tuple[Path, str], abbrev: int,
    ) -> None:
        clone, base = work
        payload = script.run_capture(clone, base=base[:abbrev], fetch=False)
        assert (payload["merge_base"], payload["txt_suffix"]) == (base, f"_{base[:7]}")
        assert "scripts/fpm/io/a.py" in [entry["path"] for entry in payload["captured"]]

    def test_branch_name_base_resolves_to_its_sha(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, base = work
        assert script.run_capture(clone, base="main", fetch=False)["merge_base"] == base

    def test_recapture_prefers_the_sibling_txt(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        script.run_build(clone, _filled(script.run_capture(clone, fetch=False)))
        slice_payload = script.run_capture(clone, base="HEAD", fetch=False)
        commits = {
            key: [paths, f"Chore: slice {key}\n\nWhy.\n  - x: y"]
            for key, (paths, _) in slice_payload["commits"].items()
        }
        script.run_build(clone, {**slice_payload, "commits": commits})
        again = script.run_capture(clone, base="HEAD", fetch=False)
        assert [message for _, message in again["commits"].values()] == [
            message for _, message in commits.values()
        ]

    @pytest.mark.parametrize("suffix", ["_../../x", "_0000000", "_ABCDEFG"])
    def test_build_rejects_a_tampered_suffix(
            self, script: ModuleType, work: Tuple[Path, str], suffix: str,
    ) -> None:
        clone, _ = work
        payload = _filled(script.run_capture(clone, base="HEAD", fetch=False))
        with pytest.raises(script.BuildError, match="txt_suffix"):
            script.run_build(clone, {**payload, "txt_suffix": suffix})
        assert not list((clone / "docs" / "_commit_messages").glob("9999-demo_*.txt"))


class TestCaptureOutput:
    def test_unparseable_existing_txt_is_reported(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        _write(clone, "docs/_commit_messages/9999-demo.txt", _UNPARSEABLE_TXT)
        with pytest.raises(script.BuildError, match="9999-demo.txt"):
            script.run_capture(clone, fetch=False)

    def test_write_skeleton_creates_missing_directories(self, script: ModuleType, tmp_path: Path) -> None:
        out = tmp_path / "docs" / "_commit_messages" / "b.json"
        script.write_skeleton(out, {"branch": "b"})
        assert out.read_text(encoding="utf-8").startswith('{\n  "branch": "b"')

    def test_configured_output_dir_is_left_out_of_capture(
            self, script: ModuleType, work: Tuple[Path, str],
    ) -> None:
        clone, _ = work
        _use_artifacts("notes/commits")
        _write(clone, "notes/commits/9999-demo.json", "{}\n")
        _write(clone, "docs/_commit_messages/other.txt", "x\n")
        captured = [c["path"] for c in script.run_capture(clone, fetch=False)["captured"]]
        assert "notes/commits/9999-demo.json" not in captured
        assert "docs/_commit_messages/other.txt" in captured


class TestGenericProject:
    def test_default_buckets_pair_src_and_tests(
            self, script: ModuleType, make_project: Callable[..., Path], tmp_path: Path,
    ) -> None:
        upstream = make_project(files={"src/pkg/a.py": "x\n"}, name="plain")
        clone = _clone(upstream, tmp_path)
        _write(clone, "src/pkg/a.py", "changed\n")
        _write(clone, "tests/pkg/test_a.py")
        _write(clone, "docs/guide.md")
        payload = script.run_capture(clone, fetch=False)
        assert [paths for paths, _ in payload["commits"].values()] == [
            ["src/pkg/a.py", "tests/pkg/test_a.py"], ["docs/guide.md"],
        ]
        assert [c["bucket"] for c in payload["captured"]] == ["Docs", "Runtime", "Test"]


class TestCli:
    def _main(self, script: ModuleType, *argv: str) -> int:
        return script.main(list(argv))

    def test_runs_as_a_standalone_script(self, plugin_root: Path, work: Tuple[Path, str]) -> None:
        clone, base = work
        done = subprocess.run([sys.executable, str(plugin_root / "scripts" / "branch_commit_msg.py"),
                               "capture", "--no-fetch"], cwd=clone, capture_output=True, text=True,
                              encoding="utf-8")
        assert done.returncode == 0, done.stderr
        assert f'"merge_base": "{base}"' in done.stdout

    def test_repo_flag_activates_that_project(
            self, script: ModuleType, work: Tuple[Path, str], tmp_path: Path,
    ) -> None:
        clone, base = work
        out = tmp_path / "skeleton.json"
        assert self._main(script, "--repo", str(clone), "capture", "--no-fetch", "--out", str(out)) == 0
        assert active().project_root == clone.resolve()
        assert f'"merge_base": "{base}"' in out.read_text(encoding="utf-8")

    def test_repo_flag_after_subcommand(
            self, script: ModuleType, work: Tuple[Path, str], tmp_path: Path,
    ) -> None:
        clone, base = work
        out = tmp_path / "skeleton.json"
        assert self._main(script, "capture", "--no-fetch", "--repo", str(clone), "--out", str(out)) == 0
        assert active().project_root == clone.resolve()
        assert f'"merge_base": "{base}"' in out.read_text(encoding="utf-8")

    def test_repo_flag_on_build_and_diff(self, script: ModuleType) -> None:
        for argv in (["build", "s.json", "--repo", "r"], ["diff", "s.json", "--block", "1", "--repo", "r"]):
            assert script._parser().parse_args(argv).repo == Path("r")

    def test_top_level_repo_survives_subcommand_default(self, script: ModuleType) -> None:
        assert script._parser().parse_args(["--repo", "r", "capture"]).repo == Path("r")

    def test_invalid_project_config_is_a_problem_line(
            self, script: ModuleType, make_project: Callable[..., Path], capsys: pytest.CaptureFixture,
    ) -> None:
        root = make_project(files={".claude/harness.json": "{not json"}, name="broken")
        assert self._main(script, "--repo", str(root), "capture", "--no-fetch") == 1
        err = capsys.readouterr().err
        assert err.startswith("problem: ") and "harness.json" in err

    def test_save_writes_skeleton_into_commit_messages_dir(
            self, script: ModuleType, make_project: Callable[..., Path], tmp_path: Path,
            capsys: pytest.CaptureFixture,
    ) -> None:
        config = {**FPM_CONFIG, "artifacts": {"commit_messages": "notes/commits"}}
        clone = _clone(make_project(config=config, files=dict(_BASE_FILES), name="saved"), tmp_path)
        _write(clone, "docs/new.md")
        assert self._main(script, "--repo", str(clone), "capture", "--no-fetch", "--save") == 0
        target = clone / "notes" / "commits" / "9999-demo.json"
        assert capsys.readouterr().out.strip() == f"wrote {target.resolve().as_posix()}"
        assert '"branch": "9999-demo"' in target.read_text(encoding="utf-8")

    def test_save_pending_uses_pending_name(
            self, script: ModuleType, work: Tuple[Path, str], capsys: pytest.CaptureFixture,
    ) -> None:
        clone, _ = work
        assert self._main(script, "--repo", str(clone), "capture", "--pending", "--save") == 0
        target = clone / "docs" / "_commit_messages" / "9999-demo_pending.json"
        assert target.is_file()
        assert capsys.readouterr().out.strip().endswith("9999-demo_pending.json")

    def test_save_with_base_uses_sibling_name(
            self, script: ModuleType, work: Tuple[Path, str],
    ) -> None:
        clone, _ = work
        sha = _git(clone, "rev-parse", "HEAD")
        argv = ("--repo", str(clone), "capture", "--no-fetch", "--base", "HEAD", "--save")
        assert self._main(script, *argv) == 0
        assert (clone / "docs" / "_commit_messages" / f"9999-demo_{sha[:7]}.json").is_file()
        assert not (clone / "docs" / "_commit_messages" / "9999-demo.json").exists()

    def test_save_pending_ignores_base(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        sha = _git(clone, "rev-parse", "HEAD")
        argv = ("--repo", str(clone), "capture", "--pending", "--base", "HEAD", "--save")
        assert self._main(script, *argv) == 0
        messages = clone / "docs" / "_commit_messages"
        assert (messages / "9999-demo_pending.json").is_file()
        assert not (messages / f"9999-demo_{sha[:7]}.json").exists()

    def test_save_with_base_and_fresh_uses_sibling_name(
            self, script: ModuleType, work: Tuple[Path, str],
    ) -> None:
        clone, _ = work
        sha = _git(clone, "rev-parse", "HEAD")
        argv = ("--repo", str(clone), "capture", "--no-fetch", "--base", "HEAD", "--fresh", "--save")
        assert self._main(script, *argv) == 0
        assert (clone / "docs" / "_commit_messages" / f"9999-demo_{sha[:7]}.json").is_file()
        assert not (clone / "docs" / "_commit_messages" / "9999-demo.json").exists()

    def test_build_of_based_skeleton_writes_sibling_txt(
            self, script: ModuleType, work: Tuple[Path, str], tmp_path: Path,
    ) -> None:
        clone, _ = work
        sha = _git(clone, "rev-parse", "HEAD")
        skeleton = tmp_path / "filled.json"
        payload = script.run_capture(clone, base="HEAD", fetch=False)
        script.write_skeleton(skeleton, _filled(payload))
        assert self._main(script, "--repo", str(clone), "build", str(skeleton)) == 0
        assert (clone / "docs" / "_commit_messages" / f"9999-demo_{sha[:7]}.txt").is_file()

    def test_save_and_out_are_exclusive(self, script: ModuleType) -> None:
        with pytest.raises(SystemExit):
            script._parser().parse_args(["capture", "--save", "--out", "x.json"])

    def test_build_writes_to_configured_dir(
            self, script: ModuleType, work: Tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        clone, _ = work
        skeleton = tmp_path / "filled.json"
        script.write_skeleton(skeleton, _filled(script.run_capture(clone, fetch=False)))
        assert self._main(script, "--repo", str(clone), "build", str(skeleton)) == 0
        assert (clone / "docs" / "_commit_messages" / "9999-demo.txt").is_file()
        assert capsys.readouterr().out.startswith("Saved: docs/_commit_messages/9999-demo.txt")


def _block_of(payload: Dict[str, object], path: str) -> int:
    """Return the commit key whose block holds ``path``."""
    return int(next(key for key, (paths, _) in payload["commits"].items() if path in paths))


def _counts(payload: Dict[str, object]) -> Dict[str, Tuple[int, int]]:
    """Map each captured path to its ``(added, deleted)`` counts."""
    return {c["path"]: (c["added"], c["deleted"]) for c in payload["captured"]}


class TestDiffBudget:
    def test_budget_split_follows_commit_diff(self) -> None:
        assert commit_diff.path_budget("scripts/fpm/io/a.py") == commit_diff.PATH_BUDGET
        assert commit_diff.path_budget("data/big.json") == commit_diff.JSON_PATH_BUDGET

    def test_capture_records_line_counts(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        counts = _counts(script.run_capture(clone, fetch=False))
        assert counts["scripts/fpm/io/a.py"] == (1, 1)
        assert counts["scripts/__tests__/test_a.py"] == (1, 0)
        assert counts["docs/new.md"] == (0, 0)

    def test_small_paths_are_read_in_full(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = script.run_capture(clone, fetch=False)
        out = script.run_diff(clone, payload, _block_of(payload, "scripts/fpm/io/a.py"))
        assert "=== scripts/fpm/io/a.py [full, +1 -1] ===" in out
        assert "+changed" in out

    def test_untracked_file_is_shown_as_additions(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = script.run_capture(clone, fetch=False)
        out = script.run_diff(clone, payload, _block_of(payload, "scripts/__tests__/test_a.py"))
        assert "=== scripts/__tests__/test_a.py [full, +1 -0] ===" in out
        assert "+x" in out

    def test_rename_stays_a_rename(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = script.run_capture(clone, fetch=False)
        out = script.run_diff(clone, payload, _block_of(payload, "docs/new.md"))
        assert "rename from docs/old.md" in out

    def test_large_json_is_summarized(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        body = "{\n" + "".join(f'  "k{n % 5}": {n},\n' for n in range(400)) + "}\n"
        _write(clone, "data/big.json", body)
        payload = script.run_capture(clone, fetch=False)
        out = script.run_diff(clone, payload, _block_of(payload, "data/big.json"))
        assert "=== data/big.json [summary, +402 -0] ===" in out
        assert "JSON diff summary" in out
        assert len(out.splitlines()) < 60

    def test_megabyte_single_line_is_clipped(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        _write(clone, "data/min.js", "v" * 1_000_000 + "\n")
        payload = script.run_capture(clone, fetch=False)
        out = script.run_diff(clone, payload, _block_of(payload, "data/min.js"))
        assert "=== data/min.js [full, +1 -0] ===" in out
        assert "[+" in out and len(out) < 2_000

    def test_block_output_is_capped(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        for n in range(8):
            _write(clone, f"data/f{n}.txt", "".join(f"{'k' * 190}{i}\n" for i in range(60)))
        payload = script.run_capture(clone, fetch=False)
        out = script.run_diff(clone, payload, _block_of(payload, "data/f0.txt"))
        assert len(out) < 45_000
        assert "[omitted: block output budget spent]" in out

    def test_unknown_block_is_reported(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = script.run_capture(clone, fetch=False)
        with pytest.raises(script.BuildError, match="block 99"):
            script.run_diff(clone, payload, 99)

    def test_glob_and_unmatched_entries_are_kept(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = script.run_capture(clone, fetch=False)
        block = _block_of(payload, "docs/new.md")
        payload["commits"][str(block)] = [["docs/*.md", "README.md", "nothing/*.py"], ""]
        out = script.run_diff(clone, payload, block)
        assert "=== docs/new.md [full, +0 -0] ===" in out
        assert "rename from docs/old.md" in out
        assert "=== README.md [no change captured] ===" in out
        assert "=== nothing/*.py [no change captured] ===" in out

    def test_untracked_binary_counts_zero(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        blob = clone / "data" / "blob.bin"
        blob.parent.mkdir(parents=True)
        blob.write_bytes(b"\x00\x01\x02\nline\n" * 50)
        payload = script.run_capture(clone, fetch=False)
        assert _counts(payload)["data/blob.bin"] == (0, 0)
        out = script.run_diff(clone, payload, _block_of(payload, "data/blob.bin"))
        assert "=== data/blob.bin [full, +0 -0] ===\nBinary file (untracked)" in out
        assert "\x00" not in out

    def test_untracked_nested_repo_is_captured(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        nested = clone / "nested"
        nested.mkdir()
        _git(nested, "init")
        _write(nested, "inner.txt")
        _git(nested, "add", "-A")
        _git(nested, "commit", "-m", "inner")
        payload = script.run_capture(clone, fetch=False)
        assert _counts(payload)["nested/"] == (0, 0)
        out = script.run_diff(clone, payload, _block_of(payload, "nested/"))
        assert "=== nested/ [full, +0 -0] ===\nNot a readable file (untracked)" in out

    def test_missing_merge_base_is_reported(self, script: ModuleType, tmp_path: Path) -> None:
        with pytest.raises(script.BuildError, match="merge_base"):
            script.run_diff(tmp_path, {"commits": {"1": [["a.py"], ""]}}, 1)

    @pytest.mark.parametrize("commits, match", [
        (["a.py"], "must be an object"),
        ({"one": [["a.py"], ""]}, "not an integer"),
        ({"1": "a.py"}, "not a \\[\\[paths"),
    ])
    def test_malformed_skeleton_is_reported(
            self, script: ModuleType, tmp_path: Path, commits: object, match: str,
    ) -> None:
        with pytest.raises(script.BuildError, match=match):
            script.run_diff(tmp_path, {"merge_base": "m", "commits": commits}, 1)

    def test_cli_diff_requires_block(self, script: ModuleType) -> None:
        with pytest.raises(SystemExit):
            script._parser().parse_args(["diff", "f.json"])


class TestBuild:
    def test_writes_round_trippable_txt(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, base = work
        out, document = script.run_build(clone, _filled(script.run_capture(clone, fetch=False)))
        assert out == clone / "docs" / "_commit_messages" / "9999-demo.txt"
        text = out.read_text(encoding="utf-8")
        assert text.startswith(f"Branch: `9999-demo`\nMerge base: {base}\nMessaged-through: ")
        assert "\nCommit 1 - Runtime+Test (2 files)\n" in text
        assert len(document.commits) == 2

    def test_writes_into_configured_commit_messages_dir(
            self, script: ModuleType, work: Tuple[Path, str],
    ) -> None:
        clone, _ = work
        _use_artifacts("notes/commits")
        out, _ = script.run_build(clone, _filled(script.run_capture(clone, fetch=False)))
        assert out == clone / "notes" / "commits" / "9999-demo.txt"
        assert not (clone / "docs" / "_commit_messages").exists()

    def test_receipt_lists_subjects(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = _filled(script.run_capture(clone, fetch=False))
        out, document = script.run_build(clone, payload)
        receipt = script.receipt(clone, out, document, payload["split"])
        assert receipt.splitlines() == [
            "Saved: docs/_commit_messages/9999-demo.txt - 2 commit(s) proposed",
            "1. Chore: commit 1",
            "2. Chore: commit 2",
            f"Split Decision: {payload['split']}",
        ]

    def test_rejects_uncovered_path_and_bad_message(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = _filled(script.run_capture(clone, fetch=False))
        payload["commits"]["2"] = [["docs/new.md"], "Plan: nope"]
        with pytest.raises(script.BuildError) as excinfo:
            script.run_build(clone, payload)
        problems = "\n".join(excinfo.value.problems)
        assert "docs/old.md" in problems
        assert "Plan: nope" in problems
        assert not (clone / "docs" / "_commit_messages" / "9999-demo.txt").exists()

    def test_failed_build_leaves_existing_txt_untouched(
            self, script: ModuleType, work: Tuple[Path, str],
    ) -> None:
        clone, _ = work
        target = clone / "docs" / "_commit_messages" / "9999-demo.txt"
        target.parent.mkdir(parents=True)
        target.write_text("previous breakdown\n", encoding="utf-8")
        payload = _filled(script.run_capture(clone, fetch=False))
        payload["commits"]["1"][1] = "Chore: a\n\nfirst\n---\nsecond"
        with pytest.raises(script.BuildError, match="---"):
            script.run_build(clone, payload)
        assert target.read_text(encoding="utf-8") == "previous breakdown\n"

    def test_rejects_branch_mismatch(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = {**_filled(script.run_capture(clone, fetch=False)), "branch": "other"}
        with pytest.raises(script.BuildError, match="branch"):
            script.run_build(clone, payload)


class TestSkeletonPayload:
    def test_round_trips_through_document(self, script: ModuleType) -> None:
        commits = {
            1: (["scripts/fpm/a.py", "scripts/__tests__/test_a.py"], "Feature(a): x"),
            2: (["docs/a.md"], ""),
        }
        document = script.document_from_commit_dict(commits, "b", "m")
        payload = script.skeleton_payload(document, "none", [])
        assert payload["commits"] == {"1": [list(commits[1][0]), "Feature(a): x"], "2": [["docs/a.md"], ""]}
        assert script._commit_dict(payload) == commits
        assert "pending" not in payload

    def test_pending_comes_from_document(self, script: ModuleType) -> None:
        commits = {1: (["docs/a.md"], "Docs: a\n\nWhy.")}
        document = script.document_from_commit_dict(commits, "b", "m", pending=True)
        payload = script.skeleton_payload(document, "single", [])
        assert payload["pending"] is True
        rebuilt = script.document_from_payload(payload)
        assert rebuilt.pending is True
        assert (rebuilt.branch, rebuilt.merge_base) == (document.branch, document.merge_base) == ("b", "m")
        assert {k: (e.files, e.message) for k, e in rebuilt.commits.items()} == {
            k: (e.files, e.message) for k, e in document.commits.items()
        }

    def test_pending_second_block_reported_by_validate(self, script: ModuleType) -> None:
        commits = {1: (["docs/a.md"], "Docs: a"), 2: (["docs/b.md"], "Docs: b")}
        document = script.document_from_commit_dict(commits, "b", "m", pending=True)
        with pytest.raises(ValueError, match="pending document has 2 commits"):
            document.validate()


class TestPending:
    def test_document_is_one_typed_entry(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        head = _git(clone, "rev-parse", "HEAD")
        document = script.pending_document(clone, script.capture_branch(clone, head), head)
        assert isinstance(document, BranchCommitDocument)
        assert document.pending is True
        assert (document.branch, document.merge_base, sorted(document.commits)) == ("9999-demo", head, [1])
        entry = document.commits[1]
        assert isinstance(entry, CommitEntry)
        assert entry.bucket is Bucket.TEST
        assert entry.files == ["docs/new.md", "docs/old.md", "scripts/__tests__/test_a.py"]
        assert (entry.header, entry.message) == (None, "")

    def test_capture_is_one_block_against_head(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = script.run_capture_pending(clone)
        assert (payload["branch"], payload["merge_base"]) == ("9999-demo", _git(clone, "rev-parse", "HEAD"))
        assert payload["pending"] is True
        assert payload["commits"] == {
            "1": [["docs/new.md", "docs/old.md", "scripts/__tests__/test_a.py"], ""],
        }

    def test_no_pending_change_is_reported(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        _git(clone, "add", "-A")
        _git(clone, "commit", "-m", "all")
        with pytest.raises(script.BuildError, match="no pending change"):
            script.run_capture_pending(clone)

    def test_build_writes_pending_txt_and_spares_ledger(
            self, script: ModuleType, work: Tuple[Path, str],
    ) -> None:
        clone, _ = work
        ledger = clone / "docs" / "_commit_messages" / "9999-demo.txt"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("branch ledger\n", encoding="utf-8")
        out, document = script.run_build(clone, _filled(script.run_capture_pending(clone)))
        assert out == clone / "docs" / "_commit_messages" / "9999-demo_pending.txt"
        assert ledger.read_text(encoding="utf-8") == "branch ledger\n"
        head = _git(clone, "rev-parse", "HEAD")
        assert out.read_text(encoding="utf-8").startswith(f"Branch: `9999-demo`\nMerge base: {head}\n")
        assert sorted(script.read_commit_txt(out).commits) == [1] == sorted(document.commits)
        assert document.pending is True

    def test_build_rejects_second_pending_block(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = _filled(script.run_capture_pending(clone))
        paths, message = payload["commits"]["1"]
        payload["commits"] = {"1": [paths[:1], message], "2": [paths[1:], message]}
        with pytest.raises(script.BuildError, match="pending document has 2 commits"):
            script.run_build(clone, payload)
        assert not (clone / "docs" / "_commit_messages" / "9999-demo_pending.txt").exists()

    def test_carries_message_until_head_moves(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        script.run_build(clone, _filled(script.run_capture_pending(clone)))
        assert script.run_capture_pending(clone)["commits"]["1"][1].startswith("Chore: commit 1")
        _git(clone, "commit", "-m", "rename")
        assert script.run_capture_pending(clone)["commits"]["1"][1] == ""

    def test_drops_message_when_files_change(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        script.run_build(clone, _filled(script.run_capture_pending(clone)))
        _git(clone, "reset", "--hard")
        (clone / "scripts" / "__tests__" / "test_a.py").unlink()
        _write(clone, "notes/other.md")
        payload = script.run_capture_pending(clone)
        assert payload["commits"] == {"1": [["notes/other.md"], ""]}

    def test_build_rejects_moved_head(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        payload = _filled(script.run_capture_pending(clone))
        _git(clone, "commit", "-m", "rename")
        with pytest.raises(script.BuildError, match="HEAD moved since capture"):
            script.run_build(clone, payload)
        assert not (clone / "docs" / "_commit_messages" / "9999-demo_pending.txt").exists()

    def test_detached_head_is_refused(self, script: ModuleType, work: Tuple[Path, str]) -> None:
        clone, _ = work
        _git(clone, "checkout", "--detach")
        with pytest.raises(script.BuildError, match="detached HEAD"):
            script.run_capture_pending(clone)

    def test_cli_accepts_pending_flag(self, script: ModuleType) -> None:
        assert script._parser().parse_args(["capture", "--pending"]).pending is True
