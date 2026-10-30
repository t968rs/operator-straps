"""Closed vocabularies of an ActionPlan, standard library only.

``plan_models`` builds the pydantic models on these; ``todo_sync`` and the plan modules import them
here so no status, model or ``red`` name is spelled twice. Each member's value is the JSON string stored in
a plan file, and ``str()`` of a member is that value.
"""
from __future__ import annotations

from enum import StrEnum
from typing import FrozenSet


class ItemStatus(StrEnum):
    """Status of an action item; only `plan.py record` moves an item once its plan is frozen."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    BLOCKED = "BLOCKED"


class ModelName(StrEnum):
    """The model tier that implements an item when it is dispatched."""

    haiku = "haiku"
    sonnet = "sonnet"
    opus = "opus"


class RedException(StrEnum):
    """The exception that fails a planned test before its item is implemented."""

    ImportError = "ImportError"
    AttributeError = "AttributeError"
    AssertionError = "AssertionError"
    NotImplementedError = "NotImplementedError"
    TypeError = "TypeError"


class Priority(StrEnum):
    """Optional severity or priority of an item."""

    critical = "critical"
    important = "important"
    minor = "minor"


class MarkdownSync(StrEnum):
    """Marker that the companion markdown trails the JSON."""

    pending_markdown_sync = "pending_markdown_sync"
    in_sync = "in_sync"


DONE: FrozenSet[ItemStatus] = frozenset({ItemStatus.COMPLETE, ItemStatus.CLOSED_NO_ACTION})
# Items the lanes export still has to do.
LANE_OPEN: FrozenSet[ItemStatus] = frozenset(
    {ItemStatus.PENDING, ItemStatus.IN_PROGRESS, ItemStatus.BLOCKED})
# Items the todo_sync plan rules treat as unfinished (a blocked item is reported elsewhere).
RULES_OPEN: FrozenSet[ItemStatus] = frozenset({ItemStatus.PENDING, ItemStatus.IN_PROGRESS})
