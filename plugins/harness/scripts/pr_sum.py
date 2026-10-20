"""pr-sum driver: capture a PR's facts from local git, print its budgeted diff, then build the summary.

``capture --pr N``
    One ``gh pr view`` read supplies the number, title, base and head names, head SHA and merge commit.
    Everything else is local git: fetch ``pull/N/head`` with ``origin <base>`` (with the merge commit instead
    once merged, so a deleted base branch does not matter), take the merge base of the head with the base tip
    (the merge commit's first parent once merged, ``origin/<base>`` before), and diff merge base..head.
    While the PR branch is checked out, the head is its local HEAD and the diff runs to the working tree
    (staged, unstaged and untracked changes); ``--remote-head`` takes the ``gh`` head instead, and
    ``--committed-only`` stops at the local HEAD. Elsewhere the committed ``gh`` head is used.
    Writes ``<summaries>/<NNNN>_pr.json``: ``{"facts": {...}, "draft": {...}}``. When that file already
    holds a parseable draft, the draft is carried forward: title, summary and sections stay, and
    descriptions stay for paths the PR still lists (new paths get empty slots).
``diff FILE [--path P ...]``
    The PR's diff under the ``commit_diff`` budgets: paths read in full until ``PR_BLOCK_BUDGET`` changed
    lines are spent, and output capped at ``PR_CHAR_BUDGET`` characters (later sections keep only their
    header and ``[omitted: block output budget spent]``). Sections run source, then tests (the project's
    configured test layout), then docs. Machine-generated artifacts are skipped unless named with
    ``--path``; ``--path`` also matches a rename's old path.
``build FILE [--visual]``
    Validate the draft, write ``<summaries>/<NNNN>_<Title>.md`` and print the receipt. ``--visual``
    (pr-sum-viz) requires the visual sections and caps their table cells.

Roots: the project (git top level of ``--repo``, which must lie inside a git checkout, else of the working
directory) holds every input and output; ``<summaries>`` is its ``.claude/harness.json``
``artifacts.summaries`` directory. The plugin
directory this script lives in supplies only code and is never written.

Every failure exits 1 with one ``problem: ...`` line per defect on stderr.

Usage::

    sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" capture --pr N
        [--no-fetch] [--remote-head] [--committed-only] [--out FILE] [--repo DIR]
    sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" diff FILE [--path P ...]
        [--repo DIR]
    sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_sum.py" build FILE [--visual]
        [--repo DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from harness_lib.branch_capture import CaptureError, git  # noqa: E402
from harness_lib.config import ConfigError, activate, active, load_config  # noqa: E402
from harness_lib.pr_capture import PrMeta, budgeted_diff, capture_pr, gh_metadata, read_rank  # noqa: E402
from harness_lib.pr_summary import (  # noqa: E402
    PrDraft,
    PrFacts,
    PrFile,
    draft_from_payload,
    draft_problems,
    facts_from_payload,
    new_draft,
    render_summary,
    skeleton,
    summary_filename,
)
from harness_lib.project import project_root  # noqa: E402

PR_BLOCK_BUDGET = 1200
PR_CHAR_BUDGET = 60_000


def activate_project(repo: Optional[Path]) -> Path:
    """Activate the harness configuration of the project holding ``repo`` (default: cwd); return its root.

    An explicit ``repo`` must sit inside a git checkout: ``project_root``'s ``CLAUDE_PROJECT_DIR`` fallback
    applies only to the working directory, so a mistyped ``--repo`` never redirects to another project.
    """
    root = project_root(Path.cwd()) if repo is None else _explicit_root(repo)
    return activate(load_config(root)).project_root


def _explicit_root(repo: Path) -> Path:
    """Git top level of ``repo`` (a directory or a file in one); raise ``CaptureError`` outside a checkout."""
    start = repo if repo.is_dir() else repo.parent
    done = git(start, "rev-parse", "--show-toplevel") if start.is_dir() else None
    if done is None or done.returncode != 0:
        raise CaptureError([f"--repo {repo}: not inside a git checkout"])
    return Path(done.stdout.strip()).resolve()


def summaries_dir(repo: Path) -> Path:
    """The active configuration's ``artifacts.summaries`` directory; ``repo`` must be the active
    project root."""
    cfg = active()
    if Path(repo).resolve() != cfg.project_root:
        raise CaptureError(
            [f"{repo} is not the active project {cfg.project_root}; activate its config first"]
        )
    return cfg.path(cfg.artifacts.summaries)


def carry_draft(facts: PrFacts, previous: Optional[PrDraft]) -> PrDraft:
    """Draft for fresh ``facts``: ``previous`` prose kept, descriptions only for paths still described."""
    if previous is None:
        return new_draft(facts)
    descriptions = {path: previous.descriptions.get(path, "") for path in facts.described}
    return PrDraft(previous.title, previous.summary, descriptions, previous.sections)


def capture_payload(
        repo: Path, meta: PrMeta, fetch: bool = True, previous: Optional[PrDraft] = None,
        local: bool = True, working_tree: bool = True,
) -> Dict[str, object]:
    """Skeleton for ``meta``: fresh facts and ``previous`` carried forward (an empty draft without one).

    By default the facts describe the checked-out PR branch with its uncommitted changes (``capture_pr``
    falls back to the committed PR head when that branch is not checked out).
    """
    facts = capture_pr(repo, meta, fetch, local=local, working_tree=working_tree)
    return skeleton(facts, carry_draft(facts, previous))


def _facts(payload: Mapping[str, object]) -> PrFacts:
    """Facts of a skeleton; raise ``CaptureError`` when they do not parse or carry wrong types."""
    try:
        facts = facts_from_payload(payload["facts"])
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise CaptureError([f"skeleton facts do not parse ({exc!r}); rerun capture"]) from exc
    if not _int(facts.number) or not all(_int(f.added) and _int(f.deleted) for f in facts.files):
        raise CaptureError(["skeleton facts carry a non-integer number or line count; rerun capture"])
    return facts


def _int(value: object) -> bool:
    """True for an int that is not a bool."""
    return isinstance(value, int) and not isinstance(value, bool)


def _draft_shape_problems(raw: Mapping[str, object]) -> List[str]:
    """Shape defects ``draft_from_payload`` cannot coerce: non-object descriptions or section entries."""
    descriptions, sections = raw.get("descriptions") or {}, raw.get("sections") or ()
    problems = [] if isinstance(descriptions, dict) else [
        f"draft descriptions must be an object of path -> text, not {type(descriptions).__name__}",
    ]
    sections_ok = isinstance(sections, (list, tuple)) and all(isinstance(s, dict) for s in sections)
    return problems + ([] if sections_ok else ["draft sections must be a list of {heading, body} objects"])


def _draft(payload: Mapping[str, object]) -> PrDraft:
    """Draft of a skeleton; raise ``CaptureError`` when it, its descriptions or sections are misshapen."""
    raw = payload.get("draft") or {}
    if not isinstance(raw, dict):
        raise CaptureError([f"skeleton draft must be an object, not {type(raw).__name__}"])
    problems = _draft_shape_problems(raw)
    if problems:
        raise CaptureError(problems)
    return draft_from_payload(raw)


def _chosen(facts: PrFacts, paths: Sequence[str]) -> List[PrFile]:
    """Files to read, source then tests then docs: the named paths (new or old side), else non-artifacts."""
    if paths:
        chosen = [f for f in facts.files if f.path in paths or (f.old_path or "") in paths]
    else:
        chosen = [f for f in facts.files if not f.artifact]
    return sorted(chosen, key=lambda f: read_rank(f.path))


def run_diff(repo: Path, payload: Mapping[str, object], paths: Sequence[str] = ()) -> str:
    """The PR's diff under the read budgets; ``paths`` narrows it, and a path not in the PR is reported."""
    facts = _facts(payload)
    text = budgeted_diff(repo, facts, _chosen(facts, paths), PR_BLOCK_BUDGET, PR_CHAR_BUDGET)
    known = {p for f in facts.files for p in (f.path, f.old_path) if p}
    missing = [f"=== {path} [not in this PR] ===" for path in paths if path not in known]
    return "\n".join(([text] if text else []) + missing)


def receipt(repo: Path, target: Path, facts: PrFacts, draft: PrDraft) -> str:
    """One-line chat receipt."""
    try:
        shown = target.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        shown = target.as_posix()
    title = draft.title.strip()
    return f"Saved: {shown} — Merge PR #{facts.number}: {title} ({facts.head} -> {facts.base})"


def run_build(repo: Path, payload: Mapping[str, object], visual: bool = False) -> Tuple[Path, str]:
    """Validate the draft, write the summary markdown, and return its path and the receipt."""
    facts, draft = _facts(payload), _draft(payload)
    problems = draft_problems(facts, draft, visual)
    if problems:
        raise CaptureError(problems)
    target = summaries_dir(repo) / summary_filename(facts.number, draft.title)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_summary(facts, draft), encoding="utf-8")
    return target, receipt(repo, target, facts, draft)


def _repo_parent() -> argparse.ArgumentParser:
    """Shared ``--repo`` option for every subcommand."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--repo", type=Path, help="Any path inside the project (default: the working directory)."
    )
    return parent


def _parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="pr_sum.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    common = [_repo_parent()]
    cap = sub.add_parser("capture", parents=common, help="Write the PR skeleton JSON (facts + draft).")
    cap.add_argument("--pr", type=int, required=True, help="PR number.")
    cap.add_argument("--no-fetch", action="store_true", help="Skip fetching the base side and pull/N/head.")
    cap.add_argument(
        "--remote-head", action="store_true",
        help="Summarize the PR head gh reports, not the checked-out PR branch (implies --committed-only).",
    )
    cap.add_argument(
        "--committed-only", action="store_true",
        help="Leave out staged, unstaged and untracked changes of the checked-out PR branch.",
    )
    cap.add_argument("--out", type=Path, help="Skeleton path (default <summaries>/<NNNN>_pr.json).")
    diff = sub.add_parser("diff", parents=common, help="Print the PR diff under the read budgets.")
    diff.add_argument("skeleton", type=Path, help="Skeleton JSON (UTF-8).")
    diff.add_argument("--path", action="append", default=[], help="Limit to this path (repeatable).")
    build = sub.add_parser("build", parents=common, help="Validate the draft and write the summary markdown.")
    build.add_argument("skeleton", type=Path, help="Filled skeleton JSON (UTF-8).")
    build.add_argument("--visual", action="store_true", help="pr-sum-viz: require the visual sections.")
    return parser


def _read(path: Path) -> Dict[str, object]:
    """Load a skeleton JSON object (a BOM is tolerated); raise ``CaptureError`` when it cannot be read."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CaptureError([f"cannot read skeleton {path} ({exc}); rerun capture"]) from exc
    if not isinstance(payload, dict):
        raise CaptureError([f"skeleton {path} must hold a JSON object; rerun capture"])
    return payload


def previous_draft(path: Path) -> Optional[PrDraft]:
    """Draft of an existing skeleton at ``path``; None when the file is missing or does not parse."""
    if not path.is_file():
        return None
    try:
        return _draft(_read(path))
    except CaptureError:
        return None


def _cmd_capture(args: argparse.Namespace, repo: Path) -> int:
    """Run ``capture`` and write the skeleton, carrying an existing draft forward."""
    out = args.out or summaries_dir(repo) / f"{args.pr:04d}_pr.json"
    previous = previous_draft(out)
    payload = capture_payload(
        repo, gh_metadata(repo, args.pr), not args.no_fetch, previous,
        local=not args.remote_head, working_tree=not args.committed_only,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}" + (" (existing draft carried forward)" if previous else ""))
    return 0


def _cmd_diff(args: argparse.Namespace, repo: Path) -> int:
    """Run ``diff`` and print the budgeted PR diff."""
    print(run_diff(repo, _read(args.skeleton), args.path))
    return 0


def _cmd_build(args: argparse.Namespace, repo: Path) -> int:
    """Run ``build`` and print the receipt."""
    _, text = run_build(repo, _read(args.skeleton), args.visual)
    print(text)
    return 0


def _utf8_streams() -> None:
    """Reconfigure stdout and stderr to UTF-8 where the stream supports it."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point; return 0 on success, 1 on a config, capture, gh, skeleton or validation failure."""
    _utf8_streams()
    args = _parser().parse_args(argv)
    commands = {"capture": _cmd_capture, "diff": _cmd_diff, "build": _cmd_build}
    try:
        return commands[args.command](args, activate_project(args.repo))
    except ConfigError as exc:
        sys.stderr.write(f"problem: {exc}\n")
        return 1
    except CaptureError as exc:
        sys.stderr.write("\n".join(f"problem: {line}" for line in exc.problems) + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
