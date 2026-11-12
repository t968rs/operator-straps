# pr-review `--adversarial` (`-a`): a code refuter and a findings refuter, run by one workflow

Issue #252 (todo-kex8). Branch `1155-local-review-strapping`, cut from `main` at `c4cda8a` after PR 276
merged. The review-local strap round that follows this work is in Sequencing. A spec review (findings
S1-S31) was resolved before this text was frozen; the "Review resolutions" table at the end maps each finding
to the section that now covers it.

## Intent

Today a pr-review run has no stage that checks its own findings. Reviewers record findings, `merge`
consolidates them unchecked, and the Phase 5 fixers spend effort on any false positives. The roast slot does
not fill that gap, because it is one more reviewer adding findings in another voice.

The developer's FEMA research workflow (`~/.claude/workflows/consolidate-fema-table-entry-points.js:94`)
shows the missing stage. An adversarial agent takes another agent's output and tries to **refute** it: it
opens every cited `path:line`, and it treats a claim as refuted when the citation does not show what the
claim says. The developer wants pr-review to gain that stage, and also an adversarial attack on the PR's
code itself:

- **Findings refuter:** attacks every finding the reviewers (and the code refuter) recorded, before `merge`.
- **Code refuter:** attacks the PR's runtime files, tests and unfrozen plan files, and reports only
  breakage it can show.

`-a` turns both on. The run is driven by a Workflow script shipped in the plugin, so each reviewer slot's
findings go to a refuter as soon as that slot returns, with no wait for the slowest slot.

## Goals

- `capture --adversarial` (short `-a`) on pr-review and review-local. It is a plain on/off flag with no
  `roll`, because an adversarial run costs too much to leave to a coin flip (D3).
- One plugin workflow script, `plugins/harness/workflows/adversarial-review.js`, runs Phase 2 under `-a`:
  the reviewers, the code refuters and the findings refuters as one pipeline (D1).
- A new agent, `harness:adversarial-reviewer`, does both roles. Its brief sets the role.
- A refuted finding **stays** in the review's `issues` and **also** gets a `post_review_resolutions` entry,
  status `REFUTED`, written by `build` (D4). The entry's evidence is the refuter's case.
- `REFUTED` joins `CLOSED_STATUSES`, so a refuted issue needs no fixer and does not block the verdict
  (see "REFUTED as a closed status").
- The developer can overrule at any time after `build`, in either direction, on any review with or without
  `-a` (D5): `refute` adds a `REFUTED` entry, and `unrefute` removes one by appending a non-closing
  `BUBBLED` (route to the bubble workflow) or `NOT_RESOLVED` (route to Phase 5 waves) entry (D12). Both read
  the issue from the built review object.
- An `-a` run records an `adversarial_check` entry in `verification_log.dispatch_time`; a run without `-a`
  records none (D8).
- `review_models.py` names the workflow explicitly: `ADVERSARIAL_WORKFLOW`, `ADVERSARIAL_AGENT`,
  `REFUTER_MODEL`, and the models the refuters record through.
- `review_merge.py` gains `merge_adversarial`, the dedicated entry point for merging adversarial output.

## Non-goals

- **pr-team.** The developer deferred `-a` there (D2). Its orchestrator and fixer agents plan and
  consolidate inside their own runs, so `-a` there means changing those two agents. It goes to a follow-up
  TODO item.
- **No change to a run without `-a`.** Phase 2 keeps its Agent-row dispatch. `plan.json` gains no
  `adversarial` key, the review gains no `adversarial_check` entry, and the slot plan, briefs and merge
  output stay byte-identical. The one difference every new review carries is the schema version string
  (`2.3.0`, from `review_merge.SCHEMA_VERSION`), since the schema gains three statuses and an optional
  entry. The `refute` and `unrefute` commands work on such a review too, but only when the developer asks.
- **No refutation of folded findings** (`fold`): those come from the developer, CI or a human reviewer, and
  already carry the developer's weight. A fold before build under `-a` gets no refuter, and its findings
  count as upheld in `merge_adversarial`.
- **No agent refutation after `build`.** Phase 5 fixers are not refuted, and neither are post-build folds.
  The developer's `refute` and `unrefute` are overrules by hand, not a second refuter pass.
- **No `git show` reader** for plan state at the PR head: when the tree is not at the head, every plan path
  counts as unfrozen (D14).

## Anti-goals

- **A refuter that closes real findings.** A wrong refutation hides a defect, which is worse than a false
  positive costing a fixer some time. So refuted findings stay visible in `issues`, the evidence is
  recorded, the `build` line and the Phase 5 pause list every refuted id with its evidence, the developer
  can overrule at any time after build, in either direction, with `refute` and `unrefute`, and the refuters
  run on `opus` (the model floor).
- **A code refuter that guesses.** Every code-refuter finding names a concrete failing input, a broken call
  path, or a test that would fail, in a required `attack` field. A finding without one is rejected by the
  model at record time (`AttackFinding`), not filtered by prose.
- **Logic in JavaScript.** The workflow is not under pytest, so it stays thin: it orders dispatches and
  passes values through. Briefs, recording, merging, models and validation stay in Python. The JS holds no
  model literal.
- **A silent skip.** `bubble` and `closeout --resolved` on a refuted id refuse with a problem line naming
  `unrefute`; neither drops the id quietly.

## Constraints

- **Workflow opt-in.** The Workflow tool runs only on an explicit opt-in. A skill whose instructions tell
  the session to call Workflow counts, so `-a` in the pr-review or review-local arguments is the opt-in.
- **Missing Workflow tool (D7).** `capture` is a subprocess and cannot see the session's tool list, so the
  check splits in two. Mechanical: `capture -a` refuses before `start_run` (so `current` does not move) when
  `<plugin_root>/workflows/adversarial-review.js` is missing. Judgment: the skill prose before capture says
  that with `-a` and no Workflow tool, the session prints a `problem:` line and does not run capture. It
  never falls back to Agent rows.
- **Workflow scripts have no filesystem access.** Everything the script needs (the rows, the run key, the
  run id, the repo root, the guidance) arrives as `args`. **Every refuter agent starts with `init`**, a
  driver command that prints its brief, the same way bubble-memo investigators start. Reviewers keep their
  `Brief: <path>` rows (`pr_review.py:571-576`, `pr-reviewer.md:9-10`).
- **`agent()` takes `agentType`, `model` and `schema`.** The script dispatches `harness:pr-reviewer` and
  `harness:adversarial-reviewer` by `agentType`, and passes each entry's model from `args`.
- **Concurrency is capped** at about ten live agents per workflow. A large PR's reviewers and refuters
  queue; nothing is dropped. The worst-case count is under "Agent count".
- **Layer 2 pending rule** (`review_merge.py:540-548`, `_pending_problems`; the hook's copy in
  `validate_pr_json_schema.py:213-229`, `_incoherent`): while `pre_fix_time` is pending, the review may hold
  no READY verdict and no resolution. `apply_phase4` fills `pre_fix_time` before `commit_review`
  (`pr_review.py:1289-1319`, `1344-1349`), so the rule fires only after a **Phase 4 first-run failure**.
  For that case the exemption covers resolutions whose status is `REFUTED`, `BUBBLED` or `NOT_RESOLVED`
  only (none of them changes code, and Phase 4 gates code changes). The READY half stays enforced through
  `hold_ready_verdict`. The build order that makes this hold is under "Build".
- **The verdict:** `REFUTED` joins `CLOSED_STATUSES` (`review_merge.py:57`). The consumer trace is under
  "REFUTED as a closed status".
- **Phase 5 detection:** `phase5_state` (`pr_review.py:1192-1203`) ignores a `REFUTED` resolution only
  when its id still carries `refuted` in `draft.json`: a refuter-written entry, which `build --replace`
  regenerates from `draft.json`. So `build --replace` still works after a refuting build; without this, a
  Phase 4 first-run STOP or the head-ancestry waiver would have no recovery. A developer `refute` or
  `unrefute` entry counts as Phase 5 begun, so `--replace` refuses after a developer overrule.
- **Plugins stay generic.** The script names no project path; the refuter scope reads `artifacts.plans`
  from config. `.js` joins the literal ban's `TEXT_SUFFIXES` so the ban scans the script.
- **Tests:** the workflow script gets a contract test; Python logic gets unit tests through `make_project`.
  The file list is under "Tests".

## Assumptions to verify first

The Workflow API facts below are unverified in this repository. The spike `SPK-1` (the plan's first item,
command-only, opus) checks them before any item that depends on them. In a
`claude --plugin-dir plugins/harness` session it runs a throwaway two-agent workflow and records each answer
in `docs/RESEARCH/pr-review/1016_workflow_spike.md`:

1. `scriptPath` accepts a path under the plugin root.
2. A plugin-shipped `workflows/` folder passes `claude plugin validate --strict`.
3. `agentType: 'harness:<name>'` resolves to the plugin agent.
4. An agent dispatched by the workflow can Write its draft file without a permission prompt.
5. `pipeline` behavior when a stage returns null.
6. Whether the Workflow call returns synchronously or asynchronously (a verifier reported an
   `async_launched` return; unverified).
7. Whether agent-watcher hooks fire for Workflow agents (this decides D6).
8. Whether the Workflow output file's `workflowProgress` carries `tokens`, `toolCalls`, `durationMs`,
   `label` and `model` per agent (the shape D6's `result` option reads).

**Phase 3 trigger.** Phase 3 starts when the Workflow call's result arrives: the call's return when it is
synchronous, its completion notification when it returns asynchronously. Nothing else counts as "the last
reviewer returned" under `-a`.

`TASK-5`, `TASK-6` and `TASK-9` depend on `SPK-1`.

## Approaches

| | Approach | Gains | Costs |
|---|---|---|---|
| **A (chosen)** | One workflow, `adversarial-review.js`. Under `-a`, Phase 2 is one Workflow call that pipelines the reviewers, the code refuters and the findings refuters | Each slot's findings are refuted as soon as that slot returns. One opt-in per run. Same shape as the developer's FEMA workflow | Two Phase 2 dispatch paths. JS that pytest does not run |
| B | Two workflows, `code-refute.js` in Phase 2 and `findings-refute.js` after it | Each file is simpler | A wait between them, and two opt-ins. `code-refute.js` only wraps slot rows the Agent dispatch already handles |
| C | No workflow: the code refuter is a capture slot like roast, and a separate subcommand prints the refuter rows after Phase 2 | Fits today's driver and is easiest to test | No pipeline, which is the reason the developer wanted a workflow |

**The developer picked A**, with the script kept thin. The two refuters depend on each other (the code
refuter's findings also go to the findings refuter), so two files would force a wait between them.

## Decisions

D1-D5 and D12 are the developer's answers. D7-D11, D13 and D14 are calls made from the spec review, not
developer answers (D11 follows from the developer's D5). D6 is open.

| ID | Question | Chosen | Source and reason |
|---|---|---|---|
| D1 | Workflow count | one | developer (Approach A) |
| D2 | pr-team | later | developer |
| D3 | Flag or roll | flag | developer; cost |
| D4 | Refuted status | `REFUTED` | developer |
| D5 | Overrule window | **anytime** after build, either direction | developer (supersedes the review's post-build-only fix for S2): a driver pipeline, `refute` (add) and `unrefute` (remove), both reading the issue from the built review object. `amend --unrefute` is dropped; Phase 3 stays atomic |
| D6 | Matrix rows for Workflow agents | **OPEN**: `watcher`, `shape`, `exempt` or `result` | waits on `SPK-1` (whether hooks fire for Workflow agents, and the `workflowProgress` shape); the developer decides |
| D7 | Missing Workflow tool | capture checks the script file | review (S14): capture checks the file before `start_run`; skill prose stops the session when the tool is missing |
| D8 | `adversarial_check` | only under `-a` | review (S11): optional in the schema, written only under `-a` |
| D9 | Attack text | folded into the summary | review (S8): `Attack: <text>` joins the issue summary; no `issue.attack` schema field |
| D10 | Frozen states | `frozen`, `locked`, `armed` | review (S10); plus a legacy in-file `frozen` |
| D11 | TS closed-status mirrors (`agent-watcher/hooks/layers/pr-review/bubbles.ts:59`, `bubble-stamp/hooks/review.ts:40`, `bubble-stamp/hooks/memo.ts:38`) | **add `REFUTED`** | review (S3), following D5: the developer can `refute` a bubbled id, so a bubbled id's latest status can be `REFUTED`, a decision that closes the bubble. The mirrors gain `REFUTED`; agent-watcher and bubble-stamp versions bump; their mirror tests and release rows move with them (`TASK-10`). `BUBBLED` and `NOT_RESOLVED` are non-closing, which the mirrors already treat as open |
| D12 | How an unrefute is recorded | two new non-closing statuses, appended: `BUBBLED` (route to the bubble workflow) and `NOT_RESOLVED` (route to Phase 5 waves) | developer: append-only; the latest-status rule reopens the id. There is no `UNREFUTED` status |
| D13 | Refutation key | content hash of the finding (`finding_key`) plus a digest of the slot report | review (S7) |
| D14 | Plan state when the tree is not at the PR head | every plan path unfrozen, with a `note:` | review (S10): conservative (attacks more), and no `git show` reader |

D6 options, for the developer: `watcher` has agent-watcher record Workflow agents as it records Agent
dispatches (needs the hooks to fire); `shape` records them as rows marked with a workflow dispatch shape;
`exempt` gives Workflow agents no matrix rows and exempts them from done criterion (h); `result` has the
session pass the Workflow completion notification's `<output-file>` to a driver command that writes one
matrix row per `workflowProgress[]` entry (label = slot id; `tokens`, `toolCalls`, `durationMs` and `model`
as observed in a live run), with `dispatch_shape: "workflow"` and no path logged. `SPK-1` confirms the
shape `result` relies on.

## Design

### Scope of the code refuter

The code refuter reviews the reviewable paths in the `runtime` or `tests` bucket (`review_plan.py:61-69`),
plus **unfrozen plan files** (classified below). Registry files that `merge_registry_into_tests` pulls into
the tests bucket (`review_plan.py:200-212`) are in scope, since they sit in that bucket after the merge.

The other buckets are out, each for a stated reason:

- **config / registry and cicd:** covered by the structural guards and by their own reviewer slots.
- **docs and skill prose:** judgment text, with no failing input for a code refuter to show.
- **Unbucketed paths:** reviewed by the OVERALL slot.

A skill-only or docs-only PR therefore gets no code refuter; capture says so, and the findings refuter still
runs over the reviewers' findings.

### Plan-path classification

A plan path is any reviewable path under `artifacts.plans`. The plan-path rule **overrides the bucket**: a
plan path never lands in the runtime or tests code-refuter slots (a `.py` under a plan folder would otherwise
bucket as runtime or tests), so each path lands in at most one `adv_code` slot. The table lives in this spec
and in `review_adversarial`.

| Path under `artifacts.plans` | State read from | Counts frozen when |
|---|---|---|
| `<stem>_ActionPlan.json` | `plan_doc.ledger_state`; ledger None -> legacy `hydrate_frozen` `frozen` field | `frozen`, `locked`, `armed`; legacy: `frozen` set |
| `<stem>_PIP.*` | the plan `<stem>_ActionPlan.json` (full stem match) | as that plan |
| `NNNN/**` | the one plan numbered NNNN | as that plan; zero or several plans with that number -> unfrozen + `note:` |
| `freezes/**` | excluded from scope (write-once ledger data) | n/a |
| `strap/*/fixtures/**` | excluded from scope (test data) | n/a |
| `strap/<name>/**` (other) | `strap_lock.is_locked` or `SkillSpec.frozen` | locked or frozen |
| anything else | unfrozen | never |

- **States:** `armed` means Locked and armed for an unlock, so it is still frozen. `unlocked` counts as
  unfrozen, because an unlock entry means a design change is under way and the plan is editable. `none`
  counts as unfrozen.
- **Legacy plans:** every root plan in this repository predates the freeze ledger (bare `frozen`, no ledger
  entry), so `ledger_state` returns None for them; the legacy `frozen` field then decides (D10).
- **Unreadable state** counts as unfrozen and gets a `note:` line from capture. Attacking it costs a
  refuter's time; skipping it could hide a defect.
- **Tree not at the PR head** (`tree_at_head` false): every plan path counts as unfrozen, with one `note:`
  line (D14).
- `NNNN` sharing is real: `0002` has two plans, which is why siblings map by full stem and `NNNN/` folders
  map only when one plan holds the number.

### Pool or single

The pool-or-single choice follows a rule, so the developer does not decide it on each run. It reuses the
small-PR cut: `SMALL_PR_FILES` (`review_plan.py:35`), applied at `review_plan.py:531-541`. The threshold
counts reviewable files, a stated choice.

| Reviewable files | Code refuter | Findings refuter |
|---|---|---|
| under 20 | one, over the whole scope | one per reviewer slot (the pipeline needs one per slot to avoid a wait) |
| 20 or more | one per non-empty bucket of the scope (runtime, tests, plans) | one per reviewer slot |

The findings refuter is per slot in both rows. A single refuter over every finding would have to wait for
all the slots, and that wait is what the workflow exists to remove. Each code refuter's findings go to one
more findings refuter of their own. There is no findings-per-refuter split cap.

### Agent count

- R reviewer slots: R <= 10 + N (5 bucket slots, 3 lenses, OVERALL, roast; N project lenses).
- C code refuters: C <= 3.
- Total agents: 2(R + C) <= 26 + 2N, at about 10 concurrent.

The formula appears here and in the pr-review SKILL.md `-a` section. A refuter whose target slot recorded
zero findings costs no reasoning: its `init` records an empty `RefutationReport` itself and prints
`no findings: done`.

### Capture

- `capture --adversarial` / `-a` (`pr_review.py:2033-2042`, next to `--roast`).
- **Refusals before `start_run`**, so `current` does not move:
  - `<plugin_root>/workflows/adversarial-review.js` is missing (D7).
  - The governing schema (`project.schema_path`, which prefers a project's pinned copy) has a
    `post_review_resolution.status` enum without `REFUTED`, `BUBBLED` or `NOT_RESOLVED`. The `problem:`
    line names the pinned path. A matching doctor check goes to `deferred_to_future_plans`.
- **Slot plan:** `plan.json["adversarial"] = {"code": [{id, paths, model}], "refute": [{id, target, model}]}`,
  kept separate from `slots` and present only under `-a`. Code-refuter ids are `adv_code` (one pooled
  slot) or `adv_code_<bucket>`; findings-refuter ids are `adv_refute_<target>`, where the target is a
  reviewer slot id or an `adv_code*` id.
- **Reserved prefix:** `review_plan._check_project_lens` rejects a project lens name starting with `adv_` or
  `adv-`, so no lens slot id can collide with a refuter id.
- **Models** come from the Python slot plan: every `adv_*` entry gets `REFUTER_MODEL` (`opus`).
- **Briefs:** capture writes the code-refuter briefs (`review_briefs.py`) and the findings-refuter briefs as
  templates; each findings refuter's `init` fills in its target's recorded findings when it runs.
- **One Workflow row** replaces the Agent rows under `-a`: the plugin script path and the `args` object
  (run key, run id, repo root, `guidance`, and per entry the `agentType`, model and prompt). The session
  passes it to Workflow with `scriptPath` and `args`, unchanged with one exception: `args.guidance`
  (`null` from capture) is the only field the session may set, to the developer's guidance text.
- Capture records `verification_log.dispatch_time.adversarial_check` (fields under "Schema"), only under
  `-a`.

### The workflow (`plugins/harness/workflows/adversarial-review.js`)

```
phase Review:  pipeline(reviewer entries,
                 e -> agent(e.prompt, agentType e.agentType, model e.model),
                 (_, e) -> agent(refuter entry for e: prompt, agentType, model))
phase Attack:  pipeline(code refuter entries,
                 e -> agent(e.prompt, agentType e.agentType, model e.model),
                 (_, e) -> agent(refuter entry for e: prompt, agentType, model))
```

- The two pipelines run concurrently (one `parallel` of the two), so code refuting overlaps reviewing.
- Every model, agent type and prompt comes from `args`; the script holds no model literal.
- When `args.guidance` is set, the script appends `Developer guidance: <text>` to every reviewer **and**
  refuter prompt. It is a pure pass-through.
- Every agent records through the typed API in its brief. The script carries no findings; it returns only
  `[{id, returned: bool}]` for the session to report.
- **Recovery** for an entry with `returned: false`: a plain Agent dispatch of the failed entry, taken
  verbatim from the printed args, reviewer first and then its refuter. A refuter whose reviewer has not
  recorded fails fast: its `init` exits 1 with `reviewer <slot> has not recorded`. There is no `block`
  step and no row-reprint command in the recovery; `merge` refuses any slot left without a refutation.

### Agent, brief and models (`review_models.py`)

- **`harness:adversarial-reviewer`** (`plugins/harness/agents/adversarial-reviewer.md`): Read, Grep, Glob
  and Bash, plus Write for its one draft file, the same tool set as `pr-reviewer`. Frontmatter
  `model: opus`. Its brief sets the role (`code` or `findings`).
- **No repo writes through Bash.** The agent file and the refuter briefs forbid them. Probes run only under
  the run directory, and pytest probes pass `-p no:cacheprovider`, so `clean_tree_check` never sees a stray
  file. The contract test checks the rule text.
- **Constants:** `ADVERSARIAL_WORKFLOW == "workflows/adversarial-review.js"` (spelled as a code literal, so
  test selection sees it), `ADVERSARIAL_AGENT == "harness:adversarial-reviewer"`,
  `REFUTER_MODEL == "opus"`. The capture row and the contract test both read them.
- **Code refuter output:** `AttackFinding(Finding)` adds a required, non-empty `attack: str` (the failing
  input, the broken call path, or the test that would fail). `CodeRefuterReport(ReviewerReport)` holds
  `AttackFinding` findings. `record`, `record_add`, `record_draft` and `load_report` validate any id that
  starts with the reserved prefix `adv_code` as a `CodeRefuterReport`, so a missing `attack` raises
  whichever record call is used. `record_attacks` and `record_attacks_draft` are the code refuter's record
  calls; they refuse an id that does not start with `adv_code`.
- **Finding keys (D13):** `finding_key(finding) -> str` is the first 12 hex characters of sha256 over the
  finding's canonical JSON (`model_dump(mode="json")`, sorted keys). `report_digest(report) -> str` is the
  same over the whole report's findings list.
- **Refuter `init`:** `init --pr <key> --agent <id> --run-id <run id>`. It refuses a run id that is not
  `current`, so a recapture during a long Workflow run cannot redirect a refuter that has not started. It
  prints each target finding as `[<key>] <severity> <name> <file>:<lines>`. The record heredocs in the
  refuter briefs embed `run_id=`, as reviewer briefs do.
- **Findings refuter output:** `RefutationReport(refuter, target, report_digest, refutations)`, each entry a
  `Refutation(key, verdict, evidence)` with verdict `refuted` or `upheld`. A refuted entry needs evidence
  (the `path:line` it opened and what it showed); the report must cover every finding of its target.
  `load_refutations(path)` reads one.
- **Record calls:** `record_refutations(pr, refuter, target, entries, repo=...)` (entries are dicts
  `{key, verdict, evidence}`) and `record_refutations_draft(pr, refuter, target, repo=...)`. Both store the
  target report's digest at record time.

### Report layout and discovery

- **Reviewer reports:** `findings/<slot>.json`, as today.
- **Code-refuter reports:** `findings/adv_code*.json`. They are part of `report_sources`, so `stray_reports`
  accepts them and `build_meta` credits them as `adv_code (opus)`; done criterion (c) credits them the same
  way.
- **Refutations:** `refutations/<target>.json`, never under `findings/`.
- **`fold_check`** refuses a source id with the `adv_` prefix.
- **`block --agent adv_refute_<t>`** reprints from `refutations/<t>.json`.
- `plan.json["adversarial"]` is the only discovery source for refuter ids; a run without the key has no
  refuters, and the existing paths behave as today.

### Merge (`review_merge.py`)

- **`merge_findings_traced(reports) -> (issues, trace)`**: the trace maps each issue id to a list of
  `(source_id, finding_key)`. `merge_findings` stays as is and equals `merge_findings_traced(...)[0]`.
- **`merge_adversarial(reports, refutations) -> (issues, notes)`**: merges every `report_sources` entry
  (reviewer, code refuter and folded), then maps each refutation onto the issue its finding landed in
  through the trace. A finding with no refutation entry (a folded one) counts as upheld.
- **Stale and missing refutations:** `merge` refuses when a refutation's stored digest differs from the
  target report's current digest (`refutation stale: rerun adv_refute_<target>`), and when a non-folded
  source has a report but no refutation report (a problem line naming the slot).
- **All-refuted issue:** an issue counts as refuted only when every finding in it was refuted. Its issue dict
  carries `"refuted": "<evidence>"` (D9's `Attack: <text>` already sits in the summary).
- **Mixed group:** when some findings in a group are refuted and some upheld, rank, name, summary and
  `fix_kind` come from the upheld findings only. The refuted findings contribute only their evidence, to the
  merge notes.
- **Attack text:** `_Record` and `_combine` carry `attack` only to fold `Attack: <text>` into the summary
  (D9). No schema field holds it.
- The `merge` table prints a `refuted` column.

### Amend

- **Refuted state lives on the draft issue dict**, key `refuted` (the evidence string), never in a map keyed
  by issue id, so it cannot go stale when ids change.
- `regrade` and `merge_ids` carry the key with the issue.
- `amend --merge` keeps `refuted` only when every merged issue is refuted, with their evidence joined by a
  blank line. The mixed-group rule above applies: rank, name, summary and `fix_kind` come from the
  non-refuted issues.
- There is no amend op for refutation, so `merge --force` drops nothing new.

### Build

Order inside `build`:

1. `review_document` reads each issue's `refuted` key, writes one `REFUTED` resolution per refuted id
   (`refuted_resolutions(issues, date)`: status `REFUTED`, the build date, the evidence), strips the key
   (`strip_refuted(issues)`), and computes the verdict over those resolutions.
2. `apply_phase4` / `hold_ready_verdict`.
3. Commit.

With this order, an all-refuted review whose Phase 4 first run fails gets a held verdict and passes
validation: the resolutions are exempt from the pending rule, and the READY half is held.

- The `build` line lists `refuted: <id> (<evidence first line>)` for each refuted id.
- `build` completes `adversarial_check` with the counts and `refuted_ids`.
- `build --replace` regenerates the refuter-written `REFUTED` entries from `draft.json` (`phase5_state`
  ignores them while `draft.json` still marks the id `refuted`), and refuses after a developer `refute` or
  `unrefute`.

### REFUTED as a closed status

`REFUTED` joins `CLOSED_STATUSES` (`review_merge.py:57`, today `("RESOLVED", "CLOSED_NO_ACTION")`). Every
reader of that tuple moves at once:

| Consumer | Before | After |
|---|---|---|
| `compute_verdict` (`review_merge.py:347`) | a refuted critical or important id stays open: NOT READY | closed; the READY text reports `K refuted` separately from resolved |
| `_closed_ids` (`:316`), `_settled_ids` (`:333`) | refuted id open | refuted id closed and settled |
| `undispositioned_ids` (`:340`) | lists the refuted id | omits a refuted id; lists an id whose latest status is `NOT_RESOLVED` |
| `_named_ids` (`:327`) | every resolution names its id | a `NOT_RESOLVED` latest status is not a disposition (the id needs a fix); a `BUBBLED` id is named by the bubble entry the `--bubble` route writes |
| closeout `apply_*` skips (`_apply_fixed` `:756`, `_apply_bubbles` `:787`, `_apply_closed` `:804`, `_apply_deferred` `:827`, `_apply_resolved` `:861`) | a refuted id can gain a RESOLVED or bubble entry | skipped as closed; `closeout --resolved` on it refuses with a problem line naming `unrefute` |
| `review_bubbles.closed_ids` (`review_bubbles.py:11-14`) | refuted id open | refuted id closed (feeds the rows below and `bubble_memo.py:475`) |
| `bubble` (`pr_review.py:1387-1389`) | bubbles a refuted id | refuses, with a problem line naming `unrefute` |
| `waves` (`pr_review.py:1462`; `--ids` through `_selected`, `:1412-1418`) | a refuted id gets a fixer | a refuted id gets no fixer, `--ids` included; a `NOT_RESOLVED` id is open and gets one |
| Done line (`pr_review.py:1953`) | counts every closed id as resolved | reports `K refuted` separately from resolved |
| `review_edit._without_closed_bubbles` (`review_edit.py:507`), `merge_issue_ids` (`:355`) | refuted id open | treated as closed, like `CLOSED_NO_ACTION` |
| `review_edit.RESOLUTION_STATUSES` (`review_edit.py:57`, closeout's `--closed` / `--deferred` vocabulary) | unchanged | unchanged: it gains none of `REFUTED`, `BUBBLED`, `NOT_RESOLVED`; only `build`, `refute` and `unrefute` write them |
| TS mirrors (`bubbles.ts:59`, `review.ts:40`, `memo.ts:38`) | a refuted bubbled id stays an open bubble | gain `REFUTED`: a bubbled id the developer refutes reads as Decided (D11, `TASK-10`) |

`operating_rules.md:35` and pr-review `SKILL.md:489` change with it. `BUBBLED` and `NOT_RESOLVED` are not
closing: the latest-status rule makes an unrefuted id open again for every consumer above.

### Refute and unrefute

A driver pipeline lets the developer overrule in either direction, any time after build (D5): in phase
consolidate, fix-plan, fix or done, on any review, with or without `-a`.

**Shared rules for both commands:**

- They pull the issue from the **built review object** (`<reviews>/<NNNN>_<slug>.json`), not from
  `draft.json`. Each refuses an id not in `issues`, prints the issue's tier, name and `file:lines`,
  recomputes the verdict and writes through the one validated review writer.
- Under `-a` they also update `adversarial_check` (`refuted_ids` / `unrefuted_ids`).
- Library: `review_edit.issue_info(doc, issue_id)` returns the issue dict (tier, name, file, lines) or
  raises `ValueError` for an unknown id. `review_edit.apply_refute(doc, issue_id, evidence, date)` and
  `review_edit.apply_unrefute(doc, issue_id, mode, reason, date)` (`mode` is `"bubble"` or `"fix"`) refuse
  with `ValueError` on the cases below.

**Add: `refute --pr <key> <ID> --evidence "<text>"`**

- Refuses an id whose latest status is already closing (`RESOLVED`, `CLOSED_NO_ACTION`, `REFUTED`).
- Appends `{"id", "status": "REFUTED", "date", "evidence"}`.
- A refuted id gets no fixer; a bubbled id becomes Decided in the mods (D11). From phase `done` the run
  stays `done`.

**Remove: `unrefute --pr <key> <ID> (--bubble --classification C --reason R | --fix [--reason R])`**

- Refuses unless the id's latest status is `REFUTED`.
- `--bubble`: appends `{"status": "BUBBLED", "evidence": R}`, then runs the existing `bubble` path for the id
  (the same classification vocabulary, `bubbles`, verdict); its bubble entry goes through the existing
  bubble function. From there the normal Phase 5 Step 5 bubble workflow applies.
- `--fix`: appends `{"status": "NOT_RESOLVED", "evidence": R or "refutation overruled"}`. The id is open
  again and the next `waves` plans a fixer for it (`waves --ids <ID>` included). The phase moves to `fix`
  when it was `done`.
- Clears the issue's `refuted` key in `draft.json` when present, so `build --replace` cannot refute it again.

**Statuses (D12):** `REFUTED` is closing; `BUBBLED` and `NOT_RESOLVED` are non-closing. `CLOSED_STATUSES`
gains only `REFUTED`. A developer `refute` or `unrefute` entry counts as Phase 5 begun for `phase5_state`.

**Visibility:** the Phase 5 Step 5 pause, or the terminal summary when there are no bubbles, lists the
refuted ids with their evidence, so the developer sees what to overrule.

### Phase 5 and the hook

- **`phase5_state`** ignores a `REFUTED` resolution only while `draft.json` marks its id `refuted`; a
  developer `refute` / `unrefute` entry counts as Phase 5 begun (Constraints).
- **Layer 3:** the hook's `_closeout_reason` (`validate_pr_json_schema.py:232-249`) does not count
  `REFUTED`, `BUBBLED` or `NOT_RESOLVED` entries toward the SHA-evidence test. Their evidence is `path:line`
  or developer text, so without this the Stop hook would block an all-refuted or refuted-plus-bubbled review
  until the stale cutoff.
- **Layer 2:** `review_merge._pending_problems` and the hook's `_incoherent` exempt `REFUTED`, `BUBBLED` and
  `NOT_RESOLVED` resolutions (Constraints); the READY half stays enforced.
- pr-review SKILL Step 0 reads "no unrefuted issues, no Phase 5".

### Schema (`PR_REVIEW.schema.json`)

- `$version` 2.2.0 -> **2.3.0** (minor, no sweep of old reviews). Moving together: the schema `$version`,
  `review_merge.SCHEMA_VERSION` (`review_merge.py:54`), `schemas/README.md:31` and `:33`, and the pin in
  `tests/lib/test_review_merge.py:404`.
- `post_review_resolution.status` gains three values:
  - `REFUTED` (closing): "refuted by the adversarial findings refuter at build, or by the developer through
    `refute`; evidence is the refuter's or the developer's case".
  - `BUBBLED` (non-closing): "a refutation overruled by the developer and routed to the bubble workflow".
  - `NOT_RESOLVED` (non-closing): "a refutation overruled by the developer and routed to Phase 5 waves".
- `verification_log.dispatch_time.adversarial_check` is **optional**, written only under `-a`, so old
  reviews, in-flight `plan.json` files and pr-team's `dispatch_time` stay valid. Fields:
  - At capture: `applies` (true), `workflow`, `code_slots`, `refute_slots`, `result`.
  - After build: `counts: {findings_checked, findings_refuted, findings_upheld, code_findings}`, and
    `refuted_ids`.
  - `unrefuted_ids`. Under `-a`, `refute` and `unrefute` also update `refuted_ids` and `unrefuted_ids`.
- No `attack` field: the schema has no finding definition, and the attack text rides in the summary (D9).
- A project's pinned copy under `schemas_dir` is updated where this repository pins one; a consumer project
  whose pin lacks the new statuses is refused at `capture -a` (see "Capture").

### Mods: agent-watcher and bubble-stamp

- `plugins/harness/agents/adversarial-reviewer.md` needs `harness:adversarial-reviewer` in the
  agent-watcher `DEFINED_AGENTS` contract; that line lands with the agent file (`TASK-6`).
- `TASK-9` owns the rest of the agent-watcher Workflow work: the refuter role in `identify.ts`, the matrix
  rule per D6, the agent-watcher version bump and its release row. It waits on `SPK-1` and `TASK-6`, and is
  blocked until the developer decides D6.
- `TASK-10` adds `REFUTED` to the TS closed-status mirrors (D11): agent-watcher
  `hooks/layers/pr-review/bubbles.ts:59`, bubble-stamp `hooks/review.ts:40` and `hooks/memo.ts:38`. Both
  mod versions bump; their mirror tests (`bubbles.test.ts`, `review.test.ts`, `memo.test.ts`) and release
  rows move with them. It depends on `TASK-1` only.

### Skills and docs

- **pr-review SKILL.md:**
  - `-a` in the argument hint and the capture table.
  - Before capture: with `-a` and no Workflow tool, print the `problem:` line and do not run capture (D7).
  - A Phase 2 section, "Under `-a`": one Workflow call with the printed row. Same rules as the Agent rows:
    no edits to the row and no added or dropped slots, with one named exception, `args.guidance`. It states
    the agent-count formula, the Phase 3 trigger and the recovery.
  - A "Model floor" row: refuters run on `opus`.
  - The `refute` and `unrefute` rows (any time after build, any review); Phase 3 reads the `refuted`
    column; the Phase 5 Step 5 pause lists refuted ids.
  - Step 0: "no unrefuted issues, no Phase 5". `SKILL.md:489` counts refuted ids apart from resolved.
- **pr-review operating_rules.md** (`:35`): `REFUTED` is closed for the verdict and Phase 5; a refuted
  issue gets no fixer; the developer overrules any time after build with `refute` or `unrefute`
  (`--bubble` or `--fix`).
- **review-local SKILL.md:** `-a` in the argument-hint, the capture line and the rows table; an "Under `-a`"
  Phase 2 paragraph; the recovery above in place of "dispatch the row again".
- **fold-in-review SKILL.md:** one line saying folded findings are not refuted.
- **`schemas/README.md`:** `:31`, `:33` (version), `:40`, `:283` (status prose).
- **`pr_review.py` module docstring** (`:1-127`): `-a`, `init --run-id`, `refute`, `unrefute`.
- **README:** a `workflows/` row in the layout table (`README.md:575-586`) and the feature prose.
- **Release:** harness `plugin.json` to `0.71.0` (minor, a new feature) and the `docs/RELEASES/v<next>.md`
  line, with the agent-watcher and bubble-stamp rows from `TASK-9` and `TASK-10`.

## Tests

New files:

| File | Covers |
|---|---|
| `tests/lib/test_review_adversarial_models.py` | constants; `AttackFinding`, `CodeRefuterReport`; `finding_key`, `report_digest`; `Refutation`, `RefutationReport` (refuted needs evidence, full coverage); `load_refutations`; `record_attacks(_draft)` refuse a non-`adv_code*` id; `record_refutations(_draft)` store the digest; `adv_code` validation in `record`, `record_add`, `record_draft`, `load_report` |
| `tests/lib/test_review_merge_adversarial.py` | `CLOSED_STATUSES` holds `REFUTED`; `SCHEMA_VERSION == "2.3.0"`; `merge_findings_traced`; `merge_adversarial` (all refuted, mixed group, folded upheld, attack fold); `refuted_resolutions`, `strip_refuted`; `regrade` / `merge_ids` carry `refuted`; `amend --merge` rule; one test per consumer in the trace; a `NOT_RESOLVED` latest status is not a disposition in `_named_ids` / `undispositioned_ids`; the Layer 2 exemption (`REFUTED`, `BUBBLED`, `NOT_RESOLVED`); READY text; `review_document` order; `review_edit.issue_info`, `apply_refute` (refuses a closing latest status), `apply_unrefute` in both modes (refuses a non-refuted id) |
| `tests/lib/test_review_adversarial.py` | every classification row through `make_project`, plus `tree_at_head` false and unreadable state; refuter slots, pool or single; agent-count formula; `workflow_args` (`guidance` null, run id); every `adv_*` slot is `opus`; `adversarial_check` / complete; the schema `REFUTED` check helper; `_check_project_lens` rejects `adv_` / `adv-` |
| `tests/schemas/test_pr_review_schema_adversarial.py` | `$version` 2.3.0; `REFUTED`, `BUBBLED` and `NOT_RESOLVED` in the enum; `adversarial_check` optional with its fields; a 2.2.0-shaped review still validates |
| `tests/hooks/test_schema_hook_refuted.py` | `_closeout_reason` on an all-refuted review, on a refuted-plus-bubbled review, and with `BUBBLED` / `NOT_RESOLVED` entries; `_incoherent` exemption |
| `tests/scripts/test_pr_review_adversarial.py` | `capture -a` refusals before `start_run` (missing script, pinned schema); `plan["adversarial"]`; the Workflow row; the off-flag shape (no `adversarial` key, no `adversarial_check`); `init --run-id` mismatch, unrecorded reviewer, zero findings; `merge` stale digest and missing refutation; `report_sources`, `stray_reports`, `fold_check`, `block`; build `REFUTED` and the `refuted:` line; `build --replace` after a Phase 4 STOP exits 0, and is refused after a developer overrule; all refuted plus a Phase 4 failure gives a held verdict that validates; `refute` on a review without `-a`; `refute` on an already closed id refused; `unrefute --fix` then `waves` plans the id; `unrefute --bubble` then the id is in `bubbles`; `unrefute` on a non-refuted id refused; both commands refuse an unknown id; phase `done` -> `fix` on `--fix`; `bubble` and `closeout --resolved` refusals; `waves` skip; done line |
| `tests/contract/test_adversarial_workflow.py` | the script's meta literal parses; its `agentType` values name existing agents; the phases match; no `'opus'`, `'sonnet'` or `'haiku'` literal in the JS; agent frontmatter `model: opus`; the Bash write ban text. Sets `WALK_ROOTS = ("plugins/harness/agents/", "plugins/harness/workflows/")` if it walks |
| `tests/skills/test_pr_review_adversarial_docs.py` | the pr-review `-a` section (row rule and `guidance` exception, agent count, Model floor row, `refute` and `unrefute` rows, Step 0); `operating_rules.md`; the review-local `-a` branch; the fold-in-review line |

Edits to existing tests:

- `tests/contract/test_no_repo_literals.py`: `.js` joins `TEXT_SUFFIXES` (lands with `TASK-6`).
- `tests/lib/test_review_merge.py`: the schema version pin (`:404`) moves to 2.3.0.
- The agent-watcher `DEFINED_AGENTS` contract (`tests/mods/test_agent_watcher_usage_contract.py:119-135`)
  gains `harness:adversarial-reviewer`.
- The TS mirror tests `plugins/agent-watcher/hooks/layers/pr-review/bubbles.test.ts`,
  `plugins/bubble-stamp/hooks/review.test.ts` and `plugins/bubble-stamp/hooks/memo.test.ts` treat a bubbled
  id whose latest status is `REFUTED` as closed (`TASK-10`; run through `claude plugin test`).

## Sequencing

1. **`SPK-1`** first: the Workflow spike (see "Assumptions to verify first").
2. Build #252 on this branch through a plan (`harness:write-plan`), TDD per item:

   | Item | Scope |
   |---|---|
   | `TASK-1` | schema 2.3.0 (`REFUTED`, `BUBBLED`, `NOT_RESOLVED`, optional `adversarial_check`), `SCHEMA_VERSION`, README and test pin, `CLOSED_STATUSES`, `_named_ids`, Layer 2 exemption in `_pending_problems` and `_incoherent`, hook `_closeout_reason` |
   | `TASK-2` | `review_models` constants, models, keys, record calls, `adv_code` validation |
   | `TASK-3` | `review_adversarial` (classification, refuter slots, `workflow_args`, `adversarial_check`, schema check helper, agent count); reserved lens prefix |
   | `TASK-4` | `review_merge` traced merge, `merge_adversarial`, carry rules, `review_document` order, READY and done text; `review_edit.issue_info`, `apply_refute`, `apply_unrefute` |
   | `TASK-5` | `pr_review.py` and `review_briefs`: capture, `init`, merge, discovery, build, `phase5_state`, `refute` and `unrefute`, refusals, waves, done line (needs `SPK-1`) |
   | `TASK-6` | the workflow script, the agent file, the `DEFINED_AGENTS` line, `.js` in `TEXT_SUFFIXES` (needs `SPK-1`) |
   | `TASK-7` | docs and release |
   | `TASK-8` | the pr-team follow-up TODO item (command-only) |
   | `TASK-9` | agent-watcher Workflow rows (needs `SPK-1`, `TASK-6`; blocked on D6) |
   | `TASK-10` | TS closed-status mirrors gain `REFUTED` (D11): agent-watcher `bubbles.ts`, bubble-stamp `review.ts` and `memo.ts`, both versions, mirror tests, release rows (needs `TASK-1` only) |

3. **Then the review-local strap round**, as `strap.py reopen review-local`: a new round on a frozen spec,
   not a plain refreeze, because `-a` is a new review-local behavior. The spec starts from the legacy stamp
   `8538f729` and is already stale (`8538f729` -> `400373d6`, todo-5rze / #275). #252 changes four of its
   parts: `pr_review.py`, `review_models.py`, `review-local/SKILL.md` and
   `tests/skills/test_review_local_skill_contract.py`. Strapping first would make it stale again. Each `-a`
   behavior is classified there:
   - Mechanical: `capture -a` refuses when the workflow script is missing; `build` writes `REFUTED`;
     `refute` closes an id and `unrefute` reopens it (`--bubble` or `--fix`).
   - Judgment: with `-a` and no Workflow tool, the session stops without running capture; the session calls
     Workflow with the row unchanged apart from `guidance`; the session never runs `refute` or `unrefute`
     without the developer's word.
4. File the follow-up TODO item for pr-team `-a` (`TASK-8`).

## Left to the builder

- Brief wording for both refuter roles, held to the anti-goals above.
- Exact names of internal helpers beyond those fixed here (`merge_adversarial`, `merge_findings_traced`,
  `refuted_resolutions`, `strip_refuted`, `finding_key`, `report_digest`, `AttackFinding`,
  `CodeRefuterReport`, `Refutation`, `RefutationReport`, `load_refutations`, `record_attacks(_draft)`,
  `record_refutations(_draft)`, `issue_info`, `apply_refute`, `apply_unrefute`, the constants and the
  driver commands).
- The key layout of the Workflow `args` object beyond `guidance` and the run id.
- The JS structure inside the thin-script rule.
- Problem-line wording, except the lines fixed above (`refutation stale: rerun adv_refute_<target>`,
  `reviewer <slot> has not recorded`, `no findings: done`, and the `unrefute` naming in refusals).
- The doctor check for a pinned schema (deferred to a future plan).
- Not the builder's: D6, which the developer decides after `SPK-1`.

## Review resolutions

| Finding | Covered in |
|---|---|
| S1 | Constraints (Phase 5 detection); Build; Refute and unrefute; Phase 5 and the hook; Tests |
| S2 | Goals; Anti-goals; Decisions (D5, D12, developer answers); Refute and unrefute; Skills and docs |
| S3 | Goals; Constraints (the verdict); REFUTED as a closed status; Decisions (D11); Mods (`TASK-10`) |
| S4 | Phase 5 and the hook (Layer 3); Skills and docs (Step 0); Tests |
| S5 | Merge (mixed group); Amend |
| S6 | Amend; Merge (all-refuted issue) |
| S7 | Agent, brief and models (finding keys, refuter `init`); Merge (traced merge, stale refutations); Decisions (D13) |
| S8 | Agent, brief and models (code refuter output); Merge (attack text); Schema; Decisions (D9) |
| S9 | Capture (slot plan); Report layout and discovery; Merge |
| S10 | Plan-path classification; Non-goals; Decisions (D10, D14) |
| S11 | Non-goals; Schema; Decisions (D8) |
| S12 | Capture (refusals); Schema |
| S13 | Constraints (Layer 2); Build; Phase 5 and the hook |
| S14 | Constraints (missing Workflow tool); Capture; Sequencing; Decisions (D7) |
| S15 | Assumptions to verify first; Sequencing |
| S16 | Mods: agent-watcher and bubble-stamp; Decisions (D6); Assumptions to verify first; Sequencing |
| S17 | The workflow (recovery); Skills and docs |
| S18 | Capture (Workflow row); The workflow; Skills and docs |
| S19 | Agent count; Skills and docs |
| S20 | Sequencing (step 3) |
| S21 | Tests; Constraints |
| S22 | Agent, brief and models (refuter `init`) |
| S23 | Agent, brief and models (no repo writes through Bash); Tests |
| S24 | Skills and docs (review-local) |
| S25 | Constraints (filesystem access) |
| S26 | Scope of the code refuter; Pool or single |
| S27 | Capture (reserved prefix); Tests |
| S28 | Capture (models); The workflow; Agent, brief and models; Skills and docs; Tests |
| S29 | Schema (`adversarial_check` fields); Build; Refute and unrefute |
| S30 | Skills and docs |
| S31 | Scope of the code refuter |
