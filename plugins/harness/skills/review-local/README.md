# review-local

Review committed work on a local branch before any PR exists. The skill runs the `pr-review` procedure
(reviewer agents, one verdict JSON, branch checks, fix waves, closeout) over a `BASE..HEAD` commit range, and
reads git where `pr-review` reads GitHub. `SKILL.md` is the procedure the agent follows; this file explains a run
from the developer's side.

## When to use it

| Situation | Use |
|---|---|
| Committed work on a branch with no PR yet: after a plan item, or before opening the PR | `review-local` |
| The branch already has an open PR | `pr-review` |
| Work not yet committed | commit it first: the review reads commits, and the branch checks need a clean tree |

The run is the same as a PR review, with the PR-only parts left out: no `gh` call, no remote head, no GitHub
review to fold, no matrix rows. `READY TO MERGE` in a local review reads "ready to open the PR".

## Arguments

```text
/harness:review-local
/harness:review-local main..HEAD --roast yes
/harness:review-local main..HEAD -a
/harness:review-local main..HEAD --pr local-retry-fix -- look hard at the retry limit
```

| Argument | Effect |
|---|---|
| `BASE..HEAD` | The range to review; default `<configured base branch>..HEAD`. The range must end on a local branch (`HEAD` on a branch, or the branch name): a SHA, a tag, `HEAD~1`, a remote-tracking ref or a detached checkout is refused, since the branch checks compare the fix branch with the captured one |
| `--pr local-<label>` | The run key; default: the head branch's label. A PR number is refused |
| `--title <T>` | The review title; default: the head branch name |
| `--plan <path>` | Names the plan or spec the change implements, in every reviewer brief |
| `--roast yes\|no\|roll` | The roast reviewer slot: forced on, off, or a 50/50 roll (the default) |
| `-a` / `--adversarial` | Adds the refuters described below. A plain on/off flag, never rolled; it needs a session with the Workflow tool |
| `-- <guidance>` | Free text after a standalone `--`: a focus, a file to check hard, a constraint on fixes. It rides on every reviewer, refuter and fixer prompt and steers the session's own calls; it never adds or drops a slot, a lens or a phase |

## What it writes, and where

Every location is a key of the project's `.claude/harness.json`; nothing is written under the plugin.

| Output | Where |
|---|---|
| The run: `plan.json`, briefs, diffs, findings, refutations (`-a`), the draft | `<artifacts.scratch>/local-<label>/<run id>/`; the `current` file names the active run, and a new capture starts a new run |
| The review | `<artifacts.reviews>/LOCAL_<label>_<slug>.json`, validated against `PR_REVIEW.schema.json` like a PR review |
| The Phase 5 sentinel | `<state_dir>/pr-review/.phase5_pending_local-<label>` under the main checkout, while fixes are pending; `closeout` clears it |
| Matrix rows | none: the `agent-watcher` mod shows the run as `local review local-<label>` |

The scratch and review folders are machine-generated output, exempt from the clean-tree check through the
project's `exclusions` file. The fixers edit the working tree; nothing is committed. The developer commits.

## The phases

```
1 Capture        git reads the range; slots, briefs, structural guards
2 Reviewers      one agent per slot, all at once          (-a: one Workflow call)
3 Consolidate    merge, regrades, build + branch checks    -> LOCAL_<label>_<slug>.json
4 Branch checks  second run, arms the sentinel
5 Fixes          bubble audit, fix waves, closeout         -> Phase 5 [done] line
```

| Phase | What happens | What the developer sees |
|---|---|---|
| 1 Capture | Git resolves the range; the slots follow the `pr-review` bucket, lens and roast rules; the structural guards run when they apply; the briefs are written | `capture [done] \| local review local-<label> \| run ... \| slots: ...` |
| 2 Reviewers | One reviewer agent per slot, all dispatched at once, each recording its findings through a typed API. Reviewers run in their own agents; the session only dispatches and consolidates | Nothing until they return |
| 3 Consolidate | `merge`, regrades by blast radius when needed, `build`, which writes the review and runs the first branch-check run | `Phase 3 [done] \| Phase 4 first-run [done] \| ...`, the verdict and counts, then straight on |
| 4 Branch checks | Five checks against the captured `plan.json`: the current branch, still the captured branch, a clean tree, the merge base and head as ancestors of `HEAD`, the base recorded. The second run arms the sentinel | A STOP only when a check fails, with its fix: check out the branch, commit or stash, or recapture after a rewrite |
| 5 Fixes | The bubble audit, fix waves of `harness:pr-fixer` agents on disjoint files, then `closeout` | The one pause: bubbled issues waiting for a decision. Then `Phase 5 [done] \| <N> issues resolved \| verdict: <v> \| next: stop`, any `deferred tests:` block and the review path |

There is no pause between `build` and the fixes: a verdict naming only minor issues still runs the fix loop,
since the verdict is the merge signal and Phase 5 is the work queue. A dirty tree stops Phase 4; the exclusions
file is never stretched to hide a real edit, and a local run never waives head ancestry. A review with no
issues left to fix ends right after `build`.

Outside feedback (notes, pasted test output, another tool's report) joins the run through
`harness:fold-in-review`, as `--findings` under the `local-<label>` key.

## What `-a` adds

```
Review pipeline:  reviewer slot    -> adv_refute_<slot>
Attack pipeline:  adv_code[_scope] -> adv_refute_adv_code[_scope]      (both run side by side)
```

- **Code refuters** attack the code: one pooled `adv_code` below 20 reviewable files, else one
  `adv_code_runtime`, `adv_code_tests` or `adv_code_plans` per non-empty scope. The scope is the runtime and
  tests paths plus the unfrozen plan paths under `artifacts.plans`:
  - A plan (`<stem>_ActionPlan.json`, its `<stem>_PIP.*` and its `NNNN/` folder) counts frozen when its
    freeze ledger state is frozen, locked or armed, or a plan without a ledger carries the legacy `frozen`
    stamp.
  - `strap/<name>/**` counts frozen when that skill's spec is frozen or locked.
  - The ledger folder `freezes/` and strap fixtures (`strap/*/fixtures/`) are never in scope.
  - Anything else under the plans folder, and any plan whose state cannot be read (a `note:` says why),
    counts unfrozen. With the tree off the range head no state is read: every other plan path counts
    unfrozen, with one `note:`.

  A finding needs a concrete attack: the failing input, the broken call path or the test that would fail.
  The attack text lands in the issue summary as `Attack: <text>`.
- **Findings refuters**, one per reviewer slot and per code refuter (`adv_refute_<slot>`), open every
  `path:line` a finding cites and record it `refuted`, with the line opened and what it showed, or `upheld`.
  Doubt upholds.
- **One Workflow call** replaces the reviewer dispatch. The plugin's `workflows/adversarial-review.js` runs each
  slot and then its findings refuter. Capture copies it into the run directory and passes that copy as `scriptPath`, since the Workflow tool reads a script only from the working directory or an added directory. Every refuter is the `harness:adversarial-reviewer` agent on `opus`. A run
  dispatches `2(R + C)` agents for `R` reviewer slots and `C` code refuters, at most `26 + 2N` with `N`
  triggered project lenses. When the workflow drops an agent, the session dispatches that entry again on its
  own, reviewer first and then its refuter.
- **`REFUTED` issues.** An issue whose every finding was refuted closes as `REFUTED` at `build`, with the
  refuter's evidence, and gets no fixer. The `merge` table shows a `refuted` / `upheld` column, `build` prints a
  `refuted: <id> (<evidence first line>)` line per id, and the verdict and the done line count refuted ids apart:
  `READY TO MERGE - 1 of 2 findings resolved, 0 bubbled, 1 refuted`. Folded findings are never refuted.
- **Overrules** are the developer's call, made any time after `build` once the first branch-check run has
  passed, on any review, with or without `-a`. The session runs them on request:

  | Command | Effect |
  |---|---|
  | `refute --pr local-<label> <ID> --evidence "<text>"` | Closes an open issue as `REFUTED`; it gets no fixer |
  | `unrefute --pr local-<label> <ID> --fix [--reason R]` | Reopens a refuted issue (`NOT_RESOLVED`); the next fix wave plans it |
  | `unrefute --pr local-<label> <ID> --bubble --classification C --reason R` | Reopens it as a bubble for a decision (`BUBBLED`) |

  The Phase 5 pause, or the closing summary when nothing paused, lists the refuted ids with their evidence,
  so the candidates for an overrule are in view. The review's `verification_log.dispatch_time.adversarial_check`
  keeps the build-time counts and tracks the overrules in `refuted_ids` and `unrefuted_ids`.

## Related

- `SKILL.md`: the procedure.
- `../pr-review/SKILL.md` and `../pr-review/operating_rules.md`: the PR form of the procedure, the review-JSON
  fields, the grading rules and the Phase 5 order this skill shares.
- `../fold-in-review/SKILL.md`: folding outside feedback into a run.
- `../../agents/adversarial-reviewer.md`: the refuter agent of an `-a` run.
