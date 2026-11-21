"""The keyword of a TODO item: the one word the working-refs line shows beside its id (plan 2028).

``guess_keyword`` answers only with high confidence: a one-word title prefix (``merge-commit-msg: ...``)
that is not a generic kind such as ``docs`` or ``fix``, else the one file stem that dominates the item's
``files`` (a leading ``test_`` dropped, everything past the first dot ignored, generic stems such as
``SKILL`` or ``README`` skipped), else None. ``fill_keywords`` writes a guess into every item of a catalog
copy that has no keyword and leaves the rest without one; ``apply_keywords`` does it to the project
catalog. ``require_keywords`` refuses a spec item that names no keyword, suggesting the guess when there
is one.
"""
from __future__ import annotations

import copy
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Tuple

from harness_lib.config import HarnessConfig
from harness_lib.todo_sync import TodoSyncError
from harness_lib.todo_sync.retire import dump_like, load_catalog, write_edits

#: The schema's ``keyword`` pattern and length cap.
KEYWORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
KEYWORD_MAX = 32
#: File stems that name no module of their own (compared without case); a stem starting with ``_`` is
#: skipped too.
GENERIC_STEMS = frozenset(s.lower() for s in (
    "SKILL", "README", "CLAUDE", "config", "defaults", "__init__", "conftest", "plugin", "index", "types",
    "hooks"))
#: Title prefixes that name a kind of work, not a subject: the item kind enum plus ``chore`` and ``fix``.
GENERIC_PREFIXES = frozenset(("bug", "feature", "refactor", "test", "cicd", "docs", "skill", "chore",
                              "fix"))
#: A title's one-word prefix: ``<word>: ``.
_PREFIX_RE = re.compile(r"^(\S+): ")
#: What a refusal says when no guess is confident.
NO_GUESS = "no confident guess: name the module, skill or class it is about"


def valid_keyword(value: Any) -> bool:
    """True for a string the schema's ``keyword`` pattern and length cap accept."""
    return isinstance(value, str) and len(value) <= KEYWORD_MAX and bool(KEYWORD_RE.match(value))


def _title_guess(title: Any) -> Optional[str]:
    """The title's one-word prefix when it is a valid keyword and no generic kind."""
    found = _PREFIX_RE.match(title) if isinstance(title, str) else None
    if not found:
        return None
    word = found.group(1)
    if word.lower() in GENERIC_PREFIXES or not valid_keyword(word):
        return None
    return word


def _stem(path: str) -> Optional[str]:
    """A file's name up to its first dot, a leading ``test_`` dropped; None for a generic stem."""
    name = PurePosixPath(path.replace("\\", "/")).name
    stem = name.split(".", 1)[0]
    if stem.startswith("test_"):
        stem = stem[len("test_"):]
    if not stem or stem.startswith("_") or stem.lower() in GENERIC_STEMS:
        return None
    return stem


def _files_guess(files: Any) -> Optional[str]:
    """The one distinct stem, or the stem counted at least twice and more often than any other."""
    if not isinstance(files, list):
        return None
    counts = Counter(s for s in (_stem(f) for f in files if isinstance(f, str)) if s)
    ranked = counts.most_common()
    if not ranked:
        return None
    if len(ranked) == 1:
        return ranked[0][0]
    (top, n), (_, runner) = ranked[0], ranked[1]
    return top if n >= 2 and n > runner else None


def guess_keyword(item: Dict[str, Any]) -> Optional[str]:
    """A high-confidence keyword for ``item`` from its ``title`` prefix, else its ``files``; else None."""
    guess = _title_guess(item.get("title")) or _files_guess(item.get("files"))
    return guess if valid_keyword(guess) else None


def has_keyword(item: Dict[str, Any]) -> bool:
    """True when ``item`` carries a non-blank ``keyword`` string."""
    value = item.get("keyword")
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class KeywordFill:
    """A catalog copy after the keyword fill: ``set`` holds ``(id, keyword)`` per item given a guess and
    ``left`` the ids still without one, both in catalog order."""

    catalog: Dict[str, Any]
    set: Tuple[Tuple[str, str], ...]
    left: Tuple[str, ...]


def _with_keyword(item: Dict[str, Any], keyword: str) -> Dict[str, Any]:
    """``item`` with ``keyword`` placed right after ``title`` (at the end when it has no title)."""
    out: Dict[str, Any] = {}
    for key, value in item.items():
        if key != "keyword":
            out[key] = value
        if key == "title":
            out["keyword"] = keyword
    out.setdefault("keyword", keyword)
    return out


def fill_keywords(catalog: Dict[str, Any]) -> KeywordFill:
    """Give every item of a copy of ``catalog`` that lacks a keyword its confident guess; an item with a
    keyword keeps it, and an item with no guess is left without the key."""
    data = copy.deepcopy(catalog)
    items, done, left = [], [], []
    for item in data.get("items") or []:
        if not isinstance(item, dict) or has_keyword(item):
            items.append(item)
            continue
        item.pop("keyword", None)
        guess = guess_keyword(item)
        if guess is None:
            left.append(str(item.get("id")))
            items.append(item)
            continue
        done.append((str(item.get("id")), guess))
        items.append(_with_keyword(item, guess))
    if "items" in data:
        data["items"] = items
    return KeywordFill(data, tuple(done), tuple(left))


def apply_keywords(cfg: HarnessConfig, dry_run: bool = False) -> KeywordFill:
    """Fill the keywords of the project's catalog; only the catalog is written, and only unless
    ``dry_run``."""
    raw, data = load_catalog(cfg, "keywords")
    out = fill_keywords(data)
    if not dry_run and out.catalog != data:
        write_edits(cfg, dump_like(out.catalog, raw))
    return out


def keyword_lines(fill: KeywordFill, dry_run: bool) -> List[str]:
    """The driver's report: the counts, then one ``set <id>: <keyword>`` line per item given a keyword."""
    verb = "would set" if dry_run else "set"
    lines = [f"keywords: {verb} {len(fill.set)}, left {len(fill.left)} without one"]
    lines.extend(f"set {item_id}: {keyword}" for item_id, keyword in fill.set)
    return lines


def require_keywords(specs: Sequence[Any]) -> None:
    """Refuse the first spec item (an object) whose ``keyword`` is absent or blank, suggesting the
    confident guess when there is one.

    Raises:
        TodoSyncError: ``item <n> lacks keyword (...)``, ``n`` counted from 1.
    """
    for n, spec in enumerate(specs, 1):
        if not isinstance(spec, dict) or has_keyword(spec):
            continue
        guess = guess_keyword(spec)
        hint = f"suggested: {guess}" if guess else NO_GUESS
        raise TodoSyncError(f"item {n} lacks keyword ({hint})")
