"""Pure logic of the parallel2 driver: dispatch plans, wave packing, probe profiles, staging, rendering.

Nothing here runs git or touches the file system. ``scripts/parallel2.py`` owns every side effect and feeds
this module plain data: the plan JSON, the state text, ``CapturedPath`` lists from a capture.

A lane is ``implement`` (writes code, gets a worktree) or read-only (``review``, ``research``). Lane
file entries are repo-relative POSIX paths: a file, a directory (trailing ``/``) or a glob (``*``, ``?``,
``[``). Two lanes of one wave may not overlap.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from fnmatch import fnmatchcase
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from harness_lib.commit_grouping import CapturedPath

IMPLEMENT = "implement"
READ_ONLY = ("review", "research")
KINDS = (IMPLEMENT, *READ_ONLY)
PLANNED, DISPATCHED, STAGED, CLEANED = "planned", "dispatched", "staged", "cleaned"
PROBE_FILE = ".p2_probe"
CHUNK = 100

_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
_GLOB_CHARS = "*?["
_DRIVE = re.compile(r"[A-Za-z]:")
_BASH_TOOL = re.compile(r"Bash\(\s*([^\s:)*]+)")
_SLUG_FOREIGN = re.compile(r"[^A-Za-z0-9._-]")
_TOOLS_NOTE = (
    "If a tool NOT listed here is needed: stop and report it back to the caller instead of prompting."
)
_PROBE_END = "For each action report SUCCESS or BLOCKED (describe what appeared). Do nothing else."


class PlanError(ValueError):
    """A plan or state defect; ``problems`` holds one message per defect."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = list(problems)


@dataclass
class Lane:
    """One lane: plan fields first, then the run state the driver records."""

    id: str
    kind: str
    model: str
    files: List[str]
    tools: List[str]
    wave: Optional[int] = None
    task: str = ""
    status: str = PLANNED
    branch: Optional[str] = None
    worktree: Optional[str] = None
    base_sha: Optional[str] = None
    staged: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Profile:
    """Implement lanes sharing one tool set, probed once."""

    name: str
    tools: Tuple[str, ...]
    lane_ids: Tuple[str, ...]
    model: str


@dataclass(frozen=True)
class StagePlan:
    """Index operations for one lane's changes: paths to check out, paths to remove, report lines."""

    checkout: List[str]
    remove: List[str]
    lines: List[str]
    touched: List[str]


# --- plan parsing -----------------------------------------------------------------------------------------

def target_slug(target: str) -> str:
    """File-system-safe form of a branch name: every character outside ``[A-Za-z0-9._-]`` becomes ``-``."""
    return _SLUG_FOREIGN.sub("-", target)


def path_problem(entry: str) -> Optional[str]:
    """Why ``entry`` is not a repo-relative POSIX path, or None."""
    if not entry:
        return "is empty"
    if entry.startswith("/") or _DRIVE.match(entry):
        return "is absolute"
    if "\\" in entry:
        return "contains a backslash"
    if ".." in entry.split("/"):
        return "has a '..' segment"
    return None


def _wave_value(raw: object) -> Optional[int]:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1 else None


def _string_list(raw: object) -> Optional[List[str]]:
    ok = isinstance(raw, list) and all(isinstance(item, str) for item in raw)
    return list(raw) if ok else None  # type: ignore[arg-type]


def _lane_problems(raw: Mapping[str, Any], label: str) -> List[str]:
    """Defects of one raw lane dict (``label`` names it in messages)."""
    problems: List[str] = []
    if not isinstance(raw.get("id"), str) or not _ID.fullmatch(raw["id"]):
        problems.append(f"{label}: id must match [a-z0-9][a-z0-9-]*")
    if raw.get("kind") not in KINDS:
        problems.append(f"{label}: kind must be one of {', '.join(KINDS)}")
    if not isinstance(raw.get("model"), str) or not raw["model"]:
        problems.append(f"{label}: model must be a non-empty string")
    if not _string_list(raw.get("tools")):
        problems.append(f"{label}: tools must be a non-empty list of strings")
    files = _string_list(raw.get("files", []))
    if files is None:
        problems.append(f"{label}: files must be a list of strings")
    elif raw.get("kind") == IMPLEMENT and not files:
        problems.append(f"{label}: an implement lane needs non-empty files")
    problems += [f"{label}: path {e!r} {why}" for e in files or [] if (why := path_problem(e))]
    if "wave" in raw and _wave_value(raw["wave"]) is None:
        problems.append(f"{label}: wave must be an integer >= 1")
    return problems


def _lane_label(raw: object, index: int) -> str:
    ident = raw.get("id") if isinstance(raw, dict) else None
    return f"lane {ident}" if isinstance(ident, str) and ident else f"lane #{index}"


def _structure_problems(data: object) -> List[str]:
    """Every structural defect of the plan JSON, in lane order."""
    if not isinstance(data, dict):
        return ["plan must be a JSON object"]
    problems: List[str] = []
    target = data.get("target")
    if target is not None and not (isinstance(target, str) and target):
        problems.append("target must be a non-empty string")
    lanes = data.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        return [*problems, "plan has no lanes"]
    seen: Dict[str, int] = {}
    for index, raw in enumerate(lanes, 1):
        if not isinstance(raw, dict):
            problems.append(f"lane #{index}: must be an object")
            continue
        problems += _lane_problems(raw, _lane_label(raw, index))
        seen[str(raw.get("id"))] = seen.get(str(raw.get("id")), 0) + 1
    problems += [f"duplicate lane id {ident}" for ident, count in seen.items() if count > 1]
    waves = [("wave" in raw) for raw in lanes if isinstance(raw, dict)]
    if any(waves) and not all(waves):
        problems.append("wave must be given on all lanes or on none")
    return problems


def _lane_from_plan(raw: Mapping[str, Any]) -> Lane:
    return Lane(
        id=raw["id"], kind=raw["kind"], model=raw["model"], files=list(raw.get("files", [])),
        tools=list(raw["tools"]), wave=raw.get("wave"), task=str(raw.get("task") or ""),
    )


def parse_plan(data: object) -> Tuple[Optional[str], List[Lane]]:
    """Validate the plan structure and return ``(target or None, lanes)``; raise ``PlanError`` otherwise."""
    problems = _structure_problems(data)
    if problems:
        raise PlanError(problems)
    assert isinstance(data, dict)
    return data.get("target"), [_lane_from_plan(raw) for raw in data["lanes"]]


# --- overlap and waves ------------------------------------------------------------------------------------

def _is_glob(entry: str) -> bool:
    return any(char in entry for char in _GLOB_CHARS)


def _is_dir(entry: str) -> bool:
    return entry.endswith("/") and not _is_glob(entry)


def _literal_prefix(glob: str) -> str:
    cut = min((glob.index(char) for char in _GLOB_CHARS if char in glob), default=len(glob))
    return glob[:cut]


def _glob_matches(glob: str, path: str) -> bool:
    return fnmatchcase(path, glob + "*" if glob.endswith("/") else glob)


def _literal_length(entry: str) -> int:
    return len(_literal_prefix(entry) if _is_glob(entry) else entry)


def _more_specific(a: str, b: str) -> str:
    """The entry that narrows the other: the longer literal part, ``a`` on a tie."""
    return b if _literal_length(b) > _literal_length(a) else a


def _glob_pair(a: str, b: str) -> Optional[str]:
    """Overlap witness when at least one of ``a``, ``b`` is a glob."""
    if _is_glob(a) and _is_glob(b):
        pa, pb = _literal_prefix(a), _literal_prefix(b)
        return _more_specific(a, b) if pa.startswith(pb) or pb.startswith(pa) else None
    glob, other = (a, b) if _is_glob(a) else (b, a)
    if _is_dir(other):
        prefix = _literal_prefix(glob)
        return glob if prefix.startswith(other) or other.startswith(prefix) else None
    return other if _glob_matches(glob, other) else None


def entry_overlap(a: str, b: str) -> Optional[str]:
    """The shared entry when two lane file entries overlap, else None.

    Equal entries overlap; a directory overlaps whatever lies under it; a glob overlaps a path it matches;
    two globs (or a glob and a directory) overlap when their literal prefixes nest. The witness is the
    narrower of the two entries.
    """
    if a == b:
        return a
    if _is_glob(a) or _is_glob(b):
        return _glob_pair(a, b)
    if _is_dir(a) and b.startswith(a):
        return b
    if _is_dir(b) and a.startswith(b):
        return a
    return None


def lanes_overlap(a: Lane, b: Lane) -> List[str]:
    """Sorted, deduplicated shared entries of two lanes' file sets."""
    found = {w for ea in a.files for eb in b.files if (w := entry_overlap(ea, eb))}
    return sorted(found)


def _implement(lanes: Sequence[Lane]) -> List[Lane]:
    return [item for item in lanes if item.kind == IMPLEMENT]


def check_wave_overlaps(lanes: Sequence[Lane]) -> List[str]:
    """One problem per overlapping implement pair that shares a wave."""
    problems: List[str] = []
    items = _implement(lanes)
    for index, first in enumerate(items):
        for second in items[index + 1:]:
            shared = lanes_overlap(first, second) if first.wave == second.wave else []
            if shared:
                problems.append(
                    f"overlap: wave {first.wave} lanes {first.id}, {second.id} share {', '.join(shared)}"
                )
    return problems


def pack_waves(lanes: Sequence[Lane]) -> None:
    """Assign waves in place: implement lanes first-fit in input order, read-only lanes to wave 1."""
    placed: Dict[int, List[Lane]] = {}
    for item in lanes:
        if item.kind != IMPLEMENT:
            item.wave = 1
            continue
        wave = 1
        while any(lanes_overlap(item, other) for other in placed.get(wave, [])):
            wave += 1
        item.wave = wave
        placed.setdefault(wave, []).append(item)


def plan_lanes(data: object) -> Tuple[Optional[str], List[Lane]]:
    """Parse the plan, then check the explicit waves for overlap or pack the lanes; raise ``PlanError``."""
    target, lanes = parse_plan(data)
    if all(item.wave is not None for item in lanes):
        problems = check_wave_overlaps(lanes)
        if problems:
            raise PlanError(problems)
    else:
        pack_waves(lanes)
    return target, lanes


# --- probe profiles and plan summary ----------------------------------------------------------------------

def probe_profiles(lanes: Sequence[Lane]) -> List[Profile]:
    """Group implement lanes by sorted, deduplicated tool set; ``P1``.. in first-appearance order."""
    groups: Dict[Tuple[str, ...], List[Lane]] = {}
    for item in _implement(lanes):
        groups.setdefault(tuple(sorted(set(item.tools))), []).append(item)
    return [
        Profile(f"P{number}", tools, tuple(i.id for i in members), members[0].model)
        for number, (tools, members) in enumerate(groups.items(), 1)
    ]


def _wave_line(wave: int, lanes: Sequence[Lane]) -> str:
    members = ", ".join(f"{item.id} ({item.kind}, {item.model})" for item in lanes if item.wave == wave)
    return f"wave {wave}: {members}"


def render_plan_summary(target: str, lanes: Sequence[Lane]) -> str:
    """The text ``plan`` prints: waves, the two prongs and the next command."""
    waves = sorted({item.wave for item in lanes if item.wave is not None})
    implement = [item.id for item in _implement(lanes)]
    read_only = [item.id for item in lanes if item.kind != IMPLEMENT]
    out = [f"target: {target}", *(_wave_line(wave, lanes) for wave in waves)]
    out.append(f"prong 1: worktrees for {', '.join(implement)}" if implement
               else "prong 1: skip (no implement lanes)")
    out += [
        f"prong 2: probe {p.name} [{', '.join(p.tools)}]: {', '.join(p.lane_ids)}"
        for p in probe_profiles(lanes)
    ]
    if read_only:
        out.append(f"prong 2: optional probe for read-only lanes: {', '.join(read_only)}")
    out.append(f"next: setup --wave {waves[0]}")
    return "\n".join(out)


# --- state ------------------------------------------------------------------------------------------------

def dump_state(target: str, lanes: Sequence[Lane]) -> str:
    """JSON text of a run: the target and every lane with its recorded state."""
    return json.dumps({"target": target, "lanes": [asdict(item) for item in lanes]}, indent=2) + "\n"


def load_state(text: str) -> Tuple[str, List[Lane]]:
    """Inverse of ``dump_state``; raise ``PlanError`` when the text is not a state file."""
    try:
        data = json.loads(text)
        names = {f.name for f in fields(Lane)}
        lanes = [Lane(**{k: v for k, v in raw.items() if k in names}) for raw in data["lanes"]]
        return str(data["target"]), lanes
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PlanError([f"state file is not a parallel2 state: {exc}"]) from exc


def unfinished(lanes: Sequence[Lane]) -> List[str]:
    """Ids of lanes not yet cleaned up."""
    return [item.id for item in lanes if item.status != CLEANED]


def has_live_worktree(item: Lane) -> bool:
    """True while a lane's recorded worktree has not been removed."""
    return bool(item.worktree) and item.status != CLEANED


def state_is_spent(lanes: Sequence[Lane]) -> bool:
    """True when no lane keeps a worktree and none still waits to be set up (a later wave)."""
    return not any(has_live_worktree(item) or item.status == PLANNED for item in lanes)


# --- staging ----------------------------------------------------------------------------------------------

def matches_entry(path: str, entry: str) -> bool:
    """True when ``path`` is covered by one lane file entry."""
    if _is_glob(entry):
        return _glob_matches(entry, path)
    return path.startswith(entry) if _is_dir(entry) else path == entry


def matches_entries(path: str, entries: Sequence[str]) -> bool:
    """True when ``path`` is covered by any entry."""
    return any(matches_entry(path, entry) for entry in entries)


def undeclared_paths(changes: Sequence[CapturedPath], entries: Sequence[str]) -> List[str]:
    """Changed paths (both sides of a rename) that no entry covers, in change order."""
    paths = [path for change in changes for path in change.paths]
    return [path for path in dict.fromkeys(paths) if not matches_entries(path, entries)]


def _report_line(change: CapturedPath) -> str:
    if change.old_path:
        return f"{change.status} {change.old_path} -> {change.path}"
    return f"{change.status} {change.path}"


def plan_staging(changes: Sequence[CapturedPath]) -> StagePlan:
    """Map captured changes to index operations: deletions remove, everything else checks out."""
    checkout: List[str] = []
    remove: List[str] = []
    for change in changes:
        if change.status == "D":
            remove.append(change.path)
        else:
            checkout.append(change.path)
            if change.old_path:
                remove.append(change.old_path)
    return StagePlan(
        checkout=checkout, remove=remove, lines=[_report_line(c) for c in changes],
        touched=_touched_in_report_order(changes),
    )


def _touched_in_report_order(changes: Sequence[CapturedPath]) -> List[str]:
    """Every staged path, a rename's old side before its new side."""
    return [path for change in changes for path in (change.old_path, change.path) if path]


def plain_files(entries: Sequence[str]) -> List[str]:
    """Entries naming one file: neither a directory nor a glob."""
    return [entry for entry in entries if not _is_glob(entry) and not _is_dir(entry)]


def chunks(paths: Sequence[str], size: int = CHUNK) -> Iterator[List[str]]:
    """``paths`` in lists of at most ``size`` items."""
    for start in range(0, len(paths), size):
        yield list(paths[start:start + size])


def pending_overlap(changed: Sequence[str], pending: Sequence[str]) -> List[str]:
    """Changed paths that are also pending in the checkout, in change order."""
    pending_set = set(pending)
    return [path for path in changed if path in pending_set]


def pending_in_entries(pending: Sequence[str], entries: Sequence[str]) -> List[str]:
    """Pending paths covered by a lane's file entries, in pending order."""
    return [path for path in pending if matches_entries(path, entries)]


# --- rendering --------------------------------------------------------------------------------------------

def render_brief(item: Lane, workdir: str) -> str:
    """Lane brief: tools, working directory, files, commit rule (implement lanes), task."""
    lines = ["## Pre-Authorized Tools", *(f"- {tool}" for tool in item.tools), _TOOLS_NOTE, ""]
    lines.append(f"Working directory: {workdir}")
    note = "edit only these paths" if item.kind == IMPLEMENT else "read-only lane: no edits, no commits"
    lines += [f"Files ({note}):", *(f"- {entry}" for entry in item.files)]
    if item.kind == IMPLEMENT:
        lines += ["", f"Commit in the worktree branch p2/{item.id}. No push, no merge, no rebase."]
    if item.task:
        lines += ["", f"Task: {item.task}"]
    return "\n".join(lines) + "\n"


def render_dispatch_row(item: Lane, worktree: Optional[str], brief: str) -> str:
    """The two lines printed per dispatched lane."""
    head = f"lane={item.id} model={item.model} kind={item.kind} worktree={worktree or '-'}"
    return f"{head}\nBrief: {brief}"


def render_status_line(item: Lane) -> str:
    """``id wave kind status branch worktree`` with dashes for absent fields."""
    wave = str(item.wave) if item.wave is not None else "-"
    return " ".join([item.id, wave, item.kind, item.status, item.branch or "-", item.worktree or "-"])


def _bash_step(tool: str, worktree: str) -> str:
    match = _BASH_TOOL.match(tool)
    if not match:
        return f"Bash: exercise {tool} once with a harmless call."
    command = match.group(1)
    if command == "git":
        return f'Bash: run `git -C "{worktree}" status --short`.'
    return f"Bash: run `{command} --version`."


def _probe_step(tool: str, worktree: str, read_target: Optional[str], tools: Sequence[str]) -> str:
    probe = f"{worktree}/{PROBE_FILE}"
    if tool == "Read":
        if read_target:
            return f"Read: Read the first 5 lines of {read_target}."
        return "Read: Read any one file in the worktree (first 5 lines)."
    if tool == "Write":
        return f'Write: create {probe} containing "probe".'
    if tool == "Edit":
        note = "" if "Write" in tools else " (report SKIPPED if absent: Write is not in this profile)"
        return f'Edit: change the text of {probe} to "probe-edited"{note}.'
    if tool.startswith("Bash"):
        return _bash_step(tool, worktree)
    return f"{tool}: exercise {tool} once with a harmless call."


def render_probe_prompt(tools: Sequence[str], worktree: str, read_target: Optional[str]) -> str:
    """Prompt for one probe agent: one representative call per tool inside ``worktree``."""
    steps = [_probe_step(tool, worktree, read_target, tools) for tool in tools]
    if "Write" in tools:
        steps.append(
            f"Delete {worktree}/{PROBE_FILE} (Bash rm when authorized; else report that it remains)."
        )
    lines = [f"Working directory: {worktree}", "Exercise one representative call per tool, in this order:"]
    lines += [f"{number}. {step}" for number, step in enumerate(steps, 1)]
    return "\n".join([*lines, _PROBE_END])
