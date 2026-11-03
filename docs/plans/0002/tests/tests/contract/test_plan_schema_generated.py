"""``ActionPlan.schema.json`` is generated from the models; no second definition of a plan's shape remains."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import pydantic
import pytest

from harness_lib import plan_models as pm

PLAN_MODULES = (
    "plugins/harness/lib/harness_lib/plan_doc.py",
    "plugins/harness/lib/harness_lib/plan_checks.py",
    "plugins/harness/lib/harness_lib/plan_render.py",
    "plugins/harness/lib/harness_lib/plan_lanes.py",
    "plugins/harness/lib/harness_lib/plan_red.py",
    "plugins/harness/lib/harness_lib/plan_api.py",
    "plugins/harness/scripts/plan.py",
    "plugins/harness/lib/harness_lib/todo_sync/rules_plans.py",
)
LITERAL = re.compile(
    r"""["'](?:PENDING|IN_PROGRESS|COMPLETE|CLOSED_NO_ACTION|BLOCKED|haiku|sonnet|opus)["']""")
PYDANTIC_LINE = re.compile(r"^pydantic(?:==([\d.]+)|>=([\d.]+),<([\d.]+))$", re.MULTILINE)


def _series(version: str) -> Tuple[int, int]:
    """Major and minor of ``version``; a missing minor counts as 0."""
    major, minor = (version.split(".") + ["0"])[:2]
    return int(major), int(minor)


def _schemas(repo_root: Path) -> Path:
    return repo_root / "plugins" / "harness" / "schemas"


def test_the_committed_schema_equals_the_one_the_models_generate(repo_root: Path) -> None:
    committed = json.loads((_schemas(repo_root) / "ActionPlan.schema.json").read_text(encoding="utf-8"))
    assert committed == pm.schema_dict()


def test_the_generator_tool_finds_no_drift(repo_root: Path) -> None:
    done = subprocess.run([sys.executable, str(repo_root / "tools" / "gen_plan_schema.py"), "--check"],
                          capture_output=True, text=True, cwd=repo_root)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_pr_attributes_schema_file_is_gone(repo_root: Path) -> None:
    assert not (_schemas(repo_root) / "prAttributes.schema.json").exists()


@pytest.mark.parametrize("module", PLAN_MODULES)
def test_a_plan_module_spells_no_status_or_model_name_as_a_literal(repo_root: Path, module: str) -> None:
    lines: List[str] = (repo_root / module).read_text(encoding="utf-8").splitlines()
    hits = [f"{n}: {line.strip()}" for n, line in enumerate(lines, 1) if LITERAL.search(line)]
    assert hits == [], "use harness_lib.plan_enums"


def test_the_dev_requirements_bound_pydantic_to_the_series_the_schema_was_generated_with(
        repo_root: Path) -> None:
    """The pin's series is the running pydantic's, which the equality test ties to the committed schema."""
    text = (repo_root / "requirements-dev.txt").read_text(encoding="utf-8")
    found = PYDANTIC_LINE.search(text)
    assert found, "requirements-dev.txt pins pydantic (==X.Y.Z) or bounds it (>=X.Y,<X.Y+1)"
    running = _series(pydantic.VERSION)
    pinned, low, high = found.groups()
    if pinned is not None:
        assert _series(pinned) == running
    else:
        assert _series(low) == running and _series(high) == (running[0], running[1] + 1)


def test_the_schema_readme_names_the_generator_and_no_plan_py_subcommand(repo_root: Path) -> None:
    text = (_schemas(repo_root) / "README.md").read_text(encoding="utf-8")
    assert "tools/gen_plan_schema.py" in text and "plan.py schema" not in text
    assert "prAttributes.schema.json" not in text.split("## Migration", 1)[0]
