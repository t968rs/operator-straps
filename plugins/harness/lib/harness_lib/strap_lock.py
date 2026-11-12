"""Freeze ledger entries, tree tags and the Locked state of a strap ``SkillSpec`` (plan 1015).

Asymmetric: ``SkillSpec.json`` keeps ``frozen``, ``rounds`` and the ``authored`` seal; the ledger under
``<artifacts.plans>/freezes/skill/<name>/`` records each freeze tree, lock, reopen and relink. Locked is
read from the ledger alone: the state of the entries of the spec's current round (``len(rounds) + 1``) is
Locked, a ``lock`` optionally followed by ``relink`` entries.

A command works out a ``Pending`` (the entries it will write and the tags it will create) before it writes
anything, preflights every tag name, and only then saves the spec and calls ``commit``. Inside a scenario
tree (``freeze_git.SCENARIO_MARKER`` at the project root) entries are still written, but no tag is created
and nothing is reconciled. This module never saves a spec; ``strap.py`` does, and hands ``commit`` the
spec's earlier bytes to put back when an entry write fails. Requires an activated config.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import os
import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from harness_lib import freeze_git as fg
from harness_lib import freeze_ledger as fl
from harness_lib.branch_capture import git
from harness_lib.config import active
from harness_lib.freeze_ledger import EntryKind, LedgerEntry
from harness_lib.strap_models import SPEC_FILE, Frozen, SkillSpec

LOCKED = "{name} is locked; reopen to change it"
LEGACY = "legacy: {name} has no ledger; one starts at its next freeze --refreeze, reopen or relink"
SET_DIRS = ("tests", "fixtures")
FALLBACK_TAGGER = {"GIT_COMMITTER_NAME": "strap", "GIT_COMMITTER_EMAIL": "strap@localhost"}


class LockRefused(ValueError):
    """A refusal from the ledger or its tags; ``problems`` holds one line per defect."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = list(problems)


@dataclasses.dataclass
class Pending:
    """The entries a command writes and the tags it creates (name to target and message)."""

    name: str
    entries: List[LedgerEntry]
    tags: Dict[str, Tuple[str, str]]


@dataclasses.dataclass
class Snapshot:
    """A built tree, the blob of each member and the sha256 of each gitignored file of the set."""

    tree: str
    files: Dict[str, str]
    ignored: Dict[str, str]


# --- locations and state ----------------------------------------------------------------------------------

def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def plans_dir() -> Path:
    cfg = active()
    return cfg.path(cfg.artifacts.plans)


def stem(name: str) -> str:
    return fl.skill_stem(name)


def folder(name: str) -> Path:
    """``<artifacts.plans>/freezes/skill/<name>``."""
    return fl.ledger_dir(plans_dir(), stem(name))


def entries(name: str) -> List[LedgerEntry]:
    """Every ledger entry of ``name``; ``LockRefused`` when one cannot be read."""
    try:
        return fl.load_entries(folder(name))
    except fl.LedgerError as exc:
        raise LockRefused(exc.problems) from None


def round_of(spec: SkillSpec) -> int:
    """The spec's current round: one past its earlier rounds."""
    return len(spec.rounds) + 1


def is_locked(spec: SkillSpec, found: Optional[List[LedgerEntry]] = None) -> bool:
    """True when the spec's current round is Locked: a ``lock`` that only a ``relink`` may follow."""
    found = entries(spec.name) if found is None else found
    current = [e for e in found if e.round == round_of(spec)]
    return fl.state(current) == fl.LedgerState.locked


def locked_problem(spec: SkillSpec) -> Optional[str]:
    """``<name> is locked; reopen to change it`` for a Locked spec, else None."""
    return LOCKED.format(name=spec.name) if is_locked(spec) else None


def refuse_locked(spec: SkillSpec) -> None:
    problem = locked_problem(spec)
    if problem:
        raise LockRefused([problem])


def _rel(root: Path, path: Path) -> str:
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def _entry_rel(root: Path, name: str, entry: LedgerEntry) -> str:
    return _rel(root, folder(name) / fl.entry_name(entry))


# --- trees ------------------------------------------------------------------------------------------------

def _spec_dir(name: str) -> Path:
    return plans_dir() / "strap" / name


def freeze_set(root: Path, spec: SkillSpec) -> List[str]:
    """Every part at its repo path, plus the spec folder's ``tests/`` and ``fixtures/`` when present."""
    spec_dir = _spec_dir(spec.name)
    extra = [_rel(root, spec_dir / sub) for sub in SET_DIRS if (spec_dir / sub).is_dir()]
    return [part.path for part in spec.parts] + extra


def lock_set(root: Path, spec: SkillSpec) -> List[str]:
    """The freeze set plus ``SkillSpec.json``."""
    return freeze_set(root, spec) + [_rel(root, _spec_dir(spec.name) / SPEC_FILE)]


def snapshot(root: Path, paths: Sequence[str]) -> Snapshot:
    """The tree of the not-gitignored files of ``paths`` and the sha256 of the gitignored ones."""
    try:
        tree, files = fg.build_tree(root, paths)
        _, ignored = fg.members(root, paths)
    except fg.FreezeGitError as exc:
        raise LockRefused([str(exc)]) from None
    return Snapshot(tree=tree, files=files, ignored=fg.ignored_digests(root, ignored))


def worktree_blobs(root: Path, paths: Sequence[str]) -> Dict[str, str]:
    """``{path: blob}`` of ``paths`` as the working tree holds them; missing files are left out."""
    present = [p for p in paths if (Path(root) / p).is_file()]
    if not present:
        return {}
    try:
        return fg.build_tree(root, present)[1]
    except fg.FreezeGitError:
        return {}


# --- entries ----------------------------------------------------------------------------------------------

def _seq(root: Path, name: str, found: Sequence[LedgerEntry], round_: int) -> int:
    return fl.next_seq(found, round_, fg.tag_seqs(root, stem(name), round_))


def _at(text: str) -> str:
    """``text`` when it is an ISO date-time the ledger accepts, else the current time."""
    try:
        dt.datetime.fromisoformat(text)
    except ValueError:
        return now()
    return text if "T" in text else now()


def history(root: Path, spec: SkillSpec, found: Sequence[LedgerEntry]) -> List[LedgerEntry]:
    """For a spec without a ledger: one history ``freeze`` per ``rounds[]`` entry and the current stamp."""
    if found:
        return []
    stamps: List[Tuple[int, Optional[str], Frozen]] = [
        (index + 1, done.base, done.frozen) for index, done in enumerate(spec.rounds)]
    if spec.frozen is not None:
        stamps.append((round_of(spec), spec.base, spec.frozen))
    out: List[LedgerEntry] = []
    for round_, base, frozen in stamps:
        out.append(LedgerEntry(kind=EntryKind.freeze, round=round_, seq=_seq(root, spec.name, out, round_),
                               at=_at(frozen.at), base=base, history=True, skill_hash=frozen.skill_hash,
                               grader=frozen.grader.value))
    return out


def _tree_tag(name: str, entry: LedgerEntry) -> str:
    return fg.entry_tag(entry.kind.value, stem(name), entry.round, entry.seq, "tree")


def freeze_pending(root: Path, spec: SkillSpec, frozen: Frozen) -> Pending:
    """The ``freeze`` entry of ``frozen`` (after any history entries) and its tree and base tags.

    No base tag is requested when a ``base/<stem>/r<N>`` or relinked ``r<N>-<m>`` tag already holds
    ``spec.base``: after a relink the plain name stays on the old base and is never re-targeted.
    """
    found = entries(spec.name)
    if is_locked(spec, found):
        raise LockRefused([LOCKED.format(name=spec.name)])
    earlier = history(root, spec, found)
    round_ = round_of(spec)
    snap = snapshot(root, freeze_set(root, spec))
    seq = _seq(root, spec.name, [*found, *earlier], round_)
    entry = LedgerEntry(kind=EntryKind.freeze, round=round_, seq=seq, tree=snap.tree, files=snap.files,
                        ignored=snap.ignored, at=frozen.at, base=spec.base, skill_hash=frozen.skill_hash,
                        grader=frozen.grader.value)
    tags = {_tree_tag(spec.name, entry): (snap.tree, f"{spec.name}: freeze r{round_}.{entry.seq} tree")}
    if spec.base and not _base_held(root, spec.name, round_, spec.base):
        tags[fg.base_tag(stem(spec.name), round_)] = (spec.base, f"{spec.name}: base of round {round_}")
    return Pending(spec.name, [*earlier, entry], tags)


def lock_pending(root: Path, spec: SkillSpec) -> Pending:
    """The ``lock`` entry of a Frozen spec: the freeze set plus ``SkillSpec.json``, tagged."""
    found = entries(spec.name)
    if spec.frozen is None:
        raise LockRefused([f"{spec.name} is not frozen; freeze it before lock"])
    round_ = round_of(spec)
    snap = snapshot(root, lock_set(root, spec))
    entry = LedgerEntry(kind=EntryKind.lock, round=round_, seq=_seq(root, spec.name, found, round_),
                        tree=snap.tree, files=snap.files, ignored=snap.ignored, at=now(), base=spec.base,
                        skill_hash=spec.frozen.skill_hash, grader=spec.frozen.grader.value)
    tags = {_tree_tag(spec.name, entry): (snap.tree, f"{spec.name}: lock r{round_}.{entry.seq} tree")}
    return Pending(spec.name, [entry], tags)


def reopen_pending(root: Path, spec: SkillSpec, base: str) -> Pending:
    """The ``reopen`` entry of the round after ``spec``'s (history first on a legacy spec), base tagged."""
    found = entries(spec.name)
    earlier = history(root, spec, found)
    round_ = round_of(spec) + 1
    entry = LedgerEntry(kind=EntryKind.reopen, round=round_,
                        seq=_seq(root, spec.name, [*found, *earlier], round_), at=now(), base=base)
    tags = {fg.base_tag(stem(spec.name), round_): (base, f"{spec.name}: base of round {round_}")}
    return Pending(spec.name, [*earlier, entry], tags)


def _base_ms(root: Path, name: str, round_: int) -> List[int]:
    """The ``m`` of each existing ``base/<stem>/r<N>[-<m>]`` tag (the plain one counts as 1)."""
    prefix = fg.base_tag(stem(name), round_)
    pattern = re.compile(rf"^{re.escape(prefix)}(?:-(\d+))?$")
    names = git(root, "tag", "--list", f"{prefix}*").stdout.split()
    return [int(match.group(1) or 1) for line in names if (match := pattern.match(line))]


def _base_held(root: Path, name: str, round_: int, base: str) -> bool:
    """True when an existing ``base/<stem>/r<N>`` or ``base/<stem>/r<N>-<m>`` tag peels to ``base``."""
    prefix = fg.base_tag(stem(name), round_)
    pattern = re.compile(rf"^{re.escape(prefix)}(?:-\d+)?$")
    names = git(root, "tag", "--list", f"{prefix}*").stdout.split()
    return any(_peel(root, line) == base for line in names if pattern.match(line))


def relink_pending(root: Path, spec: SkillSpec, new_base: str, match: str) -> Pending:
    """The ``relink`` entry re-pointing ``spec.base`` at ``new_base`` and its ``r<N>-<m>`` base tag."""
    found = entries(spec.name)
    earlier = history(root, spec, found)
    round_ = round_of(spec)
    relinks = [e for e in found if e.kind == EntryKind.relink and e.round == round_]
    m = max([*_base_ms(root, spec.name, round_), len(relinks) + 1]) + 1
    entry = LedgerEntry(kind=EntryKind.relink, round=round_,
                        seq=_seq(root, spec.name, [*found, *earlier], round_), at=now(), base=new_base,
                        old_base=spec.base, new_base=new_base, match=match)
    message = f"{spec.name}: relinked base of round {round_}"
    tags = {fg.base_tag(stem(spec.name), round_, m): (new_base, message)}
    return Pending(spec.name, [*earlier, entry], tags)


def relinked(root: Path, spec: SkillSpec, pending: Pending) -> Pending:
    """``pending`` once the re-pointed spec is saved: its ``relink`` entry re-records the files the lock (on
    a Locked spec) or the last freeze holds, with ``SkillSpec.json``'s new blob; unchanged when no held set
    names the spec file."""
    found = entries(spec.name)
    current = [e for e in found if e.round == round_of(spec)]
    src = fl.held(current, EntryKind.lock if is_locked(spec, found) else EntryKind.freeze)
    own = _rel(root, _spec_dir(spec.name) / SPEC_FILE)
    if src is None or own not in src.files:
        return pending
    blob = worktree_blobs(root, [own]).get(own)
    if blob is None:
        raise LockRefused([f"{own}: missing after the relink save"])
    update = {"files": {**src.files, own: blob}, "ignored": dict(src.ignored)}
    found_new = [e.model_copy(update=update) if e.kind == EntryKind.relink else e for e in pending.entries]
    return dataclasses.replace(pending, entries=found_new)


def base_pending(name: str, base: str) -> Pending:
    """No entry; only the round-1 base tag of a new edit spec."""
    return Pending(name, [], {fg.base_tag(stem(name), 1): (base, f"{name}: base of round 1")})


# --- preflight, write, tag, reconcile ---------------------------------------------------------------------

def preflight(root: Path, pending: Pending) -> None:
    """Refuse when a tag name ``pending`` creates already sits on another object; nothing is written."""
    if fg.in_scenario_tree(root):
        return
    problems = fg.preflight(root, {name: target for name, (target, _) in pending.tags.items()})
    if problems:
        raise LockRefused(problems)


@contextlib.contextmanager
def _tagger(root: Path) -> Iterator[None]:
    """A fallback committer identity while tagging, only when git has none configured."""
    if git(root, "var", "GIT_COMMITTER_IDENT").returncode == 0:
        yield
        return
    saved = {key: os.environ.get(key) for key in FALLBACK_TAGGER}
    os.environ.update(FALLBACK_TAGGER)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _create(root: Path, tags: Dict[str, Tuple[str, str]]) -> Tuple[List[str], List[str]]:
    """Create each tag; ``(created, warn lines)``. A git failure warns and leaves the entry in place."""
    created: List[str] = []
    warns: List[str] = []
    with _tagger(root):
        for name, (target, message) in tags.items():
            try:
                made = fg.ensure_tag(root, name, target, message)
            except (fg.FreezeGitError, OSError) as exc:
                warns.append(f"warn: {exc}")
                continue
            if made:
                created.append(made)
    return created, warns


def _peel(root: Path, name: str) -> Optional[str]:
    done = git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{name}^{{}}")
    return done.stdout.strip() if done.returncode == 0 else None


def tag_lines(root: Path, created: Sequence[str]) -> List[str]:
    """One ``tag: <name> -> <sha7>`` line per created tag, then the ``push:`` line."""
    if not created:
        return []
    lines = [f"tag: {name} -> {(_peel(root, name) or '')[:7]}" for name in created]
    return [*lines, fg.push_line(created)]


def reconcile(root: Path, name: str) -> Tuple[List[str], List[str]]:
    """Tag the commits that added ``name``'s committed entries; ``(created, warn lines)``, never raises."""
    if fg.in_scenario_tree(root):
        return [], []
    try:
        found = entries(name)
    except LockRefused as exc:
        return [], [f"warn: {line}" for line in exc.problems]
    rows = [(_entry_stem(name, e), _entry_rel(root, name, e), e.history) for e in found]
    with _tagger(root):
        return fg.reconcile(root, rows)


def _entry_stem(name: str, entry: LedgerEntry) -> str:
    return f"{entry.kind.value}/{stem(name)}/r{entry.round}.{entry.seq}"


def _write_entries(pending: Pending, restore: Optional[Tuple[Path, bytes]]) -> None:
    """Write ``pending``'s entries; a failed write puts ``restore``'s bytes back at its path, then raises."""
    target = folder(pending.name)
    try:
        for entry in pending.entries:
            fl.write_entry(target, entry)
    except (fl.LedgerError, OSError):
        if restore is not None:
            restore[0].write_bytes(restore[1])
        raise


def commit(root: Path, pending: Pending, restore: Optional[Tuple[Path, bytes]] = None) -> List[str]:
    """Write the entries, create the tags and reconcile; return the ``tag:``, ``push:`` and ``warn:``
    lines. ``restore`` is the spec file and its bytes before the command saved it, put back when an entry
    write fails so the spec never moves without its ledger entry."""
    _write_entries(pending, restore)
    if fg.in_scenario_tree(root):
        return []
    created, warns = _create(root, pending.tags)
    more, late = reconcile(root, pending.name)
    return tag_lines(root, [*created, *more]) + warns + late


# --- lock gate --------------------------------------------------------------------------------------------

def _head_blobs(root: Path, paths: Sequence[str]) -> Dict[str, str]:
    """``{path: blob}`` of ``paths`` at HEAD."""
    if not paths:
        return {}
    done = git(root, "--literal-pathspecs", "ls-tree", "-r", "-z", "HEAD", "--", *paths)
    blobs: Dict[str, str] = {}
    for line in (part for part in done.stdout.split("\0") if part):
        meta, rel = line.split("\t", 1)
        blobs[rel] = meta.split()[2]
    return blobs


def _ledger_problems(spec: SkillSpec, found: Sequence[LedgerEntry]) -> List[str]:
    refreeze = f"run freeze {spec.name} --refreeze first"
    if not found:
        return [f"{spec.name} has no ledger; {refreeze}"]
    last = fl.last_freeze(found)
    if (last is None or last.history or last.round != round_of(spec) or spec.frozen is None
            or last.skill_hash != spec.frozen.skill_hash):
        return [f"{spec.name}: the ledger's last freeze does not match the spec stamp; {refreeze}"]
    return []


def _file_problems(root: Path, last: LedgerEntry) -> List[str]:
    """Each frozen file not committed at HEAD as frozen, or changed in the working tree."""
    head = _head_blobs(root, sorted(last.files))
    work = worktree_blobs(root, sorted(last.files))
    problems: List[str] = []
    for path, blob in sorted(last.files.items()):
        if head.get(path) != blob:
            problems.append(f"{path}: not committed at HEAD as frozen; commit the freeze first")
        elif work.get(path) != blob:
            problems.append(f"{path}: the working tree differs from the freeze")
    current = fg.ignored_digests(root, sorted(last.ignored))
    problems += [f"{path}: ignored file differs from the freeze" for path, digest in
                 sorted(last.ignored.items()) if current.get(path) != digest]
    return problems


def _spec_problems(root: Path, spec: SkillSpec) -> List[str]:
    """``SkillSpec.json`` changed since HEAD: the lock tree takes it from the working tree, so it must sit
    in a commit."""
    own = _rel(root, _spec_dir(spec.name) / SPEC_FILE)
    if _head_blobs(root, [own]).get(own) == worktree_blobs(root, [own]).get(own):
        return []
    return [f"{own}: differs from HEAD; commit the spec first"]


def lock_problems(root: Path, spec: SkillSpec) -> List[str]:
    """The ledger part of the lock gate: a last freeze matching the stamp, its files and ``SkillSpec.json``
    at HEAD and clean."""
    found = entries(spec.name)
    if is_locked(spec, found):
        return [f"{spec.name} is already locked"]
    problems = _ledger_problems(spec, found)
    last = fl.last_freeze(found)
    if problems or last is None:
        return problems
    return _file_problems(root, last) + _spec_problems(root, spec)


# --- relink -----------------------------------------------------------------------------------------------

def _on_head(root: Path, commit_sha: str) -> bool:
    return git(root, "merge-base", "--is-ancestor", commit_sha, "HEAD").returncode == 0


def relink_target(root: Path, spec: SkillSpec, to: Optional[str]) -> Tuple[str, str]:
    """``(new_base, match)``: ``--to`` resolved (``ref``), or the patch-id match of the lost base."""
    if not spec.base:
        raise LockRefused([f"{spec.name} has no base to relink"])
    if to is None and _on_head(root, spec.base):
        raise LockRefused([f"base {spec.base[:12]} is on HEAD's history; nothing to relink"])
    if to is not None:
        done = git(root, "rev-parse", "--verify", "--quiet", f"{to}^{{commit}}")
        if done.returncode != 0:
            raise LockRefused([f"--to {to} does not name a commit"])
        sha = done.stdout.strip()
        if not _on_head(root, sha):
            raise LockRefused([f"--to {to} is not an ancestor of HEAD"])
        return sha, "ref"
    found = fg.patch_id_match(root, spec.base)
    if found is None:
        raise LockRefused([f"no commit on HEAD's history matches base {spec.base[:12]} by patch-id; "
                           "pass --to REF"])
    return found, "patch-id"


# --- check ------------------------------------------------------------------------------------------------

def _base_lines(root: Path, spec: SkillSpec, scenario: bool) -> List[str]:
    """``off-history:`` for a base not on HEAD's history; ``untagged:`` when no base tag holds it."""
    if not spec.base:
        return []
    role = f"base r{round_of(spec)}"
    lines = [] if _on_head(root, spec.base) else [f"off-history: {spec.base[:7]} ({role})"]
    prefix = fg.base_tag(stem(spec.name), round_of(spec))
    names = git(root, "tag", "--list", f"{prefix}*").stdout.split()
    if not scenario and not any(_peel(root, name) == spec.base for name in names):
        lines.append(f"untagged: {spec.base[:7]} ({role})")
    return lines


def _adder(root: Path, rel: str) -> Optional[str]:
    done = git(root, "--literal-pathspecs", "log", "--diff-filter=A", "--reverse", "--format=%H", "HEAD",
               "--", rel)
    found = done.stdout.split() if done.returncode == 0 else []
    return found[0] if found else None


def _entry_lines(root: Path, name: str, entry: LedgerEntry) -> List[str]:
    """``untagged:`` for a non-history entry's tree and, once committed, its commit."""
    if entry.history:
        return []
    role = f"{entry.kind.value} r{entry.round}.{entry.seq}"
    lines = []
    if entry.tree and _peel(root, _tree_tag(name, entry)) != entry.tree:
        lines.append(f"untagged: {entry.tree[:7]} ({role} tree)")
    adder = _adder(root, _entry_rel(root, name, entry))
    tagged = git(root, "tag", "--list", f"{_entry_stem(name, entry)}-commit*").stdout.split()
    if adder and not tagged:
        lines.append(f"untagged: {adder[:7]} ({role} commit)")
    return lines


def _stamp_lines(spec: SkillSpec, found: Sequence[LedgerEntry]) -> List[str]:
    """``ledger:`` when the last freeze entry and the spec stamp disagree."""
    if spec.frozen is None:
        return []
    last = fl.last_freeze(found)
    if last is not None and last.round == round_of(spec) and last.skill_hash == spec.frozen.skill_hash:
        return []
    where = f"r{last.round}.{last.seq} stamps {(last.skill_hash or 'nothing')[:12]}" if last else "has none"
    return [f"ledger: {spec.name}'s last freeze entry {where}; the spec is frozen at "
            f"{spec.frozen.skill_hash[:12]}"]


def _drift_lines(root: Path, spec: SkillSpec, found: Sequence[LedgerEntry]) -> List[str]:
    """``drift: <path> differs from <tag>`` for each Locked file changed since the lock."""
    if not is_locked(spec, list(found)):
        return []
    lock = max((e for e in found if e.kind == EntryKind.lock), key=lambda e: (e.round, e.seq))
    held = fl.held(found, EntryKind.lock) or lock
    tag = _tree_tag(spec.name, lock)
    work = worktree_blobs(root, sorted(held.files))
    paths = [p for p, blob in sorted(held.files.items()) if work.get(p) != blob]
    current = fg.ignored_digests(root, sorted(held.ignored))
    paths += [p for p, digest in sorted(held.ignored.items()) if p in current and current[p] != digest]
    return [f"drift: {path} differs from {tag}" for path in paths]


def check_lines(root: Path, spec: SkillSpec) -> List[str]:
    """Reconcile, then the ``tag:``/``push:``, ``untagged:``, ``off-history:``, ``ledger:``, ``drift:`` and
    ``legacy:`` lines of ``check``. Writes refs, never files."""
    found = entries(spec.name)
    if not found and spec.frozen is not None:
        return [LEGACY.format(name=spec.name)]
    scenario = fg.in_scenario_tree(root)
    created, warns = reconcile(root, spec.name)
    lines = tag_lines(root, created) + warns + _base_lines(root, spec, scenario)
    if not scenario:
        lines += [line for entry in found for line in _entry_lines(root, spec.name, entry)]
    return lines + _stamp_lines(spec, found) + _drift_lines(root, spec, found)
