"""Export an action plan's open items as a parallel2 dispatch plan (``{"target", "lanes"}``).

Pure logic over the loaded ``ActionPlan``: nothing here runs git or touches the file system. Each open item
(``PENDING``, ``IN_PROGRESS``, ``BLOCKED``) becomes one ``implement`` lane whose id is the item id in lower
case with dots as hyphens (``lane_id``) and whose files are the item's files plus the file of each planned
test node, each a repo-relative POSIX path (``parallel_lanes.path_problem``). The lane task is the item
title alone; the dispatcher appends the item's PIP section. Waves follow the dependency chains among open
items; a lane whose files overlap an earlier lane of its wave (``parallel_lanes.entry_overlap``) moves to
the next wave, and its dependents move with it. The result passes ``parallel_lanes.plan_lanes`` unchanged.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence

from harness_lib import parallel_lanes as pl
from harness_lib.plan_enums import LANE_OPEN
from harness_lib.plan_models import ActionItem, ActionPlan

IMPLEMENT_TOOLS = (
    "Read", "Edit", "Write", "Bash(git add *)", "Bash(git commit *)", "Bash(python -m pytest *)",
)

Item = ActionItem


class LanesError(pl.PlanError):
    """An action plan that cannot become lanes; ``problems`` holds one message per defect."""


# --- item fields ------------------------------------------------------------------------------------------

def open_items(plan: ActionPlan) -> List[Item]:
    """Items still to be done, in plan order."""
    return [item for item in plan.items if item.status in LANE_OPEN]


def node_file(node: str) -> str:
    """The repo-relative file of a pytest node id."""
    return node.split("::", 1)[0]


def lane_id(ident: object) -> str:
    """The lane id of an item id: lowercase, dots as hyphens (``TASK-3.2`` -> ``task-3-2``)."""
    return str(ident).lower().replace(".", "-")


def lane_files(item: Item) -> List[str]:
    """The item's files, then each test node's file; deduplicated, order kept."""
    nodes = [node_file(test.node) for test in item.tests]
    return list(dict.fromkeys([*item.files, *nodes]))


def open_dependencies(item: Item, open_ids: Iterable[str]) -> List[str]:
    """Dependencies on open items; a dependency on a finished item is satisfied."""
    wanted = set(open_ids)
    return [dep for dep in item.dependencies or [] if dep in wanted]


# --- problems ---------------------------------------------------------------------------------------------

def _item_problems(item: Item, known: Iterable[str]) -> List[str]:
    ident, names = item.id, set(known)
    problems = [f"item {ident}: unknown dependency {dep}"
                for dep in item.dependencies or [] if dep not in names]
    if pl.id_problem(lane_id(ident)):
        problems.append(f"item {ident}: id does not form a lane id")
    files = lane_files(item)
    if not files:
        problems.append(f"item {ident}: no files")
    problems += [f"item {ident}: path {entry!r} {why}" for entry in files if (why := pl.path_problem(entry))]
    return problems


def _shared_lane_ids(items: Sequence[Item]) -> List[str]:
    """One line per lane id that two or more open items map to."""
    by_lane: Dict[str, List[str]] = {}
    for item in items:
        by_lane.setdefault(lane_id(item.id), []).append(item.id)
    return [f"items {', '.join(idents)} share lane id {lane}"
            for lane, idents in by_lane.items() if len(set(idents)) > 1]


def _cycles(graph: Mapping[str, Sequence[str]]) -> List[List[str]]:
    """Each dependency cycle found by a depth-first walk, as ids from the first back to itself."""
    state: Dict[str, int] = {}
    found: List[List[str]] = []

    def visit(node: str, path: List[str]) -> None:
        state[node] = 1
        for dep in graph[node]:
            if state.get(dep) == 1:
                found.append([*path[path.index(dep):], dep])
            elif dep not in state:
                visit(dep, [*path, dep])
        state[node] = 2

    for node in graph:
        if node not in state:
            visit(node, [node])
    return found


def _graph(items: Sequence[Item]) -> Dict[str, List[str]]:
    ids = [item.id for item in items]
    return {item.id: open_dependencies(item, ids) for item in items}


def plan_problems(plan: ActionPlan) -> List[str]:
    """Every defect that keeps the plan's open items from becoming lanes."""
    every = [item.id for item in plan.items]
    problems = [f"duplicate item id {ident}" for ident in dict.fromkeys(every) if every.count(ident) > 1]
    items = open_items(plan)
    if not items:
        return [*problems, "plan has no open items"]
    for item in items:
        problems += _item_problems(item, every)
    problems += _shared_lane_ids(items)
    problems += [f"dependency cycle: {' -> '.join(cycle)}" for cycle in _cycles(_graph(items))]
    return problems


# --- waves ------------------------------------------------------------------------------------------------

def _depths(graph: Mapping[str, Sequence[str]]) -> Dict[str, int]:
    """1 + the longest dependency chain below each id (the graph is acyclic)."""
    depth: Dict[str, int] = {}

    def walk(node: str) -> int:
        if node not in depth:
            depth[node] = 1 + max((walk(dep) for dep in graph[node]), default=0)
        return depth[node]

    for node in graph:
        walk(node)
    return depth


def _overlaps(files: Sequence[str], others: Sequence[Sequence[str]]) -> bool:
    return any(pl.entry_overlap(a, b) for other in others for a in files for b in other)


def assign_waves(items: Sequence[Item]) -> Dict[str, int]:
    """Wave per item id: after its dependencies, and clear of overlapping lanes placed in that wave."""
    graph = _graph(items)
    depth = _depths(graph)
    order = sorted(range(len(items)), key=lambda index: (depth[items[index].id], index))
    wave: Dict[str, int] = {}
    placed: Dict[int, List[List[str]]] = {}
    for index in order:
        ident, files = items[index].id, lane_files(items[index])
        current = max((wave[dep] + 1 for dep in graph[ident]), default=1)
        while _overlaps(files, placed.get(current, [])):
            current += 1
        wave[ident] = current
        placed.setdefault(current, []).append(files)
    return wave


# --- export -----------------------------------------------------------------------------------------------

def lane_of(item: Item, wave: int) -> Dict[str, Any]:
    """The parallel2 lane dict of one open item."""
    return {
        "id": lane_id(item.id), "kind": pl.IMPLEMENT, "model": item.model.value,
        "task": item.title, "files": lane_files(item), "tools": list(IMPLEMENT_TOOLS),
        "wave": wave,
    }


def lanes_plan(plan: ActionPlan, target: str) -> Dict[str, Any]:
    """The parallel2 plan JSON for the plan's open items; raise ``LanesError`` on a defect."""
    problems = plan_problems(plan)
    if problems:
        raise LanesError(problems)
    items = open_items(plan)
    wave = assign_waves(items)
    return {"target": target, "lanes": [lane_of(item, wave[item.id]) for item in items]}
