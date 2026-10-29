"""merge-commit-msg driver: capture a PR's facts into a merge-message MD, then build the TXT.

Two subcommands bracket the one judgment step (the prose and the file bullets of the merge message):

``capture N``
    Read PR N through ``gh`` (shape, commit headlines, changed files), the branch's commit-message TXT when
    one exists, the PR's review JSON (``artifacts.reviews``) and the canned message for the changed files
    (``harness_lib.canned_messages``). Write ``PR<N>_merge.md`` into the project's ``commit_messages``
    directory (``artifacts.commit_messages``, default ``docs/_commit_messages``): the facts, then a
    ``text`` fence holding the message with the subject, lineage and review lines already filled in. Prints
    ``wrote <md>``. Exits 1 when the PR is not open.

``build N``
    Take the first ``text`` fence under ``## Message`` of ``PR<N>_merge.md``, validate it (verbatim subject,
    column-0 layout, bullets, no placeholder left, no vendor names, filler words, commit SHAs or sign-offs),
    and write it to ``PR<N>_merge.txt`` beside the MD, keeping the replaced copy as ``.txt.bak``. Prints the
    chat receipt. Exit 1 prints one ``problem:`` line per defect and leaves the TXT untouched.

Usage::

    merge_commit_msg.py [--repo DIR] capture N
    merge_commit_msg.py [--repo DIR] build N
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from harness_lib.canned_messages import get_canned_message  # noqa: E402
from harness_lib.commit_txt import filler_words, read_commit_txt, vendor_names  # noqa: E402
from harness_lib.config import ConfigError, active, activate, load_config  # noqa: E402
from harness_lib.project import project_root  # noqa: E402

LINE_WIDTH = 110
MAX_LINES = 30
PLACEHOLDER = re.compile(r"^\s*(?:-\s+)?<.*>\s*$")
_UNSAFE = re.compile(r'[\\/:*?"<>|]')
_ARROWS = re.compile(r"\s*(?:-->|->)\s*")
_SHA = re.compile(r"(?<![\w./-])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w/-])")
_SIGNOFF = re.compile(r"^\s*(co-authored-by|signed-off-by):", re.IGNORECASE)
_OPEN_FENCE = re.compile(r"^(`{3,})text\s*$")
_TITLE_FACT = re.compile(r"^- Title: (.+)$", re.MULTILINE)
PROSE_HINT = "<Prose: what changed and why, 2-3 short paragraphs; lead with the action.>"
BULLET_HINT = "  - <file>: <key change; 4-7 representative files>"
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


def md_path(pr: int) -> Path:
    return output_dir() / f"PR{pr}_merge.md"


def txt_path(pr: int) -> Path:
    return output_dir() / f"PR{pr}_merge.txt"


def safe_stem(value: str) -> str:
    """``value`` with path separators and filename-invalid characters replaced by ``_``."""
    return _UNSAFE.sub("_", value)


def pr_view(repo: Path, pr: int) -> Dict[str, object]:
    """The PR's shape from ``gh pr view``; only an open PR gets a merge message."""
    fields = "number,title,headRefName,baseRefName,additions,deletions,changedFiles,body,state"
    data = json.loads(gh(repo, "pr", "view", str(pr), "--json", fields))
    if data.get("state") != "OPEN":
        raise MergeMessageError(f"PR #{pr} is {data.get('state')}, not OPEN")
    return data


def pr_commits(repo: Path, pr: int) -> List[str]:
    """First line of each PR commit message (paginated: one page stops at 30 commits)."""
    out = gh(repo, "api", "--paginate", f"repos/{{owner}}/{{repo}}/pulls/{pr}/commits", "--jq",
             '.[].commit.message | split("\\n")[0]')
    return [line for line in out.splitlines() if line.strip()]


def pr_files(repo: Path, pr: int) -> List[str]:
    out = gh(repo, "pr", "diff", str(pr), "--name-only")
    return [line.strip() for line in out.splitlines() if line.strip()]


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


def message_template(pr: int, title: str, names: Sequence[str], canned: Optional[str]) -> List[str]:
    """The prefilled message: subject, prose (canned or a placeholder), bullets, lineage, review lines."""
    prose = canned.strip().splitlines() if canned else [PROSE_HINT]
    lineage = " -> ".join(f"`{n}`" for n in names)
    return [f"Merge PR #{pr} — {title}", "", *prose, "", BULLET_HINT, "", f"Branch lineage: {lineage}",
            *([""] if review_json(pr) else []), *review_lines(pr)]


def _bullets(lines: Sequence[str]) -> List[str]:
    return [f"- {line}" for line in lines] or ["- none"]


def render(pr: int, view: Dict[str, object], files: Sequence[str], commits: Sequence[str],
           subjects: Sequence[str]) -> str:
    """The merge-message MD: script-owned facts, then the ``text`` fence the agent edits."""
    title, base, head = str(view["title"]), str(view["baseRefName"]), str(view["headRefName"])
    names = lineage_names(str(view.get("body") or ""), base, head)
    canned = get_canned_message(files)
    message = message_template(pr, title, names, canned)
    size = f"+{view['additions']} -{view['deletions']} across {view['changedFiles']} files"
    facts = [f"- Title: {title}", f"- Branch: `{head}` into `{base}`", f"- Size: {size}",
             f"- Canned message: {'yes, prefilled as the prose' if canned else 'none'}"]
    parts = [f"# PR #{pr} merge message", "",
             "Facts are script-owned. Edit only the `text` fence under Message, then run `build`.", "",
             "## Facts", "", *facts, "", "## Changed files", "", *_bullets(files), "", "## Commits", "",
             *_bullets(commits), "", "## Branch commit subjects", "", *_bullets(subjects), "",
             "## Message", "", "```text", *message, "```", ""]
    return "\n".join(parts)


def run_capture(repo: Path, pr: int) -> Path:
    """Write ``PR<pr>_merge.md`` for the open PR and return its path."""
    view = pr_view(repo, pr)
    subjects = branch_subjects(str(view["headRefName"]))
    text = render(pr, view, pr_files(repo, pr), pr_commits(repo, pr), subjects)
    target = md_path(pr)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def extract_message(text: str) -> Tuple[List[str], str]:
    """The lines of the first ``text`` fence under ``## Message`` and the ``- Title:`` fact."""
    title = _TITLE_FACT.search(text)
    head, sep, tail = text.partition("\n## Message\n")
    if not title or not sep:
        raise MergeMessageError("the MD has no '- Title:' fact or no '## Message' section; rerun capture")
    lines = tail.splitlines()
    for i, line in enumerate(lines):
        match = _OPEN_FENCE.match(line)
        if not match:
            continue
        for j in range(i + 1, len(lines)):
            if lines[j].rstrip() == match.group(1):
                return lines[i + 1:j], title.group(1)
        raise MergeMessageError("the text fence under '## Message' is never closed")
    raise MergeMessageError("no text fence under '## Message'")


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


def structure_problems(lines: Sequence[str], pr: int, title: str) -> List[str]:
    """Subject, placeholders, bullets and lineage-after-bullets of the message lines."""
    subject = f"Merge PR #{pr} — {title}"
    problems: List[str] = []
    if not lines or lines[0] != subject:
        problems.append(f"subject must be exactly {subject!r}")
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
    """Vendor names, filler, commit SHAs and sign-offs in the body (the subject quotes the title verbatim)."""
    body = "\n".join(lines[1:])
    problems = [f"vendor name {name!r} in the message" for name in vendor_names(body)]
    problems += [f"filler {word!r} - state what changed instead" for word in filler_words(body)]
    problems += [f"commit SHA {m.group(0)!r}; the merge UI records SHAs" for m in _SHA.finditer(body)]
    problems += [f"sign-off line {line.strip()!r}" for line in lines if _SIGNOFF.match(line)]
    return problems


def message_problems(lines: Sequence[str], pr: int, title: str) -> List[str]:
    return structure_problems(lines, pr, title) + layout_problems(lines) + content_problems(lines)


def back_up_replaced(target: Path, text: str) -> None:
    """Copy an existing ``target`` that ``text`` would change to ``<name>.bak`` (one generation kept)."""
    if target.is_file() and target.read_text(encoding="utf-8") != text:
        shutil.copyfile(target, target.with_name(target.name + ".bak"))


def run_build(repo: Path, pr: int) -> Tuple[Path, str]:
    """Validate the MD's message fence and write ``PR<pr>_merge.txt``; return its path and the subject."""
    source = md_path(pr)
    if not source.is_file():
        raise MergeMessageError(f"{source.as_posix()} does not exist; run capture {pr} first")
    lines, title = extract_message(source.read_text(encoding="utf-8"))
    problems = message_problems(lines, pr, title)
    if problems:
        raise MergeMessageError("\n".join(f"problem: {p}" for p in problems))
    text = "\n".join(lines).rstrip() + "\n"
    target = txt_path(pr)
    back_up_replaced(target, text)
    target.write_text(text, encoding="utf-8", newline="\n")
    return target, lines[0]


def receipt(repo: Path, target: Path, pr: int, subject: str) -> str:
    """The chat receipt: saved path, subject and the final-as-saved line."""
    try:
        shown = target.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        shown = target.as_posix()
    final = ("Final as saved: relay this receipt unchanged. The message changes only on the developer's "
             f"ask: edit the text fence of {md_path(pr).name}, then rerun build.")
    return "\n".join([f"Saved: {shown} - merge message for PR #{pr}", f"Subject: {subject}", final])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="merge_commit_msg.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="project checkout (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("capture", "Write the merge-message MD for an open PR."),
                       ("build", "Validate the MD's message fence and write the TXT.")):
        sub.add_parser(name, help=text).add_argument("pr", type=int, help="PR number")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        repo = activate(load_config(project_root(args.repo))).project_root
        if args.command == "capture":
            print(f"wrote {run_capture(repo, args.pr).resolve().as_posix()}")
        else:
            target, subject = run_build(repo, args.pr)
            print(receipt(repo, target, args.pr, subject))
    except (MergeMessageError, ConfigError) as exc:
        text = str(exc)
        sys.stderr.write(text + "\n" if text.startswith("problem:") else f"problem: {text}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
