"""``plan.py archive``: fold a plan's driver tags into one ``archive/<stem>/r1`` tag (plan 1021, issue 284).

A plan's driver tags are the tags under ``<kind>/<stem>/`` whose first segment is ``base``, ``receipt`` or a
``freeze_ledger.EntryKind`` value (``freeze``, ``lock``, ``unlock``, ``arm``, ``reopen``, ``relink``);
``archive/`` tags never are. The fold builds one commit with git plumbing:

- its tree holds ``receipts/<ITEM>[.n]``, the tree of each ``receipt/<stem>/<ITEM>-tree[.n]`` tag and of
  each ``-commit[.n]`` receipt's commit (the tag's tail, ``<ITEM>-tree[.n]`` or ``<ITEM>-commit[.n]``, when
  an earlier receipt already took the name; never an overwrite), and ``freezes/r1.<k>``, the tree of each
  ``freeze`` or ``lock`` ``r1.<k>-tree`` tag;
- its parents are every distinct base commit (``r1`` and ``r1-<m>``), ``<kind>/<stem>/r1.<k>-commit[.n]``
  commit of any entry kind and receipt commit;
- its message maps each folded tag name to its object, one ``<tag name> <sha40>`` line per tag, by name.

A plan that already has an archive folds again into ``archive/<stem>/r1-<m>`` (D1): ``m`` is one past the
highest existing (the plain name counts as 1), the last archive commit is the first parent, and the message
ends in a ``previous: <archive tag> <sha40>`` line; no tag ever moves. Before any tag is created, each folded
commit must be reachable from the new commit (``freeze_git.reaches``) and each folded tree held in its tree
(``freeze_git.tree_held``); a miss refuses with nothing tagged or deleted. Then the archive tag is created
and the folded local tags are deleted. Inside a strap scenario tree (a linked worktree sharing the main
checkout's tags) the command refuses before any work. Nothing here reconciles a ledger or reads the config.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from harness_lib import freeze_git as fg
from harness_lib import plan_doc as pd
from harness_lib import plan_lock as pk
from harness_lib import plan_models as pm
from harness_lib.branch_capture import git
from harness_lib.freeze_ledger import EntryKind

ROUND = pk.ROUND
KINDS = ("base", "receipt", *(kind.value for kind in EntryKind))
MESSAGE = "Archive of {stem}: every base, receipt and ledger entry object"
UNREACHABLE = "{name} ({sha7}) is not reachable from the archive; nothing tagged or deleted"
_TREE_KINDS = (EntryKind.freeze.value, EntryKind.lock.value)
_RECEIPT = re.compile(r"^(?P<item>.+)-(?P<part>tree|commit)(?:\.(?P<n>\d+))?$")
_ENTRY_TREE = re.compile(rf"^r{ROUND}\.(?P<k>\d+)-tree$")
_ENTRY_COMMIT = re.compile(rf"^r{ROUND}\.\d+-commit(?:\.\d+)?$")
_BASE = re.compile(rf"^r{ROUND}(?:-\d+)?$")


@dataclasses.dataclass
class Fold:
    """The archive commit's parts: subtree entries, parents, and the folded tags each check verifies."""

    receipts: Dict[str, str] = dataclasses.field(default_factory=dict)
    freezes: Dict[str, str] = dataclasses.field(default_factory=dict)
    parents: List[str] = dataclasses.field(default_factory=list)
    commits: Dict[str, str] = dataclasses.field(default_factory=dict)
    trees: Dict[str, str] = dataclasses.field(default_factory=dict)


def _rev(repo: Path, spec: str) -> Optional[str]:
    """The full object name ``spec`` resolves to; None when it does not resolve."""
    done = git(repo, "rev-parse", "--verify", "--quiet", spec)
    return done.stdout.strip() if done.returncode == 0 else None


def _split(name: str, stem: str) -> Optional[Tuple[str, str]]:
    """``(kind, tail)`` of a driver tag ``<kind>/<stem>/<tail>``; None for any other name."""
    kind, _, rest = name.partition("/")
    prefix = f"{stem}/"
    if kind not in KINDS or not rest.startswith(prefix):
        return None
    tail = rest[len(prefix):]
    return (kind, tail) if tail and "/" not in tail else None


def driver_tags(repo: Path, stem: str) -> Dict[str, str]:
    """``{name: peeled object}`` of every driver tag of ``stem``; ``archive/`` tags never."""
    found: Dict[str, str] = {}
    for name in git(repo, "tag", "--list").stdout.splitlines():
        if _split(name, stem) is None:
            continue
        obj = _rev(repo, f"refs/tags/{name}^{{}}")
        if obj is not None:
            found[name] = obj
    return found


def _receipt_key(fold: Fold, name: str, match: re.Match, tail: str) -> str:
    """``<ITEM>[.n]``, else the tag's tail (``<ITEM>-tree[.n]``, ``<ITEM>-commit[.n]``) when that is taken.

    ``PlanError`` when both are taken: no receipt entry is ever overwritten.
    """
    key = f"{match['item']}.{match['n']}" if match["n"] else match["item"]
    for candidate in (key, tail):
        if candidate not in fold.receipts:
            return candidate
    raise pd.PlanError([f"{name}: receipts/{key} and receipts/{tail} are both taken; nothing tagged or "
                        "deleted"])


def _fold_receipt(repo: Path, fold: Fold, name: str, tail: str, obj: str) -> None:
    """Place a receipt tag: its tree (or its commit's tree) under ``receipts``, its commit as a parent."""
    match = _RECEIPT.match(tail)
    if match is not None and match["part"] == "tree":
        fold.receipts[_receipt_key(fold, name, match, tail)] = obj
        fold.trees[name] = obj
        return
    fold.commits[name] = obj
    tree = _rev(repo, f"{obj}^{{tree}}") if match is not None else None
    if match is None or tree is None:
        return
    fold.receipts[_receipt_key(fold, name, match, tail)] = tree
    fold.parents.append(obj)


def _fold_other(fold: Fold, kind: str, name: str, tail: str, obj: str) -> None:
    """Place a base or entry tag: a freeze or lock tree under ``freezes``, a commit as a parent."""
    tree = _ENTRY_TREE.match(tail) if kind in _TREE_KINDS else None
    if tree is not None:
        fold.freezes[f"r{ROUND}.{tree['k']}"] = obj
        fold.trees[name] = obj
        return
    fold.commits[name] = obj
    shape = _BASE if kind == "base" else _ENTRY_COMMIT
    if shape.match(tail):
        fold.parents.append(obj)


def fold_of(repo: Path, stem: str, tags: Dict[str, str]) -> Fold:
    """The fold of ``tags``; receipt trees are placed first, so a commit receipt yields their names.

    A tag of no known shape is placed nowhere and checked as a commit, so the reach check refuses it
    unless the archive reaches its object anyway.
    """
    fold = Fold()
    trees_first = sorted(tags, key=lambda name: (not _is_receipt_tree(name, stem), name))
    for name in trees_first:
        kind, tail = _split(name, stem) or ("", "")
        if kind == "receipt":
            _fold_receipt(repo, fold, name, tail, tags[name])
        else:
            _fold_other(fold, kind, name, tail, tags[name])
    return fold


def _is_receipt_tree(name: str, stem: str) -> bool:
    split = _split(name, stem)
    match = _RECEIPT.match(split[1]) if split and split[0] == "receipt" else None
    return match is not None and match["part"] == "tree"


def next_archive(repo: Path, stem: str) -> Tuple[str, Optional[Tuple[str, str]]]:
    """The new archive tag name and, on a re-archive, ``(previous archive tag, its commit)``.

    The previous commit is resolved from the previous tag's own name; ``PlanError`` when it does not peel
    to a commit.
    """
    if not fg.archive_tips(repo, stem):
        return fg.archive_tag(stem, ROUND), None
    pattern = re.compile(rf"^archive/{re.escape(stem)}/r{ROUND}(?:-(\d+))?$")
    names = git(repo, "tag", "--list", f"archive/{stem}/*").stdout.splitlines()
    top = max((int(match.group(1) or 1) for name in names if (match := pattern.match(name))), default=1)
    previous = fg.archive_tag(stem, ROUND, top)
    commit = _rev(repo, f"refs/tags/{previous}^{{commit}}")
    if commit is None:
        raise pd.PlanError([f"archive tag {previous} does not resolve to a commit; nothing tagged or "
                            "deleted"])
    return fg.archive_tag(stem, ROUND, top + 1), (previous, commit)


def _message(stem: str, tags: Dict[str, str], previous: Optional[Tuple[str, str]]) -> str:
    lines = [f"{name} {tags[name]}" for name in sorted(tags)]
    if previous is not None:
        lines.append(f"previous: {previous[0]} {previous[1]}")
    return "\n".join([MESSAGE.format(stem=stem), "", *lines]) + "\n"


def build(repo: Path, stem: str, tags: Dict[str, str],
          previous: Optional[Tuple[str, str]]) -> Tuple[str, Fold]:
    """``(archive commit, fold)``: the trees and the commit over them, built inside the identity fallback."""
    fold = fold_of(repo, stem, tags)
    parents = ([previous[1]] if previous is not None else []) + fold.parents
    try:
        with pk.tagger(repo):
            subtrees = {key: fg.mktree(repo, entries) for key, entries in
                        (("receipts", fold.receipts), ("freezes", fold.freezes)) if entries}
            root = fg.mktree(repo, subtrees)
            commit = fg.commit_tree(repo, root, parents, _message(stem, tags, previous))
    except (fg.FreezeGitError, OSError) as exc:
        raise pd.PlanError([str(exc)]) from None
    return commit, fold


def unreachable(repo: Path, commit: str, fold: Fold) -> List[str]:
    """A problem per folded commit the archive does not reach and per folded tree it does not hold."""
    tips = [commit]
    missed = {name: obj for name, obj in fold.commits.items() if not fg.reaches(repo, tips, obj)}
    held = fg.held_trees(repo, tips)
    missed.update({name: obj for name, obj in fold.trees.items() if obj not in held})
    return [UNREACHABLE.format(name=name, sha7=missed[name][:7]) for name in sorted(missed)]


def _tag_and_delete(repo: Path, stem: str, name: str, commit: str, folded: List[str]) -> None:
    """Preflight and create the annotated archive tag, then delete the folded local tags.

    A failed delete names the created archive tag and the ``git tag -d`` that finishes the job.
    """
    message = f"{stem}: archive of round {ROUND}"
    pk.preflight(repo, {name: (commit, message)})
    try:
        with pk.tagger(repo):
            fg.ensure_tag(repo, name, commit, message)
    except (fg.FreezeGitError, OSError) as exc:
        raise pd.PlanError([str(exc)]) from None
    try:
        fg.delete_tags(repo, folded)
    except (fg.FreezeGitError, OSError) as exc:
        left = [tag for tag in folded if _rev(repo, f"refs/tags/{tag}") is not None]
        raise pd.PlanError([f"archive tag {name} -> {commit[:7]} created; deleting the folded tags failed: "
                            f"{exc}", f"finish with: git tag -d {' '.join(left)}"]) from None


def archive_lines(plan_id: str, name: str, commit: str, folded: List[str], remote: bool) -> List[str]:
    """The status, ``tag:``, ``push:`` and ``deleted:`` lines, and with ``remote`` the remote delete line."""
    lines = [f"archive [done] | plan {plan_id} | {name} -> {commit[:7]} | folded {len(folded)} tag(s)",
             f"tag: {name} -> {commit[:7]}", fg.push_line([name]), f"deleted: {' '.join(folded)}"]
    pushed = [tag for tag in folded if not tag.startswith("receipt/")]
    if remote and pushed:
        lines.append(f"remote: git push origin --delete {' '.join(pushed)}")
    return lines


def archive(repo: Path, plan_file: Path, plan: pm.ActionPlan, remote: bool = False) -> List[str]:
    """Fold the plan's driver tags into one archive tag; the output lines. ``PlanError`` on a refusal."""
    stem = pk.stem_of(plan_file, plan)
    if fg.in_scenario_tree(repo):
        raise pd.PlanError(["plan.py archive does not run inside a strap scenario tree; nothing tagged or "
                            "deleted"])
    tags = driver_tags(repo, stem)
    if not tags:
        raise pd.PlanError([f"plan {plan.plan_id} has no driver tags to archive"])
    name, previous = next_archive(repo, stem)
    commit, fold = build(repo, stem, tags, previous)
    problems = unreachable(repo, commit, fold)
    if problems:
        raise pd.PlanError(problems)
    folded = sorted(tags)
    _tag_and_delete(repo, stem, name, commit, folded)
    return archive_lines(plan.plan_id, name, commit, folded, remote)
