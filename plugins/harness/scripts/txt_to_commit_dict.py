"""Parse branch-commit-msg commit-message TXT files and emit PowerShell commit drivers.

Inverse of the ``branch-commit-msg`` skill output saved in the project's configured
``commit_messages`` directory (default ``docs/_commit_messages``). The TXT grammar lives in
``harness_lib.commit_txt``; ``Bucket`` and ``BranchCommitDocument`` live in
``harness_lib.branch_commits`` and are re-exported here.

``txt_to_commit_dict`` parses one file into a ``BranchCommitDocument`` (``branch``, ``merge_base``,
``notes``, and ``commits`` keyed by commit number), validated on construction. Each commit entry
carries: ``index``, ``bucket`` (a ``Bucket``), ``file_count`` (recounted from ``files``), ``tag``
(bracketed annotation or None), ``files``, ``type``, ``scope``, ``subject``, ``header`` (the full
subject line), ``message`` (verbatim, footer removed), ``body``, ``bullets`` (list of
``{"file", "change"}``), and ``branch``.

Default CLI behavior iterates every digit-prefixed ``*.txt`` in that directory and writes a sibling
``<stem>.ps1`` holding a ``$commitDict`` for ``commitFactory.ps1``. A file that fails validation, or
whose message holds a double quote, is reported on stderr and skipped (exit 1); the double-quote skip
applies in ``--json`` mode too. Pass an explicit target to process a single file; pass ``--json`` to
dump the parsed document instead. The project is the git top level of ``--repo``
(default: the working directory)::

    txt_to_commit_dict.py                         # batch -> .ps1
    txt_to_commit_dict.py 1234-feature-branch
    txt_to_commit_dict.py 1234-feature-branch --json
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Union

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from harness_lib.branch_commits import BranchCommitDocument, Bucket, CommitEntry
from harness_lib.commit_txt import quote_problems, read_commit_txt
from harness_lib.config import ConfigError, activate, active, load_config
from harness_lib.project import project_root

__all__ = ["BranchCommitDocument", "Bucket", "document_to_ps1", "parse_all", "txt_to_commit_dict"]

_DIGIT_TXT_GLOB = "[0-9]*.txt"


def commit_messages_dir() -> Path:
    """Return the active project's ``artifacts.commit_messages`` directory (absolute)."""
    cfg = active()
    return cfg.path(cfg.artifacts.commit_messages)


def iter_commit_txts(folder: Optional[Path] = None) -> Iterator[Path]:
    """Yield digit-prefixed ``*.txt`` files in ``folder`` (sorted by name)."""
    target = folder if folder is not None else commit_messages_dir()
    yield from sorted(target.glob(_DIGIT_TXT_GLOB))


def txt_to_commit_dict(path: Union[str, Path], one_path_per_commit: bool = True) -> BranchCommitDocument:
    """Parse a branch-commit-msg TXT file at ``path`` into a ``BranchCommitDocument``.

    Raises ``ValueError`` when a bucket label is unknown, or when ``one_path_per_commit``
    is set and a path appears in more than one commit block.
    """
    return read_commit_txt(path, one_path_per_commit)


def parse_all(folder: Optional[Path] = None) -> Dict[str, BranchCommitDocument]:
    """Parse every digit-prefixed TXT in ``folder``, keyed by file stem."""
    return {path.stem: txt_to_commit_dict(path) for path in iter_commit_txts(folder)}


def _compose_header(commit: CommitEntry) -> str:
    """Rebuild a ``type(scope): subject`` line when the parsed header is absent."""
    type_ = commit.commit_type or "Chore"
    prefix = f"{type_}({commit.scope})" if commit.scope else f"{type_}"
    return f"{prefix}: {commit.subject or ''}".rstrip()


def _reconstruct_message(commit: CommitEntry, fallback_branch: Optional[str]) -> str:
    """Return the verbatim commit message (or the subject line) plus a ``Branch:`` footer."""
    message = commit.message or commit.header or _compose_header(commit)
    branch = commit.branch or fallback_branch
    return f"{message}\n\nBranch: `{branch}`" if branch else message


def _ps_squote(value: str) -> str:
    """Single-quote a value for PowerShell, doubling embedded single quotes."""
    return "'" + value.replace("'", "''") + "'"


def _commit_entry_ps1(commit: CommitEntry, fallback_branch: Optional[str]) -> List[str]:
    """Render one commit as a keyed entry (``<index> = @{...}``) in ``$commitDict``."""
    header = commit.header or _compose_header(commit)
    tag, files = commit.tag, commit.files

    lines: List[str] = [f"    {commit.index} = [ordered]@{{"]
    lines.append(f"        Tag     = {_ps_squote(tag) if tag else '$null'}")
    lines.append(f"        Header  = {_ps_squote(header)}")
    if files:
        lines.append("        Files   = @(")
        for path in files:
            lines.append(f"            {_ps_squote(path)}")
        lines.append("        )")
    else:
        lines.append("        Files   = @()")
    # A here-string closing delimiter must sit at column 0, so Message breaks the
    # hashtable indentation; PowerShell accepts this.
    lines.append("        Message = @'")
    lines.append(_reconstruct_message(commit, fallback_branch))
    lines.append("'@")
    lines.append("    }")
    return lines


def document_to_ps1(document: BranchCommitDocument, stem: str = "") -> str:
    """Render a parsed document as a PowerShell ``$commitDict`` ordered dictionary.

    ``commitFactory.ps1`` (``GitADict``) consumes the dictionary after the branch is reset to its
    merge base: per commit it runs ``git add -A -- <path>`` for each listed path, then
    ``git commit -m <message> -- <paths>``. Every message carries a ``Branch:`` footer.
    """
    ordered = [document.commits[key] for key in sorted(document.commits)]
    body: List[str] = []
    for commit in ordered:
        body.extend(_commit_entry_ps1(commit, document.branch))
    return "\n".join(["$commitDict = [ordered]@{", *body, "}", ""]).rstrip() + "\n"


def write_ps1(input_path: Union[str, Path], document: BranchCommitDocument) -> Path:
    """Write the PowerShell driver beside the input as ``<stem>.ps1``; return it."""
    src = Path(input_path)
    out_path = src.parent / f"{src.stem}.ps1"
    out_path.write_text(document_to_ps1(document, stem=src.stem), encoding="utf-8")
    return out_path


def _resolve_path(arg: str) -> Path:
    """Accept a direct path or a bare branch name resolved against the folder."""
    candidate = Path(arg)
    if candidate.suffix == ".txt" or candidate.exists():
        return candidate
    return commit_messages_dir() / f"{arg}.txt"


def _jsonable(document: BranchCommitDocument) -> Dict[str, object]:
    """Convert to a dict with stringified commit keys so the document serializes to valid JSON."""
    data = dataclasses.asdict(document)
    data["commits"] = {str(k): v for k, v in sorted(data["commits"].items())}
    return data


def _load_or_report(path: Path) -> Optional[BranchCommitDocument]:
    """Parse ``path``; on a validation failure, report it to stderr and return None."""
    try:
        document = txt_to_commit_dict(path)
    except ValueError as exc:
        sys.stderr.write(f"skipped {path.name}: {exc}\n")
        return None
    problems = quote_problems(document)
    if problems:
        sys.stderr.write(f"skipped {path.name}: {'; '.join(problems)}\n")
        return None
    return document


def _targets(arg: Optional[str]) -> List[Path]:
    """Resolve CLI arg to a list of input TXT paths (batch when omitted)."""
    if arg is None:
        return list(iter_commit_txts())
    path = _resolve_path(arg)
    return [path] if path.exists() else []


def _parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="txt_to_commit_dict.py",
        description="Parse branch-commit-msg commit-message TXT files and emit PowerShell commit drivers.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="Path to a .txt file, or a bare branch name. Omit to batch all "
             "digit-prefixed *.txt in the project's commit_messages directory.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the parsed document as JSON to stdout instead of writing .ps1 files.",
    )
    parser.add_argument("--indent", type=int, default=2, help="JSON indent (default: 2).")
    parser.add_argument(
        "--repo", type=Path, default=None,
        help="Directory inside the project (default: the working directory); its git top level is used.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Write a ``<stem>.ps1`` beside each input TXT (or dump JSON). Return 0/1."""
    args = _parser().parse_args(argv)
    try:
        activate(load_config(project_root(args.repo)))
    except ConfigError as exc:
        sys.stderr.write(f"problem: {exc}\n")
        return 1

    # Keep non-ASCII (em dash, etc.) intact when redirecting on a cp1252 console.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    paths = _targets(args.target)
    if not paths:
        where = args.target if args.target else f"digit-prefixed *.txt in {commit_messages_dir()}"
        sys.stderr.write(f"nothing to parse: {where}\n")
        return 1

    loaded = {path: _load_or_report(path) for path in paths}
    documents = {path: doc for path, doc in loaded.items() if doc is not None}
    exit_code = 0 if len(documents) == len(loaded) else 1

    if args.json:
        dumped = {path.stem: _jsonable(doc) for path, doc in documents.items()}
        payload = next(iter(dumped.values()), None) if args.target else dumped
        print(json.dumps(payload, indent=args.indent, ensure_ascii=False))
        return exit_code

    for path, document in documents.items():
        print(f"wrote {write_ps1(path, document)}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
