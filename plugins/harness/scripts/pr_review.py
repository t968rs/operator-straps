"""pr-review driver: capture a PR into reviewer briefs, merge findings, build the review, plan fix waves.

Every subcommand but ``capture`` works on the run that ``<artifacts.scratch>/<NNNN>/current`` names.

``capture --pr N [--no-fetch] [--allow-closed] [--roast yes|no|roll]``
    Phase 1 and the Phase 2 dispatch plan. One ``gh pr view`` read (raw stdout kept as ``phase1_meta.txt``
    and the ``pr_metadata_check`` paste); a non-OPEN PR stops unless ``--allow-closed`` (a replay that
    ``build`` refuses). Local git supplies the files; machine-generated paths are dropped; the rest sort into
    review buckets; lens triggers, content pins and the structural guard decision are evaluated at the PR
    head, and the guard suite runs in the working tree when it applies (a red guard stops; an applicable
    guard run with the checkout off the PR head stops before running). Writes ``plan.json``, one brief and
    one budgeted diff per reviewer slot, and prints one dispatch row per slot: ``agent=harness:pr-reviewer
    model=<m>`` then the prompt (four header lines and ``Brief: <abs path>``).
``block --pr N --agent ID``
    Reprint the return block of a recorded reviewer or fixer report.
``fold --pr N --source ID --kind external|tests|developer|adhoc (--from-gh-review URL | --findings FILE|-)
[--severity S]``
    Record an outside review (an external reviewer, test results, the developer, ad-hoc feedback) as
    ``findings/<ID>.json`` through ``review_models.record`` and register it in ``plan.json`` ``folded``
    (``{id, kind, origin, at}``; a re-fold replaces both). ``--findings`` takes a JSON list of findings or
    ``{"findings": [...], "strengths": [...]}``; ``--from-gh-review`` maps each inline comment of a GitHub
    PR review to one ``judgment`` finding at ``--severity`` (default minor), skipping a DISMISSED review or a
    blank one without comments. Before build the source is merge input. Once the review is built the
    source is also appended (entry gains ``after_build: true``): its findings convert as merge converts one
    report, ids continue per severity after the review's highest, nothing is renumbered or auto-merged
    (merge candidates against existing issues print as a note), the source is credited in ``reviewers``,
    the verdict is recomputed and the review is written through the validated writer. The phase stays
    ``fix-plan`` / ``fix`` inside an open Phase 5 pass and becomes ``consolidate`` otherwise, so only
    ``bubble`` / ``waves`` open a pass. The printed ``next:`` step is the Phase 4 second run unless a Phase 5
    pass is open, where it is ``waves`` for the new ids, then ``closeout``. Re-folding a source already in the
    built review is refused, naming its ids; a built review whose Phase 4 first run failed (``pre_fix_time``
    pending) refuses the fold until ``build --replace`` succeeds.
``merge --pr N [--force]``
    Merge the reports of the plan's slots, then its folded sources, into ``draft.json`` and print the issue
    table, the merge candidates and the strengths count. A findings file that is neither a slot nor a folded
    source is a problem. A draft carrying amend operations is only replaced with ``--force``.
``amend --pr N [--regrade I3=minor ...] [--merge I3+I7 ...]``
    Apply regrades and id merges to ``draft.json`` in the order given, log them, reprint the table.
``build --pr N [--replace] [--waive-head-ancestry]``
    Write ``<artifacts.reviews>/<NNNN>_<slug>.json`` from the plan and the draft, with the Phase 4 first run's
    ``pre_fix_time`` when it succeeds (else the pending literal, a READY verdict turned into ``NOT READY TO
    MERGE - Phase 4 first run failed: <reason>``, a problem and exit 1). ``--waive-head-ancestry`` also
    accepts a run whose only STOP is ``sha_ancestry_check`` with ``head_ancestor_exit != 0`` and
    ``base_ancestor_exit == 0``: ``pre_fix_time`` is inserted, ``plan.json`` records ``phase4_waiver`` and
    a ``note:`` line is printed.
``bubble --pr N ID --classification C --reason R``
    Bubble one issue for the developer and recompute the verdict.
``waves --pr N [--ids I3,M2]``
    Plan fix waves over the undispositioned, unheld issues not yet fully recorded (or exactly ``--ids``):
    a partially fixed split issue is re-planned for its unrecorded parts only; fixer-bubbled ids stay out.
    Each fixer's file set adds the registered tests targeting its issues' files and the existing paths
    their fix options name. Registered tests that ``defer_reasons`` selects (summed ``tests.timings``
    seconds over ``tests.fixer_test_seconds``, or a true ``tests.defer_flags`` path) appear in the brief as
    ``deferred, do not run`` with their reason; the deferred tests and reasons are kept in ``waves.json``
    ``deferred`` and stay deferred across follow-up waves.
    Once a closeout has run (``closeout.json`` in the run), only fix entries closeout accepts count as
    recorded, so an id whose entries it rejected is re-planned. Write ``waves.json`` (with each fixer's
    parts) and the fixer briefs, print one dispatch row per fixer, wave by wave, then the held ids and the
    pending fixer bubbles.
``bubbles --pr N``
    Read-only: print the fixer bubbles not yet in the review (``<id> (<classification>) from <fixer>:
    <reason>``), or ``pending fixer bubbles: none``.
``closeout --pr N [--closed M17=rationale ...] [--deferred I3="decision; tracker" ...]
[--resolved I4=what ...]``
    Resolve the validated fixes (only ids assigned to the recording fixer; a split issue only when every
    planned part is recorded), close the named ids, record fixer bubbles, resolve each deferred id as a
    developer-confirmed defer (kept in ``bubble_up``), resolve each ``--resolved`` id (a fix in the tree no
    accepted fixer entry records; one of its files must have changed since ``build_head``), recompute the
    verdict and print the canonical Phase 5 line, a ``hint:`` line per blocked id (partially fixed ones aside)
    whose files changed (the ``--resolved`` route), then a ``deferred tests:`` block (each file, its reason,
    one pytest command) for the deferred tests (those saved in ``waves.json`` plus those deferred now) that
    the paths changed since ``build_head`` reach. A planned fixer without a fix report, or an undispositioned
    id its planned fixers never recorded, is a problem; so is a pending ``pre_fix_time``. Writes
    ``closeout.json`` (head and problems) to the run, which switches later ``waves`` runs to
    closeout-accepted entries.
``config [--get KEY ...]``
    Print the project's merged harness configuration as JSON, or with ``--get`` one line per dotted key
    (``state_dir``, ``artifacts.reviews``): a string as-is, null as an empty line, anything else as JSON.
    Skills and agents read the configuration through this instead of an inline ``-c`` snippet carrying a
    path.

Every review write is validated in process (schema, pending rule, issue counts), replaced atomically, then
run through the real schema hook, which also clears the Phase 5 sentinel. Every failure, an argument error
included, exits 1 with one ``problem: ...`` line per defect on stderr. Each successful subcommand records
the run's position in ``plan.json`` ``phase``: ``review`` (capture, fold before build), ``consolidate``
(merge, amend, build, fold after build outside an open pass), ``fix-plan`` (bubble), ``fix`` (waves;
closeout with problems or undispositioned ids; fold after build inside an open pass keeps ``fix-plan`` /
``fix``), ``done`` (closeout with every issue id dispositioned).

Project and paths: ``--repo`` names the project (default: the git top level of the working directory); its
``.claude/harness.json`` is activated once. Run scratch is ``artifacts.scratch``, reviews go to
``artifacts.reviews``, registry tests come from ``tests.registry`` (deferred by ``tests.timings``,
``tests.fixer_test_seconds`` and ``tests.defer_flags``), the structural guards from ``review.*``,
brief pointers from ``review.domain_pointers`` and the lens catalog is the plugin's merged with
``review.lenses``. Plugin assets (the Phase 4 script, the schema hook, the catalog, the library) resolve from
the plugin root; nothing is written under it.

Usage (Bash tool; ``$PR_REVIEW`` stands for
``sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py"``)::

    $PR_REVIEW [--repo DIR] capture --pr N [--no-fetch] [--allow-closed] [--roast yes|no|roll]
    $PR_REVIEW block --pr N --agent ID
    $PR_REVIEW fold --pr N --source ID --kind K (--from-gh-review URL | --findings FILE) [--severity S]
    $PR_REVIEW merge --pr N [--force]
    $PR_REVIEW amend --pr N [--regrade ID=severity ...] [--merge KEEP+DROP ...]
    $PR_REVIEW build --pr N [--replace] [--waive-head-ancestry]
    $PR_REVIEW bubble --pr N ID --classification C --reason R
    $PR_REVIEW waves --pr N [--ids I3,M2]
    $PR_REVIEW bubbles --pr N
    $PR_REVIEW closeout --pr N [--closed ID=text ...] [--deferred ID=text ...] [--resolved ID=text ...]
    $PR_REVIEW config [--get KEY ...]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, NoReturn, Optional, Sequence, Set, Tuple

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

#: (module, v2-only attribute or None, pip requirement): the review models need pydantic>=2, the review
#: schema validation needs jsonschema and referencing. referencing comes first because jsonschema imports
#: it, so a missing referencing is named as itself.
_REQUIRED_MODULES: Tuple[Tuple[str, Optional[str], str], ...] = (
    ("pydantic", "model_validator", "pydantic>=2"),
    ("referencing", None, "referencing"),
    ("jsonschema", None, "jsonschema"),
)


def _missing_requirement() -> Optional[str]:
    """Return the pip requirement of the first review dependency that does not import, else None."""
    import importlib

    for module, attr, requirement in _REQUIRED_MODULES:
        try:
            loaded = importlib.import_module(module)
        except ImportError:
            return requirement
        if attr is not None and not hasattr(loaded, attr):
            return requirement
    return None


_MISSING = _missing_requirement()
if _MISSING is not None:
    print(f"problem: {_MISSING} is not installed; pr_review needs it (pip install '{_MISSING}')",
          file=sys.stderr)
    sys.exit(1)

from harness_lib import review_edit  # noqa: E402
from harness_lib import review_merge as rmg  # noqa: E402
from harness_lib import review_models as rm  # noqa: E402
from harness_lib import review_plan as rp  # noqa: E402
from harness_lib.branch_capture import CaptureError, git, git_out  # noqa: E402
from harness_lib.config import HarnessConfig, activate, active, load_config  # noqa: E402
from harness_lib.default_exclusions import ensure_default_exclusions  # noqa: E402
from harness_lib.pr_capture import PrMeta, budgeted_diff, capture_pr, file_patches  # noqa: E402
from harness_lib.pr_summary import PrFacts, PrFile  # noqa: E402
from harness_lib.project import plugin_root, project_root  # noqa: E402

REVIEWER_AGENT = "harness:pr-reviewer"
FIXER_AGENT = "harness:pr-fixer"
GREP_ROOTS = (".claude", "docs", ".github")
PR_BLOCK_BUDGET = 1200
PR_CHAR_BUDGET = 60_000
GUARD_TAIL_LINES = 40
CLOSEOUT_MARK = "closeout.json"
GH_FIELDS = "number,title,headRefName,baseRefName,state,url,commits,headRefOid,mergeCommit"
GH_PROJECTION = (
    "{number, title, headRefName, baseRefName, state, url, headRefOid, mergeCommit: .mergeCommit.oid, "
    "commits_count: (.commits|length), first_sha: .commits[0].oid, last_sha: .commits[-1].oid}"
)
_GH_KEYS = ("number", "title", "headRefName", "baseRefName", "state", "headRefOid")

TEST_DESIGN_CLAUSE = (
    "Test-design principle: every test in scope must be either CLEARLY BEHAVIORAL (exercises real logic "
    "with real or fake collaborators that do not stub the function under test) OR an integration test "
    "against the real dependency. Mock-chain wiring tests — tests that stub the helpers and then assert the "
    "stubs were called — are NEITHER. Flag each one as Critical, recommending removal or conversion to a "
    "behavioral or integration test."
)
ROAST_VOICE = (
    "Voice: a tired senior developer: dry, direct, honest, never cruel. Roast the code, never the author; "
    "at most one line of editorial per finding; skip style nitpicks (naming taste, whitespace, line length "
    "under the limit). The voice changes the wording only: scope, severities and the `record` call are "
    "unchanged."
)
OVERALL_SCOPE = (
    "OVERALL: review the PR as one change across every in-scope path: cross-file contracts, behavior callers "
    "depend on, plan or spec alignment, and every path no bucket reviewer owns (unbucketed paths included)."
)
BUCKET_SCOPE = (
    "Bucket `{bucket}`: review these paths for correctness, broken contracts and the conventions of this "
    "kind of file."
)
SEVERITY_RULES = (
    "Severity: `critical` blocks the merge (wrong behavior, data loss, broken contract, a test that cannot "
    "fail); `important` should be fixed before merging; `minor` is polish.",
    "fix_kind: `mechanical` when the fix is an exact edit a small model can apply; `judgment` otherwise.",
    "Each finding names one primary `file` (repo-relative) with `lines` when known (`12`, `12-18,40`), and "
    "`also` for other files it touches. `fix` lists one or more options, any of which resolves it.",
)
BUBBLE_QUESTIONS = (
    "Are there two or more reasonable resolutions, AND does picking one need domain knowledge this session "
    "does not have? (both yes: `architectural_ambiguity`)",
    "Is the fix outside the PR's actual scope? (`out_of_scope`)",
    "Does the fix need a developer call on an aesthetic or convention question with no codebase precedent? "
    "(`architectural_ambiguity`)",
)
_TIER = {"C": "critical", "I": "important", "M": "minor"}
_SECTION = re.compile(r"^=== (.+) \[([a-z]+), \+\d+ -\d+\] ===$")
_CLIPPED = re.compile(r"^(\[omitted: |\.\.\. \d+ more diff lines omitted)|\.\.\.\[\+\d+ chars\]$")
FOLD_KINDS = ("external", "tests", "developer", "adhoc")
NAME_LIMIT = 120
_GH_REVIEW_URL = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)#pullrequestreview-(\d+)$")
_GH_PR_URL = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


# --- subprocess seams (tests replace these) -----------------------------------------------------------------


def _proc(cmd: Sequence[str], repo: Path, **kwargs: object) -> subprocess.CompletedProcess:
    """Run ``cmd`` in ``repo`` with UTF-8 text capture; never raises on a non-zero exit."""
    return subprocess.run(list(cmd), cwd=repo, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kwargs)


def run_gh(repo: Path, args: Sequence[str]) -> str:
    """Stdout of ``gh <args>``; raise ``CaptureError`` when gh is missing or fails."""
    try:
        result = _proc(["gh", *args], repo)
    except OSError as exc:
        raise CaptureError([f"gh could not run ({exc}); install gh or check PATH"]) from exc
    if result.returncode != 0:
        raise CaptureError([f"gh {' '.join(args[:3])} failed: {result.stderr.strip()}"])
    return result.stdout


def phase4_script() -> Path:
    """The plugin's Phase 4 branch-safety script."""
    return plugin_root() / "skills" / "pr-review" / "commands" / "phase4_branch_safety.py"


def hook_script() -> Path:
    """The plugin's PR_REVIEW schema hook."""
    return plugin_root() / "hooks" / "validate_pr_json_schema.py"


def hpy_command() -> str:
    """The ``sh "<plugin>/scripts/hpy"`` prefix agents run Python through (absolute plugin path)."""
    return f'sh "{(plugin_root() / "scripts" / "hpy").as_posix()}"'


def run_guards(repo: Path, suite: Sequence[str]) -> Tuple[int, str]:
    """Run the structural guard suite with this interpreter in ``repo``; return the exit code and output."""
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *suite]
    result = _proc(cmd, repo)
    return result.returncode, result.stdout + result.stderr


def run_phase4(repo: Path, pr: int) -> Tuple[int, str, str]:
    """Run the Phase 4 branch-safety script (first run) in ``repo``; return exit code, stdout and stderr."""
    result = _proc([sys.executable, str(phase4_script()), str(pr)], repo)
    return result.returncode, result.stdout, result.stderr


def run_hook(repo: Path, review_path: Path) -> Tuple[int, str]:
    """Run the schema hook on ``review_path`` as an Edit event from ``repo``; return exit code and stderr."""
    event = {"tool_name": "Edit", "tool_input": {"file_path": str(review_path.resolve())}, "cwd": str(repo)}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
    result = _proc([sys.executable, str(hook_script())], repo, input=json.dumps(event), env=env)
    return result.returncode, result.stderr


# --- json io ------------------------------------------------------------------------------------------------


def _read_json(path: Path, hint: str = "") -> Dict[str, object]:
    """JSON object at ``path``; raise ``CaptureError`` (with ``hint``) when missing or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CaptureError([f"cannot read {path} ({exc}){'; ' + hint if hint else ''}"]) from exc
    if not isinstance(data, dict):
        raise CaptureError([f"{path} must hold a JSON object"])
    return data


def _write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (sibling temp file, then ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _write_json(path: Path, data: object) -> None:
    """Write ``data`` as indented UTF-8 JSON, atomically."""
    _write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _rel(repo: Path, path: Path) -> str:
    """Repo-relative posix form of ``path`` (absolute posix when outside ``repo``)."""
    try:
        return path.resolve().relative_to(repo).as_posix()
    except ValueError:
        return path.as_posix()


# --- capture: metadata, scope, guards -----------------------------------------------------------------------


def gh_command(pr: int) -> str:
    """The Phase 1 Check 1 command line as recorded in ``pr_metadata_check``."""
    return f"gh pr view {pr} --json {GH_FIELDS} --jq '{GH_PROJECTION}'"


def read_metadata(repo: Path, pr: int) -> Tuple[Dict[str, object], str]:
    """The projected ``gh pr view`` object and its raw stdout; raise ``CaptureError`` when unparseable."""
    raw = run_gh(repo, ["pr", "view", str(pr), "--json", GH_FIELDS, "--jq", GH_PROJECTION])
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise CaptureError([f"gh pr view {pr} output does not parse ({exc})"]) from exc
    missing = [k for k in _GH_KEYS if not isinstance(data, dict) or k not in data]
    if missing:
        raise CaptureError([f"gh pr view {pr} output lacks {', '.join(missing)}"])
    return data, raw


def metadata_check(pr: int, data: Mapping[str, object], raw: str, allow_closed: bool) -> Dict[str, str]:
    """``pr_metadata_check`` block; a non-OPEN PR raises unless ``allow_closed`` (a replay)."""
    state = str(data["state"])
    if state != "OPEN" and not allow_closed:
        problem = f"PR {pr} state={state}: Phase 1 stops on a non-OPEN PR (--allow-closed replays)"
        raise CaptureError([problem])
    result = f"OK (state={state})" if state == "OPEN" else f"REPLAY (state={state}; build refuses it)"
    return {"command": gh_command(pr), "stdout": raw, "result": result}


def pr_meta(data: Mapping[str, object]) -> PrMeta:
    """``PrMeta`` from the projected gh object."""
    merge = data.get("mergeCommit")
    return PrMeta(int(data["number"]), str(data["title"]), str(data["baseRefName"]), str(data["headRefName"]),
                  str(data["headRefOid"]), str(merge) if merge else None)


def split_reviewable(facts: PrFacts, patterns: Sequence[str]) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """(reviewable paths, excluded machine-generated paths), in PR order."""
    excluded = tuple(f.path for f in facts.files if rp.is_excluded(f.path, patterns))
    return tuple(f.path for f in facts.files if f.path not in excluded), excluded


def grep_roots() -> Tuple[str, ...]:
    """Top-level folders searched for skill cross-references: ``GREP_ROOTS`` plus the skills root."""
    top = rp.skills_dir().split("/", 1)[0]
    return tuple(dict.fromkeys((*GREP_ROOTS, top)))


def grep_lines(repo: Path, head: str, name: str) -> List[str]:
    """``<path>:<lineno>:<text>`` lines naming ``name`` under ``grep_roots()`` at ``head``."""
    result = git(repo, "grep", "-I", "-n", "-F", name, head, "--", *grep_roots())
    if result.returncode == 1:
        return []
    if result.returncode != 0:
        raise CaptureError([f"git grep {name} failed: {result.stderr.strip()}"])
    prefix = f"{head}:"
    return [line[len(prefix):] if line.startswith(prefix) else line for line in result.stdout.splitlines()]


def lens_paths(repo: Path, facts: PrFacts, reviewable: Sequence[str], patterns: Sequence[str],
               catalog: Mapping[str, object]) -> Tuple[Dict[str, Tuple[str, ...]], Tuple[str, ...]]:
    """Triggered path-carrying lenses (per-skill-package, multi-artifact, the catalog's project lenses) and
    the triggered skill names."""
    skills = tuple(s for s in rp.skills_touched(reviewable)
                   if rp.skill_mentioned(s, grep_lines(repo, facts.head_sha, s), patterns))
    folders = tuple(rp.skill_folder(s) for s in skills)
    lenses: Dict[str, Tuple[str, ...]] = {}
    if folders:
        lenses[rp.SKILL_PACKAGE] = tuple(p for p in reviewable if p.startswith(folders))
    new = rp.multi_artifact([(f.status, f.path) for f in facts.files if f.path in reviewable])
    if new:
        lenses[rp.MULTI_ARTIFACT] = new
    lenses.update(rp.project_lens_paths(catalog, reviewable))
    return lenses, skills


def pinned_tests(repo: Path, facts: PrFacts) -> List[str]:
    """Touched test files (not deleted) whose head content carries the configured content pin."""
    pin = rp.content_pin()
    pinned: List[str] = []
    for f in facts.files:
        if pin is not None and f.status != "D" and rp.is_pin_candidate(f.path):
            text = git(repo, "show", f"{facts.head_sha}:{f.path}").stdout
            pinned += [f.path] if pin.search(text) else []
    return pinned


def guard_command(suite: Sequence[str]) -> str:
    """The recorded structural guard invocation, naming the interpreter ``run_guards`` actually uses."""
    exe = Path(sys.executable).as_posix()
    return f"{exe} -m pytest -q -p no:cacheprovider " + " ".join(suite)


def guards_check(repo: Path, decision: rp.GuardDecision, at_head: bool) -> Dict[str, object]:
    """``structural_guards_check`` block; run the suite when it applies and raise when it fails.

    The suite runs in the working tree, so an applicable guard run off the PR head (``at_head`` False: HEAD
    differs or reviewable PR paths carry local edits) raises instead of recording a result for other code.
    """
    if not decision.applies:
        return {"applies": False, "command": "", "stdout_tail": "",
                "result": "SKIPPED (no CICD/test-infra paths in PR)"}
    if not at_head:
        raise CaptureError(["structural guards apply but the working tree is not the PR head (HEAD differs "
                            "or PR paths have local edits): check out the PR head, then rerun capture"])
    rc, output = run_guards(repo, decision.suite)
    tail = output.rstrip().splitlines()[-GUARD_TAIL_LINES:]
    if rc != 0:
        raise CaptureError([f"structural guards failed (rc {rc}): STOP, do not dispatch reviewers",
                            *(f"  {line}" for line in tail[-5:])])
    passed = re.search(r"(\d+) passed", "\n".join(tail))
    return {"applies": True, "command": guard_command(decision.suite), "stdout_tail": "\n".join(tail),
            "result": f"OK ({passed.group(1) if passed else 0} passed)"}


def roast_choice(choice: str) -> bool:
    """``yes`` / ``no``, or a fresh 50/50 roll for ``roll``."""
    return choice == "yes" or (choice == "roll" and rp.roll_roast(random.Random()))


def tree_at_head(repo: Path, head: str, paths: Sequence[str]) -> bool:
    """True when HEAD is the PR head and none of ``paths`` has local edits, tracked or untracked."""
    if git_out(repo, "rev-parse", "HEAD").strip() != head:
        return False
    return not status_paths(repo) & set(paths)


def status_paths(repo: Path) -> Set[str]:
    """Paths with local edits (staged, unstaged, untracked non-ignored), both sides of a staged rename."""
    tokens = git_out(repo, "--no-optional-locks", "status", "--porcelain", "-z",
                     "--untracked-files=all").split("\0")
    paths: Set[str] = set()
    pos = 0
    while pos < len(tokens) and tokens[pos]:
        entry = tokens[pos]
        paths.add(entry[3:])
        if entry[0] in "RC" or entry[1] in "RC":
            pos += 1
            paths.add(tokens[pos])
        pos += 1
    return paths


def run_id_for(pr: int) -> str:
    """``pr<N>_<UTC yyyymmddTHHMMSSZ>``."""
    return f"pr{pr}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"


# --- capture: plan ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """Capture-time scope: reviewable and excluded paths, buckets, lenses, skills, guards, slots."""

    reviewable: Tuple[str, ...]
    excluded: Tuple[str, ...]
    buckets: Dict[str, Tuple[str, ...]]
    notes: Tuple[str, ...]
    lenses: Dict[str, Tuple[str, ...]]
    skills: Tuple[str, ...]
    guards: rp.GuardDecision
    slots: Tuple[rp.Slot, ...]


def plan_scope(repo: Path, facts: PrFacts, roast: bool, catalog: Mapping[str, object]) -> Scope:
    """Exclusions, buckets (registry auto-merge), lens triggers, guard decision and the reviewer slots."""
    ensure_default_exclusions(active())
    patterns = rp.exclusion_patterns(repo)
    reviewable, excluded = split_reviewable(facts, patterns)
    buckets, notes = rp.merge_registry_into_tests(rp.sort_buckets(reviewable))
    lenses, skills = lens_paths(repo, facts, reviewable, patterns, catalog)
    decision = rp.guard_decision([f.path for f in facts.files], pinned_tests(repo, facts))
    slots = rp.slot_plan(buckets, lenses, roast, reviewable, extra_lenses=rp.extra_lens_names(catalog))
    return Scope(reviewable, excluded, buckets, notes, lenses, skills, decision, slots)


def review_meta(facts: PrFacts) -> Dict[str, object]:
    """The review-document fields capture knows."""
    return {"pr": facts.number, "pr_title": facts.pr_title, "branch": facts.head, "base_branch": facts.base,
            "base_sha": facts.merge_base, "head_sha": facts.head_sha,
            "stats": {"additions": facts.additions, "deletions": facts.deletions,
                      "files_changed": len(facts.files)}}


def plan_document(run_id: str, data: Mapping[str, object], facts: PrFacts, scope: Scope,
                  dispatch_time: Mapping[str, object], at_head: bool, roast: bool) -> Dict[str, object]:
    """``plan.json`` content."""
    return {
        "run_id": run_id, "pr": facts.number, "state": data["state"], "url": data.get("url"),
        "first_sha": data.get("first_sha"), "last_sha": data.get("last_sha"), "meta": review_meta(facts),
        "excluded": list(scope.excluded), "buckets": scope.buckets, "registry_notes": list(scope.notes),
        "lenses": scope.lenses, "skills": list(scope.skills), "guards": asdict(scope.guards), "roast": roast,
        "slots": [asdict(s) for s in scope.slots], "dispatch_time": dict(dispatch_time),
        "tree_at_head": at_head, "dispatch_epoch": _utc_now(), "build_head": None, "review_path": None,
        "folded": [], "phase": "review",
    }


def _utc_now() -> str:
    """Current UTC time, ISO 8601 to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- briefs -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BriefContext:
    """Run-wide values every brief draws on."""

    repo: str
    lib: str
    pr: int
    run_id: str
    facts: PrFacts
    at_head: bool
    catalog: Mapping[str, object]
    skills: Tuple[str, ...]

    def file(self, path: str) -> Optional[PrFile]:
        """The PR file at ``path``, if any."""
        return next((f for f in self.facts.files if f.path == path), None)


def load_catalog() -> Dict[str, object]:
    """The plugin lens catalog merged with the project's lens file; a malformed lens file raises."""
    try:
        return rp.load_lens_catalog()
    except (OSError, ValueError) as exc:
        raise CaptureError([f"lens catalog: {exc}"]) from exc


def header_lines(agent: str, role: str, run_id: str, pr: int) -> List[str]:
    """The four column-1 run header lines."""
    return [f"AGENT_ID: {agent}", f"AGENT_ROLE: {role}", f"RUN_ID: {run_id}", f"PR: {pr}"]


def dispatch_row(agent_type: str, model: str, agent: str, role: str, run_id: str, pr: int,
                 brief: Path) -> str:
    """``agent=<type> model=<m>`` then the prompt: four header lines and ``Brief: <abs path>``."""
    lines = [f"agent={agent_type} model={model}", *header_lines(agent, role, run_id, pr),
             f"Brief: {brief.resolve().as_posix()}"]
    return "\n".join(lines)


def partial_paths(diff_text: str) -> List[str]:
    """Paths whose diff section is summarized, character-clipped or omitted."""
    out: List[str] = []
    current, partial = None, False
    for line in diff_text.splitlines() + ["=== <end> [full, +0 -0] ==="]:
        match = _SECTION.match(line)
        if match:
            out += [current] if current and partial else []
            current, partial = match.group(1), match.group(2) != "full"
        elif _CLIPPED.search(line):
            partial = True
    return out


def slot_diff(repo: Path, facts: PrFacts, slot: rp.Slot, patches: Optional[Mapping[str, str]] = None) -> str:
    """Budgeted diff of the slot's paths that are not new files; ``patches`` holds already-read diffs."""
    files = [f for f in facts.files if f.path in slot.paths and f.status != "A"]
    return budgeted_diff(repo, facts, files, PR_BLOCK_BUDGET, PR_CHAR_BUDGET, patches) if files else ""


def _role(slot: rp.Slot) -> str:
    """One-line role description of a slot."""
    if slot.roast:
        return "roast reviewer covering the OVERALL scope" if slot.lens == "overall" else "roast reviewer"
    if slot.lens == "overall":
        return "OVERALL reviewer"
    if slot.lens in rp.PATH_BUCKETS:
        return f"`{slot.lens}` bucket reviewer"
    return f"`{slot.lens}` cross-cutting lens reviewer"


def brief_header(ctx: BriefContext, slot: rp.Slot) -> str:
    """Title, run header values, role and the PR refs."""
    f = ctx.facts
    lines = [f"# Reviewer brief: {slot.id} - PR #{ctx.pr}", ""]
    lines += [f"- {line}" for line in header_lines(slot.id, "reviewer", ctx.run_id, ctx.pr)]
    lines += ["", f"Role: {_role(slot)}, model `{slot.model}`.",
              f"PR \"{f.pr_title}\" (`{f.head}` -> `{f.base}`); merge base `{f.merge_base}`, "
              f"head `{f.head_sha}`."]
    return "\n".join(lines)


def _read_method(ctx: BriefContext) -> str:
    """How to read in-scope files: the working tree, or ``git show`` at the PR head."""
    if ctx.at_head:
        return (f"Read method: the working tree is the PR head and these paths are clean; Read them under "
                f"`{ctx.repo}/`.")
    return (f"Read method: the working tree is not the PR head (or has local edits); read each path not "
            f"marked deleted with `git -C {ctx.repo} show {ctx.facts.head_sha}:<path>`. A deleted path has "
            f"no PR-head version; read its merge-base version with "
            f"`git -C {ctx.repo} show {ctx.facts.merge_base}:<path>` or its removal in the diff.")


def _path_line(ctx: BriefContext, path: str) -> str:
    """One scope line: status and counts, or the new-file / deleted-file note."""
    f = ctx.file(path)
    if f is None:
        return f"- {path}"
    if f.status == "A":
        return f"- {path}: new file, {f.added} lines - read it"
    if f.status == "D":
        return f"- {path}: deleted in this PR (no PR-head version); the diff shows the removal"
    moved = f" (renamed from {f.old_path})" if f.old_path else ""
    return f"- {path} ({f.status}, +{f.added} -{f.deleted}){moved}"


def scope_section(ctx: BriefContext, slot: rp.Slot, diff_path: Path, partial: Sequence[str]) -> str:
    """Scope paths, the read method, the diff file and fetch commands for partially shown paths."""
    lines = ["## Scope", "", _read_method(ctx),
             f"Diff: `{diff_path.resolve().as_posix()}` (modified, renamed and deleted paths; new files are "
             f"not in it).", ""]
    lines += [_path_line(ctx, p) for p in slot.paths]
    if partial:
        lines += ["", "Summarized or omitted in the diff; read the full diff with:"]
        lines += [f"- `git -C {ctx.repo} diff {ctx.facts.merge_base} {ctx.facts.head_sha} -- {p}`"
                  for p in partial]
    return "\n".join(lines)


def _scope_text(slot: rp.Slot) -> str:
    """The slot's own scope sentence (bucket, OVERALL / roast); empty for cross-cutting lenses."""
    if slot.lens in rp.PATH_BUCKETS:
        return BUCKET_SCOPE.format(bucket=slot.lens)
    return OVERALL_SCOPE if slot.lens in ("overall", "roast") else ""


def lens_section(ctx: BriefContext, slot: rp.Slot) -> str:
    """Scope sentence, catalog lens templates, triggered skills and the default sub-lens templates."""
    templates = {str(lens["name"]): str(lens["scope_template"]) for lens in ctx.catalog["lenses"]}
    lines = ["## Lens", ""] + ([_scope_text(slot), ""] if _scope_text(slot) else [])
    for name in slot.templates:
        lines += [f"### {name}", "", templates.get(name, f"(no catalog template named {name})"), ""]
    if slot.lens == rp.SKILL_PACKAGE and ctx.skills:
        lines += [f"Triggered skills (substitute each for `<name>`): {', '.join(ctx.skills)}", ""]
    for sub in ctx.catalog["default_sub_lenses"]:
        lines += [f"### Default sub-lens: {sub['name']}", "", str(sub["scope_template"]), ""]
    return "\n".join(lines).rstrip()


def ownership_clause() -> str:
    """The reviewer ownership rule naming the project's review directory."""
    reviews = active().artifacts.reviews.rstrip("/")
    return (f"Record findings only through `record`; never write under `{reviews}/`; "
            f"reply with the printed block only.")


def _tests_in_scope(paths: Sequence[str]) -> bool:
    """True when any path reviews as a test path or is a test file in any bucket (``cicd`` included)."""
    tests = active().tests
    return any(rp.review_bucket(p) == "tests" or tests.is_test_path(p) for p in paths)


def domain_pointers(paths: Sequence[str]) -> List[str]:
    """The configured ``review.domain_pointers`` texts whose prefix starts any of ``paths``."""
    return [d.pointer for d in active().review.domain_pointers if any(p.startswith(d.prefix) for p in paths)]


def rules_section(slot: rp.Slot) -> str:
    """Ownership, severity and finding-shape rules, plus the conditional clauses."""
    rules = [ownership_clause(), *SEVERITY_RULES]
    rules += [TEST_DESIGN_CLAUSE] if _tests_in_scope(slot.paths) else []
    rules += domain_pointers(slot.paths)
    rules += [ROAST_VOICE] if slot.roast else []
    return "\n".join(["## Rules", ""] + [f"- {rule}" for rule in rules])


def record_heredoc(ctx: BriefContext, call: str, lists: Sequence[Tuple[str, Sequence[str]]]) -> str:
    """A ``sh "<plugin>/scripts/hpy" - <<'EOF'`` heredoc runnable from any directory, ending with ``call``."""
    name = call.split("(", 1)[0]
    lines = [f"{hpy_command()} - <<'EOF'", "import sys", "from pathlib import Path",
             f'sys.path.insert(0, r"{ctx.lib}")', f"from harness_lib.review_models import {name}", ""]
    for name, examples in lists:
        lines += [f"{name} = [", *(f"    # {e}" for e in examples), "]"]
    return "\n".join(lines + [call, "EOF"])


def record_section(ctx: BriefContext, slot: rp.Slot) -> str:
    """The exact ``record`` heredoc and the reply rule."""
    call = (f'record({ctx.pr}, "{slot.id}", FINDINGS, STRENGTHS, repo=Path(r"{ctx.repo}"), '
            f'run_id="{ctx.run_id}")')
    example = ('{"severity": "important", "name": "...", "summary": "...", "fix": ["..."],',
               ' "file": "src/pkg/x.py", "lines": "12-18", "also": [], "fix_kind": "mechanical"},')
    lists = (("FINDINGS", example), ("STRENGTHS", ('"one line per strength",',)))
    return "\n".join(["## Record (once, after the analysis)", "",
                      "Fill FINDINGS and STRENGTHS, then run this once from any directory; a rerun replaces "
                      "the report. An error names the failing finding index.", "", "```bash",
                      record_heredoc(ctx, call, lists), "```", "",
                      "Reply with the block `record` prints, verbatim, and nothing else."])


def reviewer_brief(ctx: BriefContext, slot: rp.Slot, diff_path: Path, partial: Sequence[str]) -> str:
    """The full reviewer brief for ``slot``."""
    parts = [brief_header(ctx, slot), scope_section(ctx, slot, diff_path, partial), lens_section(ctx, slot),
             rules_section(slot), record_section(ctx, slot)]
    return "\n\n".join(parts) + "\n"


def write_briefs(repo: Path, run: Path, ctx: BriefContext, slots: Sequence[rp.Slot]) -> None:
    """Write ``diffs/<slot>.diff`` and ``briefs/<slot>.md`` for every slot (each path's diff read once)."""
    scoped = {p for slot in slots for p in slot.paths}
    changed = [f for f in ctx.facts.files if f.path in scoped and f.status != "A"]
    patches = file_patches(repo, ctx.facts, changed)
    for slot in slots:
        text = slot_diff(repo, ctx.facts, slot, patches)
        diff_path = run / "diffs" / f"{slot.id}.diff"
        _write_text(diff_path, text + "\n" if text else "(no modified paths in scope; new files only)\n")
        brief = reviewer_brief(ctx, slot, diff_path, partial_paths(text))
        _write_text(run / "briefs" / f"{slot.id}.md", brief)


# --- capture command ----------------------------------------------------------------------------------------


def capture_summary(plan: Mapping[str, object], scope: Scope) -> List[str]:
    """Status line and notes printed before the dispatch rows."""
    guards = plan["dispatch_time"]["structural_guards_check"]["result"]  # type: ignore[index]
    lines = [f"capture [done] | PR #{plan['pr']} | run {plan['run_id']} | slots: "
             f"{', '.join(s.id for s in scope.slots)} | roast: {'yes' if plan['roast'] else 'no'} | "
             f"guards: {guards}"]
    lines += [f"note: {n}" for n in scope.notes]
    lines += [f"excluded (machine-generated): {len(scope.excluded)}"] if scope.excluded else []
    lines += base_note(str(plan["meta"]["base_branch"]))  # type: ignore[index]
    return lines + [f"dispatch every row below in one message (subagent_type={REVIEWER_AGENT}):", ""]


def base_note(base: str) -> List[str]:
    """A note when the PR's base is not the project's configured base branch."""
    configured = active().resolve_base_branch()
    if base == configured:
        return []
    return [f"note: PR base {base} is not the configured base branch {configured}"]


def _cmd_capture(repo: Path, args: argparse.Namespace) -> int:
    """Run ``capture``: Phase 1 checks, the slot plan, briefs, diffs and the dispatch rows."""
    data, raw = read_metadata(repo, args.pr)
    check = metadata_check(args.pr, data, raw, args.allow_closed)
    facts = capture_pr(repo, pr_meta(data), not args.no_fetch)
    roast = roast_choice(args.roast)
    catalog = load_catalog()
    scope = plan_scope(repo, facts, roast, catalog)
    at_head = tree_at_head(repo, facts.head_sha, scope.reviewable)
    guards = guards_check(repo, scope.guards, at_head)
    dispatch_time = {"pr_metadata_check": check, "structural_guards_check": guards}
    run_id = run_id_for(args.pr)
    run = rm.start_run(args.pr, run_id, repo)
    plan = plan_document(run_id, data, facts, scope, dispatch_time, at_head, roast)
    _write_text(run / "phase1_meta.txt", raw)
    ctx = BriefContext(repo.as_posix(), _LIB.as_posix(), args.pr, run_id, facts, at_head, catalog,
                       scope.skills)
    write_briefs(repo, run, ctx, scope.slots)
    _write_json(run / "plan.json", plan)
    rows = [dispatch_row(REVIEWER_AGENT, s.model, s.id, "reviewer", run_id, args.pr,
                         run / "briefs" / f"{s.id}.md") for s in scope.slots]
    print("\n".join(capture_summary(plan, scope) + [row + "\n" for row in rows]))
    return 0


# --- run state: plan, reports, draft, review ----------------------------------------------------------------


def load_plan(repo: Path, pr: int) -> Tuple[Path, Dict[str, object]]:
    """Current run directory and its ``plan.json``."""
    run = rm.run_dir(pr, repo)
    return run, _read_json(run / "plan.json", "rerun capture")


def save_plan(run: Path, plan: Dict[str, object], phase: str) -> None:
    """Write ``plan.json`` with ``phase`` set; called only once a subcommand's work has succeeded."""
    plan["phase"] = phase
    _write_json(run / "plan.json", plan)


def report_sources(plan: Mapping[str, object]) -> List[Tuple[str, str, str]]:
    """(report id, label, reviewers credit) for the plan's slots, then its folded sources, in order."""
    slots = [(str(s["id"]), "slot", f"{s['id']} ({s['model']})") for s in plan["slots"]]  # type: ignore[union-attr]
    folded = plan.get("folded") or []
    return slots + [(str(f["id"]), "folded source", f"{f['id']} ({f['kind']})") for f in folded]  # type: ignore


def stray_reports(run: Path, plan: Mapping[str, object]) -> List[str]:
    """One problem per ``findings/*.json`` that is neither a slot nor a folded source."""
    known = {source for source, _, _ in report_sources(plan)}
    folder = run / "findings"
    found = sorted(folder.glob("*.json")) if folder.is_dir() else []
    return [f"{_rel(run, p)} is neither a slot nor a folded source: fold it (fold --findings) or remove it"
            for p in found if p.stem not in known]


def source_reports(run: Path, plan: Mapping[str, object]) -> List[rm.ReviewerReport]:
    """Reports of the slots, then the folded sources; a missing report or a stray findings file raises."""
    paths = [(source, label, run / "findings" / f"{source}.json")
             for source, label, _ in report_sources(plan)]
    problems = [f"no report for {label} {source} ({_rel(run, p)}): that reviewer has not recorded"
                for source, label, p in paths if not p.is_file()]
    problems += stray_reports(run, plan)
    if problems:
        raise CaptureError(problems)
    return [rm.load_report(p) for _, _, p in paths]


def issue_row(issue: Mapping[str, object]) -> str:
    """``I3 important path:lines [slots] name``."""
    where = f"{issue['file']}:{issue['lines']}" if issue.get("lines") else str(issue["file"])
    return f"{issue['id']} {_TIER[str(issue['id'])[0]]} {where} [{issue.get('reviewer', '')}] {issue['name']}"


def issue_table(issues: Sequence[Mapping[str, object]], strengths: int) -> str:
    """Issue rows, merge candidates and the strengths count."""
    pairs = rmg.merge_candidates(list(issues))  # type: ignore[arg-type]
    lines = [issue_row(i) for i in issues] or ["(no findings)"]
    lines += ["merge candidates:" + ("" if pairs else " none"), *(f"  {a} + {b}" for a, b in pairs)]
    return "\n".join(lines + [f"strengths: {strengths}"])


def _union(items: Iterable[str]) -> List[str]:
    """Distinct ``items`` in first-seen order."""
    return list(dict.fromkeys(items))


def refuse_built(plan: Mapping[str, object], command: str) -> None:
    """Raise when ``build`` already wrote the review: a draft change would never reach it."""
    if plan.get("review_path"):
        raise CaptureError([f"the review is built ({plan['review_path']}): {command} no longer applies; "
                            f"fold new findings, or start a new capture to rebuild deliberately"])


def _cmd_merge(repo: Path, args: argparse.Namespace) -> int:
    """Run ``merge``: reports -> ``draft.json`` and the issue table (refused once the review is built)."""
    run, plan = load_plan(repo, args.pr)
    refuse_built(plan, "merge")
    path = run / "draft.json"
    if path.is_file() and _read_json(path).get("amend") and not args.force:
        raise CaptureError([f"{_rel(repo, path)} carries amend operations; rerun merge with --force to "
                            f"drop them"])
    reports = source_reports(run, plan)
    issues = rmg.merge_findings(reports)
    strengths = _union(s for r in reports for s in r.strengths)
    sources = report_sources(plan)
    _write_json(path, {"issues": issues, "strengths": strengths, "reviewers": [c for _, _, c in sources],
                       "sources": [s for s, _, _ in sources], "amend": []})
    save_plan(run, plan, "consolidate")
    print(issue_table(issues, len(strengths)))
    return 0


def _amend_one(issues: List[Dict[str, object]], kind: str, value: str) -> Tuple[List[Dict[str, object]], str]:
    """Apply one ``regrade`` (``I3=minor``) or ``merge`` (``I3+I7``) operation; return issues and a note."""
    if kind == "regrade":
        issue_id, _, severity = value.partition("=")
        before = {str(i["id"]) for i in issues}
        out = rmg.regrade(issues, issue_id.strip(), severity.strip())
        new = sorted({str(i["id"]) for i in out} - before)
        return out, f"{issue_id.strip()} -> {', '.join(new)}"
    ids = [i.strip() for i in value.split("+") if i.strip()]
    if len(ids) < 2:
        raise CaptureError([f"--merge {value!r} needs KEEP+DROP[+DROP...]"])
    return rmg.merge_ids(issues, ids[0], ids[1:]), f"{'+'.join(ids[1:])} folded into {ids[0]}"


def _cmd_amend(repo: Path, args: argparse.Namespace) -> int:
    """Run ``amend``: regrades and merges in argument order, logged in the draft (refused once built)."""
    run, plan = load_plan(repo, args.pr)
    refuse_built(plan, "amend")
    path = run / "draft.json"
    draft = _read_json(path, "run merge first")
    if not args.ops:
        raise CaptureError(["amend needs at least one --regrade or --merge"])
    issues = list(draft["issues"])  # type: ignore[call-overload]
    for kind, value in args.ops:
        issues, note = _amend_one(issues, kind, value)
        draft.setdefault("amend", []).append({"op": kind, "value": value, "result": note})  # type: ignore[union-attr]
    draft["issues"] = issues
    _write_json(path, draft)
    save_plan(run, plan, "consolidate")
    print(issue_table(issues, len(draft.get("strengths") or [])))  # type: ignore[arg-type]
    return 0


def commit_review(repo: Path, path: Path, doc: Mapping[str, object]) -> List[str]:
    """Validate and write ``doc`` through ``review_edit.save_review`` (raise on problems; the file's LF / CRLF
    style kept), then run the hook.

    Returns the hook problem (a nonzero exit) as a list; the hook's informational stderr is echoed.
    """
    try:
        review_edit.save_review(path, doc, repo)
    except ValueError as exc:
        raise CaptureError([line for line in str(exc).splitlines() if line.strip()]) from exc
    rc, err = run_hook(repo, path)
    if rc != 0:
        return [f"schema hook exited {rc} on {_rel(repo, path)}: {' | '.join(err.strip().splitlines())}"]
    for line in err.strip().splitlines():
        print(f"hook: {line}")
    return []


def load_review(repo: Path, plan: Mapping[str, object]) -> Tuple[Path, Dict[str, object]]:
    """The review path recorded by ``build`` and its document."""
    if not plan.get("review_path"):
        raise CaptureError(["no review recorded for this run; run build first"])
    path = repo / str(plan["review_path"])
    try:
        return path, review_edit.load_review(path)
    except (OSError, ValueError) as exc:
        raise CaptureError([f"cannot read {path} ({exc})"]) from exc


def all_issues(doc: Mapping[str, object]) -> List[Dict[str, object]]:
    """Every issue of a review, critical first."""
    return [i for tier in rmg.TIERS for i in doc["issues"].get(tier, [])]  # type: ignore[union-attr]


def closed_ids(doc: Mapping[str, object]) -> Set[str]:
    """Ids whose latest resolution is RESOLVED or CLOSED_NO_ACTION."""
    latest = {str(r["id"]): r.get("status") for r in doc.get("post_review_resolutions") or []}  # type: ignore
    return {i for i, status in latest.items() if status in rmg.CLOSED_STATUSES}


# --- fold: outside reviews as findings sources --------------------------------------------------------------


@dataclass(frozen=True)
class FoldInput:
    """What one fold records: findings, strengths, where they came from and notes to print."""

    findings: Tuple[Dict[str, object], ...]
    strengths: Tuple[str, ...]
    origin: str
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class GhReview:
    """One fetched PR review: its pull API path (``repos/<o>/<r>/pulls/<N>``), id, object and comments."""

    base: str
    review_id: str
    review: Dict[str, object]
    comments: Tuple[Dict[str, object], ...]


def read_findings(value: str) -> Tuple[List[object], List[str], str]:
    """(findings, strengths, origin) from a JSON file or ``-`` (stdin): a list of findings, or an object
    ``{"findings": [...], "strengths": [...]}``; anything else raises."""
    origin = "stdin" if value == "-" else Path(value).as_posix()
    try:
        data = json.loads(sys.stdin.read() if value == "-" else Path(value).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CaptureError([f"--findings {origin}: cannot read JSON ({exc})"]) from exc
    if isinstance(data, list):
        return data, [], origin
    if isinstance(data, dict) and isinstance(data.get("findings"), list):
        return list(data["findings"]), [str(s) for s in data.get("strengths") or []], origin
    raise CaptureError([f"--findings {origin}: expected a list of findings or an object with a findings "
                        "list"])


def _json_values(text: str) -> List[object]:
    """Every JSON value in ``text`` (``gh api --paginate`` prints one per page), list values flattened."""
    decoder, values, index, text = json.JSONDecoder(), [], 0, text.strip()
    while index < len(text):
        value, index = decoder.raw_decode(text, index)
        values.extend(value if isinstance(value, list) else [value])
        index = len(text) - len(text[index:].lstrip())
    return values


def gh_api(repo: Path, path: str, paginate: bool = False) -> List[object]:
    """JSON values ``gh api [--paginate] <path>`` prints."""
    return _json_values(run_gh(repo, ["api", *(["--paginate"] if paginate else []), path]))


def plan_repo_slug(plan_url: object) -> str:
    """``owner/repo`` (lowercase) of the captured PR url in plan.json; empty when it is not a GitHub url."""
    match = _GH_PR_URL.match(str(plan_url or "").strip())
    return f"{match.group(1)}/{match.group(2)}".lower() if match else ""


def parse_review_url(url: str, pr: int, slug: str) -> Tuple[str, str]:
    """(``repos/<o>/<r>/pulls/<N>``, review id) of a PR review URL; a malformed URL, another PR or another
    repository (``slug``, from plan_repo_slug) raises."""
    match = _GH_REVIEW_URL.match(url.strip())
    if not match:
        raise CaptureError([f"--from-gh-review {url!r} must look like "
                            f"https://github.com/<owner>/<repo>/pull/<N>#pullrequestreview-<id>"])
    owner, name, number, review_id = match.groups()
    if int(number) != pr:
        raise CaptureError([f"--from-gh-review names PR {number}, not PR {pr}"])
    if not slug or f"{owner}/{name}".lower() != slug:
        raise CaptureError([f"--from-gh-review names {owner}/{name}, not the PR's repository "
                            f"({slug or 'plan.json has no GitHub PR url'})"])
    return f"repos/{owner}/{name}/pulls/{number}", review_id


def fetch_review(repo: Path, url: str, pr: int, slug: str) -> GhReview:
    """The review ``url`` names and its inline comments, through ``run_gh``."""
    base, review_id = parse_review_url(url, pr, slug)
    review = next(iter(gh_api(repo, f"{base}/reviews/{review_id}")), None)
    if not isinstance(review, dict):
        raise CaptureError([f"gh api {base}/reviews/{review_id} returned no review object"])
    comments = gh_api(repo, f"{base}/reviews/{review_id}/comments", paginate=True)
    return GhReview(base, review_id, review, tuple(c for c in comments if isinstance(c, dict)))


def review_skip(review: GhReview) -> Optional[str]:
    """Why a review has nothing to fold (dismissed, or a blank body without inline comments), else None."""
    name = f"pullrequestreview-{review.review_id}"
    if str(review.review.get("state")) == "DISMISSED":
        return f"{name} is DISMISSED; nothing to fold"
    if not str(review.review.get("body") or "").strip() and not review.comments:
        return f"{name} has a blank body and no inline comments; nothing to fold"
    return None


def added_files(repo: Path, review: GhReview) -> Set[str]:
    """Files the PR adds (status ``added``), from the PR's file list."""
    files = gh_api(repo, f"{review.base}/files", paginate=True)
    return {str(f["filename"]) for f in files if isinstance(f, dict) and f.get("status") == "added"}


def comment_lines(comment: Mapping[str, object], added: Set[str]) -> Optional[str]:
    """``start-line`` / ``line``, else ``original_line``, else the diff position of an added file (it equals
    the file line there), else None."""
    line, start = comment.get("line"), comment.get("start_line")
    if line:
        return f"{start}-{line}" if start and start != line else str(line)
    if comment.get("original_line"):
        return str(comment["original_line"])
    if comment.get("position") and comment.get("path") in added:
        return str(comment["position"])
    return None


def _login(item: Mapping[str, object]) -> str:
    """``user.login`` of a GitHub object, else empty."""
    user = item.get("user")
    return str(user.get("login") or "") if isinstance(user, dict) else ""


def comment_finding(comment: Mapping[str, object], review: GhReview, severity: str,
                    added: Set[str]) -> Dict[str, object]:
    """One finding from one inline comment; the main session regrades it with ``amend`` afterwards."""
    body = str(comment.get("body") or "").strip()
    flat = " ".join(body.split())
    who = _login(comment) or _login(review.review) or "reviewer"
    finding: Dict[str, object] = {
        "severity": severity, "name": _SENTENCE_END.split(flat, maxsplit=1)[0][:NAME_LIMIT].rstrip(),
        "summary": f"{who} (pullrequestreview-{review.review_id}): {flat}", "fix": [body],
        "file": str(comment["path"]), "fix_kind": "judgment"}
    lines = comment_lines(comment, added)
    return {**finding, "lines": lines} if lines else finding


def gh_review_findings(repo: Path, review: GhReview, severity: str) -> List[Dict[str, object]]:
    """One finding per inline comment with a path and a non-blank body; the PR file list is read only
    when a comment needs a diff position mapped."""
    usable = [c for c in review.comments if c.get("path") and str(c.get("body") or "").strip()]
    needs = any(c.get("position") and not c.get("line") and not c.get("original_line") for c in usable)
    added = added_files(repo, review) if needs else set()
    return [comment_finding(c, review, severity, added) for c in usable]


def gh_fold_input(repo: Path, url: str, pr: int, severity: str, slug: str) -> FoldInput:
    """Findings of a GitHub PR review; a dismissed or empty review raises."""
    review = fetch_review(repo, url, pr, slug)
    skip = review_skip(review)
    if skip:
        raise CaptureError([skip])
    body = " ".join(str(review.review.get("body") or "").split())
    notes = (f"review body not folded (no file to anchor it): {body[:200]}; fold it with --findings when "
             f"it names a defect",) if body else ()
    return FoldInput(tuple(gh_review_findings(repo, review, severity)), (), url, notes)


def fold_input(repo: Path, args: argparse.Namespace, slug: str) -> FoldInput:
    """The findings ``--findings`` or ``--from-gh-review`` supplies; ``--severity`` fills a missing
    severity."""
    if args.findings is None:
        return gh_fold_input(repo, args.from_gh_review, args.pr, args.severity, slug)
    findings, strengths, origin = read_findings(args.findings)
    filled = tuple({"severity": args.severity, **f} if isinstance(f, dict) else f for f in findings)
    return FoldInput(filled, tuple(strengths), origin)  # type: ignore[arg-type]


def credited_ids(doc: Mapping[str, object], source: str) -> List[str]:
    """Ids of the review's issues whose ``reviewer`` credit names ``source``."""
    return [str(i["id"]) for i in all_issues(doc)
            if source in {s.strip() for s in str(i.get("reviewer", "")).split(",")}]


def fold_check(plan: Mapping[str, object], source: str, doc: Optional[Mapping[str, object]] = None) -> None:
    """Raise when ``source`` is a reviewer slot of the run, or when ``doc`` (the built review) already
    carries ``source`` as a folded source: re-folding it would duplicate its issues."""
    if source in {str(s["id"]) for s in plan["slots"]}:  # type: ignore[union-attr]
        raise CaptureError([f"--source {source} is a reviewer slot of this run; pick another id"])
    if doc is not None and source in {str(f["id"]) for f in plan.get("folded") or []}:  # type: ignore[union-attr]
        ids = ", ".join(credited_ids(doc, source)) or "no issues"
        raise CaptureError([f"--source {source} is already in the built review ({ids}); re-folding it would "
                            f"duplicate them: fold new findings under another --source id"])


def with_folded(entries: Sequence[Mapping[str, object]], entry: Dict[str, object]) -> List[Dict[str, object]]:
    """``entries`` with ``entry`` replacing the one of the same id in place, else appended."""
    out = [entry if e["id"] == entry["id"] else dict(e) for e in entries]
    return out if any(e["id"] == entry["id"] for e in entries) else [*out, entry]


def fold_entry(args: argparse.Namespace, origin: str, after_build: bool) -> Dict[str, object]:
    """The ``plan.json`` ``folded`` entry of one fold; ``after_build`` marks an append to a built review."""
    entry: Dict[str, object] = {"id": args.source, "kind": args.kind, "origin": origin, "at": _utc_now()}
    return {**entry, "after_build": True} if after_build else entry


def print_fold(args: argparse.Namespace, source: FoldInput, notes: Sequence[str] = ()) -> None:
    """The ``fold [done]`` line, then the source's notes and ``notes``."""
    print(f"fold [done] | {args.source} ({args.kind}) | {len(source.findings)} finding(s) "
          f"from {source.origin}")
    lines = [*source.notes, *notes]
    if lines:
        print("\n".join(f"note: {n}" for n in lines))


def _cmd_fold(repo: Path, args: argparse.Namespace) -> int:
    """Run ``fold``: record an outside review as a findings source of the run and register it; once the
    review is built, also append its issues to the review (``fold_after_build``); a built review whose
    Phase 4 first run failed refuses the fold before anything is written."""
    run, plan = load_plan(repo, args.pr)
    built = load_review(repo, plan) if plan.get("review_path") else None
    if built:
        require_phase4(built[1], "folding into the built review")
    fold_check(plan, args.source, built[1] if built else None)
    source = fold_input(repo, args, plan_repo_slug(plan.get("url")))
    rm.record(args.pr, args.source, list(source.findings), list(source.strengths), repo=repo,
              run_id=str(plan["run_id"]))
    entry = fold_entry(args, source.origin, built is not None)
    plan["folded"] = with_folded(plan.get("folded") or [], entry)  # type: ignore[arg-type]
    if built:
        return fold_after_build(repo, run, plan, built, args, source)
    save_plan(run, plan, "review")
    stale = ["draft.json predates this fold: rerun merge (merge --force when the draft was amended)"] \
        if (run / "draft.json").is_file() else []
    print_fold(args, source, stale)
    return 0


# --- fold after build: append with fresh ids ----------------------------------------------------------------


def recomputed_verdict(doc: Mapping[str, object]) -> str:
    """``review_edit.recompute_verdict`` over the review's issues and dispositions; a pending
    ``pre_fix_time`` holds READY."""
    return str(review_edit.recompute_verdict(doc)["verdict"])


def appended_review(doc: Mapping[str, object], added: Sequence[Dict[str, object]], credit: str,
                    report: str, strengths: Sequence[str]) -> Dict[str, object]:
    """``doc`` with ``added`` after its issues, ``credit`` in ``reviewers``, ``report`` in
    ``scoped_review_files``, ``strengths`` joined and the verdict recomputed; dispositions are kept."""
    out = json.loads(json.dumps(doc))
    out["issues"] = rmg.issues_by_severity([*all_issues(out), *added])
    out["reviewers"] = _union([*out.get("reviewers", []), credit])
    out["scoped_review_files"] = _union([*out.get("scoped_review_files", []), report])
    out["strengths"] = _union([*out.get("strengths", []), *strengths])
    out["verdict"] = recomputed_verdict(out)
    return out


OPEN_PASS_PHASES = ("fix-plan", "fix")


def folded_phase(phase: str) -> str:
    """The phase a fold after build saves: ``phase`` inside an open Phase 5 pass, else ``consolidate``, so a
    later fold still reads no open pass until ``bubble`` / ``waves`` open one."""
    return phase if phase in OPEN_PASS_PHASES else "consolidate"


def fold_next(phase: str) -> str:
    """The ``next:`` line of a fold after build. Inside an open Phase 5 pass (``phase`` ``fix-plan`` /
    ``fix``) the sentinel is still armed and the tree holds that pass's fixes, so the second run is skipped;
    otherwise (after a closeout, or before Phase 5 began) Phase 5 starts at the second run."""
    if phase in OPEN_PASS_PHASES:
        return "next: waves (new ids only), then closeout (Phase 5 pass open: no second run)"
    return "next: Phase 4 second run, then waves (new ids only)"


def appended_lines(added: Sequence[Mapping[str, object]], verdict: str,
                   pairs: Sequence[Tuple[str, str]], phase: str) -> List[str]:
    """Summary, issue rows, merge-candidate note and the next step of a fold after build; ``phase`` is the
    run's phase before the fold."""
    ids = ", ".join(str(i["id"]) for i in added) or "none"
    lines = [f"appended after build: {ids} | verdict: {verdict}", *(issue_row(i) for i in added)]
    if pairs:
        lines.append("note: merge candidates (not merged; amend does not run after build): "
                     + ", ".join(f"{a} + {b}" for a, b in pairs))
    return lines + [fold_next(phase)]


def fold_after_build(repo: Path, run: Path, plan: Dict[str, object], built: Tuple[Path, Dict[str, object]],
                     args: argparse.Namespace, source: FoldInput) -> int:
    """Append the just-recorded source's issues to the built review through ``commit_review`` (the hook
    runs), then save ``folded_phase``; a hook problem keeps the phase and raises after the write."""
    path, doc = built
    phase = str(plan.get("phase") or "")
    report_path = run / "findings" / f"{args.source}.json"
    report = rm.load_report(report_path)
    existing = all_issues(doc)
    added = rmg.append_findings(existing, report)
    credit = f"{args.source} ({args.kind})"
    out = appended_review(doc, added, credit, _rel(repo, report_path), report.strengths)
    problems = commit_review(repo, path, out)
    if problems:
        _write_json(run / "plan.json", plan)
    else:
        save_plan(run, plan, folded_phase(phase))
    print_fold(args, source)
    print("\n".join(appended_lines(added, str(out["verdict"]), rmg.cross_candidates(existing, added), phase)))
    if problems:
        raise CaptureError(problems)
    return 0


# --- build --------------------------------------------------------------------------------------------------


def review_dir(repo: Path) -> Path:
    """The project's review directory (``artifacts.reviews``)."""
    return repo / active().artifacts.reviews


def review_target(repo: Path, plan: Mapping[str, object]) -> Path:
    """``<artifacts.reviews>/<NNNN>_<slug>.json`` for the plan's PR."""
    meta = plan["meta"]
    slug = rmg.slugify_title(str(meta["pr_title"]))  # type: ignore[index]
    return review_dir(repo) / f"{int(plan['pr']):04d}_{slug}.json"


def straggler_check(repo: Path, pr: int, target: Path, replace: bool) -> None:
    """Raise on other review files for ``pr`` (padded or unpadded prefix) or an unreplaced existing target."""
    folder = review_dir(repo)
    found = sorted({p for n in {f"{pr:04d}_*.json", f"{pr}_*.json"} for p in folder.glob(n)}) \
        if folder.is_dir() else []
    problems = [f"straggler review file {_rel(repo, p)}: fold it in or remove it before build"
                for p in found if p.resolve() != target.resolve()]
    if target.exists() and not replace:
        problems.append(f"{_rel(repo, target)} exists; rerun build with --replace to overwrite it")
    if problems:
        raise CaptureError(problems)


def phase5_state(repo: Path, run: Path, target: Path) -> List[str]:
    """One problem per Phase 5 artifact a rebuild would orphan (dispositions, waves, fixes, closeout).

    ``merge_findings`` renumbers ids, so a rebuild under live dispositions or fixer reports would attach them
    to different findings.
    """
    review = _read_json(target) if target.is_file() else {}
    held = [f"{_rel(repo, target)} {k}" for k in ("post_review_resolutions", "bubbles", "bubble_up")
            if review.get(k)]
    held += [_rel(repo, run / n) for n in ("waves.json", "fixes", "closeout.json") if (run / n).exists()]
    return [f"Phase 5 began ({name}): build --replace would renumber ids under it; start a new capture "
            "instead" for name in held]


def build_meta(repo: Path, run: Path, plan: Mapping[str, object]) -> Dict[str, object]:
    """``review_document`` metadata: the captured fields, today's date and the scoped report paths."""
    meta = dict(plan["meta"])  # type: ignore[call-overload]
    meta["review_date"] = date.today().isoformat()
    meta["scoped_review_files"] = [_rel(repo, run / "findings" / f"{source}.json")
                                   for source, _, _ in report_sources(plan)]
    return meta


def unmerged_sources(plan: Mapping[str, object], draft: Mapping[str, object]) -> List[str]:
    """One problem per folded source missing from the draft's ``sources`` (a fold after the last merge)."""
    merged = draft.get("sources")
    if merged is None:
        return []
    return [f"folded source {f['id']} is not in draft.json: rerun merge (merge --force when amended)"
            for f in plan.get("folded") or [] if f["id"] not in merged]  # type: ignore[union-attr, index, operator]


def _json_object(text: str) -> Optional[Dict[str, object]]:
    """``text`` parsed as a JSON object, else None."""
    try:
        value = json.loads(text) if text.strip() else None
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _phase4_reason(rc: int, block: Optional[Mapping[str, object]]) -> str:
    """Why a Phase 4 first run does not count."""
    if rc == 2:
        return "argv error"
    if block is None:
        return "empty or non-JSON stdout (metadata failure)"
    return "a branch-safety check failed" if rc == 1 else "unexpected exit"


def head_desync_only(rc: int, block: Optional[Mapping[str, object]]) -> bool:
    """True when the one STOP of a Phase 4 run is ``sha_ancestry_check`` with ``head_ancestor_exit != 0``
    and ``base_ancestor_exit == 0`` (the remote PR head lags local HEAD; the operating rules waive it)."""
    if rc != 1 or block is None:
        return False
    stops = [n for n, b in block.items()
             if isinstance(b, dict) and str(b.get("result", "")).startswith("STOP")]
    check = block.get("sha_ancestry_check")
    return (stops == ["sha_ancestry_check"] and isinstance(check, dict)
            and check.get("head_ancestor_exit") != 0 and check.get("base_ancestor_exit") == 0)


def waiver_record(block: Mapping[str, object]) -> Dict[str, object]:
    """The ``phase4_waiver`` entry ``plan.json`` keeps for a waived head-ancestry STOP."""
    check = block["sha_ancestry_check"]
    return {"check": "sha_ancestry_check", "flag": "--waive-head-ancestry",
            "head_ancestor_exit": check["head_ancestor_exit"],  # type: ignore[index]
            "base_ancestor_exit": check["base_ancestor_exit"],  # type: ignore[index]
            "reason": "remote PR head is not an ancestor of local HEAD; merge base intact",
            "waived_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def apply_phase4(repo: Path, run: Path, pr: int, doc: Dict[str, object],
                 waive: bool = False) -> Tuple[Optional[str], Optional[Dict[str, object]]]:
    """Run Phase 4, keep its output, and insert ``pre_fix_time`` on success or a waived head desync.

    Returns (problem, waiver): the STOP problem when ``pre_fix_time`` stays pending, else None; the
    ``waiver_record`` when ``waive`` applied, else None.
    """
    rc, out, err = run_phase4(repo, pr)
    record = run / "phase4_first_run.json"
    _write_json(record, {"rc": rc, "stdout": out, "stderr": err})
    block = _json_object(out)
    desync = head_desync_only(rc, block)
    if block is not None and (rc == 0 or (desync and waive)):
        doc["verification_log"]["pre_fix_time"] = block  # type: ignore[index]
        return None, (waiver_record(block) if rc != 0 else None)
    reason = _phase4_reason(rc, block)
    hold_ready_verdict(doc, reason)
    hint = "; only the head ancestry failed: rerun build --replace --waive-head-ancestry" if desync else ""
    return (f"phase4 first run rc {rc}: {reason}; pre_fix_time left pending (see {_rel(repo, record)}); "
            f"STOP{hint}"), None


def hold_ready_verdict(doc: Dict[str, object], reason: str) -> None:
    """Turn a READY verdict into ``NOT READY TO MERGE - Phase 4 first run failed: <reason>``.

    A pending ``pre_fix_time`` allows no READY verdict, so the review is still written when Phase 4 fails.
    This override is a fifth verdict form, applied here rather than in ``review_merge.compute_verdict``.
    """
    if str(doc.get("verdict") or "").startswith("READY TO MERGE"):
        doc["verdict"] = review_edit.PHASE4_HOLD.format(reason=reason)


def _counts(doc: Mapping[str, object]) -> str:
    """``critical=C important=I minor=M``."""
    return " ".join(f"{t}={len(doc['issues'].get(t, []))}" for t in rmg.TIERS)  # type: ignore[union-attr]


def _cmd_build(repo: Path, args: argparse.Namespace) -> int:
    """Run ``build``: review document, Phase 4 first run, validated write, hook."""
    run, plan = load_plan(repo, args.pr)
    if plan["state"] != "OPEN":
        raise CaptureError([f"capture recorded state={plan['state']} (an --allow-closed replay); "
                            f"build refuses it"])
    target = review_target(repo, plan)
    if args.replace and phase5_state(repo, run, target):
        raise CaptureError(phase5_state(repo, run, target))
    draft = _read_json(run / "draft.json", "run merge first")
    if unmerged_sources(plan, draft):
        raise CaptureError(unmerged_sources(plan, draft))
    straggler_check(repo, args.pr, target, args.replace)
    doc = rmg.review_document(build_meta(repo, run, plan), draft, plan["dispatch_time"],  # type: ignore[arg-type]
                              schema_ref=rmg.schema_ref_for(target, active()))
    problem, waiver = apply_phase4(repo, run, args.pr, doc, args.waive_head_ancestry)
    phase4 = [problem] if problem else []
    try:
        problems = commit_review(repo, target, doc)
    except CaptureError as exc:
        raise CaptureError(exc.problems + phase4) from exc
    plan.update(build_head=git_out(repo, "rev-parse", "HEAD").strip(), review_path=_rel(repo, target),
                phase4_waiver=waiver)
    if not problems + phase4:
        plan["phase"] = "consolidate"
    _write_json(run / "plan.json", plan)
    print(f"wrote {_rel(repo, target)}\nverdict: {doc['verdict']}\n{_counts(doc)}")
    if waiver:
        print("note: Phase 4 head-ancestry STOP waived (--waive-head-ancestry; remote PR head lags local "
              "HEAD, merge base intact); recorded as phase4_waiver in plan.json")
    if problems + phase4:
        raise CaptureError(problems + phase4)
    return 0


# --- bubble -------------------------------------------------------------------------------------------------


def with_bubble(doc: Mapping[str, object], bubble: rm.FixBubble) -> Dict[str, object]:
    """``doc`` with ``bubble`` in ``bubbles`` and ``bubble_up`` (replacing older entries), verdict redone."""
    out = json.loads(json.dumps(doc))
    out["bubbles"] = _union([*out.get("bubbles", []), bubble.id])
    entry = bubble.model_dump(mode="json")
    out["bubble_up"] = [b for b in out.get("bubble_up", []) if b["id"] != bubble.id] + [entry]
    out["verdict"] = rmg.compute_verdict(out["issues"], out.get("post_review_resolutions") or [],
                                         out["bubbles"], out["bubble_up"])
    return out


def _cmd_bubble(repo: Path, args: argparse.Namespace) -> int:
    """Run ``bubble``: one issue handed to the developer; the verdict is recomputed."""
    run, plan = load_plan(repo, args.pr)
    path, doc = load_review(repo, plan)
    require_phase4(doc)
    if args.id not in {str(i["id"]) for i in all_issues(doc)}:
        raise CaptureError([f"{args.id}: no such issue in {_rel(repo, path)}"])
    if args.id in closed_ids(doc):
        raise CaptureError([f"{args.id}: already closed (latest resolution RESOLVED or CLOSED_NO_ACTION); "
                            f"bubble refused, {_rel(repo, path)} unchanged"])
    bubble = rm.FixBubble(id=args.id, classification=args.classification, reason=args.reason)
    doc = with_bubble(doc, bubble)
    problems = commit_review(repo, path, doc)
    print(f"bubbled {bubble.id} ({bubble.classification.value}) | verdict: {doc['verdict']}")
    if problems:
        raise CaptureError(problems)
    save_plan(run, plan, "fix-plan")
    return 0


# --- waves --------------------------------------------------------------------------------------------------


def fixer_bubbles(run: Path) -> List[Tuple[str, rm.FixBubble]]:
    """(fixer, bubble) for every bubble a fixer of this run recorded, by report file name."""
    return [(r.fixer, b) for r in rm.load_fix_reports(run / "fixes") for b in r.bubbled]


def pending_bubbles(doc: Mapping[str, object], run: Path) -> List[Tuple[str, rm.FixBubble]]:
    """Fixer bubbles whose id is not closed and in neither the review's ``bubbles`` nor its ``bubble_up``."""
    known = {str(b) for b in doc.get("bubbles") or []} | closed_ids(doc)  # type: ignore[union-attr]
    known |= {str(b["id"]) for b in doc.get("bubble_up") or []}  # type: ignore[union-attr, index]
    return [(fixer, b) for fixer, b in fixer_bubbles(run) if b.id not in known]


def pending_lines(pending: Sequence[Tuple[str, rm.FixBubble]]) -> List[str]:
    """``pending fixer bubbles`` heading, then one ``<id> (<classification>) from <fixer>: <reason>`` line
    per bubble; ``pending fixer bubbles: none`` without any."""
    if not pending:
        return ["pending fixer bubbles: none"]
    return ["pending fixer bubbles (audit each, then surface it to the developer before closeout):",
            *(f"  {b.id} ({b.classification.value}) from {fixer}: {b.reason}" for fixer, b in pending)]


def _selected(issues: Sequence[Dict[str, object]], ids: str) -> List[Dict[str, object]]:
    """The issues ``--ids`` names; an unknown id raises."""
    wanted = [i.strip() for i in ids.split(",") if i.strip()]
    unknown = [i for i in wanted if i not in {str(x["id"]) for x in issues}]
    if unknown:
        raise CaptureError([f"--ids names unknown issue(s): {', '.join(unknown)}"])
    return [i for i in issues if i["id"] in wanted]


def counted_bubbles(reports: Sequence[rm.FixReport], parts: Mapping[str, Mapping[str, object]]) -> Set[str]:
    """Ids bubbled by a planned fixer whose parts assign it that id (the rule closeout applies); a bubble
    closeout rejects (unplanned fixer, unassigned id) leaves its issue to re-plan."""
    return {b.id for r in reports for b in r.bubbled if b.id in parts.get(r.fixer, {})}


def _follow_up(open_issues: Sequence[Dict[str, object]], run: Path,
               checked: Optional[Tuple[Set[str], Set[str]]]) -> Tuple[List[Dict[str, object]], List[str]]:
    """(issues to plan, done ids): fully covered ids and ids a planned, assigned fixer bubbled are done; a
    partially fixed split issue is narrowed to its uncovered parts. With ``checked`` (changed, created; set
    once a closeout has run) only entries closeout accepts cover anything, so an id whose entries it
    rejected is re-planned."""
    reports = rm.load_fix_reports(run / "fixes")
    changed, created = checked if checked else (None, None)
    parts = fixer_parts(run)
    remaining = rmg.remaining_parts(open_issues, parts, reports, fixer_files=fixer_files(run),
                                    changed=changed, created=created)
    done = {i for i, missing in remaining.items() if not missing} | counted_bubbles(reports, parts)
    planned = [rmg.only_files(i, remaining[str(i["id"])]) if remaining.get(str(i["id"])) else i
               for i in open_issues]
    return planned, sorted(done)


def closeout_checked(repo: Path, plan: Mapping[str, object],
                     run: Path) -> Optional[Tuple[Set[str], Set[str]]]:
    """(changed, created) since ``build_head`` once a closeout ran (``CLOSEOUT_MARK`` exists), else None."""
    if not (run / CLOSEOUT_MARK).is_file() or not plan.get("build_head"):
        return None
    return changed_paths(repo, str(plan["build_head"]))


def wave_inputs(doc: Mapping[str, object], run: Path, ids: Optional[str],
                checked: Optional[Tuple[Set[str], Set[str]]] = None,
                ) -> Tuple[List[Dict[str, object]], List[str], List[str]]:
    """(issues, held, done) for ``plan_waves``; ``ids`` selects exactly those, nothing held or done.

    ``checked`` (see ``closeout_checked``) makes only closeout-accepted fix entries count as done.
    """
    issues = all_issues(doc)
    if ids:
        return _selected(issues, ids), [], []
    closed = closed_ids(doc)
    held = [str(b) for b in doc.get("bubbles") or []]  # type: ignore[union-attr]
    planned, done = _follow_up([i for i in issues if i["id"] not in closed], run, checked)
    return planned, held, done


def _registry_rows(repo: Path) -> List[Dict[str, object]]:
    """Entries (objects with a ``file``) of the configured ``tests.registry``; empty without one."""
    rel = active().tests.registry
    path = repo / rel if rel else None
    if path is None or not path.is_file():
        return []
    tests = _read_json(path).get("tests") or []
    return [e for e in tests if isinstance(e, dict) and "file" in e]  # type: ignore[union-attr]


def registry_entries(repo: Path) -> List[Tuple[str, Tuple[str, ...]]]:
    """(test file, test_target_paths) for every entry of the configured ``tests.registry``; empty without
    one."""
    props = ((e, e.get("properties") or {}) for e in _registry_rows(repo))
    return [(str(e["file"]), tuple(p.get("test_target_paths") or ()))  # type: ignore[union-attr]
            for e, p in props]


def timing_file(name: str) -> str:
    """A timing row's ``file`` as a registry path: forward slashes, no ``::`` test id, no leading ``./``."""
    path = name.replace("\\", "/").split("::", 1)[0]
    while path.startswith("./"):
        path = path[2:]
    return path


def file_seconds(repo: Path) -> Dict[str, float]:
    """Seconds per test file summed over the ``tests`` rows (``file``, numeric ``duration``) of the
    configured ``tests.timings`` report, keyed by ``timing_file``; empty when there is none or it cannot
    be read."""
    rel = active().tests.timings
    try:
        rows = _read_json(repo / rel).get("tests") if rel else None
    except CaptureError:
        return {}
    seconds: Dict[str, float] = {}
    for row in rows if isinstance(rows, list) else ():
        duration = row.get("duration") if isinstance(row, dict) else None
        if isinstance(row, dict) and isinstance(row.get("file"), str) and \
                isinstance(duration, (int, float)) and not isinstance(duration, bool):
            key = timing_file(row["file"])
            seconds[key] = seconds.get(key, 0.0) + float(duration)
    return seconds


def flag_set(entry: Mapping[str, object], dotted: str) -> bool:
    """True when the value at the dotted path ``dotted`` of a registry entry is ``true``."""
    value: object = entry
    for key in dotted.split("."):
        value = value.get(key) if isinstance(value, Mapping) else None
    return value is True


def defer_reasons(repo: Path) -> Dict[str, str]:
    """Registry test files fixers must not run, each with its reason: summed ``tests.timings`` seconds over
    ``tests.fixer_test_seconds``, else the ``tests.defer_flags`` paths that are true."""
    tests = active().tests
    ceiling = tests.fixer_test_seconds
    seconds = file_seconds(repo) if ceiling is not None else {}
    reasons: Dict[str, str] = {}
    for entry in _registry_rows(repo):
        test, flags = str(entry["file"]), [f for f in tests.defer_flags if flag_set(entry, f)]
        if ceiling is not None and seconds.get(test, 0.0) > ceiling:
            reasons[test] = f"measured {seconds[test]:g} s > {ceiling:g} s"
        elif flags:
            reasons[test] = ", ".join(flags)
    return reasons


def ceiling_line(repo: Path) -> Optional[str]:
    """A notice when ``tests.fixer_test_seconds`` is set but ``tests.timings`` yields no durations, so
    deferral falls back to ``tests.defer_flags`` alone; None otherwise."""
    tests = active().tests
    if tests.fixer_test_seconds is None or file_seconds(repo):
        return None
    return (f"deferral: tests.timings {tests.timings or '(unset)'} missing or unusable; "
            "runtime ceiling inactive (flags only)")


def tests_for(path: str, entries: Sequence[Tuple[str, Tuple[str, ...]]]) -> List[str]:
    """Registry test files that are ``path`` itself or whose targets name ``path`` or a folder holding it."""
    return [f for f, targets in entries
            if f == path or any(path == t or path.startswith(t.rstrip("/") + "/") for t in targets)]


def issue_files(issue: Mapping[str, object]) -> List[str]:
    """Full file list of a schema issue, primary file first."""
    return _union([str(issue["file"]), *(issue.get("files") or [])])  # type: ignore[misc]


def part_lines(issue: Mapping[str, object], part: Sequence[str]) -> List[str]:
    """``Your part`` and, when other fixers own the rest of the issue, ``Other parts``."""
    others = [f for f in issue_files(issue) if f not in part]
    lines = [f"Your part: {', '.join(part)}"]
    return lines + ([f"Other parts: {', '.join(others)} (another fixer)"] if others else [])


def _issue_block(issue: Mapping[str, object], part: Sequence[str]) -> List[str]:
    """One issue's section in a fixer brief; ``part`` is the files the fixer owns for it."""
    also = issue_files(issue)[1:]
    where = str(issue["file"]) + (f" (lines {issue['lines']})" if issue.get("lines") else "")
    where += f"; also {', '.join(also)}" if also else ""
    tier = _TIER[str(issue["id"])[0]]
    lines = [f"### {issue['id']} ({tier}, {issue.get('fix_kind', 'judgment')}) - {issue['name']}", "",
             f"Files: {where}", *part_lines(issue, part), "", str(issue["summary"]), "",
             "Fix options (any one resolves it; pick the safest, most mechanical):"]
    return lines + [f"- {option}" for option in issue["fix"]] + [""]  # type: ignore[union-attr]


def pytest_command(repo: str, tests: Sequence[str]) -> str:
    """One pytest run over the repo-relative ``tests`` through the plugin's ``hpy`` launcher; each absolute
    test path is shell-quoted, so a checkout path with spaces stays one argument."""
    paths = " ".join(shlex.quote(f"{repo}/{t}") for t in tests)
    return f"{hpy_command()} -m pytest {paths} -q -p no:cacheprovider"


def _tests_block(ctx: BriefContext, files: Sequence[str], entries: Sequence[Tuple[str, Tuple[str, ...]]],
                 deferred: Mapping[str, str]) -> List[str]:
    """Per-file registry tests: run commands, except deferred tests, named with their reason."""
    lines = ["## Files and tests", ""]
    for path in files:
        tests = tests_for(path, entries)
        lines.append(f"- {path}" + ("" if tests else ": no registered test"))
        lines += [f"  - deferred, do not run: `{t}` ({deferred[t]})" if t in deferred
                  else f"  - `{pytest_command(ctx.repo, [t])}`" for t in tests]
    return lines


def _fixer_rules() -> List[str]:
    """Fixer operating rules, including the three bubble questions."""
    rules = ["Fix only the issues above, in the order given; Read a file before editing it.",
             "Stay inside the file set above (the issues' files, the registered tests that target them and "
             "the existing paths a fix option names); new files are allowed. For an issue with other parts, "
             "edit only the files of your part plus the set's tests and named paths; another fixer owns the "
             "rest. When a fix needs an edit outside the file set, leave it and bubble the id "
             "`out_of_scope`.",
             "Run the listed test commands for every edited file before recording. When a test goes red "
             "because of an edit and cannot be fixed inside the file set, undo that edit and bubble the id "
             "`fixer_failed`, naming the test in the reason. Never run a test marked deferred: it is too "
             "slow for a fix wave, and closeout lists it for one run after the waves.",
             "Bubble an issue only when one of these answers yes; otherwise pick the safest option and "
             "fix it:",
             "No git writes (no add, commit, stash, checkout, reset, restore).",
             "Record each id with your part's files plus any new file you created and any test or named "
             "path of the set you edited for it (the `Your part` line names the part); an issue is resolved "
             "once every part's fixer has recorded it.",
             "Record once with the heredoc below; reply with the block it prints, verbatim, and nothing "
             "else.",
             "A file of your split part that the fix cites but needs no edit goes in an entry's `no_change` "
             "list, with the reason in `what`; list edited files under `files` only.",
             "When the fix is already present (an earlier wave or the developer made it), edit nothing: "
             "list the issue's own files (primary or also) in your part or file set that hold it under "
             "`no_change`, limited to your part's files for a split issue, and write `already present` and "
             "where in `what`; closeout resolves it once one of those files changed since the build (a split "
             "issue still needs every part covered), unless another issue's accepted entry edited that file."]
    questions = [f"  {n}. {q}" for n, q in enumerate(BUBBLE_QUESTIONS, start=1)]
    questions.append("  When all three are no, bubble only net-new work beyond Phase 5 scope "
                     "(`needs_follow_up`).")
    return ["## Rules", ""] + [f"- {r}" for r in rules[:4]] + questions + [f"- {r}" for r in rules[4:]]


def fixer_part(fixer: Mapping[str, object], issue: Mapping[str, object]) -> List[str]:
    """Files ``fixer`` owns for ``issue``: its planned part, else the whole file list."""
    parts = fixer.get("parts") or {}
    return list(parts.get(str(issue["id"])) or issue_files(issue))  # type: ignore[union-attr]


def fixer_brief(ctx: BriefContext, fixer: Mapping[str, object], issues: Mapping[str, Mapping[str, object]],
                entries: Sequence[Tuple[str, Tuple[str, ...]]], deferred: Mapping[str, str]) -> str:
    """The full fixer brief for one planned fixer; ``deferred`` maps the tests it must not run to reasons."""
    agent, files = str(fixer["id"]), list(fixer["files"])  # type: ignore[call-overload]
    lines = [f"# Fixer brief: {agent} - PR #{ctx.pr}", ""]
    lines += [f"- {line}" for line in header_lines(agent, "fixer", ctx.run_id, ctx.pr)]
    lines += ["", f"Repo `{ctx.repo}`, branch `{ctx.facts.head}`.", "", "## Issues (fix in this order)", ""]
    for issue_id in fixer["issue_ids"]:  # type: ignore[union-attr]
        issue = issues[str(issue_id)]
        lines += _issue_block(issue, fixer_part(fixer, issue))
    call = (f'record_fixes({ctx.pr}, "{agent}", FIXED, BUBBLED, repo=Path(r"{ctx.repo}"), '
            f'run_id="{ctx.run_id}")')
    fixed = '{"id": "M2", "what": "one line: what changed", "files": ["src/pkg/x.py"]},'
    cited = '{"id": "M2", "what": "cited only: why no edit", "no_change": ["src/pkg/y.py"]},'
    bubbled = '{"id": "I3", "classification": "architectural_ambiguity", "reason": "one line"},'
    lists = (("FIXED", (fixed, cited)), ("BUBBLED", (bubbled,)))
    lines += _tests_block(ctx, files, entries, deferred) + [""] + _fixer_rules()
    lines += ["", "## Record (once)", "", "```bash", record_heredoc(ctx, call, lists), "```"]
    return "\n".join(lines) + "\n"


def wave_context(repo: Path, plan: Mapping[str, object]) -> BriefContext:
    """A brief context rebuilt from ``plan.json`` (facts carry only what fixer briefs read)."""
    meta = plan["meta"]
    facts = PrFacts(int(plan["pr"]), str(meta["pr_title"]), str(meta["branch"]),  # type: ignore[index]
                    str(meta["base_branch"]), str(meta["head_sha"]), str(meta["base_sha"]),  # type: ignore[index]
                    "", (), ())
    return BriefContext(repo.as_posix(), _LIB.as_posix(), int(plan["pr"]),
                        str(plan["run_id"]), facts, bool(plan["tree_at_head"]), {}, ())


def wave_rows(ctx: BriefContext, run: Path, waves: Sequence[Sequence[Mapping[str, object]]]) -> List[str]:
    """Printed rows: a heading per wave, then one dispatch row per fixer."""
    lines: List[str] = []
    for fixers in waves:
        number = str(fixers[0]["id"]).split("_", 1)[0][1:]
        when = "dispatch after the previous wave returns" if lines else "dispatch every row in one message"
        lines.append(f"wave {number}: {when} (subagent_type={FIXER_AGENT})")
        lines += [dispatch_row(FIXER_AGENT, str(f["model"]), str(f["id"]), "fixer", ctx.run_id, ctx.pr,
                               run / "fix_briefs" / f"{f['id']}.md") + "\n" for f in fixers]
    return lines


def _cmd_waves(repo: Path, args: argparse.Namespace) -> int:
    """Run ``waves``: plan fixers, write their briefs, print the dispatch rows and the held ids."""
    run, plan = load_plan(repo, args.pr)
    _, doc = load_review(repo, plan)
    require_phase4(doc)
    checked = None if args.ids else closeout_checked(repo, plan, run)
    issues, held, done = wave_inputs(doc, run, args.ids, checked)
    store_path = run / "waves.json"
    store = _read_json(store_path) if store_path.is_file() else {"waves": []}
    entries, deferred = registry_entries(repo), run_deferrals(repo, run)
    waves = widened_waves(repo, issues, held, done, entries, len(store["waves"]) + 1)  # type: ignore[arg-type]
    store["waves"] = list(store["waves"]) + waves  # type: ignore[call-overload]
    store["deferred"] = deferred
    _write_json(store_path, store)
    ctx, by_id = wave_context(repo, plan), {str(i["id"]): i for i in all_issues(doc)}
    for fixer in (f for wave in waves for f in wave):
        brief = fixer_brief(ctx, fixer, by_id, entries, deferred)
        _write_text(run / "fix_briefs" / f"{fixer['id']}.md", brief)
    count = sum(len(w) for w in waves)
    print(f"waves [done] | {len(waves)} wave(s), {count} fixer(s) | run {plan['run_id']}")
    print("\n".join(wave_rows(ctx, run, waves) or ["nothing to plan"]))
    shown = [h for h in held if h in {str(i["id"]) for i in issues}]
    print(f"held: {', '.join(shown) if shown else 'none'}")
    notice = ceiling_line(repo)
    if notice:
        print(notice)
    print("\n".join(pending_lines(pending_bubbles(doc, run))))
    save_plan(run, plan, "fix")
    return 0


def saved_deferrals(run: Path) -> Dict[str, str]:
    """The deferred tests and reasons earlier ``waves`` runs gave fixers (``waves.json`` ``deferred``);
    empty without one."""
    path = run / "waves.json"
    saved = _read_json(path).get("deferred") if path.is_file() else None
    return {str(k): str(v) for k, v in saved.items()} if isinstance(saved, dict) else {}


def run_deferrals(repo: Path, run: Path) -> Dict[str, str]:
    """``defer_reasons`` now, plus every test an earlier wave of the run deferred (its saved reason wins),
    so a replaced timing report never un-defers a test a fixer was told to skip."""
    return {**defer_reasons(repo), **saved_deferrals(run)}


def widened_waves(repo: Path, issues: Sequence[Dict[str, object]], held: Sequence[str], done: Sequence[str],
                  entries: Sequence[Tuple[str, Tuple[str, ...]]],
                  start: int) -> List[List[Dict[str, object]]]:
    """``plan_waves`` with each fixer's file set widened by the registry tests targeting its files and the
    paths its fix options name that exist in ``repo``."""
    existing = {p for i in issues for p in rmg.fix_paths(i) if (repo / p).is_file()}
    return rmg.plan_waves(issues, held, done, start_wave=start, registry=dict(entries), existing=existing)


def _cmd_bubbles(repo: Path, args: argparse.Namespace) -> int:
    """Run ``bubbles`` (read-only): print the fixer bubbles not yet in the review."""
    run, plan = load_plan(repo, args.pr)
    _, doc = load_review(repo, plan)
    require_phase4(doc)
    print("\n".join(pending_lines(pending_bubbles(doc, run))))
    return 0


def require_phase4(doc: Mapping[str, object], action: str = "planning fixes") -> None:
    """Raise while the review's Phase 4 first run has not succeeded (``pre_fix_time`` still pending);
    ``action`` names the refused step in the problem line."""
    log = doc.get("verification_log") or {}
    if log.get("pre_fix_time") == rmg.PENDING:  # type: ignore[union-attr]
        raise CaptureError([f"Phase 4 first run has not succeeded (pre_fix_time pending); settle it and "
                            f"rerun build --replace before {action}"])


# --- closeout -----------------------------------------------------------------------------------------------


def changed_paths(repo: Path, base: str) -> Tuple[Set[str], Set[str]]:
    """(changed, created) since ``base``: tracked diffs to the working tree plus untracked files; a rename
    reads as the old path changed and the new path created."""
    def listed(*argv: str) -> Set[str]:
        return {p for p in git_out(repo, *argv).split("\0") if p}

    untracked = listed("ls-files", "--others", "--exclude-standard", "-z")
    changed = listed("diff", "--no-renames", "--name-only", "-z", base) | untracked
    return changed, listed("diff", "--no-renames", "--name-only", "--diff-filter=A", "-z", base) | untracked


def parse_closed(values: Sequence[str], flag: str = "--closed", label: str = "rationale") -> Dict[str, str]:
    """``ID=<label>`` pairs given to ``flag``; a malformed value raises."""
    out: Dict[str, str] = {}
    for value in values:
        issue_id, sep, text = value.partition("=")
        if not sep or not issue_id.strip() or not text.strip():
            raise CaptureError([f"{flag} {value!r} must be ID={label}"])
        out[issue_id.strip()] = text.strip()
    return out


def planned_fixers(run: Path) -> List[Dict[str, object]]:
    """Every fixer record of every wave in the run's ``waves.json``; empty without one."""
    path = run / "waves.json"
    waves = _read_json(path).get("waves", []) if path.is_file() else []
    return [f for wave in waves for f in wave]  # type: ignore[union-attr]


def fixer_files(run: Path) -> Dict[str, List[str]]:
    """Planned file set per fixer id across every wave of the run."""
    return {str(f["id"]): list(f["files"]) for f in planned_fixers(run)}  # type: ignore[call-overload]


def _parts_of(fixer: Mapping[str, object]) -> Dict[str, List[str]]:
    """A fixer's planned parts; a fixer planned without parts owns its whole file set for each issue id."""
    parts = fixer.get("parts")
    if parts is None:
        files = list(fixer["files"])  # type: ignore[call-overload]
        return {str(i): list(files) for i in fixer["issue_ids"]}  # type: ignore[union-attr]
    return {str(i): list(files) for i, files in parts.items()}  # type: ignore[union-attr]


def fixer_parts(run: Path) -> Dict[str, Dict[str, List[str]]]:
    """Planned parts (issue id -> owned files) per fixer id across every wave of the run."""
    return {str(f["id"]): _parts_of(f) for f in planned_fixers(run)}


def _cmd_closeout(repo: Path, args: argparse.Namespace) -> int:
    """Run ``closeout``: resolve validated fixes, close named ids, commit, print the Phase 5 line."""
    run, plan = load_plan(repo, args.pr)
    path, doc = load_review(repo, plan)
    require_phase4(doc, "closing out")
    if not plan.get("build_head"):
        raise CaptureError(["no build_head recorded; run build first"])
    head = git_out(repo, "rev-parse", "--short", "HEAD").strip()
    paths = changed_paths(repo, str(plan["build_head"]))
    doc, problems = closeout_review(run, paths, head, doc, args)
    try:
        deferred = deferred_lines(repo, run_deferrals(repo, run), set().union(*paths))
        problems += commit_review(repo, path, doc)
    except CaptureError as exc:
        raise CaptureError(exc.problems + problems) from exc
    _write_json(run / CLOSEOUT_MARK, {"head": head, "problems": problems})
    save_plan(run, plan, "fix" if problems or rmg.undispositioned_ids(doc) else "done")
    hints = rmg.resolvable_hints(doc, problems, paths[0])
    print("\n".join([phase5_line(doc, problems), *hints, *deferred]))
    if problems:
        raise CaptureError(problems)
    return 0


def closeout_review(run: Path, paths: Tuple[Set[str], Set[str]], head: str, doc: Mapping[str, object],
                    args: argparse.Namespace) -> Tuple[Dict[str, object], List[str]]:
    """``apply_closeout`` over the run's fixer reports and the ``--closed`` / ``--deferred`` /
    ``--resolved`` flags, against ``paths`` (``changed_paths`` since ``build_head``), plus
    ``unrecorded_problems``."""
    changed, created = paths
    deferred = parse_closed(args.deferred, "--deferred", "decision; tracker")
    resolved = parse_closed(args.resolved, "--resolved", "what")
    fixes = rm.load_fix_reports(run / "fixes")
    out, problems = rmg.apply_closeout(doc, fixes, fixer_files(run), changed, created, head,
                                       date.today().isoformat(), parse_closed(args.closed),
                                       parts=fixer_parts(run), deferred=deferred, resolved=resolved)
    return out, problems + unrecorded_problems(planned_fixers(run), fixes, out)


def unrecorded_problems(fixers: Sequence[Mapping[str, object]], fixes: Sequence[rm.FixReport],
                        doc: Mapping[str, object]) -> List[str]:
    """One problem per planned fixer without a fix report, and per id a reporting fixer was assigned but
    never recorded (no fixed entry, no bubble); only ids still undispositioned in ``doc`` count, so a fixer
    whose ids a later wave, ``--closed`` or ``bubble`` settled raises nothing. A per-id problem leads with
    the id (``resolvable_hints`` reads it there); the no-report problem covers several ids, leads with the
    fixer id and gets no ``hint:`` line, since re-dispatching the row is its route."""
    open_ids = set(rmg.undispositioned_ids(doc))
    reported = {r.fixer for r in fixes}
    recorded = {e.id for r in fixes for e in (*r.fixed, *r.bubbled)}
    problems: List[str] = []
    for fixer in fixers:
        ids = [i for i in _parts_of(fixer) if i in open_ids]
        if ids and str(fixer["id"]) not in reported:
            problems.append(f"{fixer['id']}: no fix report; re-dispatch its row")
        elif ids:
            problems += [f"{i}: planned for {fixer['id']} but not recorded; rerun waves"
                         for i in ids if i not in recorded]
    return problems


def deferred_lines(repo: Path, reasons: Mapping[str, str], paths: Iterable[str]) -> List[str]:
    """The deferred registry tests (``reasons``: test file to reason) that ``paths`` (every path changed
    since ``build_head``: commits, working tree, untracked) reach, each with its reason, and one command
    running them all; empty when none is reached."""
    entries = registry_entries(repo)
    tests = sorted({t for p in paths for t in tests_for(p, entries) if t in reasons})
    if not tests:
        return []
    lines = [f"deferred tests: {len(tests)} file(s) the changes since build_head reach; "
             "run them before commit:"]
    lines += [f"  - {t} ({reasons[t]})" for t in tests]
    return lines + [f"  {pytest_command(repo.as_posix(), tests)}"]


def phase5_line(doc: Mapping[str, object], problems: Sequence[str]) -> str:
    """The canonical Phase 5 done line, or a blocked line when closeout left problems."""
    if problems:
        return (f"Phase 5 [blocked] | {len(problems)} problems | verdict: {doc['verdict']} | "
                f"next: settle problems, rerun closeout")
    return f"Phase 5 [done] | {len(closed_ids(doc))} issues resolved | verdict: {doc['verdict']} | next: stop"


# --- block --------------------------------------------------------------------------------------------------


def _cmd_block(repo: Path, args: argparse.Namespace) -> int:
    """Run ``block``: reprint a recorded reviewer or fixer block."""
    run = rm.run_dir(args.pr, repo)
    review, fixes = run / "findings" / f"{args.agent}.json", run / "fixes" / f"{args.agent}.json"
    if review.is_file():
        print(rm.reviewer_block(rm.load_report(review), _rel(repo, review)))
    elif fixes.is_file():
        report = rm.FixReport.model_validate_json(fixes.read_text(encoding="utf-8"))
        print(rm.fixer_block(report, _rel(repo, fixes)))
    else:
        raise CaptureError([f"no report recorded for {args.agent} in {_rel(repo, run)}"])
    return 0


# --- config -------------------------------------------------------------------------------------------------


def config_data() -> Dict[str, object]:
    """The activated harness configuration as JSON-ready data (paths become strings)."""
    return json.loads(json.dumps(asdict(active()), default=str))


def config_value(data: Mapping[str, object], key: str) -> str:
    """Dotted ``key`` of ``data`` as one line: empty for null, a string as-is, anything else as JSON."""
    value: object = data
    for part in key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise CaptureError([f"config: unknown key {key!r}"])
        value = value[part]
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value)


def _cmd_config(repo: Path, args: argparse.Namespace) -> int:
    """Run ``config``: print the merged configuration as JSON, or one line per ``--get`` key.

    A query that prints ``exclusions`` seeds the default exclusions file first, so the printed path exists.
    """
    if not args.get or "exclusions" in args.get:
        ensure_default_exclusions(active())
    data = config_data()
    lines = [config_value(data, key) for key in args.get]
    print("\n".join(lines) if args.get else json.dumps(data, indent=1))
    return 0


# --- cli ----------------------------------------------------------------------------------------------------


def _pr(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the required ``--pr`` option."""
    parser.add_argument("--pr", type=int, required=True, help="PR number.")
    return parser


def _op(kind: str) -> Callable[[str], Tuple[str, str]]:
    """Argument type tagging an amend operation with its kind, so order is kept across flags."""
    return lambda value: (kind, value)


def _add_review_commands(sub: argparse._SubParsersAction) -> None:
    """Add the Phase 1-3 subcommands: capture, block, merge, amend, build."""
    cap = _pr(sub.add_parser("capture", help="Phase 1 checks, slot plan, briefs and dispatch rows."))
    cap.add_argument("--no-fetch", action="store_true", help="Skip fetching the base side and pull/N/head.")
    cap.add_argument("--allow-closed", action="store_true", help="Replay a closed or merged PR.")
    cap.add_argument("--roast", choices=("yes", "no", "roll"), default="roll", help="Roast slot (roll).")
    _pr(sub.add_parser("block", help="Reprint an agent's block.")).add_argument("--agent", required=True)
    merge = _pr(sub.add_parser("merge", help="Merge reports into draft.json."))
    merge.add_argument("--force", action="store_true", help="Replace a draft that carries amend operations.")
    amend = _pr(sub.add_parser("amend", help="Regrade or merge draft issues."))
    amend.add_argument("--regrade", dest="ops", action="append", type=_op("regrade"), help="ID=severity.")
    amend.add_argument("--merge", dest="ops", action="append", type=_op("merge"), help="KEEP+DROP[+DROP].")
    build = _pr(sub.add_parser("build", help="Write the review JSON."))
    build.add_argument("--replace", action="store_true", help="Overwrite this PR's existing review file.")
    build.add_argument("--waive-head-ancestry", action="store_true",
                       help="Accept a Phase 4 run whose only STOP is a head-ancestry desync (base intact).")
    _add_fold_command(sub)


def _add_fold_command(sub: argparse._SubParsersAction) -> None:
    """Add ``fold``: an outside review recorded as a findings source (appended once the review is built)."""
    fold = _pr(sub.add_parser("fold", help="Fold an outside review into the run (before or after build)."))
    fold.add_argument("--source", required=True, help="snake_case source id (names findings/<id>.json).")
    fold.add_argument("--kind", required=True, choices=FOLD_KINDS, help="Where the review came from.")
    given = fold.add_mutually_exclusive_group(required=True)
    given.add_argument("--from-gh-review", metavar="URL",
                       help="A GitHub PR review URL (#pullrequestreview-N).")
    given.add_argument("--findings", metavar="FILE", help="JSON findings list or object; - reads stdin.")
    fold.add_argument("--severity", choices=[s.value for s in rm.Severity], default="minor",
                      help="Severity of each GitHub comment, or of a --findings entry without one (minor); "
                           "final after build, where amend does not run.")


def _add_fix_commands(sub: argparse._SubParsersAction) -> None:
    """Add the Phase 5 subcommands: bubble, waves, closeout."""
    bubble = _pr(sub.add_parser("bubble", help="Bubble one issue."))
    bubble.add_argument("id", help="Issue id (C1, I3, M2).")
    bubble.add_argument("--classification", required=True, choices=[c.value for c in rm.BubbleClass])
    bubble.add_argument("--reason", required=True, help="One line, at most 200 characters.")
    waves = _pr(sub.add_parser("waves", help="Plan fix waves."))
    waves.add_argument("--ids", help="Plan exactly these ids (I3,M2).")
    _pr(sub.add_parser("bubbles", help="Print fixer bubbles not yet in the review (read-only)."))
    close = _pr(sub.add_parser("closeout", help="Apply fixer reports and close Phase 5."))
    close.add_argument("--closed", action="append", default=[], help="ID=rationale (repeatable).")
    close.add_argument("--deferred", action="append", default=[],
                       help="ID=decision; tracker: a developer-confirmed defer (repeatable).")
    close.add_argument("--resolved", action="append", default=[],
                       help="ID=what: a fix in the tree no accepted fixer entry records (developer-directed "
                            "work or a rejected fixer edit) (repeatable).")


class _Parser(argparse.ArgumentParser):
    """Argument parser whose errors raise ``CaptureError`` (exit 1, ``problem:`` lines) instead of exit 2.

    Subparsers inherit the class, so a subcommand's argument error reports the same way.
    """

    def error(self, message: str) -> NoReturn:  # type: ignore[override]
        """Raise the argument error as a ``CaptureError`` naming the parser and the fix."""
        raise CaptureError([f"{self.prog}: {message} (malformed command: correct the arguments and rerun)"])


def _parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = _Parser(prog="pr_review.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path,
                        help="Project root (default: the git top level of the working directory).")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_review_commands(sub)
    _add_fix_commands(sub)
    conf = sub.add_parser("config", help="Print the project's merged harness configuration (JSON).")
    conf.add_argument("--get", action="append", default=[], metavar="KEY",
                      help="Print only this dotted key, one line each (repeatable; null prints empty).")
    return parser


_COMMANDS: Dict[str, Callable[[Path, argparse.Namespace], int]] = {
    "capture": _cmd_capture, "block": _cmd_block, "fold": _cmd_fold, "merge": _cmd_merge, "amend": _cmd_amend,
    "build": _cmd_build, "bubble": _cmd_bubble, "waves": _cmd_waves, "bubbles": _cmd_bubbles,
    "closeout": _cmd_closeout, "config": _cmd_config,
}


def _utf8_streams() -> None:
    """Reconfigure stdout and stderr to UTF-8 where the stream supports it."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def activate_project(repo: Optional[Path]) -> Path:
    """The project root ``repo`` (else the working directory) belongs to, with its config activated; an
    explicit ``repo`` outside any git checkout is its own root."""
    given = Path(repo).resolve() if repo else None
    root = project_root(given)
    if given is not None and not given.is_relative_to(root):
        root = given
    cfg: HarnessConfig = activate(load_config(root))
    return cfg.project_root


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point; return 0 on success, 1 with ``problem:`` lines on any failure (argument errors
    too)."""
    _utf8_streams()
    try:
        args = _parser().parse_args(argv)
        return _COMMANDS[args.command](activate_project(args.repo), args)
    except CaptureError as exc:
        problems = exc.problems
    except (ValueError, FileNotFoundError) as exc:
        problems = [line for line in str(exc).splitlines() if line.strip()]
    sys.stderr.write("\n".join(f"problem: {line}" for line in problems) + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
