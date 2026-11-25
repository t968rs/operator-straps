# Retiring `superpowers-lt:verification-before-completion` (todo-h4c3)

Status: research, no change made. Tree at `beee688`; every `path:line` below is at that commit. Scope: only the
`verification-before-completion` skill of `superpowers-lt`. The other `superpowers-lt` skills the repo still names
are listed in Section 6 because they block the uninstall, not because this note retires them.

## Answer

- **One hard dependency, two soft ones.** `post-forcepush` Step 6 cannot finish without the skill; the
  `parallel2` README and the `HARNESS_RULES.md` "Making claims" stage name it softly. Nothing in code or tests
  depends on it. The `strap-debugging` reference the TODO item lists was already removed by PR #337.
- **The repo already states most of the tenets.** Evidence before assertions, distrust of subagent reports,
  "status is never a claim" and faithful reporting are bound in `HARNESS_RULES.md`, which the SessionStart hook
  injects into every session, and three of them are enforced by drivers inside plan, review and strap runs.
- **Retirement loses three things.** The upstream skill's 5-step gate, its single claim-to-evidence table, and
  its hedge-word and rationalization lists. The repo states these only piecemeal or not at all.
- **Recommendation (Section 5):** replace post-forcepush Step 6 with concrete, domain-specific checks (no skill
  call), and port an adapted harness skill for the general gate. `HARNESS_RULES.md:109` and
  `parallel2/README.md:89` then point at the harness skill. Size S, as the TODO item says.

## 1. Where the repo states or espouses the tenets

T1-T7 are the tenets the upstream skill teaches. "Prose" means a binding rule an agent reads; "mechanical"
means a driver, hook or model refuses the wrong state.

| Tenet | Prose (best anchors) | Mechanical | Coverage |
|---|---|---|---|
| T1 Evidence before assertions | `plugins/harness/rules/HARNESS_RULES.md:92` ("run the command that proves a claim and read its output before stating it"), `:56-58` (branch and PR state), `:94` (read a written file back), `pr-review/SKILL.md:104-109` | Only inside runs: `pr_review.py:1570-1590` captures Phase 4 output itself; `plan.py:783-807` runs the planned tests itself | Strong in prose; no gate outside runs |
| T2 A gate before claiming done, committing, opening a PR | `HARNESS_RULES.md:109` ("verification before completion; non-negotiable", with no steps), `tdd-strapped/SKILL.md:332-346` (checklist), `strap-debugging/SKILL.md:185-189`, `pr-review/SKILL.md:581-582` | Stop is gated only while a sentinel exists (`hooks/check_phase5_sentinel.py:282-308`, `check_min_viz_sentinel.py:118-136`); `plan.py freeze` and `strap.py freeze`. No hook inspects `git commit`, `git push` or `gh pr create` | Strong within skills; the general gate has a name and no procedure |
| T3 Claim-to-evidence mapping | Scattered: tests pass, `tdd-strapped:188-191`; bug fixed, `strap-debugging:188-189`, `fold-in-review:96-102`; red-green-revert, `tdd-strapped:119-138`, `porting-into-straps:76`; requirements, `agents/todo-editor.md:109-116`; agent done -> diff, `pr-team/return_contract.md:158-163` | `plan.py record` (COMPLETE needs `--sha`/`--staged` plus a passing test run), `review_merge.py:1049-1096` (fixer claims checked against the diff) | Every row exists somewhere; no single table |
| T4 Hedge words, premature satisfaction | `strap-debugging:221-222` (red flags), `decompose-module/SKILL.md:532` (local to that skill), `HARNESS_RULES.md:139` ("Tests pass, we're done") | None | Weak: nothing covers "should pass", "Done!", "Great!" |
| T5 Distrust subagent reports | `HARNESS_RULES.md:143`, `subagent-reporting/SKILL.md:43-56`, `pr-team/SKILL.md:456-477` | `plan.py` reruns tests on a throwaway tree; `pr_review.py:2224-2242` flags unrecorded fixers; `strap.py:805` checks runner replies | Strong |
| T6 Status is never a claim | `HARNESS_RULES.md:80-85`, `pr-review/operating_rules.md:50`, `write-plan/SKILL.md:18-21` | Sealed records (`plan_models.py:337-360`, `receipt_models.py:73-127`), SHA-led evidence clears the Phase 5 sentinel (`hooks/validate_pr_json_schema.py:236-273`), `guard_locked.py` | Strong for plan and review state; `ActionPlan.schema.json:85-104` alone allows COMPLETE with no record |
| T7 Faithful reporting | `HARNESS_RULES.md:93,97`, `tdd-strapped:216-218`, `d-w/SKILL.md:59-61`, `agents/todo-editor.md:176` | `pr_review.py:1593-1600` holds a READY verdict at NOT READY when Phase 4 failed | Strong in prose; pytest skips are never parsed |

**An ad-hoc session** (no plan, review or strap run) gets the `HARNESS_RULES.md` Verification section and red
flags as prose through SessionStart (`plugins/harness/hooks/session_rules.py:2,16`) and no mechanical gate.
The Stop gates return at once without a sentinel, and the PostToolUse validator acts only on plan and review
JSON. The prose is what carries the tenets there, so the gaps in T2 and T4 matter most in that setting.

## 2. Every reference to the skill

Searched case-insensitively for `verification[- _]before[- _]completion`, hidden folders included, `.git`
excluded: 11 hits in 5 files.

| path:line | Class | Hard/soft | Action |
|---|---|---|---|
| `plugins/harness/skills/post-forcepush/SKILL.md:186,188` (Step 6 heading and "Invoke the `superpowers-lt:verification-before-completion` skill via the Skill tool") | Live prose | **Hard** | Replace (Section 5.1) |
| `post-forcepush/SKILL.md:206-207` (report item 5 must read `VERIFIED`) | Live prose | **Hard** | Replace |
| `post-forcepush/SKILL.md:233` ("Step 6 is non-negotiable") | Live prose | **Hard** | Replace |
| `plugins/harness/skills/parallel2/README.md:89` (W4 row; `:79` says outside skills "apply when installed") | Live prose | Soft | Repoint |
| `plugins/harness/rules/HARNESS_RULES.md:109` ("**Making claims:** verification before completion; non-negotiable."; `:102` "Skills outside this plugin apply when installed.") | Live prose | Soft (names a practice, no skill id), but the rule itself is a gate | Repoint or restate |
| `docs/TODO/RepoToDo.json:94,115,116` (todo-h4c3), `:2248` (a parallel2 item), `:3712` (a strap-debugging item) | History (catalog) | - | Refresh through `harness:todo-edit`, never by hand (Section 7) |
| `docs/PR_REVIEWS/0337_0003_tdd_strapped.json:487` (M7, REFUTED: `:102` still covers the unnamed "verification" stage) | History | - | Leave |

**Why Step 6 is a runtime failure.** post-forcepush dispatches a haiku `general-purpose` agent
(`post-forcepush/SKILL.md:30-34`) whose pre-authorized tools include `Skill` only for Step 6 (`:58`). Where
`superpowers-lt` is not installed (any consuming project that never enabled it, or this one after the
uninstall), the Skill call fails, report item 5 cannot be filled, and Common Mistakes calls skipping the step
non-negotiable. No Python validates the report, so the break is silent in tests:
`tests/skills/test_pr_review_skill_contract.py` reads post-forcepush only for its `verification_log` paths.

**Testing trap on this machine.** The upstream `superpowers` plugin (5.0.7, a synced copy) is installed beside
`superpowers-lt` (7.0.1). A session here still resolves `superpowers:verification-before-completion` after
`superpowers-lt` goes, which masks a missed reference. Prove the change in a session with neither enabled, or by
the guard test in Section 5.

## 3. What retirement loses

The upstream skill (`superpowers-lt` 7.0.1, 120 lines; MIT, Copyright (c) 2025 Jesse Vincent) against the repo:

| Upstream component | Repo equivalent | Lost on retirement? |
|---|---|---|
| Iron law: no completion claims without fresh evidence | `HARNESS_RULES.md:92` | No |
| Gate function: identify, run, read, verify, then claim | Only per skill (`tdd-strapped` checklist, `strap-debugging` Verify Fix); `:109` names the gate without steps | **Yes**, as a general procedure |
| Claim-to-evidence table (tests, linter, build, bug fixed, regression test, agent completed, requirements) | Each row exists in some skill (Section 1, T3) | **Yes**, as one table |
| Red flags: "should", "probably", "seems to", "Great!", "Done!" | `strap-debugging:221-222`, `decompose-module:532`, local only | **Yes** |
| Rationalization table (8 rows) | `HARNESS_RULES.md:137-143` covers 2 of the 8 ideas | **Mostly** |
| Agent delegation: check the VCS diff | `HARNESS_RULES.md:143`, pr-team, `plan.py` | No |
| Requirements: re-read the plan, check each item | `agents/todo-editor.md:109-116`, `plan.py record` | No, inside runs |

**A verbatim port conflicts with this repo's rules.** The upstream step 2 says "RUN the FULL command (fresh,
complete)"; here full-suite runs belong to the developer and tests run by file name
(`HARNESS_RULES.md:95-97`). `tdd-strapped` made the same adaptation (`docs/PROVENANCE.md:17`, Verify GREEN).
The upstream table also has no rows for this repo's own claims: COMPLETE (a sealed `plan.py record`), RESOLVED
(SHA-led evidence), "saved" (the file read back, `:94`) and branch or PR state (`gh pr view`, `git log`,
`:56-58`).

## 4. Options

| | A. Port an adapted skill | B. No skill: inline checks plus a longer rules section | C. Hybrid (recommended) |
|---|---|---|---|
| post-forcepush Step 6 | Calls the harness skill | Inline checks | Inline checks |
| General gate (`:109`) | Names the harness skill, like "Writing code: `harness:tdd-strapped`" (`:104`) | Points at the Verification section, which gains a claim table and a hedge list | Names the harness skill |
| Restores T2 steps, T3 table, T4 lists | Yes | Yes, in about 10 more lines of every session's context | Yes |
| Cost | New skill folder, LICENSE, PROVENANCE row, guard test, strap rounds | Rules text only | A plus a 15-line Step 6 rewrite |
| Weakness | A haiku metadata worker loading a 120-line general skill to check a one-file edit | Every session pays the context; no trigger-time load | Two places to keep consistent |

Why the Step 6 rewrite is not optional in A: the post-forcepush worker has one file, a schema result, a SHA map
and a marker list to check. Each has a concrete command, and the skill's general gate adds nothing a worker
needs that those commands do not already prove.

## 5. Recommendation: C

### 5.1 post-forcepush Step 6, inline

Replace `:186-196` with "Step 6: verify before reporting". Run each check after the last edit and record its
line:

1. Rerun the Step 5 command; its output must be exactly `SCHEMA OK`.
2. For each NEW SHA in the map: `git -C <repo-root> cat-file -e <sha>^{commit}` exits 0.
3. `git -C <repo-root> status --porcelain` lists the review JSON and nothing else.
4. Search the JSON for every OLD SHA in the map. None remains outside `(squashed: previously ...)` and
   `[NEEDS USER VERIFICATION: was ...]` text.
5. The count of `[NEEDS USER VERIFICATION` markers in the file equals the length of report item 3.

Then make three more changes:
- Report item 5 (`:206-207`) becomes "Step 6 checks: one line each, `<check> [ok|fail] <evidence>`", and any
  `fail` makes item 6 `BLOCKED`.
- The Common Mistakes row (`:233`) becomes "Reporting before the Step 6 checks | each check runs after the last
  edit".
- In the pre-authorized tools (`:55-58`), drop `Skill` and add `Bash(git -C * status *)`.

A follow-up worth weighing under the CLAUDE.md rule that drivers act and prose does not: checks 1, 3, 4 and 5
are mechanical and could be one driver command. post-forcepush has no `commands/` folder today.

### 5.2 Port an adapted harness skill

The name is the developer's call; `tdd-strapped` suggests `harness:verification-strapped`. Follow
`porting-into-straps` (run `port_scan.py` first) and scaffold through `harness:strap-skills` (`strap.py new`), as
`tdd-strapped` was strapped. Adaptations:

- Gate step 2 runs the proving tests by file name; a full-suite claim is handed to the developer
  (`HARNESS_RULES.md:95-97`).
- The claim table gains rows for COMPLETE, RESOLVED, saved, and branch or PR state (Section 3).
- Keep the hedge-word list and the rationalization table. Drop the upstream "Why This Matters" persona text
  (not in the lt copy anyway). Write "your human partner" as "the developer". Name no AI vendor.
- The description triggers on its own, never on another plugin being absent (the check
  `tests/skills/test_strap_debugging_skill_contract.py:23-27` makes).

### 5.3 Touch list

| File | Change |
|---|---|
| `plugins/harness/skills/post-forcepush/SKILL.md` | Section 5.1 |
| `plugins/harness/skills/<name>/SKILL.md`, `LICENSE` | New; LICENSE copied from upstream, byte-identical to `strap-debugging/LICENSE` |
| `plugins/harness/rules/HARNESS_RULES.md:109` | `**Making claims:** \`harness:<name>\`; non-negotiable.` `:102` stays: it still covers "Creating plans" |
| `plugins/harness/skills/parallel2/README.md:89` | W4 row names the harness skill |
| `README.md` (skill table, near `:51`) | New row |
| `docs/PROVENANCE.md` | New row in the `:16-17` format: source repo, SHA, date, MIT and LICENSE beside it, "Verbatim except" list |
| `tests/skills/test_<name>_skill_contract.py` | New: no "superpowers" in the skill or post-forcepush text; the Making claims rule names the harness skill |
| `plugins/harness/.claude-plugin/plugin.json` | `0.88.0` here; bump from the **target branch's** version at landing time |
| `docs/RELEASES/v<X.Y.Z>.md`, `CHANGELOG.md` | Latest release is `v1.0.0`; branch `0010-timestamps-timestamps` is editing `docs/RELEASES/v1.1.0.md`, so this likely joins v1.1.0 |

## 6. Gate before uninstalling `superpowers-lt`

This note clears one skill. The plugin stays enabled (`.claude/settings.json:15`, `.claude-plugin/marketplace.json:104-109`)
while live prose still names these skills:

| Skill | Live references |
|---|---|
| `receiving-code-review` | `pr-review/SKILL.md:93`, `consumer-contract-audit/SKILL.md:156` |
| `dispatching-parallel-agents` | `parallel2/SKILL.md:20` ("**REQUIRED**", with "when installed"), `parallel2/README.md:85` |
| `subagent-driven-development` | `pr-review/SKILL.md:1189`, `plugins/harness/schemas/PLANS_PIP_Template.md:16` (propagating text) |
| `executing-plans`, `finishing-a-development-branch` | `pr-review/SKILL.md:1188,1190` |
| `writing-plans` | `consumer-contract-audit/SKILL.md:153` |

Also outstanding: the `docs/superpowers/` path convention (`plugins/harness/config/defaults.json:24,50`), which
the migrating-off-a-plugin skill classes as a data move, not a rename. Test fixtures naming
`superpowers:code-reviewer` (`plugins/agent-watcher/hooks/**/*.test.ts`) stay.

## 7. Stale prose in the catalog

todo-h4c3 is right about the dependency but stale on three points:
- `strap-debugging/SKILL.md:189` already carries an inline rule (PR #337, `e4d9108`) and is guarded by
  `test_strap_debugging_skill_contract.py:27`.
- The parallel2 README row has moved from `:87` to `:89`.
- The Verification section has moved from `:83` to `:90`.

The same strap-debugging point is stale in `RepoToDo.json:3712`, and the line numbers at `:2248`. Refresh them
with `harness:todo-edit` (update) once Section 5 is decided.

## Method

Three read-only research lanes, validated by `parallel2.py plan`, ran in parallel at `beee688`: repo prose
(tenets T1-T7), mechanical enforcement (hooks, drivers, schemas), and the reference inventory with the upstream
text, license and port precedent. The session re-checked the load-bearing claims against the tree:
- the reference lines (`HARNESS_RULES.md:90,92,102,109`; `parallel2/README.md:79,89`; post-forcepush
  `:58,186-207,233`)
- the SessionStart injection (`session_rules.py:2,16`), which corrects one lane's statement that ad-hoc sessions
  get no verification text
- the enablement lines
- the guard-test pattern
- the latest release tag
