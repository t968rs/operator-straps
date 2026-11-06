# Plan 0008: merge commit msg squash mode

> Rendered by `plan.py render` from `0008_merge_commit_msg_squash_mode_ActionPlan.json`. Change the JSON through the driver, then render again; edits to this file are overwritten.

**Plan created:** 2026-11-05
**Spec:** `https://github.com/t968rs/operator-straps/issues/226`
**Branch:** 1131-merge-msg-squash-mode -> main
**Base commit:** `854d1fe`
**Frozen:** 2026-11-05 at `035cc6a`
**Execution model:** Wave 0 inline (TASK-1, TASK-2; staged). Wave 1 harness:parallel2: implement lanes task-3 and task-4 (opus, disjoint files, one worktree each, probe first), per-lane spec and quality review, P2 stage each. Wave 2 inline (TASK-5).

## Decisions

- **D1** Must a squash-mode PR title parse as a Conventional-Commit subject, and through which parser? Chosen: `require-public` (Require it; commit_txt exposes subject_parts (private alias kept)). Rejected: `no-require` (Any title passing the non-ASCII and branch-name checks), `require-own-regex` (Require it with a second regex in the driver). Developer, 2026-11-05 (TODO-003 decision_question).
- **D2** How do the squash behaviors enter the strap gate, given a frozen spec refuses add_behavior? Chosen: `archive-fresh` (Archive the frozen spec under strap/_archive/, open a fresh new --edit spec). Rejected: `refreeze-only` (Keep the spec, add unregistered tests, freeze --refreeze), `extend-strap` (Teach strap.py to reopen a frozen spec first). Developer, 2026-11-05.
- **D3** Capture header: the issue asks for 'Mode: squash' or 'Mode: merge', and also byte-identical no-mode output. Which wins? Chosen: `both-lines` (Print 'Mode: merge' too; the no-mode output changes). Rejected: `squash-only-line` ('- Mode: squash' fact and '# PR #N squash message' heading only in squash mode; merge output unchanged). Developer, 2026-11-05. Byte identity of the no-mode capture is dropped; the TXT and receipt stay unchanged.
- **D4** Mode handoff from capture to build (capture writes nothing). Chosen: `flag-or-detect` (build takes the flag; without it, either exact subject is accepted and its mode applies). Rejected: `flag-required` (build without the flag accepts only the merge subject). Developer, 2026-11-05.
- **D5** An unknown second positional (capture 7 rebase). Chosen: `problem-line` (Optional positional without argparse choices; the driver prints a problem: line, exit 1). Rejected: `argparse-choices` (choices=['squash']; argparse exits 2 with its usage text). Developer, 2026-11-05.
- **D6** How SKILL.md commands carry the mode. Chosen: `placeholder-carries-flag` ('<PR number>' on the commands stands for the number plus ' --squash' in squash mode; command lines unchanged). Rejected: `explicit-bracket` (Commands read 'capture <PR number> [--squash]'; the stdin contract node changes). Developer, 2026-11-05.

## Values

| Name | Value | Source | Assumes |
|---|---|---|---|
| squash subject | <title> (#N) | issue #226, Requested interface | - |
| merge subject | Merge PR #N -- <title> | plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:96-98 | - |
| argument-hint | <PR number> [squash \| --squash \| -s] [-- <guidance>] | issue #226, Skill rules and frontmatter | - |
| HARNESS_RULES size budget | RULES_LIMIT 10000; file is 9322 chars at base | tests/hooks/test_session_rules.py:31 | - |
| harness plugin version | 0.57.0 -> 0.58.0 | plugins/harness/.claude-plugin/plugin.json:3 | - |

## Formats

- **TXT subject line (line 1 of PR<N>_merge.txt)**: `Fix(workers): pool crash on spawn (#7)`, copied from `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:290-295`

## Sweeps

- **S1** `_?subject_parts\(`: `plugins/harness/lib/harness_lib/commit_txt.py` (definition and two internal callers; renamed public, private alias kept)
- **S2** `subject_line\(pr, title\)|title_problem\(pr, |pr_view\(repo, pr\)`: `docs/PR_REVIEWS/0164_Featuremerge-commit-msg_merge_commit_msg.py_stdin_build.json` (historical review; unchanged), `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py` (every call site is inside the driver; each gains the squash flag)
- **S3** `merge_commit_msg\.py\"? (capture|build)|harness:merge-commit-msg <`: `README.md` (TASK-4 adds the squash forms), `docs/PROVENANCE.md` (provenance prose; unchanged), `docs/PR_REVIEWS/0164_Featuremerge-commit-msg_merge_commit_msg.py_stdin_build.json` (historical review; unchanged), `plugins/harness/hooks/guard_commit_txt.py` (route 'build <N>' rebuilds either subject without a flag (D4); unchanged), `plugins/harness/skills/branch-commit-msg/SKILL.md` (--merge-msg passes the PR number only: merge mode; unchanged), `plugins/harness/skills/merge-commit-msg/SKILL.md` (TASK-4), `plugins/harness/skills/merge-commit-msg/message_format.md` (TASK-4), `tests/contract/test_root_separation.py` (merge-mode build subprocess; unchanged, must still pass), `tests/skills/test_canned_message_skill_contract.py` (pins canned-message text in SKILL.md; TASK-4 keeps it), `tests/skills/test_merge_commit_msg_skill_contract.py` (TASK-4)

## Tasks

### TASK-1: Strap edit spec for the squash behaviors

**Status:** PENDING | **Model:** opus | **Depends on:** none
**Files:** `docs/plans/strap/merge-commit-msg/SkillSpec.json`, `docs/plans/strap/_archive/merge-commit-msg-0466076841ae/SkillSpec.json`

Wave 0, main session (spec writes are serial). The frozen spec (0466076841ae, stale since PR #224) is already archived to docs/plans/strap/_archive/merge-commit-msg-0466076841ae/ and `strap.py new merge-commit-msg --edit` opened a fresh spec from 035cc6a (D2). Through the strap api heredoc add mechanical behaviors: B1 mode parsing (three forms equal, unknown token a problem line, in capture and build); B2 squash capture (subject '<title> (#N)', '# PR #N squash message', '- Mode: squash' (and '- Mode: merge' without a token), non-Conventional title refused); B3 squash build (flag writes the squash subject and 'squash message' receipt, no flag accepts either exact subject, paraphrase rejected, cross-mode subject names --squash, squash subject without flag still checks the title); B4 docs (argument-hint, squash trigger, three forms, guidance rule, both subjects, Common Mistakes row, format card example, README and HARNESS_RULES); B5 commit_txt.subject_parts public. Each lists the matching plan 0008 nodes. Copy the plan's planned files to docs/plans/strap/merge-commit-msg/tests/<repo path>, then strap check and strap red until clean. Planned-test copies stay byte-identical to docs/plans/0008/tests/.

- [ ] Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" check merge-commit-msg`: check [ok]
- [ ] Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" red merge-commit-msg`: no problem: lines, exit 0
- [ ] Record the commit: `plan.py record 0008 TASK-1 --sha <sha>`

**Evidence:** not started

### TASK-2: commit_txt: public subject_parts

**Status:** PENDING | **Model:** opus | **Depends on:** none
**Files:** `plugins/harness/lib/harness_lib/commit_txt.py`, `tests/lib/test_commit_txt_subject_parts.py`

**Anchors:**
- `plugins/harness/lib/harness_lib/commit_txt.py:139-144` holds `def _subject_parts(header: Optional[str])`
- `plugins/harness/lib/harness_lib/commit_txt.py:40` holds `_SUBJECT = re.compile(r"^([A-Za-z]+)(?:\(([^)]*)\))?:\s*(.*)$")`

Wave 0, main session (one function; inline beats a worktree). Rename _subject_parts to subject_parts in plugins/harness/lib/harness_lib/commit_txt.py, keep `_subject_parts = subject_parts` for the two internal callers, add it to __all__ if the module has one. Copy tests/lib/test_commit_txt_subject_parts.py from the plan. Stage both files (git add) so the wave 1 snapshot carries them.

- [ ] Test `tests/lib/test_commit_txt_subject_parts.py::test_subject_parts_splits_type_scope_summary` fails with ImportError, then passes
- [ ] Test `tests/lib/test_commit_txt_subject_parts.py::test_private_name_is_the_same_function` fails with ImportError, then passes
- [ ] Run `python -m pytest tests/lib/test_commit_txt_subject_parts.py tests/lib/test_commit_txt.py -q`: all pass
- [ ] Record the commit: `plan.py record 0008 TASK-2 --sha <sha>`

**Evidence:** not started

### TASK-3: merge_commit_msg.py squash mode

**Status:** PENDING | **Model:** opus | **Depends on:** TASK-2
**Files:** `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py`, `tests/skills/test_merge_commit_msg_squash.py`

**Anchors:**
- `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:96-98` holds `return f"Merge PR #{pr} {SUBJECT_SEPARATOR} {title}"`
- `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:105` holds `def title_problem(pr: int, title: str, head: str) -> Optional[str]:`
- `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:126` holds `problem = title_problem(pr, str(data["title"]), str(data["headRefName"]))`
- `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:226` holds `return [subject_line(pr, title)`
- `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:244` holds `parts = [f"# PR #{pr} merge message"`
- `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:292-295` holds `subject = subject_line(pr, title)`
- `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:335` holds `title = str(pr_view(repo, pr)["title"])`
- `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:355` holds `f"Saved: {shown} - merge message for PR #{pr}"`
- `plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py:362-364` holds `sub.add_parser(name, help=text).add_argument("pr", type=int, help="PR number")`
- `tests/skills/test_merge_commit_msg.py:234` holds `"Saved: docs/_commit_messages/PR7_merge.txt - merge message for PR #7"`

Wave 1, parallel2 implement lane task-3 (own worktree). Copy the planned files tests/skills/test_merge_commit_msg_squash.py first. In the driver: (a) _parser: capture and build take `--squash`/`-s` (store_true) and an optional positional `mode` (nargs='?', no choices); main normalizes args.squash = flag or mode == 'squash'; any other mode is `problem: unknown mode 'X'; the only mode is squash (--squash, -s)` with exit 1 (D5). (b) subject_line(pr, title, squash=False) returns f'{title} (#{pr})' in squash mode. (c) title_problem gains squash=False: in squash mode a title whose subject_parts type is None or summary empty is `PR #N title 'X' is not a Conventional-Commit subject (Type(scope): summary), which a squash commit needs; retitle it with gh pr edit N --title`. pr_view passes the flag. (d) message_template/render take squash: the subject follows the mode; the facts gain '- Mode: merge' or '- Mode: squash' after Title in both modes (D3); in squash mode only, the heading is '# PR #N squash message' and the instruction names `build --squash`. (e) build: with the flag, line 1 must equal the squash subject; a line 1 equal to the merge subject is `subject is the merge form; drop --squash to keep it, or use '<squash>'`. Without the flag, a line 1 equal to the squash subject switches to squash mode (title check included); otherwise the unchanged merge check and text (D4). (f) receipt says 'squash message' or 'merge message'. Module docstring: both modes, usage lines. No-mode capture output equals GOLDEN in the squash test file (base output plus '- Mode: merge'); the no-mode TXT and receipt stay identical (tests/skills/test_merge_commit_msg.py). Functions under 50 lines; Optional/Union typing.

- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashCapture::test_squash_subject_line` fails with TypeError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashCapture::test_three_forms_capture_identically` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashCapture::test_squash_capture_states_the_mode` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashCapture::test_unknown_mode_token_is_a_problem` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashCapture::test_squash_capture_refuses_a_non_conventional_title` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashBuild::test_squash_build_writes_the_squash_subject` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashBuild::test_build_without_a_flag_accepts_either_exact_subject` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashBuild::test_squash_build_rejects_a_paraphrased_subject` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashBuild::test_squash_build_names_the_flag_on_a_merge_subject` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashBuild::test_squash_subject_without_a_flag_still_needs_a_conventional_title` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashBuild::test_unknown_mode_token_is_a_problem_in_build` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_squash.py::TestSquashCapture::test_default_capture_adds_only_the_merge_mode_line` fails with AssertionError, then passes
- [ ] Run `python -m pytest tests/skills/test_merge_commit_msg_squash.py tests/skills/test_merge_commit_msg.py tests/contract/test_root_separation.py -q`: all pass
- [ ] Record the commit: `plan.py record 0008 TASK-3 --sha <sha>`

**Evidence:** not started

### TASK-4: Squash mode in the skill docs

**Status:** PENDING | **Model:** opus | **Depends on:** none
**Files:** `plugins/harness/skills/merge-commit-msg/SKILL.md`, `plugins/harness/skills/merge-commit-msg/message_format.md`, `plugins/harness/rules/HARNESS_RULES.md`, `README.md`, `tests/skills/test_merge_commit_msg_skill_contract.py`

**Anchors:**
- `plugins/harness/skills/merge-commit-msg/SKILL.md:4` holds `argument-hint: "<PR number> [-- <guidance>]"`
- `plugins/harness/skills/merge-commit-msg/SKILL.md:41-42` holds `` the subject (`Merge PR #N -- <title>`, ASCII ``
- `plugins/harness/skills/merge-commit-msg/SKILL.md:61` holds `merge_commit_msg.py" build <PR number> <<'MSG'`
- `plugins/harness/skills/merge-commit-msg/message_format.md:46` holds `` **Verbatim title.** The subject is exactly `Merge PR #NNN -- <title>` ``
- `README.md:264` holds `` `/harness:merge-commit-msg <PR>` drafts the squash-merge subject and body ``
- `plugins/harness/rules/HARNESS_RULES.md:36` holds `` A merge TXT follows the same rule: `harness:merge-commit-msg` `build` ``

Wave 1, parallel2 implement lane task-4 (own worktree), file-disjoint from task-3; the interface is fixed by this plan. Copy tests/skills/test_merge_commit_msg_skill_contract.py from the plan first. SKILL.md: argument-hint '<PR number> [squash | --squash | -s] [-- <guidance>]'; description adds 'squash message' and 'squash-merge commit for PR N' triggers; Arguments: before `--` the PR number, then an optional mode token (`--squash`, `-s` or a bare `squash`), normalized to `--squash`; on every command `<PR number>` stands for the number plus ` --squash` in squash mode (D6); '`squash` after `--` is guidance'; any other token is a problem line. Step 1: subject `Merge PR #N -- <title>` or `<title> (#N)`, and squash needs a Conventional-Commit PR title (refusal reported, developer retitles). Step 2 and Changing a saved message: build with the same mode; a rebuild from the saved TXT needs no flag (build accepts either exact subject, D4). Common Mistakes: a row for running build with a different mode than capture (--squash). Keep the canned-message text (tests/skills/test_canned_message_skill_contract.py) and the stdin command form. message_format.md: both subjects in Layout, Section order 1 and Verbatim title ('Merge PR #NNN -- <title>' merge mode, '<title> (#NNN)' squash mode), and '## Worked example (squash, PR #NNN)' beside PR #887 with its receipt. README.md merge-commit-msg section: '/harness:merge-commit-msg 123 --squash' in the example block and the squash subject in the capture bullet. HARNESS_RULES.md line 36: the merge TXT rule covers squash mode (same file, same route), within RULES_LIMIT.

- [ ] Test `tests/skills/test_merge_commit_msg_skill_contract.py::test_argument_hint_names_the_squash_forms` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_skill_contract.py::test_description_triggers_on_a_squash_message` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_skill_contract.py::test_skill_names_the_three_forms_and_keeps_squash_after_the_split_as_guidance` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_skill_contract.py::test_skill_states_both_subjects` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_skill_contract.py::test_common_mistakes_cover_a_mode_mismatch` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_skill_contract.py::test_format_card_states_both_subjects_and_a_squash_example` fails with AssertionError, then passes
- [ ] Test `tests/skills/test_merge_commit_msg_skill_contract.py::test_readme_and_rules_name_the_squash_mode` fails with AssertionError, then passes
- [ ] Run `python -m pytest tests/skills/test_merge_commit_msg_skill_contract.py tests/skills/test_canned_message_skill_contract.py tests/hooks/test_session_rules.py -q`: all pass
- [ ] Record the commit: `plan.py record 0008 TASK-4 --sha <sha>`

**Evidence:** not started

### TASK-5: Version bump, strap freeze and guard runs

**Status:** PENDING | **Model:** opus | **Depends on:** TASK-1, TASK-3, TASK-4
**Files:** `plugins/harness/.claude-plugin/plugin.json`, `docs/plans/strap/merge-commit-msg/SkillSpec.json`

Wave 2, main session, after `P2 stage task-3`, `P2 stage task-4` and `P2 cleanup`. Bump plugins/harness plugin.json 0.57.0 -> 0.58.0. strap check, then `strap.py freeze merge-commit-msg` (mechanical only: every planned node passes on the staged content). ruff with --no-cache over the changed .py files. `python tools/select_tests.py --base main` and run each selected file by name. Hand off: changed-file list, frozen hash, merge recommendation; the developer commits, then plan.py record per item with that commit.

- [ ] Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" freeze merge-commit-msg`: freeze [done] | merge-commit-msg
- [ ] Run `python -m ruff check --no-cache plugins/harness/skills/merge-commit-msg/commands/merge_commit_msg.py plugins/harness/lib/harness_lib/commit_txt.py tests/skills/test_merge_commit_msg_squash.py tests/lib/test_commit_txt_subject_parts.py tests/skills/test_merge_commit_msg_skill_contract.py`: All checks passed!
- [ ] Run `python tools/select_tests.py --base main`: a list of test files, each then run by name
- [ ] Record the commit: `plan.py record 0008 TASK-5 --sha <sha>`

**Evidence:** not started
