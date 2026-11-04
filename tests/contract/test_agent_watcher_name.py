"""The run-tracking mod is ``agent-watcher`` everywhere it is wired (issue #195).

The manifest, the marketplace entry, the project's enable key, the CI mod-test loop and the matrix-owner note
the pr-review skill checks for all name ``agent-watcher``. No live line names the old mod. Kept: history
(reviews, plans, summaries, logged rows), the hyphenated-name example in ``review_plan``, the source column of
``docs/PROVENANCE.md`` (the path in the source repository keeps its name) and the migration notes, which start
``Renamed from `pr-review-watch```.

The searches run ``git grep``, a route ``tools/select_tests.py`` cannot see; the full run on ``main`` covers a
file that starts naming the old mod.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import REPO_ROOT

OLD = "pr-review-watch"
NEW = "agent-watcher"
MOD = REPO_ROOT / "plugins" / NEW
HISTORY = ("docs/PR_REVIEWS/", "docs/PR_SUMMARIES/", "docs/plans/", "docs/_harness/")
EXAMPLES = (
    "plugins/harness/lib/harness_lib/review_plan.py",
    "tests/lib/test_review_plan.py",
    "tests/contract/test_agent_watcher_name.py",
)
MIGRATION_NOTE = f"Renamed from `{OLD}`"
PROVENANCE_SOURCE = f".claude/mods/{{{OLD},"


def _json(path: Path) -> dict:
    assert path.is_file(), f"{path} is missing"
    return json.loads(path.read_text(encoding="utf-8"))


def _version(text: str) -> tuple:
    return tuple(int(part) for part in text.split("."))


def _grep(*args: str) -> list:
    command = ["git", "-C", str(REPO_ROOT), "grep", "--untracked", *args]
    return subprocess.run(command, capture_output=True, text=True, check=False).stdout.splitlines()


def test_the_manifest_names_agent_watcher() -> None:
    manifest = _json(MOD / ".claude-plugin" / "plugin.json")
    assert manifest["name"] == NEW
    assert _version(manifest["version"]) > (0, 5, 1)


def test_the_marketplace_lists_agent_watcher() -> None:
    plugins = _json(REPO_ROOT / ".claude-plugin" / "marketplace.json")["plugins"]
    entries = {p["name"]: p["source"] for p in plugins}
    assert entries.get(NEW) == f"./plugins/{NEW}"
    assert OLD not in entries


def test_the_project_enables_agent_watcher() -> None:
    enabled = _json(REPO_ROOT / ".claude" / "settings.json")["enabledPlugins"]
    assert enabled.get(f"{NEW}@operator-straps") is True
    assert f"{OLD}@operator-straps" not in enabled


def test_ci_tests_agent_watcher() -> None:
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert f"plugins/{NEW}" in ci
    assert f"plugins/{OLD}" not in ci


def test_the_owner_note_names_agent_watcher() -> None:
    skill_md = REPO_ROOT / "plugins" / "harness" / "skills" / "pr-review" / "SKILL.md"
    note = f"[{NEW}] Matrix rows for this run are recorded by the {NEW} mod"
    assert note in skill_md.read_text(encoding="utf-8")
    assert _grep("-l", "-F", f"'{note}; '", "--", f"plugins/{NEW}/hooks"), f"no hook of {NEW} writes the note"


def _live(hit: str) -> bool:
    path, _, line = hit.partition(":")
    line = line.partition(":")[2]
    if path.startswith(HISTORY) or path in EXAMPLES or MIGRATION_NOTE in line:
        return False
    return not (path == "docs/PROVENANCE.md" and PROVENANCE_SOURCE in line and line.count(OLD) == 1)


def test_no_live_file_names_the_old_mod() -> None:
    live = [hit for hit in _grep("-n", "-E", "pr-review-watch|pr_review_watch") if _live(hit)]
    assert live == [], f"lines still naming {OLD}: {live}"
