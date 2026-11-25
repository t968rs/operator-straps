"""The closed vocabularies of an ActionPlan: JSON values, ``str()`` form, status sets, stdlib only."""
from __future__ import annotations

import ast
from pathlib import Path

from harness_lib import plan_enums as pe

ENUMS_FILE = Path(pe.__file__)


def test_member_values_are_the_json_strings_of_a_plan_file() -> None:
    assert [m.value for m in pe.ItemStatus] == [
        "PENDING", "IN_PROGRESS", "COMPLETE", "CLOSED_NO_ACTION", "BLOCKED"]
    assert [m.value for m in pe.ModelName] == ["haiku", "sonnet", "opus"]
    assert [m.value for m in pe.RedException] == [
        "ImportError", "AttributeError", "AssertionError", "NotImplementedError", "TypeError"]
    assert [m.value for m in pe.Priority] == ["critical", "important", "minor"]
    assert [m.value for m in pe.MarkdownSync] == ["pending_markdown_sync", "in_sync"]


def test_a_member_prints_as_its_value() -> None:
    assert str(pe.ItemStatus.COMPLETE) == "COMPLETE"
    assert f"{pe.ModelName.opus} {pe.RedException.TypeError}" == "opus TypeError"


def test_a_member_equals_and_hashes_as_its_string() -> None:
    assert pe.ItemStatus.PENDING == "PENDING"
    assert "BLOCKED" in pe.LANE_OPEN
    assert {"COMPLETE": 1}[pe.ItemStatus.COMPLETE] == 1


def test_the_status_sets_keep_the_membership_the_code_had() -> None:
    complete, closed = pe.ItemStatus.COMPLETE, pe.ItemStatus.CLOSED_NO_ACTION
    pending, started, blocked = pe.ItemStatus.PENDING, pe.ItemStatus.IN_PROGRESS, pe.ItemStatus.BLOCKED
    assert pe.DONE == {complete, closed}
    assert pe.LANE_OPEN == {pending, started, blocked}
    assert pe.RULES_OPEN == {pending, started}


def test_the_module_imports_only_the_standard_library() -> None:
    tree = ast.parse(ENUMS_FILE.read_text(encoding="utf-8"))
    names = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
             for alias in node.names}
    names |= {node.module.split(".")[0] for node in ast.walk(tree)
              if isinstance(node, ast.ImportFrom) and node.module}
    assert names <= {"__future__", "enum", "typing"}
