"""Replay the windows-latest leg of .github/workflows/ci.yml on a local Windows checkout.

Usage: ci_local.py [--base REF | --full] [--python EXE] [--any-python] [--install] [--fetch] [--keep-env]
                   [--short-temp] [--ignore-drift] [--timeout S] [--out-dir DIR] [--dry-run]

The replay runs the ``python`` job's steps as its windows-latest leg runs them: ``tools/select_tests.py``
(``--base origin/main`` is the pull request form, ``--full`` the push-to-main form), ``pip install -r
requirements-dev.txt`` with ``--install``, pytest limited to ``-m cross_os`` with exit 5 read as a pass, the
test runtime catalog and the ``hpy launches under sh`` check. Ruff is gated to Linux and the ``plugins`` job
runs on ubuntu-latest, so neither is replayed. ``--python`` defaults to ``.venv/Scripts/python.exe`` when
the checkout has one, else the interpreter running this script; anything but 3.11.x is refused unless
``--any-python`` is given.

Every step runs in an environment shaped like a ``shell: bash`` step on the runner: Git Bash's folders, then
the target interpreter's, lead PATH; session variables (``CLAUDE*``, ``HARNESS_*``, ``GIT_*``, ``PYTHON*``,
``CONDA_*``, ``VIRTUAL_ENV``) are dropped; ``CI``, ``GITHUB_ACTIONS`` and ``RUNNER_OS=Windows`` are set; the
global git config is swapped for one holding only the ``safe.directory`` entries. ``--keep-env`` runs in the
caller's environment instead. ``--short-temp`` points TEMP and TMP at an 8.3 short path, as the runner's
``RUNNER~1`` profile does.

Before any step, ``workflow_drift`` compares the commands copied below with ci.yml and exits 3 on a mismatch
(``--ignore-drift`` overrides). A table then sets what the replay cannot reproduce (the 3.11 patch,
dependency versions, git version and line endings, symlink privilege, TEMP, code page, the merge commit a
pull request tests) beside the local value, and warnings name uncommitted paths and untracked tests, which
selection cannot see. Output lands in ``--out-dir`` (default ``.artifacts/ci-local``), emptied first.

Exit codes: 0 every replayed step passed or was skipped as CI skips it; 1 a step failed; 2 usage;
3 precondition or drift.
"""
from __future__ import annotations

import argparse
import ctypes
import itertools
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
REQUIREMENTS = ROOT / "requirements-dev.txt"
DEFAULT_OUT = ROOT / ".artifacts" / "ci-local"
OUT_MARKER = ".ci-local"
CI_PYTHON = "3.11"
WINDOWS_MARKER = "cross_os"
NO_TESTS_RC = 5
JOB_TIMEOUT_S = 15 * 60
RUNNER_TEMP = r"C:\Users\RUNNER~1\AppData\Local\Temp"
SELECT_STEP = "select work from the diff"
PIP_LINE = "python -m pip install -r requirements-dev.txt"
CATALOG_STEP = "test runtime catalog"
HPY_STEP = "hpy launches under sh"
PYTHON_JOB_STEPS = ("actions/checkout@v4", "actions/setup-python@v5", SELECT_STEP, PIP_LINE, "ruff",
                    "pytest", CATALOG_STEP, "actions/upload-artifact@v4", HPY_STEP)
SELECT_LINES = ('python tools/select_tests.py --base "origin/$BASE_REF"',
                "python tools/select_tests.py --full")
PYTEST_LINES = (f"args=(-m {WINDOWS_MARKER})",
                'python -m pytest "${targets[@]}" "${args[@]}" -q --junitxml=.artifacts/pytest-junit.xml',
                f'[ "$rc" = {NO_TESTS_RC} ]')
CATALOG_LINE = ("python tools/ci_test_runtime_catalog.py .artifacts/pytest-junit.xml "
                ".artifacts/test-runtime-catalog.json")
HPY_LINE = ('sh plugins/harness/scripts/hpy -c '
            '"import jsonschema, referencing, pydantic, sys; print(sys.version)"')
SCRUB = ("CLAUDE", "HARNESS_", "GIT_", "PYTHON", "GITHUB_", "RUNNER_", "VIRTUAL_ENV", "CONDA_")
STEP_KEY = re.compile(r"^ {6}(?:- | {2})(name|uses|if|run): ?(.*)$")
FACTS_SCRIPT = (
    "import json, locale, sys\n"
    "from importlib import metadata\n"
    "def version(name):\n"
    "    try:\n"
    "        return metadata.version(name)\n"
    "    except metadata.PackageNotFoundError:\n"
    "        return None\n"
    "print(json.dumps({'version': sys.version, 'encoding': locale.getpreferredencoding(False),\n"
    "                  'packages': {n: version(n) for n in sys.argv[1:]}}))\n"
)


@dataclass
class Step:
    label: str
    cond: str = ""
    run: str = ""


@dataclass
class Selection:
    pytest: str
    ruff: str
    plugins: bool
    tests: List[str]
    reasons: List[str]


@dataclass
class Context:
    python: Path
    out_dir: Path
    env: Dict[str, str]
    facts: Dict[str, object] = field(default_factory=dict)


# ---- ci.yml drift ---------------------------------------------------------------------------------------


def job_lines(text: str, job: str) -> List[str]:
    """The lines under ``jobs.<job>:`` of a workflow, up to the next job."""
    lines = text.splitlines()
    start = lines.index(f"  {job}:") + 1
    end = next((i for i in range(start, len(lines)) if re.match(r"  \S", lines[i])), len(lines))
    return lines[start:end]


def job_steps(lines: Sequence[str]) -> List[Step]:
    """One Step per ``- `` item at step depth: name (else ``uses``, else ``run``), ``if`` and ``run``."""
    starts = [i for i, line in enumerate(lines) if line.startswith("      - ")]
    return [_step(lines[a:b]) for a, b in zip(starts, [*starts[1:], len(lines)])]


def _step(chunk: Sequence[str]) -> Step:
    keys: Dict[str, str] = {}
    for at, line in enumerate(chunk):
        found = STEP_KEY.match(line)
        if found:
            keys[found.group(1)] = _block(chunk[at + 1:]) if found.group(2) == "|" else found.group(2)
    return Step(keys.get("name") or keys.get("uses") or keys.get("run", ""), keys.get("if", ""),
                keys.get("run", ""))


def _block(rest: Sequence[str]) -> str:
    """A ``|`` literal block: the lines indented past a step key, dedented."""
    body = itertools.takewhile(lambda line: line.startswith(" " * 10) or not line.strip(), rest)
    return textwrap.dedent("\n".join(body)).strip("\n")


def workflow_drift(text: str) -> List[str]:
    """Names of the checks ci.yml fails against this module's copies; empty when the replay matches."""
    job = job_lines(text, "python")
    steps = {s.label: s for s in job_steps(job)}
    blank = Step("")
    checks = {
        "python job step order": tuple(steps) == PYTHON_JOB_STEPS,
        "windows-latest in the matrix": bool(re.search(r"os: \[[^\]]*windows-latest", "\n".join(job))),
        "setup-python version": any(f'python-version: "{CI_PYTHON}"' in line for line in job),
        "select command": all(s in steps.get(SELECT_STEP, blank).run for s in SELECT_LINES),
        "pytest command": all(s in steps.get("pytest", blank).run for s in PYTEST_LINES),
        "ruff is Linux-only": "runner.os == 'Linux'" in steps.get("ruff", blank).cond,
        "catalog command": steps.get(CATALOG_STEP, blank).run == CATALOG_LINE,
        "hpy check": steps.get(HPY_STEP, blank).run == HPY_LINE,
    }
    return [name for name, ok in checks.items() if not ok]


# ---- environment ----------------------------------------------------------------------------------------


def git_bash_dirs() -> List[Path]:
    """Git for Windows' ``mingw64/bin`` and ``usr/bin``, which a ``shell: bash`` step puts ahead of PATH."""
    git = shutil.which("git")
    if git is None:
        return []
    top = Path(git).resolve().parent.parent
    top = top.parent if top.name.lower() == "mingw64" else top
    return [d for d in (top / "mingw64" / "bin", top / "usr" / "bin") if d.is_dir()]


def isolated_git_global(out_dir: Path) -> Path:
    """A global git config holding only the caller's ``safe.directory`` entries: the runner has no identity,
    aliases or hooks, but a checkout owned by another account must still open."""
    done = subprocess.run(["git", "config", "--global", "--get-all", "safe.directory"],
                          capture_output=True, text=True, check=False)
    entries = "".join(f"\tdirectory = {d}\n" for d in done.stdout.splitlines() if d.strip())
    path = out_dir / "gitconfig"
    path.write_text(f"[safe]\n{entries}" if entries else "", encoding="utf-8")
    return path


def ci_env(base: Mapping[str, str], python: Path, bash_dirs: Sequence[Path],
           git_global: Path) -> Dict[str, str]:
    """The environment a ``shell: bash`` step on windows-latest hands to ``python``: Git Bash and the
    interpreter's folders ahead of PATH, no session variables, and the runner's markers."""
    env = {k: v for k, v in base.items() if not k.upper().startswith(SCRUB)}
    py_dirs = [python.parent, python.parent / "Scripts", python.parent / "Library" / "bin"]
    front = [str(d) for d in [*bash_dirs, *py_dirs] if d.is_dir()]
    env["PATH"] = os.pathsep.join([*front, base.get("PATH", "")])
    env.update(CI="true", GITHUB_ACTIONS="true", RUNNER_OS="Windows", MSYSTEM="MINGW64",
               PYTHONNOUSERSITE="1", GIT_CONFIG_GLOBAL=str(git_global))
    return env


def with_temp(env: Mapping[str, str], temp: str) -> Dict[str, str]:
    """The environment with TEMP and TMP pointed at ``temp``."""
    return {**env, "TEMP": temp, "TMP": temp}


def short_temp_dir() -> Tuple[Path, bool]:
    """A long-named folder under the system temp, in its 8.3 short form when the volume makes one; the flag
    is False when it does not."""
    long_dir = Path(tempfile.gettempdir()) / "ci_local_runner_temp"
    long_dir.mkdir(exist_ok=True)
    short = _short_path(long_dir)
    return short, "~" in str(short)


def _short_path(path: Path) -> Path:
    if sys.platform != "win32":
        return path
    buf = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf))
    return Path(buf.value) if 0 < size < len(buf) else path


# ---- facts and preconditions ----------------------------------------------------------------------------


def requirements() -> List[Tuple[str, str]]:
    """(name, specifier) for each line of requirements-dev.txt."""
    rows = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        found = re.match(r"\s*([A-Za-z0-9_.-]+)\s*(.*)", line.split("#", 1)[0])
        if found:
            rows.append((found.group(1), found.group(2).strip()))
    return rows


def python_facts(python: Path, env: Mapping[str, str]) -> Dict[str, object]:
    """Version, preferred encoding and installed requirement versions of the target interpreter."""
    names = [name for name, _ in requirements()]
    try:
        done = subprocess.run([str(python), "-c", FACTS_SCRIPT, *names], env=dict(env),
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return {"version": "unrunnable", "encoding": "?", "packages": {}}


def version_problem(version: str, any_python: bool) -> Optional[str]:
    """Why the interpreter version cannot stand in for CI's, or None."""
    if any_python or version.startswith(f"{CI_PYTHON}."):
        return None
    return (f"python {version.split()[0]} is not {CI_PYTHON}.x: pass a {CI_PYTHON} interpreter as --python, "
            "or --any-python")


def git_out(*args: str) -> str:
    done = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False)
    return done.stdout.strip()


def preconditions(args: argparse.Namespace, ctx: Context) -> List[str]:
    """Problems that stop the replay before its first step."""
    problems = []
    found = version_problem(str(ctx.facts["version"]), args.any_python)
    if found:
        problems.append(found)
    if shutil.which("sh", path=ctx.env.get("PATH", "")) is None:
        problems.append("no sh on the replay PATH: install Git for Windows, whose usr/bin holds sh.exe")
    if not args.full and not git_out("rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}"):
        problems.append(f"{args.base} does not resolve (select_tests.py would quietly run everything): "
                        "pass --fetch")
    return problems


def symlink_allowed(scratch: Path) -> bool:
    link = scratch / "symlink-probe"
    try:
        link.symlink_to(scratch / OUT_MARKER)
    except OSError:
        return False
    link.unlink()
    return True


def gap_rows(ctx: Context) -> List[Tuple[str, str, str]]:
    """(item, CI, local) for every difference the replay reports but cannot remove."""
    packages: Mapping[str, Optional[str]] = ctx.facts.get("packages", {})  # type: ignore[assignment]
    rows = [("python", f"{CI_PYTHON}.x (newest patch)", str(ctx.facts["version"]).split()[0])]
    rows += [(name, spec or "newest", packages.get(name) or "missing") for name, spec in requirements()]
    symlinks = "allowed" if symlink_allowed(ctx.out_dir) else "refused: symlink tests skip"
    rows += [
        ("git", "runner image", git_out("--version")),
        ("core.autocrlf", "true (unverified)", git_out("config", "--get", "core.autocrlf") or "unset"),
        ("symlinks", "allowed (admin)", symlinks),
        ("TEMP", RUNNER_TEMP, ctx.env.get("TEMP", "")),
        ("code page", "runner default", str(ctx.facts["encoding"])),
        ("checkout", "the PR merged into its base", f"HEAD {git_out('rev-parse', '--short', 'HEAD')}"),
    ]
    return rows


def dirty_warnings(status: str, untracked_tests: str) -> List[str]:
    """Warnings for what pytest runs here but selection, which reads commits only, cannot see."""
    lines = []
    changed = [line for line in status.splitlines() if line.strip()]
    if changed:
        lines.append(f"{len(changed)} uncommitted path(s): tests read them, selection does not")
    for path in untracked_tests.splitlines():
        name = PurePosixPath(path.strip()).name
        if name.startswith("test_") and name.endswith(".py"):
            lines.append(f"untracked test {path.strip()}: a --full run picks it up, CI never sees it")
    return lines


# ---- steps ----------------------------------------------------------------------------------------------


def read_outputs(text: str) -> Dict[str, str]:
    """``key=value`` lines a step appended to GITHUB_OUTPUT."""
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def run_select(args: argparse.Namespace, ctx: Context) -> Optional[Selection]:
    """ci.yml's select step, read through the GITHUB_OUTPUT channel the workflow reads."""
    outputs = ctx.out_dir / "github_output.txt"
    outputs.write_text("", encoding="utf-8")
    mode = ["--full"] if args.full else ["--base", args.base]
    argv = [str(ctx.python), "tools/select_tests.py", *mode, "--out-dir", str(ctx.out_dir)]
    print(f"==> {SELECT_STEP}\n    $ {shlex.join(argv)}", flush=True)
    done = subprocess.run(argv, cwd=ROOT, env={**ctx.env, "GITHUB_OUTPUT": str(outputs)},
                          capture_output=True, text=True, check=False)
    if done.returncode:
        print(done.stdout + done.stderr)
        return None
    keys = read_outputs(outputs.read_text(encoding="utf-8"))
    tests = (ctx.out_dir / "selected-tests.txt").read_text(encoding="utf-8").splitlines()
    sel = Selection(keys["pytest"], keys["ruff"], keys["plugins"] == "true", tests,
                    json.loads(done.stdout)["reasons"])
    print(f"    pytest={sel.pytest} ({len(tests)} files) ruff={sel.ruff} plugins={sel.plugins}")
    for reason in sel.reasons[:20]:
        print(f"      {reason}")
    return sel


def pytest_argv(python: Path, targets: Sequence[str], junit: Path) -> List[str]:
    """ci.yml's pytest line with RUNNER_OS=Windows: targets, ``-m cross_os``, ``-q``, the JUnit report."""
    return [str(python), "-m", "pytest", *targets, "-m", WINDOWS_MARKER, "-q",
            f"--junitxml={junit.as_posix()}"]


def windows_rc(rc: int) -> int:
    """Exit 5 (no selected test carries the marker) is a pass on Windows, as in ci.yml."""
    return 0 if rc == NO_TESTS_RC else rc


def shown(argv: Sequence[str], limit: int = 12) -> str:
    """The command as Git Bash would take it, with a long run of test files cut to its ends."""
    if len(argv) <= limit:
        return shlex.join(argv)
    head, tail = list(argv[:5]), list(argv[-5:])
    return f"{shlex.join(head)} ... ({len(argv) - 10} more; see selected-tests.txt) {shlex.join(tail)}"


def run_step(name: str, argv: Sequence[str], ctx: Context, dry_run: bool,
             timeout: Optional[float] = None) -> int:
    """Print the step and its command, run it from the repo root in the replay environment, print the
    result. The executable resolves against the replay PATH, since Windows searches the parent's."""
    argv = [shutil.which(argv[0], path=ctx.env.get("PATH", "")) or argv[0], *argv[1:]]
    print(f"==> {name}\n    $ {shown(argv)}", flush=True)
    if dry_run:
        return 0
    start = time.monotonic()
    try:
        rc = subprocess.run(argv, cwd=ROOT, env=ctx.env, timeout=timeout, check=False).returncode
    except subprocess.TimeoutExpired:
        print(f"    timed out after {timeout:.0f}s; the CI job stops at {JOB_TIMEOUT_S // 60} minutes")
        return 124
    print(f"    rc={rc} in {time.monotonic() - start:.1f}s", flush=True)
    return rc


def skip_reasons(junit: Path) -> Dict[str, int]:
    """Skipped-test count per skip message; environment skips (no sh, no symlink privilege) show here."""
    counts: Dict[str, int] = {}
    for node in ElementTree.parse(junit).iter("skipped"):
        message = (node.get("message") or "").strip()
        counts[message] = counts.get(message, 0) + 1
    return counts


def print_skips(counts: Mapping[str, int]) -> None:
    for message, count in sorted(counts.items(), key=lambda item: -item[1]):
        print(f"    skipped {count:>3}: {message}")


def verdict(failed: Sequence[str]) -> int:
    print(f"== windows: FAIL ({', '.join(failed)})" if failed else "== windows: PASS")
    return 1 if failed else 0


def run_tests(args: argparse.Namespace, ctx: Context, sel: Selection) -> List[str]:
    """The pytest and catalog steps; the names of the failed ones."""
    junit = ctx.out_dir / "pytest-junit.xml"
    rc = run_step("pytest", pytest_argv(ctx.python, sel.tests, junit), ctx, args.dry_run, args.timeout)
    failed = [] if windows_rc(rc) == 0 else ["pytest"]
    if junit.is_file():
        print_skips(skip_reasons(junit))
        catalog = [str(ctx.python), "tools/ci_test_runtime_catalog.py", str(junit),
                   str(ctx.out_dir / "test-runtime-catalog.json")]
        if run_step(CATALOG_STEP, catalog, ctx, args.dry_run):
            failed.append(CATALOG_STEP)
    return failed


def run_windows(args: argparse.Namespace, ctx: Context) -> int:
    """The windows-latest leg of the ``python`` job, step for step; returns the job's exit code."""
    sel = run_select(args, ctx)
    if sel is None:
        return verdict([SELECT_STEP])
    if sel.pytest == "none" and sel.ruff == "none":
        print("the diff reaches no Python work: CI skips every later step and passes")
        return verdict([])
    pip = [str(ctx.python), "-m", "pip", "install", "-r", "requirements-dev.txt"]
    if args.install and run_step("pip install", pip, ctx, args.dry_run):
        return verdict(["pip install"])
    if sel.pytest == "none":
        print("pytest, catalog and hpy steps skipped: no selected test (ruff runs on Linux only)")
        return verdict([])
    failed = run_tests(args, ctx, sel)
    # The hpy step's ``if`` has no status function, so GitHub adds success(): an earlier failure skips it.
    if not failed and run_step(HPY_STEP, shlex.split(HPY_LINE), ctx, args.dry_run):
        failed.append(HPY_STEP)
    return verdict(failed)


# ---- setup and entry ------------------------------------------------------------------------------------


def fresh_out_dir(path: Path) -> Optional[str]:
    """Empty and recreate the output folder; refuse one holding files this tool did not write."""
    if path.is_dir() and any(path.iterdir()) and not (path / OUT_MARKER).is_file():
        return f"{path} holds files this tool did not write: pick an empty --out-dir"
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    (path / OUT_MARKER).write_text("written by tools/ci_local.py\n", encoding="utf-8")
    return None


def prepare(args: argparse.Namespace) -> Tuple[Optional[Context], List[str]]:
    """The replay context, or None and the problems; notes ride along either way."""
    problem = fresh_out_dir(args.out_dir)
    if problem:
        return None, [problem]
    env = dict(os.environ) if args.keep_env else ci_env(
        os.environ, args.python, git_bash_dirs(), isolated_git_global(args.out_dir))
    notes = []
    if args.short_temp:
        short, made = short_temp_dir()
        env = with_temp(env, str(short))
        if not made:
            notes.append("--short-temp: this volume makes no 8.3 names, so TEMP keeps its long form")
    ctx = Context(args.python, args.out_dir, env)
    ctx.facts = python_facts(args.python, env)
    status = git_out("status", "--porcelain")
    notes += dirty_warnings(status, git_out("ls-files", "--others", "--exclude-standard", "--", "tests"))
    return ctx, notes


def print_rows(rows: Sequence[Tuple[str, str, str]]) -> None:
    width = max(len(row[0]) for row in rows)
    print(f"{'':<{width}}  {'CI':<40} local")
    for item, ci_value, local in rows:
        print(f"{item:<{width}}  {ci_value:<40} {local}")


def fetch_base(base: str) -> int:
    if not base.startswith("origin/"):
        print(f"--fetch needs an origin/<branch> base, not {base}")
        return 3
    return subprocess.run(["git", "-C", str(ROOT), "fetch", "origin", base.split("/", 1)[1]],
                          check=False).returncode


def default_python() -> Path:
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    return venv if venv.is_file() else Path(sys.executable)


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--base", default="origin/main", help="pull request form: diff against REF")
    mode.add_argument("--full", action="store_true", help="push-to-main form: select every test")
    ap.add_argument("--python", type=Path, default=default_python())
    ap.add_argument("--any-python", action="store_true", help="accept a version other than 3.11")
    ap.add_argument("--install", action="store_true", help="run CI's pip install into --python first")
    ap.add_argument("--fetch", action="store_true", help="git fetch the base branch first")
    ap.add_argument("--keep-env", action="store_true", help="run in the caller's environment")
    ap.add_argument("--short-temp", action="store_true", help="TEMP and TMP as an 8.3 short path")
    ap.add_argument("--ignore-drift", action="store_true", help="run even when ci.yml has changed")
    ap.add_argument("--timeout", type=float, default=JOB_TIMEOUT_S, help="pytest step limit in seconds")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--dry-run", action="store_true", help="select, then print the other commands")
    args = ap.parse_args(argv)
    args.python, args.out_dir = args.python.absolute(), args.out_dir.absolute()
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    drift = [] if args.ignore_drift else workflow_drift(WORKFLOW.read_text(encoding="utf-8"))
    if drift:
        print(f"ci.yml no longer matches this replay: {', '.join(drift)}. Update the copies in "
              "tools/ci_local.py, or pass --ignore-drift.")
        return 3
    if args.fetch and not args.full and fetch_base(args.base):
        return 3
    ctx, notes = prepare(args)
    if ctx is None:
        print("\n".join(notes))
        return 3
    print_rows(gap_rows(ctx))
    for note in notes:
        print(f"warning: {note}")
    problems = preconditions(args, ctx)
    if problems:
        print("\n".join(f"problem: {p}" for p in problems))
        return 3
    return run_windows(args, ctx)


if __name__ == "__main__":
    sys.exit(main())
