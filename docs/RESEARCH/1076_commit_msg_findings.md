# Findings: issues #92 and #93 (commit-message skills)

Branch `1076-BUG-commit-messages`, cut from `main` at `976bdc6`. Date: 2026-10-24.

## #92: `branch-commit-msg` fork drops `--base`

**Evidence.** Fork transcript `agent-afb7cf96265a42305` (floodplain_development session `b872ab30`):

- The fork's prompt (the skill body) carried the substituted command:
  `branch_commit_msg.py capture --save --base 21df29c52`.
- The fork ran `capture --save` with no base, then replied: "The skill's example line carries `--base 21df29c52`,
  but you gave no base, so the project base applies."

**Root cause.** Argument substitution works; the haiku fork misread the substituted value. With `context: fork`,
`$ARGUMENTS` is replaced inline and no separate statement of the developer's arguments reaches the agent. The
substituted text reads as a template:

- Step 1's command sits next to a flags table that lists `--base REF` as an example.
- Line 34 becomes "`--base 21df29c52` holds the developer's arguments (a bare `REF`, `--base REF`, ...)", so the
  value looks like one more illustration.
- "Never choose or substitute a base yourself" then pushed the agent to drop what it took for an invented base.

`pr-sum` (also a fork) has no `$ARGUMENTS` placeholder, so Claude Code appends a labeled `ARGUMENTS: ...` line,
which the agent reads as input. A second exposure: `agents/messenger.md` tells the agent to read the named
skill's `SKILL.md` from disk first; that copy holds the literal `$ARGUMENTS`, which Bash expands to nothing.

## #93: main session rewrites a drafted commit message

**Evidence.** Main session `adf56f60` (floodplain_development), turns 214-243:

- The `c-msg` fork returned the receipt for `5001-todo-refresh_pending.txt`, message
  `Chore(todo): refresh TODO catalog, research stubs and snapshot` (the canned TODO message,
  `lib/harness_lib/canned_messages.py:28`, by design subject-only).
- The main session read the TXT, then hand-`Edit`ed it with a new subject and body, and reported "The agent's
  draft had a generic subject and no body, so I rewrote both."

The same failure ran in this repository's session for PR 91: the saved `Feature(a-w)` draft was re-presented
in chat as a rewritten `Fix(a-w)` message.

**Root cause.** Nothing tells the main session that a commit skill's saved TXT is final:

- "Output the receipt verbatim" and "The TXT is script output" sit in the skill bodies, which only the fork
  reads.
- `HARNESS_RULES.md` (the main session's standing rules) says when to draft messages, not what to do with a
  draft.
- The receipt names a subject-only message without saying it is intended, so a canned message looks like a weak
  draft.
- The user-global rule "propose a commit message" invites the main session to write its own.

## Fix options

| Id | Issue | Change | Enforcement |
|----|-------|--------|-------------|
| A1 | #92 | Skill body states the arguments as input: a labeled `Developer arguments:` line, Step 1 says the command already carries them; rewrite the line-34 sentence so it never substitutes the value into prose | prompt |
| A2 | #92 | `messenger.md`: a forked skill's prompt is the skill; do not re-read its `SKILL.md` from disk | prompt |
| A3 | #92 | Raise the `branch-commit-msg` fork from `haiku` to `sonnet` | model |
| B1 | #93 | `HARNESS_RULES.md`: a commit skill's saved TXT is the message; relay it as saved, never rewrite it in chat or on disk; changes go through `harness:amend-commit-msg` on the developer's ask | prompt, every session |
| B2 | #93 | `build` receipt gains a final line marking the message as final and naming `harness:amend-commit-msg` for changes; canned blocks are labeled as canned | script, tested |
| B3 | #93 | PreToolUse hook denies `Edit`/`Write` on `*.txt` under `artifacts.commit_messages` (every skill writes the TXT through `build`) | hook, tested |

## Resolutions

- 2026-10-24: the developer agreed to all six options: A1, A2, A3, B1, B2 and B3.

## Evidence (2026-10-24, plan `docs/superpowers/plans/2026-10-24-commit-msg-guards.md`)

| Id | Change | Test |
|----|--------|------|
| B2 | `receipt` ends with `FINAL_LINE`, tags canned blocks `[canned]` (`scripts/branch_commit_msg.py`) | `tests/scripts/test_branch_commit_msg.py` |
| B3 | `hooks/guard_commit_txt.py`, PreToolUse `Write\|Edit` | `tests/hooks/test_guard_commit_txt.py`, `tests/contract/test_hooks_json_paths.py` |
| A1, A3 | labeled arguments line, line-34 rewrite, `model: sonnet` (`skills/branch-commit-msg/SKILL.md`) | `tests/skills/test_branch_commit_msg_skill_contract.py` |
| A2 | forked-skill prompt is not re-read (`agents/messenger.md`) | `tests/skills/test_messenger_agent_contract.py` |
| B1 | "A drafted commit message is final as saved." (`rules/HARNESS_RULES.md`) | `tests/hooks/test_session_rules.py` |

Plan test set: 242 passed; ruff `--no-cache` clean on every changed `.py`. Each new test was run red first.
Harness plugin version 0.28.0. Not run: the full suite and Windows CI (developer-owned); a live forked
`/harness:branch-commit-msg --base <ref>` run.
