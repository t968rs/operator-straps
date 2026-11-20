"""Name constants of a local review: the review file prefix and the label pattern.

Standard library only, so the Stop and schema hooks import them through ``validation.artifact_names`` without
loading ``pydantic``. ``review_local_models`` re-exports both.
"""
from __future__ import annotations

REVIEW_PREFIX = "LOCAL_"
LABEL_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
