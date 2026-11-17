"""terminals.common.schema.json ``output_path``: only repo-relative paths that stay inside the checkout."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def output_path_pattern(plugin_root: Path) -> "re.Pattern[str]":
    schema_path = plugin_root / "skills" / "pr-team" / "terminals.common.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return re.compile(schema["$defs"]["output_path"]["pattern"])


@pytest.mark.parametrize("path", [
    "docs/fixer_1_output.md",
    "docs\\PR_REVIEWS\\out.md",
    "a..b/out.md",
    "out.md",
])
def test_repo_relative_paths_pass(output_path_pattern: "re.Pattern[str]", path: str) -> None:
    assert output_path_pattern.search(path)


@pytest.mark.parametrize("path", [
    "/etc/out.md",
    "\\foo\\out.md",
    "\\\\server\\share\\out.md",
    "//server/share/out.md",
    "C:/x/out.md",
    "C:\\x\\out.md",
    "C:out.md",
    "../out.md",
    "docs/../../out.md",
    "docs\\..\\..\\out.md",
    "..",
])
def test_rooted_drive_unc_and_parent_paths_fail(output_path_pattern: "re.Pattern[str]", path: str) -> None:
    assert not output_path_pattern.search(path)
