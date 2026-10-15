"""Shared project shapes for the commit-tooling tests: a floodplain-shaped ``harness.json`` and activation."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional, Union

from conftest import copy_project, project_factory
from harness_lib.config import HarnessConfig, activate, load_config

REGISTRY = "scripts/__tests__/__fixtures__/REGISTRY/testRegistry.json"

# Mirrors the commit buckets the commit tooling shipped with before it read them from configuration.
FPM_CONFIG: Dict[str, object] = {
    "tests": {"roots": ["scripts/__tests__/"], "registry": REGISTRY},
    "commit_buckets": [
        {"bucket": "Artifact", "prefixes": ["docs/PR_REVIEWS/", "docs/PR_SUMMARIES/", ".github/offline/"],
         "names": ["offlineTestReport.json", "summary.json"], "suffixes": ["matrix.jsonl"]},
        {"bucket": "Planning", "prefixes": ["docs/superpowers/", "docs/PLANS/"],
         "names": ["CLAUDE.md", "DesignEvolution.json"]},
        {"bucket": "Agent", "prefixes": [".claude/"]},
        {"bucket": "Cicd", "prefixes": [".github/workflows/", "scripts/__tests__/workflows/",
                                        "scripts/__tests__/shared/"],
         "names": ["checks.yaml", "test_env.txt"]},
        {"bucket": "Test", "prefixes": ["scripts/__tests__/"]},
        {"bucket": "Runtime", "prefixes": ["scripts/fpm/"]},
        {"bucket": "Docs", "prefixes": ["docs/"]},
    ],
}

Files = Optional[Dict[str, Union[str, dict, list]]]


def activate_project(make_project: Callable[..., Path], config: Optional[dict] = None,
                     files: Files = None) -> HarnessConfig:
    """Build a project with ``make_project`` and activate its configuration."""
    return activate(load_config(make_project(config=config, files=files)))


def fpm_template(parent: Path) -> Path:
    """A ``FPM_CONFIG`` project under ``parent``: the module template ``activate_copy`` copies."""
    return project_factory(parent)(config=FPM_CONFIG)


def activate_copy(template: Path, parent: Path) -> HarnessConfig:
    """Copy ``template`` under ``parent`` and activate the copy's configuration."""
    return activate(load_config(copy_project(template, parent)))
