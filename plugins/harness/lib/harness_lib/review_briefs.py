"""pr-review reviewer brief composition, and the brief helpers the fixer briefs share.

A reviewer brief is five sections built from a ``BriefContext`` (run-wide values) and one planned
``review_plan.Slot``: the header with the slot's role, the scope paths with the read method and diff file, the
lens (scope sentence, catalog templates, triggered skills, default sub-lenses), the rules, and the record
heredocs. What a slot is (bucket, catalog or project lens, OVERALL, roast) is the planner's call, read through
the ``Slot`` predicates; this module only turns it into text. The driver (the plugin's
``scripts/pr_review.py``) writes the briefs and composes the fixer briefs with ``header_lines``,
``record_heredoc``, ``draft_json``, ``target_label``, ``key_literal``, ``hpy_command``, ``TOO_LONG_RULE`` and
``REMOVAL_DEFECTS`` from here.

Under ``--adversarial`` the driver also writes ``code_refuter_brief`` (one per ``adv_code*`` slot: scope,
attack rule, no-repo-writes rule, ``record_attacks_draft`` heredoc) and ``refuter_brief`` (one template per
``adv_refute_<target>`` slot: ``init`` as the first step, refute rule, no-repo-writes rule,
``record_refutations_draft`` heredoc). Every command a refuter brief holds carries absolute paths, since a
workflow agent's Bash has no ``CLAUDE_PLUGIN_ROOT``; each record heredoc embeds ``run_id=``.

Project values come from ``harness_lib.config.active()`` inside the functions: the review directory
(``artifacts.reviews``), the test paths (``tests``) and the domain pointers (``review.domain_pointers``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple

from harness_lib import review_models as rm
from harness_lib import review_plan as rp
from harness_lib.config import active
from harness_lib.pr_summary import PrFacts, PrFile
from harness_lib.project import plugin_root
from harness_lib.review_adversarial import CodeSlot, RefuteSlot
from harness_lib.review_local_models import RunKey, is_local_key

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
REMOVAL_DEFECTS = (
    "broken (wrong behavior or a failing test), unreachable or dead, a duplicate of code that exists "
    "elsewhere, leftover (debug output, commented-out code, a stray temporary file), unsafe, or "
    "contradicting a contract"
)
PROSE_GAP_RULE = (
    "A change the commit messages or the PR description do not mention is a documentation gap, not a defect "
    "in the code: that text is drafted after the code and lags it. Report the gap alone as a `minor` finding "
    "whose fix updates that text. It never grounds an `important` or `critical` grade, and a revert is never "
    "a fix option on that ground. When the code itself is wrong, the finding states that defect; the missing "
    "mention is at most context. A revert or deletion of code the change added is a fix option only when the "
    f"finding names one of these defects in that code: {REMOVAL_DEFECTS}."
)
SEVERITY_RULES = (
    "Severity: `critical` blocks the merge (wrong behavior, data loss, broken contract, a test that cannot "
    "fail); `important` should be fixed before merging; `minor` is polish.",
    "fix_kind: `mechanical` when the fix is an exact edit a small model can apply; `judgment` otherwise.",
    "Each finding names one primary `file` (repo-relative) with `lines` when known (`12`, `12-18,40`), and "
    "`also` for other files it touches. `fix` lists one or more options, any of which resolves it.",
    PROSE_GAP_RULE,
)
TOO_LONG_RULE = ("A Bash error `unexpected EOF while looking for matching` at a line number past the end of "
                 "the command means the command was too long for the shell tool, not misquoted: do not edit "
                 "the quoting or bisect the content. Record through the draft file, or in smaller pieces.")


@dataclass(frozen=True)
class BriefContext:
    """Run-wide values every brief draws on."""

    repo: str
    lib: str
    pr: RunKey
    run_id: str
    facts: PrFacts
    at_head: bool
    catalog: Mapping[str, object]
    skills: Tuple[str, ...]  # triggered ``skills/<name>/`` folders, one per folder
    plan: Optional[str] = None

    def file(self, path: str) -> Optional[PrFile]:
        """The PR file at ``path``, if any."""
        return next((f for f in self.facts.files if f.path == path), None)


# --- shared helpers -----------------------------------------------------------------------------------------


def hpy_command() -> str:
    """The ``sh "<plugin>/scripts/hpy"`` prefix agents run Python through (absolute plugin path)."""
    return f'sh "{(plugin_root() / "scripts" / "hpy").as_posix()}"'


def header_lines(agent: str, role_name: str, run_id: str, pr: RunKey) -> List[str]:
    """The four column-1 run header lines."""
    return [f"AGENT_ID: {agent}", f"AGENT_ROLE: {role_name}", f"RUN_ID: {run_id}", f"PR: {pr}"]


def key_literal(pr: RunKey) -> str:
    """The run key as a Python literal for a brief's record heredoc: ``1234`` or ``"local-x"``."""
    return json.dumps(pr)


def target_label(pr: RunKey) -> str:
    """``PR #<N>``, or ``local review <key>``."""
    return f"local review {pr}" if is_local_key(pr) else f"PR #{pr}"


def catalog_rows(catalog: Mapping[str, object], key: str) -> List[Mapping[str, object]]:
    """The lens catalog's list of row objects under ``key``."""
    return catalog[key]  # type: ignore[return-value]


def record_heredoc(ctx: BriefContext, call: str, lists: Sequence[Tuple[str, Sequence[str]]] = ()) -> str:
    """A ``sh "<plugin>/scripts/hpy" - <<'EOF'`` heredoc runnable from any directory, ending with ``call``."""
    name = call.split("(", 1)[0]
    lines = [f"{hpy_command()} - <<'EOF'", "import sys", "from pathlib import Path",
             f'sys.path.insert(0, r"{ctx.lib}")', f"from harness_lib.review_models import {name}", ""]
    for name, examples in lists:
        lines += [f"{name} = [", *(f"    # {e}" for e in examples), "]"]
    return "\n".join(lines + [call, "EOF"])


ONLY_FILE = "It is the only file this brief lets you write."


def draft_json(ctx: BriefContext, agent: str, lists: Sequence[Tuple[str, Sequence[str]]],
               closing: str = ONLY_FILE) -> List[str]:
    """The Write-the-draft step: the draft's path and a JSON skeleton with one example per list; ``closing``
    ends the instruction (default: the draft is the only file to write)."""
    path = rm.draft_path(ctx.pr, agent, Path(ctx.repo), ctx.run_id).as_posix()
    body = [f'  "{key.lower()}": [\n' + ",\n".join(f"    {e.rstrip(',')}" for e in examples) + "\n  ]"
            for key, examples in lists]
    return [f"Write the report with the Write tool to `{path}`: one JSON object holding these lists and "
            f"nothing else (the examples show each item's shape). {closing}", "", "```json",
            "{\n" + ",\n".join(body) + "\n}", "```"]


# --- reviewer brief -----------------------------------------------------------------------------------------


def role(slot: rp.Slot) -> str:
    """One-line role description of a slot, from its planned kind."""
    if slot.roast:
        return "roast reviewer covering the OVERALL scope"
    if slot.overall_scope:
        return "OVERALL reviewer"
    if slot.bucket is not None:
        return f"`{slot.bucket}` bucket reviewer"
    return f"`{slot.lens}` cross-cutting lens reviewer"


def brief_header(ctx: BriefContext, slot: rp.Slot) -> str:
    """Title, run header values, role and the PR refs."""
    f = ctx.facts
    lines = [f"# Reviewer brief: {slot.id} - {target_label(ctx.pr)}", ""]
    lines += [f"- {line}" for line in header_lines(slot.id, "reviewer", ctx.run_id, ctx.pr)]
    lines += ["", f"Role: {role(slot)}, model `{slot.model}`.",
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
    return paths_section(ctx, slot.paths, diff_path, partial)


def paths_section(ctx: BriefContext, paths: Sequence[str], diff_path: Path, partial: Sequence[str]) -> str:
    """``scope_section`` over ``paths``: shared by reviewer and code-refuter briefs."""
    lines = ["## Scope", "", _read_method(ctx),
             f"Diff: `{diff_path.resolve().as_posix()}` (modified, renamed and deleted paths; new files are "
             f"not in it).", ""]
    lines += [_path_line(ctx, p) for p in paths]
    if partial:
        lines += ["", "Summarized or omitted in the diff; read the full diff with:"]
        lines += [f"- `git -C {ctx.repo} diff {ctx.facts.merge_base} {ctx.facts.head_sha} -- {p}`"
                  for p in partial]
    return "\n".join(lines)


def scope_text(slot: rp.Slot) -> str:
    """The slot's own scope sentence (bucket, OVERALL / roast); empty for cross-cutting lenses."""
    if slot.bucket is not None:
        return BUCKET_SCOPE.format(bucket=slot.bucket)
    return OVERALL_SCOPE if slot.overall_scope else ""


def lens_section(ctx: BriefContext, slot: rp.Slot) -> str:
    """Scope sentence, catalog lens templates, triggered skills and the default sub-lens templates."""
    lenses = catalog_rows(ctx.catalog, "lenses")
    templates = {str(lens["name"]): str(lens["scope_template"]) for lens in lenses}
    sentence = scope_text(slot)
    lines = ["## Lens", ""] + ([sentence, ""] if sentence else [])
    for name in slot.templates:
        lines += [f"### {name}", "", templates.get(name, f"(no catalog template named {name})"), ""]
    if slot.lists_skills and ctx.skills:
        named = ", ".join(f"{rp.skill_name(f)} ({f})" for f in ctx.skills)
        lines += [f"Triggered skills (substitute each name for `<name>`; its folder follows): {named}", ""]
    for sub in rp.sub_lenses_for(slot, ctx.catalog):
        lines += [f"### Default sub-lens: {sub['name']}", "", str(sub["scope_template"]), ""]
    return "\n".join(lines).rstrip()


def ownership_clause() -> str:
    """The reviewer ownership rule naming the project's review directory."""
    reviews = active().artifacts.reviews.rstrip("/")
    return (f"Record findings only through the draft file and `record_draft` (or `record_add`); "
            f"never write under `{reviews}/`; "
            f"reply with the printed block only.")


def tests_in_scope(paths: Sequence[str]) -> bool:
    """True when any path reviews as a test path or is a test file in any bucket (``cicd`` included)."""
    tests = active().tests
    return any(rp.review_bucket(p) is rp.PathBucket.TESTS or tests.is_test_path(p) for p in paths)


def domain_pointers(paths: Sequence[str]) -> List[str]:
    """The configured ``review.domain_pointers`` texts whose prefix starts any of ``paths``."""
    return [d.pointer for d in active().review.domain_pointers if any(p.startswith(d.prefix) for p in paths)]


def rules_section(slot: rp.Slot, plan: Optional[str] = None) -> str:
    """Ownership, severity and finding-shape rules, plus the conditional clauses and the plan pointer."""
    rules = [ownership_clause(), *SEVERITY_RULES]
    rules += [TEST_DESIGN_CLAUSE] if tests_in_scope(slot.paths) else []
    rules += domain_pointers(slot.paths)
    rules += [f"Plan: {plan} (the plan or spec this change implements; check the change against it)"] \
        if plan else []
    rules += [ROAST_VOICE] if slot.roast else []
    return "\n".join(["## Rules", ""] + [f"- {rule}" for rule in rules])


def record_section(ctx: BriefContext, slot: rp.Slot) -> str:
    """The draft file, the ``record_draft`` and ``record_add`` heredocs and the reply rule."""
    tail = f'repo=Path(r"{ctx.repo}"), run_id="{ctx.run_id}")'
    example = ('{"severity": "important", "name": "...", "summary": "...", "fix": ["..."],'
               ' "file": "src/pkg/x.py", "lines": "12-18", "also": [], "fix_kind": "mechanical"},',)
    lists = (("FINDINGS", example), ("STRENGTHS", ('"one line per strength",',)))
    add = f'record_add({key_literal(ctx.pr)}, "{slot.id}", FINDINGS, STRENGTHS, {tail}'
    return "\n".join(["## Record (once, after the analysis)", "", *draft_json(ctx, slot.id, lists), "",
                      "Then run this once from any directory; a rerun replaces the report. An error names "
                      "the failing finding index.", "", "```bash",
                      record_heredoc(ctx, f'record_draft({key_literal(ctx.pr)}, "{slot.id}", {tail}'),
                      "```", "",
                      "To record in pieces instead (no Write, or no draft), run this heredoc with a few "
                      "findings filled into `FINDINGS` and `STRENGTHS` per call (the commented lines show "
                      "each item's shape). Each call appends (an identical item is skipped); `record_draft` "
                      "replaces everything.", "", "```bash", record_heredoc(ctx, add, lists), "```", "",
                      TOO_LONG_RULE, "",
                      "Reply with the block the last record call prints, verbatim, and nothing else."])


def reviewer_brief(ctx: BriefContext, slot: rp.Slot, diff_path: Path, partial: Sequence[str]) -> str:
    """The full reviewer brief for ``slot``."""
    parts = [brief_header(ctx, slot), scope_section(ctx, slot, diff_path, partial), lens_section(ctx, slot),
             rules_section(slot, ctx.plan), record_section(ctx, slot)]
    return "\n\n".join(parts) + "\n"


# --- refuter briefs (--adversarial) -------------------------------------------------------------------------


#: Single-token ``AGENT_ROLE`` values, so agent-watcher's role pattern matches them.
CODE_REFUTER_ROLE = "code_refuter"
REFUTER_ROLE = "refuter"
ATTACK_RULE = (
    "Attack the changed code in scope: find an input that breaks it, a call path that no longer works, or "
    "a test that would fail. Record a finding only with an `attack`: that failing input, broken call path "
    "or failing test, stated so a fixer can reproduce it, any file named as a repo-relative `path:line` "
    "(never with the repository root in front). No attack, no finding: style, naming and prose remarks are "
    "out of scope."
)
REFUTE_RULE = (
    "For each finding `init` printed, open every `path:line` it cites (read method below) and check the "
    "claim against the code. The verdict is `refuted` only when the cited code does not show the claim; its "
    "`evidence` names the repo-relative `path:line` opened (never with the repository root in front) and "
    "what it showed. Otherwise the verdict is `upheld` (evidence optional); a citation that cannot be "
    "opened is `upheld`. Give one entry per printed key, each key exactly once."
)
REFUTER_DRAFT_CLOSING = "Besides it, write only probe files under the run directory (rules below)."


def driver_command(ctx: BriefContext) -> str:
    """The ``pr_review.py`` driver invocation with absolute paths (a workflow agent's Bash has no
    ``CLAUDE_PLUGIN_ROOT``)."""
    script = (plugin_root() / "scripts" / "pr_review.py").as_posix()
    return f'{hpy_command()} "{script}" --repo "{ctx.repo}"'


def _run_folder(ctx: BriefContext) -> Path:
    """The run directory a brief belongs to."""
    return rm.run_dir(ctx.pr, Path(ctx.repo), ctx.run_id)


def no_repo_writes_rule(ctx: BriefContext) -> str:
    """The refuter rule against repository writes, naming the run's probe folder and the pytest probe
    form."""
    probes = (_run_folder(ctx) / "probes").as_posix()
    return (f"No repository writes: create, edit or delete no file in `{ctx.repo}` through Bash or any "
            f"other tool, and run no git write (add, commit, stash, checkout, reset, restore); the draft "
            f"file below and probe files under `{probes}` are the only files to write. A probe (a script or "
            f"a pytest run) runs only under `{probes}`, and a pytest probe passes `-p no:cacheprovider`, so "
            f"the clean-tree check never sees a stray file. A pytest probe runs as "
            f"`{hpy_command()} -m pytest -p no:cacheprovider <paths>`.")


def _refuter_header(ctx: BriefContext, title: str, agent: str, role_name: str, role_line: str) -> str:
    """Title, run header values, role line, the PR refs and the run directory of a refuter brief."""
    f = ctx.facts
    lines = [f"# {title}: {agent} - {target_label(ctx.pr)}", ""]
    lines += [f"- {line}" for line in header_lines(agent, role_name, ctx.run_id, ctx.pr)]
    lines += ["", role_line, f"PR \"{f.pr_title}\" (`{f.head}` -> `{f.base}`); merge base `{f.merge_base}`, "
              f"head `{f.head_sha}`.", f"Run directory: `{_run_folder(ctx).as_posix()}`."]
    return "\n".join(lines)


def _refuter_record(ctx: BriefContext, agent: str, lists: Sequence[Tuple[str, Sequence[str]]],
                    call: str) -> str:
    """The draft file, the record heredoc running ``call`` and the reply rule."""
    draft = draft_json(ctx, agent, lists, REFUTER_DRAFT_CLOSING)
    return "\n".join(["## Record (once, after the analysis)", "", *draft, "",
                      "Then run this once from any directory; a rerun replaces the report.", "", "```bash",
                      record_heredoc(ctx, call), "```", "", TOO_LONG_RULE, "",
                      "Reply with the block the record call prints, verbatim, and nothing else."])


def code_refuter_brief(ctx: BriefContext, slot: CodeSlot, diff_path: Path, partial: Sequence[str]) -> str:
    """The full code-refuter brief for ``slot`` (an ``adv_code*`` slot)."""
    role_line = (f"Role: code refuter over the runtime, tests and unfrozen plan paths below, "
                 f"model `{slot.model}`.")
    tail = f'repo=Path(r"{ctx.repo}"), run_id="{ctx.run_id}")'
    example = ('{"severity": "important", "name": "...", "summary": "...", "fix": ["..."], '
               '"file": "src/pkg/x.py", "lines": "12-18", "also": [], "fix_kind": "mechanical", '
               '"attack": "the failing input, broken call path or failing test"},',)
    lists = (("FINDINGS", example), ("STRENGTHS", ('"one line per strength",',)))
    call = f'record_attacks_draft({key_literal(ctx.pr)}, "{slot.id}", {tail}'
    rules = [ATTACK_RULE, no_repo_writes_rule(ctx), *SEVERITY_RULES]
    parts = [_refuter_header(ctx, "Code refuter brief", slot.id, CODE_REFUTER_ROLE, role_line),
             paths_section(ctx, slot.paths, diff_path, partial),
             "\n".join(["## Rules", ""] + [f"- {rule}" for rule in rules]),
             _refuter_record(ctx, slot.id, lists, call)]
    return "\n\n".join(parts) + "\n"


def _init_section(ctx: BriefContext, slot: RefuteSlot) -> str:
    """The first step of a findings refuter: ``init``, and what each of its outcomes means."""
    init = f"{driver_command(ctx)} init --pr {ctx.pr} --agent {slot.id} --run-id {ctx.run_id}"
    return "\n".join([
        "## First step: init", "", "Run this once, before anything else:", "", "```bash", init, "```", "",
        f"It prints each finding of `{slot.target}` as `[<key>] <severity> <name> <file>:<lines>` with its "
        "summary (and its attack for a code refuter's finding). `no findings: done` means init recorded the "
        "empty report itself: reply with the block it printed and stop. Exit 1 (the run is no longer "
        f"current, or `{slot.target}` has not recorded) means stop: reply with its `problem:` lines and "
        "record nothing."])


def refuter_brief(ctx: BriefContext, slot: RefuteSlot) -> str:
    """The findings-refuter brief template for ``slot`` (an ``adv_refute_<target>`` slot); ``init`` fills
    in the target's recorded findings when the refuter runs."""
    role_line = (f"Role: findings refuter of slot `{slot.target}`, model `{slot.model}`: check each of its "
                 f"findings against the cited code.")
    tail = f'repo=Path(r"{ctx.repo}"), run_id="{ctx.run_id}")'
    examples = ('{"key": "0123456789ab", "verdict": "refuted", "evidence": "src/pkg/x.py:12 returns the '
                'old value, as the change intends"},', '{"key": "ba9876543210", "verdict": "upheld", '
                '"evidence": ""},')
    call = f'record_refutations_draft({key_literal(ctx.pr)}, "{slot.id}", "{slot.target}", {tail}'
    rules = [REFUTE_RULE, _read_method(ctx), no_repo_writes_rule(ctx)]
    parts = [_refuter_header(ctx, "Findings refuter brief", slot.id, REFUTER_ROLE, role_line),
             _init_section(ctx, slot), "\n".join(["## Rules", ""] + [f"- {rule}" for rule in rules]),
             _refuter_record(ctx, slot.id, (("REFUTATIONS", examples),), call)]
    return "\n\n".join(parts) + "\n"
