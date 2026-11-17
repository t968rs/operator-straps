"""Git plumbing for freeze tags: scoped trees, tag names, tagging and reconcile.

Callers pass plain values (paths, stems, rounds, entry files); nothing here reads the freeze ledger.

``build_tree`` hashes the not-gitignored part of a path set with working-tree content under a temporary
index, so the real index never moves. The name builders give the tag layout of the freeze-tags design
(``base/<stem>/r<N>``, ``<kind>/<stem>/r<N>.<k>-<part>``, ``...-commit.<n>``); none is a directory prefix
of another. ``ensure_tag`` and ``preflight`` refuse a name already on another object. ``reconcile`` tags
the commit that added each committed ledger entry file and never raises. Every git call passes ``-C repo``
and decodes output as UTF-8.

The archive half (``archive/<stem>/r<N>[-<m>]``): ``archive_tag`` names the tag. ``mktree`` builds a tree
of named subtrees from ``git mktree -z``. ``commit_tree`` writes a commit over a tree with every distinct
parent, in first-seen order; its message is fed as bytes (``_run_bytes``) because Windows text-mode stdin
would turn the LF line endings into CRLF, which ``git commit-tree`` stores unchanged. ``archive_tips``
lists the commits the archive tags of one stem peel to (empty, never raising, when git cannot list them);
``reaches`` and ``tree_held`` answer whether those tips keep a commit or a tree reachable, and
``held_trees`` gives the subtree set once for a caller that tests many trees. ``archived_names`` collects
the folded tag names the tips' commit messages list, so a caller can tell a tag an archive folded from
one never made. ``delete_tags`` removes the named local tags that still exist.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

# Written by strap's scenario-tree builder at the root of each throwaway worktree (plan 1015 STRAP item:
# ``build_tree (scenario trees) writes freeze_git.SCENARIO_MARKER``); drivers skip tagging and reconcile
# when the project root holds it.
SCENARIO_MARKER = ".harness-scenario-tree"

PathLike = Union[str, Path]


class FreezeGitError(RuntimeError):
    """A git step of a freeze failed, or a tag name is already on another object."""


def _run(repo: PathLike, *args: str, env: Optional[Mapping[str, str]] = None,
         stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run ``git -C repo <args>`` without raising; output decoded as UTF-8, bad bytes replaced."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=dict(env) if env is not None else None, input=stdin,
    )


def _out(repo: PathLike, *args: str, env: Optional[Mapping[str, str]] = None,
         stdin: Optional[str] = None) -> str:
    """Stdout of ``git -C repo <args>``; raise ``FreezeGitError`` on a non-zero exit."""
    done = _run(repo, *args, env=env, stdin=stdin)
    if done.returncode != 0:
        raise FreezeGitError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def _run_bytes(repo: PathLike, *args: str, stdin: bytes = b"") -> subprocess.CompletedProcess:
    """Run ``git -C repo <args>`` without raising; stdin given as bytes, stdout and stderr left as bytes."""
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, input=stdin)


def _out_bytes(repo: PathLike, *args: str, stdin: bytes = b"") -> str:
    """Stdout (UTF-8) of ``git -C repo <args>`` fed ``stdin`` bytes; ``FreezeGitError`` on a non-zero exit."""
    done = _run_bytes(repo, *args, stdin=stdin)
    if done.returncode != 0:
        raise FreezeGitError(f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout.decode("utf-8", "replace")


def _nul_list(text: str) -> List[str]:
    return [part for part in text.split("\0") if part]


def _ls_files(repo: PathLike, paths: Sequence[str], *flags: str) -> List[str]:
    """``git ls-files -z <flags>`` over literal ``paths``; empty when ``paths`` is empty."""
    if not paths:
        return []
    return _nul_list(_out(repo, "--literal-pathspecs", "ls-files", "-z", *flags, "--", *paths))


def members(repo: PathLike, paths: Sequence[str]) -> Tuple[List[str], List[str]]:
    """``(not_ignored, ignored)``: the files of ``paths`` (directories expand) that exist on disk.

    ``not_ignored`` is what ``git ls-files --cached --others --exclude-standard`` lists; ``ignored`` is
    every other existing file under ``paths``. Both are sorted repo-relative POSIX paths.
    """
    listed = _ls_files(repo, paths, "--cached", "--others", "--exclude-standard")
    not_ignored = sorted({rel for rel in listed if os.path.lexists(Path(repo) / rel)})
    others = _ls_files(repo, paths, "--others", "--ignored", "--exclude-standard")
    ignored = sorted({rel for rel in others if rel not in not_ignored and (Path(repo) / rel).is_file()})
    return not_ignored, ignored


def build_tree(repo: PathLike, paths: Sequence[str]) -> Tuple[str, Dict[str, str]]:
    """``(tree, {path: blob})`` of the not-ignored files of ``paths``, with working-tree content.

    Built under a temporary ``GIT_INDEX_FILE`` (``git add``, ``git write-tree``), so the real index is
    untouched; raise ``FreezeGitError`` when the set is empty or a git step fails.
    """
    not_ignored, _ = members(repo, paths)
    if not not_ignored:
        raise FreezeGitError(f"no not-ignored file among {len(paths)} path(s); the tree would be empty")
    with tempfile.TemporaryDirectory(prefix="freeze-index-") as scratch:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(scratch) / "index")}
        _out(repo, "--literal-pathspecs", "add", "--force", "--pathspec-from-file=-",
             "--pathspec-file-nul", env=env, stdin="\0".join(not_ignored))
        tree = _out(repo, "write-tree", env=env).strip()
        staged = _nul_list(_out(repo, "ls-files", "-z", "--stage", env=env))
    blobs = {}
    for line in staged:
        meta, rel = line.split("\t", 1)
        blobs[rel] = meta.split()[1]
    return tree, blobs


def ignored_digests(repo: PathLike, paths: Sequence[str]) -> Dict[str, str]:
    """``{path: sha256}`` of each existing file of ``paths``, CRLF read as LF (as ``content_hash`` does)."""
    digests = {}
    for rel in paths:
        target = Path(repo) / rel
        if target.is_file():
            digests[rel] = hashlib.sha256(target.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return digests


def base_tag(stem: str, round: int, m: int = 1) -> str:
    """``base/<stem>/r<N>``, or ``base/<stem>/r<N>-<m>`` for the m-th relinked base (m from 2)."""
    return f"base/{stem}/r{round}" if m <= 1 else f"base/{stem}/r{round}-{m}"


def entry_tag(kind: str, stem: str, round: int, seq: int, part: str) -> str:
    """``<kind>/<stem>/r<N>.<k>-<part>``, e.g. ``freeze/plan/0015-x/r1.2-tree``."""
    return f"{kind}/{stem}/r{round}.{seq}-{part}"


def commit_tag(stem: str, n: int) -> str:
    """``<stem>-commit`` for the first commit tag of an entry stem, ``<stem>-commit.<n>`` after a rewrite."""
    return f"{stem}-commit" if n <= 1 else f"{stem}-commit.{n}"


def archive_tag(stem: str, round: int, m: int = 1) -> str:
    """``archive/<stem>/r<N>``, or ``archive/<stem>/r<N>-<m>`` for the m-th archive of a round (m from 2)."""
    return f"archive/{stem}/r{round}" if m <= 1 else f"archive/{stem}/r{round}-{m}"


def _tag_names(repo: PathLike) -> List[str]:
    return [line for line in _out(repo, "tag", "--list").splitlines() if line]


def tag_seqs(repo: PathLike, stem: str, round: int) -> List[int]:
    """The ``k`` values the existing ``<kind>/<stem>/r<N>.<k>-...`` tags of ``stem`` and ``round`` use."""
    pattern = re.compile(rf"^[^/]+/{re.escape(stem)}/r{round}\.(\d+)-")
    return sorted({int(match.group(1)) for name in _tag_names(repo) if (match := pattern.match(name))})


def _peeled(repo: PathLike, name: str) -> Optional[str]:
    """The object the tag ``name`` peels to, or None when no such tag exists."""
    done = _run(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{name}^{{}}")
    return done.stdout.strip() if done.returncode == 0 else None


def _resolve(repo: PathLike, target: str) -> Optional[str]:
    """The full object name of ``target``, or None when it does not resolve."""
    done = _run(repo, "rev-parse", "--verify", "--quiet", f"{target}^{{object}}")
    return done.stdout.strip() if done.returncode == 0 else None


def _conflict(repo: PathLike, name: str, target: str) -> Optional[str]:
    """A problem line when ``name`` cannot point at ``target``; None when it is free or already there."""
    wanted = _resolve(repo, target)
    if wanted is None:
        return f"tag {name}: target {target} does not resolve"
    existing = _peeled(repo, name)
    if existing is None or existing == wanted:
        return None
    return f"tag {name} already points at {existing[:7]}, not {wanted[:7]}"


def preflight(repo: PathLike, wanted: Mapping[str, str]) -> List[str]:
    """Problem lines (no ``problem:`` prefix) for each name of ``wanted`` that exists on another object."""
    return [line for name, target in wanted.items() if (line := _conflict(repo, name, target))]


def ensure_tag(repo: PathLike, name: str, target: str, message: str) -> Optional[str]:
    """Create the annotated tag ``name`` on ``target`` and return ``name``.

    None when the tag already peels to ``target``; ``FreezeGitError`` when it sits on another object or
    git fails.
    """
    problem = _conflict(repo, name, target)
    if problem:
        raise FreezeGitError(problem)
    if _peeled(repo, name) is not None:
        return None
    _out(repo, "tag", "-a", "-m", message, name, target)
    return name


def _adder(repo: PathLike, rel: str) -> Optional[str]:
    """The oldest commit on HEAD's history that added ``rel``; None when none did."""
    log = _out(repo, "--literal-pathspecs", "log", "--diff-filter=A", "--reverse", "--format=%H",
               "HEAD", "--", rel)
    lines = log.split()
    return lines[0] if lines else None


def _commit_tags(repo: PathLike, stem_tag: str) -> Dict[int, str]:
    """``{n: name}`` of the existing ``<stem_tag>-commit[.n]`` tags."""
    pattern = re.compile(rf"^{re.escape(stem_tag)}-commit(?:\.(\d+))?$")
    found = {}
    for name in _tag_names(repo):
        match = pattern.match(name)
        if match:
            found[int(match.group(1) or 1)] = name
    return found


def _on_head(repo: PathLike, commit: Optional[str]) -> bool:
    return commit is not None and _run(repo, "merge-base", "--is-ancestor", commit, "HEAD").returncode == 0


def _reconcile_one(repo: PathLike, stem_tag: str, rel: str) -> Optional[str]:
    """Tag the commit that added ``rel`` when no commit tag of ``stem_tag`` is on HEAD's history."""
    adder = _adder(repo, rel)
    if adder is None:
        return None
    existing = _commit_tags(repo, stem_tag)
    if any(_on_head(repo, _peeled(repo, name)) for name in existing.values()):
        return None
    name = commit_tag(stem_tag, max(existing, default=0) + 1)
    return ensure_tag(repo, name, adder, f"{stem_tag}: the commit that added {rel}")


def reconcile(repo: PathLike, entries: Sequence[Tuple[str, str, bool]]) -> Tuple[List[str], List[str]]:
    """Tag the commits that added ledger entry files; return ``(created, warn lines)``, never raise.

    ``entries`` holds ``(stem_tag, entry_file_rel, history)``. A history entry is skipped, and so, silently,
    is an entry whose file no commit on HEAD's history added. Each warn line starts with ``warn:``.
    """
    created: List[str] = []
    warns: List[str] = []
    if _run(repo, "rev-parse", "--verify", "--quiet", "HEAD").returncode != 0:
        return created, warns
    for stem_tag, rel, history in entries:
        if history:
            continue
        try:
            name = _reconcile_one(repo, stem_tag, rel)
        except (FreezeGitError, OSError) as exc:
            warns.append(f"warn: reconcile {stem_tag}: {exc}")
            continue
        if name:
            created.append(name)
    return created, warns


def _patch_ids(repo: PathLike, log_args: Sequence[str]) -> List[Tuple[str, str]]:
    """``(patch_id, commit)`` pairs of ``git log -p <log_args>``, in log order."""
    patch = _out(repo, "log", "-p", "--no-merges", "--no-color", "--no-ext-diff", "--no-textconv",
                 "--format=commit %H", *log_args)
    if not patch.strip():
        return []
    ids = _out(repo, "patch-id", "--stable", stdin=patch)
    return [(parts[0], parts[1]) for parts in (line.split() for line in ids.splitlines()) if len(parts) == 2]


def patch_id_match(repo: PathLike, old: str) -> Optional[str]:
    """The commit on HEAD's history whose ``git patch-id`` equals ``old``'s; ``old`` itself when on HEAD.

    Only commits of ``old..HEAD`` are searched; the oldest match wins. None when nothing matches, ``old``
    has no patch id (a merge or an empty commit) or a git step fails.
    """
    try:
        resolved = _resolve(repo, f"{old}^{{commit}}")
        if resolved is None:
            return None
        if _on_head(repo, resolved):
            return resolved
        own = _patch_ids(repo, ["-1", resolved])
        if not own:
            return None
        matches = [commit for pid, commit in _patch_ids(repo, [f"{resolved}..HEAD"]) if pid == own[0][0]]
    except FreezeGitError:
        return None
    return matches[-1] if matches else None


def _bad_entry_name(name: str) -> bool:
    return name in ("", ".", "..") or "/" in name or "\0" in name


def mktree(repo: PathLike, entries: Mapping[str, str]) -> str:
    """Tree sha of the subtrees ``entries`` (``{name: tree sha}``, mode 040000); the empty tree for none.

    ``git mktree -z`` reads NUL-joined entries sorted by name, fed as bytes so a name that holds a newline
    stays exact. ``FreezeGitError`` before any git call for an empty name, ``.``, ``..`` or a name holding
    ``/`` or NUL.
    """
    for name in entries:
        if _bad_entry_name(name):
            raise FreezeGitError(f"bad tree entry name {name!r}")
    lines = [f"040000 tree {sha}\t{name}" for name, sha in sorted(entries.items())]
    feed = b"".join(line.encode("utf-8") + b"\0" for line in lines)
    return _out_bytes(repo, "mktree", "-z", stdin=feed).strip()


def commit_tree(repo: PathLike, tree: str, parents: Sequence[str], message: str) -> str:
    """Commit sha of a commit over ``tree`` with one ``-p`` per distinct parent, first-seen order."""
    flags: List[str] = []
    for parent in dict.fromkeys(parents):
        flags += ["-p", parent]
    return _out_bytes(repo, "commit-tree", tree, *flags, "-F", "-", stdin=message.encode("utf-8")).strip()


def _archive_order(stem: str, name: str) -> Optional[Tuple[int, int]]:
    """``(round, m)`` of an ``archive/<stem>/r<N>[-<m>]`` tag name; None for any other name."""
    match = re.fullmatch(rf"archive/{re.escape(stem)}/r(\d+)(?:-(\d+))?", name)
    return (int(match.group(1)), int(match.group(2) or 1)) if match else None


def archive_tips(repo: PathLike, stem: str) -> List[str]:
    """The commits the ``archive/<stem>/r<N>[-<m>]`` tags peel to, by round then m (plain name first).

    Never raises: empty when git cannot list the tags (a folder outside git, a broken repository).
    """
    listed = _run(repo, "tag", "--list", f"archive/{stem}/*")
    if listed.returncode != 0:
        return []
    ranked = sorted((order, name) for name in listed.stdout.splitlines()
                    if (order := _archive_order(stem, name)))
    tips = []
    for _, name in ranked:
        tip = _resolve(repo, f"refs/tags/{name}^{{commit}}")
        if tip is not None:
            tips.append(tip)
    return tips


def reaches(repo: PathLike, tips: Sequence[str], obj: str) -> bool:
    """True when ``obj`` is a commit equal to, or an ancestor of, any of ``tips``; False for no tips."""
    if not tips:
        return False
    commit = _resolve(repo, f"{obj}^{{commit}}")
    if commit is None:
        return False
    return any(_run(repo, "merge-base", "--is-ancestor", commit, tip).returncode == 0 for tip in tips)


def held_trees(repo: PathLike, tips: Sequence[str]) -> Set[str]:
    """Every subtree sha listed by ``git ls-tree -r -d -z`` of any of ``tips``, one git call per tip.

    Only subtrees are listed, so a tip's own root tree is not counted. A tip git cannot list is skipped.
    """
    held: Set[str] = set()
    for tip in tips:
        done = _run(repo, "ls-tree", "-r", "-d", "-z", tip)
        if done.returncode != 0:
            continue
        for entry in _nul_list(done.stdout):
            held.update(entry.split("\t", 1)[0].split()[2:3])
    return held


def tree_held(repo: PathLike, tips: Sequence[str], tree: str) -> bool:
    """True when ``tree`` (a full sha) is in ``held_trees`` of ``tips``."""
    return tree in held_trees(repo, tips)


_FOLDED_LINE = re.compile(r"^(\S+) [0-9a-f]{40}(?:[0-9a-f]{24})?$")


def archived_names(repo: PathLike, tips: Sequence[str]) -> Set[str]:
    """The tag names the ``<name> <sha40>`` lines of the commit messages of ``tips`` list; empty for no tips.

    A ``previous: <archive tag> <sha>`` line has two tokens before the sha, so it never matches and the
    earlier archive is not taken for a folded tag. A tip whose message git cannot read is skipped.
    """
    names: Set[str] = set()
    for tip in tips:
        done = _run(repo, "log", "-1", "--format=%B", tip)
        if done.returncode != 0:
            continue
        for line in done.stdout.splitlines():
            match = _FOLDED_LINE.match(line.strip())
            if match:
                names.add(match.group(1))
    return names


def delete_tags(repo: PathLike, names: Sequence[str]) -> None:
    """``git tag -d`` of the local tags ``names`` that exist; names already gone are skipped.

    No git call when none remain, so a missing name never leaves a partial delete behind a failed call.
    """
    present = [name for name in names if _peeled(repo, name) is not None]
    if present:
        _out(repo, "tag", "-d", *present)


def in_scenario_tree(root: PathLike) -> bool:
    """True when strap's scenario-tree marker (``SCENARIO_MARKER``) sits at ``root``."""
    return (Path(root) / SCENARIO_MARKER).is_file()


def push_line(names: Sequence[str]) -> str:
    """``push: git push origin <names>``; empty when ``names`` is empty."""
    return f"push: git push origin {' '.join(names)}" if names else ""
