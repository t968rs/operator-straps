"""Stable TODO item ids (``todo-k7qf``): the format, the generator, resolution of typed ids, the legacy guard.

An id is ``PREFIX`` plus ``CODE_LENGTH`` characters of ``ALPHABET`` holding at least one digit and one
letter. It carries no rank, so structural edits never rename it. Rank-tied ``TODO-NNN`` ids are parsed
only to point at ``migrate-ids`` and at the stored ``legacy_ids`` map.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any, Container, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from harness_lib.todo_sync.errors import TodoSyncError

PREFIX = "todo-"
ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
CODE_LENGTH = 4
_DIGITS = "".join(c for c in ALPHABET if c.isdigit())
_LETTERS = "".join(c for c in ALPHABET if c.isalpha())
_WITHIN = f"[{ALPHABET}]{{0,{CODE_LENGTH - 1}}}"
ID_RE = re.compile(rf"\b{PREFIX}(?={_WITHIN}[{_DIGITS}])(?={_WITHIN}[{_LETTERS}])"
                   rf"[{ALPHABET}]{{{CODE_LENGTH}}}\b")
LEGACY_RE = re.compile(r"\bTODO-[0-9]{3,}\b")
MIGRATE_HINT = ("the catalog still uses rank-tied TODO-NNN ids; run todo_sync.py migrate-ids --dry-run, "
                "then without --dry-run")
_LEGACY_RAW = re.compile(r"(?i)(?:TODO-)?0*([1-9][0-9]*)")
_SEPARATORS = re.compile(r"[,;\s]+")


def is_id(text: Any) -> bool:
    """True when ``text`` is exactly one stable id (lower case, as stored)."""
    return isinstance(text, str) and ID_RE.fullmatch(text) is not None


def _strings(value: Any) -> List[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Catalog items whose ``id`` is a string."""
    items = catalog.get("items")
    return [i for i in items if isinstance(i, dict) and isinstance(i.get("id"), str)] \
        if isinstance(items, list) else []


def is_legacy(catalog: Dict[str, Any]) -> bool:
    """True when any item id is a rank-tied ``TODO-NNN`` id."""
    return any(LEGACY_RE.fullmatch(i["id"]) for i in _items(catalog))


def _recorded_ids(catalog: Dict[str, Any]) -> Set[str]:
    """Ids the ``legacy_ids`` map and ``split_ids`` record: map values, split originals and their parts."""
    legacy = _dict(_dict(catalog.get("legacy_ids")).get("map"))
    split = _dict(catalog.get("split_ids"))
    parts = {p for value in split.values() for p in _strings(value)}
    return {v for v in legacy.values() if isinstance(v, str)} | set(split) | parts


def taken_ids(catalog: Dict[str, Any]) -> Set[str]:
    """Ids a new draw must skip: live item ids, ``retired_ids`` and every id the id records name.

    An item deleted by hand leaves its id in ``legacy_ids`` or ``split_ids``; skipping those keeps a recorded
    id from naming a new, unrelated item.
    """
    live = {i["id"] for i in _items(catalog)}
    return live | set(_strings(catalog.get("retired_ids"))) | _recorded_ids(catalog)


def new_id(taken: Container[str], rng: Optional[random.Random] = None) -> str:
    """A fresh id drawn from ``rng`` (default ``random.SystemRandom()``), redrawn until valid and free."""
    draw = rng if rng is not None else random.SystemRandom()
    while True:
        code = PREFIX + "".join(draw.choice(ALPHABET) for _ in range(CODE_LENGTH))
        if is_id(code) and code not in taken:
            return code


def _clean(raw: str) -> str:
    """``raw`` without surrounding whitespace and one trailing ``,`` or ``;``."""
    text = raw.strip()
    return text[:-1] if text[-1:] in (",", ";") else text


def canonical(raw: str) -> Optional[str]:
    """``todo-k7qf`` from ``TODO-K7QF``, ``k7qf`` or ``k7qf,``; None when ``raw`` names no stable id."""
    text = _clean(raw).lower()
    text = text if text.startswith(PREFIX) else PREFIX + text
    return text if is_id(text) else None


def mentions(text: str, ids: Iterable[str]) -> List[str]:
    """The ``ids``, in their order, that ``text`` names in any case on word bounds."""
    return [i for i in ids if re.search(rf"\b{re.escape(i)}\b", text, re.IGNORECASE)]


def require_stable(catalog: Dict[str, Any], verb: str) -> None:
    """Refuse ``verb`` on a catalog that still holds ``TODO-NNN`` ids.

    Raises:
        TodoSyncError: ``'<verb>: <MIGRATE_HINT>'``.
    """
    if is_legacy(catalog):
        raise TodoSyncError(f"{verb}: {MIGRATE_HINT}")


@dataclass(frozen=True)
class _Lookup:
    """What resolution consults: live titles, retired ids, split parts, the legacy map and its date."""

    titles: Dict[str, str]
    retired: FrozenSet[str]
    split: Dict[str, Any]
    legacy: Dict[str, Any]
    migrated: str


def _lookup(catalog: Dict[str, Any]) -> _Lookup:
    legacy = _dict(catalog.get("legacy_ids"))
    return _Lookup({i["id"]: str(i.get("title") or "") for i in _items(catalog)},
                   frozenset(_strings(catalog.get("retired_ids"))), _dict(catalog.get("split_ids")),
                   _dict(legacy.get("map")), str(legacy.get("migrated") or "an unrecorded date"))


def _legacy_id(raw: str) -> Optional[str]:
    """``TODO-007`` when ``raw`` reads as a rank-tied id (``TODO-007``, ``007`` or ``7``), else None."""
    match = _LEGACY_RAW.fullmatch(_clean(raw))
    return f"TODO-{int(match.group(1)):03d}" if match else None


def _legacy_note(old: str, look: _Lookup) -> str:
    """The problem line for a rank-tied id: what the stored map says it meant, or that it holds no entry."""
    head = f"{old} is a rank-tied id from before migrate-ids: "
    new = look.legacy.get(old)
    if not isinstance(new, str):
        return head + "no legacy_ids entry"
    what = look.titles[new] if new in look.titles else (
        "retired" if new in look.retired else "not in the catalog")
    return head + f"it meant {new} ({what}) as of {look.migrated}; older references may name another item"


def _triage(raw: str, look: _Lookup) -> Tuple[str, str]:
    """``(kind, text)`` for one raw id; kind is ``ok``, ``note``, ``unknown`` or ``malformed``."""
    code = canonical(raw)
    if code is None:
        old = _legacy_id(raw)
        return ("note", _legacy_note(old, look)) if old else ("malformed", repr(raw))
    if code in look.titles:
        return "ok", code
    if code in look.split:
        return "note", f"{code} was split into {', '.join(_strings(look.split[code]))}"
    if code in look.retired:
        return "note", f"{code} was retired"
    return "unknown", code


def _problems(by_kind: Dict[str, List[str]]) -> List[str]:
    """Per-id notes in input order, then the unknown ids and the malformed raws, one line each."""
    problems = list(by_kind["note"])
    if by_kind["unknown"]:
        problems.append(f"no such item(s) in the catalog: {', '.join(by_kind['unknown'])}")
    if by_kind["malformed"]:
        problems.append(f"not a TODO id: {', '.join(by_kind['malformed'])} (use todo-k7qf or k7qf)")
    return problems


def _pieces(raws: Iterable[str]) -> List[str]:
    """Each raw split at commas, semicolons and whitespace, empty pieces dropped (``k7qf,2a2a``: two ids)."""
    return [piece for raw in raws for piece in _SEPARATORS.split(raw) if piece]


def resolve_ids(catalog: Dict[str, Any], raws: Iterable[str]) -> List[str]:
    """The live ids ``raws`` name, canonical, in input order without repeats.

    A raw holding several ids joined by ``,``, ``;`` or whitespace counts as each of them.

    Raises:
        TodoSyncError: one message joining every problem with ``'; '``.
    """
    raws = _pieces(raws)
    if not raws:
        raise TodoSyncError("name at least one TODO id")
    look, by_kind = _lookup(catalog), {"ok": [], "note": [], "unknown": [], "malformed": []}
    for raw in raws:
        kind, text = _triage(raw, look)
        if text not in by_kind[kind]:
            by_kind[kind].append(text)
    problems = _problems(by_kind)
    if problems:
        raise TodoSyncError("; ".join(problems))
    return by_kind["ok"]
