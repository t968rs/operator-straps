# Bubble memos: skill, script, reviewer and stamping mod

Date: 2026-10-29. Branch: `1095-bubble-memos`.

**Status: draft. Direction approved by the developer 2026-10-29 (builder-check answers folded in below); plan 0001
(`docs/plans/0001_Bubble_memos_ActionPlan.json`) follows from this file.**

## Intent

During a `pr-review`, issues that no fixer may decide are bubbled to the developer. The developer decides them
from a readable memo, not from the review JSON, whose entries are too long to read (developer, 2026-10-29).
Three memos were produced by hand for the floodplain project
(`docs/PR_REVIEWS/PR_1490_Bubbles.md`, `PR_1510_Bubbles.md`, `PR_1514_Bubbles.md` there). This work turns that
into a repeatable capability:

1. A skill the developer can request at any point in a review, usually after Phase 5 once the non-bubble fixes
   have returned.
2. A script that owns the memo's high-level format and proves every currently bubbled issue is in it.
3. A separate reviewer of the finished memo.
4. A mod that stamps each decision into the memo as it is recorded in the review JSON, with no prose written.

## Goals

- A decision-ready memo per PR at `<artifacts.reviews>/PR_<N>_Bubbles.md` (N unpadded, as in the three
  examples; the review JSON is `<NNNN>_<Title>.json`, N padded to four).
- Each entry carries: a brief description; references with `file:line`; **current behavior**; **when the issue
  triggers**; **expected behavior under each proposed fix** (developer's required fields).
- The script guarantees completeness against `bubbles`, and checks mechanically what a script can check.
- Decisions reach the memo without a model turn.
- Memos are snapshots: excluded from review capture and the clean-tree check.

## Non-goals

- Migrating the three existing memos to the new format. The mod skips any memo that lacks the anchors below.
- Memos for pr-team runs beyond what the shared review JSON already supports (the memo reads the consolidated
  review JSON, which both skills write).
- A UI band or any state shown on screen. One toast on a stamp, nothing more.
- Writing decisions into the review JSON. The JSON is the source; the memo follows it.

## Anti-goals (failure even if it technically works)

- A memo that lists resolved issues the developer no longer needs to decide.
- A memo whose line numbers or behavior claims are wrong. A wrong claim sends the developer to the wrong fix.
- A stamp that overwrites the developer's or the drafting agent's prose, or loses an edit made in the same
  moment.
- A plugin file that names a consuming project, or a new harness config key (see Constraints).

## Developer decisions (2026-10-29)

1. **Pin to currently bubbled issues, not `bubble_up`.** `bubble_up` holds every issue ever bubbled; resolved
   ones are not worth a memo entry. "Currently bubbled" is `bubbles` **plus the pending fixer bubbles**: those
   `pr_review.py bubbles` lists (fixer reports not yet in `bubbles`/`bubble_up`), because only `closeout` writes
   fixer bubbles into `bubbles`, and the developer decides at the Step 5 pause, before `closeout`. Class and
   reason of a pending bubble come from its fixer report; with no pr-review run on disk the set is `bubbles`
   alone. An id that already has an entry stays in the memo after it is resolved; the script never regenerates
   over existing entries.
2. **Chain steps and flow diagram are required, not optional,** for critical bubbles (id starts with `C`) and
   for any bubble whose issue references more than one code file.
3. **Stamping is a TypeScript mod,** modelled on `plugins/pr-review-watch`, named `bubble-stamp`. It is not a
   skill step and not part of `closeout`. It is mechanical and scripted.
4. **Triggers:** tool calls plus `turn.complete`. No timer poll.
5. **Reviewer:** a separate reviewer of the finished memo, for accuracy and for semantic clarity and
   simplicity.
6. **Exclusion:** `*_Bubbles.md` joins the default review exclusions.
7. **Format calls, confirmed:** the index is one table with a Status column (`Open` or `Decided`); entries
   never move between sections on a stamp (only the index row and the entry's Decision line change); the stamp
   is final for a row (only rows still `Open` are stamped; a later change to a decision is a hand edit).
8. **Models:** the main session runs on whatever the session uses (Sonnet is enough). Flagged entries
   (decision 2) get one read-only **investigator** agent each, dispatched with `model: opus`. The reviewer's
   model is printed by the script: `opus` when any entry is flagged, else `sonnet`.
9. **Minimal agent context, scripted setup:** a dispatched agent's prompt is only a few header lines (PR, the
   issue id, its file list and one line of issue context). The agent's first action is a script call that
   prints everything else (git facts, files, excerpts, fix options, the record command); its last action is a
   script call that validates and writes a standardized report and prints the return block. Same shape as
   `pr-reviewer` / `pr-fixer`. Git and file discovery are done by the script, never by the agent.

## Author's calls (not yet confirmed by the developer; check these)

- Skill name `harness:bubble-memo`, script `scripts/bubble_memo.py`, library `harness_lib/bubble_memo.py`,
  agents `harness:bubble-memo-investigator` and `harness:bubble-memo-reviewer` (both read-only: Read, Grep,
  Glob, Bash).
- The main session writes the prose of non-flagged entries and every entry's Description and Recommendation;
  investigator facts are applied to flagged entries by a script (`apply`), not retyped.
- One reviewer round. A second round only when the first returned an accuracy finding.
- References are checked against the working tree (uncommitted fix-wave edits included). The header records
  the HEAD SHA and "uncommitted fixes included". Only entries for currently bubbled ids are
  reference-checked.
- A stale id (renamed or merged by `regrade_issue` / `merge_issue_ids`) leaves a stale row: `check` prints a
  `note:` and does not fail, so the skill's "check until clean" loop finishes. The mod counts a memo as active
  while it holds any `Open` row; a stale row costs one `stat` per turn, and the developer settles it by hand.
- Pending fixer bubbles are read through a new library module extracted from `scripts/pr_review.py`
  (`harness_lib/review_bubbles.py`: `fixer_bubbles`, `pending_bubbles`, `closed_ids`), which `pr_review.py`
  imports under the same names.

## Memo format (the contract)

Anchors live in one Python module, `harness_lib/bubble_memo.py`, and are mirrored in the mod. Prose between the
anchors is free.

```
# PR #<N> Bubbles: <title>

- **Scope:** ...            (what the memo covers and which review JSON)
- **Verified against:** branch, SHA, date
- **Sources:** reviewers / run
- **Not bubbled:** one line

## Index

| ID | Class | Status | Decision | Tracked in |
|----|-------|--------|----------|------------|
| I2 | architectural_ambiguity | Open | - | - |

## Entries

### I2. <title>

- **Class:** <classification from bubble_up, else "unclassified">
- **Description:** brief
- **References:** `path/file.py:120-135`, `path/other.py:40`
- **Current behavior:** ...
- **When:** the input condition that triggers it
- **Chain:** (required when flagged)  numbered steps
  ```                                  (flow block, required when flagged)
  ...
  ```
- **Expected behavior per fix:**
    - (a) <fix option> -> <what the code does afterwards>
    - (b) ...
- **Recommendation:** ...
- **Decision:** open
```

- Entry boundary: from its `### <ID>.` heading to the next `### `, `## ` or `---` line.
- Unfilled stubs are written by the script as `TODO(fill)`; `check` fails while any remains.
- **Flagged entries** (Chain and flow required): id starts with `C`, or the review JSON's `file` / `files` name
  more than one distinct path. `check` also flags any entry whose `References` cite more than one distinct
  file, so a second file the JSON missed still demands the chain.
- Expected-behavior sub-bullets: one per entry of the issue's `fix[]` array, in order, so the memo cannot
  silently drop a proposed fix. `check` compares the count.

## Components

### 1. Script: `scripts/bubble_memo.py`

Run through `hpy` like every driver; it calls `activate(load_config(project_root(...)))` once.

| Command | Does |
|---------|------|
| `scaffold --pr N` | Reads the review JSON and the pending fixer bubbles (decision 1). Creates the memo if absent. If present, appends an entry and an index row for each currently bubbled id the memo lacks; never edits existing text. Entries pre-fill what the sources know (title, class, References from `file`/`files`/`lines`, one expected-behavior stub per `fix[]` item, the flag) and mark the rest `TODO(fill)`. Prints the ids it added, which are flagged, and one dispatch row per flagged id (below). |
| `init --pr N --id ID --role investigator` | The investigator's first call. Prints the agent's whole brief to stdout and saves it under the scratch folder: issue text and fix options from the JSON, class and reason, git facts (branch, HEAD, review head and base SHAs, `git status` and a `git diff --stat <review head>` of the referred files), every referred file with its existence and length, line-numbered excerpts around each cited range from the working tree, and the exact `record` command. |
| `record --pr N --id ID --role investigator` | The investigator's last call; the report arrives as JSON on stdin. Validates it (below), refuses a reference whose file or line is not on disk, writes `<artifacts.scratch>/bubble_memo/<PR>/facts/<ID>.json`, and prints the return block. A rerun replaces the report. |
| `apply --pr N` | Writes each recorded facts report into its entry: References, Current behavior, When, Chain, flow block and Expected behavior per fix replace their `TODO(fill)` stubs; Description and Recommendation stay for the main session. Touches only entries whose facts exist and whose stubs remain. |
| `check --pr N` | Exit 0 only when: every currently bubbled id has an entry and an index row; no `TODO(fill)` remains; every flagged entry has Chain and a flow block; each `References` item of such an entry names a file that exists in the tree with the line (or range) inside the file; expected-behavior count equals `fix[]` count; anchors are well-formed. A memo id that is neither bubbled nor decided (renamed or merged id) prints `note:` and does not fail. When clean it prints the reviewer's dispatch row with the model rule of decision 8. Failures print as `<ID>: <what>`. |
| `init ... --role reviewer` and `record ... --role reviewer` | The reviewer's first and last calls, same shape: `init` prints the memo's per-entry table (flagged, references with excerpts, fix options) and the record command; `record` validates `{id, kind, what, suggested}` findings (`kind` is `accuracy` or `clarity`; the id must be in the memo) and writes `findings/<N>.json`. |

**Dispatch rows** copy `pr_review.py capture`: `agent=<type> model=<m>`, then the prompt, which is only
`PR: <N>`, `ISSUE: <ID>` (reviewer: `Memo: <abs path>`), `FILES: <comma-separated repo paths>`, `CONTEXT: <one line:
issue name, class, reason (at most 200 characters)>` and an optional `Developer guidance:` line. The prompt
carries no run header lines, so `pr-review-watch` logs a usage row as a standalone dispatch. Everything else
reaches the agent through `init`.

**Facts report** (investigator `record` input): `{id, current_behavior, when, chain: [step], flow,
references: [{at, note}], fix_effects: [{option, effect}], confidence}`. `fix_effects` has one item per `fix[]`
entry, in order; `references[].at` is `path:line` or `path:start-end`. A malformed report or a reference off
disk exits 1 with `problem:` lines and records nothing.

**Return block:** `record` prints the fenced `---` block with a `SIGNAL:` line that
`skills/pr-team/return_contract.md` defines, so a usage row carries the signal. The agent replies with that
block, verbatim, and nothing else.

Pure parsing and rendering live in the library module; the script only wires files and runs git.

### 2. Skill: `skills/bubble-memo/SKILL.md`

Flow: `scaffold` (nothing currently bubbled: it says so and the skill stops) -> dispatch the printed
investigator rows in one message, one per flagged id (`harness:parallel2` rule) -> `apply` -> the main session
fills the remaining `TODO(fill)` (non-flagged entries in full; Description and Recommendation everywhere) by
reading the code at the cited lines, and records the verified-against header -> `check` until clean ->
dispatch the reviewer row `check` printed -> apply its findings by hand -> `check` again -> hand the path to the
developer. The skill states what to do and why, directly (writing convention); no comparison with other
skills. It takes the `-- <guidance>` tail like every invocable skill; guidance reaches the agents only as the
`Developer guidance:` line.

### 3. Agents: `agents/bubble-memo-investigator.md` and `agents/bubble-memo-reviewer.md`

Both are read-only (Read, Grep, Glob, Bash), carry only generic procedure, and follow `pr-reviewer`'s
structure: read the prompt, run `init` first, work from its output, run `record` exactly once, reply with the
block it printed, stop with `problem:` lines when `init` or `record` fails (three `record` failures). They never
write files, run read-only git only, and use the `hpy` launcher as the brief writes it.

- **Investigator** (one per flagged entry): traces the issue through the cited code and reports the facts
  report above. It does not write memo prose, and does not draft a recommendation.
- **Reviewer** (one per memo): its checks are below.

Reviewer checks:

- **Accuracy:** each reference exists and says what the entry claims; current-behavior and when-triggered
  claims agree with the code at the recorded SHA; each expected-behavior line follows from its fix option; no
  claim contradicts the review JSON.
- **Semantic clarity and simplicity:** ordinary words; one claim per bullet; no term the code does not use;
  nothing repeated across Description, Current behavior and Chain; the recommendation is stated once and
  decisively.

Returns findings through `record` as `{id, kind, what, suggested}`. It edits nothing; the main session applies
the corrections. Because two new agent files exist, `DEFINED_AGENTS` in
`plugins/pr-review-watch/hooks/contract.ts` must list both
(`tests/mods/test_pr_review_watch_usage_contract.py` fails until it does), and their dispatches then log usage
rows like any defined agent.

### 4. Mod: `plugins/bubble-stamp`

Layout and conventions follow `pr-review-watch`: `hooks/hooks.json` -> `register.ts`, `config.ts`
(mirror), `root.ts` and `watch.ts` (project resolution), a pure `memo.ts` (parse and stamp), engine glue in
`stamp.ts`, tests beside each, `README.md`, `.claude-plugin/plugin.json`, `tsconfig.json`.

- **Activation:** only in a project holding `.claude/harness.json`; otherwise every hook passes through. Fails
  open: an unreadable file, malformed JSON or memo, or a refused host call does nothing and never blocks a tool
  call, a turn or a stop.
- **Config mirror:** reads one key, `artifacts.reviews` (default `docs/PR_REVIEWS`), merged over the copy in
  `config.ts`. `tests/mods/test_bubble_stamp_config_mirror.py` pins the copy to `defaults.json`.
- **Active memos:** on `session.start`, and whenever a trigger shows a memo not yet known, list
  `<artifacts.reviews>` for `PR_<N>_Bubbles.md`. A memo is active while its index holds an `Open` row. Each
  active memo maps to its review JSON (newest `<NNNN>_*.json` for N, the `reviewFileFor` rule) and the mtime
  last seen. A memo with no Open row, or without the anchors, is dropped. A stale `Open` row (a renamed id)
  keeps its memo active, at the cost of one `stat` per turn; the developer settles it by hand.
- **Triggers:** (a) `tool.call` on Bash or PowerShell whose command names `pr_review.py` or `review_edit.py`;
  (b) `tool.call` on Edit or Write whose path is an active memo's review JSON; (c) `turn.complete`. Each
  trigger stats each active memo's review JSON and reads it only when the mtime moved. The idle cost is a
  string test per call and one `stat` per active memo per turn.
- **Stamp rule:** for each id whose latest `post_review_resolutions` entry is `RESOLVED` or `CLOSED_NO_ACTION`
  (the `closedOf` rule in `pr-review-watch/hooks/bubbles.ts`) and whose index row is `Open`:
    - index Status becomes `Decided`;
    - Decision cell: `<STATUS> <date>: <evidence>`, evidence verbatim on one line, `|` escaped;
    - Tracked in cell: the first `#<n>` or 7-40 hex SHA found in the evidence, else `-`;
    - the entry's `- **Decision:** open` line becomes `- **Decision:** <STATUS>, <date>. <evidence>`.
  Nothing else in the file changes. A second run changes nothing. `DOWNGRADED_TO_*` entries do not stamp.
- **Write safety:** the memo is re-read immediately before the write; the write happens only when the text
  changed; a memo that exists but cannot be read is never overwritten. One toast names the ids stamped.
- **Contract test:** `tests/mods/test_bubble_stamp_anchors_contract.py` pins the mod's anchor constants (table
  header, status words, Decision line prefix, TODO marker, entry heading pattern) to
  `harness_lib/bubble_memo.py`.

### 5. Exclusion

`plugins/harness/lib/harness_lib/default_exclusions.py` `_entries` gains
`("*_Bubbles.md", "bubble memos (point-in-time snapshots)")`. fnmatch `*` crosses `/`, so the pattern holds
anywhere in the tree. `with_harness_patterns` merges it in memory for projects whose seeded file predates it, and
new seeds include it. Memos under the default reviews folder are already covered by `docs/PR_REVIEWS/*`; the new
row covers a configured reviews folder or memos saved elsewhere.

## Constraints

- **Plugins stay generic:** nothing names a consuming project; the floodplain paths above appear only in this
  spec's intent. `tests/contract/test_no_repo_literals.py` enforces the ban list.
- **No new harness config key.** The memo path derives from `artifacts.reviews`. (A new key would touch
  `defaults.json`, `harness.schema.json`, `config.py` and the README key table together.)
- **Data to the project, code in the plugin:** the script and mod write only the memo under the project.
  `tests/contract/test_root_separation.py` enforces it.
- **Python:** 3.11, `Optional` / `Union`, no first or second person in comments or docstrings, functions under
  50 lines, standard library plus the allowed dependencies only.
- **Hooks:** the mod registers through its own `hooks.json`; the harness `hooks.json` is untouched.
- **Releases:** bump `harness` `plugin.json` (new skill, agent, script); `bubble-stamp` starts at 0.1.0;
  marketplace manifest and root README (mods table, install list; "five TypeScript mods" in `CLAUDE.md` becomes
  six) updated; `docs/PROVENANCE.md` only if anything is imported (nothing is).
- **CI selector:** a module that reads a data file spells its name in a code string literal; new tests name
  their files explicitly, never a directory.

## Files to touch

| File | Why |
|------|-----|
| `plugins/harness/skills/bubble-memo/SKILL.md` (new) | skill |
| `plugins/harness/scripts/bubble_memo.py` (new) | driver |
| `plugins/harness/lib/harness_lib/bubble_memo.py` (new) | anchors, parse, render, checks |
| `plugins/harness/agents/bubble-memo-investigator.md`, `bubble-memo-reviewer.md` (new) | agents |
| `plugins/harness/lib/harness_lib/review_bubbles.py` (new), `plugins/harness/scripts/pr_review.py` | pending fixer bubbles extracted; `pr_review.py` imports them |
| `plugins/harness/lib/harness_lib/default_exclusions.py` | exclusion row |
| `plugins/harness/.claude-plugin/plugin.json` | version bump |
| `plugins/pr-review-watch/hooks/contract.ts` | `DEFINED_AGENTS` gains both agents |
| `plugins/bubble-stamp/**` (new) | mod |
| marketplace manifest, `README.md`, `CLAUDE.md` | register the mod, document it |
| `tests/lib/test_bubble_memo.py`, `tests/scripts/test_bubble_memo_driver.py` (new) | library and driver |
| `tests/lib/test_default_exclusions*.py` (existing file, found by the builder) | new row |
| `tests/mods/test_bubble_stamp_config_mirror.py`, `tests/mods/test_bubble_stamp_anchors_contract.py` (new) | mod contracts |
| `plugins/bubble-stamp/hooks/*.test.ts` (new) | mod behavior |

## Left to the builder

- Exact module split inside the library and the mod, and the CLI flag spelling beyond `--pr`.
- The wording of the skill, the reviewer prompt and the stub text, within the anchors above.
- Whether the main session fans out entry drafting, and above how many bubbles.
- How `check` locates the repo root for reference verification (the project root, as every driver does).
- Where `bubble-stamp` keeps its in-memory map of active memos (state atoms, as `pr-review-watch` does).
