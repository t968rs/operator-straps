"""review_edit CLI: validated per-field edits of one PR review JSON through ``harness_lib.review_edit``.

Each invocation loads ``FILE``, applies one subcommand, and writes once through ``save_review`` (schema,
pending-``pre_fix_time`` and issue-count checks; canonical 2-space form, the file's LF / CRLF style kept). Any
problem leaves the file untouched, prints ``problem:`` lines and exits 1; a malformed command line is an
argparse usage error and exits 2.

``FILE resolve ID STATUS TEXT [--sha SHA] [--date D]``
    Append a ``post_review_resolutions`` entry for ``ID`` (earlier entries stay as history). With ``--sha``
    the evidence becomes ``<SHA> (working-tree snapshot; developer commits) - TEXT``. ``CLOSED_NO_ACTION``
    takes the rationale.
``FILE resolve-file PROPOSED_JSON --sha SHA [--bubble-ups BUBBLE_UPS_JSON]``
    Mirror every ``{id, classification, reason}`` item of ``BUBBLE_UPS_JSON`` (a pr-team sidecar ``{run_id,
    items}`` or a bare list) into ``bubble_up``, apply every ``{id, status, evidence[, date]}`` entry of
    ``PROPOSED_JSON`` (a list, or an object whose ``post_review_resolutions`` holds the list), recompute the
    verdict and write once; one bad entry writes nothing, and evidence must be a string. An entry whose id
    already has a latest resolution of the same status is skipped, so a re-run appends nothing. With
    ``--sha`` is required; evidence not already starting with a SHA takes the snapshot form.
``FILE verdict (--recompute | --text T)``
    ``--text`` is the developer's override; an agent recomputes (the verdict is derived, never typed).
``FILE bubble-up ID CLASSIFICATION REASON`` / ``FILE drop-bubble-up ID``
``FILE bubble ID`` / ``FILE clear-bubble ID``
``FILE reviewer (--add | --remove) NAME``
``FILE strength TEXT``
``FILE shas [--base SHA] [--head SHA]`` / ``FILE review-date D`` / ``FILE stats ADD DEL FILES``
``FILE regrade ID SEVERITY`` / ``FILE merge KEEP DROP[,DROP...]``
``FILE check``
    Validate only; nothing is written.

``--recompute`` recomputes the verdict before the write; it goes before the subcommand
(``FILE --recompute resolve ...``) or after it (``FILE resolve ... --recompute``) on every subcommand except
``verdict``, which rejects the top-level flag (its own ``--recompute`` does the same, and ``--text`` would be
overwritten), and ``check``, which rejects it (it validates the file as written).

An edit that leaves a READY verdict the dispositions no longer support (a reopening ``resolve``,
``clear-bubble``, ``drop-bubble-up``, ``regrade``) is refused with the computed verdict; rerun it with
``--recompute``. ``resolve-file`` always recomputes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from harness_lib import review_edit as re_  # noqa: E402
from harness_lib import review_merge as rmg  # noqa: E402
from harness_lib.config import activate, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402

Doc = Dict[str, object]


def _resolve(doc: Doc, a: argparse.Namespace) -> Doc:
    text = re_.snapshot_evidence(a.sha, a.text) if a.sha else a.text
    return re_.resolve(doc, a.id, a.status, text, a.date)


def _proposed(path: Path) -> List[Dict[str, object]]:
    """Proposed resolution entries of ``path``: a JSON list, or an object's ``post_review_resolutions``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    entries = data.get("post_review_resolutions") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected a list of resolutions or an object with post_review_resolutions")
    return entries


def _bubble_items(path: Optional[Path]) -> List[Dict[str, object]]:
    """Items of a pr-team ``bubble_ups.json`` sidecar (``{run_id, items}``, or a bare list); none without
    ``path``."""
    if path is None:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError(f"{path}: expected a list of bubble-up items or an object with items")
    return items


def _resolve_file(doc: Doc, a: argparse.Namespace) -> Doc:
    return re_.resolve_all(doc, _proposed(a.proposed), a.sha, _bubble_items(a.bubble_ups))


def _verdict(doc: Doc, a: argparse.Namespace) -> Doc:
    return re_.recompute_verdict(doc) if a.text is None else re_.set_verdict(doc, a.text)


def _reviewer(doc: Doc, a: argparse.Namespace) -> Doc:
    return re_.remove_reviewer(doc, a.name) if a.remove else re_.add_reviewer(doc, a.name)


_EDITS: Dict[str, Callable[[Doc, argparse.Namespace], Doc]] = {
    "resolve": _resolve,
    "resolve-file": _resolve_file,
    "verdict": _verdict,
    "bubble-up": lambda d, a: re_.add_bubble_up(d, a.id, a.classification, a.reason),
    "drop-bubble-up": lambda d, a: re_.drop_bubble_up(d, a.id),
    "bubble": lambda d, a: re_.add_bubble(d, a.id),
    "clear-bubble": lambda d, a: re_.clear_bubble(d, a.id),
    "reviewer": _reviewer,
    "strength": lambda d, a: re_.add_strength(d, a.text),
    "shas": lambda d, a: re_.set_shas(d, a.base, a.head),
    "review-date": lambda d, a: re_.set_review_date(d, a.date),
    "stats": lambda d, a: re_.set_stats(d, a.additions, a.deletions, a.files_changed),
    "regrade": lambda d, a: re_.regrade_issue(d, a.id, a.severity),
    "merge": lambda d, a: re_.merge_issue_ids(d, a.keep, [x.strip() for x in a.drop.split(",") if x.strip()]),
    "check": lambda d, a: d,
}


def _recompute_parent() -> argparse.ArgumentParser:
    """Parent parser adding ``--recompute`` after a subcommand (default suppressed so the top-level value
    stands when the flag is absent)."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--recompute", action="store_true", default=argparse.SUPPRESS,
                        help="Recompute the verdict before writing.")
    return parent


def _add_edits(sub: argparse._SubParsersAction, common: List[argparse.ArgumentParser]) -> None:
    res = sub.add_parser("resolve", parents=common)
    for name in ("id", "status", "text"):
        res.add_argument(name)
    res.add_argument("--sha")
    res.add_argument("--date")
    batch = sub.add_parser("resolve-file", parents=common)
    batch.add_argument("proposed", type=Path)
    batch.add_argument("--sha", required=True)
    batch.add_argument("--bubble-ups", type=Path)
    ver =sub.add_parser("verdict").add_mutually_exclusive_group(required=True)
    ver.add_argument("--recompute", action="store_true", dest="verdict_recompute")
    ver.add_argument("--text")
    bub = sub.add_parser("bubble-up", parents=common)
    for name in ("id", "classification", "reason"):
        bub.add_argument(name)
    for name in ("drop-bubble-up", "bubble", "clear-bubble"):
        sub.add_parser(name, parents=common).add_argument("id")
    rev = sub.add_parser("reviewer", parents=common)
    who = rev.add_mutually_exclusive_group(required=True)
    who.add_argument("--add", action="store_true")
    who.add_argument("--remove", action="store_true")
    rev.add_argument("name")
    sub.add_parser("strength", parents=common).add_argument("text")


def _add_meta(sub: argparse._SubParsersAction, common: List[argparse.ArgumentParser]) -> None:
    shas = sub.add_parser("shas", parents=common)
    shas.add_argument("--base")
    shas.add_argument("--head")
    sub.add_parser("review-date", parents=common).add_argument("date")
    stats = sub.add_parser("stats", parents=common)
    for name in ("additions", "deletions", "files_changed"):
        stats.add_argument(name, type=int)
    reg = sub.add_parser("regrade", parents=common)
    reg.add_argument("id")
    reg.add_argument("severity")
    mrg = sub.add_parser("merge", parents=common)
    mrg.add_argument("keep")
    mrg.add_argument("drop")
    sub.add_parser("check", parents=common)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review_edit.py", description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path)
    parser.add_argument("--repo", type=Path, help="Project root (default: the file's project).")
    parser.add_argument("--recompute", action="store_true", help="Recompute the verdict before writing.")
    sub = parser.add_subparsers(dest="command", required=True)
    common = [_recompute_parent()]
    _add_edits(sub, common)
    _add_meta(sub, common)
    return parser


def _load(path: Path) -> Doc:
    """``review_edit.load_review`` with a JSON decode error prefixed by the file name."""
    try:
        return re_.load_review(path)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _refuse_stale_ready(out: Doc, command: str) -> None:
    """``ValueError`` when the edited document keeps a READY verdict that ``recompute_verdict`` rejects."""
    if not str(out.get("verdict") or "").startswith("READY TO MERGE"):
        return
    computed = str(re_.recompute_verdict(out)["verdict"])
    if not computed.startswith("READY TO MERGE"):
        raise ValueError(f"{command} leaves a stale READY verdict; computed verdict: {computed} "
                         "(rerun with --recompute)")


def run(args: argparse.Namespace) -> int:
    """Apply one edit to ``args.file`` and write it (``check``: validate only)."""
    root = project_root(args.repo or args.file.resolve().parent)
    activate(load_config(root))
    if args.recompute and args.command == "check":
        raise ValueError("--recompute does not apply to check: check validates the file as written")
    if args.recompute and args.command == "verdict":
        raise ValueError("top-level --recompute conflicts with verdict: "
                         "use verdict --recompute or verdict --text")
    out = _EDITS[args.command](_load(args.file), args)
    if args.recompute:
        out = re_.recompute_verdict(out)
    if args.command != "check":
        _refuse_stale_ready(out, args.command)
    if args.command == "check":
        problems = rmg.validate_review(out, root)
        if problems:
            raise ValueError("\n".join(problems))
        print(f"ok: {args.file}")
        return 0
    re_.save_review(args.file, out, root)
    print(f"wrote {args.file}: verdict: {out.get('verdict')}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point; 0 on success, 1 with ``problem:`` lines otherwise (2 on a usage error)."""
    args = _parser().parse_args(argv)
    try:
        return run(args)
    except KeyError as exc:
        lines = [f"{args.file}: missing key {exc}"]
    except (ValueError, OSError, TypeError) as exc:
        lines = [line for line in str(exc).splitlines() if line.strip()] or [type(exc).__name__]
    sys.stderr.write("\n".join(f"problem: {line}" for line in lines) + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
