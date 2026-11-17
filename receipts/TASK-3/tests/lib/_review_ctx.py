"""Shared reviewer-brief context for the ``harness_lib.review_briefs`` tests."""
from __future__ import annotations

from pathlib import Path

from harness_lib import review_briefs as rb
from harness_lib import review_plan as rp
from harness_lib.pr_summary import PrFacts, PrFile


def brief_ctx(root: Path) -> rb.BriefContext:
    """A brief context over a one-file PR at a fixed head, rooted at ``root``."""
    facts = PrFacts(1234, "demo", "1234-demo", "main", "a" * 40, "b" * 40, "", (),
                    (PrFile("M", "src/a.py", None, 2, 1),))
    return rb.BriefContext(root.as_posix(), (root / "lib").as_posix(), 1234, "pr1234_20990101T000000Z",
                           facts, True, rp.load_lens_catalog(), ())
