"""The freeze ledger: one write-once JSON file per freeze, lock, unlock, arm, reopen or relink.

A subject (a plan or a strap skill) owns a folder ``<plans>/freezes/<stem>/`` where ``<stem>`` is
``plan/<no>-<slug>`` or ``skill/<name>``. Each entry is a file named ``r<N>.<k>-<kind>.json``: ``N`` the
round, ``k`` a sequence that counts across kinds. A file is written once and never rewritten, so the folder
is an append-only history and the subject's state is a pure function of its entries.

``schemas/FreezeLedgerEntry.schema.json`` is ``LedgerEntry.model_json_schema()`` and is never edited by hand.
"""
from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Dict, Iterable, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from harness_lib.plan_enums import RecordScheme

FREEZES_DIR = "freezes"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://github.com/t968rs/operator-straps/plugins/harness/schemas/FreezeLedgerEntry.schema.json"
_SHA40 = r"^[0-9a-f]{40}$"
_SHA64 = r"^[0-9a-f]{64}$"
Sha40 = Annotated[str, Field(pattern=_SHA40)]
Sha64 = Annotated[str, Field(pattern=_SHA64)]


class EntryKind(str, Enum):
    freeze = "freeze"
    lock = "lock"
    unlock = "unlock"
    arm = "arm"
    reopen = "reopen"
    relink = "relink"


class LedgerState(str, Enum):
    none = "none"
    frozen = "frozen"
    locked = "locked"
    armed = "armed"
    unlocked = "unlocked"


_STATE_OF_KIND = {
    EntryKind.freeze: LedgerState.frozen,
    EntryKind.lock: LedgerState.locked,
    EntryKind.arm: LedgerState.armed,
    EntryKind.unlock: LedgerState.unlocked,
}


class LedgerError(Exception):
    """A ledger folder or entry that cannot be written or trusted; ``problems`` lists each cause."""

    def __init__(self, message: str, problems: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.problems: List[str] = list(problems) if problems else [message]


class LedgerEntry(BaseModel):
    # The dialect and id make the generated file self-describing, like every sibling schema: a validator
    # registry that loads the schemas folder needs ``$schema`` to pick the draft.
    model_config = ConfigDict(extra="forbid", regex_engine="python-re",
                              json_schema_extra={"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID})

    kind: EntryKind
    round: int = Field(ge=1)
    seq: int = Field(ge=1)
    tree: Optional[Sha40] = None
    files: Dict[str, Sha40] = Field(default_factory=dict,
                                    description="Repo path to blob SHA of each tree member.")
    ignored: Dict[str, Sha64] = Field(default_factory=dict,
                                      description="Repo path to sha256 of each ignored file.")
    at: str = Field(json_schema_extra={"format": "date-time"})
    base: Optional[Sha40] = None
    history: bool = False
    digest: Optional[Sha64] = None
    records: Optional[RecordScheme] = None
    skill_hash: Optional[Sha64] = None
    grader: Optional[str] = None
    reason: Optional[str] = None
    old_base: Optional[Sha40] = None
    new_base: Optional[Sha40] = None
    match: Optional[Literal["patch-id", "ref"]] = None

    @field_validator("at")
    @classmethod
    def _iso_date_time(cls, value: str) -> str:
        if "T" not in value:
            raise ValueError("must be an ISO 8601 date-time")
        datetime.fromisoformat(value)
        return value


def plan_stem(plan_id: str, slug: str) -> str:
    return f"plan/{plan_id}-{slug}"


def skill_stem(name: str) -> str:
    return f"skill/{name}"


def ledger_dir(plans_dir: Path, stem: str) -> Path:
    return Path(plans_dir) / FREEZES_DIR / Path(*stem.split("/"))


def entry_name(entry: LedgerEntry) -> str:
    return f"r{entry.round}.{entry.seq}-{entry.kind.value}.json"


def entry_text(entry: LedgerEntry) -> str:
    return json.dumps(entry.model_dump(mode="json"), indent=2) + "\n"


def write_entry(folder: Path, entry: LedgerEntry) -> Path:
    """Write ``entry`` to a new file in ``folder``; an existing file is never replaced."""
    path = Path(folder) / entry_name(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(entry_text(entry))
    except FileExistsError:
        raise LedgerError(f"ledger entry {path.name} already exists; entries are written once") from None
    return path


def _read_entry(path: Path) -> LedgerEntry:
    try:
        entry = LedgerEntry.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise LedgerError(f"ledger entry {path.name} is invalid: {exc}") from exc
    if entry_name(entry) != path.name:
        raise LedgerError(f"ledger entry {path.name} holds {entry_name(entry)}; name and content disagree")
    return entry


def load_entries(folder: Path) -> List[LedgerEntry]:
    """Every entry of ``folder`` sorted by (round, seq); ``[]`` when the folder is absent."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    entries = [_read_entry(path) for path in sorted(folder.glob("*.json"))]
    return sorted(entries, key=lambda e: (e.round, e.seq))


def state(entries: Iterable[LedgerEntry]) -> LedgerState:
    """The state after the highest entry; ``reopen`` and ``relink`` leave the state before them."""
    current = LedgerState.none
    for entry in sorted(entries, key=lambda e: (e.round, e.seq)):
        current = _STATE_OF_KIND.get(entry.kind, current)
    return current


def last_freeze(entries: Iterable[LedgerEntry]) -> Optional[LedgerEntry]:
    return _last_of_kind(entries, EntryKind.freeze)


def _last_of_kind(entries: Iterable[LedgerEntry], kind: EntryKind) -> Optional[LedgerEntry]:
    found = [e for e in entries if e.kind == kind]
    return max(found, key=lambda e: (e.round, e.seq)) if found else None


def held(entries: Iterable[LedgerEntry], kind: EntryKind) -> Optional[LedgerEntry]:
    """The entry holding the files the last ``kind`` entry fixed: a later ``relink`` that re-recorded them
    (its ``files`` set), else that entry; None without a ``kind`` entry."""
    ordered = sorted(entries, key=lambda e: (e.round, e.seq))
    anchor = _last_of_kind(ordered, kind)
    if anchor is None:
        return None
    later = [e for e in ordered if e.kind == EntryKind.relink and e.files
             and (e.round, e.seq) > (anchor.round, anchor.seq)]
    return later[-1] if later else anchor


def next_seq(entries: Iterable[LedgerEntry], round_: int, taken: Iterable[int]) -> int:
    """One past the highest ``k`` of ``round_`` among ``entries`` and the tag sequences in ``taken``."""
    seqs = [e.seq for e in entries if e.round == round_]
    return max(seqs + list(taken), default=0) + 1


def current_round(entries: Iterable[LedgerEntry]) -> int:
    return max((e.round for e in entries), default=1)


def locked_files(entries: Iterable[LedgerEntry], plans_rel: str) -> List[str]:
    """Files and ignored keys of the last lock entry under ``plans_rel``; empty unless locked or armed.

    A lock binds only its own round: a ``reopen`` starts the next round, which releases it.
    """
    entries = list(entries)
    if state(entries) not in (LedgerState.locked, LedgerState.armed):
        return []
    lock = _last_of_kind(entries, EntryKind.lock)
    if lock is None or lock.round != current_round(entries):
        return []
    prefix = plans_rel.strip("/") + "/"
    return sorted(p for p in {**lock.files, **lock.ignored} if p.startswith(prefix))


def schema_text() -> str:
    """The text of ``FreezeLedgerEntry.schema.json``: the model schema with ``$schema`` and ``$id`` first."""
    body = LedgerEntry.model_json_schema()
    head = {key: body.pop(key) for key in ("$schema", "$id")}
    return json.dumps({**head, **body}, indent=2) + "\n"
