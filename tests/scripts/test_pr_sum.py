"""Behavioral tests for the harness plugin's ``scripts/pr_sum.py`` (pr-sum capture / diff / build driver).

The script is loaded by absolute path from the plugin. Git-backed tests get a throwaway upstream project
(base branch ``main``, a ``harness.json`` that moves the summaries directory and the test root) and a clone
whose branch carries the PR's commits, both copied from a module template built once; the clone's
configuration is activated before each test. ``gh`` is bypassed by constructing ``PrMeta`` directly. The
script is the only end-to-end caller of harness_lib.pr_summary (``render_summary`` through ``build``) and
of the head-mode capture in harness_lib.branch_capture (``capture_paths`` and ``diff_section`` against a
commit), so both modules are exercised here as well.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable, Dict, Iterator, Optional, Sequence, Tuple

import pytest

from conftest import copy_project, project_factory
from harness_lib import branch_capture, min_viz_sentinel, pr_capture
from harness_lib.commit_diff import DiffStat
from harness_lib.commit_grouping import CapturedPath
from harness_lib.config import activate, active, load_config

_SCRIPT = Path("scripts") / "pr_sum.py"
_SUMMARIES = "out/summaries"
_CONFIG = {"artifacts": {"summaries": _SUMMARIES}, "tests": {"roots": ["checks/"]}}
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "commit.gpgsign",
    "GIT_CONFIG_VALUE_0": "false",
}
_REPORT = "docs/PR_REVIEWS/1234_demo.json"
_BINARY = bytes(range(256)) * 16
_FLOW_BODY = "```\nBEFORE\nread every path\n```\n```\nAFTER\nread source first  [changed]\n```"
_SYMBOLS_BODY = "| Symbol | File | Status |\n|---|---|---|\n| `run_diff` | pr_sum.py | CHANGED |"


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> Iterator[ModuleType]:
    """Import pr_sum.py by absolute path, registered in ``sys.modules`` so dataclass annotations resolve."""
    spec = importlib.util.spec_from_file_location("pr_sum_under_test", plugin_root / _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd`` with a fixed identity and no system config; return stdout.

    Every call runs at a repo root or at ``tmp_path``, so ``cwd.parent`` as the ceiling stops discovery
    from climbing out of the test's temporary tree.
    """
    env = {**os.environ, **_GIT_ENV, "GIT_CEILING_DIRECTORIES": str(cwd.parent)}
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env)
    return result.stdout.strip()


def _write(root: Path, rel: str, text: str = "x\n") -> None:
    """Write ``text`` to ``root/rel``, creating parents."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(clone: Path, files: Dict[str, str], message: str) -> str:
    """Commit only ``files`` (path -> text) on the checked-out branch; return the new HEAD."""
    for rel, text in files.items():
        _write(clone, rel, text)
    _git(clone, "add", "--", *files)
    _git(clone, "commit", "-m", message)
    return _git(clone, "rev-parse", "HEAD")


def _build_pr(parent: Path) -> Tuple[str, str]:
    """``parent/upstream`` and its clone ``parent/work`` as ``pr_repo`` describes; (base SHA, head SHA)."""
    files = {"src/pkg/a.py": "x\n", "docs/old/b.md": "x\n", "README.md": "x\n"}
    upstream = project_factory(parent)(config=_CONFIG, files=files, name="upstream")
    (upstream / "assets").mkdir()
    (upstream / "assets" / "logo.bin").write_bytes(_BINARY)
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-m", "base")
    base = _git(upstream, "rev-parse", "HEAD")
    clone = parent / "work"
    _git(parent, "clone", str(upstream), str(clone))
    _git(clone, "checkout", "-b", "1234-demo")
    _write(clone, "src/pkg/a.py", "changed\n")
    _git(clone, "commit", "-am", "Feature(a): change a")
    (clone / "docs" / "new").mkdir()
    _git(clone, "mv", "docs/old/b.md", "docs/new/b.md")
    _write(clone, _REPORT, "{\n" + '  "k": 1,\n' * 28 + "}\n")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "Chore: move b, add report")
    head = _git(clone, "rev-parse", "HEAD")
    _git(upstream, "fetch", str(clone), "1234-demo")
    _git(upstream, "update-ref", "refs/pull/1234/head", head)
    _write(clone, "src/pkg/a.py", "uncommitted\n")
    return base, head


@pytest.fixture(scope="module")
def pr_template(tmp_path_factory: pytest.TempPathFactory) -> Tuple[Path, str, str]:
    """The upstream and clone built once per module; ``pr_repo`` copies them and never writes here."""
    parent = tmp_path_factory.mktemp("pr_sum_template")
    return (parent, *_build_pr(parent))


@pytest.fixture()
def pr_repo(tmp_path: Path, pr_template: Tuple[Path, str, str]) -> Tuple[Path, str, str]:
    """Clone with PR branch ``1234-demo``: an edit, a pure move, a 30-line artifact; plus an uncommitted edit.

    The base also carries an unchanged binary ``assets/logo.bin`` and the ``_CONFIG`` ``harness.json``. The
    upstream holds the PR head under ``refs/pull/1234/head`` and no branch for it. Both are copies of the
    template, with the clone's ``origin`` re-pointed at the copied upstream; the clone's configuration is
    activated. Returns (clone, upstream main SHA, PR head SHA).
    """
    template, base, head = pr_template
    upstream = copy_project(template / "upstream", tmp_path)
    clone = copy_project(template / "work", tmp_path)
    _git(clone, "remote", "set-url", "origin", str(upstream))
    activate(load_config(clone))
    return clone, base, head


def _meta(script: ModuleType, head: str, merge_commit: Optional[str] = None, base: str = "main") -> object:
    """PR #1234 metadata as ``gh pr view`` would report it."""
    return script.PrMeta(1234, "1234 demo", base, "1234-demo", head, merge_commit)


def _fresh_clone(tmp_path: Path, name: str) -> Path:
    """Object-copying clone of the upstream (``--no-local``), so the PR head arrives only by fetch."""
    fresh = tmp_path / name
    _git(tmp_path, "clone", "--no-local", str(tmp_path / "upstream"), str(fresh))
    return fresh


def _filled(payload: Dict[str, object], sections: Sequence[Dict[str, str]] = ()) -> Dict[str, object]:
    """Fill the draft with a title, Summary, every description slot and ``sections``."""
    draft = dict(payload["draft"])
    draft.update(
        title="Feature(a): `a` change", summary="Changes `a`.",
        descriptions={path: "changes `a`" for path in draft["descriptions"]}, sections=list(sections),
    )
    return {**payload, "draft": draft}


def _headers(text: str) -> list:
    """Paths of the ``=== path [...] ===`` section headers, in order."""
    return [line[4:].split(" [", 1)[0] for line in text.splitlines() if line.startswith("=== ")]


class TestPrMeta:
    def test_from_gh(self, script: ModuleType) -> None:
        raw = {
            "number": 5, "title": "t", "baseRefName": "dev", "headRefName": "h", "headRefOid": "abc",
            "mergeCommit": {"oid": "def"},
        }
        meta = script.PrMeta.from_gh(raw)
        assert (meta.number, meta.head_sha, meta.merge_commit, meta.base_tip) == (5, "abc", "def", "def^1")
        assert meta.fetch_refs == ("def", "pull/5/head")
        assert "state" not in pr_capture.GH_FIELDS.split(",")

    def test_open_pr_diffs_against_origin_base(self, script: ModuleType) -> None:
        raw = {
            "number": 5, "title": "t", "baseRefName": "dev", "headRefName": "h", "headRefOid": "abc",
            "mergeCommit": None,
        }
        meta = script.PrMeta.from_gh(raw)
        assert (meta.base_tip, meta.fetch_refs) == ("origin/dev", ("dev", "pull/5/head"))


class _Done:
    """Stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, stdout: str) -> None:
        self.returncode, self.stdout, self.stderr = 0, stdout, ""


class TestGhMetadata:
    @pytest.mark.parametrize("outcome", [FileNotFoundError("gh"), "not json", '{"number": 1}'])
    def test_failures_are_capture_errors(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, outcome: object,
    ) -> None:
        def fake_run(*_args: object, **_kwargs: object) -> _Done:
            if isinstance(outcome, Exception):
                raise outcome
            return _Done(str(outcome))

        monkeypatch.setattr(pr_capture.subprocess, "run", fake_run)
        with pytest.raises(script.CaptureError, match="gh pr view 1234"):
            script.gh_metadata(Path("."), 1234)


class TestCapture:
    def test_facts_from_commit_range(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        clone, base, head = pr_repo
        facts = script.capture_pr(clone, _meta(script, head), fetch=False, today="2026-10-10")
        assert (facts.number, facts.head, facts.base, facts.merge_base, facts.date) == (
            1234, "1234-demo", "main", base, "2026-10-10",
        )
        assert [line.split(" ", 1)[1] for line in facts.commits] == [
            "Feature(a): change a", "Chore: move b, add report",
        ]
        assert [(f.status, f.path, f.old_path, f.added, f.deleted, f.binary) for f in facts.files] == [
            ("A", _REPORT, None, 30, 0, False),
            ("R", "docs/new/b.md", "docs/old/b.md", 0, 0, False),
            ("M", "src/pkg/a.py", None, 1, 1, False),
        ]

    def test_merged_pr_uses_merge_commit_parent(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, base, head = pr_repo
        _git(clone, "stash", "-u")
        _git(clone, "checkout", "main")
        _git(clone, "merge", "--no-ff", "1234-demo", "-m", "Merge PR 1234")
        merge = _git(clone, "rev-parse", "HEAD")
        _git(clone, "update-ref", "refs/remotes/origin/main", merge)
        facts = script.capture_pr(clone, _meta(script, head, merge), fetch=False)
        assert facts.merge_base == base
        assert len(facts.files) == 3

    def test_fetch_matches_local_capture(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
    ) -> None:
        clone, _, head = pr_repo
        fresh = _fresh_clone(tmp_path, "fresh")
        assert subprocess.run(["git", "cat-file", "-e", head], cwd=fresh, capture_output=True).returncode != 0
        local = script.capture_pr(clone, _meta(script, head), fetch=False)
        fetched = script.capture_pr(fresh, _meta(script, head), fetch=True)
        assert (fetched.files, fetched.commits) == (local.files, local.commits)
        assert fetched.merge_base == local.merge_base

    def test_fetch_merged_pr_without_base_branch(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
    ) -> None:
        _, base, head = pr_repo
        upstream = tmp_path / "upstream"
        _git(upstream, "merge", "--no-ff", "refs/pull/1234/head", "-m", "Merge PR 1234")
        merge = _git(upstream, "rev-parse", "HEAD")
        fresh = _fresh_clone(tmp_path, "fresh")
        facts = script.capture_pr(fresh, _meta(script, head, merge, base="deleted-base"), fetch=True)
        assert facts.merge_base == base
        assert len(facts.files) == 3

    def test_binary_rename_with_edit_is_listed(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, _, _ = pr_repo
        _git(clone, "mv", "assets/logo.bin", "assets/mark.bin")
        (clone / "assets" / "mark.bin").write_bytes(_BINARY[:-8] + b"\xff" * 8)
        _git(clone, "add", "--", "assets/mark.bin")
        _git(clone, "commit", "-m", "Chore: rename and edit logo")
        head = _git(clone, "rev-parse", "HEAD")
        facts = script.capture_pr(clone, _meta(script, head), fetch=False)
        mark = next(f for f in facts.files if f.path == "assets/mark.bin")
        assert (mark.status, mark.old_path, mark.added, mark.deleted, mark.binary) == (
            "R", "assets/logo.bin", 0, 0, True,
        )
        assert not mark.relocated
        assert "assets/mark.bin" in facts.described

    def test_pr_file_statuses(self) -> None:
        stats = {"gone.py": DiffStat("gone.py", 0, 4)}
        deleted = pr_capture._pr_file(CapturedPath("D", "gone.py"), stats, frozenset())
        typed = pr_capture._pr_file(CapturedPath("T", "link.py"), stats, frozenset({"link.py"}))
        assert (deleted.status, deleted.path, deleted.added, deleted.deleted, deleted.binary) == (
            "D", "gone.py", 0, 4, False,
        )
        assert (typed.status, typed.added, typed.deleted, typed.binary) == ("M", 0, 0, True)


class TestCaptureSource:
    def test_local_head_includes_unpushed_commits(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, _, head = pr_repo
        local = _commit(clone, {"src/pkg/c.py": "c\n"}, "Feature(c): add c")
        facts = script.capture_pr(clone, _meta(script, head), fetch=False, local=True)
        assert (facts.head_sha, facts.head_source, facts.working_tree) == (local, "local", False)
        assert "src/pkg/c.py" in [f.path for f in facts.files]
        assert facts.commits[-1].endswith("Feature(c): add c")
        remote = script.capture_pr(clone, _meta(script, head), fetch=False)
        assert (remote.head_sha, remote.head_source, remote.working_tree) == (head, "remote", False)
        assert "src/pkg/c.py" not in [f.path for f in remote.files]

    def test_off_the_pr_branch_falls_back_to_the_pr_head(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, _, head = pr_repo
        _git(clone, "stash", "-u")
        _git(clone, "checkout", "main")
        _write(clone, "README.md", "dirty on main\n")
        _write(clone, "src/pkg/new.py", "n\n")
        facts = script.capture_pr(clone, _meta(script, head), fetch=False, local=True, working_tree=True)
        assert (facts.head_sha, facts.head_source, facts.working_tree) == (head, "remote", False)
        assert facts.files == script.capture_pr(clone, _meta(script, head), fetch=False).files
        assert {f.path for f in facts.files} == {"src/pkg/a.py", "docs/new/b.md", _REPORT}

    def test_working_tree_adds_staged_unstaged_and_untracked(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, _, head = pr_repo
        _write(clone, "README.md", "staged\n")
        _git(clone, "add", "--", "README.md")
        _write(clone, "src/pkg/new.py", "one\ntwo\n")
        (clone / "assets" / "new.bin").write_bytes(_BINARY)
        (clone / "assets" / "logo.bin").unlink()
        facts = script.capture_pr(clone, _meta(script, head), fetch=False, local=True, working_tree=True)
        assert (facts.head_sha, facts.head_source, facts.working_tree) == (head, "local", True)
        rows = {f.path: (f.status, f.added, f.deleted, f.binary, f.untracked) for f in facts.files}
        assert set(rows) == {
            "README.md", "src/pkg/a.py", "src/pkg/new.py", "assets/new.bin", "assets/logo.bin",
            "docs/new/b.md", _REPORT,
        }
        assert rows["README.md"] == ("M", 1, 1, False, False)
        assert rows["src/pkg/a.py"] == ("M", 1, 1, False, False)
        assert rows["src/pkg/new.py"] == ("A", 2, 0, False, True)
        assert rows["assets/new.bin"] == ("A", 0, 0, True, True)
        assert rows["assets/logo.bin"] == ("D", 0, 0, True, False)
        assert rows["docs/new/b.md"][0] == "R"
        assert rows[_REPORT] == ("A", 30, 0, False, False)
        patches = pr_capture.file_patches(clone, facts, facts.files)
        assert "+uncommitted" in patches["src/pkg/a.py"]
        assert "+staged" in patches["README.md"]
        assert patches["src/pkg/new.py"] == "+one\n+two"
        assert patches["assets/new.bin"] == branch_capture.BINARY_BODY

    def test_clean_checkout_records_no_working_tree(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, _, head = pr_repo
        _git(clone, "checkout", "--", "src/pkg/a.py")
        facts = script.capture_pr(clone, _meta(script, head), fetch=False, local=True, working_tree=True)
        assert (facts.head_sha, facts.head_source, facts.working_tree) == (head, "local", False)

    def test_local_branch_behind_the_pr_head_falls_back(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, _, head = pr_repo
        _git(clone, "reset", "--hard", "HEAD~1")
        facts = script.capture_pr(clone, _meta(script, head), fetch=False, local=True, working_tree=True)
        assert (facts.head_sha, facts.head_source, facts.working_tree) == (head, "remote", False)

    def test_untracked_harness_output_is_left_out(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, _, head = pr_repo
        for rel in (f"{_SUMMARIES}/1234_pr.json", "docs/PR_REVIEWS/extra.json", "notes/out.json", "src/n.py"):
            _write(clone, rel)
        facts = script.capture_pr(
            clone, _meta(script, head), fetch=False, local=True, working_tree=True,
            skip=frozenset({"notes/out.json"}),
        )
        untracked = [f.path for f in facts.files if f.untracked]
        assert untracked == ["src/n.py"]
        assert _REPORT in [f.path for f in facts.files]

    def test_diff_refuses_a_moved_checkout(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, _, head = pr_repo
        facts = script.capture_pr(clone, _meta(script, head), fetch=False, local=True, working_tree=True)
        _commit(clone, {"src/pkg/c.py": "c\n"}, "Feature(c): add c")
        with pytest.raises(script.CaptureError, match="working tree moved since capture"):
            pr_capture.file_patches(clone, facts, facts.files)


class TestCaptureCommand:
    def _run(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, clone: Path, head: str, out: Path,
    ) -> int:
        """``capture --no-fetch --repo clone`` with ``gh`` replaced by ``_meta(head)``."""
        monkeypatch.setattr(script, "gh_metadata", lambda _repo, _pr: _meta(script, head))
        return script.main(["capture", "--pr", "1234", "--no-fetch", "--out", str(out), "--repo", str(clone)])

    def test_cwd_selects_project_and_default_skeleton_path(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch, make_project: Callable[..., Path],
    ) -> None:
        clone, _, head = pr_repo
        other = make_project(config={"artifacts": {"summaries": "elsewhere"}}, name="other")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(other))
        monkeypatch.chdir(clone / "src")
        seen = []
        monkeypatch.setattr(script, "gh_metadata", lambda repo, _pr: seen.append(repo) or _meta(script, head))
        assert script.main(["capture", "--pr", "1234", "--no-fetch"]) == 0
        skeleton = clone / _SUMMARIES / "1234_pr.json"
        assert json.loads(skeleton.read_text(encoding="utf-8"))["facts"]["head_sha"] == head
        assert seen == [clone.resolve()] and active().project_root == clone.resolve()
        assert not (other / "elsewhere").exists()
        assert script.main(["capture", "--pr", "1234", "--no-fetch"]) == 0
        files = json.loads(skeleton.read_text(encoding="utf-8"))["facts"]["files"]
        assert f"{_SUMMARIES}/1234_pr.json" not in [f["path"] for f in files]

    def test_repo_argument_selects_project(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        clone, _, head = pr_repo
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "1234_pr.json"
        assert self._run(script, monkeypatch, clone, head, out) == 0
        assert active().project_root == clone.resolve()
        assert json.loads(out.read_text(encoding="utf-8"))["facts"]["base"] == "main"

    @pytest.mark.parametrize("flags, expected", [
        ((), ("local", True)),
        (("--remote-head",), ("remote", False)),
        (("--committed-only",), ("local", False)),
    ])
    def test_source_defaults_and_overrides(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch, flags: Tuple[str, ...], expected: Tuple[str, bool],
    ) -> None:
        clone, _, head = pr_repo
        monkeypatch.setattr(script, "gh_metadata", lambda _repo, _pr: _meta(script, head))
        out = tmp_path / "1234_pr.json"
        argv = ["capture", "--pr", "1234", "--no-fetch", "--out", str(out), "--repo", str(clone), *flags]
        assert script.main(argv) == 0
        facts = json.loads(out.read_text(encoding="utf-8"))["facts"]
        assert (facts["head_source"], facts["working_tree"]) == expected

    def test_rerun_carries_draft_forward(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        clone, _, head = pr_repo
        out = tmp_path / "1234_pr.json"
        assert self._run(script, monkeypatch, clone, head, out) == 0
        sections = [{"heading": "Changed Symbols", "body": "x"}]
        filled = _filled(json.loads(out.read_text(encoding="utf-8")), sections)
        filled["draft"]["descriptions"]["stale.py"] = "gone"
        out.write_text(json.dumps(filled), encoding="utf-8")
        new_head = _commit(clone, {"src/pkg/c.py": "c\n"}, "Feature(c): add c")
        assert self._run(script, monkeypatch, clone, new_head, out) == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["facts"]["head_sha"] == new_head
        assert payload["draft"] == {
            "title": "Feature(a): `a` change", "summary": "Changes `a`.",
            "descriptions": {"src/pkg/a.py": "changes `a`", "src/pkg/c.py": ""}, "sections": sections,
        }

    def test_unparseable_skeleton_is_replaced(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        clone, _, head = pr_repo
        out = tmp_path / "1234_pr.json"
        out.write_text('{"draft": {"descriptions": [1]', encoding="utf-8")
        assert self._run(script, monkeypatch, clone, head, out) == 0
        draft = json.loads(out.read_text(encoding="utf-8"))["draft"]
        assert draft == {"title": "", "summary": "", "descriptions": {"src/pkg/a.py": ""}, "sections": []}


class TestReadRank:
    @pytest.mark.parametrize(("path", "rank"), [
        ("src/pkg/a.py", 0),
        ("checks/verify_a.py", 1),
        ("pkg/test_b.py", 1),
        ("docs/guide.txt", 2),
        ("doc/guide.rst", 2),
        ("README.md", 2),
        ("notes/design.adoc", 2),
        ("scripts/__tests__/case.py", 0),
    ])
    def test_ranks_follow_configured_test_layout(
            self, make_project: Callable[..., Path], path: str, rank: int,
    ) -> None:
        activate(load_config(make_project(config=_CONFIG)))
        assert pr_capture.read_rank(path) == rank


class TestDiff:
    def test_default_read_skips_artifacts_and_orders_source_tests_docs(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, _, _ = pr_repo
        data = json.dumps({f"k{i}": i for i in range(58)}, indent=2) + "\n"
        files = {
            "checks/verify_a.py": "def test_a():\n    pass\n",
            "docs/c.md": "c\n",
            "data/big.json": data,
        }
        head = _commit(clone, files, "Test(a): add test, doc and data")
        payload = script.capture_payload(clone, _meta(script, head), fetch=False, working_tree=False)
        text = script.run_diff(clone, payload)
        assert _headers(text) == [
            "data/big.json", "src/pkg/a.py", "checks/verify_a.py", "docs/c.md", "docs/new/b.md",
        ]
        assert "=== data/big.json [summary, +60 -0] ===" in text
        assert "=== src/pkg/a.py [full, +1 -1] ===" in text
        assert "+changed" in text
        assert "uncommitted" not in text

    def test_artifact_read_when_named(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        clone, _, head = pr_repo
        payload = script.capture_payload(clone, _meta(script, head), fetch=False)
        assert _headers(script.run_diff(clone, payload, [_REPORT])) == [_REPORT]

    def test_pr_char_budget(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        clone, _, _ = pr_repo
        body = "".join(f"line_{i:03d} " + "x" * 180 + "\n" for i in range(60))
        big = {f"src/pkg/big{k:02d}.py": body for k in range(15)}
        head = _commit(clone, big, "Feature(big): add big files")
        text = script.run_diff(clone, script.capture_payload(clone, _meta(script, head), fetch=False))
        marker = "[omitted: block output budget spent]"
        sections = ["=== " + part for part in ("\n" + text).split("\n=== ")[1:]]
        spent = 0
        for section in sections:
            omitted = section.splitlines()[1:] == [marker]
            assert omitted == (spent >= script.PR_CHAR_BUDGET), section.splitlines()[0]
            spent += 0 if omitted else len(section) + 1
        assert script.PR_CHAR_BUDGET == 60_000
        assert sections[0].startswith("=== src/pkg/a.py [full")
        assert sections[-1].startswith("=== docs/new/b.md [") and sections[-1].endswith(marker)

    def test_budgeted_diff_of_no_files_is_empty(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, _, head = pr_repo
        facts = script.capture_pr(clone, _meta(script, head), fetch=False)
        assert pr_capture.budgeted_diff(clone, facts, (), 1200, 60_000) == ""

    def test_file_patches_match_per_path_diffs_from_one_git_call(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        clone, _, _ = pr_repo
        _git(clone, "rm", "-q", "README.md")
        head = _commit(clone, {"docs/a b.md": "spaced\n", "docs/café.md": "accent\n"}, "Docs: more")
        facts = script.capture_pr(clone, _meta(script, head), fetch=False)
        expected = {f.path: branch_capture.path_diff(clone, facts.merge_base, f.path, f.old_path, False, head)
                    for f in facts.files}
        diffs = []
        real = pr_capture.git_out

        def spy(repo: Path, *args: str) -> str:
            diffs.append(args) if args[0] == "diff" else None
            return real(repo, *args)

        monkeypatch.setattr(pr_capture, "git_out", spy)
        patches = pr_capture.file_patches(clone, facts, facts.files)
        assert patches == expected
        assert {"D", "R", "M", "A"} <= {f.status for f in facts.files}
        # One batch read; a header git quotes (non-ASCII under core.quotePath) adds one per-path read.
        assert len(diffs) in (1, 2)

    def test_budgeted_diff_reads_given_patches(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        clone, _, head = pr_repo
        facts = script.capture_pr(clone, _meta(script, head), fetch=False)
        patches = pr_capture.file_patches(clone, facts, facts.files)
        monkeypatch.setattr(pr_capture, "git_out", lambda *a: pytest.fail(f"unexpected git call {a}"))
        text = pr_capture.budgeted_diff(clone, facts, facts.files, 1200, 60_000, patches)
        assert "=== src/pkg/a.py [full, +1 -1] ===" in text and "+changed" in text

    def test_named_paths(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        clone, _, head = pr_repo
        payload = script.capture_payload(clone, _meta(script, head), fetch=False)
        text = script.run_diff(clone, payload, ["src/pkg/a.py", "nope.py"])
        assert text.splitlines()[0] == "=== src/pkg/a.py [full, +1 -1] ==="
        assert text.splitlines()[-1] == "=== nope.py [not in this PR] ==="
        assert _REPORT not in text

    def test_old_path_names_the_rename(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        clone, _, head = pr_repo
        payload = script.capture_payload(clone, _meta(script, head), fetch=False)
        text = script.run_diff(clone, payload, ["docs/old/b.md"])
        assert _headers(text) == ["docs/new/b.md"]
        assert "[not in this PR]" not in text


class TestBuild:
    def test_writes_summary_and_receipt(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        clone, _, head = pr_repo
        payload = {**_filled(script.capture_payload(clone, _meta(script, head), fetch=False)), "level": 1}
        out, receipt = script.run_build(clone, payload)
        assert out == clone / _SUMMARIES / "1234_Feature_a_a_change.md"
        text = out.read_text(encoding="utf-8")
        assert "**Files Changed:** 3 (+31 / -1 lines, 1 relocated)" in text
        assert "***Note:***" in text
        assert "Relocated 1 files" in text
        assert receipt == (
            f"Saved: {_SUMMARIES}/1234_Feature_a_a_change.md — "
            "Merge PR #1234: Feature(a): `a` change (1234-demo -> main)"
        )

    def test_level_two_build(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        clone, _, head = pr_repo
        sections = [
            {"heading": "Behavior: diff read", "body": _FLOW_BODY},
            {"heading": "Changed Symbols", "body": _SYMBOLS_BODY},
        ]
        payload = _filled(script.capture_payload(clone, _meta(script, head), fetch=False), sections)
        out, _ = script.run_build(clone, payload)
        text = out.read_text(encoding="utf-8")
        assert f"\n## Behavior: diff read\n\n{_FLOW_BODY}\n" in text
        assert (
            text.index("## Behavior: diff read") < text.index("## Changed Symbols")
            < text.index("<summary>Files Changed")
        )

    def test_rejects_unfilled_draft(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        clone, _, head = pr_repo
        payload = script.capture_payload(clone, _meta(script, head), fetch=False)
        with pytest.raises(script.CaptureError) as excinfo:
            script.run_build(clone, payload)
        assert "draft title is empty" in excinfo.value.problems
        assert not (clone / _SUMMARIES).exists()

    def test_default_level_requires_sections(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone, _, head = pr_repo
        payload = _filled(script.capture_payload(clone, _meta(script, head), fetch=False))
        with pytest.raises(script.CaptureError, match="needs its sections"):
            script.run_build(clone, payload)

    def test_malformed_facts(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        clone, _, _ = pr_repo
        with pytest.raises(script.CaptureError, match="rerun capture"):
            script.run_build(clone, {"facts": {}, "draft": {}})

    def test_wrong_typed_number(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        clone, _, head = pr_repo
        payload = _filled(script.capture_payload(clone, _meta(script, head), fetch=False))
        payload["facts"]["number"] = "1234"
        with pytest.raises(script.CaptureError, match="rerun capture"):
            script.run_build(clone, payload)

    @pytest.mark.parametrize("field, value", [
        ("head_source", "elsewhere"), ("working_tree", "false"), ("binary", 0), ("untracked", "no"),
    ])
    def test_wrong_typed_source_or_flag(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], field: str, value: object,
    ) -> None:
        clone, _, head = pr_repo
        payload = _filled(script.capture_payload(clone, _meta(script, head), fetch=False))
        target = payload["facts"]["files"][0] if field in ("binary", "untracked") else payload["facts"]
        target[field] = value
        with pytest.raises(script.CaptureError, match="wrong-typed source or file flag"):
            script.run_diff(clone, payload)

    @pytest.mark.parametrize(("draft", "word"), [
        ({"descriptions": ["a.py"]}, "descriptions"),
        ({"sections": ["Changed Symbols"]}, "sections"),
        ({"sections": "Changed Symbols"}, "sections"),
    ])
    def test_malformed_draft(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], draft: Dict[str, object], word: str,
    ) -> None:
        clone, _, head = pr_repo
        payload = script.capture_payload(clone, _meta(script, head), fetch=False)
        with pytest.raises(script.CaptureError, match=word):
            script.run_build(clone, {**payload, "draft": draft})

    def test_repo_other_than_active_project_is_rejected(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], make_project: Callable[..., Path],
    ) -> None:
        clone, _, head = pr_repo
        payload = {**_filled(script.capture_payload(clone, _meta(script, head), fetch=False)), "level": 1}
        other = make_project(name="other")
        with pytest.raises(script.CaptureError, match="not the active project"):
            script.run_build(other, payload)
        assert not (other / _SUMMARIES).exists() and not (clone / _SUMMARIES).exists()


def _diagram(n: int) -> str:
    """A fenced block that qualifies for ``--min-viz``: over 200 characters, with an arrow."""
    return "```\n" + "start ──► finish\n" * 14 + f"case {n}\n```"


_SYMBOLS_SECTION = {"heading": "Changed Symbols", "body": _SYMBOLS_BODY}


def _level3_sections(diagrams: int) -> list:
    """``diagrams`` New Behavior sections of one qualifying block each, then Changed Symbols."""
    flows = [{"heading": f"New Behavior: case {n}", "body": _diagram(n)} for n in range(diagrams)]
    return [*flows, _SYMBOLS_SECTION]


class TestBuildLevels:
    def _payload(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], sections: Sequence[Dict[str, str]],
            **keys: object,
    ) -> Dict[str, object]:
        clone, _, head = pr_repo
        filled = _filled(script.capture_payload(clone, _meta(script, head), fetch=False), sections)
        return {**filled, **keys}

    def test_level_one_leaves_out_commits(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        out, _ = script.run_build(pr_repo[0], self._payload(script, pr_repo, [], level=1))
        text = out.read_text(encoding="utf-8")
        assert "<summary>Commits</summary>" not in text and "<summary>Files Changed" in text
        assert "Chore: move b, add report" not in text

    def test_level_one_rejects_sections(self, script: ModuleType, pr_repo: Tuple[Path, str, str]) -> None:
        payload = self._payload(script, pr_repo, _level3_sections(1), level=1)
        with pytest.raises(script.CaptureError, match="sections are for levels 2 and 3"):
            script.run_build(pr_repo[0], payload)

    @pytest.mark.parametrize("level", [2, 3])
    def test_visual_levels_leave_out_commits(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], level: int,
    ) -> None:
        sections = [
            {"heading": "Behavior: diff read", "body": _FLOW_BODY},
            {"heading": "Changed Symbols", "body": _SYMBOLS_BODY},
        ]
        out, _ = script.run_build(pr_repo[0], self._payload(script, pr_repo, sections, level=level))
        text = out.read_text(encoding="utf-8")
        assert "<summary>Commits</summary>" not in text and "<summary>Files Changed" in text
        assert "Chore: move b, add report" not in text

    def test_skeleton_without_a_level_builds_at_level_two(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        with pytest.raises(script.CaptureError, match="needs its sections"):
            script.run_build(pr_repo[0], self._payload(script, pr_repo, []))
        sections = [{"heading": "New Behavior: a", "body": _diagram(0)}, _SYMBOLS_SECTION]
        out, _ = script.run_build(pr_repo[0], self._payload(script, pr_repo, sections))
        assert "## Changed Symbols" in out.read_text(encoding="utf-8")

    def test_level_three_without_min_viz_needs_no_blocks(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        sections = [
            {"heading": "Data Flow", "body": "x"}, {"heading": "Changed Symbols", "body": _SYMBOLS_BODY},
        ]
        out, _ = script.run_build(pr_repo[0], self._payload(script, pr_repo, sections, level=3))
        assert "## Data Flow" in out.read_text(encoding="utf-8")

    def test_min_viz_passes_and_clears_the_sentinel(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone = pr_repo[0]
        sentinel = min_viz_sentinel.arm(active(), 1234, 3)
        payload = self._payload(script, pr_repo, _level3_sections(3), level=3, min_viz=3)
        script.run_build(clone, payload)
        assert not sentinel.exists()

    def test_min_viz_shortfall_keeps_the_sentinel(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        clone = pr_repo[0]
        sentinel = min_viz_sentinel.arm(active(), 1234, 3)
        payload = self._payload(script, pr_repo, _level3_sections(1), level=3, min_viz=3)
        with pytest.raises(script.CaptureError) as excinfo:
            script.run_build(clone, payload)
        assert excinfo.value.problems == [
            "--min-viz needs 3 diagram blocks (fenced, over 200 characters, with an arrow); found 1",
        ]
        assert sentinel.exists() and not (clone / _SUMMARIES).exists()

    def test_min_viz_is_ignored_below_level_three(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str],
    ) -> None:
        payload = self._payload(script, pr_repo, [], level=1, min_viz=3)
        out, _ = script.run_build(pr_repo[0], payload)
        assert out.is_file()

    @pytest.mark.parametrize("keys, word", [
        ({"level": 4}, "level"), ({"level": "2"}, "level"), ({"level": True}, "level"),
        ({"level": 3, "min_viz": -1}, "min_viz"), ({"level": 3, "min_viz": "3"}, "min_viz"),
    ])
    def test_malformed_level_keys(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], keys: Dict[str, object], word: str,
    ) -> None:
        with pytest.raises(script.CaptureError, match=f"{word}.*rerun capture"):
            script.run_build(pr_repo[0], self._payload(script, pr_repo, [], **keys))


class TestCaptureLevels:
    def _capture(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, pr_repo: Tuple[Path, str, str],
            tmp_path: Path, *flags: str,
    ) -> Dict[str, object]:
        clone, _, head = pr_repo
        monkeypatch.setattr(script, "gh_metadata", lambda _repo, _pr: _meta(script, head))
        out = tmp_path / "1234_pr.json"
        argv = ["capture", "--pr", "1234", "--no-fetch", "--out", str(out), "--repo", str(clone), *flags]
        assert script.main(argv) == 0
        return json.loads(out.read_text(encoding="utf-8"))

    def test_no_flags_store_level_two(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        payload = self._capture(script, monkeypatch, pr_repo, tmp_path)
        assert payload["level"] == 2 and "min_viz" not in payload
        assert not min_viz_sentinel.sentinel_path(active(), 1234).exists()

    @pytest.mark.parametrize("level", ["1", "2", "3"])
    def test_level_is_stored(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch, level: str,
    ) -> None:
        payload = self._capture(script, monkeypatch, pr_repo, tmp_path, "--level", level)
        assert payload["level"] == int(level) and "min_viz" not in payload

    @pytest.mark.parametrize("flags, count", [(("--min-viz",), 3), (("--min-viz", "5"), 5)])
    def test_min_viz_at_level_three_arms_the_sentinel(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, flags: Tuple[str, ...],
            count: int,
    ) -> None:
        payload = self._capture(script, monkeypatch, pr_repo, tmp_path, "--level", "3", *flags)
        assert (payload["level"], payload["min_viz"]) == (3, count)
        sentinel = min_viz_sentinel.sentinel_path(active(), 1234)
        assert sentinel.read_text(encoding="utf-8").splitlines()[3] == str(count)
        assert f"--min-viz armed: {count} diagram blocks" in capsys.readouterr().out

    @pytest.mark.parametrize("level", ["1", "2"])
    def test_min_viz_below_level_three_is_ignored(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch, level: str,
    ) -> None:
        payload = self._capture(script, monkeypatch, pr_repo, tmp_path, "--level", level, "--min-viz")
        assert "min_viz" not in payload
        assert not min_viz_sentinel.sentinel_path(active(), 1234).exists()

    def test_min_viz_at_the_default_level_is_ignored(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        payload = self._capture(script, monkeypatch, pr_repo, tmp_path, "--min-viz")
        assert "min_viz" not in payload
        assert not min_viz_sentinel.sentinel_path(active(), 1234).exists()

    def test_recapture_without_the_flag_disarms(
            self, script: ModuleType, pr_repo: Tuple[Path, str, str], tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._capture(script, monkeypatch, pr_repo, tmp_path, "--level", "3", "--min-viz")
        sentinel = min_viz_sentinel.sentinel_path(active(), 1234)
        assert sentinel.exists()
        payload = self._capture(script, monkeypatch, pr_repo, tmp_path, "--level", "2")
        assert not sentinel.exists() and "min_viz" not in payload

    @pytest.mark.parametrize("flags", [("--level", "0"), ("--level", "4"), ("--min-viz", "x")])
    def test_bad_flag_values_are_rejected(self, script: ModuleType, flags: Tuple[str, ...]) -> None:
        with pytest.raises(SystemExit):
            script._parser().parse_args(["capture", "--pr", "1", *flags])

    def test_parser_defaults(self, script: ModuleType) -> None:
        bare = script._parser().parse_args(["capture", "--pr", "1"])
        assert (bare.level, bare.min_viz) == (2, None)
        flagged = script._parser().parse_args(["capture", "--pr", "1", "--level", "3", "--min-viz"])
        assert (flagged.level, flagged.min_viz) == (3, 3)


class TestCli:
    def test_parser(self, script: ModuleType) -> None:
        assert script._parser().parse_args(["build", "x.json"]).command == "build"
        with pytest.raises(SystemExit):
            script._parser().parse_args(["build", "x.json", "--visual"])
        assert script._parser().parse_args(["capture", "--pr", "12"]).pr == 12
        diff = script._parser().parse_args(["diff", "x.json", "--path", "a", "--path", "b"])
        assert diff.path == ["a", "b"]
        assert diff.repo is None
        assert script._parser().parse_args(["build", "x.json", "--repo", "p"]).repo == Path("p")

    @pytest.mark.parametrize("text", ['{"facts": ', "[]", None])
    @pytest.mark.parametrize("command", ["build", "diff"])
    def test_bad_skeleton_reports_problem(
            self, script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture, command: str,
            text: Optional[str], make_project: Callable[..., Path], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(make_project())
        skeleton = tmp_path / "1234_pr.json"
        if text is not None:
            skeleton.write_text(text, encoding="utf-8")
        assert script.main([command, str(skeleton)]) == 1
        err = capsys.readouterr().err
        assert err.startswith("problem: ") and "Traceback" not in err

    @pytest.mark.parametrize("config", ["{not json", '{"no_such_key": 1}'])
    def test_bad_config_reports_problem(
            self, script: ModuleType, capsys: pytest.CaptureFixture, config: str,
            make_project: Callable[..., Path], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(make_project(files={".claude/harness.json": config}))
        assert script.main(["build", "x.json"]) == 1
        err = capsys.readouterr().err
        assert err.startswith("problem: ") and "Traceback" not in err

    @pytest.mark.parametrize("name", ["plain", "no/such/typo"])
    def test_repo_outside_git_is_rejected(
            self, script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture, name: str,
            make_project: Callable[..., Path], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        other = make_project(config=_CONFIG, name="other")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(other))
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        (tmp_path / "plain").mkdir()
        monkeypatch.setattr(script, "gh_metadata", lambda repo, _pr: pytest.fail(f"gh read for {repo}"))
        assert script.main(["capture", "--pr", "1234", "--no-fetch", "--repo", str(tmp_path / name)]) == 1
        err = capsys.readouterr().err
        assert err.startswith("problem: --repo ") and "not inside a git checkout" in err
        assert not (other / _SUMMARIES).exists()
