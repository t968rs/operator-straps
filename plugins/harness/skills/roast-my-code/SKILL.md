---
name: roast-my-code
description: Use when the user asks for a code review, says "review this", "roast my code", or "what do you think of this code".
argument-hint: "[<path> | PR #<n> | <commit>..<commit>] [brutal|gentle]"
---

# Roast My Code

User-facing entry for the roast-my-code review voice. This skill is a thin
delegator — all review content, tone, and output rules live in the
`harness:roast-my-code` agent. The skill exists only so the user can trigger a
roast explicitly (typing `/roast-my-code` or prose like "roast my code"); the
agent does the work in an isolated context window so the main session stays
unburdened.

## Steps

1. **Resolve scope.** If the user named a file, directory, PR number, or
   commit range, that is the scope. If not, ask — do not guess. Acceptable
   scopes:
   - `<path>` (file or directory under the repo)
   - `PR #<n>` (resolves to the PR's diff against its base branch; for the
     default, the project's configured `base_branch` in `.claude/harness.json`)
   - `<commit>..<commit>` or `HEAD~N..HEAD`
   - Pasted code in the user's message
2. **Dispatch the agent.** Call `Agent(subagent_type="harness:roast-my-code", ...)`
   with a prompt that:
   - Names the resolved scope verbatim (path, PR number, or pasted snippet).
   - Includes any user-provided intensity hint (`brutal`, `gentle`, default
     unspecified). The agent reads its own tone rules from its definition;
     do not restate them here.
   - Does **not** pre-summarize, pre-grade, or pre-filter findings. The
     agent reads the code; the dispatcher does not.
3. **Return the agent's response verbatim.** Do not editorialize. Do not
   soften. Do not add a preamble like "the agent says…" — the user asked for
   a roast, the agent produced one, the conduit is invisible.

## Out of scope for this skill

- **Don't do the review in the main session.** Even when a roast could happen
  inline (e.g. one-line snippet with an obvious bug), still dispatch — the cost
  of a subagent call is lower than the cost of two different roasts coming out
  of this skill depending on who invoked it.
- **Don't paraphrase the agent's output.** Verbatim or nothing.
- **Don't add CI-eligibility footnotes or fix-it-yourself offers.** The
  roast is a review, not a remediation contract. If the user wants fixes
  applied, they'll ask in a follow-up turn.

## Why the split

Skills are entry points for the active session; agents do isolated work.
Roasting code is isolated work — reading a diff in full, holding it in a
fresh context, producing a structured roast. Doing that in the main session
burns context the user wants for the surrounding conversation. The skill is
the doorbell; the agent answers the door.
