"""Add Todo: the dispatch row ``add_todo.py row`` prints for the ``harness:todo-editor`` agent.

The row is the ``agent=`` line, then the prompt's header lines. The session appends the ``Note:`` and
``Context:`` lines, so the developer's text never passes through a command line.

``__all__`` is the surface ``skill_api.py`` binds for an api heredoc.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from harness_lib.add_todo_models import AddTodoRequest, ResearchLevel

__all__ = ["AGENT", "AddTodoRequest", "ResearchLevel", "dispatch_row"]

AGENT = "harness:todo-editor"


def dispatch_row(request: AddTodoRequest, project_root: Path) -> List[str]:
    """The ``agent=`` line and the prompt header for ``request`` in the project at ``project_root``."""
    return [f"agent={AGENT} model={request.research.model}", "SKILL: add-todo", "Operation: add",
            f"Issue: {'yes' if request.issue else 'no'}", f"Research: {int(request.research)}",
            f"Project root: {Path(project_root).resolve().as_posix()}"]
