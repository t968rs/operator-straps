"""The TODO sync error type, outside the package ``__init__`` so any submodule imports it without a cycle."""
from __future__ import annotations


class TodoSyncError(ValueError):
    """A request the engine cannot serve (inactive feature, bad rule id, render target refused)."""
