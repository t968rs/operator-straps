# Return Contract for `pr-team` agents

This document defines the strict-format text block that every agent dispatched by the
`pr-team` shim — reviewer, fixer, orchestrator-mode, or closer-mode — MUST emit
as the last thing in its return text.

The format is **deliberately not JSON.** Subagent return text is unstructured by the
harness; embedding JSON inside text creates parser fragility (escape mismatches, partial
truncation, trailing prose). The grammar below is line-oriented, verb-first, and
regex-parseable in one pass.

The contract is designed to be:

- **Model-agnostic.** Every model family can emit it regardless of effort. The format is six fields
  max; no formatting tricks (no tables, no nested markdown, no code-fenced JSON).
- **Effort-agnostic.** Low, medium, high, and xhigh budgets produce the same block — the
  reasoning that produces the values changes, the surface form does not.
- **Forgiving of trailing prose.** Models often want to add a summary after the block;
  the shim parser ignores everything after the closing `---` line.
- **Position-stable.** Fields appear in a fixed order; missing fields are parser errors,
  not silent zeros.

---

## Block structure (canonical)

Every return ends with one block bounded by two `---` lines. The block is
**always at the end of the return text** — any pre-block prose is ignored.

```
---
SIGNAL: <verb>
<verb-specific fields, one per line, KEY: VALUE>
---
```

The leading `---` is the parser's start anchor. The closing `---` is the end. The block
MUST begin in column 1 of its own line; YAML-style indentation is not permitted.

Six verbs are defined. Each verb pins which fields follow. Fields not listed for a verb
must be omitted (extra fields produce a `STOP_PROTOCOL` from the shim).

---

## Verb: `DONE` (reviewer-style)

Emitted by reviewer agents on successful completion of their scoped review.
**Every DONE block MUST include `AGENT_ROLE:` as the second line** — the shim's
parser branches on `AGENT_ROLE` (reviewer-row vs fixer-row schemas have
distinct allowable fields).

```
---
SIGNAL: DONE
AGENT_ROLE: reviewer
COUNTS: findings=<N> critical=<C> important=<I> minor=<M>
OUTPUT: <repo-relative path to detailed findings file>
NOTES: <optional one-line freetext, omit line entirely if none>
---
```

**Field rules:**

- `AGENT_ROLE: reviewer` — literal string. Identifies the row as matching
  `terminals.reviewer.schema.json` (allowable signals: DONE / FAIL / STOP only).
- `COUNTS:` — exact key-value list, space-separated. Order fixed: `findings` → `critical`
  → `important` → `minor`. Non-negative integers only. `findings` MUST equal
  `critical + important + minor` (the shim's QA pass enforces this).
- `OUTPUT:` — one path, no quotes, no surrounding text. Must exist on disk when the
  signal is emitted. Must be inside the run's `runtime_dir/outputs/` per the dispatch
  plan.
- `NOTES:` — optional. If present, one line only. If absent, omit the line entirely
  (no empty `NOTES:`).

**Parser regex:**

```
^SIGNAL: DONE$
^AGENT_ROLE: reviewer$
^COUNTS: findings=(\d+) critical=(\d+) important=(\d+) minor=(\d+)$
^OUTPUT: (.+)$
(^NOTES: (.+)$)?
```

---

## Verb: `DONE` (fixer-style)

Emitted by fixer subagent agents on successful completion of their assigned edits,
AND by the closer agent (CLOSEOUT mode). **Disambiguated from reviewer-style by
`AGENT_ROLE: fixer`** (NOT by presence/absence of fields — the shim parses
`AGENT_ROLE` first and validates the rest of the block against the role's
schema).

```
---
SIGNAL: DONE
AGENT_ROLE: fixer
FIXED: <comma-separated issue IDs the agent successfully resolved, no spaces, e.g. C1,I3,M2>
BUBBLED: <comma-separated issue IDs the agent is bubbling up (mid-batch ambiguity or aggregated unresolved at closer), no spaces; may be empty>
EDITED: <integer count of files edited; >= 1 for individual fixers; == 1 for closer>
OUTPUT: <repo-relative path to fixer log / per-file diff summary>
EVIDENCE:
  <id1>: <one-line evidence claim>
  <id2>: <one-line evidence claim>
  ...
NOTES: <optional one-line freetext, omit line entirely if none>
---
```

**Field rules:**

- `AGENT_ROLE: fixer` — literal string. Identifies the row as matching
  `terminals.fixer.schema.json` (allowable signals: DONE / FAIL / FORK_AMBIGUITY /
  FORK_BLOCKER / STOP).
  **Closer-specific subset:** when `AGENT_ROLE: fixer` AND `agent_id: closer`, only DONE / FORK_AMBIGUITY / STOP are
  valid signals. FAIL and FORK_BLOCKER apply to regular Step 5 fixer subagents only — the closer's atomic Edit must
  succeed, and on Edit failure the closer emits STOP.
- `FIXED:` — comma-separated `[CIM]\d+` IDs the agent successfully resolved.
  Empty allowed (`FIXED:`) only if the agent emits both `FIXED:` and `BUBBLED:`
  empty (no work) — but such a row should have signaled FAIL or FORK_BLOCKER
  instead. For the closer row: aggregate of all fixer DONE rows' FIXED arrays
  (validated RESOLVED-status entries from post_review_resolutions[]).
- `BUBBLED:` — comma-separated `[CIM]\d+` IDs the agent is bubbling up. Disjoint
  from `FIXED`. Individual fixer subagents typically leave this empty
  (`BUBBLED:`). For the closer row: the full set of unresolved IDs from the
  bubble_ups sidecar + any fixer-FAILed IDs.
- `EDITED:` — distinct file count. For individual fixers, MUST be >= 1 (zero =
  should have been FAIL or FORK_BLOCKER). For the closer (agent_id == "closer"),
  MUST be exactly 1 (single file write: the proposed_resolutions.json sidecar).
  The shim owns the atomic Edit to the consolidated JSON in its own Step 7;
  the closer does NOT touch the consolidated JSON directly. Schema
  enforces this via conditional `allOf` on `agent_id`.
- `OUTPUT:` — same path-existence rules as reviewer-style.
- `EVIDENCE:` — multi-line subsection mapping each FIXED id to a one-line evidence
  claim. REQUIRED when `signal == "DONE"` and `FIXED` is non-empty. MUST be omitted
  entirely if `FIXED` is empty. Each line within the block takes the form
  `<id>: <claim>` (indented, no quotes). The evidence claim is the fixer subagent's
  first-person assertion of what was changed (e.g., "L88 _is_skip rewritten to
  defensive substring; verified via Read post-edit").

**Parser regex:**

```
^SIGNAL: DONE$
^AGENT_ROLE: fixer$
^FIXED: ([CIM]\d+(,[CIM]\d+)*)?$
^BUBBLED: ([CIM]\d+(,[CIM]\d+)*)?$
^EDITED: (\d+)$
^OUTPUT: (.+)$
(^EVIDENCE:$
  ^  ([CIM]\d+): (.+)$)+  [only when FIXED is non-empty]
(^NOTES: (.+)$)?
```

**Evidence block semantics:**

The EVIDENCE block is the fixer subagent's claim of work done, one line per FIXED id.
The shim (main session) reads these claims, validates them against the file diff,
and writes the canonical post_review_resolutions[] entries to the consolidated PR_REVIEW
JSON — the fixer subagent does NOT touch the consolidated JSON directly. This
separation gives the shim an orthogonal verification step (fixer claims vs actual
diff).

The shim disambiguates DONE rows by `AGENT_ROLE` first, then validates the
remaining fields against the role's schema (terminals.reviewer.schema.json or
terminals.fixer.schema.json). A row with `SIGNAL: DONE` but no `AGENT_ROLE`
line, or with `AGENT_ROLE` set to a value outside {reviewer, fixer}, produces
`STOP_PROTOCOL`.

---

## Verb: `DONE` (planner-style)

Emitted by **orchestrator-PLAN** and **fixer-PLAN** modes — the two subagent
returns that author dispatch-plan files rather than findings or fixes. Planner
DONE is a stripped variant that omits `COUNTS` (reviewer-style) and
`FIXED`/`BUBBLED`/`EDITED`/`EVIDENCE` (fixer-style); the dispatch plan itself
(referenced via `OUTPUT:`) carries the operative state.

```
---
SIGNAL: DONE
AGENT_ROLE: <reviewer for orchestrator-PLAN; fixer for fixer-PLAN — names the downstream batch role this plan authorizes>
OUTPUT: <runtime_dir>/dispatch_plan_review.json   (or dispatch_plan_fix.json)
NOTES: <one-line summary; e.g. "N reviewers planned across buckets [...]; dispatch_parallel=true" or "M=<n> mechanical fixers, K=<n> bubbled; sentinel armed">
---
```

**Planner-style DONE is NOT recorded to terminals.jsonl.** The shim parses the
block to extract `OUTPUT:` (and ignores the rest) and dispatches the next phase.
The reviewer/fixer return-contract schemas do NOT apply to planner returns —
their absence of COUNTS / FIXED / BUBBLED / EDITED is by design. Validation that
the planner emitted SOMETHING usable is the shim's responsibility (read the
dispatch plan path; validate it against `dispatch_plan.schema.json`).

`AGENT_ROLE` on planner DONE names the **downstream batch role** the plan
authorizes: orchestrator-PLAN authorizes reviewer dispatch (→ AGENT_ROLE:
reviewer); fixer-PLAN authorizes fixer dispatch (→ AGENT_ROLE: fixer).

---

## Verb: `FAIL`

Emitted by any agent that cannot complete its task.

```
---
SIGNAL: FAIL
AGENT_ROLE: <reviewer | fixer>
REASON: <one-line diagnostic>
PARTIAL_OUTPUT: <optional path to whatever was written before failure, omit if none>
---
```

**Field rules:**

- `REASON:` — one line, ≤ 200 chars. Stack traces, multi-line error messages, etc. go
  in `PARTIAL_OUTPUT`; the signal-line stays terse.
- `PARTIAL_OUTPUT:` — optional. If omitted, the shim treats the run as zero-output.

The shim's response to `FAIL` is role-specific: a failed reviewer means one fewer
data point for the consolidator (consolidator handles the gap); a failed fixer
means the issue stays in the bubbled set (closer adds the FAILed fixer's
assigned IDs to the bubble_ups sidecar and they appear in the closer DONE row's
`BUBBLED:` array — they do NOT auto-resolve to `CLOSED_NO_ACTION`).

**FAIL blocks should ALSO include `AGENT_ROLE:` as the second line** — same
parser-dispatch reason as DONE blocks. Reviewer FAIL → `AGENT_ROLE: reviewer`;
Fixer FAIL → `AGENT_ROLE: fixer`.

---

## Verb: `FORK_AMBIGUITY`

Emitted by fixer-mode agents (closer or individual fixer subagents) when an issue is real
but the resolution has two reasonable options. The agent must NOT pick autonomously;
this verb is the escape hatch. Reviewers MUST NOT emit FORK_AMBIGUITY — they have no
design-fork authority (terminals.reviewer.schema.json rejects the verb).

```
---
SIGNAL: FORK_AMBIGUITY
AGENT_ROLE: fixer
ISSUE_ID: <single issue ID, e.g. C1>
ISSUE_DESCRIPTION: <one-line problem statement>
OPTION_A: <one-line description of option A>
OPTION_B: <one-line description of option B>
OPTION_C: <optional third option, omit line entirely if only two>
---
```

**Field rules:**

- `AGENT_ROLE: fixer` — literal. Reviewers cannot emit this verb.
- `ISSUE_DESCRIPTION:` — named `ISSUE_DESCRIPTION` (NOT `DESCRIPTION`) to avoid
  colliding with the JSON-Schema reserved meta-keyword. The row-data field is
  `issue_description` per terminals.common.schema.json.
- Exactly two or three options. One option = not actually a fork (pick it). Four+
  options = scope it down to top 2-3.
- The shim forwards the entire block verbatim to the user. The user picks (or adds a
  fourth path); the shim re-dispatches the fixer with the choice as additional
  prompt input.

---

## Verb: `FORK_BLOCKER`

Emitted by fixer-mode agents when an issue cannot be resolved without external action
(test infrastructure missing, conflict in the base branch, dependency on a separate PR).
Reviewers MUST NOT emit FORK_BLOCKER (same reason as FORK_AMBIGUITY).

```
---
SIGNAL: FORK_BLOCKER
AGENT_ROLE: fixer
ISSUE_ID: <single issue ID>
ISSUE_DESCRIPTION: <one-line problem statement>
EXTERNAL_ACTION_NEEDED: <one-line description of what must happen outside the skill>
---
```

**Field rules:**

- `AGENT_ROLE: fixer` — literal. Reviewers cannot emit this verb.
- `ISSUE_DESCRIPTION:` — same renaming rationale as FORK_AMBIGUITY.

The shim forwards verbatim. The user resolves out-of-band; on re-invocation the fixer
re-reads the JSON to discover what's already resolved.

---

## Verb: `STOP`

Emitted by any agent when a Phase 1, 3, 4 (first or second run), or 5 check fails in a
way that halts the entire skill. Distinct from `FAIL` (single-agent failure) — `STOP`
means the shim must halt and surface a recovery action.

```
---
SIGNAL: STOP
AGENT_ROLE: <reviewer | fixer>
PHASE: <phase>.<check>
DIAGNOSTIC: <one-line>
RECOVERY: <one-line command or action the user runs to unblock>
---
```

**Field rules:**

- `AGENT_ROLE:` — literal `reviewer` or `fixer` per the emitting agent class.
  Required so the row validates against the correct role schema.
- `PHASE:` — dotted-path identifier (e.g. `phase1.check1`, `phase4_second.check3`).
  See agent docs for the canonical phase/check names.
- `RECOVERY:` — must be actionable. "Check the logs" is not acceptable;
  "Run `git checkout 1046-feature-branch` then re-invoke `/harness:pr-team 1122`"
  is.

The shim forwards verbatim. Re-entry rules are phase-specific (see SKILL.md).

---

## Shim-internal Signaling (Not Emitted by Agents)

The signals in this section are emitted by the shim (main session) when parsing fails or
protocol violations occur. **Agents NEVER emit these directly.** They appear in shim-side
error reports and may be recorded in terminals.jsonl by the shim itself, but are not part
of the agent return contract.

### `STOP_PROTOCOL`

Emitted by the shim itself when an agent's return text violates this contract (missing
block, wrong verb, malformed field). Documented here for completeness; agents must never
emit it.

```
---
SIGNAL: STOP_PROTOCOL
AGENT_ID: <id from dispatch plan>
EXPECTED: <one of: DONE, FAIL, FORK_*, STOP>
RECEIVED: <one-line excerpt of what was actually returned>
RECOVERY: re-invoke `/harness:pr-team <PR>` (forces a fresh run; the malformed agent
          will be re-dispatched with the same prompt file)
---
```

---

## Composition example (a 4-reviewer parallel dispatch)

The shim dispatches 4 reviewers in parallel; each returns one block at the end of its
text. The shim collects 4 blocks; from each it extracts `(signal, counts, output_path)`;
forwards the 4 `output_path` values to the consolidator agent (which reads them in its
own context).

```
# Reviewer R1 return text (abbreviated, prose elided)
... (reviewer's analysis text, ignored by shim parser) ...
---
SIGNAL: DONE
AGENT_ROLE: reviewer
COUNTS: findings=7 critical=0 important=4 minor=3
OUTPUT: .claude/state/harness/pr-team/_runtime/pr1122_20260518T060416Z/outputs/r1_config.json
NOTES: 7 strengths recorded; $id collision is the only schema-level concern
---

# Reviewer R3 return text (abbreviated)
... (large reviewer analysis) ...
---
SIGNAL: DONE
AGENT_ROLE: reviewer
COUNTS: findings=15 critical=3 important=6 minor=6
OUTPUT: .claude/state/harness/pr-team/_runtime/pr1122_20260518T060416Z/outputs/r3_overall.json
---

# Closer DONE return text (Step 6 CLOSEOUT)
---
SIGNAL: DONE
AGENT_ROLE: fixer
FIXED: I5,I6,I7,I9,I12,M3,M4,M14,M19,M20,M21
BUBBLED: C1,C2,C3,I1,I8,I10,I11,I13,I16,I18,I20,I21,I22,M5,M6,M7,M8,M16,M23
EDITED: 1
OUTPUT: <artifacts.reviews>/1122_SKILL_pr-team.json
NOTES: TERMINAL: Phase 5 [done] | resolved=30 bubbled=19 | verdict: NOT READY TO MERGE | next: QA
---
```

**Rule:** NOTES is the human-readable summary; BUBBLED/FIXED/EDITED are the structured QA inputs — never parse NOTES.

The shim parses these blocks WITHOUT loading the analysis text into its context. It
hands `[r1.json, r2.json, r3.json, r4.json]` to the consolidator subagent.

---

## Why this grammar (design notes)

- **Verb-first.** Parser branches on `SIGNAL:` line first; field set is verb-determined.
  No conditional field interpretation ("if X is present, treat Y differently").
- **Key-value with `:` separator.** Lowest common denominator across model formatting
  preferences. Low-effort dispatches reliably produce it; high-effort dispatches don't dress it up.
- **No nested structures.** Counts are a flat space-separated KV list, not a sub-object.
  Low-effort dispatches occasionally struggle with nested JSON-in-text; flat KV is reliable.
- **Path-only, never content.** `OUTPUT:` is always a path; the shim NEVER reads the
  path's content. The consolidator/closer reads it from inside its own subagent context.
- **`---` boundaries.** Markdown thematic break, recognized across model families as a
  section delimiter. Reliable as anchor.
- **No timestamps in the block.** The dispatch plan's `run_id` is the canonical time
  anchor; per-agent timestamps would drift and don't help the shim parse.
