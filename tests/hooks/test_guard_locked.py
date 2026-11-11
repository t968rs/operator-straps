"""Plan 1015 GRD-1: the lock guard ``plugins/harness/hooks/guard_locked.py`` and its three dispatchers.

``guard_locked.decide(payload)`` returns a PreToolUse deny JSON or None. It denies a write to any file under
``<artifacts.plans>/freezes/`` and to any path a Locked or armed subject's ledger lists
(``freeze_ledger.locked_files``), for the Write and Edit tools and, best-effort, for Bash and PowerShell
commands. Ledgers are the LED-1 store: one JSON file per entry under ``<plans>/freezes/<stem>/``, with stems
``plan/<no>-<slug>`` and ``skill/<name>``. Every path outside ``<artifacts.plans>`` passes at once, locked or
not, and a target written with backslashes is normalized before the test. The hook and
``harness_lib.freeze_ledger`` (LED-1) are loaded inside each test, so before the work the behavior tests fail
with ImportError and the registration test fails on its asserts.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Tuple

from conftest import PLUGIN_ROOT

HOOKS = PLUGIN_ROOT / "hooks"
GUARD = HOOKS / "guard_locked.py"
HOOKS_JSON = HOOKS / "hooks.json"
DISPATCHERS = ("bash_pretool.py", "write_pretool.py", "powershell_pretool.py")
_IMPORTS_GUARD = re.compile(r"^\s*(?:import\s+guard_locked\b|from\s+guard_locked\s+import\b)", re.MULTILINE)

PLANS = "docs/PLANS"
LOCKED_PLAN = f"{PLANS}/0001_demo_ActionPlan.json"
PLANNED_TEST = f"{PLANS}/0001/tests/tests/test_demo.py"
RECEIPT = f"{PLANS}/0001/receipts/DEMO-1.json"
FROZEN_PLAN = f"{PLANS}/0002_other_ActionPlan.json"
ARMED_PLAN = f"{PLANS}/0003_armed_ActionPlan.json"
ARMED_TEST = f"{PLANS}/0003/tests/tests/test_armed.py"
UNLOCKED_PLAN = f"{PLANS}/0004_reopened_ActionPlan.json"
SKILL_SPEC = f"{PLANS}/strap/demo/SkillSpec.json"
SKILL_TEST = f"{PLANS}/strap/demo/tests/test_demo_contract.py"
STRAP_PART = "plugins/demo/skills/demo/SKILL.md"
OUTSIDE = "src/app.py"
_TEST_TEXT = "def test_demo() -> None:\n    assert True\n"
_AT = "2026-11-11T10:00:00+00:00"


def _load() -> Tuple[ModuleType, ModuleType]:
    """``(guard_locked, freeze_ledger)``; ImportError until GRD-1 and LED-1 are built."""
    if not GUARD.is_file():
        raise ImportError(f"{GUARD.name} is not built yet (plan 1015 GRD-1)")
    ledger = importlib.import_module("harness_lib.freeze_ledger")
    spec = importlib.util.spec_from_file_location("guard_locked", GUARD)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {GUARD}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["guard_locked"] = module
    spec.loader.exec_module(module)
    return module, ledger


def _blob(text: str) -> str:
    """The git blob SHA of ``text`` as UTF-8."""
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry(ledger: ModuleType, kind: str, seq: int, files: Optional[Dict[str, str]] = None,
           ignored: Optional[Dict[str, str]] = None, strap: bool = False) -> Any:
    """One round-1 entry; ``arm`` and ``unlock`` carry no tree and no files, as LED-1 defines them."""
    treeless = kind in ("arm", "unlock")
    plan_seal, strap_seal = not (strap or treeless), strap and not treeless
    return ledger.LedgerEntry(
        kind=kind, round=1, seq=seq, tree=None if treeless else "a" * 40,
        files={} if treeless else dict(files or {}), ignored={} if treeless else dict(ignored or {}),
        at=_AT, base="b" * 40, digest="d" * 64 if plan_seal else None,
        records="receipts" if plan_seal else None, skill_hash="e" * 64 if strap_seal else None,
        grader="strap-judge" if strap_seal else None,
        reason="design change approved" if kind == "arm" else None)


def _write_ledger(ledger: ModuleType, plans_dir: Path, stem: str, entries: List[Any]) -> List[Path]:
    """Write each entry into the stem's ledger folder; returns the entry files."""
    folder = ledger.ledger_dir(plans_dir, stem)
    return [ledger.write_entry(folder, entry) for entry in entries]


def _plan_entries(ledger: ModuleType, plan: str, test: Optional[str], kinds: Tuple[str, ...]) -> List[Any]:
    """Entries of ``kinds`` in order over the plan JSON and, when given, its untracked planned test."""
    files = {plan: _blob("{}\n")}
    ignored = {} if test is None else {test: _sha256(_TEST_TEXT)}
    return [_entry(ledger, kind, seq, files, ignored) for seq, kind in enumerate(kinds, start=1)]


def _seed_ledgers(ledger: ModuleType, plans_dir: Path) -> List[Path]:
    """Plan 0001 locked, 0002 frozen, 0003 locked and armed, 0004 unlocked; strap ``demo`` locked."""
    written: List[Path] = []
    for no, slug, plan, test, kinds in (
            ("0001", "demo", LOCKED_PLAN, PLANNED_TEST, ("freeze", "lock")),
            ("0002", "other", FROZEN_PLAN, None, ("freeze",)),
            ("0003", "armed", ARMED_PLAN, ARMED_TEST, ("freeze", "lock", "arm")),
            ("0004", "reopened", UNLOCKED_PLAN, None, ("freeze", "lock", "arm", "unlock"))):
        stem = ledger.plan_stem(no, slug)
        written += _write_ledger(ledger, plans_dir, stem, _plan_entries(ledger, plan, test, kinds))
    parts = {STRAP_PART: _blob("# demo\n")}
    lock_files = {**parts, SKILL_SPEC: _blob("{}\n")}
    skill_ignored = {SKILL_TEST: _sha256(_TEST_TEXT)}
    written += _write_ledger(ledger, plans_dir, ledger.skill_stem("demo"), [
        _entry(ledger, "freeze", 1, parts, skill_ignored, strap=True),
        _entry(ledger, "lock", 2, lock_files, skill_ignored, strap=True)])
    return written


def _project(make_project, monkeypatch) -> Tuple[Path, ModuleType, List[Path]]:
    """A project seeded by ``_seed_ledgers``; returns the root, the guard and the ledger entry files.

    The planned tests and the strap contract test stay untracked, recorded in ``ignored`` by sha256.
    """
    guard, ledger = _load()
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    root = make_project({}, files={LOCKED_PLAN: "{}\n", FROZEN_PLAN: "{}\n", ARMED_PLAN: "{}\n",
                                   UNLOCKED_PLAN: "{}\n", SKILL_SPEC: "{}\n", STRAP_PART: "# demo\n",
                                   OUTSIDE: "x = 1\n"})
    for rel in (PLANNED_TEST, ARMED_TEST, SKILL_TEST):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(_TEST_TEXT.encode("utf-8"))
    written = _seed_ledgers(ledger, root / PLANS)
    return root, guard, written


def _payload(root: Path, tool: str, tool_input: Dict[str, str]) -> Dict[str, Any]:
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(root), "tool_input": tool_input}


def _output(guard: ModuleType, payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """The parsed ``hookSpecificOutput`` of ``guard.decide``, or None when it makes no decision."""
    raw = guard.decide(payload)
    if raw is None:
        return None
    out = json.loads(raw)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    return out


def _decision(guard: ModuleType, payload: Dict[str, Any]) -> Optional[str]:
    out = _output(guard, payload)
    return None if out is None else out["permissionDecision"]


def _write(root: Path, rel: str) -> Dict[str, Any]:
    return _payload(root, "Write", {"file_path": str(root / rel), "content": "changed\n"})


def _edit(root: Path, rel: str) -> Dict[str, Any]:
    return _payload(root, "Edit", {"file_path": str(root / rel), "old_string": "{}", "new_string": "[]"})


def _bash(root: Path, command: str) -> Dict[str, Any]:
    return _payload(root, "Bash", {"command": command})


def _pwsh(root: Path, command: str) -> Dict[str, Any]:
    return _payload(root, "PowerShell", {"command": command})


def _backslashed(rel: str) -> str:
    return rel.replace("/", "\\")


def test_write_to_locked_plan_json_is_denied(make_project, monkeypatch) -> None:
    root, guard, _ = _project(make_project, monkeypatch)
    out = _output(guard, _write(root, LOCKED_PLAN))
    assert out is not None and out["permissionDecision"] == "deny"
    reason = out["permissionDecisionReason"]
    assert "--arm" in reason and "unlock" in reason and "reopen" in reason, reason
    assert _decision(guard, _edit(root, LOCKED_PLAN)) == "deny"
    assert _decision(guard, _write(root, PLANNED_TEST)) == "deny"
    assert _decision(guard, _write(root, SKILL_SPEC)) == "deny"
    assert _decision(guard, _write(root, SKILL_TEST)) == "deny"
    assert _decision(guard, _write(root, ARMED_PLAN)) == "deny"
    assert _decision(guard, _edit(root, ARMED_TEST)) == "deny"
    windows_abs = f"{root}\\{_backslashed(LOCKED_PLAN)}"
    assert _decision(guard, _payload(root, "Write", {"file_path": windows_abs, "content": "x"})) == "deny"
    windows_rel = {"file_path": _backslashed(LOCKED_PLAN), "old_string": "{}", "new_string": "[]"}
    assert _decision(guard, _payload(root, "Edit", windows_rel)) == "deny"


def test_unlocked_and_outside_paths_pass(make_project, monkeypatch) -> None:
    root, guard, _ = _project(make_project, monkeypatch)
    assert _decision(guard, _write(root, FROZEN_PLAN)) is None
    assert _decision(guard, _edit(root, FROZEN_PLAN)) is None
    assert _decision(guard, _write(root, UNLOCKED_PLAN)) is None
    assert _decision(guard, _edit(root, UNLOCKED_PLAN)) is None
    assert _decision(guard, _write(root, RECEIPT)) is None
    assert _decision(guard, _write(root, OUTSIDE)) is None
    assert _decision(guard, _edit(root, STRAP_PART)) is None
    assert _decision(guard, _write(root, STRAP_PART)) is None
    assert _decision(guard, _bash(root, f"echo x > {STRAP_PART}")) is None
    assert _decision(guard, _payload(root, "Write", {"content": "x"})) is None


def test_ledger_files_always_denied(make_project, monkeypatch) -> None:
    root, guard, written = _project(make_project, monkeypatch)
    freezes = root / PLANS / "freezes"
    assert len(written) == 12, written
    for path in written:
        assert path.is_file() and freezes in path.parents, path
        assert _decision(guard, _write(root, path.relative_to(root).as_posix())) == "deny", path
    frozen_only = (freezes / "plan" / "0002-other" / "r1.1-freeze.json").relative_to(root).as_posix()
    assert frozen_only in [p.relative_to(root).as_posix() for p in written]
    assert _decision(guard, _edit(root, frozen_only)) == "deny"
    assert _decision(guard, _write(root, f"{PLANS}/freezes/plan/0009-new/r1.1-freeze.json")) == "deny"
    assert _decision(guard, _write(root, f"{PLANS}/freezes/notes.txt")) == "deny"
    assert _decision(guard, _bash(root, f"echo x >> {frozen_only}")) == "deny"
    skill_lock = f"{PLANS}/freezes/skill/demo/r1.2-lock.json"
    assert _decision(guard, _pwsh(root, f"Set-Content -Path {skill_lock} -Value x")) == "deny"


def test_bash_and_powershell_writes_matched(make_project, monkeypatch) -> None:
    root, guard, _ = _project(make_project, monkeypatch)
    absolute = (root / LOCKED_PLAN).as_posix()
    for command in (f"sed -i 's/a/b/' {LOCKED_PLAN}", f'echo x > "{absolute}"', f"echo x >> {LOCKED_PLAN}",
                    f"cp README.md {LOCKED_PLAN}", f"echo x | tee {PLANNED_TEST}",
                    f"mv /tmp/x.json {ARMED_PLAN}"):
        assert _decision(guard, _bash(root, command)) == "deny", command
    for command in (f'Set-Content -Path "{root / LOCKED_PLAN}" -Value x',
                    f"Copy-Item README.md -Destination {LOCKED_PLAN}",
                    f"Set-Content -Path {_backslashed(LOCKED_PLAN)} -Value x",
                    f"Out-File -FilePath {_backslashed(ARMED_TEST)} -InputObject x"):
        assert _decision(guard, _pwsh(root, command)) == "deny", command
    for command in (f"cat {LOCKED_PLAN}", f"grep demo {absolute}", f"echo x > {FROZEN_PLAN}",
                    f"echo x > {UNLOCKED_PLAN}", f"echo x > {OUTSIDE}"):
        assert _decision(guard, _bash(root, command)) is None, command
    assert _decision(guard, _pwsh(root, f"Get-Content -Path {LOCKED_PLAN}")) is None


def _scheme_entries(ledger: ModuleType, plan: str, test: str, records: Optional[str]) -> List[Any]:
    """A freeze then a lock entry over ``plan`` and ``test``, both carrying the ``records`` scheme."""
    entries = []
    for seq, kind in enumerate(("freeze", "lock"), start=1):
        entries.append(ledger.LedgerEntry(
            kind=kind, round=1, seq=seq, tree="a" * 40, files={plan: _blob("{}\n")},
            ignored={test: _sha256(_TEST_TEXT)}, at=_AT, base="b" * 40, digest="d" * 64,
            records=records, skill_hash=None, grader=None, reason=None))
    return entries


def test_sealed_plan_json_stays_writable_under_lock(make_project, monkeypatch) -> None:
    guard, ledger = _load()
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    cases = (("0005", "sealed", "sealed"), ("0006", "unset", None))
    plans = {no: (f"{PLANS}/{no}_{slug}_ActionPlan.json", f"{PLANS}/{no}/tests/tests/test_{slug}.py")
             for no, slug, _ in cases}
    root = make_project({}, files={plan: "{}\n" for plan, _ in plans.values()})
    for no, slug, records in cases:
        plan, test = plans[no]
        (root / test).parent.mkdir(parents=True, exist_ok=True)
        (root / test).write_bytes(_TEST_TEXT.encode("utf-8"))
        _write_ledger(ledger, root / PLANS, ledger.plan_stem(no, slug),
                      _scheme_entries(ledger, plan, test, records))
    for no, slug, _ in cases:
        plan, test = plans[no]
        assert _decision(guard, _write(root, plan)) is None, slug
        assert _decision(guard, _edit(root, plan)) is None, slug
        assert _decision(guard, _write(root, test)) == "deny", slug
        assert _decision(guard, _edit(root, test)) == "deny", slug


def _pretool_commands() -> Dict[str, List[str]]:
    """The PreToolUse commands of hooks.json, by matcher."""
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    return {group.get("matcher", ""): [hook["command"] for hook in group["hooks"]]
            for group in data["hooks"]["PreToolUse"]}


def test_dispatchers_registered_and_compose_guard_locked() -> None:
    commands = _pretool_commands()
    write_edit, powershell = commands.get("Write|Edit", []), commands.get("PowerShell", [])
    assert any("/hooks/write_pretool.py" in c for c in write_edit), write_edit
    assert not any("/hooks/guard_commit_txt.py" in c for c in write_edit), write_edit
    assert any("/hooks/powershell_pretool.py" in c for c in powershell), powershell
    assert not any("/hooks/powershell_allow_shapes.py" in c for c in powershell), powershell
    for name in DISPATCHERS:
        path = HOOKS / name
        assert path.is_file(), name
        assert _IMPORTS_GUARD.search(path.read_text(encoding="utf-8")), f"{name} does not import guard_locked"
