"""Environment checks behind ``/harness:doctor``: the interpreter, its modules, the tools and the project.

Nothing here needs a third-party module at import time: the checks exist to run, and to say what is wrong,
when ``pydantic``, ``jsonschema`` or ``referencing`` are missing.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, List, Mapping, Optional, Tuple

if TYPE_CHECKING:
    from harness_lib.config import HarnessConfig

OK, WARN, FAIL = "ok", "warn", "fail"

#: Python the harness targets.
MIN_PYTHON: Tuple[int, int] = (3, 11)

#: Environment variables ``hpy`` reads for an interpreter, in the order it tries them.
INTERPRETER_VARS: Tuple[str, ...] = ("HARNESS_PY", "CLAUDE_PLUGIN_OPTION_PYTHON")

#: (module, v2-only attribute or None, pip requirement); the same list ``pr_review.py`` gates on.
REQUIRED_MODULES: Tuple[Tuple[str, Optional[str], str], ...] = (
    ("pydantic", "model_validator", "pydantic>=2"),
    ("referencing", None, "referencing"),
    ("jsonschema", None, "jsonschema"),
)


@dataclass(frozen=True)
class Check:
    """One finding: ``status`` is ``ok``, ``warn`` or ``fail``; ``fix`` is a command or an instruction."""

    status: str
    name: str
    detail: str
    fix: Optional[str] = None


def check_python() -> Check:
    """The running interpreter's version against the harness floor."""
    found = sys.version_info[:2]
    label = f"{found[0]}.{found[1]} ({sys.executable})"
    if found < MIN_PYTHON:
        return Check(FAIL, "python", f"{label}; the harness targets {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+")
    return Check(OK, "python", label)


def _same_interpreter(configured: str) -> bool:
    resolved = shutil.which(configured) or configured
    return os.path.normcase(os.path.realpath(resolved)) == os.path.normcase(os.path.realpath(sys.executable))


def configured_python(settings: Path) -> Optional[str]:
    """The harness plugin's ``python`` option as recorded in the user settings file, if any."""
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    configs = data.get("pluginConfigs") if isinstance(data, dict) else None
    for key, entry in (configs.items() if isinstance(configs, dict) else ()):
        options = entry.get("options") if key.startswith("harness@") and isinstance(entry, dict) else None
        value = options.get("python") if isinstance(options, dict) else None
        if isinstance(value, str) and value:
            return value
    return None


def _unexported_option(configured: str) -> Check:
    """The ``python`` option is set in user settings, yet the shell ``hpy`` ran in does not carry it."""
    return Check(WARN, "interpreter",
                 f"the harness python option is {configured} in user settings, but this shell does not "
                 f"export it; hpy fell back to {sys.executable}",
                 'set HARNESS_PY to that interpreter under "env" in the project\'s '
                 ".claude/settings.local.json (one project, kept out of git) or in ~/.claude/settings.json "
                 "(every project); the python option is not exported to the shell skill commands run in")


def check_interpreter(environ: Mapping[str, str], configured: Optional[str] = None) -> Check:
    """Which override, if any, picked the running interpreter; a set override ``hpy`` skipped is a warning.

    ``configured`` is the ``python`` option from the user settings: when it names another interpreter and no
    override variable reached the shell, ``hpy`` ignored it, which is a warning too.
    """
    skipped: List[str] = []
    for var in INTERPRETER_VARS:
        value = environ.get(var)
        if not value:
            continue
        if _same_interpreter(value):
            detail = f"{sys.executable} (from {var})"
            if skipped:
                note = f"{', '.join(skipped)} did not start and was skipped"
                fix = "fix or unset the override that was skipped"
                return Check(WARN, "interpreter", f"{detail}; {note}", fix)
            return Check(OK, "interpreter", detail)
        skipped.append(f"{var}={value}")
    if skipped:
        return Check(WARN, "interpreter",
                     f"{', '.join(skipped)} did not start; hpy fell through to {sys.executable}",
                     "point HARNESS_PY (project settings env) or the harness python option at a working "
                     "interpreter")
    if configured and not _same_interpreter(configured):
        return _unexported_option(configured)
    return Check(OK, "interpreter", f"{sys.executable} (PATH fallback; set HARNESS_PY to pin one)")


def _installed(module: str, attr: Optional[str]) -> bool:
    try:
        loaded = importlib.import_module(module)
    except ImportError:
        return False
    return attr is None or hasattr(loaded, attr)


def _version(requirement: str) -> str:
    dist = requirement.split(">=")[0]
    try:
        return f"{dist} {importlib.metadata.version(dist)}"
    except importlib.metadata.PackageNotFoundError:
        return dist


def check_modules() -> Check:
    """Every required module imports; otherwise one pip line naming all that are missing."""
    missing = [req for module, attr, req in REQUIRED_MODULES if not _installed(module, attr)]
    if not missing:
        return Check(OK, "modules", ", ".join(_version(req) for _, _, req in REQUIRED_MODULES))
    pip = f'"{sys.executable}" -m pip install ' + " ".join(f'"{req}"' for req in missing)
    return Check(FAIL, "modules", "missing: " + ", ".join(missing), pip)


def check_tool(name: str, severity: str, needed_by: str) -> Check:
    """``name`` is on PATH; ``severity`` is the status reported when it is not."""
    path = shutil.which(name)
    if path:
        return Check(OK, name, path)
    return Check(severity, name, f"not on PATH; {needed_by}", f"install {name} and reopen the terminal")


def _repository_check(root: Path) -> Check:
    if (root / ".git").exists():
        return Check(OK, "repository", str(root))
    return Check(WARN, "repository", f"{root} is not a git repository; worktree and branch tooling need one",
                 "run the command from inside the project's checkout")


def _config_check(root: Path) -> Tuple[Check, Optional[HarnessConfig]]:
    from harness_lib.config import CONFIG_REL, ConfigError, load_config
    source = root / CONFIG_REL
    try:
        cfg = load_config(root)
    except ConfigError as exc:
        fix = f"repair {source.as_posix()} (schema: config/harness.schema.json)"
        return Check(FAIL, "config", str(exc), fix), None
    rel = CONFIG_REL.as_posix()
    detail = f"{source.as_posix()} loaded" if source.is_file() else f"no {rel}, defaults apply"
    return Check(OK, "config", detail), cfg


def _writable_ancestor(path: Path) -> Path:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def _worktree_root_check(cfg: HarnessConfig) -> Check:
    target = cfg.resolve_worktree_root()
    anchor = _writable_ancestor(target)
    if os.access(anchor, os.W_OK):
        return Check(OK, "worktree_root", str(target))
    return Check(WARN, "worktree_root", f"{target} cannot be created: {anchor} is not writable",
                 "set worktree_root in .claude/harness.json to a writable folder")


def check_project(start: Path) -> List[Check]:
    """Repository, config and worktree-root checks for the project holding ``start``."""
    from harness_lib.project import project_root
    root = project_root(start)
    config, cfg = _config_check(root)
    checks = [_repository_check(root), config]
    if cfg is not None:
        checks.append(_worktree_root_check(cfg))
    return checks


def run_checks(start: Path, environ: Mapping[str, str]) -> List[Check]:
    """Every check, in the order the report lists them."""
    settings = Path(environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
    return [
        check_python(),
        check_interpreter(environ, configured_python(settings)),
        check_modules(),
        check_tool("git", FAIL, "every harness skill needs it"),
        check_tool("gh", WARN, "pr-review, pr-team and pr-sum need it"),
        *check_project(start),
    ]


def summary(checks: List[Check]) -> str:
    """The status line: overall state, the non-ok counts, the number of checks."""
    fails = sum(1 for check in checks if check.status == FAIL)
    warns = sum(1 for check in checks if check.status == WARN)
    state = FAIL if fails else WARN if warns else OK
    parts = [f"{n} {word}" for n, word in ((fails, "fail"), (warns, "warn")) if n]
    counts = ", ".join(parts)
    return f"doctor [{state}] | " + (f"{counts} | " if counts else "") + f"{len(checks)} checks"


def render(checks: List[Check]) -> List[str]:
    """One line per check, with the fix on a continuation line when there is one."""
    lines: List[str] = []
    for check in checks:
        lines.append(f"[{check.status}] {check.name}: {check.detail}")
        if check.fix:
            lines.append(f"       fix: {check.fix}")
    return lines


def exit_code(checks: List[Check]) -> int:
    """1 when any check failed, else 0 (warnings do not fail the run)."""
    return 1 if any(check.status == FAIL for check in checks) else 0
