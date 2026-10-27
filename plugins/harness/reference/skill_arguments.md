# Skill arguments: the `--` guidance tail

Every user-invocable harness skill takes an optional tail after a standalone `--` token:

```
/harness:<skill> <own arguments> -- <guidance>
```

## Splitting

Split `$ARGUMENTS` at the first standalone `--` token: one at the start, or with whitespace on both sides. A
flag such as `--base` or `--no-fetch` is not standalone.

- **Before the token:** the skill's own arguments (flags, ids, refs, a PR number, a path), parsed exactly as
  the skill states.
- **After the token:** guidance for this run, free text that may name paths. No token: no guidance, and the
  run is unchanged.

A skill whose own arguments are free text (a requested change, a question, a note) treats a leading `--` as
optional: `-- <text>` and `<text>` are the same invocation.

## Applying guidance

- Guidance is the developer's instruction for this run. Follow it wherever the skill leaves room: focus,
  emphasis, extra material to read or include, an output preference.
- A path in guidance is resolved against the project root and read as asked. Naming a path does not permit
  editing it.
- Guidance never waives a rule of the skill, a harness rule (commit and push ownership, branch safety, a
  Stop-hook sentinel) or the project's CLAUDE.md. On a conflict, report the conflict and follow the rule.
- A skill that dispatches subagents says in its own body which dispatches carry the guidance. Such a prompt
  ends with one `Developer guidance:` line holding the guidance verbatim, newlines folded to spaces. A
  dispatch the skill does not name gets none.
- The tail is prose for the session. It never lands on a command line, in a script argument or in a shell
  heredoc: commands carry only the arguments before the token, and a `$ARGUMENTS` placeholder never sits on a
  line of a fenced command.
- A `--` argument that appears inside pasted material (for example pytest's `-- Docs:` line) is not a split
  point when the skill says where to look for the token.
