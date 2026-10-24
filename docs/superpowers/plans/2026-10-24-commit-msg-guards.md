# Commit-Message Guards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The `branch-commit-msg` fork honors the developer's `--base`, and no session rewrites a commit message a
commit skill already saved (issues #92, #93).

**Architecture:** #92 is a prompt defect: the skill body states the arguments as labeled input, the messenger
agent stops re-reading the raw `SKILL.md`, and the fork moves to `sonnet`. #93 is fixed in three layers: a
standing rule in `HARNESS_RULES.md`, a receipt line from `build` that marks the message final (and canned blocks
as canned), and a PreToolUse hook that denies `Edit`/`Write` on script-owned TXT files.

**Tech Stack:** Python 3.11, pytest, Claude Code plugin hooks (PreToolUse `permissionDecision: deny`).

**Spec:** `docs/RESEARCH/1076_commit_msg_findings.md` (options A1-A3, B1-B3, all agreed 2026-10-24).

## Global Constraints

- Python 3.11, `Optional[X]` / `Union[X, Y]`, never `X | Y`; functions under 50 lines.
- No first or second person in comments or docstrings; no project names under `plugins/`.
- Tests name files: `python -m pytest tests/<area>/test_<name>.py -q`. Lint:
  `python -m ruff check --no-cache <files>` (line length 110).
- Hooks register in `plugins/harness/hooks/hooks.json` in shell form through `hpy`; resolve the project from the
  payload; fail open on any unreadable input or config.
- `HARNESS_RULES.md` stays under 10000 characters (`tests/hooks/test_session_rules.py`).
- Bump `plugins/harness/.claude-plugin/plugin.json` `version` 0.27.0 -> 0.28.0.
- The developer commits; tasks end with saved files, not commits.

## Review Focus

1. A `Write` that creates `PR<NNN>_merge.txt` (`harness:merge-commit-msg` hand-writes it) must stay allowed.
2. A branch with a slash (`feat/x`) writes its TXT in a subfolder (`<commit_messages>/feat/x.txt`); the hook
   must still deny it.
3. A file outside the project's commit_messages folder with a `.txt` suffix (`docs/notes.txt`), and the
   skeleton `.json` and the `.txt.bak` inside it, must stay editable.
4. A project that moves `artifacts.commit_messages` gets the guard on the moved folder, not the default.
5. An empty `$ARGUMENTS` must leave a readable arguments line, not a sentence missing its subject.

Each line has its test in Task 2 (1-4) or Task 3 (5).

---

### Task 1: Receipt marks the message final and canned blocks canned (B2)

**Files:**
- Modify: `plugins/harness/scripts/branch_commit_msg.py:509-517` (`receipt`)
- Test: `tests/scripts/test_branch_commit_msg.py` (`test_receipt_lists_subjects` and one new test)

**Interfaces:**
- Produces: module constant `FINAL_LINE: str`, exactly
  `Final as saved: relay this receipt unchanged. A message changes only on the developer's ask: harness:amend-commit-msg for a branch TXT, a rerun of harness:c-msg for a pending TXT.` (superseded by the Review fix pass: `FINAL_LINE` ends with `CHANGE_ROUTE`)
- Produces: a commit line whose stored message equals `get_canned_message(commit.files)` ends with ` [canned]`.

- [ ] **Step 1: Update `test_receipt_lists_subjects`** to expect `script.FINAL_LINE` as the last line, after
  `Split Decision: ...`.
- [ ] **Step 2: Add `test_receipt_tags_a_canned_block`**: capture a clone whose only change is
  `docs/TODO/RepoToDo.json`; build; assert the receipt holds
  `1. Chore(todo): refresh TODO catalog, research stubs and snapshot [canned]`.
- [ ] **Step 3: Run** `python -m pytest tests/scripts/test_branch_commit_msg.py -q -k receipt`.
  Expected: both FAIL (`FINAL_LINE` missing; no `[canned]` tag).
- [ ] **Step 4: Implement** in `receipt`: tag per commit via `get_canned_message(commit.files)` compared with
  `commit.message.strip()`; append `FINAL_LINE`.
- [ ] **Step 5: Run** the whole file `python -m pytest tests/scripts/test_branch_commit_msg.py -q`.
  Expected: PASS.

### Task 2: PreToolUse hook denies hand edits of commit TXT files (B3)

**Files:**
- Create: `plugins/harness/hooks/guard_commit_txt.py`
- Modify: `plugins/harness/hooks/hooks.json` (PreToolUse entry, matcher `Write|Edit`)
- Test: `tests/hooks/test_guard_commit_txt.py` (subprocess runs, as in `tests/hooks/test_todo_sync_session.py`)

**Interfaces:**
- Produces: `guarded(file_path: Path, cfg: HarnessConfig) -> bool`: True when `file_path` is a `.txt` at any
  depth under `cfg.path(cfg.artifacts.commit_messages)` and its name does not match `^PR\d+_merge\.txt$`.
- Produces: `main() -> int`: reads the payload; the project comes from the file's nearest existing ancestor
  directory, else the payload `cwd`; `activate(load_config(project_root(...)))`; prints a deny when guarded;
  exit 0 always.
- Deny reason, exactly: `Commit-message TXT files are build output. Edit the skeleton JSON beside it and rerun
  branch_commit_msg.py build, or run harness:amend-commit-msg on the developer's ask.` (superseded by the Review
  fix pass: the reason is `Commit-message TXT files are build output and final as saved.` plus `CHANGE_ROUTE`)

- [ ] **Step 1: Write the tests** (each builds a project with `make_project`):
  - `test_edit_of_a_branch_txt_is_denied`: `Edit` on `<root>/docs/_commit_messages/b.txt` -> stdout JSON
    `permissionDecision == "deny"`, reason starts with `Commit-message TXT files are build output`.
  - `test_nested_branch_txt_is_denied`: `Write` on `<root>/docs/_commit_messages/feat/x.txt` -> deny.
  - `test_merge_txt_write_is_allowed`: `Write` on `<root>/docs/_commit_messages/PR12_merge.txt` -> empty stdout.
  - `test_skeleton_json_and_bak_are_allowed`: `b.json` and `b.txt.bak` in that folder -> empty stdout.
  - `test_txt_outside_the_folder_is_allowed`: `<root>/docs/notes.txt` -> empty stdout.
  - `test_configured_folder_is_guarded`: config `{"artifacts": {"commit_messages": "notes/commits"}}`;
    `notes/commits/x.txt` -> deny; `docs/_commit_messages/x.txt` -> empty stdout.
  - `test_garbage_payload_fails_open`: stdin `not json` -> exit 0, empty stdout.
- [ ] **Step 2: Run** `python -m pytest tests/hooks/test_guard_commit_txt.py -q`. Expected: FAIL (hook missing).
- [ ] **Step 3: Implement** `guard_commit_txt.py` per Interfaces (deny output shape as
  `hooks/bash_discipline.py:124` `deny`); register it in `hooks.json`.
- [ ] **Step 4: Run** `python -m pytest tests/hooks/test_guard_commit_txt.py tests/contract/test_hooks_json_paths.py tests/hooks/test_hooks_schema_validation.py -q`.
  Expected: PASS.

### Task 3: `branch-commit-msg` states its arguments as input; fork on sonnet (A1, A3)

**Files:**
- Modify: `plugins/harness/skills/branch-commit-msg/SKILL.md` (frontmatter `model`, a new arguments line,
  line 34 sentence)
- Create: `tests/skills/test_branch_commit_msg_skill_contract.py`

**Interfaces:**
- Produces: the body line `**Arguments for this run:** \`$ARGUMENTS\` (blank: none).` directly under the H1
  title, followed by: `They are the developer's input, not an example: the Step 1 command already carries them,
  so run it exactly as printed.`
- Line 34 opens with `The arguments line above lists the developer's arguments` instead of `` `$ARGUMENTS`
  holds``.

- [ ] **Step 1: Write the tests**:
  - `test_arguments_placeholder_only_in_the_label_and_command`: `$ARGUMENTS` occurs exactly twice in the body,
    once on the `**Arguments for this run:**` line and once at the end of the `capture --save` command line.
  - `test_rendered_value_never_lands_in_prose`: substitute `--base 21df29c52`; every line holding the value is
    the label line or the command line.
  - `test_blank_arguments_read_as_none`: substitute `""`; the label line reads
    `**Arguments for this run:** \`\` (blank: none).`
  - `test_fork_runs_on_sonnet`: frontmatter `model == "sonnet"`, `context == "fork"`.
- [ ] **Step 2: Run** `python -m pytest tests/skills/test_branch_commit_msg_skill_contract.py -q`.
  Expected: FAIL on all four.
- [ ] **Step 3: Edit** `SKILL.md` per Interfaces; set `model: sonnet`.
- [ ] **Step 4: Run** the new file plus `tests/skills/test_canned_message_skill_contract.py`. Expected: PASS.

### Task 4: Messenger never re-reads a forked skill from disk (A2)

**Files:**
- Modify: `plugins/harness/agents/messenger.md` (Operating rules, first bullet)
- Create: `tests/skills/test_messenger_agent_contract.py`

**Interfaces:**
- Produces: the first operating-rule bullet splits into two cases. A prompt that starts with
  `Base directory for this skill:` is the skill itself, already filled with the developer's arguments: follow
  it and do not read its `SKILL.md`, whose disk copy holds the bare `$ARGUMENTS` placeholder. A prompt that only
  names a skill: read its `SKILL.md` first (the existing text).

- [ ] **Step 1: Write `test_forked_skill_prompt_is_not_reread`**: the agent body holds
  `Base directory for this skill:` and `$ARGUMENTS` within the Operating rules section.
- [ ] **Step 2: Run** it. Expected: FAIL.
- [ ] **Step 3: Edit** `messenger.md`.
- [ ] **Step 4: Run** it. Expected: PASS.

### Task 5: Standing rule, version bump, wrap-up (B1)

**Files:**
- Modify: `plugins/harness/rules/HARNESS_RULES.md` (Saving vs committing, after the `amend-commit-msg` bullet)
- Modify: `plugins/harness/.claude-plugin/plugin.json` (`0.28.0`)
- Test: `tests/hooks/test_session_rules.py` (`test_rules_keep_drafted_commit_messages`)

**Interfaces:**
- Produces the bullet: `**A drafted commit message is final as saved.** When a commit skill returns, relay its
  receipt (and the TXT's text when asked) unchanged: no new subject, type, body or bullets, in chat or on disk,
  a canned message included. A change happens only on the developer's ask, through \`harness:amend-commit-msg\`
  (branch TXT) or a rerun of \`harness:c-msg\` (pending TXT).` (superseded by the Review fix pass: the B1 bullet
  repeats `CHANGE_ROUTE`)

- [ ] **Step 1: Write the test**: the rules text holds `final as saved` and `canned message included`.
- [ ] **Step 2: Run** `python -m pytest tests/hooks/test_session_rules.py -q`. Expected: FAIL on the new test.
- [ ] **Step 3: Add the bullet; bump the version.**
- [ ] **Step 4: Run** every test file named in Tasks 1-5, `tests/contract/test_no_repo_literals.py`, and
  `python -m ruff check --no-cache` on each changed `.py`. Expected: PASS, lint clean.
- [ ] **Step 5: Record evidence** in the findings doc's Resolutions section; list changed files for the developer.

### Review fix pass (ultracode adversarial review `wf_80ec4ede-d01`)

These supersede the wording of Tasks 1, 2 and 5 above:

- **One route string.** `CHANGE_ROUTE` in `plugins/harness/lib/harness_lib/commit_txt.py`:
  `A message changes only on the developer's ask: harness:amend-commit-msg -- <change> for a branch TXT,
  harness:c-msg <change> for a pending TXT.` `FINAL_LINE` and the hook `REASON` (`Commit-message TXT files are
  build output and final as saved.`) end with it; the B1 bullet repeats it (pinned by test).
- **Hook reason** names no skeleton-JSON route: that route bypassed the ask and could rebuild over TXT edits.
- **c-msg takes the requested change** (`argument-hint`, labeled `Requested change for this run:` line, Step 2
  rewrites a carried or canned message when a change is given): a bare rerun returns the same message.
- **messenger.md**: a skill read from disk gets `$ARGUMENTS` replaced with the dispatcher's arguments.
- **B1** names c-msg and branch-commit-msg, and makes the saved text the proposed commit message wherever an
  instruction asks for one.
