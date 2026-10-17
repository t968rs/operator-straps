# PR Review Operating Rules

Standing developer rules for `pr-review` runs in this repo. `pr-team` follows every section except "Phase 5 flow",
whose dispatch order its own Step 4.5 defines. `pr-team` does not run `pr_review.py`: it writes resolutions and the
`bubble_up` ledger only through `scripts/review_edit.py <JSON> resolve-file ... --bubble-ups ...` at its Step 7 (its
bubbles live in the `<runtime_dir>/bubble_ups.json` sidecar until then), and uses other `review_edit.py`
subcommands only for the fields the "Review JSON fields" section lists as uncovered; rules naming `fold`, `waves`,
`build`, `bubble`, `amend` or `closeout` do not apply to it.
Where a rule here names a step order, it overrides the literal order in `pr-review/SKILL.md`.

## Review JSON fields

- **`bubbles`** (root) is TRANSIENT: issue IDs currently awaiting a developer decision. `closeout` removes an ID once
  it is decided (resolved, closed or deferred); the developer may also curate this array by hand and reads only it; a
  chat list of "items awaiting input" that differs from `bubbles` is a defect.
- **`bubble_up`** (root) is a PERMANENT ledger of every issue ever bubbled. An item stays after it resolves. Shape:
  `{id, classification, reason}`.
- **No `follow_ups` field exists.** Net-new deferred work is a `bubble_up` entry with `classification:
  needs_follow_up`. The schema root has no extra-property slot.
- **`post_review_resolutions[]`** gets an entry only after closure: a fix landed AND validated (`RESOLVED`), or the
  developer explicitly closed it (`CLOSED_NO_ACTION`). Bubbled items, FAILed fixers and skipped items get no entry.
  A fixer's DONE block is a claim; `closeout` validates it (every file the entry lists changed since `build_head` and
  lies in that fixer's file set or is new) and writes the entry. A fixer resolves only the ids its planned parts
  assign it; a split issue resolves only when its fixers' entries together cover every planned part.
- **Developer-directed work outside the fixer waves** (a fix the developer asked the main session for) is
  `RESOLVED` through `closeout --resolved ID="what changed"`, never through a hand-written fixer report. One of the
  issue's files (primary + `also`) must have changed since `build_head`; evidence reads `<HEAD short sha>
  (working-tree snapshot; developer commits) - <what> (outside fixer waves)`. Use it only for developer-directed
  work; planned fixes resolve through their fixer reports.
- **A developer-confirmed defer** (usually tracked by a GH issue) is `RESOLVED` for this PR, with evidence naming the
  decision and the tracker, plus its `bubble_up` entry: `closeout --deferred ID="decision; tracker"` writes both. An
  unconfirmed defer stays bubbled. `CLOSED_NO_ACTION` means
  no action at all (intended behavior, or superseded by the developer's own work).
- **Status enum:** `RESOLVED`, `DOWNGRADED_TO_MINOR`, `DOWNGRADED_TO_IMPORTANT`, `CLOSED_NO_ACTION`. Put framing
  such as "pushed back" in `evidence`, never in `status`.
- **Evidence must START with a SHA** (`^[0-9a-f]{7,40}( |$)`) for the Phase 5 sentinel to clear. `closeout`
  generates `<HEAD short sha> (working-tree snapshot; developer commits) - <what changed>`; a hand-written entry
  follows the same form.
- **The verdict is derived, never typed.** `build`, `bubble` and `closeout` recompute it with one function aligned
  with the hook's issue-count check: unresolved critical, else unresolved important, else any undispositioned id
  (`NOT READY TO MERGE - minor findings pending Phase 5: ...`), else `READY TO MERGE - <R> of <T> findings resolved,
  <B> bubbled`. One override sits outside that function: when the Phase 4 first run fails inside `build`, the review
  is still written, but a READY verdict becomes `NOT READY TO MERGE - Phase 4 first run failed: <reason>` and
  `build` exits 1. After a hand edit by the developer, the next script write recomputes it.
- **JSON string values that describe `"` or `\`** (mojibake, shell quoting, regex) use escape-sequence text, never the
  rendered glyph. The agent never hand-edits the review JSON. In `pr-review`, every agent write goes through a
  `pr_review.py` subcommand, which validates the whole document before replacing it, and resolutions, defers,
  bubbles, regrades and merges always go through `closeout`, `bubble` and `amend`, which check the evidence and
  write the verdict; in `pr-team` they go through `review_edit.py resolve-file` alone (see the top of this file).
  An edit no subcommand covers (a reviewer, a strength, `shas`, `review-date`, `stats`) goes through
  `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/review_edit.py" <review JSON> --recompute
  <subcommand> ...` (`harness_lib.review_edit`: one editor per root field, validated byte-stable write), never
  `python -c`. The agent never runs its `verdict --text`, and runs `resolve-file` only as the `pr-team` shim's
  closeout step; any other field (PR title, issue text, verification log) is surfaced to the developer.
- **Folder glob:** only true PR reviews live at the top of the project's review directory (`artifacts.reviews`
  in `.claude/harness.json`) as `NNNN_*.json`. Audits and notes use a subfolder or a non-digit prefix
  (`AUDIT_NNNN_*.json`).
- When unsure how to record a disposition, read the field descriptions in `PR_REVIEW.schema.json` (the project's
  pinned copy under its `schemas_dir`, else `${CLAUDE_PLUGIN_ROOT}/schemas/PR_REVIEW.schema.json`) before writing.

## Folding outside reviews

- **Every outside review goes through `fold`:** an external reviewer (`--from-gh-review <URL>`),
  test results, the developer, or ad-hoc feedback (`--findings <FILE>` or `-`), each under its own snake_case
  `--source` and the matching `--kind`. Folded findings are validated by the same Finding model reviewers use and
  merge like a slot; never paste outside findings into the draft or the review JSON by hand.
- **Regrade after folding (folds before `build`).** A GitHub review's comments arrive at one `--severity`
  (default `minor`); grade each by blast radius with `amend --regrade` after `merge`.
- **Grade before a post-build fold.** After `build`, `amend` does not run, so the fold's severity is final. When
  the comments differ in blast radius, convert the review to a `--findings` file with a per-finding `severity`;
  otherwise pass the matching `--severity`. A comment reporting a critical or important defect never lands at the
  default `minor`.
- **Fold after `merge` means `merge` again** (`--force` when amended); `build` refuses a draft missing a folded
  source.
- **Fold after `build` appends, at any point of Phase 5:** the source's issues join the review with fresh ids
  (per severity, after the highest existing; nothing renumbers, nothing auto-merges, `amend` does not run, so
  regrades are out and merge candidates are only a printed note), the verdict is recomputed and the phase stays
  `fix-plan` / `fix` inside an open pass, else becomes `consolidate` (so back-to-back folds after a closeout all
  name the second run). A review whose Phase 4 first run failed refuses the fold until `build --replace` lands.
  After a completed closeout, re-enter Phase 5 at the Phase 4 second run (re-arms the sentinel),
  `waves` for the new ids, `closeout`. Mid-pass (a Phase 5 pass still open, sentinel armed, tree holding that
  pass's fixes) the second run is skipped: the next step is `waves` for the new ids, then `closeout`.
  A source already in the built review is never re-folded; new findings take a new `--source` id.

## Phase 5 flow

- **Bubble only genuine decisions** (architectural ambiguity, behavior intent, domain calls). Fix every mechanical
  finding directly: docstrings, dead branches, renames, unused vars, registry `added_in_pr`.
- **Repo-answerable questions are not bubbles.** If a reason reads "depends on whether X", investigate X (or dispatch
  a subagent to), then resolve.
- **Dispatch first, ask second.** After the Phase 4 second run and the bubble audit, dispatch the planned waves for
  every non-bubbled issue with no confirmation pause, then surface bubbles. `waves` holds every id in `bubbles`; fold
  bubble answers into a follow-up wave with `waves --ids <ids>`.
- **Waves come from `waves`, sized by unit count.** A mechanical multi-file issue splits into one single-file part per
  file (parts of one issue may sit in different fixers of a wave); a judgment multi-file issue stays whole over
  primary + `also`, with one owner, placed first. At most 6 units (whole issues or parts) per fixer (a file with more
  splits into chunks), fixers file-disjoint within a wave over the files they own, later waves dispatched only after
  the earlier one returns, `haiku` only when every issue is `fix_kind: mechanical`. Each fixer's file set also
  holds the registered tests targeting its issues' files and the existing paths their `fix` options name, so tests
  and docs a fix requires stay inside the fixer. Tests over the `tests.fixer_test_seconds` ceiling or matching a
  `tests.defer_flags` path are listed as deferred: editable, never run by a fixer, printed by `closeout`. Never
  hand-split a plan or hand-write a fixer prompt. A bare `waves` re-plan skips ids already covered by fixer reports of the run and plans
  only the missing parts of a partially fixed split issue; after a closeout, only entries closeout accepted count.
- **Bubbles and closeout go through the script.** `bubble <ID> --classification <C> --reason <R>` adds to `bubbles`
  and `bubble_up`; `closeout [--closed ID="rationale" ...] [--resolved ID="what" ...]` writes resolutions, fixer
  bubbles and the verdict. Both validate before writing and run the hook after.
- **Latest-message authority.** Workflow and fix-wave subagents treat only the newest user message as consent. If any
  user message arrived after an approval, plan the items approved in the older message in their own `waves --ids
  <ids>` follow-up wave; never apply them inline or hand-write a fixer prompt. Never bundle items approved in
  different user messages into one wave.
- **The developer may edit the review JSON concurrently.** Every `pr_review.py` write re-reads the file first and
  recomputes the verdict, so the agent runs the next subcommand and never edits the file by hand.

## Phase 4 branch checks

- **Remote/local head desync is waived.** The developer amends and pushes later, so the remote PR head lagging local
  HEAD (`head_ancestor` failing) is not a STOP. Still required: correct branch name, no unrelated load-bearing edits,
  and an intact merge base with the PR's base branch (`base_ancestor_exit == 0`). A base-ancestry failure IS a STOP. The first run
  applies the waiver through `build --waive-head-ancestry` (recorded in `plan.json`); a waived second run arms no
  sentinel.
- The invariant that matters is that parallel fixers stay in sync with the working branch: each owns a strictly
  non-overlapping file set.

## Sentinel

- The Phase 5 sentinel `<project>/<state_dir>/pr-review/.phase5_pending_<PR>` (`state_dir` from
  `.claude/harness.json`) is a dotfile; check it with `ls -la`, not `ls | grep`.
- Script writes (`build`, `bubble`, `closeout`) run the hook themselves. If the sentinel survives a valid closeout,
  run the plugin's schema hook from the project checkout:

  ```bash
  sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/hooks/validate_pr_json_schema.py" <<'EOF'
  {"tool_name":"Edit","cwd":"<abs project root>","tool_input":{"file_path":"<abs path to the review NNNN_*.json>"}}
  EOF
  ```

- Never delete a sentinel by hand to get past a Stop block. A sentinel for a PR the current session is not reviewing
  is out of scope: leave the file alone and ask.

## Grading and verifying findings

- **Re-grade reviewer severity by blast radius** with `amend --regrade <ID>=<severity>` before `build`. Count the
  callers the contract change reaches. A "minor" label on a return-type, annotation-widening or raises-vs-returns
  change with more than ~5 callers is almost never minor.
- **A docstring cited as evidence is a claim, not a fact.** Probe the runtime the docstring describes before fixing.
  After any test edit, run the test before recording `RESOLVED`.
- **"Dead code" findings need proof.** Grep the project's test roots (`tests.roots`), including tests that only run
  in a local or licensed environment (they read as zero callers in a plain grep of CI-run tests), and treat
  intentionally broad API surface as a bubble, not an auto-fix.
- **Machine-generated artifacts** listed in the project's exclusions file (`exclusions` in `.claude/harness.json`)
  are never review subjects (`capture` scopes no slot to them). Close any finding about them `CLOSED_NO_ACTION` via
  `closeout --closed`.

## External review threads

- Do not reply in threads opened by bot reviewers (`[bot]` in `user.login`); verify, fix, move on. Human threads still
  get replies.
