"""PostToolUse hook (Write|Edit|Bash): validate plan and review JSON artifacts against their schemas.

Reads the hook payload from stdin and resolves the consuming project from its ``cwd``. A target is a
``.json`` file under the project's configured ``artifacts.plans`` directory (``ActionPlan.schema.json``)
or ``artifacts.reviews`` directory (``PR_REVIEW.schema.json``; only names passing
``is_review_artifact_name``, so auxiliary files such as ``Catalog.json`` are skipped). Write/Edit
payloads name the file; Bash payloads are scanned for artifact paths that exist on disk. Schemas
resolve through ``schema_path`` (a project-pinned copy first, else the plugin copy).

Review targets get three further layers after the schema check:

- Layer 2 (incoherence): a ``pending`` ``pre_fix_time`` alongside a READY TO MERGE verdict or any
  ``post_review_resolutions`` blocks.
- Layer 3 (sentinel cleanup): a Phase 5 closeout deletes ``<state_dir>/pr-review/.phase5_pending_<PR>``.
  Never blocks.
- Issue-count tabulation (``validate_issue_counts``) blocks on unaccounted or orphan issue ids.

A stdlib-only pre-check (``_cannot_target``) runs first and exits 0 for an event that cannot name a target,
so ``harness_lib`` and the validators are imported only when one might.

Exit 1 with a stderr report on a violation; exit 0 otherwise. Failure modes that are not a violation
(no target, missing schema, malformed stdin, unusable harness config or git missing from PATH, a payload
without ``tool_input`` such as a Stop event) exit 0. A missing ``jsonschema`` or ``referencing`` exits 0
with a one-line stderr warning naming the missing module.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Pattern, Tuple, Union

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig

_DEFAULTS_PATH = Path(__file__).resolve().parents[1] / "config" / "defaults.json"

_PLAN = ("ActionPlan.schema.json", "ActionPlan")
_REVIEW = ("PR_REVIEW.schema.json", "PR_REVIEW")

# A SHA-shaped token (7-40 hex chars) at the start of resolution evidence. Layer 3 requires one so a
# closeout draft landing before the fixer commits cannot clear the sentinel early.
_SHA_EVIDENCE_PATTERN = re.compile(r"^[0-9a-f]{7,40}( |$)")

# Fallback when the schema shape moves; the schema's const is the single source.
_PENDING_FALLBACK = "pending - to be populated in Phase 4"

_PHASE4_COMMAND = (
    'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" '
    '"${CLAUDE_PLUGIN_ROOT}/skills/pr-review/commands/phase4_branch_safety.py"'
)


def _rel_token(rel: str) -> str:
    """``/<rel>/`` in POSIX form, the segment-bounded substring a target path must contain."""
    return "/" + rel.replace("\\", "/").strip("/") + "/"


def _target_kind(file_path: str, cfg: HarnessConfig) -> Optional[Tuple[str, str]]:
    """``(schema name, label)`` for a plan or review artifact path, else None."""
    from harness_lib.validation.artifact_names import is_review_artifact_name

    norm = "/" + file_path.replace("\\", "/").lstrip("/")
    if not norm.endswith(".json"):
        return None
    if _rel_token(cfg.artifacts.plans) in norm:
        return _PLAN
    if _rel_token(cfg.artifacts.reviews) in norm and is_review_artifact_name(Path(norm).name):
        return _REVIEW
    return None


def _alternation(rels: Iterable[str]) -> str:
    parts = (re.escape(r.replace("\\", "/").strip("/")).replace("/", r"[/\\]") for r in rels)
    return "(?:" + "|".join(parts) + ")"


def _dirs_alternation(cfg: HarnessConfig) -> str:
    return _alternation((cfg.artifacts.plans, cfg.artifacts.reviews))


def _bash_target_pattern(cfg: HarnessConfig) -> Pattern[str]:
    """Path tokens under the plan or review directory, either slash style, with any prefix."""
    return re.compile(r"[^\s'\"]*" + _dirs_alternation(cfg) + r"[/\\][^\s'\"]+?\.json")


def _existing_candidate(token: str, cfg: HarnessConfig) -> Optional[str]:
    """Resolve a path token to an existing file: as given, project-relative, then its artifact-dir tail."""
    root = cfg.project_root
    candidates = [token]
    if not Path(token).is_absolute():
        candidates.append(str(root / token))
    tail = re.search(_dirs_alternation(cfg) + r"[/\\].*", token)
    if tail:
        candidates.append(str(root / tail.group(0)))
    return next((c for c in candidates if Path(c).is_file()), None)


def _resolve_file_paths(tool_input: Dict[str, Any], tool_response: Dict[str, Any],
                        cfg: HarnessConfig) -> List[str]:
    """Target file(s) of a tool event: the explicit ``file_path``, else artifact paths in a Bash command."""
    direct = tool_input.get("file_path") or tool_response.get("filePath")
    if direct:
        return [direct]
    command = tool_input.get("command")
    if not isinstance(command, str) or not command:
        return []
    out: List[str] = []
    for token in _bash_target_pattern(cfg).findall(command):
        resolved = _existing_candidate(token, cfg)
        if resolved and resolved not in out:
            out.append(resolved)
    return out


def _pending_literal(schema: Dict[str, Any]) -> str:
    """The pre_fix_time pending sentinel, read from PR_REVIEW.schema.json's const (fallback if absent)."""
    try:
        canonical = schema["properties"]["verification_log"]["oneOf"][1]
        return canonical["properties"]["pre_fix_time"]["oneOf"][0]["const"]
    except (KeyError, IndexError, TypeError):
        return _PENDING_FALLBACK


def _read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _schema_check(file_path: str, schema_file: Path, cfg: HarnessConfig,
                  label: str) -> Union[int, Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Validate against the schema: ``(data, schema)`` when valid, else the exit code to return."""
    import jsonschema

    from harness_lib.validation.schema_registry import schema_registry

    try:
        data = _read_json(Path(file_path))
        schema = _read_json(schema_file)
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls(schema, registry=schema_registry(cfg)).validate(data)
    except jsonschema.ValidationError as exc:
        where = ".".join(str(p) for p in exc.absolute_path) or "<root>"
        sys.stderr.write(f"{label} SCHEMA VIOLATION in {file_path}\n")
        sys.stderr.write(f"  at path: {where}\n")
        sys.stderr.write(f"  problem: {exc.message}\n")
        return 1
    except Exception as exc:  # noqa: BLE001 - a setup failure is never a violation
        sys.stderr.write(f"Schema validation setup error for {file_path}: {exc}\n")
        return 0
    return data, schema


def _incoherent(file_path: str, data: Dict[str, Any], schema: Dict[str, Any]) -> bool:
    """Layer 2: a still-pending pre_fix_time cannot coexist with a READY verdict or resolutions."""
    verification_log = data.get("verification_log") or {}
    if verification_log.get("pre_fix_time") != _pending_literal(schema):
        return False
    verdict = data.get("verdict") or ""
    if not (verdict.startswith("READY TO MERGE") or data.get("post_review_resolutions")):
        return False
    pr_value = data.get("pr", "<PR>")
    sys.stderr.write(f"PR_REVIEW INCOHERENCE in {file_path}\n")
    sys.stderr.write("  pre_fix_time is still the \"pending\" string but the JSON has progressed "
                     "past Phase 4\n")
    sys.stderr.write("  (verdict starts with \"READY TO MERGE\" and/or post_review_resolutions is "
                     "populated).\n")
    sys.stderr.write(f"  Run: {_PHASE4_COMMAND} {pr_value}\n")
    sys.stderr.write("  and Edit pre_fix_time with the script's stdout before completing the review.\n")
    return True


def _closeout_reason(data: Dict[str, Any]) -> Optional[str]:
    """Why the review counts as a Phase 5 closeout, or None when it does not."""
    from harness_lib.validation.id_handling import all_issues_dispositioned

    resolutions = data.get("post_review_resolutions") or []
    verdict = data.get("verdict") or ""
    has_sha_evidence = any(
        isinstance(r, dict)
        and isinstance(r.get("evidence"), str)
        and _SHA_EVIDENCE_PATTERN.match(r["evidence"])
        for r in resolutions
    )
    if resolutions and not verdict.startswith("NOT READY TO MERGE") and has_sha_evidence:
        return ("post_review_resolutions populated, verdict no longer NOT READY TO MERGE, "
                "at least one SHA-shaped evidence entry present")
    if all_issues_dispositioned(data) and (not resolutions or has_sha_evidence):
        return "every issue id dispositioned via resolutions / bubbles / bubble_up"
    return None


def _clear_sentinel(data: Dict[str, Any], cfg: HarnessConfig) -> None:
    """Layer 3: delete the PR's Phase 5 sentinel on closeout. Never raises, never blocks."""
    from harness_lib.validation.artifact_names import phase5_sentinel_path

    pr_value = data.get("pr")
    reason = _closeout_reason(data) if pr_value is not None else None
    if reason is None:
        return
    sentinel = phase5_sentinel_path(cfg, pr_value)
    if not sentinel.is_file():
        return
    try:
        sentinel.unlink()
        sys.stderr.write(f"Phase 5 sentinel cleared for PR #{pr_value} ({reason})\n")
    except OSError as exc:
        sys.stderr.write(f"Phase 5 sentinel cleanup failed for PR #{pr_value}: {exc}\n")


def _issue_count_check(file_path: str, data: Dict[str, Any]) -> int:
    from harness_lib.validation.pr_json_validation import IssueTabulationError, validate_issue_counts

    try:
        validate_issue_counts(data)
    except IssueTabulationError as exc:
        sys.stderr.write(f"PR_REVIEW ISSUE COUNT VIOLATION in {file_path}\n")
        sys.stderr.write(f"  {exc.message}\n")
        return 1
    return 0


def _validate_target(file_path: str, cfg: HarnessConfig) -> int:
    from harness_lib.project import schema_path

    kind = _target_kind(file_path, cfg)
    if kind is None:
        return 0
    name, label = kind
    schema_file = schema_path(name, cfg)
    if not Path(file_path).is_file() or not schema_file.is_file():
        return 0
    checked = _schema_check(file_path, schema_file, cfg, label)
    if isinstance(checked, int):
        return checked
    data, schema = checked
    if label != _REVIEW[1]:
        return 0
    if _incoherent(file_path, data, schema):
        return 1
    _clear_sentinel(data, cfg)
    return _issue_count_check(file_path, data)


def _read_payload() -> Dict[str, Any]:
    """The hook payload as a dict; empty, non-JSON or non-object stdin reads as {}."""
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _start_dir(payload: Dict[str, Any]) -> Path:
    cwd = payload.get("cwd")
    return Path(cwd) if isinstance(cwd, str) and cwd else Path(os.getcwd())


def _config_dirs(config_file: Path) -> Optional[List[str]]:
    """``artifacts.plans`` and ``artifacts.reviews`` named in a config file, plain ``json`` only.

    None when the file is unreadable or the values are not strings, so the caller runs the full path.
    """
    try:
        artifacts = json.loads(config_file.read_text(encoding="utf-8")).get("artifacts") or {}
        dirs = [artifacts[key] for key in ("plans", "reviews") if key in artifacts]
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    return dirs if all(isinstance(d, str) and d for d in dirs) else None


def _candidate_dirs(start: Path) -> Optional[List[str]]:
    """Every plan or review directory a config near ``start`` could name: the plugin defaults plus each
    ancestor's (and ``CLAUDE_PROJECT_DIR``'s) ``harness.json``. A superset of what ``load_config`` reads."""
    roots = [start, *start.parents]
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        roots.append(Path(os.environ["CLAUDE_PROJECT_DIR"]))
    files = [_DEFAULTS_PATH] + [r / ".claude" / "harness.json" for r in roots]
    out: List[str] = []
    for config_file in (f for f in files if f.is_file()):
        dirs = _config_dirs(config_file)
        if dirs is None:
            return None
        out.extend(dirs)
    return out


def _cannot_target(payload: Dict[str, Any], tool_input: Dict[str, Any],
                   tool_response: Dict[str, Any]) -> bool:
    """True when the event cannot name a plan or review artifact, decided with the stdlib only.

    Runs before any ``harness_lib`` import. A path event needs a ``.json`` path and a Bash event needs a
    ``.json`` token, each under a candidate artifact directory; anything uncertain returns False.
    """
    dirs = _candidate_dirs(_start_dir(payload))
    if dirs is None:
        return False
    under_dir = re.compile(_alternation(dirs) + r"[/\\]")
    direct = tool_input.get("file_path") or tool_response.get("filePath")
    if direct:
        return not (str(direct).endswith(".json") and under_dir.search(str(direct)))
    command = tool_input.get("command")
    return not (isinstance(command, str) and ".json" in command and under_dir.search(command))


def _activate_project(payload: Dict[str, Any]) -> Optional[HarnessConfig]:
    """Activate the harness config of the project holding the payload's ``cwd`` (else the process cwd)."""
    from harness_lib.config import ConfigError, activate, load_config
    from harness_lib.project import project_root

    start = _start_dir(payload)
    try:
        return activate(load_config(project_root(start)))
    except (ConfigError, OSError) as exc:  # OSError: git missing from PATH during the project lookup
        sys.stderr.write(f"validate_pr_json_schema: harness config unusable, skipping ({exc})\n")
        return None


def _missing_validator() -> Optional[str]:
    """Top-level package whose import breaks the validator stack (jsonschema imports referencing),
    else None."""
    for name in ("jsonschema", "referencing"):
        try:
            importlib.import_module(name)
        except ImportError as exc:
            return (exc.name or name).split(".")[0]
    return None


def main() -> int:
    payload = _read_payload()
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    tool_response = payload.get("tool_response")
    tool_response = tool_response if isinstance(tool_response, dict) else {}
    if _cannot_target(payload, tool_input, tool_response):
        return 0
    cfg = _activate_project(payload)
    if cfg is None:
        return 0
    targets = [t for t in _resolve_file_paths(tool_input, tool_response, cfg) if _target_kind(t, cfg)]
    missing = _missing_validator() if targets else None
    if missing:
        sys.stderr.write(
            f"validate_pr_json_schema: {missing} not installed; skipped {len(targets)} file(s)\n"
        )
        return 0
    worst = 0
    for file_path in targets:
        rc = _validate_target(file_path, cfg)
        if rc != 0:
            worst = rc
    return worst


if __name__ == "__main__":
    sys.exit(main())
