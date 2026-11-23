"""Add Todo: the request the ``add-todo`` skill turns into a ``harness:todo-editor`` dispatch.

A request holds the choices made before the ``--`` token: whether to file a GitHub issue, the research
level, and an optional session hook. The level decides how far the agent reads before it drafts, and which
model it runs on. The hook (``TodoHook``) turns the added item into the session's goal once the item has an
id: the session-bookmark mod reads the hook switch and runs ``/goal`` with ``TodoHook.goal``. The note itself
and the session's context never enter the request: they travel in the prompt only. This module imports no
other ``harness_lib`` module.
"""
from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

MAX_GOAL_CHARS = 500
"""The longest ``/goal`` condition: the approval dialog shows the whole condition."""
MAX_DESC_CHARS = 300
"""The longest hook description; with the id and the closing clause it stays under ``MAX_GOAL_CHARS``."""


class ResearchLevel(IntEnum):
    """How much research the agent does before it drafts the item; ``-r``/``--research`` on the skill."""

    NONE = 0
    LIGHT = 1
    MODERATE = 2
    EXHAUSTIVE = 3

    @property
    def model(self) -> str:
        """The agent model for this level: a cheap model for a reminder, opus once tracing begins."""
        return _MODELS[self]


_MODELS = {ResearchLevel.NONE: "haiku", ResearchLevel.LIGHT: "sonnet", ResearchLevel.MODERATE: "opus",
           ResearchLevel.EXHAUSTIVE: "opus"}


class Closing(StrEnum):
    """What closes a hooked item's session goal; ``--hook`` on the skill, the ``/goal`` evaluator's test.

    ``/goal`` re-checks its condition at every stop, so each condition is one the agent meets by its own
    actions: a condition that waits on the developer's words or commit keeps waking a session with nothing
    left to do. ``committed`` and ``developer`` therefore end at the handoff (tests passed, then a drafted
    commit message or a report to the developer); the developer commits and closes the item.
    """

    RETIRED = "retired"
    COMMITTED = "committed"
    DEVELOPER = "developer"

    @property
    def condition(self) -> str:
        """The clause after the item's name in the goal: what the evaluator must see in the conversation."""
        return _CONDITIONS[self]


_CONDITIONS = {
    Closing.RETIRED: "is retired from the TODO catalog (`todo_sync.py retire` reported it)",
    Closing.COMMITTED: ("is ready to commit: its tests ran by file name and passed, and its commit message "
                        "is drafted (a c-msg or branch-commit-msg receipt)"),
    Closing.DEVELOPER: ("is handed to the developer: its tests ran by file name and passed, and a reply "
                        "lists the files changed and what is left"),
}

PENDING_DESC = "the item this add-todo run adds"
"""A row-time hook's description: the item has no id or title until the inbox drain lands it."""


class TodoHook(BaseModel):
    """An optional session goal tied to one TODO item: the hook switch the session-bookmark mod fires.

    ``start_time`` is epoch seconds (``datetime.timestamp()``); ``todo_id`` is unset until the drain gives the
    item its id.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    closed_by: Closing
    desc: str = Field(min_length=1, max_length=MAX_DESC_CHARS)
    start_time: float
    todo_id: Optional[str] = None

    def goal(self) -> str:
        """The ``/goal`` condition: the item, then its closing clause, at most ``MAX_GOAL_CHARS``."""
        subject = f"TODO {self.todo_id} ({self.desc})" if self.todo_id else self.desc
        return f"{subject} {self.closed_by.condition}"[:MAX_GOAL_CHARS]


class AddTodoRequest(BaseModel):
    """The skill's own arguments: ``--issue``, the research level and ``--hook`` (default: a local reminder,
    no research, no hook)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issue: bool = False
    research: ResearchLevel = ResearchLevel.NONE
    hook: Optional[TodoHook] = None
