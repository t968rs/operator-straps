---
name: memo-guard
description: "Use when a review memo of bubbled issues is finished and the developer asks for an issue to be decided, marked or filled in."
argument-hint: "<memo path> [-- <guidance>]"
---

# memo-guard: the Decision lines stay the developer's

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token. Before it: the memo path. After it: guidance for this run,
applied to the session's own writing. It never reaches a command: no command below carries the guidance.

A bubble memo lists the issues only the developer may decide. Each entry ends in a Decision line the
developer fills in; the memo records the developer's call, so a Decision line written by an agent records
nothing.

## Rules

- **Never write a Decision line.** Not one word, not under time pressure, not when the analysis points one way.
- **Redirect the call.** State the analysis in the reply and ask the developer for the decision.
- **A refusal is information.** Read the `problem:` line, fix the input it names and run the same command
  again. Never work around a refusal by changing the file another way.

## Steps

1. **Read the memo** at the path given before the `--` token.
2. **Answer in the reply**: the issue, the analysis and the options, and a question naming the decision.
3. **Hand off.** Leave the memo unchanged and name the Decision lines still open.

## Judgment

| Situation | Call |
|---|---|
| The developer says one option is obvious | Ask the developer to write the line; the memo records whose call it is. |
| The arguments name no memo | Ask the developer for the path; never invent one. |
