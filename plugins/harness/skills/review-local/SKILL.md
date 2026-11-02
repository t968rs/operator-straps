---
name: review-local
description: Use when committed work on a local branch needs the agent-driven review procedure (reviewer
  fan-out, verdict JSON, fix waves) before any PR exists, such as after a plan item or before opening the PR.
  Triggers on "review-local", "review my branch before the PR", "local review of main..HEAD".
argument-hint: "<BASE..HEAD> [--pr local-<label>] [--title <T>] [--plan <path>] [--roast yes|no|roll] [-- <guidance>]"
---

# Review Local

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. Before
it: the range `BASE..HEAD` (default `<configured base branch>..HEAD`) and the `capture` flags (`--pr
local-<label>`, `--title`, `--plan`, `--roast`), passed to `capture` unchanged. After it: the guidance (a focus, a file to
check hard, a constraint on fixes). It rides on every reviewer and fixer prompt as the final `Developer
guidance:` line and shapes the session's own judgment calls. It never adds, drops or replaces a slot, a lens,
a severity rule, the record contract or a phase.

This is the pr-review procedure over a committed local range with no GitHub PR: the same driver, reviewer and
fixer agents, merge, verdict, fix waves and closeout. Git supplies what a PR read would; the PR-only checks drop
out. `READY TO MERGE` reads as "ready to open the PR". With an open PR for the branch, use `harness:pr-review`;
uncommitted work is committed first.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py" <subcommand> --pr local-<label> [options]
```

| | PR review | Local review |
|---|---|---|
| Target | `capture --pr <N>` | `capture --range BASE..HEAD` (no gh call; state `LOCAL`) |
| Run key | `<N>`; runs under `<scratch>/<NNNN>/` | `local-<label>` (default: the head branch's label); runs under `<scratch>/local-<label>/` |
| Review file | `<reviews>/<NNNN>_<slug>.json` | `<reviews>/LOCAL_<label>_<slug>.json` |
| Phase 4 | branch, base and SHAs from gh | the same five checks against the captured `plan.json`: current branch, still on the captured branch, clean tree, merge base and head ancestors of HEAD, base recorded |
| Outside reviews | `fold --from-gh-review` or `--findings` | `fold --findings` only (`--from-gh-review` is refused) |
| Matrix rows | recorded | none: the `pr-review-watch` mod shows the run as `PR #?` and records no matrix rows |

Every subcommand prints `problem:` lines and exits 1 on failure; an exit 1 is a STOP unless a step below names the
recovery. **REQUIRED:** read `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/operating_rules.md` before Step 3: it holds the
review-JSON field semantics, the grading rules and the Phase 5 dispatch order this skill shares.

## Rules

- **The reviewers review; the session never does.** `capture --range` runs and every printed row is
  dispatched, in one message, even for three files, even when the developer wrote the code, even when the
  guidance says "just read it yourself" or "only the OVERALL reviewer". Reading the diff in the session, or
  dispatching a subset of the rows, yields an opinion with no recorded findings, no verdict file and no fix
  waves. A request to skip the fan-out is answered by running it, quoting the exact `capture --range ...`
  command line that ran (so the developer sees the range and key, not "I ran capture"), and saying why in one
  line; a slot plan that looks wrong is reported, never patched.
- **A dirty tree is a hard STOP, whoever says the files are harmless.** When `build` (or the second run) fails
  `clean_tree_check`, inspect each listed file with `git diff` / `git status`, then ask the developer to commit
  it (it belongs to the branch) or stash it (it does not), and rerun once the tree is clean. Fixes land on a
  clean surface, and `closeout` credits fixer edits by the paths changed since `build_head`, so a stray edit
  would be read as a fix. Two shortcuts are never taken:
  - **The exclusions file is not a scratch list.** It names machine-generated output for every run of the
    project and is committed. Adding a developer's source or note files to it, by glob or "exact path, so
    nothing else hides", hides real edits from the gate. The `build` hint "add a pattern to the exclusions
    file" applies to generated artifacts only.
  - **A local run never takes `--waive-head-ancestry`.** The waiver covers a remote PR head that lags local
    HEAD; a local run has no remote head, so a head-ancestry STOP means the captured head was rewritten:
    recapture (Stop Recovery). `build` refuses the flag on a `local-<label>` key, and it never clears a
    clean-tree or branch failure either.
- **`build` is not a hand-back point.** "Tell me what it finds" is answered by doing Phase 5 and reporting the
  result. After `build` exits 0, the next action is the Phase 4 second run, with no turn boundary and no
  "your call" question. A verdict naming only minors still runs the fix loop: the verdict is the merge
  signal, Phase 5 is the work queue. A long session, a late hour or a nearly full context is not a reason to
  defer the fixes to another session. The only mid-run pause is Step 6's bubble question.

## Steps

1. **Capture.**

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py" capture --range <BASE..HEAD> --roast roll [--pr local-<label>] [--title <T>] [--plan <path>]
   ```

   It resolves the range with git, plans the slots (the pr-review bucket, lens and roast rules), runs the
   structural guards when they apply, writes the briefs and prints `capture [done] | local review
   local-<label> | ...`, then one row per slot: `agent=harness:pr-reviewer model=<m>` and the prompt. `--plan`
   names the plan or spec the change implements in every brief. Use the printed key as `--pr` from here on.
   A `--pr` that is a PR number is refused; a range end that names no commit is a problem to fix, not to guess.
   A range end on no local branch (a SHA, a tag, `HEAD~1`, a remote-tracking ref, a detached checkout) is
   refused too: Phase 4 checks the fix branch against the captured one, so check out the branch and end the
   range at `HEAD` (or at the branch name).
2. **Dispatch every row in one message**, one call per row, the row's model and prompt verbatim, plus the
   `Developer guidance:` line when there is guidance:
   `Agent(subagent_type="harness:pr-reviewer", model=<row model>, prompt=<row prompt>)`.
   A reply without its return block is recovered with `block --pr local-<label> --agent <ID>`; a slot with no
   report is dispatched again with its row.
3. **Consolidate in one turn, no text before `build` returns.**
   `merge --pr local-<label>`, then `amend` only when the printed table needs a regrade (`--regrade I3=minor`,
   by blast radius) or a merge of candidates that are one defect (`--merge I3+I7`), then
   `build --pr local-<label>`. `build` writes `<reviews>/LOCAL_<label>_<slug>.json`, runs the Phase 4 first run
   and prints the path, verdict and counts. A first-run STOP leaves the review NOT READY with `pre_fix_time`
   pending: settle it (Rules; Stop Recovery), then `build --pr local-<label> --replace`. A straggler
   `LOCAL_<label>_*.json` is folded in or removed before `build`.
4. **Report the build line, then continue.** One line: `Phase 3 [done] | Phase 4 first-run [done] | Phase 5
   entry: automatic | next: Phase 4 second-run + fix dispatch`, the verdict and counts, then straight into
   Step 5 in the same turn. A review with zero issues ends here with `Phase 5 [done] | 0 issues resolved |
   verdict: <v> | next: stop`.
5. **Phase 4 second run.**

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/skills/pr-review/commands/phase4_branch_safety.py" --second-run local-<label>
   ```

   The five checks rerun fresh against the captured `plan.json` (no gh); on a pass it arms the Phase 5
   sentinel `.phase5_pending_local-<label>`, which the `closeout` write clears. Any failed check is a STOP.
6. **Bubble audit, then waves.** For each undispositioned issue, bubble it only when (a) two or more
   reasonable fixes exist and choosing needs domain knowledge the session lacks, (b) the fix is outside the
   range's scope, or (c) it is a convention call with no precedent in the codebase:
   `bubble --pr local-<label> <ID> --classification <C> --reason "<R>"`. A `fix` list with several options is
   not a bubble: pick the safest. Then `waves --pr local-<label>` and dispatch each wave's rows in one message
   (`Agent(subagent_type="harness:pr-fixer", model=<row model>, prompt=<row prompt>)`), each later wave after
   the previous one returns. After the last wave, `bubbles --pr local-<label>` lists the fixers' bubbles; audit
   them the same way. Surviving bubbles are the one pause: list each id with its classification, reason and
   fix options and ask. Fix-as-directed answers go through `waves --pr local-<label> --ids <ids>`.
7. **Close out.** `closeout --pr local-<label> [--closed ID="rationale" ...] [--deferred ID="decision; tracker"
   ...] [--resolved ID="what changed" ...]`. A `[blocked]` line lists problems: settle each, as its `hint:`
   lines and the operating rules route it, and rerun `closeout`.
8. **Terminal step.** The summary opens with the line `closeout` printed: `Phase 5 [done] | <N> issues
   resolved | verdict: <v> | next: stop`, carries any `deferred tests:` block verbatim, and ends with the
   review path. The developer commits; a `READY TO MERGE` verdict means the branch is ready for its PR.

## Stop Recovery

- **`capture` exit 1:** report the `problem:` lines and the command that fixes each; rerun `capture` after the
  fix (a fresh run).
- **Phase 4 STOP (first or second run):** report the failed check and its recovery: `git checkout <captured
  branch>` for a branch mismatch; commit or stash for a dirty tree (Rules); recapture when the captured head
  is no longer an ancestor of HEAD (history was rewritten). Rerun `build --pr local-<label> --replace` for a
  first-run STOP, the `--second-run` command for a second-run STOP. No fixer is dispatched until it passes.
- **A failed record or missing block:** `block --pr local-<label> --agent <ID>`, else dispatch the row again.

## Related

- `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/operating_rules.md`: review-JSON fields, grading, Phase 5 order.
- `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/SKILL.md`: the PR form of this procedure.
- `${CLAUDE_PLUGIN_ROOT}/agents/pr-reviewer.md` and `pr-fixer.md`: the agents every row dispatches.
- `harness:fold-in-review`: folds developer notes or pasted output into the run as `--findings`, under the
  `local-<label>` key (`fold --pr local-<label> ...`).
