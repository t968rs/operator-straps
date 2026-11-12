"""Freeze ledger entries, tags and the Locked state of a plan (plan 1015).

A plan's freeze stamp lives in ``<plan folder>/freezes/plan/<id>-<slug>/``, one write-once entry file per
``freeze``, ``lock``, ``arm``, ``unlock`` or ``relink``; the plan JSON carries only the static ``ledger``
field (the stem). The stem's slug is the plan file's title slug in lower case, each run of characters
outside ``[a-z0-9]`` (underscores among them) one hyphen. Plans
have one round, so every entry is ``r1.<k>``. A ``relink`` entry re-records the held files with the plan
JSON's new blob, so the lock gate and ``drift:`` compare against the relinked plan.

Every tag-creating step works out its names first and preflights them (``freeze_git.preflight``) before the
command writes anything; a name on another object refuses the command. Tags are local; ``tag:`` lines and
one ``push:`` line (never naming a ``receipt/`` tag) follow the command's status line. Inside a strap scenario
tree (``freeze_git.SCENARIO_MARKER`` at the project root) entries are still written, but no tag is created
and nothing is reconciled. Nothing here reads the config: callers pass the plan file, whose folder holds the
ledger. This module never saves a plan except in ``write_freeze``; ``plan.py`` does the rest.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import json
import os
import posixpath
import re
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from harness_lib import freeze_git as fg
from harness_lib import freeze_ledger as fl
from harness_lib import plan_doc as pd
from harness_lib import plan_models as pm
from harness_lib.branch_capture import git
from harness_lib.freeze_ledger import EntryKind, LedgerEntry, LedgerState
from harness_lib.plan_enums import RecordScheme, RecordSource

ROUND = 1
LEGACY = "legacy: plan {id} keeps an in-file stamp; migrates at its next refreeze"
FALLBACK_TAGGER = {"GIT_COMMITTER_NAME": "plan", "GIT_COMMITTER_EMAIL": "plan@localhost"}
_ID_PREFIX = re.compile(r"^(\d{4})_")
_PLAN_TAG = re.compile(r"^[^/]+/plan/(\d{4})-")
_LOCKED = (LedgerState.locked, LedgerState.armed)
Tags = Dict[str, Tuple[str, str]]


@dataclasses.dataclass
class Pending:
    """A freeze worked out before any write: its stem, history entries, sequence and known-target tags."""

    stem: str
    history: List[LedgerEntry]
    seq: int
    tags: Tags


# --- locations and state ----------------------------------------------------------------------------------

def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def stem_slug(title_slug: str) -> str:
    """A title slug as a stem slug: lower case, each run of characters outside ``[a-z0-9]`` one hyphen.

    The result always fits the ``ledger`` pattern, even for a hand-named plan file whose title holds a dot,
    a plus sign or a non-ASCII letter.
    """
    return re.sub(r"[^a-z0-9]+", "-", title_slug.lower()).strip("-")


def file_slug(plan_file: Path) -> str:
    """The stem slug of a plan file name ``<id>_<Title>_ActionPlan.json``."""
    name = plan_file.name
    if name.endswith(pd.PLAN_SUFFIX):
        name = name[: -len(pd.PLAN_SUFFIX)]
    return stem_slug(_ID_PREFIX.sub("", name, count=1))


def stem_of(plan_file: Path, plan: pm.ActionPlan) -> str:
    """The plan's ``ledger`` field, else ``plan/<id>-<slug>`` from its file name."""
    return plan.ledger or fl.plan_stem(plan.plan_id, file_slug(plan_file))


def folder_of(plan_file: Path, stem: str) -> Path:
    return fl.ledger_dir(plan_file.parent, stem)


def entries_of(plan_file: Path, plan: pm.ActionPlan) -> List[LedgerEntry]:
    """Every ledger entry of the plan; ``PlanError`` when one cannot be read."""
    try:
        return fl.load_entries(folder_of(plan_file, stem_of(plan_file, plan)))
    except fl.LedgerError as exc:
        raise pd.PlanError(exc.problems) from None


def rel(repo: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _last(found: Sequence[LedgerEntry], kind: EntryKind) -> Optional[LedgerEntry]:
    hits = [e for e in found if e.kind == kind]
    return max(hits, key=lambda e: (e.round, e.seq)) if hits else None


def refuse_locked(plan_file: Path, plan: pm.ActionPlan) -> None:
    """Refuse a Locked or armed plan: ``unlock`` runs first."""
    current = fl.state(entries_of(plan_file, plan))
    pid = plan.plan_id
    if current == LedgerState.locked:
        raise pd.PlanError([f"plan {pid} is locked; unlock first: plan.py unlock {pid} --arm REASON on the "
                            f"developer's explicit OK, then plan.py unlock {pid}"])
    if current == LedgerState.armed:
        raise pd.PlanError([f"plan {pid} is locked and armed; unlock first: plan.py unlock {pid}"])


def _require_ledger(plan: pm.ActionPlan, then: str) -> None:
    """Refuse a plan without a ledger: a legacy stamp needs its migration refreeze, an open plan a freeze."""
    if plan.ledger is not None:
        return
    pid = plan.plan_id
    if plan.frozen is not None:
        raise pd.PlanError([f"plan {pid} keeps an in-file stamp; run plan.py freeze {pid} --refreeze to move "
                            f"it to the ledger, then {then}"])
    raise pd.PlanError([f"plan {pid} is not frozen; run plan.py freeze {pid} first"])


# --- trees and tags ---------------------------------------------------------------------------------------

def freeze_set(repo: Path, plan_file: Path, plan: pm.ActionPlan) -> List[str]:
    """The plan JSON and, when present, everything under ``<plan folder>/<id>/tests/``."""
    tests = plan_file.parent / plan.plan_id / "tests"
    return [rel(repo, plan_file)] + ([rel(repo, tests)] if tests.is_dir() else [])


def snapshot(repo: Path, paths: Sequence[str]) -> Tuple[str, Dict[str, str], Dict[str, str]]:
    """``(tree, files, ignored)``: the tree of the not-ignored files and the sha256 of the ignored ones."""
    try:
        tree, files = fg.build_tree(repo, paths)
        _, ignored = fg.members(repo, paths)
    except fg.FreezeGitError as exc:
        raise pd.PlanError([str(exc)]) from None
    return tree, files, fg.ignored_digests(repo, ignored)


def worktree_blobs(repo: Path, paths: Sequence[str]) -> Dict[str, str]:
    """``{path: blob}`` of ``paths`` as the working tree holds them; missing files are left out."""
    present = [p for p in paths if (Path(repo) / p).is_file()]
    if not present:
        return {}
    try:
        return fg.build_tree(repo, present)[1]
    except fg.FreezeGitError:
        return {}


def _seq(repo: Path, stem: str, found: Sequence[LedgerEntry]) -> int:
    return fl.next_seq(found, ROUND, fg.tag_seqs(repo, stem, ROUND))


def tree_tag(stem: str, kind: str, seq: int) -> str:
    return fg.entry_tag(kind, stem, ROUND, seq, "tree")


def _entry_stem(stem: str, entry: LedgerEntry) -> str:
    return f"{entry.kind.value}/{stem}/r{entry.round}.{entry.seq}"


def base_tags(stem: str, base: str, repo: Optional[Path] = None) -> Tags:
    """The round-1 base tag of ``stem`` on ``base``; empty without a base.

    With ``repo``, also empty when a ``base/<stem>/r1`` or relinked ``base/<stem>/r1-<m>`` tag already peels
    to ``base``: after a relink the plain name stays on the old base and is never re-targeted.
    """
    if not base or (repo is not None and base_held(repo, stem, base)):
        return {}
    return {fg.base_tag(stem, ROUND): (base, f"{stem}: base of round {ROUND}")}


def base_held(repo: Path, stem: str, base: str) -> bool:
    """True when an existing ``base/<stem>/r1`` or ``base/<stem>/r1-<m>`` tag peels to ``base``."""
    prefix = fg.base_tag(stem, ROUND)
    pattern = re.compile(rf"^{re.escape(prefix)}(?:-\d+)?$")
    names = git(repo, "tag", "--list", f"{prefix}*").stdout.split()
    return any(_peel(repo, name) == base for name in names if pattern.match(name))


def _peel(repo: Path, name: str) -> Optional[str]:
    done = git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{name}^{{}}")
    return done.stdout.strip() if done.returncode == 0 else None


def preflight(repo: Path, tags: Tags, fresh: Sequence[str] = ()) -> None:
    """Refuse when a name of ``tags`` sits on another object or a ``fresh`` name exists; writes nothing."""
    if fg.in_scenario_tree(repo):
        return
    try:
        problems = fg.preflight(repo, {name: target for name, (target, _) in tags.items()})
    except fg.FreezeGitError as exc:
        raise pd.PlanError([str(exc)]) from None
    problems += [f"tag {name} already exists" for name in fresh if _peel(repo, name)]
    if problems:
        raise pd.PlanError(problems)


@contextlib.contextmanager
def _tagger(repo: Path) -> Iterator[None]:
    """A fallback committer identity while tagging, only when git has none configured."""
    if git(repo, "var", "GIT_COMMITTER_IDENT").returncode == 0:
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


def _create(repo: Path, tags: Tags) -> Tuple[List[str], List[str]]:
    """Create each tag; ``(created, warn lines)``. A git failure warns and leaves the entry in place."""
    created: List[str] = []
    warns: List[str] = []
    with _tagger(repo):
        for name, (target, message) in tags.items():
            try:
                made = fg.ensure_tag(repo, name, target, message)
            except (fg.FreezeGitError, OSError) as exc:
                warns.append(f"warn: {exc}")
                continue
            if made:
                created.append(made)
    return created, warns


def tag_lines(repo: Path, created: Sequence[str], push: bool = True) -> List[str]:
    """One ``tag: <name> -> <sha7>`` line per created tag, then the ``push:`` line unless ``push`` is off."""
    if not created:
        return []
    lines = [f"tag: {name} -> {(_peel(repo, name) or '')[:7]}" for name in created]
    return [*lines, fg.push_line(created)] if push else lines


def reconcile(repo: Path, plan_file: Path, plan: pm.ActionPlan) -> Tuple[List[str], List[str]]:
    """Tag the commits that added the plan's committed entries; ``(created, warn lines)``, never raises."""
    if fg.in_scenario_tree(repo):
        return [], []
    stem = stem_of(plan_file, plan)
    folder = folder_of(plan_file, stem)
    try:
        found = fl.load_entries(folder)
    except fl.LedgerError as exc:
        return [], [f"warn: {line}" for line in exc.problems]
    rows = [(_entry_stem(stem, e), rel(repo, folder / fl.entry_name(e)), e.history) for e in found]
    if not rows:
        return [], []
    with _tagger(repo):
        return fg.reconcile(repo, rows)


def reconcile_lines(repo: Path, plan_file: Path, plan: pm.ActionPlan) -> List[str]:
    """Reconcile; the ``tag:``, ``push:`` and ``warn:`` lines."""
    created, warns = reconcile(repo, plan_file, plan)
    return tag_lines(repo, created) + warns


def create_lines(repo: Path, tags: Tags) -> List[str]:
    """Create ``tags`` (skipped in a scenario tree); the ``tag:``, ``push:`` and ``warn:`` lines."""
    if fg.in_scenario_tree(repo):
        return []
    created, warns = _create(repo, tags)
    return tag_lines(repo, created) + warns


def commit_tags(repo: Path, plan_file: Path, plan: pm.ActionPlan, tags: Tags) -> List[str]:
    """Create ``tags`` and reconcile the plan's ledger; the ``tag:``, ``push:`` and ``warn:`` lines."""
    if fg.in_scenario_tree(repo):
        return []
    created, warns = _create(repo, tags)
    more, late = reconcile(repo, plan_file, plan)
    return tag_lines(repo, [*created, *more]) + warns + late


def _write(plan_file: Path, stem: str, found: Sequence[LedgerEntry]) -> None:
    folder = folder_of(plan_file, stem)
    try:
        for entry in found:
            fl.write_entry(folder, entry)
    except fl.LedgerError as exc:
        raise pd.PlanError(exc.problems) from None


# --- freeze -----------------------------------------------------------------------------------------------

def history(repo: Path, stem: str, plan: pm.ActionPlan, found: Sequence[LedgerEntry]) -> List[LedgerEntry]:
    """For a plan with an in-file stamp and no ledger: the history ``freeze`` entry the stamp stands for."""
    stamp = plan.frozen
    if plan.ledger is not None or stamp is None:
        return []
    records = None if stamp.records is None else RecordScheme(stamp.records).value
    return [LedgerEntry(kind=EntryKind.freeze, round=ROUND, seq=_seq(repo, stem, found),
                        at=f"{stamp.date}T00:00:00+00:00", base=plan.base_commit or None, history=True,
                        digest=stamp.digest, records=records)]


def freeze_pending(repo: Path, plan_file: Path, plan: pm.ActionPlan) -> Pending:
    """The freeze's stem, history entries, sequence and base tag, preflighted; nothing is written.

    No base tag is requested when a round-1 base tag (a relinked one included) already holds the base.
    """
    stem = stem_of(plan_file, plan)
    found = entries_of(plan_file, plan)
    earlier = history(repo, stem, plan, found)
    seq = _seq(repo, stem, [*found, *earlier])
    pending = Pending(stem, earlier, seq, base_tags(stem, plan.base_commit, repo))
    preflight(repo, pending.tags, [tree_tag(stem, EntryKind.freeze.value, seq)])
    return pending


def write_freeze(repo: Path, plan_file: Path, plan: pm.ActionPlan, pending: Pending,
                 scheme: Optional[RecordScheme]) -> Tags:
    """Set ``ledger``, save the plan JSON, build its tree and write the entries; the tags to create.

    The digest covers ``ledger``. ``plan.frozen`` becomes the ledger stamp. A failed tree or entry write
    restores the plan file's bytes.
    """
    before = plan_file.read_bytes()
    plan.ledger = pending.stem
    digest = pd.frozen_digest(plan, scheme)
    pd.save_plan(plan_file, plan)
    try:
        tree, files, ignored = snapshot(repo, freeze_set(repo, plan_file, plan))
        entry = LedgerEntry(kind=EntryKind.freeze, round=ROUND, seq=pending.seq, tree=tree, files=files,
                            ignored=ignored, at=now(), base=plan.base_commit or None, digest=digest,
                            records=None if scheme is None else scheme.value)
        _write(plan_file, pending.stem, [*pending.history, entry])
    except pd.PlanError:
        plan_file.write_bytes(before)
        raise
    pd.hydrate_frozen(plan, plan_file.parent)
    message = f"{pending.stem}: freeze r{ROUND}.{entry.seq} tree"
    return {**pending.tags, tree_tag(pending.stem, EntryKind.freeze.value, entry.seq): (tree, message)}


# --- lock gate and lock -----------------------------------------------------------------------------------

def _head_blobs(repo: Path, paths: Sequence[str]) -> Dict[str, str]:
    """``{path: blob}`` of ``paths`` at HEAD."""
    if not paths:
        return {}
    done = git(repo, "--literal-pathspecs", "ls-tree", "-r", "-z", "HEAD", "--", *paths)
    blobs: Dict[str, str] = {}
    for line in (part for part in done.stdout.split("\0") if part):
        meta, path = line.split("\t", 1)
        blobs[path] = meta.split()[2]
    return blobs


def _file_problems(repo: Path, last: LedgerEntry) -> List[str]:
    """Each frozen file not committed at HEAD as frozen or changed in the working tree; each ignored file
    whose sha256 moved."""
    head = _head_blobs(repo, sorted(last.files))
    work = worktree_blobs(repo, sorted(last.files))
    problems: List[str] = []
    for path, blob in sorted(last.files.items()):
        if head.get(path) != blob:
            problems.append(f"{path}: not committed at HEAD as frozen; commit the freeze first")
        elif work.get(path) != blob:
            problems.append(f"{path}: the working tree differs from the freeze")
    current = fg.ignored_digests(repo, sorted(last.ignored))
    problems += [f"{path}: ignored file differs from the freeze" for path, digest in
                 sorted(last.ignored.items()) if current.get(path) != digest]
    return problems


def lock_problems(repo: Path, plan_file: Path, plan: pm.ActionPlan) -> List[str]:
    """The ledger part of the lock gate: Frozen with a ledger, the last freeze committed and clean."""
    _require_ledger(plan, "lock")
    found = entries_of(plan_file, plan)
    if fl.state(found) in _LOCKED:
        return [f"plan {plan.plan_id} is already locked"]
    last = fl.last_freeze(found)
    if last is None or last.history or last.tree is None:
        return [f"plan {plan.plan_id} has no ledger freeze with a tree; run plan.py freeze "
                f"{plan.plan_id} --refreeze first"]
    return _file_problems(repo, fl.held(found, EntryKind.freeze) or last)


def _held_tree(repo: Path, last: LedgerEntry, src: LedgerEntry) -> str:
    """The tree of ``src``'s files: the freeze's own tree, or one rebuilt after a ``relink`` re-recorded
    them (the lock gate has already matched them to HEAD and the working tree)."""
    if src is last and last.tree is not None:
        return last.tree
    try:
        return fg.build_tree(repo, sorted(src.files))[0]
    except fg.FreezeGitError as exc:
        raise pd.PlanError([str(exc)]) from None


def lock(repo: Path, plan_file: Path, plan: pm.ActionPlan) -> Tuple[LedgerEntry, List[str]]:
    """Write the ``lock`` entry (the files the last freeze, or a later ``relink``, holds, with the freeze's
    digest and records) and tag its tree."""
    stem = stem_of(plan_file, plan)
    found = entries_of(plan_file, plan)
    last = fl.last_freeze(found)
    if last is None or last.tree is None:
        raise pd.PlanError([f"plan {plan.plan_id} has no ledger freeze with a tree to lock"])
    src = fl.held(found, EntryKind.freeze) or last
    tree = _held_tree(repo, last, src)
    seq = _seq(repo, stem, found)
    entry = LedgerEntry(kind=EntryKind.lock, round=ROUND, seq=seq, tree=tree, files=dict(src.files),
                        ignored=dict(src.ignored), at=now(), base=plan.base_commit or None,
                        digest=last.digest, records=last.records)
    tags = {tree_tag(stem, EntryKind.lock.value, seq): (tree, f"{stem}: lock r{ROUND}.{seq} tree")}
    preflight(repo, tags)
    _write(plan_file, stem, [entry])
    return entry, commit_tags(repo, plan_file, plan, tags)


# --- unlock -----------------------------------------------------------------------------------------------

def _arm_entry(plan: pm.ActionPlan, found: Sequence[LedgerEntry], seq: int, reason: str) -> LedgerEntry:
    """The ``arm`` entry; it carries the lock's digest and records, which the lock guard reads."""
    pid = plan.plan_id
    if not reason.strip():
        raise pd.PlanError(["--arm needs a non-empty REASON (an unset shell variable?)"])
    current = fl.state(found)
    if current != LedgerState.locked:
        raise pd.PlanError([f"plan {pid} is {current.value}, not locked; --arm applies to a Locked plan"])
    held = _last(found, EntryKind.lock)
    return LedgerEntry(kind=EntryKind.arm, round=ROUND, seq=seq, at=now(), base=plan.base_commit or None,
                       reason=reason.strip(), digest=None if held is None else held.digest,
                       records=None if held is None else held.records)


def _unlock_entry(plan: pm.ActionPlan, found: Sequence[LedgerEntry], seq: int) -> LedgerEntry:
    """The ``unlock`` entry; refused without a live arm."""
    pid = plan.plan_id
    if fl.state(found) != LedgerState.armed:
        raise pd.PlanError([f"plan {pid} has no live arm; plan.py unlock {pid} --arm REASON runs first, "
                            "on the developer's explicit OK"])
    return LedgerEntry(kind=EntryKind.unlock, round=ROUND, seq=seq, at=now(), base=plan.base_commit or None)


def unlock(repo: Path, plan_file: Path, plan: pm.ActionPlan,
           reason: Optional[str]) -> Tuple[LedgerEntry, List[str]]:
    """``--arm REASON`` writes ``arm`` on a Locked plan; without it, ``unlock`` uses up a live arm."""
    _require_ledger(plan, "lock it")
    stem = stem_of(plan_file, plan)
    found = entries_of(plan_file, plan)
    seq = _seq(repo, stem, found)
    if reason is not None:
        entry = _arm_entry(plan, found, seq, reason)
    else:
        entry = _unlock_entry(plan, found, seq)
    _write(plan_file, stem, [entry])
    return entry, commit_tags(repo, plan_file, plan, {})


# --- relink -----------------------------------------------------------------------------------------------

def _on_head(repo: Path, sha: str) -> bool:
    return git(repo, "merge-base", "--is-ancestor", sha, "HEAD").returncode == 0


def relink_target(repo: Path, base: str, to: Optional[str]) -> Tuple[str, str]:
    """``(new_base, match)``: ``--to`` resolved (``ref``), or the patch-id match of the lost base."""
    if to is None and _on_head(repo, base):
        raise pd.PlanError([f"base {base[:12]} is on HEAD's history; nothing to relink"])
    if to is not None:
        done = git(repo, "rev-parse", "--verify", "--quiet", f"{to}^{{commit}}")
        if done.returncode != 0:
            raise pd.PlanError([f"--to {to} does not name a commit"])
        sha = done.stdout.strip()
        if not _on_head(repo, sha):
            raise pd.PlanError([f"--to {to} is not an ancestor of HEAD"])
        return sha, "ref"
    found = fg.patch_id_match(repo, base)
    if found is None:
        raise pd.PlanError([f"no commit on HEAD's history matches base {base[:12]} by patch-id; "
                            "pass --to REF"])
    return found, "patch-id"


def _base_ms(repo: Path, stem: str) -> List[int]:
    """The ``m`` of each existing ``base/<stem>/r1[-<m>]`` tag (the plain one counts as 1)."""
    prefix = fg.base_tag(stem, ROUND)
    pattern = re.compile(rf"^{re.escape(prefix)}(?:-(\d+))?$")
    names = git(repo, "tag", "--list", f"{prefix}*").stdout.split()
    return [int(match.group(1) or 1) for name in names if (match := pattern.match(name))]


def relinked_files(repo: Path, plan_file: Path, found: Sequence[LedgerEntry]) -> Tuple[Dict[str, str],
                                                                                         Dict[str, str]]:
    """``(files, ignored)`` a ``relink`` re-records: those the lock (Locked or armed) or the last freeze
    holds, with the saved plan JSON's new blob; empty when no held set names the plan JSON."""
    src = fl.held(found, EntryKind.lock if fl.state(found) in _LOCKED else EntryKind.freeze)
    own = rel(repo, plan_file)
    if src is None or own not in src.files:
        return {}, {}
    blob = worktree_blobs(repo, [own]).get(own)
    if blob is None:
        raise pd.PlanError([f"{own}: missing after the relink save"])
    return {**src.files, own: blob}, dict(src.ignored)


def relink(repo: Path, plan_file: Path, plan: pm.ActionPlan, to: Optional[str],
           save: Callable[[Path, pm.ActionPlan], object]) -> Tuple[LedgerEntry, List[str]]:
    """Re-point ``plan.base_commit``, ``save`` the plan, write ``relink`` and tag the new base.

    The entry re-records the held files with the plan JSON's new blob, so the lock gate and ``drift:``
    compare against the relinked plan rather than the one the freeze or lock saw.
    """
    if plan.ledger is None and plan.frozen is not None:
        _require_ledger(plan, "relink")
    old = plan.base_commit
    if not old:
        raise pd.PlanError([f"plan {plan.plan_id} has no base_commit to relink"])
    new, match = relink_target(repo, old, to)
    stem = stem_of(plan_file, plan)
    found = entries_of(plan_file, plan)
    relinks = [e for e in found if e.kind == EntryKind.relink]
    m = max([*_base_ms(repo, stem), len(relinks) + 1]) + 1
    tags = {fg.base_tag(stem, ROUND, m): (new, f"{stem}: relinked base of round {ROUND}")}
    preflight(repo, tags)
    plan.base_commit = new
    save(plan_file, plan)
    files, ignored = relinked_files(repo, plan_file, found)
    entry = LedgerEntry(kind=EntryKind.relink, round=ROUND, seq=_seq(repo, stem, found), at=now(), base=new,
                        old_base=old, new_base=new, match=match, files=files, ignored=ignored)
    _write(plan_file, stem, [entry])
    return entry, commit_tags(repo, plan_file, plan, tags)


def digest_view(plan: pm.ActionPlan, plans_folder: Path) -> pm.ActionPlan:
    """The plan as its last freeze hashed it: a base a later ``relink`` re-pointed reads as the freeze's.

    Any other plan is returned as is, so a legacy plan's digest is computed exactly as before.
    """
    if plan.ledger is None:
        return plan
    try:
        found = fl.load_entries(fl.ledger_dir(plans_folder, plan.ledger))
    except fl.LedgerError:
        return plan
    last = fl.last_freeze(found)
    if last is None or last.base is None:
        return plan
    later = [e for e in found if e.kind == EntryKind.relink and (e.round, e.seq) > (last.round, last.seq)]
    if not later or plan.base_commit != later[-1].new_base:
        return plan
    return plan.model_copy(update={"base_commit": last.base})


# --- check ------------------------------------------------------------------------------------------------

def _base_lines(repo: Path, plan: pm.ActionPlan, stem: str, scenario: bool) -> List[str]:
    """``off-history:`` for a base not on HEAD's history; ``untagged:`` when no base tag holds it."""
    base = plan.base_commit
    if not base:
        return []
    role = f"base r{ROUND}"
    lines = [] if _on_head(repo, base) else [f"off-history: {base[:7]} ({role})"]
    names = git(repo, "tag", "--list", f"{fg.base_tag(stem, ROUND)}*").stdout.split()
    if not scenario and not any(_peel(repo, name) == base for name in names):
        lines.append(f"untagged: {base[:7]} ({role})")
    return lines


def _adder(repo: Path, path: str) -> Optional[str]:
    done = git(repo, "--literal-pathspecs", "log", "--diff-filter=A", "--reverse", "--format=%H", "HEAD",
               "--", path)
    found = done.stdout.split() if done.returncode == 0 else []
    return found[0] if found else None


def _entry_lines(repo: Path, plan_file: Path, stem: str, entry: LedgerEntry) -> List[str]:
    """``untagged:`` for a non-history entry's tree and, once committed, its commit."""
    if entry.history:
        return []
    role = f"{entry.kind.value} r{entry.round}.{entry.seq}"
    lines = []
    if entry.tree and _peel(repo, tree_tag(stem, entry.kind.value, entry.seq)) != entry.tree:
        lines.append(f"untagged: {entry.tree[:7]} ({role} tree)")
    adder = _adder(repo, rel(repo, folder_of(plan_file, stem) / fl.entry_name(entry)))
    tagged = git(repo, "tag", "--list", f"{_entry_stem(stem, entry)}-commit*").stdout.split()
    if adder and not tagged:
        lines.append(f"untagged: {adder[:7]} ({role} commit)")
    return lines


def _drift_lines(repo: Path, plan_file: Path, stem: str, found: Sequence[LedgerEntry]) -> List[str]:
    """``drift: <path> differs from <tag>`` for each Locked file changed since the lock.

    The plan JSON counts only under the receipts scheme: a sealed or unset-scheme plan's ``record`` still
    writes it.
    """
    lock = _last(found, EntryKind.lock)
    held = fl.held(found, EntryKind.lock)
    if fl.state(found) not in _LOCKED or lock is None or held is None:
        return []
    tag = tree_tag(stem, EntryKind.lock.value, lock.seq)
    own = rel(repo, plan_file)
    files = {p: b for p, b in held.files.items() if p != own or lock.records == RecordScheme.receipts.value}
    work = worktree_blobs(repo, sorted(files))
    paths = [p for p, blob in sorted(files.items()) if work.get(p) != blob]
    current = fg.ignored_digests(repo, sorted(held.ignored))
    paths += [p for p, digest in sorted(held.ignored.items()) if p in current and current[p] != digest]
    return [f"drift: {path} differs from {tag}" for path in paths]


def check_lines(repo: Path, plan_file: Path, plan: pm.ActionPlan) -> List[str]:
    """Reconcile, then the ``tag:``/``push:``, ``untagged:``, ``off-history:`` and ``drift:`` lines, or the
    one ``legacy:`` line of a plan with an in-file stamp. Writes refs, never files."""
    if plan.ledger is None and plan.frozen is not None:
        return [LEGACY.format(id=plan.plan_id)]
    stem = stem_of(plan_file, plan)
    scenario = fg.in_scenario_tree(repo)
    try:
        found = entries_of(plan_file, plan)
    except pd.PlanError as exc:
        return [f"warn: {line}" for line in exc.problems]
    lines = reconcile_lines(repo, plan_file, plan) + _base_lines(repo, plan, stem, scenario)
    if not scenario:
        lines += [line for entry in found for line in _entry_lines(repo, plan_file, stem, entry)]
    return lines + _drift_lines(repo, plan_file, stem, found)


# --- receipt tags -----------------------------------------------------------------------------------------

def receipt_lines(repo: Path, plan_file: Path, plan: pm.ActionPlan, item_id: str,
                  prov: pm.Provenance) -> List[str]:
    """Tag the code a COMPLETE record tested, locally: ``receipt/<stem>/<ITEM>-commit`` or ``-tree``, a
    re-record ``.2``, ``.3``. The ``tag:`` line only; no ``push:`` line ever names a receipt tag."""
    if fg.in_scenario_tree(repo):
        return []
    by_commit = prov.source == RecordSource.commit and prov.commit
    part, target = ("commit", prov.commit) if by_commit else ("tree", prov.tree)
    prefix = f"receipt/{stem_of(plan_file, plan)}/{item_id}-{part}"
    pattern = re.compile(rf"^{re.escape(prefix)}(?:\.(\d+))?$")
    names = git(repo, "tag", "--list", f"{prefix}*").stdout.split()
    taken = {int(match.group(1) or 1): name for name in names if (match := pattern.match(name))}
    if any(_peel(repo, name) == target for name in taken.values()):
        return []
    n = max(taken, default=0) + 1
    name = prefix if n == 1 else f"{prefix}.{n}"
    created, warns = _create(repo, {name: (str(target), f"{item_id}: the code its receipt tested")})
    return tag_lines(repo, created, push=False) + warns


# --- plan numbers -----------------------------------------------------------------------------------------

def _branch_ids(repo: Path, folder_rel: str) -> List[int]:
    """The plan numbers in ``folder_rel`` on every local and remote-tracking branch."""
    refs = git(repo, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes").stdout.split()
    ids: List[int] = []
    for ref in refs:
        done = git(repo, "ls-tree", "-z", "--name-only", ref, "--", f"{folder_rel}/")
        names = [posixpath.basename(p) for p in done.stdout.split("\0") if p] if done.returncode == 0 else []
        ids += [int(match.group(1)) for name in names if (match := _ID_PREFIX.match(name))]
    return ids


def seen_plan_ids(repo: Path, plans_folder: Path) -> List[int]:
    """Plan numbers on every branch's plans folder and in every ``*/plan/<no>-*`` tag."""
    names = git(repo, "tag", "--list").stdout.split()
    tagged = [int(match.group(1)) for name in names if (match := _PLAN_TAG.match(name))]
    return _branch_ids(repo, rel(repo, plans_folder)) + tagged


# --- the record scheme at HEAD ----------------------------------------------------------------------------

def head_records(repo: Path, plan_name: str, stem: str) -> Optional[str]:
    """The record scheme of the last ``freeze`` entry HEAD holds in the ledger of ``stem`` beside the
    repo path ``plan_name``; None when HEAD holds none."""
    folder = posixpath.join(posixpath.dirname(plan_name), fl.FREEZES_DIR, stem)
    listed = git(repo, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", f"{folder}/")
    found: List[LedgerEntry] = []
    for path in (p for p in listed.stdout.split("\0") if p.endswith(".json")):
        shown = git(repo, "show", f"HEAD:{path}")
        try:
            found.append(LedgerEntry.model_validate(json.loads(shown.stdout)))
        except ValueError:
            continue
    last = fl.last_freeze(found)
    return None if last is None else last.records
