"""bubble_memo driver: scaffold, brief, record, apply and check the decision memo of a PR's bubbled issues.

The memo ``<artifacts.reviews>/PR_<N>_Bubbles.md`` lists each issue a pr-review bubbled up for the developer's
decision. Pure parsing and rendering live in ``harness_lib.bubble_memo``; this script wires files and runs
read-only git. Every defect is one ``problem: ...`` line on stderr with exit 1.

``scaffold --pr N``
    Read the newest ``<NNNN>_*.json`` review of PR N and, when a pr-review run exists, its pending fixer
    bubbles. Create the memo, or append the entries and index rows it lacks. Print the added and flagged ids
    and one investigator dispatch row per newly added flagged id. Without a bubbled issue, print
    ``nothing currently bubbled`` and write no memo.

``init --pr N --id ID --role investigator`` / ``init --pr N --role reviewer``
    Print the agent's whole brief and save it under ``<artifacts.scratch>/bubble_memo/<N>/briefs``.

``record --pr N [--id ID] --role investigator|reviewer``
    Read the agent's JSON report on stdin, validate it, write it under ``facts`` (investigator) or
    ``findings`` (reviewer) and print the fenced return block.

``apply --pr N``
    Write each recorded facts report into its memo entry, over the ``TODO(fill)`` stubs. References are
    replaced by the verified ones only while the entry's other fact stubs remain, so a rerun keeps hand
    corrections. Only ids whose entry changed are listed as applied.

``check --pr N``
    Exit 1 with one problem line per defect; ``note:`` lines never fail. When clean, print ``check [ok]`` and
    the reviewer dispatch row.

``--repo`` (default: the working directory) names a directory inside the project. Usage::

    bubble_memo.py [--repo DIR] scaffold --pr N
    bubble_memo.py [--repo DIR] init --pr N --role investigator --id ID
    bubble_memo.py [--repo DIR] init --pr N --role reviewer
    bubble_memo.py [--repo DIR] record --pr N --role investigator --id ID < facts.json
    bubble_memo.py [--repo DIR] record --pr N --role reviewer < findings.json
    bubble_memo.py [--repo DIR] apply --pr N
    bubble_memo.py [--repo DIR] check --pr N
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from harness_lib import bubble_memo as bm
from harness_lib import review_bubbles as rb
from harness_lib import review_models as rm
from harness_lib.branch_capture import CaptureError, git
from harness_lib.config import ConfigError, active, activate, load_config
from harness_lib.project import project_root

PROBLEMS = (CaptureError, ConfigError, ValueError, OSError)
INVESTIGATOR_AGENT = "harness:bubble-memo-investigator"
REVIEWER_AGENT = "harness:bubble-memo-reviewer"
INVESTIGATOR_MODEL = "opus"
CONTEXT_LINES = 5
CONTEXT_MAX = 200
SCRIPT_DIR = Path(__file__).resolve().parent
_SHA_RE = re.compile(r"[0-9a-f]{7,40}")
_TOKEN_RE = re.compile(r"`([^`]+?:\d+(?:-\d+)?)`")

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MemoFinding(BaseModel):
    """One reviewer finding about the memo."""

    model_config = ConfigDict(extra="forbid")

    id: NonEmpty
    kind: Literal["accuracy", "clarity"]
    what: NonEmpty
    suggested: NonEmpty


class MemoFindings(BaseModel):
    """The reviewer's report: findings, possibly none."""

    model_config = ConfigDict(extra="forbid")

    findings: List[MemoFinding]


@dataclass(frozen=True)
class Review:
    """A PR's review JSON with the issues currently bubbled."""

    pr: int
    path: Path
    doc: Dict[str, Any]
    bubbled: List[bm.Bubbled]


# --- locations --------------------------------------------------------------------------------------------

def _root() -> Path:
    return active().project_root.resolve()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(_root()).as_posix()
    except ValueError:
        return path.as_posix()


def _reviews_dir() -> Path:
    return active().path(active().artifacts.reviews)


def memo_path(pr: int) -> Path:
    return (_reviews_dir() / bm.memo_name(pr)).resolve()


def agent_dir(pr: int) -> Path:
    """``<artifacts.scratch>/bubble_memo/<PR>``: briefs, facts and findings of the agents."""
    return active().path(active().artifacts.scratch) / "bubble_memo" / str(pr)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


# --- review and bubbled set -------------------------------------------------------------------------------

def find_review(pr: int) -> Path:
    """The newest ``<NNNN>_*.json`` of PR ``pr`` under ``artifacts.reviews``."""
    folder = _reviews_dir()
    found = list(folder.glob(f"{pr:04d}_*.json")) if folder.is_dir() else []
    if not found:
        raise CaptureError([f"no review JSON for PR {pr} under {_rel(folder)}"])
    return max(found, key=lambda p: (p.stat().st_mtime_ns, p.name))


def pending_fixer_bubbles(doc: Mapping[str, Any], pr: int) -> List[Tuple[str, str, str]]:
    """``(id, class, reason)`` of the fixer bubbles not yet in the review; empty without a pr-review run."""
    try:
        run = rm.run_dir(pr, _root())
    except FileNotFoundError:
        return []
    if not run.is_dir():
        return []
    return [(b.id, str(getattr(b.classification, "value", b.classification)), b.reason)
            for _, b in rb.pending_bubbles(doc, run)]


def _doc_problems(doc: Mapping[str, Any]) -> List[str]:
    """Defects of the review fields the driver puts into paths, git arguments and memo text."""
    problems = []
    sha = doc.get("head_sha")
    if sha and not _SHA_RE.fullmatch(str(sha)):
        problems.append(f"head_sha {sha!r} is not a 7-40 character hex SHA")
    for entry in doc.get("bubble_up") or []:
        if not isinstance(entry, Mapping) or "id" not in entry:
            problems.append("a bubble_up entry has no id")
    ids = [str(i) for i in doc.get("bubbles") or []]
    ids += [str(e["id"]) for e in doc.get("bubble_up") or [] if isinstance(e, Mapping) and "id" in e]
    problems += [f"issue id {i!r} does not match {rm.ISSUE_ID}"
                 for i in ids if not re.fullmatch(rm.ISSUE_ID, i)]
    return problems


def load_review(pr: int) -> Review:
    path = find_review(pr)
    doc = json.loads(path.read_text(encoding="utf-8"))
    problems = _doc_problems(doc)
    if problems:
        raise CaptureError([f"{_rel(path)}: {p}" for p in problems])
    return Review(pr, path, doc, bm.currently_bubbled(doc, pending_fixer_bubbles(doc, pr)))


def read_memo(pr: int) -> str:
    path = memo_path(pr)
    if not path.is_file():
        raise CaptureError([f"no memo at {_rel(path)}; run scaffold first"])
    return path.read_text(encoding="utf-8")


# --- dispatch rows ----------------------------------------------------------------------------------------

def _context(review: Review, item: bm.Bubbled) -> str:
    issue = bm.find_issue(review.doc, item.id) or {}
    text = bm.one_line(f"{issue.get('name') or item.id}; {item.cls}; {item.reason}")
    return text if len(text) <= CONTEXT_MAX else text[:CONTEXT_MAX - 3] + "..."


def investigator_row(review: Review, item: bm.Bubbled) -> str:
    issue = bm.find_issue(review.doc, item.id) or {}
    files = ", ".join(bm.issue_files(issue))
    return "\n".join([f"agent={INVESTIGATOR_AGENT} model={INVESTIGATOR_MODEL}", f"PR: {review.pr}",
                      f"ISSUE: {item.id}", f"FILES: {files}", f"CONTEXT: {_context(review, item)}"])


def entry_flagged(doc: Mapping[str, Any], ident: str, block: str) -> bool:
    """Entry-level flag, the rule `check` applies: the JSON rule, or References naming several files."""
    return bm.needs_chain(ident, bm.find_issue(doc, ident)) or len(bm.reference_files(block)) > 1


def reviewer_row(review: Review) -> str:
    blocks = bm.entry_blocks(read_memo(review.pr))
    flagged = [b.id for b in review.bubbled if entry_flagged(review.doc, b.id, blocks.get(b.id, ""))]
    model = bm.reviewer_model(flagged)
    return "\n".join([f"agent={REVIEWER_AGENT} model={model}", f"PR: {review.pr}",
                      f"Memo: {memo_path(review.pr).as_posix()}"])


# --- scaffold ---------------------------------------------------------------------------------------------

def _scaffold_text(review: Review) -> Tuple[str, List[str]]:
    """New memo text and added ids: the whole memo when absent, else the appended entries."""
    path = memo_path(review.pr)
    if path.is_file():
        return bm.add_missing(path.read_text(encoding="utf-8"), review.doc, review.bubbled)
    text = bm.scaffold_memo(review.doc, review.bubbled, review_file=_rel(review.path))
    return text, [b.id for b in review.bubbled]


def cmd_scaffold(args: argparse.Namespace) -> int:
    review = load_review(args.pr)
    if not review.bubbled:
        print(f"scaffold [done] | PR {args.pr} | nothing currently bubbled; no memo written")
        return 0
    path = memo_path(args.pr)
    had = set(bm.entry_blocks(path.read_text(encoding="utf-8"))) if path.is_file() else set()
    text, added = _scaffold_text(review)
    if added:
        _write(path, text)
    flagged = bm.flagged_ids(review.doc, [i for i in added if i not in had])
    print(f"scaffold [done] | memo: {memo_path(args.pr).as_posix()} | added: {', '.join(added) or '-'} "
          f"| flagged: {', '.join(flagged) or '-'}")
    rows = [investigator_row(review, b) for b in review.bubbled if b.id in flagged]
    if rows:
        print("\n\n".join(rows))
    return 0


# --- init: shared pieces ----------------------------------------------------------------------------------

def _git_text(*args: str) -> str:
    done = git(_root(), *args)
    return done.stdout.rstrip() if done.returncode == 0 else "unavailable"


def _git_facts(doc: Mapping[str, Any], files: Sequence[str]) -> List[str]:
    paths = ["--", *files] if files else []
    status = _git_text("status", "--short", *paths)
    stat = _git_text("diff", "--stat", str(doc.get("head_sha") or "HEAD"), *paths)
    return ["## Git facts (read-only)", "",
            f"- Branch: {_git_text('branch', '--show-current') or '(detached)'}",
            f"- HEAD: {_git_text('rev-parse', 'HEAD')}",
            f"- Review head: {doc.get('head_sha') or 'unknown'}",
            f"- Review base: {doc.get('base_sha') or 'unknown'}",
            "- git status --short of the referred files:", *_indented(status or "(clean)"),
            "- git diff --stat since the review head, referred files:", *_indented(stat or "(no change)"), ""]


def _indented(text: str) -> List[str]:
    return [f"    {line}" for line in text.split("\n")]


def _safe_file(rel_path: str) -> Optional[Path]:
    target = (_root() / rel_path).resolve()
    return target if target.is_relative_to(_root()) and target.is_file() else None


def _file_lines(rel_path: str) -> Optional[List[str]]:
    target = _safe_file(rel_path)
    if target is None:
        return None
    parts = target.read_text(encoding="utf-8", errors="replace").split("\n")
    return parts[:-1] if parts and parts[-1] == "" else parts


def _file_facts(files: Sequence[str]) -> List[str]:
    out = ["## Files", ""]
    for name in files:
        lines = _file_lines(name)
        out.append(f"- {name}: " + (f"exists, {len(lines)} lines" if lines is not None else "does not exist"))
    return out + [""]


def excerpt(rel_path: str, first: int, last: int) -> List[str]:
    """Line-numbered lines around ``first-last`` of a working-tree file; cited lines carry a ``>``."""
    lines = _file_lines(rel_path)
    if lines is None:
        return [f"    {rel_path}: not on disk"]
    start, end = max(1, first - CONTEXT_LINES), min(len(lines), last + CONTEXT_LINES)
    out = [f"  {rel_path}:{first}" + (f"-{last}" if last != first else "")]
    out += [f"  {'>' if first <= n <= last else ' '}{n:>5}: {lines[n - 1]}" for n in range(start, end + 1)]
    return out


def _span(value: str) -> Optional[Tuple[int, int]]:
    match = bm.LINES_RE.fullmatch(value.strip().lstrip("~").strip())
    return (int(match.group(1)), int(match.group(2) or match.group(1))) if match else None


def cited_ranges(issue: Mapping[str, Any]) -> List[Tuple[str, int, int]]:
    """``(file, first, last)`` the issue cites: its `lines` when it names exactly one file."""
    files = bm.issue_files(issue)
    span = _span(str(issue.get("lines"))) if len(files) == 1 and issue.get("lines") else None
    return [(files[0], span[0], span[1])] if span else []


def _fix_lines(issue: Mapping[str, Any]) -> List[str]:
    fixes = issue.get("fix") or []
    return [f"  ({bm.label(i)}) {bm.one_line(fix)}" for i, fix in enumerate(fixes)]


def _record_command(args: argparse.Namespace, ident: Optional[str]) -> str:
    who = f" --id {ident}" if ident else ""
    return (f'sh "{(SCRIPT_DIR / "hpy").as_posix()}" "{(SCRIPT_DIR / "bubble_memo.py").as_posix()}" '
            f'--repo "{_root().as_posix()}" record --pr {args.pr}{who} --role {args.role}')


def _heredoc(command: str, body: str) -> List[str]:
    return ["```", f"{command} <<'JSON'", *body.split("\n"), "JSON", "```", ""]


def _save_brief(pr: int, name: str, text: str) -> None:
    _write(agent_dir(pr) / "briefs" / f"{name}.md", text)
    sys.stdout.write(text)


# --- init: investigator -----------------------------------------------------------------------------------

def _facts_template(issue: Mapping[str, Any], ident: str) -> str:
    template = {"id": ident, "current_behavior": "...", "when": "...", "chain": ["step one", "step two"],
                "flow": "a -> b", "references": [{"at": "path:line or path:start-end", "note": "..."}],
                "fix_effects": [{"option": bm.one_line(f), "effect": "..."} for f in issue.get("fix") or []],
                "confidence": "high|medium|low"}
    return json.dumps(template, indent=2)


def _issue_section(item: bm.Bubbled, issue: Mapping[str, Any]) -> List[str]:
    return ["## Issue", "", f"- Id: {item.id}", f"- Name: {bm.one_line(issue.get('name') or '')}",
            f"- Class: {item.cls}", f"- Reason bubbled: {item.reason or '(none given)'}",
            f"- Summary: {bm.one_line(issue.get('summary') or '')}",
            f"- Files: {', '.join(bm.issue_files(issue)) or '(none named)'}",
            f"- Lines: {issue.get('lines') or '(none named)'}", "- Fix options:", *_fix_lines(issue), ""]


def investigator_brief(review: Review, item: bm.Bubbled, args: argparse.Namespace) -> str:
    issue = bm.find_issue(review.doc, item.id) or {}
    files = bm.issue_files(issue)
    ranges = [line for rng in cited_ranges(issue) for line in excerpt(*rng)]
    out = [f"# Investigator brief: PR {review.pr}, issue {item.id}", "", *_issue_section(item, issue),
           *_git_facts(review.doc, files), *_file_facts(files),
           "## Excerpts around the cited lines", "", *(ranges or ["  (no cited range; read the files)"]), "",
           "## Report", "",
           "Trace the issue through the code. Cite each reference as `path:line` or `path:start-end` in "
           "the working tree. One fix_effects item per fix option, in order, with the option text unchanged. "
           "Run record exactly once:", "",
           *_heredoc(_record_command(args, item.id), _facts_template(issue, item.id))]
    return "\n".join(out)


def _bubbled_item(review: Review, ident: Optional[str]) -> bm.Bubbled:
    if not ident:
        raise CaptureError(["--id is required for the investigator role"])
    for item in review.bubbled:
        if item.id == ident:
            return item
    raise CaptureError([f"{ident} is not currently bubbled in PR {review.pr}"])


# --- init: reviewer ---------------------------------------------------------------------------------------

def memo_references(block: str) -> List[Tuple[str, int, int]]:
    """``(file, first, last)`` of each backticked `path:line` span of a memo entry."""
    out = []
    for token in _TOKEN_RE.findall(block):
        match = bm.REF_RE.fullmatch(token)
        if match:
            out.append((match.group(1), int(match.group(2)), int(match.group(3) or match.group(2))))
    return out


def _entry_table(review: Review, ident: str, block: str) -> List[str]:
    issue = bm.find_issue(review.doc, ident) or {}
    flagged = "yes" if entry_flagged(review.doc, ident, block) else "no"
    refs = memo_references(block)
    out = [f"### {ident} (flagged: {flagged})", "", "Fix options:", *_fix_lines(issue), "",
           "References with excerpts:"]
    for ref in refs:
        out += excerpt(*ref)
    return out + ([] if refs else ["  (none)"]) + [""]


def reviewer_brief(review: Review, args: argparse.Namespace) -> str:
    text = read_memo(args.pr)
    blocks = bm.entry_blocks(text)
    template = json.dumps({"findings": [{"id": "I1", "kind": "accuracy|clarity", "what": "...",
                                         "suggested": "..."}]}, indent=2)
    out = [f"# Reviewer brief: PR {review.pr}", "", f"Memo: {memo_path(args.pr).as_posix()}",
           f"Review JSON: {_rel(review.path)}", "", *_git_facts(review.doc, []),
           "## Entries", "", *(line for i, b in blocks.items() for line in _entry_table(review, i, b)),
           "## Report", "",
           "Check accuracy (each reference exists and says what the entry claims; behavior claims agree with "
           "the code; each expected-behavior line follows from its fix option) and clarity (ordinary words, "
           "one claim per bullet, nothing repeated). Edit nothing. Run record exactly once:", "",
           *_heredoc(_record_command(args, None), template)]
    return "\n".join(out)


def cmd_init(args: argparse.Namespace) -> int:
    review = load_review(args.pr)
    if args.role == "investigator":
        item = _bubbled_item(review, args.id)
        _save_brief(args.pr, item.id, investigator_brief(review, item, args))
    else:
        _save_brief(args.pr, "reviewer", reviewer_brief(review, args))
    return 0


# --- record -----------------------------------------------------------------------------------------------

def _stdin_json() -> Any:
    raw = sys.stdin.read().lstrip("﻿")
    if not raw.strip():
        raise ValueError("no JSON report on stdin")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"stdin is not valid JSON: {exc}") from exc


def return_block(role: str, output: Path) -> str:
    return "\n".join(["---", "SIGNAL: DONE", f"AGENT_ROLE: {role}", f"OUTPUT: {_rel(output)}", "---"])


def _record_investigator(review: Review, ident: Optional[str]) -> Path:
    item = _bubbled_item(review, ident)
    issue = bm.find_issue(review.doc, item.id)
    if issue is None:
        raise CaptureError([f"{item.id} is not an issue of the review JSON"])
    facts = bm.validate_facts(_stdin_json(), issue, _root())
    path = agent_dir(review.pr) / "facts" / f"{item.id}.json"
    _write(path, facts.model_dump_json(indent=2) + "\n")
    return path


def _record_reviewer(review: Review) -> Path:
    try:
        report = MemoFindings.model_validate(_stdin_json())
    except ValidationError as exc:
        raise ValueError(bm.format_errors(exc)) from exc
    known = set(bm.entry_blocks(read_memo(review.pr)))
    unknown = sorted({f.id for f in report.findings if f.id not in known})
    if unknown:
        raise ValueError(f"finding ids not in the memo: {', '.join(unknown)}")
    path = agent_dir(review.pr) / "findings" / f"{review.pr}.json"
    _write(path, report.model_dump_json(indent=2) + "\n")
    return path


def cmd_record(args: argparse.Namespace) -> int:
    review = load_review(args.pr)
    if args.role == "investigator":
        path = _record_investigator(review, args.id)
    else:
        path = _record_reviewer(review)
    print(return_block(args.role, path))
    return 0


# --- apply ------------------------------------------------------------------------------------------------

def _load_facts(report: Path) -> bm.Facts:
    try:
        return bm.Facts.model_validate_json(report.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ValueError(f"{report.name}: {bm.format_errors(exc)}") from exc


def cmd_apply(args: argparse.Namespace) -> int:
    path = memo_path(args.pr)
    text = read_memo(args.pr)
    folder = agent_dir(args.pr) / "facts"
    applied: List[str] = []
    for report in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        facts = _load_facts(report)
        updated = bm.apply_facts(text, facts)
        if updated != text:
            applied.append(facts.id)
            text = updated
    if applied:
        _write(path, text)
    print(f"apply [done] | memo: {path.as_posix()} | applied: {', '.join(applied) or '-'}")
    return 0


# --- check ------------------------------------------------------------------------------------------------

def cmd_check(args: argparse.Namespace) -> int:
    review = load_review(args.pr)
    problems, notes = bm.check_memo(read_memo(args.pr), review.bubbled, review.doc, _root())
    for note in notes:
        print(f"note: {note}")
    if problems:
        raise CaptureError(problems)
    print(f"check [ok] | PR {args.pr} | {len(review.bubbled)} entries "
          f"| memo: {memo_path(args.pr).as_posix()}")
    print(reviewer_row(review))
    return 0


# --- cli --------------------------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bubble_memo.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=None, help="Directory inside the project (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("scaffold", "Create or extend the memo."), ("check", "Check the memo is complete.")):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--pr", type=int, required=True)
    apply_cmd = sub.add_parser("apply", help="Write recorded facts into the memo.")
    apply_cmd.add_argument("--pr", type=int, required=True)
    for name, text in (("init", "Print and save an agent's brief."), ("record", "Record an agent's report.")):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--pr", type=int, required=True)
        cmd.add_argument("--role", choices=("investigator", "reviewer"), required=True)
        cmd.add_argument("--id", default=None, help="Issue id (investigator role).")
    return parser


COMMANDS: Dict[str, Callable[[argparse.Namespace], int]] = {
    "scaffold": cmd_scaffold, "init": cmd_init, "record": cmd_record, "apply": cmd_apply, "check": cmd_check,
}


def _problem_lines(exc: Exception) -> List[str]:
    lines = getattr(exc, "problems", None)
    return [str(line) for line in lines] if lines else [str(exc)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point; return 0 on success, 1 on a problem."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        activate(load_config(project_root(args.repo)))
        return COMMANDS[args.command](args)
    except PROBLEMS as exc:
        sys.stderr.write("".join(f"problem: {line}\n" for line in _problem_lines(exc)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
