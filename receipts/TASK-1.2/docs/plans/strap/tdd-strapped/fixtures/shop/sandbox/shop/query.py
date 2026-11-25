"""Search query strings built from filter dicts."""
from __future__ import annotations

from typing import Dict


def _clause(field: str, value: str) -> str:
    """One ``field:"value"`` clause."""
    return f'{field}:"{value}"'


def build_query(filters: Dict[str, str]) -> str:
    """The query for ``filters``: one clause per field, in key order, joined with AND."""
    return " AND ".join(_clause(field, value) for field, value in sorted(filters.items()))
