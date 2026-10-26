"""Parse and render the branch-commit-msg TXT (``<branch>.txt`` in the ``commit_messages`` directory).

Layout is defined by the plugin's ``skills/branch-commit-msg/txt_format.md``: a header (``Branch:``,
``Merge base:``, free-form note lines such as ``Messaged-through:`` / ``Split:``), a ``===`` line,
then ``---``-separated commit blocks::

    Commit N - <Bucket> (<M> files)
    "path/one.py",

    <Type>(<scope>): <subject>

    Prose body.
      - file: change

The ``Branch:`` footer closes the last block only. Parsing also accepts the legacy em-dash header
separator and lowercase bucket labels.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from harness_lib.branch_commits import BranchCommitDocument, Bucket, CommitEntry, commit_bucket

SECTION_SEP = "==="
GROUP_SEP = "---"

# The one statement of how a saved commit message may change; the build receipt, the TXT guard hook and the
# harness rules all repeat it word for word.
CHANGE_ROUTE = ("A message changes only on the developer's ask: harness:amend-commit-msg [--base <sha7>] -- "
                "<change> for a branch TXT (the --base its draft used), harness:c-msg <change> for a "
                "pending TXT.")

# "Commit 1 - Runtime+Test (5 files)" or legacy "Commit 1 — runtime (5 files) [COMMITTED f0d4360d]"
_COMMIT_HEADER = re.compile(
    r"^Commit\s+(\d+)\s+[-–—]\s+(.+?)\s+\((\d+)\s+files?\)(?:\s+\[(.+)])?\s*$"
)
# "Feature(billing): add rate validation"
_SUBJECT = re.compile(r"^([A-Za-z]+)(?:\(([^)]*)\))?:\s*(.*)$")
# "  - params.py: extend tool parameter contract"
_BULLET = re.compile(r"^\s*-\s*(.+?):\s*(.*)$")
_QUOTED_PATH = re.compile(r'^"(.+?)",?$')
_BACKTICKED = re.compile(r"^`(.*)`$")

# Subject rule from the plugin's reference/commit_format.md "Commit types".
_HEADER_RULE = re.compile(r"^(?:Feature|Fix|Refactor|Test|Build|Docs|Chore)(?:\([^()\s]+\))?: \S")
# Vendor names outside verbatim paths (".claude/", "CLAUDE.md" and similar are exempt).
_VENDOR = re.compile(
    r"(?<![\w./-])(copilot|claude|chatgpt|anthropic|openai|codex|gemini)(?![\w/-]|\.\w)", re.IGNORECASE
)
# Filler prose that names a quality instead of the change (commit_format.md "Body"); paths are exempt.
_FILLER = re.compile(
    r"(?<![\w./-])(enhanc\w*|improv\w*|streamlin\w*|robust\w*|reliab\w*|maintainab\w*|readab\w*"
    r"|seamless\w*|comprehensive\w*|leverag\w*|various)(?![\w/-]|\.\w)",
    re.IGNORECASE,
)


def _strip_backticks(value: str) -> str:
    """Remove a single wrapping pair of backticks, if present."""
    match = _BACKTICKED.match(value.strip())
    return match.group(1) if match else value.strip()


def _split_header_and_body(text: str) -> Tuple[List[str], str]:
    """Return (header_lines, body_text) split on the first ``===`` separator."""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() == SECTION_SEP:
            return lines[:idx], "\n".join(lines[idx + 1:])
    return [], text


def _parse_header(header_lines: List[str]) -> Dict[str, object]:
    """Extract branch, merge base, and free-form note lines from the header."""
    branch: Optional[str] = None
    merge_base: Optional[str] = None
    notes: List[str] = []
    for raw in header_lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Branch:"):
            branch = _strip_backticks(line[len("Branch:"):].strip())
        elif line.startswith("Merge base:"):
            merge_base = line[len("Merge base:"):].strip()
        else:
            notes.append(line)
    return {"branch": branch, "merge_base": merge_base, "notes": notes}


def _parse_files(lines: List[str], start: int) -> Tuple[List[str], int]:
    """Collect consecutive quoted-path lines from ``start``; return (files, next)."""
    files: List[str] = []
    idx = start
    while idx < len(lines):
        match = _QUOTED_PATH.match(lines[idx].strip())
        if not match:
            break
        files.append(match.group(1))
        idx += 1
    return files, idx


def _parse_body(body_lines: List[str]) -> Tuple[str, List[Dict[str, str]], Optional[str]]:
    """Split body lines into (prose, bullets, branch) for one commit block."""
    prose: List[str] = []
    bullets: List[Dict[str, str]] = []
    branch: Optional[str] = None
    for raw in body_lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Branch:"):
            branch = _strip_backticks(line[len("Branch:"):].strip())
            continue
        bullet = _BULLET.match(raw)
        if bullet:
            bullets.append({"file": bullet.group(1).strip(), "change": bullet.group(2).strip()})
        else:
            prose.append(line)
    return " ".join(prose).strip(), bullets, branch


def strip_footer(message: str) -> str:
    """Return ``message`` without ``Branch:`` footer lines, right-trimmed per line, outer blanks removed."""
    kept = [line.rstrip() for line in message.splitlines() if not line.strip().startswith("Branch:")]
    return "\n".join(kept).strip()


def _subject_parts(header: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (type, scope, subject) from a subject line, or Nones when it does not parse."""
    match = _SUBJECT.match(header) if header else None
    if match is None:
        return None, None, None
    return match.group(1), match.group(2), match.group(3).strip()


def _parse_commit_block(block: str) -> Optional[CommitEntry]:
    """Parse one ``---``-delimited commit block into a structured entry."""
    lines = block.splitlines()
    header_idx = next((i for i, ln in enumerate(lines) if _COMMIT_HEADER.match(ln.strip())), None)
    if header_idx is None:
        return None
    head = _COMMIT_HEADER.match(lines[header_idx].strip())
    files, after_files = _parse_files(lines, header_idx + 1)

    rest = list(lines[after_files:])
    subject_idx = next((i for i, ln in enumerate(rest) if _SUBJECT.match(ln.strip())), None)
    header_line = rest[subject_idx].strip() if subject_idx is not None else None
    type_, scope, subject = _subject_parts(header_line)
    message_lines = rest[subject_idx:] if subject_idx is not None else []
    body, bullets, branch = _parse_body(rest[subject_idx + 1:] if subject_idx is not None else rest)
    return CommitEntry(
        index=int(head.group(1)),
        bucket=head.group(2).strip(),
        files=files,
        header=header_line,
        message=strip_footer("\n".join(message_lines)),
        commit_type=type_,
        scope=scope,
        subject=subject,
        tag=head.group(4).strip() if head.group(4) else None,
        body=body,
        bullets=bullets,
        branch=branch,
        file_count=int(head.group(3)),
    )


def parse_commit_txt(text: str, one_path_per_commit: bool = True) -> BranchCommitDocument:
    """Parse branch-commit-msg TXT content into a ``BranchCommitDocument``.

    Raises ``ValueError`` when a bucket label is unknown, or when ``one_path_per_commit``
    is set and a path appears in more than one commit block.
    """
    header_lines, body_text = _split_header_and_body(text)
    commits: Dict[int, CommitEntry] = {}
    for block in body_text.split(f"\n{GROUP_SEP}\n"):
        entry = _parse_commit_block(block)
        if entry is not None:
            commits[entry.index] = entry
    return BranchCommitDocument(
        **_parse_header(header_lines), commits=commits, one_path_per_commit=one_path_per_commit
    )


def read_commit_txt(path: Union[str, Path], one_path_per_commit: bool = True) -> BranchCommitDocument:
    """Read and parse the TXT at ``path`` (UTF-8)."""
    return parse_commit_txt(Path(path).read_text(encoding="utf-8"), one_path_per_commit)


def entry_from_message(number: int, paths: Sequence[str], message: str) -> CommitEntry:
    """Build a commit entry from a path list and a full commit message; the bucket derives from the paths."""
    text = strip_footer(message)
    header = text.splitlines()[0].strip() if text else None
    type_, scope, subject = _subject_parts(header)
    return CommitEntry(
        index=number,
        bucket=commit_bucket(paths),
        files=list(paths),
        header=header,
        message=text,
        commit_type=type_,
        scope=scope,
        subject=subject,
        file_count=len(paths),
    )


def _render_block(number: int, commit: CommitEntry) -> str:
    """Render one commit block (header line, quoted file list, message) without separators."""
    message = commit.message or commit.header or ""
    head = f"Commit {number} - {Bucket(commit.bucket).value} ({len(commit.files)} files)"
    return "\n".join([head, *(f'"{path}",' for path in commit.files), "", message])


def document_to_txt(document: BranchCommitDocument) -> str:
    """Render ``document`` as TXT; commits are numbered by sorted key and the footer closes the last block."""
    head = [f"Branch: `{document.branch}`", f"Merge base: {document.merge_base}", *document.notes]
    blocks = [_render_block(n, document.commits[key]) for n, key in enumerate(sorted(document.commits), 1)]
    body = f"\n{GROUP_SEP}\n\n".join(blocks)
    return "\n".join([*head, "", SECTION_SEP, "", body, "", f"Branch: `{document.branch}`", ""])


def vendor_names(text: str) -> List[str]:
    """AI vendor names in ``text``, outside verbatim paths (``.claude/``, ``CLAUDE.md`` and similar)."""
    return [match.group(1) for match in _VENDOR.finditer(text)]


def filler_words(text: str) -> List[str]:
    """Filler words in ``text`` (qualities that name no change), outside verbatim paths."""
    return [match.group(1) for match in _FILLER.finditer(text)]


def _commit_message_problems(key: int, commit: CommitEntry) -> List[str]:
    """Problems for one commit: subject rule, vendor names, filler prose."""
    header = commit.header or ""
    text = commit.message or header
    problems: List[str] = []
    if not _HEADER_RULE.match(header):
        problems.append(
            f"commit {key}: subject {header!r} is not '<Type>(<scope>): <subject>' with a valid type"
        )
    problems += [f"commit {key}: vendor name {name!r} in message" for name in vendor_names(text)]
    problems += [f"commit {key}: filler {word!r} - state what changed instead" for word in filler_words(text)]
    if any(line.strip() == GROUP_SEP for line in text.splitlines()):
        problems.append(f"commit {key}: a message line of '{GROUP_SEP}' would split the TXT block; reword it")
    return problems


def message_problems(document: BranchCommitDocument) -> List[str]:
    """Return a problem per subject-rule break, vendor name, or filler word across the document's messages."""
    return [problem for key in sorted(document.commits)
            for problem in _commit_message_problems(key, document.commits[key])]
