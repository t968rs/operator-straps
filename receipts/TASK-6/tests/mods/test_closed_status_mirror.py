"""Pin the TypeScript closed-status mirrors to ``review_merge.CLOSED_STATUSES``.

agent-watcher's ``bubbles.ts`` (``CLOSING_STATUSES``) and bubble-stamp's ``review.ts`` (``CLOSING_STATUSES``)
and ``memo.ts`` (``STAMPING``) each copy the statuses that close a review issue, since an installed mod
cannot import the harness library. Each array, read from its source, must hold REFUTED and equal the
harness set. The arrays stay unexported; the regex reads the literal.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pytest

from harness_lib import review_merge as rmg

# Full paths spelled out so tools/select_tests.py selects this test when any mirror changes.
_MIRRORS = {
    "agent-watcher-bubbles": "plugins/agent-watcher/hooks/layers/pr-review/bubbles.ts",
    "bubble-stamp-review": "plugins/bubble-stamp/hooks/review.ts",
    "bubble-stamp-memo": "plugins/bubble-stamp/hooks/memo.ts",
}
_ARRAY = re.compile(r"const (CLOSING_STATUSES|STAMPING)[^=]*=\s*\[(.*?)\]", re.S)
_QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"")


def _statuses(source: str) -> List[str]:
    """The string literals of the one closed-status array in ``source``."""
    found = _ARRAY.findall(source)
    assert len(found) == 1, found
    return [a or b for a, b in _QUOTED.findall(found[0][1])]


@pytest.mark.parametrize("rel", list(_MIRRORS.values()), ids=list(_MIRRORS))
def test_the_mirror_holds_refuted_and_equals_the_harness_set(repo_root: Path, rel: str) -> None:
    statuses = _statuses((repo_root / rel).read_text(encoding="utf-8"))
    assert "REFUTED" in statuses, (rel, statuses)
    assert set(statuses) == set(rmg.CLOSED_STATUSES), (rel, statuses)
