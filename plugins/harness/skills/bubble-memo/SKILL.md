---
name: bubble-memo
description: Use when a PR review has bubbled issues that only the developer may decide and they need a readable decision memo, usually after the non-bubble fixes of Phase 5 have returned. Triggers on "bubble memo", "memo the bubbles", "write up the bubbles", "bubble-memo".
argument-hint: "<PR number> [-- <guidance>]"
---

# bubble-memo: a decision memo for the bubbled issues

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. Before
it: the PR number. After it: guidance for this run (an entry to look at hard, a file to read, a wording
preference). The session applies it to its own writing, and it rides on each agent dispatch as the last line of
the prompt, `Developer guidance:` followed by the guidance verbatim with newlines folded to spaces. It never
reaches a command: no command below carries the guidance.

A bubbled issue is one no fixer may decide. The developer decides it from the memo
`<artifacts.reviews>/PR_<N>_Bubbles.md`, so each entry must be accurate and short enough to read: a wrong line
number or a wrong behavior claim sends the developer to the wrong fix. The driver owns the memo's format and
proves that every currently bubbled issue has an entry; this skill supplies the prose and the dispatches.

Every command below is written out in full and runs with the Bash tool from the project checkout. Every defect
is a `problem:` line and exit 1, and `note:` lines never fail a run.

## Rules

- **The memo is a point-in-time snapshot** (the snapshot rule). It reads the review JSON as it stands now,
  keeps an entry after its issue is resolved, and is never regenerated over existing text. A later change of
  the review or the code does not rewrite it.
- **References are checked against the working tree**, uncommitted fix-wave edits included. The header records
  the HEAD SHA and says so.
- **The session writes prose; the driver and the agents write facts.** The session writes every entry's
  Description and Recommendation and the whole of each non-flagged entry. An investigator's recorded facts reach
  a flagged entry through `apply`, never retyped.
- **Decision stamping is not this skill's job.** The `bubble-stamp` mod stamps each decision into the memo as it
  is recorded in the review JSON. Never write a decision into the memo, and never edit a `Decision` line or an
  index `Status` cell.
- **An agent prompt is only the lines a printed row carries.** Add the row's `Developer guidance:` line when
  the invocation carried guidance, and nothing else: the agent's `init` call returns the rest.

## Steps

1. **Scaffold.**

   ```
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/bubble_memo.py" scaffold --pr <N>
   ```

   It reads the review JSON of PR `<N>` and the fixer bubbles not yet closed out, creates the memo or appends
   the entries and index rows it lacks, and prints the memo path, the ids added, the flagged ids and one
   investigator row per flagged id it just added. A rerun prints rows only for entries it adds, so it cannot
   replay a dispatch; to redispatch an investigator, reuse the row already printed. Flagged entries (a critical
   id, or an issue that touches more than one code file) need a chain of steps and a flow block. When it prints
   `nothing currently bubbled`, tell the developer so and stop: no memo is written. When a
   `PR_<N>_Bubbles.md` from an earlier run is on disk, name its path: the snapshot rule keeps it as it is.

2. **Dispatch the investigators** (`harness:bubble-memo-investigator`, one per row). The printed rows already satisfy `harness:parallel2`: the agents are
   read-only with a fixed tool set, and their entries are independent. Load no sub-skill. A row is a block of
   lines separated from the next by a blank line: its first line is `agent=<type> model=<model>`, and the lines
   after it are the prompt. Make one call per row, all in one message, so the agents run in parallel:

   `Agent(subagent_type=<agent>, model=<model>, prompt=<the lines after the agent= line>)`

   The `agent=` line itself is not part of the prompt. The model is the one printed on that line; never
   substitute another. Each reply is a return block; read the facts report at its `OUTPUT:` path (relative to
   the project root) when the facts need a look, since the session never sees the agent's brief. A reply with
   no `SIGNAL:` line is a failed run: redispatch that row once. When it fails again, stop filling that entry,
   finish the rest, and in the hand-off give the memo path, the failed ids and the agent's `problem:` lines,
   and say the memo is not clean.

3. **Apply the facts.**

   ```
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/bubble_memo.py" apply --pr <N>
   ```

   It writes each recorded report into its entry over the `TODO(fill)` stubs: References, Current behavior,
   When, Chain, the flow block and the expected behavior per fix. It touches only entries whose facts exist and
   whose stubs remain. The scaffold's pre-filled References give way to the verified ones only while the
   entry's other fact stubs remain, so a rerun of `apply` keeps a References line corrected by hand.

4. **Fill what remains.** Read the memo, then every `TODO(fill)` left in it:
   - **Non-flagged entries, in full:** open the code at the cited lines and write Current behavior, When
     (the input condition that triggers the issue), one expected-behavior line per proposed fix, in the fix
     order, saying what the code does afterwards, and References.
   - **References, everywhere:** each is a backticked span, such as `src/a.py:120-135`, with the path relative
     to the project root; `check` and the reviewer read only backticked spans. The scaffold pre-fills
     References from the review JSON's file and lines at the review head: confirm each against the working
     tree and correct any that moved.
   - **A second file in a non-flagged entry** makes it need a Chain. Write the field in the layout the scaffold
     uses for flagged entries: a `- **Chain:**` line, the steps numbered and indented by two spaces beneath it,
     then a flow block fenced by two lines of two spaces and three backticks, its lines indented by two
     spaces. Write it from the code, and say in the hand-off that the session wrote that chain.
   - **Every entry:** Description (a brief statement of the issue) and Recommendation (one decisive choice
     among the fixes, stated once).
   - **The header:** replace the Verified-against stub with the branch, the HEAD SHA from
     `git -C "<project root>" rev-parse HEAD`, the date and the words `uncommitted fixes included`; fill
     Sources (the reviewers or the run the issues came from) and Not bubbled (one line on what the memo leaves
     out).

   Ordinary words, one claim per bullet, no term the code does not use, nothing repeated across Description,
   Current behavior and Chain. Every claim comes from code read at the cited lines: a line that could not be
   confirmed is left out or marked as unconfirmed, never guessed.

5. **Check until clean.**

   ```
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/bubble_memo.py" check --pr <N>
   ```

   It fails with one `<ID>: <what>` line per defect: a missing entry or index row, a remaining stub, a flagged
   entry without a chain or flow block, a reference off disk or outside the file, an expected-behavior count
   that differs from the fix count. Fix each in the memo and run it again. A `note:` line (an id that is no
   longer bubbled, renamed or merged) does not fail the run; mention it to the developer in the hand-off. When
   it is clean it prints `check [ok]` and one reviewer row.

6. **Dispatch the reviewer.** Dispatch the printed reviewer row as in step 2, with one call to
   `harness:bubble-memo-reviewer`: the model printed on its `agent=` line, the lines after it as the prompt,
   and the guidance line when the invocation carried guidance. It reads the memo for accuracy and for clarity
   and simplicity, edits nothing and returns findings as `{id, kind, what, suggested}`; read them at the
   reply's `OUTPUT:` path.

7. **Apply the findings by hand.** Open each finding's location in the memo and make the correction, after
   checking the claim against the code: a finding is evidence to weigh, not an order. Run `check` again until
   it is clean. This is one reviewer round. Run a second round, a fresh dispatch of the reviewer row `check`
   prints, only when the first returned an `accuracy` finding; `clarity` findings alone end the review.

8. **Hand off.** Give the developer the memo path, the count of entries and how many are flagged, any `note:`
   lines, any chain the session wrote, and the findings that were left unapplied with the reason. The memo is
   final for this run: the developer decides from it, and `bubble-stamp` records each decision as the review
   JSON gains it.

## Related

- `${CLAUDE_PLUGIN_ROOT}/scripts/bubble_memo.py`: the driver; `--help` on each subcommand lists its options.
- `${CLAUDE_PLUGIN_ROOT}/agents/bubble-memo-investigator.md` and `bubble-memo-reviewer.md`: the two agents.
- `harness:parallel2`: the dispatch rule the printed rows already satisfy.
