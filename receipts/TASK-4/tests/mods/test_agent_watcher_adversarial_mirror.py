"""Pin the agent-watcher mod's pr-review ``-a`` vocabulary to the harness library.

An installed mod cannot import the harness library, so
``plugins/agent-watcher/hooks/layers/pr-review/identify.ts`` copies the refuter ``AGENT_ROLE`` values of
``harness_lib.review_briefs`` (``REFUTER_ROLES``), and
``plugins/agent-watcher/hooks/layers/pr-review/matrixRow.ts`` copies the keys it reads from the Workflow args
that ``harness_lib.review_adversarial.workflow_args`` builds (``WORKFLOW_ARG_KEYS``, ``WORKFLOW_GROUPS``,
``WORKFLOW_ROLES``, ``WORKFLOW_SLOT_KEYS``).
This test fails when the mod reads a role, group or key the library no longer writes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pytest

from harness_lib import review_adversarial as ra
from harness_lib.review_briefs import CODE_REFUTER_ROLE, REFUTER_ROLE
from mods._mods_helpers import ts_string_array

_IDENTIFY_TS_REL = "plugins/agent-watcher/hooks/layers/pr-review/identify.ts"
_MATRIX_ROW_TS_REL = "plugins/agent-watcher/hooks/layers/pr-review/matrixRow.ts"
#: The role pr_review.py writes into a reviewer slot's prompt (capture's ``prompt(s.id, "reviewer")``).
_REVIEWER_ROLE = "reviewer"


def _read(repo_root: Path, rel: str) -> str:
    path = repo_root / rel
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def matrix_row_ts(repo_root: Path) -> str:
    return _read(repo_root, _MATRIX_ROW_TS_REL)


@pytest.fixture(scope="module")
def sample_args() -> Dict[str, object]:
    """Workflow args with one entry in every slot array: a reviewer, a pooled code refuter, their refuters."""
    plan = ra.refuter_slots(["runtime"], {"runtime": ["src/a.py"]}, 1)
    reviewers = [{"id": "runtime", "model": "opus", "prompt": "p"}]
    prompts = {slot.id: "p" for slot in (*plan.code, *plan.refute)}
    return ra.workflow_args("1526", "pr1526_20261009T120000Z", reviewers, plan, prompts)


def test_refuter_roles_equal_review_briefs(repo_root: Path) -> None:
    roles = ts_string_array(_read(repo_root, _IDENTIFY_TS_REL), "REFUTER_ROLES")
    assert sorted(roles) == sorted([REFUTER_ROLE, CODE_REFUTER_ROLE])


def test_workflow_roles_follow_the_groups(matrix_row_ts: str) -> None:
    roles = ts_string_array(matrix_row_ts, "WORKFLOW_ROLES")
    groups = ts_string_array(matrix_row_ts, "WORKFLOW_GROUPS")
    assert dict(zip(groups, roles)) == {"reviewers": _REVIEWER_ROLE, "code": CODE_REFUTER_ROLE,
                                        "refute": REFUTER_ROLE}
    assert len(roles) == len(groups)


def test_the_keys_read_are_keys_workflow_args_writes(matrix_row_ts: str,
                                                     sample_args: Dict[str, object]) -> None:
    read = {name for const in ("WORKFLOW_ARG_KEYS", "WORKFLOW_GROUPS")
            for name in ts_string_array(matrix_row_ts, const)}
    assert read <= set(sample_args)


def test_every_slot_entry_carries_the_slot_keys(matrix_row_ts: str, sample_args: Dict[str, object]) -> None:
    slot_keys = set(ts_string_array(matrix_row_ts, "WORKFLOW_SLOT_KEYS"))
    groups: Dict[str, List[Dict[str, object]]] = {
        g: list(sample_args[g]) for g in ts_string_array(matrix_row_ts, "WORKFLOW_GROUPS")  # type: ignore[call-overload]
    }
    assert {g: len(entries) for g, entries in groups.items()} == {"reviewers": 1, "code": 1, "refute": 2}
    assert all(slot_keys <= set(entry) for entries in groups.values() for entry in entries)
