# PR #202 Bubbles: Feature(bubble-memo): run the memo reviewer only on request

- **Scope:** Issues bubbled for decision in the review of PR #202, review file docs/PR_REVIEWS/0202_Featurebubble-memo_run_the_memo_reviewer_only_on_request.json, head 514d096.
- **Verified against:** branch 1121-bubble-memo-pruning, HEAD 514d096994a73d03e7fe531b866bebf3fdab57d8, 2026-11-03, uncommitted fixes included.
- **Sources:** review run pr202_20261103T235750Z: reviewers tests, runtime, docs and roast.
- **Not bubbled:** nothing. All seven issues of the review are bubbled at the developer's direction, though each has a known fix.

## Index

| ID | Class | Status | Decision | Tracked in |
|----|-------|--------|----------|------------|
| I1 | architectural_ambiguity | Decided | RESOLVED 2026-11-03: 514d096 (working-tree snapshot; developer commits) - Snapshot rule now allows two changes after hand-off (a decision stamp, cross-referenced by the rule's name instead of 'next rule', and corrections from a requested review, section "On request"); On request states its timing: between steps 5 and 6 when the invocation asks, otherwise after hand-off with a short follow-up. bubble-memo-reviewer.md: its after-hand-off example is now permitted by the rule, no edit needed. | - |
| I2 | architectural_ambiguity | Decided | RESOLVED 2026-11-03: 514d096 (working-tree snapshot; developer commits) - test_the_memo_stays_a_snapshot_apart_from_decision_stamps now extracts the snapshot-rule bullet and asserts 'after hand-off', 'decision stamp' and 'On request' inside it, replacing the body-wide substring checks. SKILL.md: the clause it pins was written under I1, no further edit. | - |
| M1 | architectural_ambiguity | Decided | RESOLVED 2026-11-03: 514d096 (working-tree snapshot; developer commits) - Agent description line 10 now names `bubble_memo.py check --reviewer-row` as the row source, matching the example at line 13.; no edit in this part: plugins/harness/scripts/bubble_memo.py cmd_check already prints the reviewer row only under --reviewer-row (bubble_memo.py:511-512); the stale sentence at plugins/harness/agents/bubble-memo-reviewer.md:10 is the other part's edit | - |
| M2 | architectural_ambiguity | Decided | RESOLVED 2026-11-03: 514d096 (working-tree snapshot; developer commits) - Step 5 now runs section "On request" before the hand-off when the invocation asked for a review; On request reruns `check` without `--reviewer-row` (the step 5 command) and reports unapplied findings to the developer, in the hand-off only when the review ran in the same invocation. | - |
| M3 | architectural_ambiguity | Decided | RESOLVED 2026-11-03: 514d096 (working-tree snapshot; developer commits) - test_a_failing_check_prints_no_reviewer_row_even_on_request now also asserts "Memo:" not in out (tests/scripts/test_bubble_memo_driver.py:176), matching the default-path test at line 161 | - |
| M4 | architectural_ambiguity | Decided | RESOLVED 2026-11-03: 514d096 (working-tree snapshot; developer commits) - restored the space around '=' in the chain assignment (tests/scripts/test_bubble_memo_driver.py:275) | - |
| M5 | architectural_ambiguity | Decided | RESOLVED 2026-11-03: 514d096 (working-tree snapshot; developer commits) - _split_steps asserts the Steps and On request headings are present before splitting, so a missing section fails with a named message instead of an unpack or index error. | - |

## Entries

### I1. Snapshot rule says a decision stamp is the only change after hand-off; On request edits the memo after hand-off

- **Class:** architectural_ambiguity
- **Description:** The snapshot rule allows only a decision stamp after hand-off, but the On request section tells the session to correct the memo after a review, and no step leads into that section.
- **References:** `plugins/harness/skills/bubble-memo/SKILL.md:27-30` (Snapshot rule; line 29 says the one change after hand-off is a decision stamp, pointer (next rule).), `plugins/harness/skills/bubble-memo/SKILL.md:31-32` (New One pass, no review cycle bullet, the actual next rule, deferring to section On request.), `plugins/harness/skills/bubble-memo/SKILL.md:38-40` (Decision-stamping bullet, now three bullets below the snapshot rule.), `plugins/harness/skills/bubble-memo/SKILL.md:116-118` (Step 5 ends at check [ok] and says the work is done.), `plugins/harness/skills/bubble-memo/SKILL.md:120-122` (Step 6 Hand off: memo final for this run; no mention of a review.), `plugins/harness/skills/bubble-memo/SKILL.md:124-140` (On request section: tied to no step; corrects the memo per finding (137-138), reports unapplied findings in the hand-off (139-140).), `plugins/harness/agents/bubble-memo-reviewer.md:18-23` (Second example: review the memo again, a review after an earlier one.)
- **Current behavior:** The snapshot rule (SKILL.md:27-30) says the one change to the memo after hand-off is a decision stamp and points to it as (next rule). The PR inserted the One pass, no review cycle bullet (SKILL.md:31-32) right after it, so the decision-stamping bullet now sits three bullets down at SKILL.md:38-40. Step 5 ends the work at check [ok] (SKILL.md:118) and step 6 hands off with no hook for a review (SKILL.md:120-122). The On request section (SKILL.md:124-140) is tied to no step: it tells the session to correct the memo at each reviewer finding (SKILL.md:137-138) and to report unapplied findings in the hand-off (SKILL.md:139-140). The reviewer agent second example, review the memo again (bubble-memo-reviewer.md:18-23), shows a review that follows an earlier one. bubble_memo.py has no hand-off or snapshot text, so the conflict lives only in skill prose.
- **When:** The developer asks for a memo review after step 6 has handed off, either as a follow-up or as a repeat review like the reviewer example. When the invocation guidance asks for a review, step 5 has already declared the work done and step 6 has no point where On request runs, so where the review falls relative to hand-off is undefined.
- **Chain:**
  1. Steps 1-5 run; check prints check [ok] and step 5 says the work is done (SKILL.md:118).
  2. Step 6 hands off the memo as final for this run (SKILL.md:120-122).
  3. The developer asks for a review; On request runs check --reviewer-row and dispatches harness:bubble-memo-reviewer (SKILL.md:126-136).
  4. On request tells the session to open each finding location and correct the memo (SKILL.md:137-138), which edits memo text after hand-off.
  5. The snapshot rule allows only a decision stamp after hand-off (SKILL.md:29-30), so the session must refuse the corrections or break the rule.
  6. Separately, the (next rule) pointer at SKILL.md:29 lands on the One pass bullet (SKILL.md:31-32), not on decision stamping (SKILL.md:38-40).
  ```
  step 5 check [ok] -> step 6 hand-off -> developer asks for review -> On request dispatches reviewer -> session corrects memo -> conflicts with snapshot rule
  ```
- **Expected behavior per fix:**
    - (a) Rewrite SKILL.md:29-30 to: 'The only changes after hand-off are a decision stamp (the decision-stamping rule below) and the corrections from a review the developer asks for (section "On request").' -> The snapshot rule lists reviewer corrections as an allowed change after hand-off, so a review after hand-off no longer breaks it, and the wrong (next rule) pointer is gone. On request still does not say when it runs relative to steps 5 and 6.
    - (b) Alternatively, scope the On request section to before hand-off and say a review after hand-off is a fresh memo edit the developer authorizes, then make the snapshot rule name that exception. -> On request applies only before step 6. A review after hand-off is a developer-authorized edit that the snapshot rule names as an exception. The (next rule) pointer stays wrong unless it is also edited.
    - (c) Reword SKILL.md:29-30 to allow both changes, e.g. 'After hand-off the memo changes only by a decision stamp (rule "Decision stamping is not this skill's job") or by corrections from a review the developer asked for (section "On request").' Then state the timing in the On request section: when the invocation's guidance asks for a review, run it between steps 5 and 6 and fold the unapplied findings into the step 6 hand-off; when the developer asks after hand-off, run it then and report the unapplied findings in a short follow-up. -> The snapshot rule allows both changes and names the decision-stamping rule, which fixes the pointer. On request gets a defined place both for a review asked for in the guidance (between steps 5 and 6) and for one asked for after hand-off (with a follow-up report).
    - (d) Alternatively, make the review a pre-hand-off step only: add to step 5 'when the developer asked for a review, run section "On request" before step 6', and say in On request that a review requested after hand-off counts as a new run that starts from step 5. -> Every review runs before a hand-off: a later request reopens the run at step 5 and ends with a new step 6, so no edit happens after a hand-off. The snapshot text and its (next rule) pointer at SKILL.md:29-30 stay as they are.
    - (e) Replace '(next rule)' with '(rule "Decision stamping is not this skill's job")', or with 'the decision-stamping rule below'. -> The pointer at SKILL.md:29 names the decision-stamping rule (SKILL.md:38-40) and no longer lands on the One pass bullet. The snapshot versus On request contradiction is untouched.
    - (f) Or move the 'Decision stamping is not this skill's job' bullet up so it directly follows the snapshot rule. -> The (next rule) pointer is correct again because decision stamping sits right after the snapshot rule. The contradiction is untouched.
    - (g) Replace '(next rule)' with '(rule "Decision stamping is not this skill's job" below)'. -> Same as the first pointer fix: SKILL.md:29 names the decision-stamping rule explicitly, plus below. The contradiction is untouched.
    - (h) Or move the 'One pass, no review cycle' bullet below the decision-stamping bullet (SKILL.md:38-40), so the decision-stamping rule follows the snapshot rule again. -> One pass moves below decision stamping, but the References and prose bullets (SKILL.md:33-37) still sit between the snapshot rule and decision stamping, so (next rule) still points at the References bullet unless those move too. The contradiction is untouched.
- **Recommendation:** Choose (c). It lets the snapshot rule allow both changes, fixes the `(next rule)` pointer, and gives On request a defined place relative to hand-off.
- **Decision:** RESOLVED, 2026-11-03. 514d096 (working-tree snapshot; developer commits) - Snapshot rule now allows two changes after hand-off (a decision stamp, cross-referenced by the rule's name instead of 'next rule', and corrections from a requested review, section "On request"); On request states its timing: between steps 5 and 6 when the invocation asks, otherwise after hand-off with a short follow-up. bubble-memo-reviewer.md: its after-hand-off example is now permitted by the rule, no edit needed.

### I2. New snapshot/decision-stamp contract test passes on the pre-PR skill

- **Class:** architectural_ambiguity
- **Description:** The new snapshot test checks three words anywhere in the skill, and all three were already in the skill before this PR, so deleting the clause the PR added would not fail it.
- **References:** `tests/skills/test_bubble_memo_skill_contract.py:91-94` (The test under review: three body-wide substring asserts ('snapshot', 'bubble-stamp', 'Hand off').), `tests/skills/test_bubble_memo_skill_contract.py:97-100` (test_the_skill_keeps_prose_and_the_snapshot_rule asserts only Description, Recommendation and the stub marker; despite its name, no 'snapshot' assert.), `tests/skills/test_bubble_memo_skill_contract.py:70-74` (_split_steps splits on the Steps and On request headings; the Rules section is never isolated by any helper.), `plugins/harness/skills/bubble-memo/SKILL.md:27-30` (Snapshot-rule bullet; lines 29-30 are the PR-added clause 'The one change after hand-off is a decision stamp (next rule)...'.), `plugins/harness/skills/bubble-memo/SKILL.md:31-32` (PR-added rule 'One pass, no review cycle' with 'unless the developer asks' on line 32.), `plugins/harness/skills/bubble-memo/SKILL.md:38` (Decision-stamping rule naming the 'bubble-stamp' mod (line 35 at base).), `plugins/harness/skills/bubble-memo/SKILL.md:120` (Step 6 heading '**Hand off.**', the only capitalised 'Hand off' (step 8, line 128, at base).), `plugins/harness/skills/bubble-memo/SKILL.md:25` ('## Rules' heading; the Rules section runs to '## Steps' at line 44.)
- **Current behavior:** test_the_memo_stays_a_snapshot_apart_from_decision_stamps runs three whole-body substring checks: 'snapshot', 'bubble-stamp' and 'Hand off'. At HEAD they match SKILL.md lines 27 (snapshot-rule bullet), 38 (decision-stamping rule) and 120 (step 6 heading). At the merge base 10d0ad2 the same three strings sit at lines 27, 35 and 128 (old step 8), so the test passes on the pre-PR skill. Neither the clause this PR added to the snapshot rule (SKILL.md:29-30, 'The one change after hand-off is a decision stamp') nor the new 'One pass, no review cycle' rule (SKILL.md:31-32) is read by any assertion. Also, the neighbouring test_the_skill_keeps_prose_and_the_snapshot_rule (lines 97-100) does not assert 'snapshot' despite its name: it checks only 'Description', 'Recommendation' and the stub marker. So the review's claim that 'snapshot' is covered there is wrong; the new test is the only one checking that string.
- **When:** Always. Any SKILL.md body that contains the word 'snapshot' anywhere (it also appears in step 1 at line 58), the mod name 'bubble-stamp' anywhere (lines 38 and 122), and a capitalised 'Hand off' anywhere (line 120) passes the test. That includes the merge-base skill and a HEAD skill with lines 29-30 or 31-32 deleted. The lowercase 'hand-off' on line 29 does not match the 'Hand off' needle.
- **Chain:**
  1. The parts fixture loads plugins/harness/skills/bubble-memo/SKILL.md through skill_parts and returns (frontmatter, body).
  2. The test asserts 'snapshot' in body and 'bubble-stamp' in body, then 'Hand off' in body, with no section scoping.
  3. 'snapshot' matches line 27 (and line 58), 'bubble-stamp' matches line 38 (and 122), 'Hand off' matches the step 6 heading at line 120.
  4. All three strings were already in the merge-base SKILL.md (lines 27, 35, 128), so the added clause at 29-30 and the rule at 31-32 never affect the result.
  5. Deleting either addition leaves the test green, so the test's name promises a guard on the decision-stamp exception that its assertions do not give.
  ```
  parts fixture -> body string -> three body-wide `in` checks -> matches at SKILL.md:27/38/120 (also present at base 27/35/128) -> green with or without SKILL.md:29-32
  ```
- **Expected behavior per fix:**
    - (a) Pin the new clause: take the snapshot-rule bullet (the text from '**The memo is a point-in-time snapshot**' to the next '\n- **') and assert that 'decision stamp' and 'after hand-off' are in it, in place of the three body-wide substring checks. -> The slice covers SKILL.md:27-30, and both needles sit on line 29, so the test passes at HEAD, fails on the merge-base skill and fails if the clause is deleted. It no longer checks 'bubble-stamp', 'Hand off' or the 'One pass' rule at 31-32, and it fails if the bullet's bold opener is reworded.
    - (b) Alternatively, assert the exact sentence: assert "The one change after hand-off is a decision stamp" in body. -> The sentence sits whole on SKILL.md:29, so the assert passes at HEAD and fails at base or after deleting the clause. Any rewording, or a re-wrap that puts a newline inside the sentence, also fails it. Nothing ties it to the snapshot bullet, and lines 31-32 stay unguarded.
    - (c) Scope the assertions to the Rules section (split on '\n## Rules' and '\n## Steps') and assert the new 'One pass, no review cycle' rule and its 'unless the developer asks' clause there, alongside 'bubble-stamp' and 'snapshot'. -> The Rules slice (SKILL.md:25-43) holds all four needles (lines 27, 31, 32, 38), so the test passes at HEAD and fails at base because the 'One pass' rule is missing there. Deleting the decision-stamp clause at 29-30 still leaves it green, and the 'Hand off' check drops out unless kept separately.
    - (d) Fold the 'bubble-stamp' and 'Hand off' checks into test_the_skill_keeps_prose_and_the_snapshot_rule and drop the duplicate test. -> The checks stay body-wide, so the merged test still passes on the merge-base skill and with SKILL.md:29-32 deleted. Since the target test has no 'snapshot' assert (lines 97-100), dropping the new test also drops the only 'snapshot' check unless that check moves over too.
- **Recommendation:** Choose (a). It slices out the snapshot bullet and pins the clause the PR added, so the test fails on the old skill.
- **Decision:** RESOLVED, 2026-11-03. 514d096 (working-tree snapshot; developer commits) - test_the_memo_stays_a_snapshot_apart_from_decision_stamps now extracts the snapshot-rule bullet and asserts 'after hand-off', 'decision stamp' and 'On request' inside it, replacing the body-wide substring checks. SKILL.md: the clause it pins was written under I1, no further edit.

### M1. Agent description names `check` as the row source without the new flag

- **Class:** architectural_ambiguity
- **Description:** The reviewer agent description says its prompt comes from `bubble_memo.py check`, but plain `check` no longer prints the row; only `check --reviewer-row` does.
- **References:** `plugins/harness/agents/bubble-memo-reviewer.md:10` (Says the prompt is the header lines the 'bubble_memo.py check' driver prints for the row, with no '--reviewer-row' flag.), `plugins/harness/agents/bubble-memo-reviewer.md:13` (The example context names 'bubble_memo.py check --reviewer-row' as printing 'check [ok]' and one reviewer row.), `plugins/harness/scripts/bubble_memo.py:502-513` (cmd_check prints the status line, then prints reviewer_row(review) only under 'if args.reviewer_row'.), `plugins/harness/scripts/bubble_memo.py:206-211` (reviewer_row builds the 'agent=... model=...', 'PR:' and 'Memo:' lines that make up the dispatch prompt.), `plugins/harness/scripts/bubble_memo.py:525-527` ('--reviewer-row' is a store_true flag on 'check' (default False), with help text 'After a clean check, print the memo reviewer dispatch row.'), `plugins/harness/scripts/bubble_memo.py:25-27` (The module docstring says 'check --pr N [--reviewer-row]' prints the reviewer dispatch row only with '--reviewer-row'.)
- **Current behavior:** The reviewer agent's description says at line 10 that the prompt is the header lines that `bubble_memo.py check` prints for the row. Plain `check` prints only the `check [ok]` status line. The reviewer row (agent/model, PR, Memo) is printed only when `--reviewer-row` is set. The example at line 13 of the same description names `check --reviewer-row`, so the agent description contradicts its own example.
- **When:** A dispatcher (main session or a human) follows the line-10 sentence and runs `bubble_memo.py check --pr N` without `--reviewer-row`. The check passes, prints `check [ok]`, and prints no row to build the agent prompt from.
- **Chain:**
  1. bubble-memo-reviewer.md:10 tells the dispatcher the prompt comes from what `bubble_memo.py check` prints
  2. The dispatcher runs `check --pr N` with no flag
  3. cmd_check prints the `check [ok]` status line at bubble_memo.py:509-510
  4. args.reviewer_row is False, so the reviewer_row() print at bubble_memo.py:511-512 is skipped
  5. No `agent=... model=...` / `PR:` / `Memo:` lines appear, so the dispatcher has no prompt or model to pass
  ```
  agent description line 10 -> check --pr N (no flag) -> cmd_check prints status only -> reviewer_row skipped -> no dispatch row
  ```
- **Expected behavior per fix:**
    - (a) Change line 10 to: 'The prompt is the header lines `bubble_memo.py check --reviewer-row` prints for the row.' -> The agent description names the same command as its line-13 example and as the driver's flag, so a dispatcher following line 10 runs the command that prints the row. Driver behavior does not change: only the agent's frontmatter description text changes.
- **Recommendation:** Choose (a), the only fix offered. It makes line 10 match the example on line 13.
- **Decision:** RESOLVED, 2026-11-03. 514d096 (working-tree snapshot; developer commits) - Agent description line 10 now names `bubble_memo.py check --reviewer-row` as the row source, matching the example at line 13.; no edit in this part: plugins/harness/scripts/bubble_memo.py cmd_check already prints the reviewer row only under --reviewer-row (bubble_memo.py:511-512); the stale sentence at plugins/harness/agents/bubble-memo-reviewer.md:10 is the other part's edit

### M2. Step 5 ends the work even when the invocation itself asked for a review

- **Class:** architectural_ambiguity
- **Description:** Step 5 declares the work done at the first clean `check`, so an invocation that itself asked for a review has no step where the review runs.
- **References:** `plugins/harness/skills/bubble-memo/SKILL.md:118`, `plugins/harness/skills/bubble-memo/SKILL.md:120-122`, `plugins/harness/skills/bubble-memo/SKILL.md:124-127`
- **Current behavior:** Step 5 ends with `check [ok]` and says the work is done (SKILL.md:118). Step 6 hands off and does not mention a review (SKILL.md:120-122). The On request section opens with "Only when the developer asks" and names no step it follows (SKILL.md:124-127).
- **When:** The invocation itself asks for a review, for example through guidance that says to review the memo. The skill then does not say whether the review runs before or after step 6.
- **Expected behavior per fix:**
    - (a) Step 5 sends an invocation that asked for a review to the On request section before step 6, so the review runs in the same run and its unapplied findings reach the step 6 hand-off. The new sentence avoids the words the Steps test bans, so that test still passes.
    - (b) The On request section reports unapplied findings to the developer, in the hand-off when the review ran in the same invocation. Step 5 still ends the work at the first clean `check`, so the missing link from step 5 stays.
    - (c) The line at SKILL.md:138 tells the session to re-run the step 5 command, which prints no reviewer row, so a re-run after a correction dispatches no second review. The missing link from step 5 stays.
- **Recommendation:** Choose (a). It is the only option that gives a review asked for in the invocation a place in the steps.
- **Decision:** RESOLVED, 2026-11-03. 514d096 (working-tree snapshot; developer commits) - Step 5 now runs section "On request" before the hand-off when the invocation asked for a review; On request reruns `check` without `--reviewer-row` (the step 5 command) and reports unapplied findings to the developer, in the hand-off only when the review ran in the same invocation.

### M3. Failing-check test checks only 'agent=', not the Memo line

- **Class:** architectural_ambiguity
- **Description:** The failing-check test asserts that the row's `agent=` line is absent but not its `Memo:` line, which the default-flow test at line 161 does check.
- **References:** `tests/scripts/test_bubble_memo_driver.py:172-176`, `tests/scripts/test_bubble_memo_driver.py:161`
- **Current behavior:** The test scaffolds without filling the entries, runs `check --reviewer-row` and asserts exit code 1, an `I2: ` line on stderr and no `agent=` in stdout (line 176). It does not look for `Memo:`. The default-flow test asserts both markers are absent (line 161).
- **When:** A later change prints the `Memo:` line of the row on a failed check without printing the `agent=` line. The test stays green.
- **Expected behavior per fix:**
    - (a) The test also fails when `Memo:` appears in stdout, so lines 161 and 176 check the same two row markers.
- **Recommendation:** Choose (a), the only fix offered. It is a one-line assertion.
- **Decision:** RESOLVED, 2026-11-03. 514d096 (working-tree snapshot; developer commits) - test_a_failing_check_prints_no_reviewer_row_even_on_request now also asserts "Memo:" not in out (tests/scripts/test_bubble_memo_driver.py:176), matching the default-path test at line 161

### M4. Stray whitespace removal around '=' in an unrelated line

- **Class:** architectural_ambiguity
- **Description:** Line 275 has no space before `=`, while the same assignment at the merge base (line 260) has one.
- **References:** `tests/scripts/test_bubble_memo_driver.py:275`
- **Current behavior:** Line 275 reads `chain ="- **Chain:** step one\n  ```\n  a -> b\n  ```\n"`. The string is the same as the merge-base string, so the test behaves the same. Only the spacing of the assignment differs.
- **When:** Never at run time. It shows up in the diff of a PR that did not need to touch the line.
- **Expected behavior per fix:**
    - (a) The assignment is spaced as before and the diff no longer touches that line. As worded, the option also shows one-space indents inside the string, which differ from the two-space indents at the merge base and from the layout the skill requires; only the space before `=` should change.
- **Recommendation:** Choose (a), restoring only the space before `=`.
- **Decision:** RESOLVED, 2026-11-03. 514d096 (working-tree snapshot; developer commits) - restored the space around '=' in the chain assignment (tests/scripts/test_bubble_memo_driver.py:275)

### M5. _split_steps fails with a bare unpack error when a heading is missing

- **Class:** architectural_ambiguity
- **Description:** `_split_steps` raises a bare index or unpack error when the Steps or On request heading is missing, instead of naming the missing heading.
- **References:** `tests/skills/test_bubble_memo_skill_contract.py:70-74`
- **Current behavior:** The helper takes `body.split("\n## Steps", 1)[1]` and then unpacks `steps.split("\n## On request", 1)` into two names (lines 72-73). Without the Steps heading the first line raises `IndexError`. Without the On request heading the second raises `ValueError`. Neither message names the heading.
- **When:** Someone renames or removes the `## Steps` or `## On request` heading in SKILL.md. Two tests then fail with an error that does not say why.
- **Expected behavior per fix:**
    - (a) A missing heading fails with `Steps section missing` or `On request section missing`, and the two tests that use the helper report which heading went missing.
- **Recommendation:** Choose (a), the only fix offered.
- **Decision:** RESOLVED, 2026-11-03. 514d096 (working-tree snapshot; developer commits) - _split_steps asserts the Steps and On request headings are present before splitting, so a missing section fails with a named message instead of an unpack or index error.
