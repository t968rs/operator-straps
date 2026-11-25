"""URL slugs for product titles."""
from __future__ import annotations

import re


def slug(title: str) -> str:
    """The lower-case slug of ``title``: words joined by single hyphens, no other punctuation."""
    text = re.sub(r"[^a-z0-9 -]", "", title.lower())
    return text.strip().replace(" ", "-")
