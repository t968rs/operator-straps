"""Review-local: the run key, commit range and review file name of a PR-free review.

A review run is keyed by a PR number or by a local key, ``local-<label>``. Every run-state path, review file
name and sentinel name is built from the key, so a key parses only when it is filesystem-safe: the label is
lower-case letters, digits and single hyphens, at most ``LABEL_MAX`` characters. A local review file is
``LOCAL_<label>_<slug>.json``: the review folder keeps digit prefixes for PR reviews. This module imports no
other ``harness_lib`` module.
"""
from __future__ import annotations

import re
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field

LOCAL_PREFIX = "local-"
REVIEW_PREFIX = "LOCAL_"
LOCAL_STATE = "LOCAL"
LABEL_MAX = 48
LABEL_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
_LABEL = re.compile(LABEL_PATTERN)
_REF = r"^[^\s.\-][^\s]*$"
_NON_LABEL = re.compile(r"[^a-z0-9]+")

RunKey = Union[int, str]


class LocalRange(BaseModel):
    """A ``BASE..HEAD`` commit range; each end is a git revision without whitespace that starts with
    neither a dot nor a dash, so no end reaches git as an option."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base: str = Field(pattern=_REF)
    head: str = Field(pattern=_REF)


def _valid_label(label: str) -> bool:
    return len(label) <= LABEL_MAX and bool(_LABEL.match(label))


def is_local_key(value: object) -> bool:
    """True for a valid ``local-<label>`` key."""
    if not isinstance(value, str) or not value.startswith(LOCAL_PREFIX):
        return False
    return _valid_label(value[len(LOCAL_PREFIX):])


def parse_key(value: RunKey) -> RunKey:
    """A PR number (an int, or a digit string, at least 1) as an int, or a valid ``local-<label>`` key as is.

    Raises ``ValueError`` for anything else.
    """
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    text = str(value)
    if text.isdigit() and int(text) >= 1:
        return int(text)
    if is_local_key(text):
        return text
    raise ValueError(f"{text!r} is neither a PR number nor a {LOCAL_PREFIX}<label> key (label: lower-case "
                     f"letters, digits and single hyphens, at most {LABEL_MAX} characters)")


def key_label(key: str) -> str:
    """The label of a local key; raises ``ValueError`` for anything else."""
    if not is_local_key(key):
        raise ValueError(f"{key!r} is not a {LOCAL_PREFIX}<label> key")
    return key[len(LOCAL_PREFIX):]


def parse_range(text: str) -> LocalRange:
    """``BASE..HEAD`` as a ``LocalRange``; a three-dot range, a missing end or extra dots raise
    ``ValueError``."""
    parts = text.split("..")
    if len(parts) != 2 or "..." in text or not all(parts):
        raise ValueError(f"range {text!r} is not BASE..HEAD")
    return LocalRange(base=parts[0], head=parts[1])


def branch_label(branch: Optional[str], sha: str) -> str:
    """The label a branch name slugs to; ``head-<sha7>`` for a detached HEAD or a name without letters or
    digits."""
    slug = _NON_LABEL.sub("-", (branch or "").lower()).strip("-")
    slug = slug[:LABEL_MAX].rstrip("-")
    return slug if slug else f"head-{sha[:7]}"


def review_file_name(key: str, slug: str) -> str:
    """``LOCAL_<label>_<slug>.json`` for a local key."""
    return f"{REVIEW_PREFIX}{key_label(key)}_{slug}.json"


def review_file_glob(key: str) -> str:
    """The glob of every review file of a local key, ``LOCAL_<label>_*.json``."""
    return f"{REVIEW_PREFIX}{key_label(key)}_*.json"
