"""Add Todo: the request the ``add-todo`` skill turns into a ``harness:todo-editor`` dispatch.

A request holds the two choices made before the ``--`` token: whether to file a GitHub issue, and the
research level. The level decides how far the agent reads before it drafts, and which model it runs on. The
note itself and the session's context never enter the request: they travel in the prompt only. This module
imports no other ``harness_lib`` module.
"""
from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, ConfigDict


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


class AddTodoRequest(BaseModel):
    """The skill's own arguments: ``--issue`` and the research level (default: a local reminder, no
    research)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issue: bool = False
    research: ResearchLevel = ResearchLevel.NONE
