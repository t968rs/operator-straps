"""Keep the session notes the session-bookmark mod prints in its compaction bookmark.

Usage: add_note.py [--repo PATH] add [--standing] TEXT... | list | remove N... | edit N TEXT... | clear
       | goal TEXT... | goal --todo ID --closed-by retired|committed|developer | goal --clear

The notes live in ``<state_dir>/session-bookmark/notes.json`` under the project root: ``{"version": 1,
"notes": [{"added": "<UTC ISO 8601>", "branch": "<name>", "text": "..."}]}``. ``add`` records the checked-out
branch; the key is left out under ``--standing`` and on a detached HEAD, and a note without a usable branch
applies on every branch. ``list`` marks a note added on another branch as ``[<branch>; now on <current>]``.
``remove`` and ``edit`` address a note by its ``list`` number; ``remove`` takes several, all numbered from
one listing. A note stays until ``remove`` or ``clear``. The mod reads the file at every compaction;
``tests/mods/test_session_bookmark_notes_contract.py`` pins the names both sides share.

``goal`` arms the mod's hook switch (``<state_dir>/session-bookmark/hook.json``, written through
``harness_lib.add_todo_api``): the mod runs ``/goal <goal>`` when the current main-loop turn ends. The switch
records the arming session (``CLAUDE_CODE_SESSION_ID``), so only that session fires it. The goal is
free text, or a TODO catalog item with its closing (``--todo``, ``--closed-by``); ``goal --clear`` removes
the switch. A goal already set ends with ``/goal clear``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from harness_lib.add_todo_models import MAX_GOAL_CHARS, Closing  # noqa: E402

CLOSINGS = [member.value for member in Closing]

NOTES_REL = "session-bookmark/notes.json"
NOTES_VERSION = 1
BRANCH_KEY = "branch"
OTHER_BRANCH_MARK = "now on"
MAX_NOTES = 20
MAX_NOTE_CHARS = 300

Note = Dict[str, str]


class NoteError(RuntimeError):
    """A note the script refuses to store."""


def _config(repo: Path) -> Any:
    """The active config of the project holding ``repo``; raises ``ConfigError`` for an unreadable config."""
    from harness_lib.config import activate, load_config
    from harness_lib.project import project_root
    return activate(load_config(project_root(repo)))


def notes_path(repo: Path) -> Path:
    """The notes file of the project holding ``repo``; raises ``ConfigError`` for an unreadable config."""
    cfg = _config(repo)
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
        raise NoteError(f"{MAX_NOTES} notes are stored; run remove N or clear first")
    return text


def _git_name(repo: Path, *args: str) -> Optional[str]:
    """The stripped stdout of ``git -C repo ARGS``; ``None`` on a failure, a timeout or empty output."""
    from harness_lib.project import run_git
    try:
        done = run_git(["git", "-C", str(repo), *args])
    except OSError:
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def current_branch(repo: Path) -> Optional[str]:
    """The checked-out branch of ``repo``; ``None`` for a detached HEAD or when git cannot say.

    An unborn branch (no commit yet) fails ``rev-parse``, so ``symbolic-ref`` answers for it; on a detached
    HEAD ``rev-parse`` prints ``HEAD``, which reads as ``None``.
    """
    name = _git_name(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if name is None:
        name = _git_name(repo, "symbolic-ref", "--short", "HEAD")
    return None if name in (None, "HEAD") else name


def _note_branch(note: Note) -> Optional[str]:
    """The note's branch; ``None`` for a note without a usable one (absent, not text, or blank)."""
    branch = note.get(BRANCH_KEY)
    return branch.strip() if isinstance(branch, str) and branch.strip() else None


def note_body(note: Note, current: Optional[str]) -> str:
    """The note as printed: bare for a standing note, branch-tagged otherwise, marked when elsewhere."""
    branch = _note_branch(note)
    if branch is None:
        return note["text"]
    if current is None or branch == current:
        return f"[{branch}] {note['text']}"
    return f"[{branch}; {OTHER_BRANCH_MARK} {current}] {note['text']}"


def note_line(number: int, note: Note, current: Optional[str]) -> str:
    return f"{number}. {note_body(note, current)}"


def add(path: Path, words: List[str], branch: Optional[str]) -> str:
    notes = read_notes(path)
    text = checked_text(words, len(notes))
    added = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    note: Note = {"added": added, "text": text}
    if branch is not None:
        note = {"added": added, BRANCH_KEY: branch, "text": text}
    write_notes(path, [*notes, note])
    return f"note {len(notes) + 1}/{MAX_NOTES}: {note_body(note, branch)}"


def listing(path: Path, current: Optional[str]) -> str:
    notes = read_notes(path)
    return "\n".join(note_line(i, n, current) for i, n in enumerate(notes, 1)) or "no notes"


def _pick(notes: List[Note], number: int) -> Note:
    """The note at the 1-based ``number``, or ``NoteError`` when none is stored there."""
    if not 1 <= number <= len(notes):
        raise NoteError(f"no note {number}; {len(notes)} stored")
    return notes[number - 1]


def remove(path: Path, numbers: List[int], current: Optional[str]) -> str:
    """Drop the notes at ``numbers``, all read against one listing; one missing number drops none."""
    notes = read_notes(path)
    picked = sorted(set(numbers))
    gone = [_pick(notes, number) for number in picked]
    write_notes(path, [n for n in notes if not any(n is g for g in gone)])
    lines = [f"removed note {number}: {note_body(note, current)}" for number, note in zip(picked, gone)]
    return "\n".join([*lines, listing(path, current)])


def edit(path: Path, number: int, words: List[str], current: Optional[str]) -> str:
    """Replace the text of one note; ``added`` and the branch stay."""
    notes = read_notes(path)
    old = _pick(notes, number)
    new: Note = {**old, "text": checked_text(words, 0)}
    write_notes(path, [new if n is old else n for n in notes])
    return f"edited note {number}: {note_body(new, current)}\n{listing(path, current)}"


def clear(path: Path) -> str:
    """Empty the file; an unreadable one is reset rather than refused."""
    try:
        count = len(read_notes(path))
    except NoteError:
        write_notes(path, [])
        return "reset a notes file that could not be read"
    write_notes(path, [])
    return f"cleared {count} note{'' if count == 1 else 's'}"


def _goal_text(words: List[str]) -> str:
    """The free-text goal, or ``NoteError`` when it is blank or longer than ``/goal`` takes.

    The length counts code points, the unit ``TodoHook.goal`` and the mod's ``Array.from`` cut both use.
    """
    text = " ".join(" ".join(words).split())
    if not text:
        raise NoteError("goal is blank")
    if len(text) > MAX_GOAL_CHARS:
        raise NoteError(f"goal is {len(text)} characters; the limit is {MAX_GOAL_CHARS}")
    return text


def _goal_catalog(cfg: Any) -> Dict[str, Any]:
    """The TODO catalog, refused like ``add_todo.py hook``: no TODO folder, no catalog, or rank-tied ids."""
    from harness_lib.todo_sync import ids
    from harness_lib.todo_sync.errors import TodoSyncError
    if not cfg.todo.enabled or cfg.todo.catalog is None:
        raise NoteError("goal --todo needs todo.folder in .claude/harness.json")
    catalog = cfg.path(cfg.todo.catalog)
    if not catalog.is_file():
        raise NoteError(f"no TODO catalog at {cfg.todo.catalog}; create it with todo_sync.py init")
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise NoteError(f"the TODO catalog at {cfg.todo.catalog} cannot be read") from None
    if not isinstance(data, dict):
        raise NoteError(f"the TODO catalog at {cfg.todo.catalog} is not a JSON object")
    try:
        ids.require_stable(data, "bookmark goal")
    except TodoSyncError as exc:
        raise NoteError(str(exc)) from exc
    return data


def _todo_goal(cfg: Any, todo_id: str, closed_by: str) -> Any:
    """The ``TodoHook`` for a catalog item; ``NoteError`` for a refused catalog or an unknown id."""
    from harness_lib.add_todo_api import catalog_item, todo_hook
    item = catalog_item(_goal_catalog(cfg), todo_id)
    if item is None:
        raise NoteError(f"no catalog item {todo_id}")
    return todo_hook(Closing(closed_by), item)


def _clear_goal(path: Path) -> str:
    if not path.is_file():
        return "goal: none"
    path.unlink()
    return "goal: cleared"


def goal(cfg: Any, args: argparse.Namespace) -> str:
    """Arm the hook switch with a free-text goal or a catalog item's goal, or clear it."""
    from harness_lib.add_todo_api import HOOK_REL, arming_session, write_goal_switch, write_hook_switch
    path = cfg.path(cfg.state_dir) / HOOK_REL
    session = arming_session(os.environ)
    if args.clear:
        if args.text or args.todo is not None or args.closed_by is not None:
            raise NoteError("goal --clear takes no text, --todo or --closed-by")
        return _clear_goal(path)
    if args.todo is None:
        if args.closed_by is not None:
            raise NoteError("--closed-by needs --todo ID")
        text = _goal_text(args.text)
        write_goal_switch(path, text, time.time(), session)
        return f"goal armed: {text}"
    if args.text:
        raise NoteError("goal takes text or --todo ID, not both")
    if args.closed_by is None:
        raise NoteError(f"goal --todo needs --closed-by {'|'.join(CLOSINGS)}")
    hook = _todo_goal(cfg, args.todo, args.closed_by)
    write_hook_switch(path, hook, session)
    return f"goal armed for {hook.todo_id} ({hook.closed_by.value}): {hook.goal()}"


def _goal_parser(sub: Any) -> None:
    goal_cmd = sub.add_parser("goal", help="arm the session-bookmark hook switch with a /goal")
    goal_cmd.add_argument("--todo", help="a TODO catalog id the goal names")
    goal_cmd.add_argument("--closed-by", choices=CLOSINGS,
                          help="what closes a --todo goal")
    goal_cmd.add_argument("--clear", action="store_true", help="remove the switch")
    goal_cmd.add_argument("text", nargs="*")


def parse_args(argv: Optional[list]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="project to write under (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)
    add_cmd = sub.add_parser("add", help="store one note on the current branch")
    add_cmd.add_argument("--standing", action="store_true", help="store the note with no branch")
    add_cmd.add_argument("text", nargs="+")
    sub.add_parser("list", help="print the stored notes, numbered")
    remove_cmd = sub.add_parser("remove", help="drop notes by their listed numbers")
    remove_cmd.add_argument("numbers", type=int, nargs="+")
    edit_cmd = sub.add_parser("edit", help="replace the text of one note by its listed number")
    edit_cmd.add_argument("number", type=int)
    edit_cmd.add_argument("text", nargs="+")
    sub.add_parser("clear", help="drop every stored note")
    _goal_parser(sub)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> str:
    if args.command == "goal":
        return goal(_config(args.repo), args)
    path = notes_path(args.repo)
    if args.command == "clear":
        return clear(path)
    if args.command == "add" and args.standing:
        return add(path, args.text, None)
    current = current_branch(args.repo)
    if args.command == "add":
        return add(path, args.text, current)
    if args.command == "remove":
        return remove(path, args.numbers, current)
    if args.command == "edit":
        return edit(path, args.number, args.text, current)
    return listing(path, current)


def main(argv: Optional[list] = None) -> int:
    from harness_lib.config import ConfigError
    try:
        print(run(parse_args(argv)))
    except (NoteError, ConfigError, OSError, ValueError) as exc:
        print(f"add_note: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
