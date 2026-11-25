# Comment format

Two kinds of `#` comment carry this convention: **section dividers**, which give a large module an outline,
and **process comments**, which say what the code cannot. Docstrings follow `writing-docstrings`; this file
covers `#` comments only.

## Section dividers

Every rule and minor divider line is exactly the project's `comments.divider_width` long (default 88),
indentation included; title and sentence lines are free length. `comment_sections.py` measures it and prints
the canonical line on each `width` flag; never count dashes by eye.

### Major: a banner per top-level group

```python
# --------------------------------------------------------------------------------------
# Immutable ranking
# --------------------------------------------------------------------------------------
```

A rule (`# ` and dashes), a title line, then a closing rule at the same indentation. Lines between the title
and the closing rule may add a sentence about the group:

```python
# --------------------------------------------------------------------------------------
# Core attribution logic (thread-safe)
# Every public function here takes the module lock; helpers assume it is held.
# --------------------------------------------------------------------------------------
```

### Minor: one line per group inside a major section or a class body

```python
# -- row helpers -----------------------------------------------------------------------
```

`# -- `, the title, a space, then dashes to the width. Inside a class body the line starts at the body's
indentation and still ends at the width.

### Which forms are not canonical

`comment_sections.py` flags each of these; none is written new:

| Written | Flag |
|---|---|
| `### ======= PROCESSING CLASSES ============ ###` | `style` |
| `# ----------------------------------------- scaffold` (title after the dash run) | `style` |
| a rule with no title, or a rule and title with no closing rule | `banner` |
| `# -- helpers` (a minor line with no closing dash run) | `style` |
| a rule or minor line shorter or longer than the width, `# -- helpers --` included | `width` |

An existing non-canonical divider is rewritten only when the work rewrites the block it heads, or on an
explicit ask for a section pass. A module the work does not change keeps every comment as it is.

### When a module gets dividers

- A module the work creates gets them once it holds more than one group of definitions (helpers and the
  public functions built on them, a class and its factories, readers and writers). A module with one group
  gets none.
- An existing module gets them only on an explicit ask ("add section comments", "outline this module").
- A title names what the group holds: `Row helpers`, `Public API`, `Exporter`. No numbering, no ids, no
  citations.

Order the module so each group sits under its divider: constants and types, then helpers, then the
functions and classes built on them. Leave two blank lines before a module-level major divider and one
after it; a minor divider takes one blank line before and none after.

## Process comments

A process comment states what the code cannot show:

- why one branch wins over another;
- an ordering the code depends on;
- an invariant a later line relies on;
- a constraint from outside the module (a library's behavior, a format another component parses);
- a unit or value whose meaning is not in its name.

One line where it fits, directly above the line it explains, or at the end of a short declaration:

```python
    # An explicit method wins over tier selection -- only AUTO defers to the tiers.
    if method is not AreaMethod.AUTO:
        ...
```

```python
    __members__: dict  # populated by EnumMeta when mixed with Enum
```

A comment never:

- restates the next line (`# loop over the rows`, `# return the total`, `# sort the entries`);
- carries a PR number, review item, ticket id, plan or report reference: the commit message carries those,
  and the comment states the reason itself;
- speaks in the first or second person;
- keeps commented-out code.

A request for "thorough" comments asks for the reasons above, stated fully; it is met with more reasons,
never with narration.

Write `--` for a dash and single backticks around a name; no Unicode dashes or arrows.

## The section command

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/skills/writing-comments/commands/comment_sections.py" <file.py> [<file.py> ...]
```

It prints the outline and the flags of each file, in line order:

```
src/mod.py:12: major Row helpers
src/mod.py:40: minor quoting
src/mod.py:77: minor writers
src/mod.py:77: flag width: # -- writers --- -> # -- writers ---------------------------------------------------------------------------
```

or `src/mod.py: no dividers`. A `width` flag ends `-> <canonical line>`: the rule or minor line at that
comment's indentation and the project's width, ready to paste over the flagged one. It writes nothing. A `problem:` line on stderr (exit 1, nothing on stdout) names what to fix: a missing or
non-`.py` path, source that does not tokenize, no path given, or an invalid configuration.
