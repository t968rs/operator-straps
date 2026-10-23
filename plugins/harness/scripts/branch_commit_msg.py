"""branch-commit-msg driver: capture a branch's changes into a commit skeleton, then build the TXT.

Two subcommands bracket the one judgment step (drafting commit messages):

``capture``
    Resolve the merge base against the project's base branch (fetching ``origin <base>`` first),
    capture every path that differs from it (``git diff --name-status -M -z`` plus untracked files),
    bucket, pair, split and order them, and carry forward groupings and messages from an existing
    ``<branch>.txt`` in the project's ``commit_messages`` directory (default ``docs/_commit_messages``).
    ``--fresh`` skips that carry-forward (and never parses the TXT), so a stale or over-split grouping
    is replanned from the rules; messages come back empty. ``--base REF`` replaces the resolved merge base
    with REF (stored as a SHA); the skeleton gets ``"txt_suffix": "_<sha7>"`` (with or without
    ``--fresh``) and ``--save`` and ``build`` write ``<branch>_<sha7>.json`` / ``.txt`` beside the branch
    TXT, which a based capture never overwrites. Carry-forward reads that ``<branch>_<sha7>.txt`` when it
    exists, else the branch TXT.
    Prints (or writes with ``--out``) a JSON skeleton::

        {"branch": ..., "merge_base": ..., "split": ..., "captured": [...],
         "commits": {"1": [["path", ...], "message or empty"], ...}}

    ``--pending`` (the ``c-msg`` skill) instead captures the change pending against HEAD (staged,
    unstaged, untracked) as one commit with ``merge_base`` set to HEAD and ``"pending": true``. The
    message carries forward from ``<branch>_pending.txt`` only while HEAD is unchanged; the branch
    ledger is never read.

``build``
    Read a filled skeleton (same shape; commits renumbered in key order), construct a
    ``BranchCommitDocument`` from the ``Dict[int, Tuple[List[str], str]]`` commit dictionary (buckets
    derive from paths), validate it (null fields, one path per commit, merge-base coverage, subject
    rules, vendor names, filler, block-separator lines), render the TXT and re-parse it in memory to
    confirm the round trip, then write ``<branch>.txt`` into the ``commit_messages`` directory
    (``<branch>_<sha7>.txt`` for a ``--base`` skeleton, ``<branch>_pending.txt`` for a
    pending skeleton) and print the chat receipt. A ``txt_suffix`` other than ``_<merge_base[:7]>`` is
    rejected. Exit 1 with one
    problem per line when validation fails; the existing TXT is left untouched then. A pending skeleton
    builds only while HEAD still equals its ``merge_base``.

``diff``
    Print the diff of one skeleton block under line budgets (``harness_lib.commit_diff``): paths within
    budget in full, larger ones as a summary (key tallies for JSON, a truncated head otherwise). The
    ``captured`` entries carry ``added``/``deleted`` counts so sizes are known before reading.

The project is the git top level of ``--repo`` (default: the working directory); its
``.claude/harness.json`` is activated once at startup, and an invalid one exits 1 with a ``problem:``
line. ``--repo`` goes before or after the subcommand. Usage::

    branch_commit_msg.py [--repo DIR] capture [REF | --base REF] [--no-fetch] [--fresh] [--out FILE | --save]
    branch_commit_msg.py [--repo DIR] capture --pending [--out FILE | --save]
    branch_commit_msg.py [--repo DIR] diff FILE --block N
    branch_commit_msg.py [--repo DIR] build FILE [--out TXT]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib.branch_capture import (
    CaptureError,
    capture_paths,
    capture_stats,
    current_branch,
    diff_section,
    git,
    git_out,
    resolve_merge_base,
    untracked_paths,
)
from harness_lib.branch_commits import BranchCommitDocument
from harness_lib.commit_diff import DiffStat, cap_sections, plan_reads
from harness_lib.commit_grouping import (
    CapturedPath,
    captured_set,
    coverage_problems,
    expand_entry,
    parse_registry_targets,
    plan_commits,
)
from harness_lib.commit_txt import (
    document_to_txt,
    entry_from_message,
    message_problems,
    parse_commit_txt,
    read_commit_txt,
)
from harness_lib.config import ConfigError, active, activate, load_config
from harness_lib.project import project_root

CommitDict = Dict[int, Tuple[List[str], str]]

_REF_PATTERN = re.compile(r"[A-Za-z0-9/._~^-]+")

PENDING_SUFFIX = "_pending"
PENDING_SPLIT = "single commit: pending change against HEAD"

# Kept as an alias: the docstrings and tests of this script name BuildError.
BuildError = CaptureError


def output_dir() -> str:
    """Project-relative POSIX directory the TXT and skeleton files live in (``artifacts.commit_messages``)."""
    return active().artifacts.commit_messages.strip("/")


def capture_branch(repo: Path, merge_base: str) -> List[CapturedPath]:
    """Capture every path differing from ``merge_base`` (committed, staged, unstaged, untracked).

    Paths under the ``commit_messages`` directory are the tooling's own output and are left out.
    """
    output_prefix = output_dir() + "/"
    return [c for c in capture_paths(repo, merge_base) if not c.path.startswith(output_prefix)]


def txt_path(repo: Path, branch: str, suffix: str = "") -> Path:
    """Default TXT location for ``branch``; ``suffix`` names a sibling file (a ``--base`` capture)."""
    return repo / output_dir() / f"{branch}{suffix}.txt"


def resolve_base_ref(repo: Path, ref: str) -> str:
    """Commit SHA of ``ref`` (a SHA, ``HEAD``, a branch); ``BuildError`` when it names no commit."""
    probe = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if probe.returncode != 0:
        raise BuildError([f"--base {ref!r} does not name a commit"])
    return probe.stdout.strip()


def base_suffix(merge_base: str, base: Optional[str]) -> str:
    """Filename suffix for a capture: ``_<sha7>`` for any ``--base`` capture, else empty.

    A based capture covers a slice of the branch, so it never replaces the branch's own TXT;
    ``--fresh`` only skips carry-forward and leaves the suffix alone.
    """
    return f"_{merge_base[:7]}" if base else ""


def _existing_document(path: Path) -> Optional[BranchCommitDocument]:
    """Parse an existing TXT leniently (shared paths allowed); None when absent.

    An unparseable TXT raises ``BuildError`` so its groupings and messages are repaired, not silently dropped.
    """
    if not path.exists():
        return None
    try:
        return read_commit_txt(path, one_path_per_commit=False)
    except ValueError as exc:
        raise BuildError([f"{path.name} exists but does not parse; fix or remove it: {exc}"]) from exc


def _registry_targets(repo: Path) -> Dict[str, List[str]]:
    """Working-tree registry mapping of test file to ``test_target_paths``.

    Empty when the project configures no ``tests.registry`` or the file is absent.
    """
    registry = active().tests.registry
    path = repo / registry if registry else None
    return parse_registry_targets(path.read_text(encoding="utf-8")) if path and path.exists() else {}


def skeleton_payload(
        document: BranchCommitDocument, split: str, captures: Sequence[CapturedPath],
        stats: Optional[Mapping[str, DiffStat]] = None,
) -> Dict[str, object]:
    """Serialize ``document`` to the JSON skeleton; the inverse of ``_commit_dict`` for its commits.

    ``stats`` supplies each captured path's changed-line counts (zero when absent).
    """
    known = stats or {}
    payload: Dict[str, object] = {
        "branch": document.branch,
        "merge_base": document.merge_base,
        "split": split,
        "captured": [_captured_entry(c, known.get(c.path, DiffStat(c.path, 0, 0))) for c in captures],
        "commits": {
            str(key): [list(entry.files), entry.message] for key, entry in sorted(document.commits.items())
        },
    }
    if document.pending:
        payload["pending"] = True
    return payload


def run_capture(
        repo: Path, base: Optional[str] = None, fetch: bool = True, fresh: bool = False,
) -> Dict[str, object]:
    """Build the JSON skeleton payload for the checked-out branch; ``fresh`` ignores the existing TXT.

    Without ``base`` the merge base resolves against the project's base branch (``resolve_base_branch``).
    With ``base`` (any ref, stored as its SHA), with or without ``fresh``, the payload carries
    ``txt_suffix`` so ``--save`` and ``build`` write beside the branch TXT instead of over it.
    Carry-forward reads that sibling ``<branch>_<sha7>.txt`` when it exists, else the branch TXT.
    """
    branch = current_branch(repo)
    if base:
        merge_base = resolve_base_ref(repo, base)
    else:
        merge_base = resolve_merge_base(repo, active().resolve_base_branch(), fetch)
    captures = capture_branch(repo, merge_base)
    suffix = base_suffix(merge_base, base)
    existing = None if fresh else _existing_document(carry_forward_path(repo, branch, suffix))
    groups, split = plan_commits(captures, existing, _registry_targets(repo))
    commits = {n: (list(group.paths), group.message) for n, group in enumerate(groups, 1)}
    document = document_from_commit_dict(commits, branch, merge_base)
    payload = skeleton_payload(document, split, captures, stats=capture_stats(repo, merge_base, captures))
    return {**payload, "txt_suffix": suffix} if suffix else payload


def carry_forward_path(repo: Path, branch: str, suffix: str) -> Path:
    """TXT read for carry-forward: the ``suffix`` sibling when it exists, else the branch TXT."""
    sibling = txt_path(repo, branch, suffix)
    return sibling if suffix and sibling.exists() else txt_path(repo, branch)


def checked_suffix(payload: Mapping[str, object]) -> str:
    """The skeleton's ``txt_suffix``: empty or ``_<merge_base[:7]>``; anything else raises ``BuildError``."""
    suffix = str(payload.get("txt_suffix") or "")
    merge_base = str(payload.get("merge_base") or "")
    if suffix and not (re.fullmatch(r"_[0-9a-f]{7}", suffix) and suffix == f"_{merge_base[:7]}"):
        raise BuildError([f"txt_suffix {suffix!r} does not match merge_base; rerun capture"])
    return suffix


def pending_txt_path(repo: Path, branch: str) -> Path:
    """``c-msg`` TXT location for ``branch``: the pending change, kept apart from the branch ledger."""
    return repo / output_dir() / f"{branch}{PENDING_SUFFIX}.txt"


def _pending_message(path: Path, head: str, paths: Sequence[str]) -> str:
    """Message of an existing pending TXT drafted against ``head`` over overlapping ``paths``.

    Empty once HEAD has moved or when none of the TXT's files is among ``paths``.
    """
    existing = _existing_document(path)
    if existing is None or existing.merge_base != head or not existing.commits:
        return ""
    entry = existing.commits[min(existing.commits)]
    return entry.message if set(entry.files) & set(paths) else ""


def pending_document(repo: Path, captures: Sequence[CapturedPath], head: str) -> BranchCommitDocument:
    """One-commit document for ``captures`` against ``head``; the message carries over from the pending TXT.

    A detached HEAD (no branch name) raises ``BuildError``.
    """
    branch = current_branch(repo)
    if not branch:
        raise BuildError(["detached HEAD: check out a branch before capture --pending"])
    paths = [path for capture in captures for path in capture.paths]
    message = _pending_message(pending_txt_path(repo, branch), head, paths)
    return document_from_commit_dict({1: (paths, message)}, branch, head, pending=True)


def run_capture_pending(repo: Path) -> Dict[str, object]:
    """Build the one-commit skeleton for the pending change (staged, unstaged, untracked) against HEAD."""
    head = git_out(repo, "rev-parse", "HEAD").strip()
    captures = capture_branch(repo, head)
    if not captures:
        raise BuildError([f"no pending change against HEAD {head[:9]}"])
    document = pending_document(repo, captures, head)
    return skeleton_payload(document, PENDING_SPLIT, captures, stats=capture_stats(repo, head, captures))


def _captured_entry(capture: CapturedPath, stat: DiffStat) -> Dict[str, object]:
    """One ``captured`` skeleton entry: status, paths, bucket and changed-line counts."""
    return {
        "status": capture.status, "path": capture.path, "old_path": capture.old_path,
        "bucket": capture.bucket.value, "added": stat.added, "deleted": stat.deleted,
    }


def _block_paths(payload: Mapping[str, object], block: int) -> List[str]:
    """Entries of skeleton block ``block``; raise ``BuildError`` when the block is absent or malformed."""
    commits = _commit_dict(payload)
    if block not in commits:
        blocks = ", ".join(str(key) for key in sorted(commits))
        raise BuildError([f"block {block} is not in the skeleton (blocks: {blocks})"])
    return list(commits[block][0])


def _block_stats(
        entries: Sequence[str], captures: Sequence[CapturedPath], stats: Mapping[str, DiffStat],
) -> Tuple[List[DiffStat], List[str]]:
    """Stats for a block's entries in entry order (globs expanded), and the entries matching nothing.

    A rename's old side matches but carries no stat of its own; its new path's diff covers it.
    """
    captured = captured_set(captures)
    ordered: Dict[str, DiffStat] = {}
    unmatched: List[str] = []
    for entry in entries:
        matched = sorted(expand_entry(entry, captured))
        if not matched:
            unmatched.append(entry)
        ordered.update({path: stats[path] for path in matched if path in stats and path not in ordered})
    return list(ordered.values()), unmatched


def run_diff(repo: Path, payload: Mapping[str, object], block: int) -> str:
    """Diff of one skeleton block under the ``commit_diff`` budgets: ``full`` or ``summary`` per path.

    Glob entries expand against the capture; an entry matching no captured path prints
    ``=== <entry> [no change captured] ===``.
    """
    merge_base = str(payload.get("merge_base") or "")
    if not merge_base:
        raise BuildError(["skeleton has no merge_base; rerun capture"])
    entries = _block_paths(payload, block)
    captures = capture_branch(repo, merge_base)
    ordered, unmatched = _block_stats(entries, captures, capture_stats(repo, merge_base, captures))
    modes = plan_reads(ordered)
    olds = {c.path: c.old_path for c in captures if c.old_path}
    untracked = set(untracked_paths(repo))
    sections = cap_sections([
        diff_section(repo, merge_base, s, modes[s.path], olds.get(s.path), s.path in untracked)
        for s in ordered
    ])
    sections += [f"=== {entry} [no change captured] ===" for entry in unmatched]
    return "\n".join(sections)


def document_from_commit_dict(
        commits: CommitDict, branch: Optional[str], merge_base: Optional[str], notes: Sequence[str] = (),
        pending: bool = False,
) -> BranchCommitDocument:
    """Construct a ``BranchCommitDocument`` from ``{order: (paths, message)}``, renumbered 1..N in key order.

    Construction skips the shared-path and pending one-commit checks so a later ``validate()`` reports
    every problem at once; the returned document carries the rebuild strategy (``one_path_per_commit=True``)
    and ``pending``.
    """
    entries = {
        number: entry_from_message(number, list(commits[key][0]), commits[key][1])
        for number, key in enumerate(sorted(commits), 1)
    }
    document = BranchCommitDocument(
        branch=branch, merge_base=merge_base, notes=list(notes), commits=entries, one_path_per_commit=False,
    )
    document.one_path_per_commit = True
    document.pending = pending
    return document


def _block_key(key: object) -> int:
    """Integer commit key of a skeleton block; raise ``BuildError`` when it does not parse."""
    try:
        return int(key)
    except (TypeError, ValueError) as exc:
        raise BuildError([f"skeleton commit key {key!r} is not an integer"]) from exc


def _block_value(key: object, value: object) -> Tuple[List[str], str]:
    """``(paths, message)`` of one skeleton block; raise ``BuildError`` unless ``[[paths], message]``."""
    if not (isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], (list, tuple))):
        raise BuildError([f"skeleton commit {key!r} is not a [[paths...], message] pair"])
    return list(value[0]), str(value[1])


def _commit_dict(payload: Mapping[str, object]) -> CommitDict:
    """Convert the payload's JSON commits (string keys, list pairs) to the commit dictionary.

    A ``commits`` value that is not an object, a non-integer key, or a malformed block raises ``BuildError``.
    """
    raw = payload.get("commits") or {}
    if not isinstance(raw, dict):
        raise BuildError([f"skeleton commits must be an object, not {type(raw).__name__}"])
    return {_block_key(key): _block_value(key, value) for key, value in raw.items()}


def document_from_payload(payload: Mapping[str, object], notes: Sequence[str] = ()) -> BranchCommitDocument:
    """Construct the ``BranchCommitDocument`` a skeleton describes; the inverse of ``skeleton_payload``."""
    return document_from_commit_dict(
        _commit_dict(payload), payload.get("branch"), str(payload.get("merge_base") or "") or None, notes,
        pending=bool(payload.get("pending")),
    )


def _validation_problems(document: BranchCommitDocument) -> List[str]:
    """Run ``validate()`` (null fields + one path per commit) and return its problems as lines."""
    try:
        document.validate()
    except ValueError as exc:
        return [line.strip() for line in str(exc).splitlines()[1:]]
    return []


def _round_trip_problems(text: str, document: BranchCommitDocument) -> List[str]:
    """Re-parse the rendered TXT and report any commit whose files or message would not survive."""
    try:
        parsed = parse_commit_txt(text)
    except ValueError as exc:
        return [f"rendered TXT does not re-parse: {exc}"]
    if sorted(parsed.commits) != sorted(document.commits):
        return [f"rendered TXT re-parses to {len(parsed.commits)} commits, expected {len(document.commits)}"]
    return [
        f"commit {key} does not round-trip through the TXT"
        for key, entry in document.commits.items()
        if (parsed.commits[key].files, parsed.commits[key].message) != (entry.files, entry.message)
    ]


def run_build(
        repo: Path, payload: Mapping[str, object], out: Optional[Path] = None,
) -> Tuple[Path, BranchCommitDocument]:
    """Validate the filled skeleton against a fresh capture and write the TXT.

    Any defect raises ``BuildError``. A pending skeleton whose ``merge_base`` is no longer HEAD raises
    before any validation.
    """
    branch = current_branch(repo)
    if payload.get("branch") != branch:
        raise BuildError([
            f"payload branch {payload.get('branch')!r} is not the checked-out branch {branch!r}",
        ])
    merge_base = str(payload.get("merge_base") or "")
    head = git_out(repo, "rev-parse", "HEAD").strip()
    notes = [f"Messaged-through: {head}", f"Split: {payload.get('split', '')}"]
    document = document_from_payload(payload, notes)
    if document.pending and document.merge_base != head:
        raise BuildError(["HEAD moved since capture; rerun capture --pending"])
    problems = _validation_problems(document)
    problems += coverage_problems(document, capture_branch(repo, merge_base)) if merge_base else []
    problems += message_problems(document)
    if problems:
        raise BuildError(problems)
    text = document_to_txt(document)
    round_trip = _round_trip_problems(text, document)
    if round_trip:
        raise BuildError(round_trip)
    suffix = checked_suffix(payload)
    default = pending_txt_path(repo, branch) if document.pending else txt_path(repo, branch, suffix)
    target = out or default
    target.parent.mkdir(parents=True, exist_ok=True)
    back_up_replaced(target, text)
    target.write_text(text, encoding="utf-8")
    return target, document


def back_up_replaced(target: Path, text: str) -> None:
    """Copy an existing ``target`` that ``text`` would change to ``<name>.bak`` (one generation kept).

    A dropped or mistyped ``--base`` then costs a rename, not the messages already drafted.
    """
    if target.is_file() and target.read_text(encoding="utf-8") != text:
        shutil.copyfile(target, target.with_name(target.name + ".bak"))


def receipt(repo: Path, out: Path, document: BranchCommitDocument, split: str) -> str:
    """Return the SKILL Step 7 chat receipt."""
    try:
        shown = out.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        shown = out.as_posix()
    lines = [f"Saved: {shown} - {len(document.commits)} commit(s) proposed"]
    lines += [f"{key}. {document.commits[key].header}" for key in sorted(document.commits)]
    return "\n".join([*lines, f"Split Decision: {split}"])


_REPO_HELP = "Directory inside the project (default: the working directory); its git top level is used."


def _repo_parent() -> argparse.ArgumentParser:
    """``--repo`` for each subcommand; a suppressed default keeps a top-level ``--repo`` intact."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help=_REPO_HELP)
    return parent


def _parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser; ``--repo`` is accepted before or after the subcommand."""
    parser = argparse.ArgumentParser(prog="branch_commit_msg.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=None, help=_REPO_HELP)
    sub = parser.add_subparsers(dest="command", required=True)
    repo = [_repo_parent()]
    cap = sub.add_parser(
        "capture", parents=repo, help="Print the commit skeleton JSON for the checked-out branch.",
    )
    cap.add_argument(
        "ref", nargs="?", metavar="REF",
        help="A bare ref is the same as --base REF; both given must name the same ref.",
    )
    cap.add_argument(
        "--base",
        help=(
            "Ref (SHA, HEAD, branch) to use as the merge base instead of resolving the project's base "
            "branch. The output is <branch>_<sha7>.json/.txt (also with --fresh), beside the branch "
            "TXT, which is never overwritten."
        ),
    )
    cap.add_argument("--no-fetch", action="store_true", help="Skip 'git fetch origin <base branch>'.")
    target = cap.add_mutually_exclusive_group()
    target.add_argument("--out", type=Path, help="Write the skeleton here instead of stdout.")
    target.add_argument(
        "--save", action="store_true",
        help="Write the skeleton to <commit_messages dir>/<branch>.json (<branch>_<sha7>.json for a "
             "--base capture, <branch>_pending.json with --pending) and print its "
             "absolute path.",
    )
    cap.add_argument(
        "--fresh", action="store_true",
        help=(
            "Replan from the rules, ignoring groupings and messages in the existing TXT "
            "(the <branch>_<sha7>.txt sibling or the branch TXT); the output name is unchanged."
        ),
    )
    cap.add_argument(
        "--pending", action="store_true",
        help=(
            "One commit for the change pending against HEAD (c-msg); "
            "--base, --no-fetch and --fresh are ignored."
        ),
    )
    diff = sub.add_parser(
        "diff", parents=repo, help="Print one skeleton block's diff under the read budgets.",
    )
    diff.add_argument("skeleton", type=Path, help="Skeleton JSON (UTF-8).")
    diff.add_argument("--block", type=int, required=True, help="Commit key of the block to read.")
    build = sub.add_parser("build", parents=repo, help="Validate a filled skeleton and write the TXT.")
    build.add_argument("skeleton", type=Path, help="Filled skeleton JSON (UTF-8).")
    build.add_argument(
        "--out", type=Path,
        help=(
            "TXT path (default <commit_messages dir>/<branch>.txt, <branch>_<sha7>.txt for a "
            "--base skeleton, or <branch>_pending.txt for a pending skeleton)."
        ),
    )
    return parser


def write_skeleton(out: Path, payload: Mapping[str, object]) -> None:
    """Write the skeleton JSON to ``out``, creating missing parent directories."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def skeleton_path(repo: Path, branch: str, pending: bool = False, suffix: str = "") -> Path:
    """``--save`` location: the TXT path for ``branch`` (pending or ledger) with a ``.json`` suffix."""
    path = pending_txt_path(repo, branch) if pending else txt_path(repo, branch, suffix)
    return path.with_suffix(".json")


def effective_base(ref: Optional[str], base: Optional[str]) -> Optional[str]:
    """The ref a capture plans against: a bare ``ref`` is ``--base``; both given must agree.

    A bare token outside the ref character set (free text, shell syntax) raises ``BuildError``.
    """
    if ref is not None and not _REF_PATTERN.fullmatch(ref):
        raise BuildError([f"{ref!r} is not a ref: expected a SHA, branch or tag name"])
    if ref is not None and base is not None and ref != base:
        raise BuildError([f"bare ref {ref!r} conflicts with --base {base!r}: give one"])
    return base if base is not None else ref


def _cmd_capture(repo: Path, args: argparse.Namespace) -> int:
    """Run ``capture`` and emit the skeleton."""
    base = effective_base(args.ref, args.base)
    if args.pending:
        payload = run_capture_pending(repo)
    else:
        payload = run_capture(repo, base, not args.no_fetch, fresh=args.fresh)
    if args.save:
        pending, suffix = bool(payload.get("pending")), str(payload.get("txt_suffix") or "")
        out = skeleton_path(repo, str(payload["branch"]), pending, suffix)
        write_skeleton(out, payload)
        print(f"wrote {out.resolve().as_posix()}")
    elif args.out:
        write_skeleton(args.out, payload)
        print(f"wrote {args.out}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _cmd_build(repo: Path, args: argparse.Namespace) -> int:
    """Run ``build`` and print the receipt."""
    payload = json.loads(args.skeleton.read_text(encoding="utf-8"))
    out, document = run_build(repo, payload, args.out)
    print(receipt(repo, out, document, str(payload.get("split", ""))))
    return 0


def _cmd_diff(repo: Path, args: argparse.Namespace) -> int:
    """Run ``diff`` and print the budgeted block diff."""
    payload = json.loads(args.skeleton.read_text(encoding="utf-8"))
    print(run_diff(repo, payload, args.block))
    return 0


def activate_project(start: Optional[Path]) -> Path:
    """Activate the configuration of the project holding ``start`` (default: cwd); return its root."""
    root = project_root(start)
    activate(load_config(root))
    return root


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point; return 0 on success, 1 on a validation or git failure."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    commands = {"capture": _cmd_capture, "diff": _cmd_diff, "build": _cmd_build}
    try:
        return commands[args.command](activate_project(args.repo), args)
    except BuildError as exc:
        sys.stderr.write("\n".join(f"problem: {line}" for line in exc.problems) + "\n")
        return 1
    except ConfigError as exc:
        sys.stderr.write(f"problem: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
