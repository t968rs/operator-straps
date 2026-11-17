"""Guard test: a todo-editor split drafts its spec before it takes the catalog lease, waits for a lease
another split holds, and holds the lease only from its dry run to its reply; retire and refresh still take
it first.

Several split agents then draft at once and apply one after another, each holding the lease for its apply
step alone. The agent file is prose, so the test pins the order of the steps and the commands they name.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

_AGENT = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "agents" / "todo-editor.md"


def _section(name: str) -> str:
    body = _AGENT.read_text(encoding="utf-8")
    assert f"\n## {name}\n" in body, f"todo-editor.md has no {name} section"
    return body.split(f"\n## {name}\n", 1)[1].split("\n## ", 1)[0]


def _steps(section: str) -> List[str]:
    """The numbered steps of a section, each with its continuation lines."""
    return [s for s in re.split(r"\n(?=\d+\. )", section) if re.match(r"\d+\. ", s)]


def _acquire_step(name: str) -> int:
    steps = _steps(_section(name))
    index = next((n for n, step in enumerate(steps) if "TS lease acquire" in step), None)
    assert index is not None, f"todo-editor.md {name} section has no TS lease acquire step"
    return index


def test_split_writes_its_spec_before_it_takes_the_lease() -> None:
    split = _section("split")
    assert split.index("split-<id>.json") < split.index("TS lease acquire")


def test_split_takes_the_lease_right_before_its_dry_run() -> None:
    steps = _steps(_section("split"))
    after = steps[_acquire_step("split") + 1]
    assert "--dry-run" in after


def test_split_waits_for_a_lease_another_run_holds() -> None:
    command = re.search(r"`TS lease acquire ([^`]+)`", _section("split"))
    assert command, "the split section names no lease acquire command"
    assert "--wait 300" in command.group(1)
    assert "3 times" in _section("split"), "a held-lease refusal is retried a bounded number of times"


def test_retire_and_refresh_still_take_the_lease_first() -> None:
    for name in ("retire", "refresh"):
        assert _acquire_step(name) == 0, name


def test_a_one_deliverable_split_stops_without_a_release() -> None:
    reading = next(s for s in _steps(_section("split")) if "independent deliverables" in s)
    assert "release" not in reading


def test_the_rules_say_when_a_split_holds_the_lease() -> None:
    rule = next(r for r in _section("Rules").split("\n- ") if "Queue, never write" in r)
    assert "dry run" in rule
    assert "Retire and refresh" in rule
