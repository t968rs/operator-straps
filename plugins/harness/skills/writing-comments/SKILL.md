---
name: writing-comments
description: Use when writing or editing Python `#` comments, when creating a Python module that holds more than one group of definitions, when asked to add section dividers or outline a large module, or when choosing what a process comment should say.
---

# writing-comments: section dividers and process comments

Two kinds of `#` comment carry this convention, both defined in `${CLAUDE_SKILL_DIR}/comment_format.md`:

- **Section dividers** give a module an outline: a rule / title / rule banner per top-level group and a
  `# -- name ----` line per group inside one, every rule and minor line exactly `comments.divider_width`
  long (default 88), indentation included; title and sentence lines are free length.
- **Process comments** state what the code cannot show: why a branch wins, an ordering the code depends on,
  an invariant, an outside constraint. One line where it fits; never a restatement of the next line, never a
  PR, review, ticket or plan id.

Read the format file before writing either kind.

## A new module gets dividers

A module the work creates that holds more than one group of definitions (helpers and the functions built on
them, a class and its factory, readers and writers) gets a major divider per top-level group before it is
called done, and minor dividers inside a group or a class body when the group itself splits. A one-group
module gets none. Writing the module without dividers "because it is short" leaves the next reader to find
the groups; four definitions in two groups is already two sections.

Order the module so each group sits under its divider, then measure it:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/skills/writing-comments/commands/comment_sections.py" <file.py>
```

It prints one `major` or `minor` line per divider and one `flag` line per divider off the convention. Fix
every flag in the lines written, rerun until none is left, and end the reply with `comment_sections.py` by
name and its last output, so a reader can tell the outline was measured.
Never count dashes by eye: the command measures the width, and a `width` flag ends `-> <canonical line>`,
the exact rule or minor line to paste at that comment's indentation.

## Scope

- **Existing modules:** dividers only on an explicit ask ("add section comments", "outline this module").
- **Existing comments:** rewritten only inside the code the work changes. A non-canonical divider is
  rewritten only when the work rewrites the block it heads, or on that explicit ask.
- **A module the work does not change** keeps every comment and divider as it is, however inconsistent.
  Offer a section pass in the reply instead.

## Quick reference

| Situation | Call |
|---|---|
| Creating a module with two or more groups | Major dividers per group, minor inside; run the command; clear its flags |
| Creating a one-group module | No dividers |
| Asked to outline an existing module | Run the command first, then add or rewrite dividers; rerun until no flag |
| Editing one function in a module with odd dividers | Leave dividers outside the rewritten block; rewrite the one heading a block the work rewrites; offer a section pass in the reply |
| Asked for "thorough" comments | More reasons, stated fully; never narration |
| A comment would repeat the line below it | Delete it |
