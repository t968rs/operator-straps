#!/usr/bin/env python
"""pr-review Phase 4 — Branch Safety Verification (mechanical executor).

Single-script body for all five Phase 4 checks. Replaces the prose-only Phase 4
description in SKILL.md with a deterministic execution path: invoke this script,
capture stdout into the JSON's verification_log.pre_fix_time field.

Usage (Bash tool, from the project checkout):
    sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" \
        "${CLAUDE_PLUGIN_ROOT}/skills/pr-review/commands/phase4_branch_safety.py" \
        [--second-run] [--exclusions-fixture <path>] <PR_NUMBER>

The project is the git top level of the working directory (``harness_lib.project.project_root``, the same
resolution the hooks apply to their payload ``cwd``); its ``.claude/harness.json`` is activated once.

Flags:
    --second-run: declares this is the Phase 5 entry invocation (not the Phase 3
                  Step 7 first-run). On all-checks-pass, writes a Phase 5 sentinel
                  file at <project>/<state_dir>/pr-review/.phase5_pending_<PR>. The
                  harness Stop hook (check_phase5_sentinel.py) blocks only the
                  arming session's end while the sentinel is hot (line 3 holds the
                  owner id; a sentinel without it blocks every session). The
                  sentinel is cleared mechanically by Layer 3 of the harness
                  validate_pr_json_schema.py hook when the matching PR_REVIEW JSON
                  shows Phase 5 closeout. WITHOUT this flag, no sentinel is
                  written; that path is for Phase 3's Step 7 first-run.
    --exclusions-fixture <path>: exclusions JSON for the clean_tree_check (default:
                  the project's configured ``exclusions`` file; none configured
                  means every working-tree change counts).

Argv contract (strict):
    Exactly one positional argument (the PR number). Extra positionals or
    unknown -- flags raise ValueError -> exit 2. Silent drops are unsafe in
    a gatekeeper.

Output:
    On PASS: stdout = JSON object matching the pre_fix_time schema sub-block
             (current_branch_check / branch_match_check / clean_tree_check /
             sha_ancestry_check / base_branch_recorded). Exit 0. With
             --second-run, sentinel file written; stderr confirms the path.
    On FAIL: stdout = JSON object with the same keys, but the failed check's
             result field starts with "STOP" and a diagnostic. Exit 1.
             Stderr carries a one-line failure summary. Sentinel NOT written
             even with --second-run when any check fails.

The JSON output is the literal value the caller pastes into
verification_log.pre_fix_time -- no field renaming or post-processing required.

Why a script: prose-only Phase 4 enforcement is fragile; agents can rationalize
single-check skips. A script either runs to completion (all five captures) or
exits non-zero. The protocol becomes a single observable tool call.
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

_LIB = Path(__file__).resolve().parents[3] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig

_NO_EXCLUSIONS = "(none configured)"


def _run(cmd: list, cwd: Optional[str] = None) -> Tuple[int, str, str]:
    """Run a subprocess; return (exit_code, stdout, stderr) with stripped strings.

    UTF-8 is forced because Windows defaults subprocess `text=True` to CP1252,
    which crashes on non-CP1252 bytes (em-dash, smart quotes) common in
    `gh pr view` output and commit messages. errors='replace' guards against
    truly malformed bytes without raising during decode.
    """
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _gh_pr_metadata(pr_number: str) -> Dict[str, Any]:
    """Pull headRefName / baseRefName / first+last SHAs from gh pr view."""
    cmd = [
        "gh", "pr", "view", pr_number,
        "--json", "headRefName,baseRefName,state,commits",
    ]
    code, out, err = _run(cmd)
    if code != 0:
        raise RuntimeError(f"gh pr view {pr_number} failed: {err}")
    data = json.loads(out)
    commits = data.get("commits") or []
    return {
        "headRefName": data["headRefName"],
        "baseRefName": data["baseRefName"],
        "state": data["state"],
        "first_sha": commits[0]["oid"] if commits else "",
        "last_sha": commits[-1]["oid"] if commits else "",
    }


def _check_current_branch() -> Dict[str, Any]:
    code, branch, err = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return {
        "command": "git rev-parse --abbrev-ref HEAD",
        "stdout": branch,
        "result": "OK" if code == 0 and branch else f"STOP: {err or 'empty branch name'}",
    }


def _check_branch_match(current_branch: str, head_ref_name: str) -> Dict[str, Any]:
    match = current_branch == head_ref_name
    return {
        "assertion": "CURRENT_BRANCH == headRefName",
        "current_branch": current_branch,
        "head_ref_name": head_ref_name,
        "result": "OK (match)" if match else (
            f"STOP: branch mismatch -- on '{current_branch}', PR head is '{head_ref_name}'. "
            f"Recovery: git checkout {head_ref_name}"
        ),
    }


def _porcelain(repo_root: Path) -> str:
    """Raw ``git status --porcelain`` of ``repo_root``, trailing newline dropped.

    Not ``_run``: porcelain output's first column is a single space for worktree-only statuses
    (' M file'), and stripping the whole blob would corrupt the first line's columns.
    """
    proc = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain"], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return proc.stdout.rstrip("\n")


def _exclusion_patterns(repo_root: Path, exclusions_fixture: Optional[str]) -> List[str]:
    """fnmatch patterns of ``exclusions_fixture`` (relative to ``repo_root`` unless absolute); none when
    no file is named. A named file that is missing or malformed raises ``OSError`` / ``ValueError``."""
    if not exclusions_fixture:
        return []
    from harness_lib.git_status_filter_excluded import load_exclusions
    path = Path(exclusions_fixture)
    return list(load_exclusions(path if path.is_absolute() else repo_root / path))


def _filtered(raw_status: str, patterns: List[str]) -> str:
    """Porcelain lines whose path (column 3 on) matches no pattern."""
    lines = raw_status.splitlines() if raw_status else []
    return "\n".join(line for line in lines if not any(fnmatch.fnmatch(line[3:], p) for p in patterns))


def _check_clean_tree(repo_root: Path, exclusions_fixture: Optional[str]) -> Dict[str, Any]:
    """Phase 4 Check 3: the working tree is clean once the exclusions are filtered out."""
    raw_status = _porcelain(repo_root)
    check = {"command": "git status --porcelain", "stdout": raw_status, "filtered_stdout": "",
             "exclusions_fixture": exclusions_fixture or _NO_EXCLUSIONS}
    try:
        patterns = _exclusion_patterns(repo_root, exclusions_fixture)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {**check, "result": f"STOP: exclusions file unreadable: {exc}"}
    filtered = _filtered(raw_status, patterns)
    result = ("OK (empty after exclusions)" if not filtered
              else f"STOP: working tree has non-exempt changes:\n{filtered}")
    return {**check, "filtered_stdout": filtered, "result": result}


def _check_sha_ancestry(base_sha: str, head_sha: str) -> Dict[str, Any]:
    base_code, _, _ = _run(["git", "merge-base", "--is-ancestor", base_sha, "HEAD"])
    head_code, _, _ = _run(["git", "merge-base", "--is-ancestor", head_sha, "HEAD"])
    if base_code == 0 and head_code == 0:
        result = "OK (both ancestors)"
    else:
        missing = []
        if base_code != 0:
            missing.append(f"BASE_SHA {base_sha[:8]}")
        if head_code != 0:
            missing.append(f"HEAD_SHA {head_sha[:8]}")
        result = f"STOP: not ancestors of HEAD -- {', '.join(missing)}"
    return {
        "base_sha": base_sha,
        "head_sha": head_sha,
        "base_ancestor_command": f"git merge-base --is-ancestor {base_sha} HEAD",
        "base_ancestor_exit": base_code,
        "head_ancestor_command": f"git merge-base --is-ancestor {head_sha} HEAD",
        "head_ancestor_exit": head_code,
        "result": result,
    }


def _check_base_branch_recorded(base_ref_name: str, configured_base: str) -> Dict[str, Any]:
    """Phase 4 Check 5: record the PR's base branch, noting whether it is the configured base branch."""
    same = base_ref_name == configured_base
    note = "configured base" if same else f"not the configured base {configured_base}"
    return {
        "source": "gh pr view <PR> --json baseRefName --jq .baseRefName",
        "value": base_ref_name,
        "result": f"OK (recorded; {note})",
    }


def _project() -> Tuple[Path, HarnessConfig]:
    """The working directory's project root and its activated harness configuration."""
    from harness_lib.config import activate, load_config
    from harness_lib.project import project_root
    root = project_root()
    return root, activate(load_config(root))


def _exclusions_for(flag_value: Optional[str], cfg: HarnessConfig) -> Optional[str]:
    """The exclusions file the clean-tree check uses: the flag's value, else the configured one."""
    return flag_value or cfg.exclusions


def _write_phase5_sentinel(pr_number: str, repo_root: Path) -> None:
    """Write the Phase 5 sentinel for pr_number at <main checkout>/<state_dir>/pr-review/.

    ``repo_root`` is the project ``_project`` resolves (the git top level of the working directory). The
    sentinel lands in that repository's main checkout (``sentinel_dir_under``), where the Stop hook and the
    schema hook look whichever worktree their payload ``cwd`` names; ``state_dir`` comes from the active
    harness configuration.

    Content: line 1 is the PR number (audit trail of which invocation armed it), line 2 is the unix
    write-time. The hook reads line 2 to evaluate hot-vs-stale, immune to incidental mtime touches. Line 3
    is the arming session's id from CLAUDE_CODE_SESSION_ID, which Claude Code exports to every Bash call
    (subagents included); the hook blocks only that session. Without the env var line 3 is omitted, and
    the hook treats the unowned sentinel as blocking every session. A session started by /clear, a forked
    resume, or a new terminal is a different owner and is not blocked; re-running --second-run <PR> from
    the continuing session re-arms the sentinel under its id.
    """
    from harness_lib.config import active
    from harness_lib.validation.artifact_names import sentinel_dir_under
    sentinel_dir = sentinel_dir_under(Path(repo_root), active().state_dir)
    sentinel_dir.mkdir(parents=True, exist_ok=True)
    sentinel = sentinel_dir / f".phase5_pending_{pr_number}"
    lines = [pr_number, str(int(time.time()))]
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if session_id:
        lines.append(session_id)
    sentinel.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


_USAGE = "usage: phase4_branch_safety.py [--second-run] [--exclusions-fixture <path>] <PR_NUMBER>\n"
_KNOWN_FLAGS = frozenset({"--second-run", "--exclusions-fixture"})


def _parse_argv(argv: list) -> Tuple[bool, Optional[str], Optional[str]]:
    """Parse phase4 argv: detect flags, extract PR number, resolve exclusions path.

    Strict contract — this script gates branch safety, so silent argv drops
    are unsafe (a stray positional could send Phase 4 against the wrong PR).
    Raises ValueError on:
      * any -- flag not in _KNOWN_FLAGS
      * more than one non-flag positional argument
    Returns (second_run_flag, pr_number_or_None, exclusions_fixture_or_None) when the shape is valid; a
    None fixture means the project's configured exclusions file governs.
    """
    rest = argv[1:]
    second_run = "--second-run" in rest
    exclusions_fixture: Optional[str] = None
    positional = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--second-run":
            i += 1
            continue
        if arg == "--exclusions-fixture":
            if i + 1 >= len(rest):
                raise ValueError("--exclusions-fixture requires an argument")
            exclusions_fixture = rest[i + 1]
            i += 2
            continue
        if arg.startswith("--"):
            raise ValueError(f"unknown flag: {arg}")
        positional.append(arg)
        i += 1
    if len(positional) > 1:
        raise ValueError(
            f"too many positional arguments: {positional!r}; expected exactly one PR number"
        )
    pr_number = positional[0] if positional else None
    return second_run, pr_number, exclusions_fixture


def _pre_fix_checks(meta: Dict[str, Any], repo_root: Path, cfg: HarnessConfig,
                    exclusions_fixture: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """The five Phase 4 check blocks, keyed as ``verification_log.pre_fix_time`` records them."""
    current_branch_check = _check_current_branch()
    return {
        "current_branch_check": current_branch_check,
        "branch_match_check": _check_branch_match(current_branch_check["stdout"], meta["headRefName"]),
        "clean_tree_check": _check_clean_tree(repo_root, _exclusions_for(exclusions_fixture, cfg)),
        "sha_ancestry_check": _check_sha_ancestry(meta["first_sha"], meta["last_sha"]),
        "base_branch_recorded": _check_base_branch_recorded(meta["baseRefName"], cfg.resolve_base_branch()),
    }


def main(argv: list) -> int:
    try:
        second_run, pr_number, exclusions_fixture = _parse_argv(argv)
    except ValueError as exc:
        sys.stderr.write(f"argv error: {exc}\n")
        sys.stderr.write(_USAGE)
        return 2
    if pr_number is None:
        sys.stderr.write(_USAGE)
        return 2

    try:
        meta = _gh_pr_metadata(pr_number)
    except (RuntimeError, json.JSONDecodeError, KeyError, IndexError) as exc:
        sys.stderr.write(f"FAIL: cannot read PR metadata: {exc}\n")
        return 1

    from harness_lib.config import ConfigError
    try:
        repo_root, cfg = _project()
    except (ConfigError, OSError) as exc:
        sys.stderr.write(f"FAIL: harness config: {exc}\n")
        return 1

    pre_fix_time = _pre_fix_checks(meta, repo_root, cfg, exclusions_fixture)
    json.dump(pre_fix_time, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")

    failed = [
        name for name, block in pre_fix_time.items()
        if str(block.get("result", "")).startswith("STOP")
    ]
    if failed:
        sys.stderr.write(f"FAIL: Phase 4 checks failed: {', '.join(failed)}\n")
        return 1

    if second_run:
        _write_phase5_sentinel(pr_number, repo_root)
        sys.stderr.write(f"Sentinel written: .phase5_pending_{pr_number}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
