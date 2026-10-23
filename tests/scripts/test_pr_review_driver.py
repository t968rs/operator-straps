"""Behavioral tests for the plugin's scripts/pr_review.py (the pr-review capture-to-closeout driver).

The script is loaded by absolute path from the plugin. Each test gets a throwaway project: a copy of
the module's ``pr_template``, or its own ``_make_pr`` build when it needs other files or configuration.
Unit-level tests of driver functions (``defer_reasons``, ``ceiling_line``, config) build a bare project with
``make_project`` and activate its config directly.
The project holds ``.claude/harness.json`` (``_CONFIG``: base branch, scratch directory, exclusions file,
test registry, structural guard suite, a domain pointer), the vendored exclusions fixture
(``fixtures/pr_review_exclusions.json``), a one-entry test registry and the base files on ``dev`` (with
``origin/dev`` pointing at it), then branch ``1234-demo`` carrying the PR's commit. Schemas and the lens
catalog come from the plugin (the project pins none).
``gh``, the structural guard run and the Phase 4 script are replaced through the driver's module-level
seams. The plugin's schema hook runs for real: in-process through its ``main`` with the driver's event, and
as the driver's own subprocess in ``_REAL_HOOK_TESTS``.

``capture`` runs end to end through ``harness_lib.pr_capture`` (metadata, budgeted diffs),
``harness_lib.review_plan`` (buckets, lenses, slot plan), ``harness_lib.branch_capture`` and
``harness_lib.pr_summary``.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import pytest

from conftest import copy_project, project_factory
from harness_lib import review_merge as rmg
from harness_lib import review_models as rm
from harness_lib.config import activate, load_config

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_SCRIPT = Path("scripts") / "pr_review.py"
_HOOK = Path("hooks") / "validate_pr_json_schema.py"
_REAL_HOOK_TESTS = frozenset({"test_closeout_end_to_end_clears_sentinel",
                              "test_closeout_through_the_plugin_hook_subprocess"})
_SKILL = Path("skills") / "pr-review" / "SKILL.md"
_PR = 1234
_TITLE = "1234 demo: review"
_REVIEW_NAME = "1234_1234_demo_review.json"
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "commit.gpgsign",
    "GIT_CONFIG_VALUE_0": "false",
}
_SCRATCH = "build/review_runs"
_STATE = "build/harness_state"
_POINTER = "pkg-arch: `src/pkg/**` is in scope; check it against the package architecture notes."
_GUARDS = ["tests/guards/test_workflows.py", "tests/guards/test_runner.py"]
_CONFIG = {
    "base_branch": "dev",
    "state_dir": _STATE,
    "exclusions": "config/exclusions.json",
    "artifacts": {"scratch": _SCRATCH},
    "tests": {"registry": "tests/registry.json"},
    "review": {"guard_suite": _GUARDS, "structural_guard_prefixes": [".github/workflows/"],
               "domain_pointers": [{"prefix": "src/pkg/", "pointer": _POINTER}]},
}
_BASE_FILES = {
    "src/pkg/a.py": "".join(f"def f{n}():\n    return {n}\n" for n in range(10)),
    "docs/a.md": "# A\n\nold text\n",
}
_PR_FILES = {
    "src/pkg/a.py": "".join(f"def f{n}():\n    return {n + 1}\n" for n in range(10)),
    "src/pkg/b.py": "".join(f"B{n} = {n}\n" for n in range(5)),
    "tests/test_a.py": "def test_a():\n    assert True\n",
    "docs/a.md": "# A\n\nnew text\n",
    ".github/offline/offlineTestReport.json": "{\n  \"k\": 1\n}\n",
}
_REGISTRY = {"tests": [{"file": "tests/test_a.py", "properties": {"test_target_paths": ["src/pkg/a.py"]}}]}
_PRE_FIX = {
    "current_branch_check": {"command": "git rev-parse --abbrev-ref HEAD", "stdout": "1234-demo",
                             "result": "OK"},
    "branch_match_check": {"assertion": "CURRENT_BRANCH == headRefName", "current_branch": "1234-demo",
                           "head_ref_name": "1234-demo", "result": "OK (match)"},
    "clean_tree_check": {"command": "git status --porcelain", "stdout": "", "result": "OK (empty)"},
    "sha_ancestry_check": {"base_sha": "x", "head_sha": "y", "base_ancestor_command": "c",
                           "base_ancestor_exit": 0, "head_ancestor_command": "c", "head_ancestor_exit": 0,
                           "result": "OK (both ancestors)"},
    "base_branch_recorded": {"source": "gh", "value": "dev", "result": "OK (recorded)"},
}


@pytest.fixture(scope="module")
def script(plugin_root: Path) -> Iterator[ModuleType]:
    """Import pr_review.py by absolute path, registered in ``sys.modules`` so annotations resolve."""
    spec = importlib.util.spec_from_file_location("pr_review_under_test", plugin_root / _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(scope="module")
def hook(plugin_root: Path) -> ModuleType:
    """The plugin's schema hook imported once; ``sys.path`` left unchanged."""
    saved = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location("pr_json_schema_hook_under_test", plugin_root / _HOOK)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


def _run_hook_here(hook: ModuleType, repo: Path, review_path: Path) -> Tuple[int, str]:
    """``run_hook`` without a new interpreter: the same Edit event on stdin and ``CLAUDE_PROJECT_DIR``."""
    event = {"tool_name": "Edit", "tool_input": {"file_path": str(review_path.resolve())}, "cwd": str(repo)}
    err = io.StringIO()
    with pytest.MonkeyPatch.context() as mp, contextlib.redirect_stderr(err), \
            contextlib.redirect_stdout(io.StringIO()):
        mp.setenv("CLAUDE_PROJECT_DIR", str(repo))
        mp.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
        rc = hook.main()
    return rc, err.getvalue()


@pytest.fixture(autouse=True)
def _hook_in_process(request: pytest.FixtureRequest, script: ModuleType, hook: ModuleType,
                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Route ``run_hook`` through ``_run_hook_here`` (a fresh interpreter costs ~0.25 s per review write),
    except in ``_REAL_HOOK_TESTS``, which keep the driver's subprocess."""
    if request.node.originalname not in _REAL_HOOK_TESTS:
        monkeypatch.setattr(script, "run_hook", lambda repo, path: _run_hook_here(hook, repo, path))


def _git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd`` with a fixed identity, no system config and discovery capped at ``cwd.parent``."""
    env = {**os.environ, **_GIT_ENV, "GIT_CEILING_DIRECTORIES": str(cwd.parent)}
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env)
    return result.stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    """Write ``text`` to ``root/rel``, creating parents."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project_files() -> Dict[str, object]:
    """The base commit: the vendored exclusions, the registry, the ignore file and ``_BASE_FILES``."""
    exclusions = json.loads((_FIXTURES / "pr_review_exclusions.json").read_text(encoding="utf-8"))
    return {"config/exclusions.json": exclusions, "tests/registry.json": _REGISTRY,
            ".gitignore": "build/\n__pycache__/\n", **_BASE_FILES}


def _make_pr(make_project, extra: Optional[Dict[str, str]] = None, config: Optional[dict] = None,
             base_extra: Optional[Dict[str, object]] = None) -> Tuple[Path, str]:
    """Project on branch ``1234-demo`` with ``_PR_FILES`` plus ``extra`` over the base; (repo, head).

    ``dev`` holds the base commit (plus ``base_extra``) and ``origin/dev`` points at it, the only remote
    ref a ``--no-fetch`` capture reads, so no upstream repo is needed. ``config`` replaces ``_CONFIG``.
    """
    files = {**_project_files(), **(base_extra or {})}
    repo = make_project(config=_CONFIG if config is None else config, files=files, name="work")
    _git(repo, "branch", "-m", "dev")
    _git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
    _git(repo, "checkout", "-q", "-b", "1234-demo")
    for rel, text in {**_PR_FILES, **(extra or {})}.items():
        _write(repo, rel, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Feature(a): demo change")
    return repo, _git(repo, "rev-parse", "HEAD")


@pytest.fixture(scope="module")
def pr_template(tmp_path_factory: pytest.TempPathFactory) -> Tuple[Path, str]:
    """The default PR built once per module; ``pr_repo`` clones it and never writes to it."""
    return _make_pr(project_factory(tmp_path_factory.mktemp("pr_template")))


@pytest.fixture()
def pr_repo(tmp_path: Path, pr_template: Tuple[Path, str]) -> Tuple[Path, str]:
    """The default three-bucket small PR (runtime, tests, docs) plus an excluded offline report.

    A copy of the template, so refs, index and working tree match a fresh ``_make_pr`` without its nine
    git calls.
    """
    return copy_project(pr_template[0], tmp_path), pr_template[1]


def _gh_stub(head: str, state: str = "OPEN") -> Tuple[List[Sequence[str]], object]:
    """A ``run_gh`` replacement returning the capture projection, and the list of argument lists it saw."""
    calls: List[Sequence[str]] = []
    payload = {"number": _PR, "title": _TITLE, "headRefName": "1234-demo", "baseRefName": "dev",
               "state": state, "url": "https://github.com/o/r/pull/1234", "headRefOid": head,
               "mergeCommit": None, "commits_count": 1, "first_sha": head, "last_sha": head}

    def fake(repo: Path, args: Sequence[str]) -> str:
        calls.append(list(args))
        return json.dumps(payload) + "\n"

    return calls, fake


def _run(script: ModuleType, repo: Path, *argv: str) -> int:
    """Run the driver CLI against ``repo``."""
    return script.main(["--repo", str(repo), *argv])


def _capture(script: ModuleType, monkeypatch: pytest.MonkeyPatch, clone: Path, head: str,
             *extra: str, state: str = "OPEN") -> int:
    """Run ``capture`` with gh stubbed and the roast off."""
    _, fake = _gh_stub(head, state)
    monkeypatch.setattr(script, "run_gh", fake)
    return _run(script, clone, "capture", "--pr", str(_PR), "--no-fetch", "--roast", "no", *extra)


def _current(clone: Path) -> Path:
    """The ``current`` pointer file of ``_PR``'s runs in ``clone``."""
    return clone / rm.run_root(clone) / f"{_PR:04d}" / "current"


def _plan(clone: Path) -> Dict[str, object]:
    """The current run's plan.json."""
    return json.loads((rm.run_dir(_PR, clone) / "plan.json").read_text(encoding="utf-8"))


def _brief(clone: Path, agent: str, folder: str = "briefs") -> str:
    """A brief from the current run."""
    return (rm.run_dir(_PR, clone) / folder / f"{agent}.md").read_text(encoding="utf-8")


def _finding(file: str, lines: Optional[str] = "1", **overrides: object) -> Dict[str, object]:
    """A minor mechanical finding mapping on ``file``."""
    base: Dict[str, object] = {"severity": "minor", "name": f"Tidy {file}", "summary": "s", "fix": ["f"],
                               "file": file, "lines": lines, "fix_kind": "mechanical"}
    base.update(overrides)
    return base


def _split_findings() -> List[Dict[str, object]]:
    """Six findings on a.py (M1-M6) plus M7, mechanical over a.py and docs/a.md, split across two waves."""
    findings = [_finding("src/pkg/a.py", None, name=f"a{n}") for n in range(6)]
    return findings + [_finding("src/pkg/a.py", None, name="z split", also=["docs/a.md"])]


def _record_all(clone: Path, runtime: Sequence[Dict[str, object]] = ()) -> None:
    """Record every default slot: ``runtime`` findings for the runtime slot, nothing for the others."""
    for slot in ("runtime", "tests", "docs", "overall"):
        rm.record(_PR, slot, list(runtime) if slot == "runtime" else [], ["clear seams"], repo=clone)


def _phase4(monkeypatch: pytest.MonkeyPatch, script: ModuleType, rc: int = 0,
            stdout: Optional[str] = None, stderr: str = "") -> None:
    """Replace ``run_phase4`` with a fixed result (a valid pre_fix_time block by default)."""
    out = json.dumps(_PRE_FIX) if stdout is None else stdout
    monkeypatch.setattr(script, "run_phase4", lambda repo, pr: (rc, out, stderr))


def _built(script: ModuleType, monkeypatch: pytest.MonkeyPatch, clone: Path, head: str,
           runtime: Sequence[Dict[str, object]] = (_finding("src/pkg/a.py"),)) -> Path:
    """Capture, record, merge and build; return the review path."""
    assert _capture(script, monkeypatch, clone, head) == 0
    _record_all(clone, runtime)
    assert _run(script, clone, "merge", "--pr", str(_PR)) == 0
    _phase4(monkeypatch, script)
    assert _run(script, clone, "build", "--pr", str(_PR)) == 0
    return clone / "docs" / "PR_REVIEWS" / _REVIEW_NAME


def _heredoc(text: str) -> str:
    """Body of the first ``sh "<plugin>/scripts/hpy" - <<'EOF'`` heredoc in ``text``."""
    match = re.search(r"sh \"[^\"\n]*/scripts/hpy\" - <<'EOF'\n(.*?)\nEOF\n", text, re.S)
    assert match, "brief carries no record heredoc"
    return match.group(1)


def _normalized(text: str) -> str:
    """``text`` with whitespace runs collapsed."""
    return " ".join(text.split())


def _delete_in_pr(clone: Path, rel: str) -> str:
    """Commit a removal of ``rel`` on top of the PR head so the PR deletes it; returns the new head."""
    _git(clone, "rm", "-q", rel)
    _git(clone, "commit", "-m", f"Feature(a): drop {rel}")
    return _git(clone, "rev-parse", "HEAD")


class TestCapture:
    def test_default_exclusions_are_seeded_and_applied(self, script: ModuleType, make_project,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
        # Probe paths no default Artifact commit bucket covers, so only the seeded patterns exclude them.
        config = {k: v for k, v in _CONFIG.items() if k != "exclusions"}
        config["artifacts"] = {**_CONFIG["artifacts"], "summaries": "out/sums"}
        config["matrix_path"] = "out/rows/watch_rows.jsonl"
        probes = {"out/sums/0001_x.md", "out/rows/watch_rows.jsonl"}
        clone, head = _make_pr(make_project, config=config, extra={
            "out/sums/0001_x.md": "summary\n", "out/rows/watch_rows.jsonl": "{}\n"})
        assert not (clone / ".claude" / "review_exclusions.json").exists()
        assert _capture(script, monkeypatch, clone, head) == 0
        assert (clone / ".claude" / "review_exclusions.json").is_file()
        assert not any(script.rp.is_excluded(p, ()) for p in probes)
        assert probes <= set(_plan(clone)["excluded"])

    def test_small_three_bucket_pr(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                   pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        assert _capture(script, monkeypatch, clone, head) == 0
        plan = _plan(clone)
        slots = {s["id"]: s for s in plan["slots"]}
        assert list(slots) == ["tests", "runtime", "docs", "overall"]
        assert slots["runtime"]["model"] == "opus" and slots["tests"]["model"] == "sonnet"
        assert slots["overall"]["templates"] == ["overall-system-shape"]
        assert ".github/offline/offlineTestReport.json" in plan["excluded"]
        assert ".github/offline/offlineTestReport.json" not in slots["overall"]["paths"]
        assert plan["meta"]["head_sha"] == head and plan["tree_at_head"] is True
        assert plan["dispatch_time"]["structural_guards_check"]["applies"] is False
        assert (rm.run_dir(_PR, clone) / "phase1_meta.txt").read_text(encoding="utf-8").startswith("{")
        for slot in slots:
            assert (rm.run_dir(_PR, clone) / "briefs" / f"{slot}.md").is_file()
            assert (rm.run_dir(_PR, clone) / "diffs" / f"{slot}.diff").is_file()

    def test_new_files_listed_not_diffed(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                         pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        brief = _brief(clone, "runtime")
        diff = (rm.run_dir(_PR, clone) / "diffs" / "runtime.diff").read_text(encoding="utf-8")
        assert "src/pkg/b.py: new file, 5 lines - read it" in brief
        assert "=== src/pkg/a.py [full" in diff and "src/pkg/b.py" not in diff

    def test_prompt_rows(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                         pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        lines = capsys.readouterr().out.splitlines()
        rows = [n for n, line in enumerate(lines) if line.startswith("agent=harness:pr-reviewer model=")]
        assert len(rows) == 4
        run_id = _plan(clone)["run_id"]
        for n in rows:
            prompt = lines[n + 1:n + 6]
            keys = [p.split(":", 1)[0] for p in prompt]
            assert keys == ["AGENT_ID", "AGENT_ROLE", "RUN_ID", "PR", "Brief"]
            assert prompt[1] == "AGENT_ROLE: reviewer" and prompt[2] == f"RUN_ID: {run_id}"
            assert Path(prompt[4].split(": ", 1)[1]).is_file()
            assert n + 6 == len(lines) or not lines[n + 6].strip()

    def test_closed_pr_refused(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                               pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        assert _capture(script, monkeypatch, clone, head, state="MERGED") == 1
        assert "problem:" in capsys.readouterr().err
        assert not _current(clone).exists()

    def test_allow_closed_replays_but_build_refuses(self, script: ModuleType,
                                                    monkeypatch: pytest.MonkeyPatch,
                                                    pr_repo: Tuple[Path, str],
                                                    capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        assert _capture(script, monkeypatch, clone, head, "--allow-closed", state="MERGED") == 0
        _record_all(clone)
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 0
        _phase4(monkeypatch, script)
        capsys.readouterr()
        assert _run(script, clone, "build", "--pr", str(_PR)) == 1
        assert "MERGED" in capsys.readouterr().err
        assert not (clone / "docs" / "PR_REVIEWS").exists()

    def test_dirty_tree_reads_from_head(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                        pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        _write(clone, "src/pkg/a.py", "uncommitted\n")
        _capture(script, monkeypatch, clone, head)
        assert _plan(clone)["tree_at_head"] is False
        assert f"git -C {clone.resolve().as_posix()} show {head}:<path>" in _brief(clone, "runtime")

    def test_untracked_replacement_of_deleted_path_is_not_at_head(self, script: ModuleType,
                                                                  monkeypatch: pytest.MonkeyPatch,
                                                                  pr_repo: Tuple[Path, str]) -> None:
        clone, _ = pr_repo
        head = _delete_in_pr(clone, "docs/a.md")
        _write(clone, "docs/a.md", "untracked replacement\n")
        _capture(script, monkeypatch, clone, head)
        assert _plan(clone)["tree_at_head"] is False

    def test_deleted_path_read_at_merge_base(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                             pr_repo: Tuple[Path, str]) -> None:
        clone, _ = pr_repo
        head = _delete_in_pr(clone, "docs/a.md")
        _write(clone, "src/pkg/a.py", "uncommitted\n")
        _capture(script, monkeypatch, clone, head)
        base = _plan(clone)["meta"]["base_sha"]
        brief = _brief(clone, "docs")
        assert "- docs/a.md: deleted in this PR (no PR-head version)" in brief
        assert f"`git -C {clone.resolve().as_posix()} show {base}:<path>`" in brief
        assert f"show {head}:<path>" in brief

    def test_summarized_path_gets_fetch_command(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                make_project) -> None:
        big = "".join(f"line {n}\n" for n in range(1500))
        clone, head = _make_pr(make_project, {"docs/a.md": big})
        _capture(script, monkeypatch, clone, head)
        merge_base = _plan(clone)["meta"]["base_sha"]
        command = f"git -C {clone.resolve().as_posix()} diff {merge_base} {head} -- docs/a.md"
        assert command in _brief(clone, "docs")

    def test_guard_failure_stops(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, make_project,
                                 capsys: pytest.CaptureFixture) -> None:
        clone, head = _make_pr(make_project, {".github/workflows/ci.yml": "on: push\n"})
        seen: List[Sequence[str]] = []

        def failing(repo: Path, suite: Sequence[str]) -> Tuple[int, str]:
            seen.append(suite)
            return 1, "E\n1 failed"

        monkeypatch.setattr(script, "run_guards", failing)
        assert _capture(script, monkeypatch, clone, head) == 1
        assert seen and tuple(seen[0]) == tuple(_GUARDS)
        assert "problem:" in capsys.readouterr().err
        assert not _current(clone).exists()

    def test_guard_pass_recorded(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                 make_project) -> None:
        clone, head = _make_pr(make_project, {".github/workflows/ci.yml": "on: push\n"})
        monkeypatch.setattr(script, "run_guards", lambda repo, suite: (0, "....\n5 passed in 1.0s\n"))
        assert _capture(script, monkeypatch, clone, head) == 0
        check = _plan(clone)["dispatch_time"]["structural_guards_check"]
        assert check["applies"] is True and check["result"] == "OK (5 passed)"
        assert "5 passed" in check["stdout_tail"] and "pytest" in check["command"]


class TestProjectConfig:
    """Every project path and agent id the driver uses comes from the project config or the plugin."""

    def test_run_scratch_is_the_configured_directory(self, script: ModuleType,
                                                     monkeypatch: pytest.MonkeyPatch,
                                                     pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        assert _capture(script, monkeypatch, clone, head) == 0
        run = rm.run_dir(_PR, clone)
        assert run.relative_to(clone.resolve()).as_posix().startswith(f"{_SCRATCH}/{_PR:04d}/")

    def test_custom_review_directory(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                     make_project) -> None:
        config = {**_CONFIG, "artifacts": {"scratch": _SCRATCH, "reviews": "reviews/pr"}}
        clone, head = _make_pr(make_project, config=config)
        path = _built(script, monkeypatch, clone, head)
        assert not path.exists()
        assert (clone / "reviews" / "pr" / _REVIEW_NAME).is_file()
        assert _plan(clone)["review_path"] == f"reviews/pr/{_REVIEW_NAME}"
        assert "never write under `reviews/pr/`" in _brief(clone, "runtime")

    def test_schema_ref_is_the_plugin_id_without_a_pinned_copy(self, script: ModuleType,
                                                               monkeypatch: pytest.MonkeyPatch,
                                                               pr_repo: Tuple[Path, str],
                                                               plugin_root: Path) -> None:
        clone, head = pr_repo
        doc = json.loads(_built(script, monkeypatch, clone, head).read_text(encoding="utf-8"))
        schema = json.loads((plugin_root / "schemas" / "PR_REVIEW.schema.json").read_text(encoding="utf-8"))
        assert doc["schema_ref"] == schema["$id"]

    def test_briefs_run_python_through_the_plugin_hpy(self, script: ModuleType,
                                                      monkeypatch: pytest.MonkeyPatch,
                                                      pr_repo: Tuple[Path, str], plugin_root: Path) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        hpy = f'sh "{(plugin_root / "scripts" / "hpy").resolve().as_posix()}"'
        assert f"{hpy} - <<'EOF'" in _brief(clone, "runtime")
        fixer = _brief(clone, "w1_fix_1", "fix_briefs")
        assert f"{hpy} - <<'EOF'" in fixer and f"`{hpy} -m pytest " in fixer
        assert (plugin_root / "lib").resolve().as_posix() in fixer

    @pytest.mark.parametrize("base, noted", [("dev", False), ("main", True)])
    def test_base_branch_note(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, make_project,
                              capsys: pytest.CaptureFixture, base: str, noted: bool) -> None:
        clone, head = _make_pr(make_project, config={**_CONFIG, "base_branch": base})
        capsys.readouterr()
        assert _capture(script, monkeypatch, clone, head) == 0
        note = f"note: PR base dev is not the configured base branch {base}"
        assert (note in capsys.readouterr().out) is noted

    def test_project_lens_gets_a_slot(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                      make_project) -> None:
        lens = {"name": "pkg-boundary", "summary": "s", "scope_template": "Check the pkg boundary.",
                "trigger": {"description": "two pkg files", "path_globs": ["src/pkg/*"], "min_files": 2}}
        config = {**_CONFIG, "review": {**_CONFIG["review"], "lenses": "config/lenses.json"}}
        lens_file = {"config/lenses.json": {"lenses": [lens]}}
        clone, head = _make_pr(make_project, config=config, base_extra=lens_file)
        assert _capture(script, monkeypatch, clone, head) == 0
        slots = {s["id"]: s for s in _plan(clone)["slots"]}
        assert slots["pkg_boundary"]["paths"] == ["src/pkg/a.py", "src/pkg/b.py"]
        assert "Check the pkg boundary." in _brief(clone, "pkg_boundary")


class TestBriefs:
    def test_ownership_and_test_design_clauses(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                               pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        ownership = ("Record findings only through `record`; never write under `docs/PR_REVIEWS/`; "
                     "reply with the printed block only")
        for slot in ("runtime", "tests", "docs", "overall"):
            assert ownership in _brief(clone, slot)
        clause = _normalized(script.TEST_DESIGN_CLAUSE)
        assert clause in _normalized(_brief(clone, "tests"))
        assert clause in _normalized(_brief(clone, "overall"))
        assert clause not in _normalized(_brief(clone, "docs"))

    def test_test_design_clause_is_the_skill_text(self, script: ModuleType, plugin_root: Path) -> None:
        text = (plugin_root / _SKILL).read_text(encoding="utf-8").splitlines()
        start = next(n for n, line in enumerate(text) if line.startswith("> Test-design principle:"))
        quoted = []
        for line in text[start:]:
            if not line.startswith(">"):
                break
            quoted.append(line[1:].strip())
        assert _normalized(script.TEST_DESIGN_CLAUSE) == _normalized(" ".join(quoted))

    def test_catalog_templates_and_pointers(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                            pr_repo: Tuple[Path, str], plugin_root: Path) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        catalog_path = plugin_root / "schemas" / "catalogs" / "CrossCuttingLensCatalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        sub_lens = catalog["default_sub_lenses"][0]["scope_template"]
        shape = next(lens["scope_template"] for lens in catalog["lenses"]
                     if lens["name"] == "overall-system-shape")
        runtime, overall, docs = (_brief(clone, s) for s in ("runtime", "overall", "docs"))
        assert sub_lens in runtime and runtime.count(sub_lens) == 1
        assert shape in overall and shape not in runtime
        assert _POINTER in runtime and _POINTER not in docs

    def test_roast_slot_carries_voice_and_full_scope(self, script: ModuleType,
                                                     monkeypatch: pytest.MonkeyPatch,
                                                     pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        _, fake = _gh_stub(head)
        monkeypatch.setattr(script, "run_gh", fake)
        assert _run(script, clone, "capture", "--pr", str(_PR), "--no-fetch", "--roast", "yes") == 0
        slots = {s["id"]: s for s in _plan(clone)["slots"]}
        assert "overall" not in slots and slots["roast"]["roast"] is True
        assert "tired senior developer" in _brief(clone, "roast")

    def test_record_heredoc_runs_verbatim(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                          pr_repo: Tuple[Path, str], tmp_path: Path) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        run = rm.run_dir(_PR, clone)
        body = _heredoc(_brief(clone, "runtime"))
        assert f'run_id="{run.name}"' in body
        rm.start_run(_PR, "pr1234_20990101T000000Z", clone)
        result = subprocess.run([sys.executable, "-"], input=body, cwd=tmp_path, capture_output=True,
                                text=True, check=False)
        assert result.returncode == 0, result.stderr
        assert "SIGNAL: DONE" in result.stdout
        assert "COUNTS: findings=0 critical=0 important=0 minor=0" in result.stdout
        assert (run / "findings" / "runtime.json").is_file()
        assert not (rm.run_dir(_PR, clone) / "findings").exists()


class TestMergeAndAmend:
    def test_missing_report_names_slot(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                       pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        rm.record(_PR, "runtime", [], [], repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 1
        err = capsys.readouterr().err
        assert "tests" in err and "docs" in err and "overall" in err

    def test_merge_writes_draft_and_prints_table(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                 pr_repo: Tuple[Path, str],
                                                 capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [_finding("src/pkg/a.py", "4", severity="important"),
                            _finding("src/pkg/a.py", None, name="Rename f helper"),
                            _finding("src/pkg/a.py", None, name="Rename f helpers")])
        capsys.readouterr()
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 0
        out = capsys.readouterr().out
        draft = json.loads((rm.run_dir(_PR, clone) / "draft.json").read_text(encoding="utf-8"))
        assert [i["id"] for i in draft["issues"]] == ["I1", "M1", "M2"]
        assert "runtime (opus)" in draft["reviewers"] and draft["amend"] == []
        assert "I1 important src/pkg/a.py:4 [runtime]" in out
        assert "merge candidates:" in out and "M1 + M2" in out

    def test_amend_then_merge_refuses_without_force(self, script: ModuleType,
                                                    monkeypatch: pytest.MonkeyPatch,
                                                    pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [_finding("src/pkg/a.py", None, name="Rename f helper"),
                            _finding("src/pkg/a.py", None, name="Rename f helpers"),
                            _finding("src/pkg/a.py", "7", name="Other")])
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 0
        assert _run(script, clone, "amend", "--pr", str(_PR), "--regrade", "M1=important",
                    "--merge", "M2+M3") == 0
        draft = json.loads((rm.run_dir(_PR, clone) / "draft.json").read_text(encoding="utf-8"))
        assert sorted(i["id"] for i in draft["issues"]) == ["I1", "M2"]
        assert [op["op"] for op in draft["amend"]] == ["regrade", "merge"]
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 1
        assert _run(script, clone, "merge", "--pr", str(_PR), "--force") == 0

    def test_block_reprints(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                            pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        rm.record(_PR, "runtime", [_finding("src/pkg/a.py")], [], repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "block", "--pr", str(_PR), "--agent", "runtime") == 0
        assert "COUNTS: findings=1 critical=0 important=0 minor=1" in capsys.readouterr().out


class TestBuild:
    def test_schema_valid_with_pre_fix_time(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                            pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["verification_log"]["pre_fix_time"] == _PRE_FIX
        assert doc["verdict"] == "NOT READY TO MERGE - minor findings pending Phase 5: M1"
        assert doc["head_sha"] == head and doc["pr"] == _PR
        assert rmg.validate_review(doc, clone) == []
        plan = _plan(clone)
        assert plan["build_head"] == _git(clone, "rev-parse", "HEAD")
        record = json.loads((rm.run_dir(_PR, clone) / "phase4_first_run.json").read_text(encoding="utf-8"))
        assert record["rc"] == 0

    @pytest.mark.parametrize("rc, stdout, word", [
        (1, json.dumps(_PRE_FIX), "check failed"), (2, "", "argv"), (0, "", "metadata"),
        (1, "", "metadata"),
    ])
    def test_phase4_failure_keeps_pending(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                          pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture,
                                          rc: int, stdout: str, word: str) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [_finding("src/pkg/a.py")])
        _run(script, clone, "merge", "--pr", str(_PR))
        _phase4(monkeypatch, script, rc, stdout, "FAIL: x")
        capsys.readouterr()
        assert _run(script, clone, "build", "--pr", str(_PR)) == 1
        err = capsys.readouterr().err
        assert "problem:" in err and word in err and f"rc {rc}" in err
        doc = json.loads((clone / "docs" / "PR_REVIEWS" / _REVIEW_NAME).read_text(encoding="utf-8"))
        assert doc["verification_log"]["pre_fix_time"] == rmg.PENDING

    def test_clean_tree_stop_names_paths_and_exclusions(self, script: ModuleType,
                                                        monkeypatch: pytest.MonkeyPatch,
                                                        pr_repo: Tuple[Path, str],
                                                        capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [_finding("src/pkg/a.py")])
        _run(script, clone, "merge", "--pr", str(_PR))
        dirty = "".join(f"?? tmp/f{i}.txt\n" for i in range(7))
        block = {**_PRE_FIX, "clean_tree_check": {
            "command": "git status --porcelain --untracked-files=all", "stdout": dirty,
            "filtered_stdout": dirty, "exclusions_fixture": ".claude/review_exclusions.json",
            "result": "STOP: working tree has non-exempt changes"}}
        _phase4(monkeypatch, script, 1, json.dumps(block), "")
        capsys.readouterr()
        assert _run(script, clone, "build", "--pr", str(_PR)) == 1
        err = capsys.readouterr().err
        assert "a branch-safety check failed: clean_tree_check" in err
        assert "tmp/f0.txt, tmp/f1.txt" in err and "tmp/f5.txt" not in err and "(+2 more)" in err
        assert ".claude/review_exclusions.json" in err
        assert len([ln for ln in err.splitlines() if "phase4 first run" in ln]) == 1

    def test_phase4_failure_holds_a_ready_verdict(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                  pr_repo: Tuple[Path, str],
                                                  capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [])
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 0
        _phase4(monkeypatch, script, 1, json.dumps(_PRE_FIX), "FAIL: x")
        capsys.readouterr()
        assert _run(script, clone, "build", "--pr", str(_PR)) == 1
        assert "rc 1" in capsys.readouterr().err
        doc = json.loads((clone / "docs" / "PR_REVIEWS" / _REVIEW_NAME).read_text(encoding="utf-8"))
        assert doc["verdict"] == "NOT READY TO MERGE - Phase 4 first run failed: a branch-safety check failed"
        assert doc["verification_log"]["pre_fix_time"] == rmg.PENDING
        assert rmg.validate_review(doc, clone) == []
        assert _plan(clone)["review_path"] == f"docs/PR_REVIEWS/{_REVIEW_NAME}"

    @pytest.mark.parametrize("command", ["waves", "bubbles"])
    def test_phase4_failure_blocks_fix_planning(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture,
                                                command: str) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [_finding("src/pkg/a.py")])
        _run(script, clone, "merge", "--pr", str(_PR))
        _phase4(monkeypatch, script, 1, json.dumps(_PRE_FIX), "FAIL: x")
        assert _run(script, clone, "build", "--pr", str(_PR)) == 1
        capsys.readouterr()
        assert _run(script, clone, command, "--pr", str(_PR)) == 1
        assert "problem:" in capsys.readouterr().err
        assert not (rm.run_dir(_PR, clone) / "waves.json").exists()

    def test_straggler_and_replace(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                   pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        capsys.readouterr()
        assert _run(script, clone, "build", "--pr", str(_PR)) == 1
        assert "--replace" in capsys.readouterr().err
        assert _run(script, clone, "build", "--pr", str(_PR), "--replace") == 0
        straggler = path.parent / "1234_reviewer_notes.json"
        straggler.write_text("{}", encoding="utf-8")
        capsys.readouterr()
        assert _run(script, clone, "build", "--pr", str(_PR), "--replace") == 1
        assert "1234_reviewer_notes.json" in capsys.readouterr().err

    def test_replace_refused_after_bubble(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                          pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "bubble", "--pr", str(_PR), "M1", "--classification", "out_of_scope",
                    "--reason", "r") == 0
        before, phase = path.read_bytes(), _plan(clone)["phase"]
        capsys.readouterr()
        assert _run(script, clone, "build", "--pr", str(_PR), "--replace") == 1
        err = capsys.readouterr().err
        assert "problem: Phase 5 began" in err and "bubbles" in err and "new capture" in err
        assert path.read_bytes() == before and _plan(clone)["phase"] == phase

    def test_replace_refused_after_waves(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                         pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        before = path.read_bytes()
        capsys.readouterr()
        assert _run(script, clone, "build", "--pr", str(_PR), "--replace") == 1
        err = capsys.readouterr().err
        assert "problem: Phase 5 began" in err and "waves.json" in err
        assert path.read_bytes() == before and _plan(clone)["phase"] == "fix"

    def test_replace_refused_after_closeout(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                            pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        _resolve_m1(script, clone)
        before = path.read_bytes()
        capsys.readouterr()
        assert _run(script, clone, "build", "--pr", str(_PR), "--replace") == 1
        assert "post_review_resolutions" in capsys.readouterr().err
        assert path.read_bytes() == before and _plan(clone)["phase"] == "done"


class TestBubble:
    def test_unknown_id_leaves_file_unchanged(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                              pr_repo: Tuple[Path, str],
                                              capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        before = path.read_bytes()
        capsys.readouterr()
        assert _run(script, clone, "bubble", "--pr", str(_PR), "M9", "--classification", "out_of_scope",
                    "--reason", "r") == 1
        assert "M9" in capsys.readouterr().err and path.read_bytes() == before

    def test_bubble_recomputes_verdict(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                       pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "bubble", "--pr", str(_PR), "M1", "--classification", "out_of_scope",
                    "--reason", "belongs to another PR") == 0
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["bubbles"] == ["M1"] and doc["bubble_up"][0]["classification"] == "out_of_scope"
        assert doc["verdict"] == "READY TO MERGE - 0 of 1 findings resolved, 1 bubbled"

    def test_closed_id_refused_file_unchanged(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                              pr_repo: Tuple[Path, str],
                                              capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        _resolve_m1(script, clone)
        before = path.read_bytes()
        capsys.readouterr()
        assert _run(script, clone, "bubble", "--pr", str(_PR), "M1", "--classification", "out_of_scope",
                    "--reason", "stale") == 1
        assert "M1: already closed" in capsys.readouterr().err and path.read_bytes() == before

    def test_phase4_failure_blocks_bubble(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                          pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [_finding("src/pkg/a.py")])
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 0
        _phase4(monkeypatch, script, 1, json.dumps(_PRE_FIX), "FAIL: x")
        assert _run(script, clone, "build", "--pr", str(_PR)) == 1
        path = clone / "docs" / "PR_REVIEWS" / _REVIEW_NAME
        before, phase = path.read_bytes(), _plan(clone)["phase"]
        capsys.readouterr()
        assert _run(script, clone, "bubble", "--pr", str(_PR), "M1", "--classification", "out_of_scope",
                    "--reason", "r") == 1
        assert "problem:" in capsys.readouterr().err
        assert path.read_bytes() == before and _plan(clone)["phase"] == phase


class TestWavesAndCloseout:
    def test_waves_rows_and_fix_brief(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                      pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head)
        capsys.readouterr()
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        lines = capsys.readouterr().out.splitlines()
        row = next(n for n, line in enumerate(lines) if line.startswith("agent=harness:pr-fixer model="))
        assert lines[row] == "agent=harness:pr-fixer model=haiku"
        assert lines[row + 1:row + 3] == ["AGENT_ID: w1_fix_1", "AGENT_ROLE: fixer"]
        assert lines[row + 3] == f"RUN_ID: {_plan(clone)['run_id']}"
        assert lines[row + 5].startswith("Brief: ")
        brief = _brief(clone, "w1_fix_1", "fix_briefs")
        assert "M1" in brief and "tests/test_a.py" in brief
        assert 'record_fixes(1234, "w1_fix_1"' in brief
        assert '"no_change": ["src/pkg/y.py"]' in brief and "`no_change` list" in brief
        assert "Your part: src/pkg/a.py" in brief and "Other parts:" not in brief
        assert "- tests/test_a.py\n" in brief.split("## Files and tests", 1)[1]
        waves = json.loads((rm.run_dir(_PR, clone) / "waves.json").read_text(encoding="utf-8"))
        assert waves["waves"][0][0]["files"] == ["src/pkg/a.py", "tests/test_a.py"]
        assert waves["waves"][0][0]["parts"] == {"M1": ["src/pkg/a.py"]}

    def test_waves_widen_by_existing_fix_paths(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                               pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        fix = ["Edit src/pkg/a.py, then note it in docs/a.md and docs/missing.md."]
        path = _built(script, monkeypatch, clone, head, [_finding("src/pkg/a.py", fix=fix)])
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        [[fixer]] = _waves(clone)
        assert fixer["files"] == ["docs/a.md", "src/pkg/a.py", "tests/test_a.py"]
        assert fixer["parts"] == {"M1": ["src/pkg/a.py"]}
        _write(clone, "src/pkg/a.py", "def f0():\n    return 0\n")
        _write(clone, "tests/test_a.py", "def test_a():\n    assert 0 == 0\n")
        files = ["src/pkg/a.py", "tests/test_a.py"]
        rm.record_fixes(_PR, "w1_fix_1", [{"id": "M1", "what": "fixed and tested", "files": files}],
                        repo=clone)
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 0
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert [r["id"] for r in doc["post_review_resolutions"]] == ["M1"]

    def test_split_issue_briefs_and_closeout(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, pr_repo: Tuple[Path, str],
            capsys: pytest.CaptureFixture,
    ) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head, _split_findings())
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        waves = json.loads((rm.run_dir(_PR, clone) / "waves.json").read_text(encoding="utf-8"))["waves"]
        assert [[f["parts"] for f in wave] for wave in waves] == [
            [{f"M{n}": ["src/pkg/a.py"] for n in range(1, 7)}, {"M7": ["docs/a.md"]}],
            [{"M7": ["src/pkg/a.py"]}],
        ]
        brief = _normalized(_brief(clone, "w1_fix_2", "fix_briefs"))
        assert "Your part: docs/a.md" in brief
        assert "Other parts: src/pkg/a.py (another fixer)" in brief
        assert "record each id with your part's files plus any new file you created" in brief.lower()
        _write(clone, "docs/a.md", "# A\n\nfixed\n")
        rm.record_fixes(_PR, "w1_fix_2", [{"id": "M7", "what": "docs part", "files": ["docs/a.md"]}],
                        repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 1
        assert "M7 partially fixed: missing src/pkg/a.py" in capsys.readouterr().err
        _write(clone, "src/pkg/a.py", "def f0():\n    return 0\n")
        rm.record_fixes(_PR, "w2_fix_1", [{"id": "M7", "what": "code part", "files": ["src/pkg/a.py"]}],
                        repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 1
        assert "w1_fix_1: no fix report; re-dispatch its row" in capsys.readouterr().err
        fixed = [{"id": f"M{n}", "what": "w", "files": ["src/pkg/a.py"]} for n in range(1, 7)]
        rm.record_fixes(_PR, "w1_fix_1", fixed, repo=clone)
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 0
        doc = json.loads(path.read_text(encoding="utf-8"))
        [entry] = [r for r in doc["post_review_resolutions"] if r["id"] == "M7"]
        assert entry["status"] == "RESOLVED" and entry["evidence"].endswith("- docs part; code part")

    def test_waves_skips_fixed_and_held(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                        pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head, [_finding("src/pkg/a.py"), _finding("docs/a.md")])
        _run(script, clone, "bubble", "--pr", str(_PR), "M2", "--classification", "out_of_scope",
             "--reason", "r")
        rm.record_fixes(_PR, "w1_fix_1", [{"id": "M1", "what": "w", "files": ["docs/a.md"]}], repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        out = capsys.readouterr().out
        assert "agent=harness:pr-fixer" not in out and "held: M2" in out

    def test_closeout_through_the_plugin_hook_subprocess(self, script: ModuleType,
                                                         monkeypatch: pytest.MonkeyPatch,
                                                         pr_repo: Tuple[Path, str],
                                                         capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        _write(clone, "src/pkg/a.py", "def f0():\n    return 0\n")
        rm.record_fixes(_PR, "w1_fix_1", [{"id": "M1", "what": "tidied a", "files": ["src/pkg/a.py"]}],
                        repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 0, capsys.readouterr().err
        assert "Phase 5 [done]" in capsys.readouterr().out

    def test_closeout_end_to_end_clears_sentinel(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                 pr_repo: Tuple[Path, str],
                                                 capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        _write(clone, "src/pkg/a.py", "def f0():\n    return 0\n")
        rm.record_fixes(_PR, "w1_fix_1", [{"id": "M1", "what": "tidied a", "files": ["src/pkg/a.py"]}],
                        repo=clone)
        sentinel = clone / _STATE / "pr-review" / f".phase5_pending_{_PR}"
        _write(clone, sentinel.relative_to(clone).as_posix(), "")
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 0
        out = capsys.readouterr().out
        assert "Phase 5 [done] | 1 issues resolved | verdict: READY TO MERGE" in out
        assert not sentinel.exists()
        doc = json.loads(path.read_text(encoding="utf-8"))
        short = _git(clone, "rev-parse", "--short", "HEAD")
        assert doc["post_review_resolutions"][0]["evidence"].startswith(f"{short} ")
        assert rmg.validate_review(doc, clone) == []

    def test_closeout_unchanged_file_is_a_problem(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                  pr_repo: Tuple[Path, str],
                                                  capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        _run(script, clone, "waves", "--pr", str(_PR))
        fixed = [{"id": "M1", "what": "w", "files": ["src/pkg/a.py"]}]
        rm.record_fixes(_PR, "w1_fix_1", fixed, repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 1
        assert "not changed" in capsys.readouterr().err
        assert _run(script, clone, "closeout", "--pr", str(_PR), "--closed", "M1=not needed") == 0
        assert "not changed" not in capsys.readouterr().err
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert [r["status"] for r in doc["post_review_resolutions"]] == ["CLOSED_NO_ACTION"]

    def test_closeout_without_fix_report_is_blocked(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                    pr_repo: Tuple[Path, str],
                                                    capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 1
        captured = capsys.readouterr()
        assert "w1_fix_1: no fix report; re-dispatch its row" in captured.err
        assert "Phase 5 [blocked] | 1 problems" in captured.out and "next: stop" not in captured.out
        assert _plan(clone)["phase"] == "fix"

    def test_closeout_with_unrecorded_planned_id_is_blocked(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, pr_repo: Tuple[Path, str],
            capsys: pytest.CaptureFixture,
    ) -> None:
        clone, head = pr_repo
        runtime = [_finding("src/pkg/a.py"), _finding("src/pkg/a.py", "40", name="Second")]
        _built(script, monkeypatch, clone, head, runtime)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        assert _waves(clone)[0][0]["issue_ids"] == ["M1", "M2"]
        _write(clone, "src/pkg/a.py", "def f0():\n    return 0\n")
        rm.record_fixes(_PR, "w1_fix_1", [{"id": "M2", "what": "w", "files": ["src/pkg/a.py"]}],
                        repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 1
        captured = capsys.readouterr()
        assert "M1: planned for w1_fix_1 but not recorded; rerun waves" in captured.err
        assert "Phase 5 [blocked]" in captured.out and "next: stop" not in captured.out

    def test_rejected_entry_superseded_by_follow_up_fixer(self, script: ModuleType,
                                                          monkeypatch: pytest.MonkeyPatch,
                                                          pr_repo: Tuple[Path, str],
                                                          capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        _write(clone, "docs/a.md", "# A\n\nedited\n")
        rm.record_fixes(_PR, "w1_fix_1", [{"id": "M1", "what": "w", "files": ["docs/a.md"]}], repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 1
        assert "M1 (w1_fix_1)" in capsys.readouterr().err
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        assert [(f["id"], f["issue_ids"]) for f in _waves(clone)[1]] == [("w2_fix_1", ["M1"])]
        _write(clone, "src/pkg/a.py", "def f0():\n    return 0\n")
        rm.record_fixes(_PR, "w2_fix_1", [{"id": "M1", "what": "redone", "files": ["src/pkg/a.py"]}],
                        repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 0
        assert "M1 (w1_fix_1)" not in capsys.readouterr().err
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert [(r["id"], r["status"]) for r in doc["post_review_resolutions"]] == [("M1", "RESOLVED")]


def _waves(clone: Path) -> List[List[Dict[str, object]]]:
    """The run's planned waves."""
    return json.loads((rm.run_dir(_PR, clone) / "waves.json").read_text(encoding="utf-8"))["waves"]


_DEFER_TESTS = {"registry": "tests/registry.json", "timings": "reports/timings.json",
                "fixer_test_seconds": 60, "defer_flags": ["properties.super_slow"]}
_DEFER_CONFIG = {**_CONFIG, "tests": _DEFER_TESTS}
_DEFER_REGISTRY = {"tests": [
    {"file": "tests/test_a.py", "properties": {"test_target_paths": ["src/pkg/a.py"]}},
    {"file": "tests/test_slow.py", "properties": {"test_target_paths": ["src/pkg/"]}},
    {"file": "tests/test_flagged.py",
     "properties": {"super_slow": True, "test_target_paths": ["src/pkg/a.py"]}},
]}
# test_slow.py crosses the ceiling only summed (50 + 40 > 60); test_flagged.py is fast but flagged.
_TIMINGS = {"tests": [{"file": "tests/test_a.py", "duration": 0.5},
                      {"file": "tests/test_slow.py", "duration": 50.0},
                      {"file": "tests/test_slow.py", "duration": 40.0},
                      {"file": "tests/test_flagged.py", "duration": 1.0}]}


def _defer_pr(make_project, timings: bool = True) -> Tuple[Path, str]:
    """A PR whose registry targets ``src/pkg/a.py`` with a fast, a measured-slow and a flagged test;
    ``timings`` False leaves the configured ``reports/timings.json`` out."""
    extra = {"tests/test_slow.py": "def test_slow():\n    assert True\n",
             "tests/test_flagged.py": "def test_flagged():\n    assert True\n"}
    base: Dict[str, object] = {"tests/registry.json": _DEFER_REGISTRY}
    if timings:
        base["reports/timings.json"] = _TIMINGS
    return _make_pr(make_project, extra, _DEFER_CONFIG, base)


def _run_lines(text: str) -> List[str]:
    """Lines of ``text`` that carry a pytest run command."""
    return [line for line in text.splitlines() if " -m pytest " in line]


class TestDeferredTests:
    def test_fixer_brief_lists_slow_and_flagged_tests_as_deferred(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, make_project,
    ) -> None:
        clone, head = _defer_pr(make_project)
        _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        brief = _brief(clone, "w1_fix_1", "fix_briefs")
        tests = brief.split("## Files and tests", 1)[1].split("## Rules", 1)[0]
        runs = _run_lines(tests)
        assert runs and all("tests/test_a.py" in line for line in runs)
        assert "- deferred, do not run: `tests/test_slow.py` (measured 90 s > 60 s)" in tests
        assert "- deferred, do not run: `tests/test_flagged.py` (properties.super_slow)" in tests

    def test_closeout_prints_deferred_tests_the_fixes_reach(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, make_project,
            capsys: pytest.CaptureFixture,
    ) -> None:
        clone, head = _defer_pr(make_project)
        _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        _write(clone, "src/pkg/a.py", "def f0():\n    return 0\n")
        rm.record_fixes(_PR, "w1_fix_1", [{"id": "M1", "what": "tidied a", "files": ["src/pkg/a.py"]}],
                        repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 0
        out = capsys.readouterr().out
        assert ("deferred tests: 2 file(s) the changes since build_head reach; run them before commit:"
                in out)
        assert "  - tests/test_flagged.py (properties.super_slow)" in out
        assert "  - tests/test_slow.py (measured 90 s > 60 s)" in out
        [run] = _run_lines(out)
        assert "tests/test_flagged.py" in run and "tests/test_slow.py" in run
        assert "tests/test_a.py" not in run

    def test_closeout_prints_nothing_when_no_deferred_test_is_reached(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, make_project,
            capsys: pytest.CaptureFixture,
    ) -> None:
        clone, head = _defer_pr(make_project)
        _built(script, monkeypatch, clone, head, [_finding("docs/a.md")])
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        _write(clone, "docs/a.md", "# A\n\nfixed\n")
        rm.record_fixes(_PR, "w1_fix_1", [{"id": "M1", "what": "w", "files": ["docs/a.md"]}], repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 0
        assert "deferred tests" not in capsys.readouterr().out

    @pytest.mark.parametrize("timings", [None, "{not json", {"tests": [{"file": "tests/test_slow.py"}]},
                                         {"tests": [{"file": "tests/test_slow.py", "duration": "90"}]},
                                         {"tests": [{"file": "tests/test_slow.py", "duration": True}]},
                                         [{"file": "tests/test_slow.py", "duration": 90}]])
    def test_unusable_timings_defer_by_flags_only(self, script: ModuleType, make_project,
                                                  timings: object) -> None:
        files: Dict[str, object] = {"tests/registry.json": _DEFER_REGISTRY}
        if timings is not None:
            files["reports/timings.json"] = timings
        repo = make_project(_DEFER_CONFIG, files)
        activate(load_config(repo))
        assert script.defer_reasons(repo) == {"tests/test_flagged.py": "properties.super_slow"}
        assert script.ceiling_line(repo) == ("deferral: tests.timings reports/timings.json missing or "
                                             "unusable; runtime ceiling inactive (flags only)")

    @pytest.mark.parametrize("flags, expected", [
        ([], {}), (["properties.super_slow"], {"tests/test_flagged.py": "properties.super_slow"})])
    def test_no_ceiling_ignores_timings(self, script: ModuleType, make_project, flags: List[str],
                                        expected: Dict[str, str]) -> None:
        config = {**_CONFIG, "tests": {**_DEFER_TESTS, "fixer_test_seconds": None, "defer_flags": flags}}
        files = {"tests/registry.json": _DEFER_REGISTRY, "reports/timings.json": _TIMINGS}
        repo = make_project(config, files)
        activate(load_config(repo))
        assert script.defer_reasons(repo) == expected
        assert script.ceiling_line(repo) is None

    def test_measured_reason_keeps_the_fraction(self, script: ModuleType, make_project) -> None:
        timings = {"tests": [{"file": "tests/test_slow.py", "duration": 60.4}]}
        repo = make_project(_DEFER_CONFIG, {"tests/registry.json": _DEFER_REGISTRY,
                                            "reports/timings.json": timings})
        activate(load_config(repo))
        assert script.defer_reasons(repo)["tests/test_slow.py"] == "measured 60.4 s > 60 s"
        assert script.ceiling_line(repo) is None

    def test_waves_reports_an_inactive_ceiling(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, make_project,
            capsys: pytest.CaptureFixture,
    ) -> None:
        clone, head = _defer_pr(make_project, timings=False)
        _built(script, monkeypatch, clone, head)
        capsys.readouterr()
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        out = capsys.readouterr().out
        assert "deferral: tests.timings reports/timings.json missing or unusable" in out
        assert "(measured " not in _brief(clone, "w1_fix_1", "fix_briefs")


class TestFollowUpWaves:
    def test_partially_fixed_split_issue_replans_missing_part(self, script: ModuleType,
                                                              monkeypatch: pytest.MonkeyPatch,
                                                              pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head, _split_findings())
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        fixed = [{"id": f"M{n}", "what": "w", "files": ["src/pkg/a.py"]} for n in range(1, 7)]
        rm.record_fixes(_PR, "w1_fix_1", fixed, repo=clone)
        rm.record_fixes(_PR, "w1_fix_2", [{"id": "M7", "what": "docs", "files": ["docs/a.md"]}], repo=clone)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        third = _waves(clone)[2]
        assert [(f["id"], f["parts"]) for f in third] == [("w3_fix_1", {"M7": ["src/pkg/a.py"]})]
        brief = _normalized(_brief(clone, "w3_fix_1", "fix_briefs"))
        assert "Your part: src/pkg/a.py" in brief and "Other parts: docs/a.md (another fixer)" in brief

    def test_ids_follow_up_after_bubble(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                        pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head, [_finding("src/pkg/a.py"), _finding("docs/a.md")])
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        w1_brief = rm.run_dir(_PR, clone) / "fix_briefs" / "w1_fix_1.md"
        before = w1_brief.read_bytes()
        assert _run(script, clone, "bubble", "--pr", str(_PR), "M2", "--classification",
                    "architectural_ambiguity", "--reason", "two options") == 0
        capsys.readouterr()
        assert _run(script, clone, "waves", "--pr", str(_PR), "--ids", "M2") == 0
        out = capsys.readouterr().out
        ids = [line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("AGENT_ID: ")]
        assert ids and all(i.startswith("w2_") for i in ids)
        waves = _waves(clone)
        assert len(waves) == 2 and waves[1][0]["issue_ids"] == ["M2"]
        assert w1_brief.read_bytes() == before
        assert _run(script, clone, "waves", "--pr", str(_PR), "--ids", "M2,M9") == 1
        assert "M9" in capsys.readouterr().err

    def test_fixer_heredoc_pins_run_id(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                       pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        run_id = _plan(clone)["run_id"]
        assert f'run_id="{run_id}"' in _heredoc(_brief(clone, "w1_fix_1", "fix_briefs"))


class TestPendingBubbles:
    def test_bubbles_and_waves_print_pending_fixer_bubbles(self, script: ModuleType,
                                                           monkeypatch: pytest.MonkeyPatch,
                                                           pr_repo: Tuple[Path, str],
                                                           capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head, [_finding("src/pkg/a.py"), _finding("docs/a.md")])
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        bubble = {"id": "M1", "classification": "out_of_scope", "reason": "belongs elsewhere"}
        rm.record_fixes(_PR, "w1_fix_1", [], [bubble], repo=clone)
        before = path.read_bytes()
        capsys.readouterr()
        assert _run(script, clone, "bubbles", "--pr", str(_PR)) == 0
        line = "  M1 (out_of_scope) from w1_fix_1: belongs elsewhere"
        assert line in capsys.readouterr().out.splitlines() and path.read_bytes() == before
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        out = capsys.readouterr().out
        assert line in out.splitlines()
        assert "AGENT_ID: w2_fix_1" in out and "M1" not in _waves(clone)[1][0]["issue_ids"]
        assert _run(script, clone, "bubble", "--pr", str(_PR), "M1", "--classification", "out_of_scope",
                    "--reason", "belongs elsewhere") == 0
        capsys.readouterr()
        assert _run(script, clone, "bubbles", "--pr", str(_PR)) == 0
        assert "pending fixer bubbles: none" in capsys.readouterr().out

    def test_rejected_fixer_bubble_is_replanned(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        bubble = {"id": "M1", "classification": "out_of_scope", "reason": "belongs elsewhere"}
        rm.record_fixes(_PR, "w9_fix_1", [], [bubble], repo=clone)
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 1
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        assert [f["issue_ids"] for f in _waves(clone)[1]] == [["M1"]]
        rm.record_fixes(_PR, "w2_fix_1", [], [bubble], repo=clone)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        assert len(_waves(clone)) == 2


class TestDeferredCloseout:
    def test_deferred_resolves_bubbled_issue(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                             pr_repo: Tuple[Path, str],
                                             capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "bubble", "--pr", str(_PR), "M1", "--classification",
                    "architectural_ambiguity", "--reason", "two options") == 0
        assert _run(script, clone, "closeout", "--pr", str(_PR), "--deferred", "M1=keep as is; GH #9") == 0
        doc = json.loads(path.read_text(encoding="utf-8"))
        short = _git(clone, "rev-parse", "--short", "HEAD")
        [entry] = doc["post_review_resolutions"]
        assert entry["status"] == "RESOLVED"
        assert entry["evidence"] == f"{short} (developer-confirmed defer) - keep as is; GH #9"
        assert doc["bubbles"] == [] and [b["id"] for b in doc["bubble_up"]] == ["M1"]
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR), "--deferred", "M1") == 1
        assert "ID=" in capsys.readouterr().err


def _ancestry_block(head_exit: int, base_exit: int = 0, **other: str) -> str:
    """A Phase 4 stdout block whose sha_ancestry_check carries the given exits (STOP when either fails)."""
    block = json.loads(json.dumps(_PRE_FIX))
    check = block["sha_ancestry_check"]
    check.update(head_ancestor_exit=head_exit, base_ancestor_exit=base_exit)
    if head_exit or base_exit:
        check["result"] = "STOP: not ancestors of HEAD -- HEAD_SHA y"
    for name, result in other.items():
        block[name]["result"] = result
    return json.dumps(block)


class TestHeadAncestryWaiver:
    def _merged(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, clone: Path, head: str) -> None:
        """Capture, record and merge one minor finding."""
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [_finding("src/pkg/a.py")])
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 0

    def test_waived_head_desync_inserts_pre_fix_time(self, script: ModuleType,
                                                     monkeypatch: pytest.MonkeyPatch,
                                                     pr_repo: Tuple[Path, str],
                                                     capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        self._merged(script, monkeypatch, clone, head)
        stdout = _ancestry_block(head_exit=1)
        _phase4(monkeypatch, script, 1, stdout, "FAIL: Phase 4 checks failed: sha_ancestry_check")
        capsys.readouterr()
        assert _run(script, clone, "build", "--pr", str(_PR)) == 1
        assert "--waive-head-ancestry" in capsys.readouterr().err
        assert _run(script, clone, "build", "--pr", str(_PR), "--replace", "--waive-head-ancestry") == 0
        assert "head-ancestry" in capsys.readouterr().out
        doc = json.loads((clone / "docs" / "PR_REVIEWS" / _REVIEW_NAME).read_text(encoding="utf-8"))
        assert doc["verification_log"]["pre_fix_time"] == json.loads(stdout)
        assert _plan(clone)["phase4_waiver"]["check"] == "sha_ancestry_check"

    @pytest.mark.parametrize("stdout", [
        _ancestry_block(head_exit=1, base_exit=1),
        _ancestry_block(head_exit=1, clean_tree_check="STOP: working tree has non-exempt changes"),
    ])
    def test_other_failures_stay_stops(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                       pr_repo: Tuple[Path, str], stdout: str) -> None:
        clone, head = pr_repo
        self._merged(script, monkeypatch, clone, head)
        _phase4(monkeypatch, script, 1, stdout)
        assert _run(script, clone, "build", "--pr", str(_PR), "--waive-head-ancestry") == 1
        doc = json.loads((clone / "docs" / "PR_REVIEWS" / _REVIEW_NAME).read_text(encoding="utf-8"))
        assert doc["verification_log"]["pre_fix_time"] == rmg.PENDING
        assert not _plan(clone).get("phase4_waiver")


class TestPathsAndScope:
    def test_changed_paths_reads_rename_as_delete_and_create(self, script: ModuleType,
                                                             pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        _git(clone, "mv", "src/pkg/b.py", "src/pkg/c.py")
        changed, created = script.changed_paths(clone, head)
        assert {"src/pkg/b.py", "src/pkg/c.py"} <= changed
        assert "src/pkg/c.py" in created and "src/pkg/b.py" not in created

    def test_status_paths_and_tree_at_head(self, script: ModuleType, pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        assert script.status_paths(clone) == set()
        assert script.tree_at_head(clone, head, ["src/pkg/a.py"])
        _git(clone, "mv", "src/pkg/b.py", "src/pkg/c.py")
        _write(clone, "src/pkg/a.py", "edited\n")
        _write(clone, "docs/new dir/n.md", "untracked\n")
        _write(clone, "build/ignored.md", "ignored\n")
        assert script.status_paths(clone) == {"src/pkg/b.py", "src/pkg/c.py", "src/pkg/a.py",
                                              "docs/new dir/n.md"}
        assert not script.tree_at_head(clone, head, ["src/pkg/b.py"])
        assert script.tree_at_head(clone, head, ["docs/a.md"])

    def test_tests_for_includes_registered_test_file(self, script: ModuleType) -> None:
        entries = [("tests/test_a.py", ("src/pkg/a.py",))]
        assert script.tests_for("tests/test_a.py", entries) == ["tests/test_a.py"]
        assert script.tests_for("src/pkg/a.py", entries) == ["tests/test_a.py"]
        assert script.tests_for("src/pkg/b.py", entries) == []

    @pytest.mark.parametrize("path", [
        "tests/workflows/test_render_comment.py", "src/pkg/conftest.py",
        ".claude/mods/x/hooks/tracker.test.ts", "web/app.test.js",
    ])
    def test_test_design_clause_for_any_test_file(self, script: ModuleType, path: str) -> None:
        slot = script.rp.Slot("cicd", "cicd", "sonnet", (path,), ())
        assert _normalized(script.TEST_DESIGN_CLAUSE) in _normalized(script.rules_section(slot))

    def test_no_test_design_clause_without_test_files(self, script: ModuleType) -> None:
        slot = script.rp.Slot("cicd", "cicd", "sonnet", (".github/workflows/ci.yml",), ())
        assert _normalized(script.TEST_DESIGN_CLAUSE) not in _normalized(script.rules_section(slot))

    def test_fixer_rules_cover_failed_and_out_of_scope(self, script: ModuleType) -> None:
        rules = _normalized("\n".join(script._fixer_rules()))
        assert "`fixer_failed`" in rules and "naming the test" in rules
        assert "outside the file set" in rules and "`out_of_scope`" in rules
        assert "`no_change` list" in rules and "list edited files under `files`" in rules
        assert "already present" in rules
        assert "closeout resolves it once one of those files changed since the build" in rules
        assert "Never run a test marked deferred" in rules


_URL = f"https://github.com/o/r/pull/{_PR}#pullrequestreview-77"


def _fold(script: ModuleType, clone: Path, source: str, kind: str, *argv: str) -> int:
    """Run ``fold`` for ``source`` of ``kind``."""
    return _run(script, clone, "fold", "--pr", str(_PR), "--source", source, "--kind", kind, *argv)


def _findings_file(tmp_path: Path, data: object, name: str = "findings.json") -> Path:
    """``data`` written as JSON to ``tmp_path/name``."""
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _report(clone: Path, agent: str) -> Dict[str, object]:
    """A recorded findings report of the current run."""
    return json.loads((rm.run_dir(_PR, clone) / "findings" / f"{agent}.json").read_text(encoding="utf-8"))


def _gh_review(review: Dict[str, object], comments: Sequence[Dict[str, object]],
               files: Sequence[Tuple[str, str]] = ()) -> Tuple[List[Sequence[str]], object]:
    """A ``run_gh`` fake for one PR review: the review, its comments (two concatenated pages) and the PR
    files."""
    calls: List[Sequence[str]] = []

    def fake(repo: Path, args: Sequence[str]) -> str:
        calls.append(list(args))
        if args[-1].endswith("/comments"):
            return json.dumps(list(comments[:1])) + json.dumps(list(comments[1:]))
        if args[-1].endswith("/files"):
            return json.dumps([{"filename": f, "status": s} for f, s in files])
        return json.dumps(review)

    return calls, fake


def _comment(path: str, body: str, **fields: object) -> Dict[str, object]:
    """A review comment by ``alice`` on ``path``."""
    return {"path": path, "body": body, "user": {"login": "alice"}, "line": None, "start_line": None,
            "original_line": None, "position": None, **fields}


_REVIEW = {"id": 77, "state": "COMMENTED", "body": "", "user": {"login": "alice"}}


class TestFold:
    @pytest.mark.parametrize("kind, shape", [("external", "list"), ("tests", "object"),
                                             ("developer", "stdin"), ("adhoc", "list")])
    def test_each_kind_through_findings(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                        pr_repo: Tuple[Path, str], tmp_path: Path, kind: str,
                                        shape: str) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        findings = [_finding("docs/a.md", "3", name="Stale line")]
        data = {"findings": findings, "strengths": ["tidy"]} if shape == "object" else findings
        if shape == "stdin":
            monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(data)))
            origin, arg = "stdin", "-"
        else:
            path = _findings_file(tmp_path, data)
            origin, arg = path.as_posix(), str(path)
        assert _fold(script, clone, f"{kind}_one", kind, "--findings", arg) == 0
        [entry] = _plan(clone)["folded"]
        assert (entry["id"], entry["kind"], entry["origin"]) == (f"{kind}_one", kind, origin)
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$", entry["at"])
        report = _report(clone, f"{kind}_one")
        assert report["findings"][0]["name"] == "Stale line"
        assert report["strengths"] == (["tidy"] if shape == "object" else [])
        assert _plan(clone)["phase"] == "review"

    def test_refold_replaces_report_and_entry(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                              pr_repo: Tuple[Path, str], tmp_path: Path) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        first = _findings_file(tmp_path, [_finding("docs/a.md"), _finding("src/pkg/a.py")], "one.json")
        second = _findings_file(tmp_path, [_finding("docs/a.md", name="Only one")], "two.json")
        assert _fold(script, clone, "ext", "external", "--findings", str(first)) == 0
        assert _fold(script, clone, "ext", "developer", "--findings", str(second)) == 0
        assert [(e["id"], e["kind"]) for e in _plan(clone)["folded"]] == [("ext", "developer")]
        assert [f["name"] for f in _report(clone, "ext")["findings"]] == ["Only one"]

    def test_invalid_finding_is_a_problem(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                          pr_repo: Tuple[Path, str], tmp_path: Path,
                                          capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        bad = _finding("docs/a.md")
        del bad["fix"]
        capsys.readouterr()
        bad_file = str(_findings_file(tmp_path, [bad]))
        assert _fold(script, clone, "ext", "external", "--findings", bad_file) == 1
        assert "fix" in capsys.readouterr().err
        assert not _plan(clone).get("folded")

    def test_slot_id_refused(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                             pr_repo: Tuple[Path, str], tmp_path: Path,
                             capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        capsys.readouterr()
        path = _findings_file(tmp_path, [_finding("docs/a.md")])
        assert _fold(script, clone, "runtime", "external", "--findings", str(path)) == 1
        assert "slot" in capsys.readouterr().err

    def test_gh_review_mapping(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                               pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        comments = [
            _comment("src/pkg/a.py", "Off by one here. Use range(n).", line=7, start_line=5),
            _comment("docs/a.md", "Typo", original_line=3),
            _comment("src/pkg/b.py", "New constant unused", position=4),
            _comment("src/pkg/a.py", "Outdated hunk\n\n  still wrong", position=9),
            _comment("docs/a.md", "   "),
        ]
        files = [("src/pkg/b.py", "added"), ("src/pkg/a.py", "modified")]
        calls, fake = _gh_review(_REVIEW, comments, files)
        monkeypatch.setattr(script, "run_gh", fake)
        assert _fold(script, clone, "alice_review", "external", "--from-gh-review", _URL,
                     "--severity", "important") == 0
        found = _report(clone, "alice_review")["findings"]
        assert [(f["file"], f.get("lines")) for f in found] == [
            ("src/pkg/a.py", "5-7"), ("docs/a.md", "3"), ("src/pkg/b.py", "4"), ("src/pkg/a.py", None)]
        first = found[0]
        assert first["name"] == "Off by one here."
        assert first["summary"] == "alice (pullrequestreview-77): Off by one here. Use range(n)."
        assert first["fix"] == ["Off by one here. Use range(n)."]
        assert {f["severity"] for f in found} == {"important"} and first["fix_kind"] == "judgment"
        assert found[3]["summary"] == "alice (pullrequestreview-77): Outdated hunk still wrong"
        assert ["api", "repos/o/r/pulls/1234/reviews/77"] in calls
        assert _plan(clone)["folded"][0]["origin"] == _URL

    @pytest.mark.parametrize("review, comments, word", [
        ({**_REVIEW, "state": "DISMISSED", "body": "x"}, [_comment("docs/a.md", "y", original_line=1)],
         "DISMISSED"),
        ({**_REVIEW, "body": "  "}, [], "blank"),
    ])
    def test_gh_review_skipped(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                               pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture,
                               review: Dict[str, object], comments: List[Dict[str, object]],
                               word: str) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        monkeypatch.setattr(script, "run_gh", _gh_review(review, comments)[1])
        capsys.readouterr()
        assert _fold(script, clone, "alice_review", "external", "--from-gh-review", _URL) == 1
        assert word in capsys.readouterr().err
        assert not _plan(clone).get("folded")
        assert not (rm.run_dir(_PR, clone) / "findings" / "alice_review.json").exists()

    def test_gh_review_url_for_another_pr_refused(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                  pr_repo: Tuple[Path, str],
                                                  capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        capsys.readouterr()
        url = "https://github.com/o/r/pull/99#pullrequestreview-77"
        assert _fold(script, clone, "alice_review", "external", "--from-gh-review", url) == 1
        assert "99" in capsys.readouterr().err

    def test_gh_review_url_for_another_repository_refused(self, script: ModuleType,
                                                          monkeypatch: pytest.MonkeyPatch,
                                                          pr_repo: Tuple[Path, str],
                                                          capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        calls, fake = _gh_review(_REVIEW, [_comment("docs/a.md", "y", original_line=1)])
        monkeypatch.setattr(script, "run_gh", fake)
        capsys.readouterr()
        url = f"https://github.com/x/other/pull/{_PR}#pullrequestreview-77"
        assert _fold(script, clone, "alice_review", "external", "--from-gh-review", url) == 1
        assert "x/other" in capsys.readouterr().err
        assert not calls and not _plan(clone).get("folded")

    def test_fold_after_merge_notes_rerun_and_build_refuses(self, script: ModuleType,
                                                            monkeypatch: pytest.MonkeyPatch,
                                                            pr_repo: Tuple[Path, str], tmp_path: Path,
                                                            capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [_finding("src/pkg/a.py")])
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 0
        capsys.readouterr()
        path = _findings_file(tmp_path, [_finding("docs/a.md")])
        assert _fold(script, clone, "ext", "external", "--findings", str(path)) == 0
        assert "rerun merge" in capsys.readouterr().out
        _phase4(monkeypatch, script)
        assert _run(script, clone, "build", "--pr", str(_PR)) == 1
        assert "ext" in capsys.readouterr().err and not _plan(clone).get("review_path")


def _review_doc(path: Path) -> Dict[str, object]:
    """The review document at ``path``."""
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_m1(script: ModuleType, clone: Path) -> None:
    """Plan waves, fix M1 through ``w1_fix_1`` and close it out (M1 RESOLVED)."""
    assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
    _write(clone, "src/pkg/a.py", "def f0():\n    return 0\n")
    rm.record_fixes(_PR, "w1_fix_1", [{"id": "M1", "what": "tidied a", "files": ["src/pkg/a.py"]}],
                    repo=clone)
    assert _run(script, clone, "closeout", "--pr", str(_PR)) == 0


class TestFoldAfterBuild:
    def test_appends_keeps_resolution_and_waves_plan_new_ids(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, pr_repo: Tuple[Path, str],
            tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        _resolve_m1(script, clone)
        before = _review_doc(path)
        assert before["verdict"].startswith("READY TO MERGE")
        found = [_finding("src/pkg/b.py", "4", name="Odd name"), _finding("docs/a.md", "3", name="Stale")]
        capsys.readouterr()
        found_file = str(_findings_file(tmp_path, found))
        assert _fold(script, clone, "ext", "external", "--findings", found_file) == 0
        out = capsys.readouterr().out
        doc = _review_doc(path)
        added = doc["issues"]["minor"][1:]
        assert [(i["id"], i["file"], i["reviewer"]) for i in added] == [
            ("M2", "docs/a.md", "ext"), ("M3", "src/pkg/b.py", "ext")]
        assert doc["issues"]["minor"][0] == before["issues"]["minor"][0]
        assert doc["post_review_resolutions"] == before["post_review_resolutions"]
        assert doc["bubbles"] == before["bubbles"] and doc["bubble_up"] == before["bubble_up"]
        assert doc["verdict"] == "NOT READY TO MERGE - minor findings pending Phase 5: M2, M3"
        assert doc["reviewers"][-1] == "ext (external)"
        assert rmg.validate_review(doc, clone) == []
        assert all(script.issue_row(i) in out for i in added)
        assert out.rstrip().splitlines()[-1] == "next: Phase 4 second run, then waves (new ids only)"
        plan = _plan(clone)
        assert plan["phase"] == "consolidate" and plan["folded"][-1]["after_build"] is True
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        assert sorted(i for f in _waves(clone)[-1] for i in f["parts"]) == ["M2", "M3"]

    def test_mid_pass_fold_skips_second_run(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, pr_repo: Tuple[Path, str],
            tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        assert _plan(clone)["phase"] == "fix"
        capsys.readouterr()
        found = [_finding("docs/a.md", "3", name="Stale")]
        found_file = str(_findings_file(tmp_path, found))
        assert _fold(script, clone, "ext", "external", "--findings", found_file) == 0
        assert capsys.readouterr().out.rstrip().splitlines()[-1] == (
            "next: waves (new ids only), then closeout (Phase 5 pass open: no second run)")
        assert _plan(clone)["phase"] == "fix"

    def test_two_folds_after_closeout_both_name_second_run(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, pr_repo: Tuple[Path, str],
            tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head)
        _resolve_m1(script, clone)
        assert _plan(clone)["phase"] == "done"
        for source, file in (("ext_one", "docs/a.md"), ("ext_two", "src/pkg/b.py")):
            found = _findings_file(tmp_path, [_finding(file, "3", name=f"{source} finding")],
                                   f"{source}.json")
            capsys.readouterr()
            assert _fold(script, clone, source, "external", "--findings", str(found)) == 0
            assert capsys.readouterr().out.rstrip().splitlines()[-1] == (
                "next: Phase 4 second run, then waves (new ids only)")
            assert _plan(clone)["phase"] == "consolidate"

    def test_failed_first_run_refuses_fold_and_closeout(
            self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, pr_repo: Tuple[Path, str],
            tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [_finding("src/pkg/a.py")])
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 0
        _phase4(monkeypatch, script, 1, json.dumps(_PRE_FIX), "FAIL: x")
        assert _run(script, clone, "build", "--pr", str(_PR)) == 1
        path = clone / "docs" / "PR_REVIEWS" / _REVIEW_NAME
        before, plan = path.read_bytes(), _plan(clone)
        capsys.readouterr()
        found = _findings_file(tmp_path, [_finding("docs/a.md", "3", name="Stale")])
        assert _fold(script, clone, "ext", "external", "--findings", str(found)) == 1
        assert "rerun build --replace before folding" in capsys.readouterr().err
        assert not (rm.run_dir(_PR, clone) / "findings" / "ext.json").exists()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 1
        captured = capsys.readouterr()
        assert "rerun build --replace before closing out" in captured.err
        assert "Phase 5 [done]" not in captured.out
        assert path.read_bytes() == before and _plan(clone) == plan

    def test_ids_continue_per_severity(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                       pr_repo: Tuple[Path, str], tmp_path: Path) -> None:
        clone, head = pr_repo
        runtime = [_finding("src/pkg/a.py"), _finding("src/pkg/a.py", "20", severity="important")]
        path = _built(script, monkeypatch, clone, head, runtime)
        found = [_finding("docs/a.md", line, severity=s, name=f"{s} one")
                 for s, line in (("minor", "1"), ("important", "20"), ("critical", "40"))]
        assert _fold(script, clone, "ci", "tests", "--findings", str(_findings_file(tmp_path, found))) == 0
        doc = _review_doc(path)
        assert {t: [i["id"] for i in doc["issues"][t]] for t in rmg.TIERS} == {
            "critical": ["C1"], "important": ["I1", "I2"], "minor": ["M1", "M2"]}
        assert doc["issues"]["important"][1]["name"] == "important one"
        assert doc["verdict"] == "NOT READY TO MERGE - critical: C1"

    def test_refold_after_build_refused(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                        pr_repo: Tuple[Path, str], tmp_path: Path,
                                        capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        found = _findings_file(tmp_path, [_finding("docs/a.md", "3", name="Stale")])
        assert _fold(script, clone, "ext", "external", "--findings", str(found)) == 0
        before = path.read_bytes()
        capsys.readouterr()
        assert _fold(script, clone, "ext", "external", "--findings", str(found)) == 1
        err = capsys.readouterr().err
        assert "ext" in err and "M2" in err and path.read_bytes() == before

    def test_merge_candidates_noted_not_merged(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                               pr_repo: Tuple[Path, str], tmp_path: Path,
                                               capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        capsys.readouterr()
        found = _findings_file(tmp_path, [_finding("src/pkg/a.py", "40")])
        assert _fold(script, clone, "dev", "developer", "--findings", str(found)) == 0
        assert "note: merge candidates (not merged; amend does not run after build): M1 + M2" in \
            capsys.readouterr().out
        assert [i["id"] for i in _review_doc(path)["issues"]["minor"]] == ["M1", "M2"]


class TestMergeWithFolded:
    def test_merge_and_build_credit_folded_sources(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                   pr_repo: Tuple[Path, str], tmp_path: Path) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [_finding("src/pkg/a.py")])
        path = _findings_file(tmp_path, [_finding("docs/a.md", name="Folded docs finding")])
        assert _fold(script, clone, "ci_tests", "tests", "--findings", str(path)) == 0
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 0
        draft = json.loads((rm.run_dir(_PR, clone) / "draft.json").read_text(encoding="utf-8"))
        assert draft["reviewers"][-1] == "ci_tests (tests)" and "runtime (opus)" in draft["reviewers"]
        assert [i["reviewer"] for i in draft["issues"] if i["name"] == "Folded docs finding"] == ["ci_tests"]
        _phase4(monkeypatch, script)
        assert _run(script, clone, "build", "--pr", str(_PR)) == 0
        doc = json.loads((clone / "docs" / "PR_REVIEWS" / _REVIEW_NAME).read_text(encoding="utf-8"))
        assert doc["reviewers"][-1] == "ci_tests (tests)"
        assert doc["scoped_review_files"][-1].endswith("/findings/ci_tests.json")

    def test_merge_refuses_unregistered_findings_file(self, script: ModuleType,
                                                      monkeypatch: pytest.MonkeyPatch,
                                                      pr_repo: Tuple[Path, str],
                                                      capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        _record_all(clone, [])
        rm.record(_PR, "stray_notes", [_finding("docs/a.md")], [], repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 1
        assert "stray_notes" in capsys.readouterr().err
        assert not (rm.run_dir(_PR, clone) / "draft.json").exists()


class TestResolvedOutsideWaves:
    def test_resolved_needs_a_changed_file(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                           pr_repo: Tuple[Path, str], capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        path = _built(script, monkeypatch, clone, head)
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR), "--resolved", "M1=hand fix") == 1
        assert "M1: none of its files changed" in capsys.readouterr().err
        assert _run(script, clone, "closeout", "--pr", str(_PR), "--resolved", "M9=x") == 1
        assert "M9" in capsys.readouterr().err
        _write(clone, "src/pkg/a.py", "def f0():\n    return 0\n")
        assert _run(script, clone, "closeout", "--pr", str(_PR), "--resolved", "M1=hand fix") == 0
        doc = json.loads(path.read_text(encoding="utf-8"))
        short = _git(clone, "rev-parse", "--short", "HEAD")
        assert doc["post_review_resolutions"][-1]["evidence"] == (
            f"{short} (working-tree snapshot; developer commits) - hand fix (outside fixer waves)")

    def test_blocked_closeout_hints_resolved(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                             pr_repo: Tuple[Path, str],
                                             capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head)
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        _write(clone, "docs/a.md", "# A\n\nedited\n")
        _write(clone, "src/pkg/a.py", "def f0():\n    return 0\n")
        rm.record_fixes(_PR, "w1_fix_1", [{"id": "M1", "what": "w", "files": ["docs/a.md"]}], repo=clone)
        capsys.readouterr()
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 1
        out = capsys.readouterr().out
        assert "Phase 5 [blocked]" in out
        assert 'hint: M1: src/pkg/a.py changed since build' in out and '--resolved M1="what changed"' in out


class TestPhase:
    def test_phase_walk(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch, pr_repo: Tuple[Path, str],
                        tmp_path: Path) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        assert _plan(clone)["phase"] == "review"
        _record_all(clone, [_finding("src/pkg/a.py")])
        assert _fold(script, clone, "dev_notes", "developer", "--findings",
                     str(_findings_file(tmp_path, [_finding("docs/a.md")]))) == 0
        assert _plan(clone)["phase"] == "review"
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 0
        assert _plan(clone)["phase"] == "consolidate"
        _plan_path = rm.run_dir(_PR, clone) / "plan.json"
        _plan_path.write_text(json.dumps({**_plan(clone), "phase": "review"}), encoding="utf-8")
        assert _run(script, clone, "amend", "--pr", str(_PR), "--regrade", "M1=important") == 0
        assert _plan(clone)["phase"] == "consolidate"
        _phase4(monkeypatch, script)
        assert _run(script, clone, "build", "--pr", str(_PR)) == 0
        assert _plan(clone)["phase"] == "consolidate"
        assert _run(script, clone, "bubble", "--pr", str(_PR), "I1", "--classification", "out_of_scope",
                    "--reason", "r") == 0
        assert _plan(clone)["phase"] == "fix-plan"
        assert _run(script, clone, "waves", "--pr", str(_PR)) == 0
        assert _plan(clone)["phase"] == "fix"
        _plan_path.write_text(json.dumps({**_plan(clone), "phase": "x"}), encoding="utf-8")
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 1
        assert _plan(clone)["phase"] == "fix"
        rm.record_fixes(_PR, "w1_fix_1", [{"id": "M2", "what": "w", "files": ["src/pkg/a.py"]}], repo=clone)
        _plan_path.write_text(json.dumps({**_plan(clone), "phase": "x"}), encoding="utf-8")
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 1
        assert _plan(clone)["phase"] == "fix"
        _write(clone, "src/pkg/a.py", "def f0():\n    return 0\n")
        assert _run(script, clone, "closeout", "--pr", str(_PR)) == 0
        assert _plan(clone)["phase"] == "done"

    def test_failed_subcommand_leaves_phase(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                            pr_repo: Tuple[Path, str]) -> None:
        clone, head = pr_repo
        _capture(script, monkeypatch, clone, head)
        assert _run(script, clone, "merge", "--pr", str(_PR)) == 1
        assert _plan(clone)["phase"] == "review"


class TestArgumentErrors:
    def test_missing_required_arguments_report_problem(self, script: ModuleType, tmp_path: Path,
                                                       capsys: pytest.CaptureFixture) -> None:
        assert script.main(["--repo", str(tmp_path), "fold", "--pr", "1"]) == 1
        err = capsys.readouterr().err
        assert "problem:" in err and "--source" in err and "--kind" in err
        assert "usage:" not in err

    def test_missing_subcommand_reports_problem(self, script: ModuleType, tmp_path: Path,
                                                capsys: pytest.CaptureFixture) -> None:
        assert script.main(["--repo", str(tmp_path)]) == 1
        err = capsys.readouterr().err
        assert "problem:" in err and "usage:" not in err

    def test_invalid_choice_reports_problem(self, script: ModuleType, tmp_path: Path,
                                            capsys: pytest.CaptureFixture) -> None:
        assert script.main(["--repo", str(tmp_path), "bubble", "--pr", "1", "I1",
                            "--classification", "not_a_class", "--reason", "r"]) == 1
        err = capsys.readouterr().err
        assert "problem:" in err and "usage:" not in err


class TestConfigCommand:
    """``config`` prints the merged project configuration, so prompts never carry an inline ``-c`` path."""

    def test_prints_the_merged_configuration_as_json(self, script: ModuleType, make_project,
                                                     capsys: pytest.CaptureFixture) -> None:
        root = make_project(config={"state_dir": _STATE, "artifacts": {"reviews": "out/reviews"}})
        assert _run(script, root, "config") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["state_dir"] == _STATE and data["artifacts"]["reviews"] == "out/reviews"
        assert data["skills_dir"] == ".claude/skills/" and Path(data["project_root"]) == root.resolve()

    def test_get_prints_one_line_per_key_and_empty_for_unset(self, script: ModuleType, make_project,
                                                             capsys: pytest.CaptureFixture) -> None:
        root = make_project(config={"state_dir": _STATE})
        assert _run(script, root, "config", "--get", "state_dir", "--get", "base_branch",
                    "--get", "artifacts.reviews") == 0
        assert capsys.readouterr().out.splitlines() == [_STATE, "", "docs/PR_REVIEWS"]

    def test_get_exclusions_defaults_to_the_seeded_file(self, script: ModuleType, make_project,
                                                        capsys: pytest.CaptureFixture) -> None:
        root = make_project(config={"state_dir": _STATE})
        assert not (root / ".claude" / "review_exclusions.json").exists()
        assert _run(script, root, "config", "--get", "exclusions") == 0
        assert capsys.readouterr().out.splitlines() == [".claude/review_exclusions.json"]
        assert (root / ".claude" / "review_exclusions.json").is_file()

    def test_get_other_keys_does_not_seed(self, script: ModuleType, make_project,
                                          capsys: pytest.CaptureFixture) -> None:
        root = make_project(config={"state_dir": _STATE})
        assert _run(script, root, "config", "--get", "state_dir") == 0
        assert capsys.readouterr().out.splitlines() == [_STATE]
        assert not (root / ".claude" / "review_exclusions.json").exists()

    def test_get_unknown_key_reports_problem(self, script: ModuleType, make_project,
                                             capsys: pytest.CaptureFixture) -> None:
        root = make_project()
        assert _run(script, root, "config", "--get", "artifacts.nope") == 1
        assert "problem:" in capsys.readouterr().err

    def test_repo_argument_wins_over_the_working_directory(self, script: ModuleType, make_project,
                                                           monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture) -> None:
        wanted = make_project(config={"state_dir": "wanted/state"}, name="wanted")
        other = make_project(config={"state_dir": "other/state"}, name="other")
        monkeypatch.chdir(other)
        assert _run(script, wanted, "config", "--get", "state_dir") == 0
        assert capsys.readouterr().out.strip() == "wanted/state"


class TestBuiltReviewRefusesDraftEdits:
    def test_merge_and_amend_refused_after_build(self, script: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                 pr_repo: Tuple[Path, str],
                                                 capsys: pytest.CaptureFixture) -> None:
        clone, head = pr_repo
        _built(script, monkeypatch, clone, head, [_finding("src/pkg/a.py"), _finding("docs/a.md")])
        draft = rm.run_dir(_PR, clone) / "draft.json"
        before_draft = draft.read_bytes()
        before_phase = _plan(clone)["phase"]
        capsys.readouterr()
        assert _run(script, clone, "merge", "--pr", str(_PR), "--force") == 1
        assert "review is built" in capsys.readouterr().err
        assert _run(script, clone, "amend", "--pr", str(_PR), "--regrade", "M1=critical") == 1
        assert "review is built" in capsys.readouterr().err
        assert draft.read_bytes() == before_draft
        assert _plan(clone)["phase"] == before_phase
