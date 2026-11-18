"""Keep the session notes the session-bookmark mod prints in its compaction bookmark.

Usage: add_note.py [--repo PATH] add TEXT... | list | clear

The notes live in ``<state_dir>/session-bookmark/notes.json`` under the project root: ``{"version": 1,
"notes": [{"added": "<UTC ISO 8601>", "text": "..."}]}``. A note stays until ``clear``. The mod reads the file
at every compaction; ``tests/mods/test_session_bookmark_notes_contract.py`` pins the names both sides share.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

NOTES_REL = "session-bookmark/notes.json"
NOTES_VERSION = 1
MAX_NOTES = 20
MAX_NOTE_CHARS = 300

Note = Dict[str, str]


class NoteError(RuntimeError):
    """A note the script refuses to store."""


def notes_path(repo: Path) -> Path:
    """The notes file of the project holding ``repo``; raises ``ConfigError`` for an unreadable config."""
    from harness_lib.config import activate, load_config
    from harness_lib.project import project_root
    cfg = activate(load_config(project_root(repo)))
    return cfg.path(cfg.state_dir) / NOTES_REL


def _usable(entry: object) -> bool:
    """Whether an entry holds a non-blank text, the rule the mod's ``parseNotes`` applies."""
    return isinstance(entry, dict) and isinstance(entry.get("text"), str) and bool(entry["text"].strip())


def _is_current(version: object) -> bool:
    """Whether a file's ``version`` is ``NOTES_VERSION``; a JSON boolean never is."""
    return not isinstance(version, bool) and version == NOTES_VERSION


def read_notes(path: Path) -> List[Note]:
    """The stored notes with a non-blank text, oldest first; an absent file holds none.

    Mirrors the mod's ``parseNotes``: a bad entry is skipped, not fatal. A file that is not JSON, holds no
    ``notes`` list or carries another version raises ``NoteError``, so ``add`` never overwrites it and
    ``list`` never reports it as empty; ``clear`` is the explicit reset.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except ValueError as exc:
        raise NoteError(f"{path} is not JSON; run clear to reset it") from exc
    if not isinstance(data, dict) or not isinstance(data.get("notes"), list):
        raise NoteError(f"{path} holds no notes list; run clear to reset it")
    if not _is_current(data.get("version")):
        raise NoteError(f"{path} is not a version {NOTES_VERSION} notes file; run clear to reset it")
    return [n for n in data["notes"] if _usable(n)]


def write_notes(path: Path, notes: List[Note]) -> None:
    """Write the file through a sibling temp file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"version": NOTES_VERSION, "notes": notes}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def checked_text(words: List[str], stored: int) -> str:
    """The note text, or ``NoteError`` when it is blank, too long, or the file is full."""
    text = " ".join(" ".join(words).split())
    if not text:
        raise NoteError("note is blank")
    if len(text) > MAX_NOTE_CHARS:
        raise NoteError(f"note is {len(text)} characters; the limit is {MAX_NOTE_CHARS}")
    if stored >= MAX_NOTES:
        raise NoteError(f"{MAX_NOTES} notes are stored; run clear first")
    return text


def add(path: Path, words: List[str]) -> str:
    notes = read_notes(path)
    text = checked_text(words, len(notes))
    added = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_notes(path, [*notes, {"added": added, "text": text}])
    return f"note {len(notes) + 1}/{MAX_NOTES}: {text}"


def listing(path: Path) -> str:
    notes = read_notes(path)
    return "\n".join(f"{i}. {n['text']}" for i, n in enumerate(notes, 1)) or "no notes"


def clear(path: Path) -> str:
    """Empty the file; an unreadable one is reset rather than refused."""
    try:
        count = len(read_notes(path))
    except NoteError:
        write_notes(path, [])
        return "reset a notes file that could not be read"
    write_notes(path, [])
    return f"cleared {count} note{'' if count == 1 else 's'}"


def parse_args(argv: Optional[list]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="project to write under (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("add", help="store one note").add_argument("text", nargs="+")
    sub.add_parser("list", help="print the stored notes")
    sub.add_parser("clear", help="drop every stored note")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> str:
    path = notes_path(args.repo)
    if args.command == "add":
        return add(path, args.text)
    return listing(path) if args.command == "list" else clear(path)


def main(argv: Optional[list] = None) -> int:
    from harness_lib.config import ConfigError
    try:
        print(run(parse_args(argv)))
    except (NoteError, ConfigError, OSError) as exc:
        print(f"add_note: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
