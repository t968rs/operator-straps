"""The agent usage log and its schema carry the generic name ``agent_usage`` (issue #192).

The log records every Agent dispatch, not only pr-review ones, so its default path, its schema file, the
canned review-artifact commit message and the repository's own log all use ``agent_usage``.
"""
from __future__ import annotations

import json

from conftest import PLUGIN_ROOT, REPO_ROOT
from harness_lib.canned_messages import has_canned_message
from harness_lib.config import load_config

NEW_LOG = "docs/_harness/agent_usage.jsonl"
OLD_LOG = "docs/_harness/pr_review_agent_usage.jsonl"
SCHEMA = PLUGIN_ROOT / "schemas" / "agent_usage.schema.json"


def test_default_usage_path_is_agent_usage(make_project) -> None:
    assert load_config(make_project()).agent_usage_path == NEW_LOG


def test_schema_file_is_agent_usage() -> None:
    assert SCHEMA.is_file(), f"{SCHEMA} is missing"
    assert json.loads(SCHEMA.read_text(encoding="utf-8"))["$id"].endswith("/schemas/agent_usage.schema.json")
    assert not (PLUGIN_ROOT / "schemas" / "pr_review_agent_usage.schema.json").exists()


def test_canned_message_covers_the_new_log() -> None:
    assert has_canned_message([NEW_LOG, "docs/_harness/pr_review_invocation_test_matrix.jsonl"])


def test_the_usage_log_moved() -> None:
    assert (REPO_ROOT / NEW_LOG).is_file(), f"{NEW_LOG} is missing"
    assert not (REPO_ROOT / OLD_LOG).exists()
