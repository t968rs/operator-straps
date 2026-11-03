"""Review-artifact naming and Phase 5 sentinel location, shared by the review hooks and pr-review commands.

Sentinel layout: ``<main checkout>/<state_dir>/pr-review/.phase5_pending_<PR>``. Line 1 is the PR identifier,
line 2 (optional) the unix-int write time, line 3 (optional) the arming session id.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Union

from harness_lib.review_local_models import LABEL_PATTERN, REVIEW_PREFIX

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig

_LABEL_BODY = LABEL_PATTERN.strip("^$")
REVIEW_ARTIFACT_PATTERN = re.compile(rf"^(\d{{4}}|{REVIEW_PREFIX}{_LABEL_BODY})_")
SENTINEL_PREFIX = ".phase5_pending_"
SENTINEL_GLOB = f"{SENTINEL_PREFIX}*"
# Spelled out here, not imported from ``harness_lib.plan_doc.PLAN_SUFFIX``: that module also builds the
# plan_models tree and its model classes, which this module does not need. A test pins the two equal.
PLAN_ARTIFACT_SUFFIX = "_ActionPlan.json"


def is_plan_artifact_name(name: str) -> bool:
    """True iff ``name`` ends in ``_ActionPlan.json``, the plan file suffix.

    Other JSON under the plans directory (a strap ``SkillSpec.json``, research data) is not an ActionPlan
    and is never validated against its schema.
    """
    return name.endswith(PLAN_ARTIFACT_SUFFIX)


def is_review_artifact_name(name: str) -> bool:
    """True iff ``name`` starts with a 4-digit zero-padded PR number, or ``LOCAL_<label>`` (a local review
    keyed ``local-<label>``), and an underscore.

    Example: ``0916_SKILL_pr-review_Phase_4_Mechanics.json``. Auxiliary files in the reviews
    directory (``Catalog.json``, ``BUG_*.json``) do not qualify and are never schema-validated.
    """
    return bool(REVIEW_ARTIFACT_PATTERN.match(name))


def sentinel_dir_under(project: Path, state_dir: str) -> Path:
    """``<main checkout of project>/<state_dir>/pr-review``; usable without a loaded config.

    Sentinels are per repository: a linked worktree resolves to its main checkout, so a sentinel armed
    from a worktree gates the stop of a session opened in the main checkout, and the reverse.
    """
    from harness_lib.project import main_worktree
    return main_worktree(Path(project)) / Path(state_dir) / "pr-review"


def phase5_sentinel_dir(cfg: HarnessConfig) -> Path:
    """Directory holding the repository's Phase 5 sentinels (see ``sentinel_dir_under``)."""
    return sentinel_dir_under(cfg.project_root, cfg.state_dir)


def phase5_sentinel_path(cfg: HarnessConfig, pr: Union[int, str]) -> Path:
    """Sentinel file for ``pr``; the PR value is used verbatim in its string form."""
    return phase5_sentinel_dir(cfg) / f"{SENTINEL_PREFIX}{pr}"
