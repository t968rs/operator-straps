"""Pin the bubble-stamp mod's memo anchors to ``harness_lib.bubble_memo``.

The mod parses and stamps memos in TypeScript (``plugins/bubble-stamp/hooks/memo.ts``), where the plugin test
sandbox cannot read repository files. This test fails when either side changes an anchor without the other,
and renders a memo with the library to prove the mod's anchors appear in what the script writes.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

import pytest

from harness_lib import bubble_memo as bm
from mods._mods_helpers import ts_string

_MEMO_TS_REL = "plugins/bubble-stamp/hooks/memo.ts"
_ANCHORS: Dict[str, str] = {
    "INDEX_HEADER": bm.INDEX_HEADER,
    "STATUS_OPEN": bm.STATUS_OPEN,
    "STATUS_DECIDED": bm.STATUS_DECIDED,
    "DECISION_OPEN": bm.DECISION_OPEN,
    "DECISION_PREFIX": bm.DECISION_PREFIX,
    "ENTRY_PREFIX": bm.ENTRY_PREFIX,
    "MEMO_SUFFIX": bm.MEMO_SUFFIX,
}


@pytest.fixture(scope="module")
def memo_ts(repo_root: Path) -> str:
    path = repo_root / _MEMO_TS_REL
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(_ANCHORS))
def test_the_mod_anchor_equals_the_library_anchor(memo_ts: str, name: str) -> None:
    assert ts_string(memo_ts, name) == _ANCHORS[name]


def test_the_mod_entry_id_shape_is_the_library_heading_id_shape(memo_ts: str) -> None:
    pattern = ts_string(memo_ts, "ENTRY_ID_PATTERN")
    assert pattern in bm._HEADING_RE.pattern
    assert re.fullmatch(pattern, "I2") and re.fullmatch(pattern, "C10")
    assert not re.fullmatch(pattern, "i2") and not re.fullmatch(pattern, "I")


def test_a_rendered_memo_carries_every_anchor_the_mod_reads(memo_ts: str) -> None:
    issue = {"id": "I2", "name": "Stale cache", "summary": "s", "fix": ["a", "b"],
             "file": "src/a.py", "lines": "1-2"}
    doc = {"pr": 7, "pr_title": "T", "bubbles": ["I2"], "bubble_up": [], "post_review_resolutions": [],
           "issues": {"critical": [], "important": [issue], "minor": []}}
    text = bm.scaffold_memo(doc, bm.currently_bubbled(doc, []))
    assert ts_string(memo_ts, "INDEX_HEADER") in text.splitlines()
    assert ts_string(memo_ts, "DECISION_OPEN") in text.splitlines()
    assert any(line.startswith(ts_string(memo_ts, "ENTRY_PREFIX") + "I2.") for line in text.splitlines())
    assert f"| I2 | unclassified | {ts_string(memo_ts, 'STATUS_OPEN')} |" in text
    assert bm.memo_name(7).endswith(ts_string(memo_ts, "MEMO_SUFFIX"))
