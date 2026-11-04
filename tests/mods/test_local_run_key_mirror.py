"""Pin the mods' review-local run key rule to the harness library.

A review run is keyed by a PR number or by a local key ``local-<label>``. An installed mod cannot import the
harness library, so ``plugins/agent-watcher/hooks/layers/pr-review/runKey.ts`` and
``plugins/bubble-stamp/hooks/review.ts`` copy the key constants of ``harness_lib.review_local_models``, and
``runKey.ts`` copies the run-id rule of
``harness_lib.review_models.RUN_ID`` as a pattern string. This test fails when either side changes without
the other: the constants must be equal, and the TypeScript run-id pattern must accept exactly the run ids the
Python pattern accepts over a sample built from the Python constants.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pytest

from harness_lib.review_local_models import LABEL_MAX, LABEL_PATTERN, LOCAL_PREFIX, REVIEW_PREFIX
from harness_lib.review_models import RUN_ID
from harness_lib.validation.artifact_names import SENTINEL_PREFIX
from mods._mods_helpers import ts_number, ts_string

_RUN_KEY_TS_REL = "plugins/agent-watcher/hooks/layers/pr-review/runKey.ts"
_REVIEW_TS_REL = "plugins/bubble-stamp/hooks/review.ts"
_SENTINELS_TS_REL = "plugins/agent-watcher/hooks/layers/pr-review/sentinels.ts"
_MIRRORS = (_RUN_KEY_TS_REL, _REVIEW_TS_REL)
_PREFIX_BUILDER = "`${REVIEW_PREFIX}${key.slice(LOCAL_PREFIX.length)}_`"
_STAMP = "20261102T080910Z"


def _read(repo_root: Path, rel: str) -> str:
    path = repo_root / rel
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def _ts_pattern(source: str, name: str) -> str:
    """The run-time value of ``export const <name> = '...'`` (the literal may start on the next line)."""
    match = re.search(rf"export const {name} =\s*'([^']*)'", source)
    assert match is not None, f"{name} not found"
    return match.group(1).replace("\\\\", "\\")


def _run_id_samples() -> List[str]:
    """Run ids on both sides of each rule: PR digits, label shape, label length and stamp shape."""
    at_max, over_max = "a" * LABEL_MAX, "a" * (LABEL_MAX + 1)
    keys = [
        "pr1", "pr1234567", "pr12345678", "pr", "prx", f"{LOCAL_PREFIX}x", f"{LOCAL_PREFIX}fix-band-2",
        f"{LOCAL_PREFIX}{at_max}", f"{LOCAL_PREFIX}{over_max}", f"{LOCAL_PREFIX}{at_max[:-2]}-b",
        f"{LOCAL_PREFIX}X", f"{LOCAL_PREFIX}a--b", f"{LOCAL_PREFIX}-a", f"{LOCAL_PREFIX}a-", LOCAL_PREFIX,
        f"{LOCAL_PREFIX}a_b", "standalone", "local_x",
    ]
    stamps = [_STAMP, "20261102T080910", "2026110T080910Z", f"{_STAMP}_1"]
    return [f"{key}_{stamp}" for key in keys for stamp in stamps]


@pytest.mark.parametrize("rel", _MIRRORS)
def test_the_key_constants_equal_review_local_models(repo_root: Path, rel: str) -> None:
    source = _read(repo_root, rel)
    assert ts_string(source, "LOCAL_PREFIX") == LOCAL_PREFIX
    assert ts_string(source, "REVIEW_PREFIX") == REVIEW_PREFIX
    assert ts_string(source, "LABEL_PATTERN") == LABEL_PATTERN
    assert ts_number(source, "LABEL_MAX") == LABEL_MAX


@pytest.mark.parametrize("rel", _MIRRORS)
def test_the_review_prefix_is_built_like_review_file_name(repo_root: Path, rel: str) -> None:
    assert _PREFIX_BUILDER in _read(repo_root, rel)


def test_the_run_id_pattern_accepts_what_review_models_accepts(repo_root: Path) -> None:
    ts_run_id = re.compile(_ts_pattern(_read(repo_root, _RUN_KEY_TS_REL), "RUN_ID_PATTERN"))
    differ = [s for s in _run_id_samples() if bool(ts_run_id.match(s)) != bool(RUN_ID.match(s))]
    assert differ == []
    assert any(RUN_ID.match(s) for s in _run_id_samples() if s.startswith(LOCAL_PREFIX))


def test_the_sentinel_prefix_equals_artifact_names(repo_root: Path) -> None:
    assert ts_string(_read(repo_root, _SENTINELS_TS_REL), "SENTINEL_PREFIX") == SENTINEL_PREFIX
