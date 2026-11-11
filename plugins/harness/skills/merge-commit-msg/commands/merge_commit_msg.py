"""merge-commit-msg driver: capture a PR's facts to stdout, then build the TXT from a message on stdin.

Two subcommands bracket the one judgment step (the prose and the file bullets of the merge message). No file
stands between them: ``build`` asks ``gh`` for the title again.

Two modes set the subject. The merge mode (the default) heads a merge commit, ``Merge PR #N -- <title>``.
The squash mode (``--squash``, ``-s`` or a bare ``squash`` after the PR number) heads the one commit a
squash-merge lands, GitHub's ``<title> (#N)``, so the title must parse as a ``Word(scope): summary``
subject: a word of letters, an optional scope, a colon and a non-empty summary (the type is not checked
against a type list). Any other mode token is refused. Both modes write ``PR<N>_merge.txt``.

``capture N [squash]``
    Read PR N through ``gh`` (shape, commit headlines, changed files, one ``gh pr diff``), the branch's
    commit-message TXT when one exists, the PR's review JSON (``artifacts.reviews``) and the canned message
    for the changed files (``harness_lib.canned_messages``). Print the facts (the mode among them) and the
    PR's diff (one section per file under ``DIFF_SECTION_CHARS`` characters, the whole under
    ``DIFF_CHAR_BUDGET``: a section past the budget keeps its ``diff --git`` header), then a ``text`` fence
    holding the message skeleton with the subject of the mode, lineage and review lines already filled in.
    Writes no file. Exits 1 when the PR is not open or its title cannot head the subject of the mode; with
    ``--auto-title`` such a title adds a ``- Title problem:`` fact instead, and the subject line of the
    skeleton becomes ``RETITLE_HINT``, filled from what ``retitle`` prints. Without the flag the project's
    ``auto_title`` key decides; ``--no-auto-title`` turns it off for one capture.

``retitle N [squash] --title T``
    Replace a PR title the mode refuses with ``T`` through ``harness_lib.pr_title.change_pr_title``
    (``gh pr edit``; ``T`` must pass the ``Word(scope): summary`` rule in both modes) and print the subject of
    the mode for ``T``. Exits 1, changing nothing, when the PR is not open, its title already heads the
    subject of the mode, or ``T`` is refused.

``build N [squash]``
    Take the message from stdin, validate it (verbatim subject of the mode from ``gh``, column-0 layout,
    bullets, no placeholder left, no vendor names, filler words, commit SHAs or sign-offs), and write it to
    ``PR<N>_merge.txt`` in the project's ``commit_messages`` directory (``artifacts.commit_messages``, default
    ``docs/_commit_messages``), keeping the replaced copy as ``.txt.bak``. Prints the chat receipt. Exit 1
    prints one ``problem:`` line per defect and leaves the TXT untouched. Reads the title from ``gh`` again,
    so it exits 1 when the PR is not open or ``gh`` fails. Without a squash flag or token, a first line equal
    to the squash subject selects the squash mode, so a saved squash TXT rebuilds without the flag.

Usage::

    merge_commit_msg.py [--repo DIR] capture N [--squash | -s | squash] [--auto-title | --no-auto-title]
    merge_commit_msg.py [--repo DIR] retitle N [--squash | -s | squash] --title T
    merge_commit_msg.py [--repo DIR] build N [--squash | -s | squash] <<'MSG' ... MSG
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, TextIO, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from harness_lib.canned_messages import project_canned_message  # noqa: E402
from harness_lib.commit_diff import cap_sections, clip_text  # noqa: E402
from harness_lib.commit_txt import (  # noqa: E402
    filler_words,
    glyph_problems,
    read_commit_txt,
    vendor_names,
)
from harness_lib.config import ConfigError, active, activate, load_config  # noqa: E402
from harness_lib.pr_capture import read_rank  # noqa: E402
from harness_lib.pr_title import TitleError, change_pr_title, title_defect, title_problem  # noqa: E402
from harness_lib.project import project_root  # noqa: E402

LINE_WIDTH = 110
MAX_LINES = 30
DIFF_SECTION_CHARS = 4_000
DIFF_CHAR_BUDGET = 20_000
_DIFF_START = re.compile(r"^(?=diff --git )", re.M)
_DIFF_PATH = re.compile(r"^diff --git a/.* b/(.+)$")
PLACEHOLDER = re.compile(r"^\s*(?:-\s+)?<.*>\s*$")
_UNSAFE = re.compile(r'[\\/:*?"<>|]')
SUBJECT_SEPARATOR = "--"
_ARROWS = re.compile(r"\s*(?:-->|->)\s*")
_SHA = re.compile(r"(?<![\w./-])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w/-])")
_SIGNOFF = re.compile(r"^\s*(co-authored-by|signed-off-by):", re.IGNORECASE)
PROSE_HINT = "<Prose: what changed and why, 2-3 short paragraphs; lead with the action.>"
BULLET_HINT = "  - <file>: <key change; 4-7 representative files>"
RETITLE_HINT = "<Subject: the Subject line retitle prints>"
TIERS = ("critical", "important", "minor")


class MergeMessageError(RuntimeError):
    """A precondition for capturing or building the merge message does not hold."""


def gh(repo: Path, *args: str) -> str:
    """Stdout of ``gh args`` run in ``repo``; a failure raises ``MergeMessageError`` with gh's message."""
    try:
        done = subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
    except FileNotFoundError as exc:
        raise MergeMessageError("gh is not installed or not on PATH") from exc
    if done.returncode != 0:
        detail = done.stderr.strip() or done.stdout.strip()
        raise MergeMessageError(f"gh {' '.join(args[:2])} failed: {detail}")
    return done.stdout


def output_dir() -> Path:
    """The configured commit_messages directory of the active project."""
    return active().path(active().artifacts.commit_messages.strip("/"))


def txt_path(pr: int) -> Path:
    return output_dir() / f"PR{pr}_merge.txt"


def safe_stem(value: str) -> str:
    """``value`` with path separators and filename-invalid characters replaced by ``_``."""
    return _UNSAFE.sub("_", value)


def subject_line(pr: int, title: str, squash: bool = False) -> str:
    """The subject of the mode: GitHub's squash form, or the merge form with an ASCII separator.

    The separator is ASCII because Windows shell wrappers garble a non-ASCII one.
    """
    if squash:
        return f"{title} (#{pr})"
    return f"Merge PR #{pr} {SUBJECT_SEPARATOR} {title}"


def fetch_view(repo: Path, pr: int) -> Dict[str, object]:
    """The PR's shape from ``gh pr view``; a PR that is not open is refused."""
    fields = "number,title,headRefName,baseRefName,additions,deletions,changedFiles,body,state"
    data = json.loads(gh(repo, "pr", "view", str(pr), "--json", fields))
    if data.get("state") != "OPEN":
        raise MergeMessageError(f"PR #{pr} is {data.get('state')}, not OPEN")
    return data


def check_title(view: Dict[str, object], pr: int, squash: bool = False,
                offer_auto_title: bool = True) -> None:
    """Raise ``MergeMessageError`` when the PR title cannot head the subject of the mode.

    ``offer_auto_title`` False keeps the ``--auto-title`` hint out of the problem, for ``build``.
    """
    problem = title_problem(pr, str(view["title"]), str(view["headRefName"]), squash, offer_auto_title)
    if problem:
        raise MergeMessageError(problem)


def pr_commits(repo: Path, pr: int) -> List[str]:
    """First line of each PR commit message (paginated: one page stops at 30 commits)."""
    out = gh(repo, "api", "--paginate", f"repos/{{owner}}/{{repo}}/pulls/{pr}/commits", "--jq",
             '.[].commit.message | split("\\n")[0]')
    return [line for line in out.splitlines() if line.strip()]


def pr_files(repo: Path, pr: int) -> List[str]:
    out = gh(repo, "pr", "diff", str(pr), "--name-only")
    return [line.strip() for line in out.splitlines() if line.strip()]


def _section_path(section: str) -> str:
    """The new-side path of a ``diff --git`` section (its whole header line when the path does not parse)."""
    header = section.split("\n", 1)[0]
    match = _DIFF_PATH.match(header)
    return match.group(1) if match else header


def pr_diff(repo: Path, pr: int) -> List[str]:
    """The PR's diff as one section per file (source, tests, docs order), each clipped, the whole capped.

    One ``gh pr diff`` call; sections split on ``diff --git`` headers. A section past ``DIFF_SECTION_CHARS``
    ends in an omission line; once ``DIFF_CHAR_BUDGET`` characters are spent, later sections keep only
    their header.
    """
    text = gh(repo, "pr", "diff", str(pr), "--color=never")
    sections = [s for s in _DIFF_START.split(text) if s.startswith("diff --git ")]
    ordered = sorted(sections, key=lambda s: read_rank(_section_path(s)))
    return cap_sections([clip_text(s, DIFF_SECTION_CHARS) for s in ordered], DIFF_CHAR_BUDGET)


def lineage_names(body: str, base: str, head: str) -> List[str]:
    """Branch names from a ``lineage:`` or ``-->`` line of the PR body, else ``[base, head]``."""
    for line in body.splitlines():
        if "-->" not in line and not re.search(r"lineage:", line, re.IGNORECASE):
            continue
        text = re.sub(r"(?i)^.*?lineage:\s*", "", line)
        names = [n.strip(" []`*") for n in _ARROWS.split(text) if n.strip(" []`*")]
        if len(names) >= 2:
            return names
    return [base, head]


def review_json(pr: int) -> Optional[Path]:
    """The PR's review JSON (``<reviews>/<NNNN>_*.json``), else None; the first by name when several."""
    folder = active().path(active().artifacts.reviews.strip("/"))
    found = sorted(folder.glob(f"{pr:04d}_*.json")) if folder.is_dir() else []
    return found[0] if found else None


def review_fix_counts(path: Path) -> Dict[str, int]:
    """Resolved issues per tier (critical, important, minor) of a review JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    resolved = {r.get("id") for r in data.get("post_review_resolutions", []) if r.get("status") == "RESOLVED"}
    issues = data.get("issues", {})
    return {tier: sum(1 for i in issues.get(tier, []) if i.get("id") in resolved) for tier in TIERS}


def review_lines(pr: int) -> List[str]:
    """The ``Review artifacts:`` line, plus ``Includes`` when fixes were resolved; empty without a JSON."""
    path = review_json(pr)
    if path is None:
        return []
    rel = path.resolve().relative_to(active().project_root.resolve()).as_posix()
    lines = [f"Review artifacts: {rel}."]
    if len(lines[0]) > LINE_WIDTH:
        lines = ["Review artifacts:", f"{rel}."]
    counts = review_fix_counts(path)
    if sum(counts.values()):
        tiers = ", ".join(f"{t.title()}: {counts[t]}" for t in TIERS)
        lines.append(f"Includes {sum(counts.values())} review fixes ({tiers}).")
    return lines


def branch_subjects(branch: str) -> List[str]:
    """Commit subjects of the branch's ``<branch>.txt`` ledger (nested or flat), empty when there is none."""
    folder = output_dir()
    key = safe_stem(branch)
    for path in sorted(folder.rglob("*.txt")) if folder.is_dir() else []:
        if safe_stem(path.relative_to(folder).with_suffix("").as_posix()) != key:
            continue
        try:
            document = read_commit_txt(path, one_path_per_commit=False)
        except (OSError, ValueError):
            return []
        return [document.commits[k].header or "" for k in sorted(document.commits)]
    return []


def message_template(pr: int, title: str, names: Sequence[str], canned: Optional[str],
                     squash: bool = False) -> List[str]:
    """The prefilled message: mode subject, prose (canned or a placeholder), bullets, lineage, review."""
    prose = canned.strip().splitlines() if canned else [PROSE_HINT]
    lineage = " -> ".join(f"`{n}`" for n in names)
    return [subject_line(pr, title, squash), "", *prose, "", BULLET_HINT, "", f"Branch lineage: {lineage}",
            *([""] if review_json(pr) else []), *review_lines(pr)]


def _bullets(lines: Sequence[str]) -> List[str]:
    return [f"- {line}" for line in lines] or ["- none"]


def mode_name(squash: bool) -> str:
    return "squash" if squash else "merge"


def retitle_lines(pr: int, squash: bool) -> List[str]:
    """The capture intro lines for a title ``--auto-title`` replaces: write one, run ``retitle``."""
    command = f"retitle {pr}{' --squash' if squash else ''} --title \"<title>\""
    return ["", "The PR title cannot head the subject (Title problem). Write a Word(scope): summary title "
            f"from the facts and run `{command}`; it sets the PR title. Then replace the subject placeholder "
            "with the Subject line it prints."]


def render(pr: int, view: Dict[str, object], files: Sequence[str], commits: Sequence[str],
           subjects: Sequence[str], diff: Sequence[str] = (), squash: bool = False,
           retitle: Optional[str] = None) -> str:
    """The capture output: script-owned facts, then the ``text`` fence holding the message skeleton.

    ``retitle`` is the defect of a title ``--auto-title`` replaces: it becomes a ``- Title problem:`` fact
    and the skeleton's subject becomes ``RETITLE_HINT``.
    """
    title, base, head = str(view["title"]), str(view["baseRefName"]), str(view["headRefName"])
    names = lineage_names(str(view.get("body") or ""), base, head)
    canned = project_canned_message(files)
    message = message_template(pr, title, names, canned, squash)
    message[0] = RETITLE_HINT if retitle else message[0]
    size = f"+{view['additions']} -{view['deletions']} across {view['changedFiles']} files"
    facts = [f"- Title: {title}", *([f"- Title problem: {retitle}"] if retitle else []),
             f"- Mode: {mode_name(squash)}", f"- Branch: `{head}` into `{base}`",
             f"- Size: {size}", f"- Canned message: {'yes, prefilled as the prose' if canned else 'none'}"]
    command = "build --squash" if squash else "build"
    parts = [f"# PR #{pr} {mode_name(squash)} message", "",
             "Facts and the diff are script-owned. Fill the placeholders of the skeleton under Message from "
             "them, keep its subject, lineage and review lines, and pass the message to "
             f"`{command}` on stdin.",
             *(retitle_lines(pr, squash) if retitle else []),
             "",
             "## Facts", "", *facts, "", "## Changed files", "", *_bullets(files), "", "## Diff", "",
             *(diff or ["- none"]), "", "## Commits", "",
             *_bullets(commits), "", "## Branch commit subjects", "", *_bullets(subjects), "",
             "## Message", "", "```text", *message, "```", ""]
    return "\n".join(parts)


def run_capture(repo: Path, pr: int, squash: bool = False, auto_title: bool = False) -> str:
    """The facts and the message skeleton of the open PR in the mode; nothing is written.

    A title the mode refuses ends the capture, unless ``auto_title``: then the skeleton asks for ``retitle``.
    """
    view = fetch_view(repo, pr)
    if not auto_title:
        check_title(view, pr, squash)
    defect = title_defect(str(view["title"]), str(view["headRefName"]), squash)
    subjects = branch_subjects(str(view["headRefName"]))
    return render(pr, view, pr_files(repo, pr), pr_commits(repo, pr), subjects, pr_diff(repo, pr), squash,
                  defect)


def run_retitle(repo: Path, pr: int, title: str, squash: bool = False) -> str:
    """Set the open PR's title to ``title`` when the mode refuses the current one; return the report lines.

    ``change_pr_title`` refuses a ``title`` that is not a ``Word(scope): summary`` subject before ``gh``
    runs; a usable current title is refused here, so a title that already works is never replaced.
    """
    title = title.strip()
    view = fetch_view(repo, pr)
    old, head = str(view["title"]), str(view["headRefName"])
    if title_defect(old, head, squash) is None:
        raise MergeMessageError(f"PR #{pr} title {old!r} already heads the {mode_name(squash)} subject; "
                                "nothing to retitle")
    change_pr_title(pr, title, repo, head)
    return f"Retitled PR #{pr}: {old!r} -> {title!r}\nSubject: {subject_line(pr, title, squash)}"


def read_message(stream: TextIO) -> List[str]:
    """The message lines on ``stream`` without trailing blank lines; an empty message is refused."""
    if stream.isatty():
        raise MergeMessageError("no message on stdin; pass the message to build as a heredoc or pipe")
    try:
        lines = stream.read().splitlines()
    except UnicodeDecodeError as exc:
        raise MergeMessageError("stdin is not UTF-8; pass the message as a heredoc from Git Bash") from exc
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise MergeMessageError("no message on stdin; pass the message to build as a heredoc")
    return lines


def layout_problems(lines: Sequence[str]) -> List[str]:
    """Column-0 layout, bullet indent, width and length defects of the message lines."""
    problems = [f"line {n}: indented text; only '  - ' bullets indent" for n, line in enumerate(lines, 1)
                if line[:1].isspace() and not line.startswith("  - ")]
    problems += [f"line {n}: wider than {LINE_WIDTH} columns" for n, line in enumerate(lines, 1)
                 if len(line) > LINE_WIDTH]
    problems += [f"line {n}: a markdown fence belongs outside the message" for n, line in enumerate(lines, 1)
                 if line.lstrip().startswith("```")]
    if len(lines) > MAX_LINES:
        problems.append(f"{len(lines)} lines; the budget is {MAX_LINES}")
    return problems


def subject_problem(lines: Sequence[str], pr: int, title: str, squash: bool = False) -> Optional[str]:
    """Why line 1 is not the subject of the mode, else None; in squash mode a merge subject names the flag."""
    subject = subject_line(pr, title, squash)
    if lines and lines[0] == subject:
        return None
    if squash and lines and lines[0] == subject_line(pr, title):
        return (f"subject is the merge form; drop the squash mode (--squash, -s, squash) to keep it, "
                f"or use {subject!r}")
    return f"subject must be exactly {subject!r}"


def structure_problems(lines: Sequence[str], pr: int, title: str, squash: bool = False) -> List[str]:
    """Subject, placeholders, bullets and lineage-after-bullets of the message lines."""
    problem = subject_problem(lines, pr, title, squash)
    problems: List[str] = [problem] if problem else []
    if len(lines) > 1 and lines[1].strip():
        problems.append("line 2 must be blank")
    problems += [f"line {n}: unfilled placeholder" for n, line in enumerate(lines, 1)
                 if PLACEHOLDER.match(line)]
    bullets = [n for n, line in enumerate(lines) if line.startswith("  - ")]
    lineage = [n for n, line in enumerate(lines) if line.startswith("Branch lineage: ")]
    if not bullets:
        problems.append("no '  - file: change' bullet")
    if len(lineage) != 1:
        problems.append("exactly one 'Branch lineage:' line is required")
    elif bullets and lineage[0] < bullets[-1]:
        problems.append("'Branch lineage:' must come after the bullets")
    return problems


def content_problems(lines: Sequence[str]) -> List[str]:
    """Vendor names, filler, emoji, section signs, SHAs and sign-offs in the body (not the quoted subject)."""
    body = "\n".join(lines[1:])
    problems = [f"vendor name {name!r} in the message" for name in vendor_names(body)]
    problems += [f"filler {word!r} - state what changed instead" for word in filler_words(body)]
    problems += glyph_problems(body, "the message")
    problems += [f"commit SHA {m.group(0)!r}; the merge UI records SHAs" for m in _SHA.finditer(body)]
    problems += [f"sign-off line {line.strip()!r}" for line in lines if _SIGNOFF.match(line)]
    return problems


def message_problems(lines: Sequence[str], pr: int, title: str, squash: bool = False) -> List[str]:
    return structure_problems(lines, pr, title, squash) + layout_problems(lines) + content_problems(lines)


def back_up_replaced(target: Path, text: str) -> None:
    """Copy an existing ``target`` that ``text`` would change to ``<name>.bak`` (one generation kept)."""
    if target.is_file() and target.read_text(encoding="utf-8") != text:
        shutil.copyfile(target, target.with_name(target.name + ".bak"))


def run_build(repo: Path, pr: int, stream: TextIO, squash: bool = False) -> Tuple[Path, str, bool]:
    """Validate the message on ``stream`` and write ``PR<pr>_merge.txt``; return its path, subject and mode.

    Without ``squash``, a first line equal to the squash subject selects the squash mode, title check
    included. With ``squash``, a merge-form first line is refused before the title check, so the hint to
    drop the squash mode is not masked by a title the squash mode refuses.
    """
    lines = read_message(stream)
    view = fetch_view(repo, pr)
    title = str(view["title"])
    if squash and lines[0] == subject_line(pr, title):
        raise MergeMessageError(f"problem: {subject_problem(lines, pr, title, squash)}")
    squash = squash or lines[0] == subject_line(pr, title, squash=True)
    check_title(view, pr, squash, offer_auto_title=False)
    problems = message_problems(lines, pr, title, squash)
    if problems:
        raise MergeMessageError("\n".join(f"problem: {p}" for p in problems))
    text = "\n".join(lines).rstrip() + "\n"
    target = txt_path(pr)
    target.parent.mkdir(parents=True, exist_ok=True)
    back_up_replaced(target, text)
    target.write_text(text, encoding="utf-8", newline="\n")
    return target, lines[0], squash


def receipt(repo: Path, target: Path, pr: int, subject: str, squash: bool = False) -> str:
    """The chat receipt: saved path with the mode, subject and the final-as-saved line."""
    try:
        shown = target.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        shown = target.as_posix()
    final = ("Final as saved: relay this receipt unchanged. The message changes only on the developer's "
             f"ask: rerun build with PR{pr}_merge.txt, changed as asked, on stdin.")
    saved = f"Saved: {shown} - {mode_name(squash)} message for PR #{pr}"
    return "\n".join([saved, f"Subject: {subject}", final])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="merge_commit_msg.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="project checkout (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {}
    for name, text in (("capture", "Print the facts and the message skeleton of an open PR."),
                       ("build", "Validate the message on stdin and write the TXT."),
                       ("retitle", "Replace a PR title the mode refuses (gh pr edit); print the subject.")):
        command = commands[name] = sub.add_parser(name, help=text)
        command.add_argument("pr", type=int, help="PR number")
        command.add_argument("mode", nargs="?", help="'squash' for a squash-merge subject")
        command.add_argument("--squash", "-s", action="store_true", help="squash subject '<title> (#N)'")
    commands["capture"].add_argument("--auto-title", action=argparse.BooleanOptionalAction, default=None,
                                     help="a title the mode refuses asks for retitle instead of exiting 1 "
                                          "(default: harness.json auto_title)")
    commands["retitle"].add_argument("--title", required=True, help="the new Word(scope): summary title")
    return parser


def squash_mode(args: argparse.Namespace) -> bool:
    """Whether the parsed arguments select the squash mode; an unknown mode token is refused."""
    if args.mode is not None and args.mode != "squash":
        raise MergeMessageError(f"unknown mode {args.mode!r}; the only mode is squash (--squash, -s)")
    return bool(args.squash or args.mode == "squash")


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream, encoding in ((sys.stdin, "utf-8-sig"), (sys.stdout, "utf-8")):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding=encoding)
    args = _parser().parse_args(argv)
    try:
        squash = squash_mode(args)
        repo = activate(load_config(project_root(args.repo))).project_root
        if args.command == "capture":
            auto_title = active().auto_title if args.auto_title is None else args.auto_title
            sys.stdout.write(run_capture(repo, args.pr, squash, auto_title))
        elif args.command == "retitle":
            print(run_retitle(repo, args.pr, args.title, squash))
        else:
            target, subject, squash = run_build(repo, args.pr, sys.stdin, squash)
            print(receipt(repo, target, args.pr, subject, squash))
    except (MergeMessageError, TitleError, ConfigError) as exc:
        text = str(exc)
        sys.stderr.write(text + "\n" if text.startswith("problem:") else f"problem: {text}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
