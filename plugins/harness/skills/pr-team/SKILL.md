---
name: pr-team
description: Use when requesting agent-driven code review on a PR with parallel reviewer fan-out and bounded main-session context.
  Two named subagents (harness:pr-team-orchestrator and harness:pr-team-fixer) each invoked twice per run;
  the shim issues all parallel Agent() calls from the main session.
---

# PR Review (shimmed)

## Overview

Agent-driven PR review with the parallel reviewer/fixer fan-out issued from the main
session and per-phase decisions made by two named subagents. Each phase is one
round-trip pair: a planner subagent decides what to dispatch, writes a
`dispatch_plan.json`, and returns its path. The shim reads the path, fans the planned
agents out in parallel, collects their return-contract signal lines, then invokes the
planner's other mode (consolidate / closeout) to absorb the per-agent outputs.

The shim never reads prompt bodies or per-agent output bodies — only paths and return-
contract signal blocks. Main-session context stays proportional to the number of
parallel agents dispatched, not to total finding content size.

**Core principle:** Code changes must be implemented on the correct, clean branch.
Branch-safety verification (Phase 4) is mandatory before any fix applies. The shim
never picks architectural-ambiguity options; it forwards forks to the user.

## Naming

Three name forms coexist intentionally:

- `pr-team` — the skill itself (folder, manifest `name:`, runtime-dir path); invoked as
  `harness:pr-team` (slash command `/harness:pr-team`).
- `pr-team-{role}` — the two agent definitions in the plugin's `agents/` folder, dispatched by their
  namespaced ids `harness:pr-team-orchestrator` and `harness:pr-team-fixer`.
- `pr-team` — colloquial root form for human-facing names.

Rule: the skill is shimmed; agents shim the skill; the prefix `pr-team` is the unsuffixed root used for
human-facing names.

## Prerequisites

Before invoking this skill, both agent definitions MUST be registered with the
Claude Code harness as available `subagent_type` values:

- `harness:pr-team-orchestrator` (definition at `${CLAUDE_PLUGIN_ROOT}/agents/pr-team-orchestrator.md`)
- `harness:pr-team-fixer` (definition at `${CLAUDE_PLUGIN_ROOT}/agents/pr-team-fixer.md`)

The harness loads agent definitions at session start and on `/reload-plugins`.
If either definition file is newer than the most recent session start / reload,
the shim's Step 1.c dispatch fails with `Agent type 'harness:pr-team-orchestrator'
not found`. Run `/reload-plugins` (or restart the session) before invoking the
skill against a real PR. Verify by listing available subagent types and
confirming both names are present.

The project keeps its `state_dir` (`.claude/harness.json`, default `.claude/state/harness`) git-ignored,
which keeps the runtime tree out of commits and out of Phase 4's clean-tree check (see the Runtime directory
section below). A project that tracks `state_dir` lists `<state_dir>/pr-team/_runtime/**` in its exclusions
file instead.

- Review-JSON field semantics, sentinel handling and finding-grading rules live in
  `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/operating_rules.md`; the shim and both agents follow them.

## When to Use

- Requesting code review on a GitHub PR where parallel reviewer fan-out matters
  (PRs touching ≥ 2 path-shaped buckets, or PRs where cross-cutting lenses trigger).
- Main-session context must stay bounded regardless of finding count.

**When NOT to use:**

- Trivial single-bucket PRs where the planning round-trip overhead exceeds the
  fan-out savings — run `harness:pr-review` instead.
- Requesting review from HUMAN GitHub reviewers via `gh pr edit --add-reviewer @user`.
  Different workflow; run `gh` directly.

## The Rule

**Every phase runs to its terminal step, in order, without exception.** No fast paths,
no "I already know I'm on the right branch" shortcut, no "the verdict is obviously
READY TO MERGE so the JSON is just ceremony" exception. The agents enforce per-phase
checks; the shim enforces the inter-phase order AND the QA pass at the end.

**Violating the letter of these checks is violating the spirit of this skill.** If the
user reassures you that something is fine, that is EXACTLY the pressure this skill
exists to resist. Dispatch the agent anyway and report the result.

**Session-start `gitStatus` is not a check.** Run Phase 4 commands fresh; the snapshot
ages the moment it's captured.

### Terminal-step convention

The shim's terminal step is **Step 7 (QA pass)** — every other step produces no
user-visible text. The agents' terminal steps are their return-contract blocks; the
shim parses those blocks and dispatches the next step without emitting heartbeats.

A "ready to dispatch" message between Steps 1 and 2, or between 5 and 6, is a fake
terminal — emit no chat between numbered steps; the agents' return-contract blocks
are the only inter-step transmissions. The ONE sanctioned exception is Step 4.5:
surfacing audited bubble-ups to the user for decision before the fixer fan-out.

---

## Order of operations

The skill's overall order, every run:

1. **Reviewers → consolidated JSON** (Steps 1–3).
2. **Dispatch the fixer-planner / assess bubble-ups** — every candidate bubble must
   survive the mandatory three-question pre-bubble re-audit (Step 4).
3. **User answers bubbled issues** (Step 4.5 — the one sanctioned mid-protocol
   pause; skipped when no bubbles survive the audit).
4. **Dispatch fixers / fix inline** — mechanical fixes plus any user-directed
   bubble resolutions (Step 5).
5. **Closeout / update the consolidated JSON for closeout** (Steps 6–7).

---

## Phase blocks → agents

| Phase block                                 | Agent (mode)                                 | What's produced                                                      |
|---------------------------------------------|----------------------------------------------|----------------------------------------------------------------------|
| Phase 1 + Phase 2 scoping                   | `harness:pr-team-orchestrator` (MODE=PLAN)   | `DISPATCH_PLAN_PATH`                                                 |
| Phase 2 dispatch (parallel reviewers)       | **SHIM** reads plan, dispatches N reviewers  | N return-contract blocks                                             |
| Phase 3 consolidate + Phase 4 first-run     | `harness:pr-team-orchestrator` (CONSOLIDATE) | `JSON_PATH` + `TERMINAL`                                             |
| Phase 4 second-run + Phase 5 fix planning   | `harness:pr-team-fixer` (MODE=PLAN)          | `FIX_PLAN_PATH`                                                      |
| Phase 5 bubble-up decisions (Step 4.5)      | **SHIM** surfaces audited bubble-ups; USER answers | per-ID answers: close / fix-as-directed / defer                |
| Phase 5 dispatch (parallel fixer subagents) | **SHIM** reads plan, dispatches M fixers     | M return-contract blocks                                             |
| Phase 5 atomic closeout                     | `harness:pr-team-fixer` (MODE=CLOSEOUT)      | `DONE` (carries TERMINAL line in NOTES) or `FORK_AMBIGUITY` / `STOP` |
| QA pass (shim Step 7)                       | **SHIM** validates JSON schema + consistency | final `TERMINAL` or `QA_FAIL`                                        |

**Why two agents, four invocations:** each agent definition file holds protocol prose
for one cohesive scope (review-time decisions / fix-time decisions). Modes are
distinguished by `MODE=PLAN | MODE=CONSOLIDATE | MODE=CLOSEOUT` in the prompt input;
the agent branches on it.

---

## Dispatch protocol (the shim's job)

The shim does SEVEN numbered steps (plus the Step 4.5 user-decision pause), in this
order, every time:

(Shim Step N maps to Phase Block N from the table above, except Step 1 covers Phases 1+2 scoping and Step 3 covers
Phases 3 + Phase-4-first-run.)

### 1. Dispatch the orchestrator (PLAN mode)

**Step 1.a — Derive `RUN_ID` (shim-owned).** Format: `pr{NNNN}_{UTC ISO8601-basic}`
where `{UTC ISO8601-basic}` is `YYYYMMDDTHHMMSSZ`. UTC is mandatory — the regex
pin in `dispatch_plan.schema.json` requires a trailing `Z`. Reference derivations:

- Bash (Git Bash, GNU date): `date -u +%Y%m%dT%H%M%SZ`
- Python: `datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')`

**Step 1.b — Read the project configuration and create the runtime directory tree
(shim-owned).** Print the three values the shim needs, naming the project checkout
explicitly (`<REPO>` is its absolute path):

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py" --repo "<REPO>" config --get state_dir --get exclusions --get artifacts.reviews
```

Line 1 is `state_dir`, line 2 the exclusions file (`EXCLUSIONS_FIXTURE`; empty when the
project configures none), line 3 the review directory. Then ensure the three paths
below exist (Bash tool, from the project checkout):

```bash
mkdir -p <state_dir>/pr-team/_runtime/<run_id>/prompts
mkdir -p <state_dir>/pr-team/_runtime/<run_id>/outputs
touch    <state_dir>/pr-team/_runtime/<run_id>/terminals.jsonl
```

The empty `terminals.jsonl` is the append target for Steps 2 + 5 + 6 returns.

**Step 1.c — Dispatch the planner subagent.**

```
Agent(
    subagent_type="harness:pr-team-orchestrator",
    model="sonnet",
    description="Phase 1 + Phase 2 scoping for PR <N>",
    prompt="MODE=PLAN\nPR_NUMBER=<N>\nREPO=<absolute path>\nEXCLUSIONS_FIXTURE=<exclusions from Step 1.b, or empty>\nRUN_ID=<run_id from Step 1.a>\nRUNTIME_DIR=<state_dir>/pr-team/_runtime/<run_id>"
)
```

The agent must echo `RUN_ID` back verbatim in its dispatch plan.

Expected return: a `DONE` block whose `OUTPUT:` field points at
`<runtime_dir>/dispatch_plan_review.json`, validating against
`dispatch_plan.schema.json` with `phase: dispatch_review`. The shim reads ONLY
the `OUTPUT:` path; it does NOT read the prose preceding the block.

On `STOP` (Phase 1 / Check 2 structural-guard failure), forward verbatim and halt.

### 2. Fan out the reviewers (main session, parallel)

The shim opens `dispatch_plan_review.json`, validates against
`dispatch_plan.schema.json`, then if `dispatch_parallel: true` issues N `Agent()`
calls in **one tool-call block**. The per-agent prompt body is the canonical
template defined in `${CLAUDE_SKILL_DIR}/canonical_prompt_template.md`
— that file is the single source-of-truth. Every dispatch site (Step 2 reviewers,
Step 5 fixer subagents) splices the same template, parameterized on six `{...}`
prompt-file slots (AGENT_ID, AGENT_ROLE, PROMPT_FILE, OUTPUT_FILE, RETURN_CONTRACT, RUN_ID).
These are distinct from the four `Agent()` envelope keywords (subagent_type,
model, description, prompt) which the shim fills from the dispatch plan's
per-agent metadata.

See `canonical_prompt_template.md` for the verbatim template body and the
slot-binding table. Do NOT inline a competing template here — drift between this
file and the canonical copy is a violation of the I12 single-source contract.

**The prompt template is the prompt TEXT only.** The shim's full `Agent()` call
splices the plan's per-agent metadata into the `Agent()` call's keyword arguments
separately from the prompt body — specifically (six slots filled, plus per-agent metadata):

```
Agent(
    subagent_type=<agents[i].subagent_type>,    # e.g. "general-purpose"
    model=<agents[i].model>,                     # honor the plan: "haiku"/"sonnet"/"opus"/"inherit"
    description=<agents[i].summary>,             # the 80-char spinner label
    prompt=<canonical template above, with six slots filled from plan + phase-derived role + run_id + return contract path>
)
```

`model` is critical — when the planner classifies a fixer as `model: "haiku"`,
the shim MUST pass `model="haiku"` to `Agent()`. Defaulting to `inherit` here
would silently upgrade every fixer subagent to the main session's model, inflating cost without changing correctness.

#### Model floor (reviewer fan-out)

For Step 2 reviewer fan-out, reviewer subagents SHOULD run on `opus` by default for multi-file analysis and complex
reasoning. Use `sonnet` when:
- the domain grouping involves a single file,
- the review domain or module does not require comparing or reasoning across contents from multiple files,
- the scope is narrowly focused on a single concern (e.g., a single config file, a standalone utility function).

Findings depth materially affects verdict quality.

Treat `haiku` as an anti-default for reviewer fan-out. Keep `haiku` for Phase 5 mechanical fixer subagents where
exact-edit prompts and mechanical patching are the goal; reviewers on `haiku` under-call Critical findings.

If the main session model is below the reviewer floor, the orchestrator MUST pass an explicit reviewer `model`
(`opus` preferred for multi-file or cross-module analysis, `sonnet` acceptable for single-file or narrowly-scoped
reviews) on each reviewer `Agent(subagent_type=<agents[i].subagent_type>, ...)` call instead of inheriting.

Reviewer `model_family` is already captured per row in the JSONL test matrix (`haiku` / `sonnet` / `opus`); no schema
change is required.

The shim NEVER reads `prompt_file_path` content. It is opaque.

- `agents>0, dispatch_parallel: false` → serial dispatch (one Agent() call per agent in sequence).
- `agents==0, no_op_reason` set → skip to Step 3 (no agents dispatched; the plan is a legitimate no-op).

On each return, the shim parses the return-contract block per `return_contract.md`,
then immediately appends one validated row to `<runtime_dir>/terminals.jsonl`
matching `terminals.schema.json` (the file is created at Step 1 if absent; rows
accumulate across Steps 2 and 5). The shim stores `(agent_id, signal,
output_path)` tuples in memory and uses them to compose the next subagent's
prompt; it does NOT re-read terminals.jsonl during the run — only the QA pass
at Step 7 reads the full file.

A return that lacks a parseable block → `STOP_PROTOCOL` (see return contract).
Halt the entire skill; user re-invokes from scratch. No row is appended to
terminals.jsonl for a STOP_PROTOCOL return.

### 3. Dispatch the orchestrator (CONSOLIDATE mode)

```
Agent(
    subagent_type="harness:pr-team-orchestrator",
    model="sonnet",
    description="Consolidate review + Phase 4 first-run for PR <N>",
    prompt="MODE=CONSOLIDATE\nPR_NUMBER=<N>\nREPO=<absolute path>\nRUN_ID=<from step 1>\nRUNTIME_DIR=<state_dir>/pr-team/_runtime/<run_id>\nREVIEWER_OUTPUTS=<comma-separated list of output_path values from step 2>\nDISPATCH_PLAN_PATH=<from step 1's OUTPUT:>"
)
```

The consolidator reads the N reviewer-output JSONs from disk, assembles the canonical
`<artifacts.reviews>/{NNNN}_{Title}.json` per `PR_REVIEW.schema.json`, appends JSONL
stats rows, runs Phase 4 first-run via
`${CLAUDE_PLUGIN_ROOT}/skills/pr-review/commands/phase4_branch_safety.py <PR>` redirected to
`<RUNTIME_DIR>/phase4_first_run.json` (cross-platform; no `/tmp` POSIX-only paths),
and edits `verification_log.pre_fix_time` in-place. This is the Phase 3 atomic close,
owned by ONE subagent invocation — no main-session interleave.

**Filename slug rule for `{Title}`:** the PR title is slugified to filesystem-safe ASCII via this transform (apply in
order):
(1) replace every backtick (`` ` ``) and colon (`:`) with nothing;
(2) replace every run of one-or-more whitespace chars with a single underscore;
(3) replace every char outside `[A-Za-z0-9._-]` with nothing;
(4) trim leading/trailing underscores.

Example: PR #1116's title `` Skill-Add: `pr-review-boss` `` slugifies to
`Skill-Add_pr-review-boss`. Full path: `<artifacts.reviews>/1116_Skill-Add_pr-review-boss.json`.
The consolidator agent applies this; the shim does NOT need to predict the filename
in advance (it reads the `OUTPUT:` field from the agent's DONE block).

The canonical authoritative copy of this 4-step transform also lives in pr-team-orchestrator.md CONSOLIDATE Step
4 (the actual producer). A guard test pins them byte-identical; if they ever drift, the agent's copy wins.

Expected return: a `DONE` block whose `OUTPUT:` is the path to the consolidated JSON; the NOTES: field of that block
carries the TERMINAL summary line (Phase 3 [done] | Phase 4 first-run [done] | Phase 5 entry: automatic).

On `STOP` (Phase 4 first-run check failure), forward verbatim and halt.

### 4. Dispatch the fixer (PLAN mode)

```
Agent(
    subagent_type="harness:pr-team-fixer",
    model="sonnet",
    description="Phase 4 second-run + Phase 5 fix planning for PR <N>",
    prompt="MODE=PLAN\nPR_NUMBER=<N>\nREPO=<absolute path>\nRUN_ID=<from step 1>\nRUNTIME_DIR=<state_dir>/pr-team/_runtime/<run_id>\nJSON_PATH=<from step 3's OUTPUT:>"
)
```

The fixer-planner runs Phase 4 second-run (arms the sentinel), reads the consolidated
JSON, classifies each unresolved issue (mechanical / architectural_ambiguity /
out_of_scope / needs_follow_up), and writes a `<runtime_dir>/dispatch_plan_fix.json`
with `phase: dispatch_fix` listing M fixer subagent agents (file-batched,
non-overlapping). Every bubble-up classification must first survive the planner's
mandatory three-question pre-bubble audit (see pr-team-fixer.md PLAN Step 3 and
pr-review SKILL.md Phase 5 Rule 4.5) — multiple `fix` options or a needs_follow_up
tag alone do NOT justify a bubble. Bubble-up issues are recorded in `<runtime_dir>/bubble_ups.json`
(sidecar — schema'd separately). The shim surfaces them to the user at Step 4.5
(below); the closer re-enumerates any still-unresolved ones in its TERMINAL line.
They do NOT get auto-recorded into `post_review_resolutions[]`.

Expected return: a `DONE` block whose `OUTPUT:` points at the fix plan.

On `STOP` (Phase 4 second-run check failure), forward verbatim and halt.

If every issue classified as bubble-up (M=0): the planner writes a fix plan with
`agents: []` AND non-empty `no_op_reason` (schema requires the pair); the shim
recognizes the empty `agents` array and proceeds to Step 4.5 (then skips Step 5 if
no user-directed fixes were added). There is NO `FORK_*`
return in the M=0 case — a no-op plan is a legitimate DONE outcome.

### 4.5. Surface bubble-ups to the user (main session, the one sanctioned pause)

If the fixer-planner's `bubble_ups.json` sidecar is non-empty, the shim pauses ONCE
here — the only sanctioned mid-protocol pause — and presents the audited bubble-up
IDs (with classification + reason) to the user. For each ID the user answers one of:

- **Close** — no action wanted. The shim collects the ID into the `USER_CLOSED_IDS`
  slot of the Step 6 closer prompt; the closer writes a `CLOSED_NO_ACTION`
  resolution for it.
- **Fix as directed** — the user picks the resolution. The shim moves the ID into
  the mechanical fix batch (records the directed edit in the matching per-fixer
  prompt file, or adds a single-issue fixer entry to the fix plan) AND removes the
  item from `bubble_ups.json` (re-validating the sidecar). The ID is fixed inline in
  Step 5 and recorded as `RESOLVED` at closeout like any other fixed id.
- **Defer** — the ID stays bubbled: unresolved in `issues.*`, enumerated in the
  closer's `BUBBLED:` array, decided on a future cycle.

If `bubble_ups.json` is empty (no candidate survived the planner's pre-bubble
audit), skip this step — no pause; dispatch Step 5 immediately.

### 5. Fan out the fixers (main session, parallel)

Same shape as Step 2 (same canonical per-agent prompt template with the `{agent_role}`
slot set to `"fixer"`, same per-return terminals.jsonl append, same `STOP_PROTOCOL`
rule) but for fixer subagents. Per-agent prompt files are pre-written by the fixer-planner;
each contains the exact files to read, the exact edits to apply, and the issue IDs the
fixer is resolving. The fixer's DONE return is fixer-style (`AGENT_ROLE: fixer` +
`FIXED:` array + `BUBBLED:` array + `EDITED:` + **`EVIDENCE:`**), disambiguated from
reviewer-style by the `AGENT_ROLE` line per `return_contract.md`.

**EVIDENCE field requirement:** Fixers return FIXED + EVIDENCE as a paired set. The
EVIDENCE block is a multi-line subsection, one entry per FIXED id. Each entry maps
the id to a one-line claim of the fixer's work (e.g., "L88 _is_skip rewritten to
defensive substring; verified via Read post-edit"). The shim reads these claims as
evidence before writing the canonical post_review_resolutions[] entries to the
consolidated JSON.

If M=0 (empty `agents: []` from Step 4), skip to Step 6 immediately. No `Agent()`
calls; no terminals.jsonl rows written for this step.

### 6. Dispatch the fixer (CLOSEOUT mode)

```
Agent(
    subagent_type="harness:pr-team-fixer",
    model="sonnet",
    description="Atomic closeout for PR <N>",
    prompt="MODE=CLOSEOUT\nPR_NUMBER=<N>\nREPO=<absolute path>\nRUN_ID=<from step 1>\nRUNTIME_DIR=<state_dir>/pr-team/_runtime/<run_id>\nJSON_PATH=<from step 3>\nFIXER_OUTPUTS=<comma-separated list of output_path values from step 5, or empty if M=0>\nFIX_PLAN_PATH=<from step 4>\nUSER_CLOSED_IDS=<OPTIONAL: comma-separated IDs the user decided to close without action at Step 4.5, or since a prior invocation; omit when the user closed none>"
)
```

The closer validates each named ID is in issues.*[].id AND in bubble_ups.items[].id; orphan or non-bubbled IDs produce a
STOP.

The closer reads the M fixer-output files (validated DONE blocks with `FIXED` and
`EVIDENCE` pairs; FAILs do not produce resolutions), extracts each fixer's per-id
EVIDENCE claims, and composes a `proposed_resolutions.json` sidecar at
`<runtime_dir>/proposed_resolutions.json` containing the proposed
`post_review_resolutions[]` array (one entry per fixer's FIXED id, with evidence
from the per-fixer EVIDENCE claims). Bubble-up ids + FAILed-fixer ids are
enumerated in the closer's DONE block's `BUBBLED:` field as a first-class array
so the user sees them in chat AND the QA pass C4 check reads them directly (no
regex on a TERMINAL string). CLOSED_NO_ACTION entries are composed ONLY when the
user has explicitly named specific IDs via the `USER_CLOSED_IDS` slot above —
collected at the Step 4.5 bubble-up pause this run, or on a re-invocation cycle
(closer validates each named ID is in
`issues.*[].id` AND in `bubble_ups.items[].id`; orphan or non-bubbled IDs
produce a STOP).

**Step 7 (QA pass) then performs a final atomic Edit** to the consolidated JSON,
reading the closer's proposed_resolutions.json sidecar and the per-fixer EVIDENCE
claims to validate them against the file diffs in the consolidated tree, then
appending `post_review_resolutions[]` and recomputing the verdict. This separation
ensures the shim (main session) has an orthogonal verification step before writing
the canonical JSON.

The closer's DONE return is recorded as ONE fixer-style row in terminals.jsonl
with literal `agent_id: "closer"` and `agent_role: "fixer"` (the closer is
dispatched directly by the shim, NOT via `fix_plan.agents[]`, so the agent_id
has no plan-side source — the shim hardcodes the literal `"closer"`). Row
fields per terminals.fixer.schema.json: `agent_id: "closer"`,
`agent_role: "fixer"`, `signal: "DONE"`, `output_path: <proposed_resolutions.json path>`,
`fixed: [<RESOLVED-status ids only>]`, `bubbled: [<unresolved ids: bubble-ups +
fixer-FAILed>]`, `edited: 1` (schema-enforced via conditional allOf), `notes:
<TERMINAL summary line for user>`.

Expected return: a `DONE` block whose `NOTES:` field carries the TERMINAL line
(`Phase 5 [done] | resolved=<R> bubbled=<B> | verdict: <new> |
next: QA`). The `BUBBLED:` array (first-class field, not parsed from NOTES) is
the source of truth for unresolved IDs — the NOTES summary line is for human
display.

On `FORK_AMBIGUITY` / `FORK_BLOCKER`, forward verbatim. The user resolves; on
re-invocation the closer re-reads the JSON to discover what's resolved and resumes.

### 7. Atomic Edit + QA pass (main session, inline)

**Edit step:** The shim reads the closer's `proposed_resolutions.json` sidecar
(from Step 6's closer dispatch). For each proposed resolution, the shim reads the
per-fixer EVIDENCE claims, validates them against the consolidated tree's file diffs
(confirmable via `git diff`), then performs ONE atomic Edit to the consolidated JSON:
inserting `post_review_resolutions[]` (from the closer's proposal) and replacing the
`verdict` field with the recomputed value. The edit goes through `harness_lib.review_edit`
(one `resolve` per proposed entry, then `recompute_verdict`, written once by `save_review`,
which validates and keeps the file's formatting), from the CLI as
`sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/review_edit.py" <JSON_PATH> --recompute resolve <ID> <STATUS> "<text>" [--sha <head>]`;
never an inline `python -c` or a hand edit, and never verdict wording copied from another review.
On a write refusal (schema validation error, READY verdict with undispositioned ids) or
evidence not found in the diff, the shim halts with a STOP rather than continuing
to QA.

**QA step:** After the Edit succeeds, the shim validates the updated consolidated
JSON for two properties:

**Property A — schema correctness.** Run:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_SKILL_DIR}/commands/qa_review_json.py" \
    --json <consolidated-JSON-path> \
    --schema <PR_REVIEW.schema.json: the project's <schemas_dir> copy when pinned, else ${CLAUDE_PLUGIN_ROOT}/schemas/PR_REVIEW.schema.json> \
    --terminals-file <runtime_dir>/terminals.jsonl \
    --dispatch-plan <runtime_dir>/dispatch_plan_review.json \
    --fix-plan <runtime_dir>/dispatch_plan_fix.json
```

Add `--bubble-ups <runtime_dir>/bubble_ups.json` when the fixer-planner wrote one.

Exit code handling:

- **Exit 0** = all checks PASS. Stdout carries `QA_PASS: <run_id> | A=..., B=..., C=..., D=...; all N checks green.`
- **Exit 1** = one or more checks FAIL. Stderr carries one `QA_FAIL: <check_id> <PASS|FAIL>: <diagnostic>` line per
  failed check plus a trailing `RECOVERY:` line.
- **Exit 2** = argv shape error OR input file load failure (missing file, malformed JSON/JSONL). Stderr carries one
  `FATAL:` line. The shim treats exit 2 the same as exit 1 (QA_FAIL surface) — the user-facing diagnostic just names the
  load issue rather than a substantive check failure.

**Property B — consistency with aggregated terminal emissions.** The
`terminals.jsonl` file is written by the shim during Steps 2 and 5 and at the
close of Step 6 — one JSON object per parsed return-contract block, each row
matching `terminals.schema.json`. NOTES is the human-readable summary; BUBBLED/FIXED/EDITED are the structured QA
inputs — never parse NOTES. The QA script cross-checks (the full check list is enumerated in the bullets immediately
below; the qa_review_json.py module docstring documents CLI usage only):

- **A1**: consolidated JSON validates against `PR_REVIEW.schema.json` (top-level
  schema check; failure short-circuits all downstream checks to SKIP).
- **A2**: `verification_log.pre_fix_time` is present and well-formed (Phase 4
  first-run sentinel).
- **A3**: `verdict` field matches the canonical regex prefix
  (`READY TO MERGE` | `NOT READY TO MERGE` | `BLOCKED` | …).
- **A4**: every terminals.jsonl row validates against the union schema at
  `terminals.schema.json` (oneOf reviewer-row / fixer-row, discriminated by
  `agent_role`). Catches missing `agent_role`, wrong-shape DONE rows, etc. at
  source.
- **B1**: every planned reviewer has a terminals entry (DONE or FAIL) with
  `agent_role: "reviewer"`.
- **B2**: each DONE reviewer's `counts.findings` equals its
  `critical + important + minor`, and the sum of reviewer `counts.findings` ≥
  `len(issues.critical) + len(issues.important) + len(issues.minor)` in the
  JSON. Inequality permitted (consolidator may de-duplicate cross-reviewer
  finds); reverse inequality is a FAIL (consolidator invented findings).
- **B3**: per-severity counts in the JSON ≤ summed reviewer per-severity
  counts.
- **C1**: every planned fixer has a terminals entry with `agent_role: "fixer"`.
- **C2**: RESOLVED-status ids in `post_review_resolutions[]` ==
  aggregate `fixed` arrays from fixer DONE blocks (exact equality; bubbled +
  FAILed ids must NOT appear in fixer `fixed`).
- **C2a**: no auto-generated `CLOSED_NO_ACTION` entries (evidence text must
  reflect a user decision, not a fixer bubble/fail).
- **C2b**: closer's `FIXED:` aggregate equals the union of all planned fixers'
  `fixed` arrays (no closer claims a RESOLVED id that no fixer reported as
  FIXED, and vice versa).
- **C3**: orphan-resolution check — every `post_review_resolutions[].id` is a
  member of `issues.*[].id`.
- **C4**: closer's DONE row `bubbled` array (first-class field per
  terminals.fixer.schema.json) equals the bubble_ups sidecar items[].id set.
  Direct field comparison; no regex parsing.
- **C5**: per-id evidence coverage — for every closer FIXED id, the closer
  `evidence` object MUST contain a matching key with a non-empty claim string.
- **D**: verdict prefix matches the verdict re-evaluation rule given the
  current `issues` × `post_review_resolutions` state.

**On QA PASS:** the shim emits the final terminal line verbatim from Step 6 and writes
a `<runtime_dir>/.complete` sentinel. Cleanup of older `_runtime/*` dirs sweeps on
next invocation.

**On QA FAIL:** the shim emits:

```
QA_FAIL: <which check>
DIAGNOSTIC: <one-line from qa_review_json.py stderr>
JSON_PATH: <path>
RECOVERY: inspect the JSON, fix the inconsistency manually, or re-run /harness:pr-team <N>
```

The skill halts. The `.complete` sentinel is NOT written; the runtime dir stays for
forensics.
No `.complete` sentinel is written on exit 2; the runtime dir is retained for forensics, same as exit 1.

**On STOP_PROTOCOL (shim-internal):** if any subagent returns text without a
parseable return-contract block, the shim emits:

```
STOP_PROTOCOL: <agent_id from dispatch plan>
EXPECTED: <one of DONE, FAIL, FORK_AMBIGUITY, FORK_BLOCKER, STOP per the agent's expected_return_signal>
RECEIVED: <one-line excerpt of the malformed return-text tail>
RECOVERY: re-invoke /harness:pr-team <N> from scratch — the agent will be re-dispatched with the same prompt file; persistent failure indicates a prompt-file bug or a model-side issue
```

The skill halts. No row is appended to terminals.jsonl for the STOP_PROTOCOL
return (per Step 2's append rule). The runtime dir is retained for forensics.

---

## Fork-handling protocol

| Return form        | Shim action                                                                                                                                                             |
|--------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `DONE` (any agent) | Parse block, store tuple, proceed to next step.                                                                                                                         |
| `FAIL` (reviewer)  | Carry the gap into Step 3; consolidator handles missing reviewer.                                                                                                       |
| `FAIL` (fixer)     | Issue stays unresolved in `issues.*`; closer adds the id to the bubble_ups sidecar; closer does NOT write a `post_review_resolutions[]` entry. User decides next cycle. |
| `FORK_AMBIGUITY`   | Emit verbatim. Halt. User decides; re-dispatch closer with the choice.                                                                                                  |
| `FORK_BLOCKER`     | Emit verbatim. Halt. User resolves; re-dispatch closer.                                                                                                                 |
| `STOP` (any agent) | Emit verbatim. Halt. Re-entry rules per agent definition.                                                                                                               |
| `STOP_PROTOCOL`    | Shim-internal — agent returned malformed text. Halt; user re-invokes from scratch.                                                                                      |

**Note:** FORK_BLOCKER is emitted by regular fixer subagents only (Step 5 parallel dispatch). The closer (CLOSEOUT-mode)
does NOT emit FORK_BLOCKER or FAIL — it is restricted to DONE / FORK_AMBIGUITY / STOP.

**Do NOT pick between ambiguity options autonomously.** Do NOT silently retry on STOP.
Do NOT auto-resolve `FORK_BLOCKER` by waiting and re-checking — the shim has no
session memory across halts.

---

## Inter-agent hand-off contracts

| Artifact                                                             | Producer                                                                 | Consumer                        | Schema                                            |
|----------------------------------------------------------------------|--------------------------------------------------------------------------|---------------------------------|---------------------------------------------------|
| `<runtime_dir>/dispatch_plan_review.json`                            | shim-orchestrator (PLAN)                                                 | shim → reviewers                | `dispatch_plan.schema.json`                       |
| `<runtime_dir>/prompts/{id}.md` (N files)                            | shim-orchestrator (PLAN)                                                 | reviewer agents                 | freeform markdown — agents' task specs            |
| `<runtime_dir>/outputs/{id}.json` (N files)                          | reviewer agents                                                          | shim-orchestrator (CONSOLIDATE) | freeform (per-reviewer findings; no fixed schema) |
| `<runtime_dir>/terminals.jsonl`                                      | shim (Step 2 + Step 5 + Step 6 closer row)                               | QA script (Step 7)              | one JSON per line: `{agent_id, signal, ...}`      |
| `<artifacts.reviews>/{NNNN}_{Title}.json`                            | shim-orchestrator (CONSOLIDATE)                                          | shim-fixer + user + QA          | `PR_REVIEW.schema.json`                           |
| `<runtime_dir>/dispatch_plan_fix.json`                               | shim-fixer (PLAN)                                                        | shim → fixer subagents          | `dispatch_plan.schema.json`                       |
| `<runtime_dir>/outputs/{id}.json` (M files, fixer-style)             | fixer subagent agents                                                    | shim-fixer (CLOSEOUT)           | freeform (per-fixer log + diff summary)           |
| `post_review_resolutions[]` + recomputed verdict (in PR_REVIEW JSON) | shim-fixer (CLOSEOUT)                                                    | user + QA                       | `PR_REVIEW.schema.json`                           |
| `<state_dir>/pr-review/.phase5_pending_<PR>` (sentinel)              | shim-fixer (Phase 4 2nd run, via `phase4_branch_safety.py --second-run`) | Stop hook                       | n/a (file-existence signal)                       |
| `<runtime_dir>/.complete` (success sentinel)                         | shim (QA PASS)                                                           | next-run cleanup sweep          | n/a (file-existence signal)                       |

**Stale-sentinel manual cleanup** (rare): `rm <state_dir>/pr-review/.phase5_pending_<PR>` for the PR the Stop
hook's stale warning names. Never glob, and never delete a hot sentinel another session armed.
The sentinel lives in `<project>/<state_dir>/pr-review/`, NOT under this skill's runtime tree.
The Stop hook reads that single canonical directory; this skill writes to it intentionally
(shared Phase 5 gate with pr-review). Do not move the sentinel write target.

---

## Return contract

See `return_contract.md`. Every dispatched subagent (reviewer, fixer,
orchestrator-mode, closer-mode) MUST emit the strict block per that document. The
shim's parser is one-pass line-iteration; any deviation produces `STOP_PROTOCOL`.

---

## Pointers to fixtures (referenced, NOT forked)

This skill does NOT ship its own copies of the operational fixtures. Reference the
canonical copies at the paths below; do not duplicate them under this skill's folder.

- `${CLAUDE_PLUGIN_ROOT}/schemas/fixtures/pr-review/rationalization_table.json` — pattern-counter for "I can skip
  this because…" rationalizations
- `${CLAUDE_PLUGIN_ROOT}/schemas/fixtures/pr-review/red_flags.json` — short-form STOP triggers
- `${CLAUDE_PLUGIN_ROOT}/schemas/fixtures/pr-review/troubleshooting.json` — Q&A for branch-state recoveries
- `${CLAUDE_PLUGIN_ROOT}/schemas/catalogs/CrossCuttingLensCatalog.json` — lens trigger commands + scope templates
  (read by shim-orchestrator PLAN mode, merged with the project's `review.lenses` file)
- `pr_review_invocation_test_matrix.schema.json` — schema for JSONL stats (the project's `schemas_dir` copy when
  pinned, else the plugin's `schemas/`; read by shim-orchestrator CONSOLIDATE mode for validate-then-append)
- `<project>/<matrix_path>` — JSONL stats append target
- `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/commands/phase4_branch_safety.py` — Phase 4 gate script (called by both
  orchestrator CONSOLIDATE and fixer PLAN modes)
- `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/commands/to_roast_or_not_to_roast.py` — dice gate for the
  `harness:roast-my-code` reviewer slot
- `PR_REVIEW.schema.json` — canonical PR review JSON schema (project-pinned copy first, else the plugin's)
- the project's exclusions file (`exclusions` in `.claude/harness.json`) — exclusions for the clean-tree check and
  bucket-sort filtering

**To extend** a schema or fixture for one project: pin a copy under the project's `schemas_dir` (the harness
reads a pinned schema before the plugin's) or, for lenses, add them to the project's `review.lenses` file. A
change to the plugin's canonical copies reaches every project that pins nothing.

**This skill's own files** are just the protocol (`SKILL.md`), the dispatch-plan
contract (`dispatch_plan.schema.json`), the bubble-ups sidecar contract (`bubble_ups.schema.json`), the terminals row
contract (`terminals.schema.json`), the return-contract spec (`return_contract.md`),
the QA script (`commands/qa_review_json.py`), and the manifests. Everything else is by
reference.

---

## Runtime directory

`<project>/<state_dir>/pr-team/_runtime/{run_id}/` holds:

- `dispatch_plan_review.json` — Step 1 output
- `dispatch_plan_fix.json` — Step 4 output
- `prompts/{id}.md` — per-agent task-spec files (N reviewers + M fixers)
- `outputs/{id}.json` — per-agent detailed output files
- `terminals.jsonl` — shim-recorded return-contract blocks (Steps 2 + 5)
- `.complete` — written by QA PASS; marks the run as cleanup-eligible

**Keep the runtime tree out of the clean-tree check.** The project git-ignores its
`state_dir` (the default `.claude/state/harness/` belongs in `.gitignore`); a project
that tracks `state_dir` instead lists the pattern `<state_dir>/pr-team/_runtime/**` in
its exclusions file. Without either, Phase 4 first-run AND second-run STOP on the
in-flight runtime files. Verify once on a fresh checkout (`git check-ignore
<state_dir>/pr-team/_runtime/x` exits 0, or the exclusions file carries the pattern).

**Cleanup discipline:** at every shim invocation, sweep `_runtime/*` directories whose
`.complete` sentinel exists AND whose mtime is older than 7 days. Runs without `.complete`
are kept (forensics for failed runs).

---

## Stop recovery

| Halt source             | Re-entry rule                                                                                                                                                                  |
|-------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Step 1 STOP             | Re-invoke skill from scratch (Phase 1 failure means no JSON written yet)                                                                                                       |
| Step 2 STOP_PROTOCOL    | Re-invoke from scratch — malformed agent return invalidates the run                                                                                                            |
| Step 3 STOP             | Re-invoke from scratch (Phase 4 first-run failure means JSON may not exist)                                                                                                    |
| Step 4 STOP             | Re-dispatch shim from Step 4 (orchestrator's JSON is preserved; only fixer-PLAN re-runs)                                                                                       |
| Step 5 FAIL (per agent) | Fixer FAIL ids added to bubble_ups sidecar (classification: fixer_failed); stay UNRESOLVED and surface in closer BUBBLED array for user decision. Skill continues. Not a halt. |
| Step 6 FORK_*           | User decides; re-dispatch shim from Step 6 with choice. Closer re-reads JSON to resume.                                                                                        |
| Step 6 STOP             | Re-dispatch shim from Step 4 (Phase 4 second-run failed mid-fix-loop)                                                                                                          |
| Step 7 QA_FAIL          | Manual JSON inspection; re-invoke skill from scratch only if user wants a fresh run.                                                                                           |

The JSON on disk is the source of truth for state across halts. The shim does not
maintain conversation memory of resolved issues — the closer reads
`post_review_resolutions[]` on re-invocation.
