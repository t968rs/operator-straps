---
name: writing-docstrings
description: Use when writing, restyling or reformatting Python docstrings, when a docstring is a placeholder such as "Push.", "Get desc." or "Generate tables.", when a docstring is a paragraph of prose describing behavior rules, or when choosing a docstring layout (brief, compact or full).
argument-hint: "<file> [<symbol> ...] [-- <guidance>]"
---

# writing-docstrings: three docstring tiers, chosen per symbol

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. Before
it: the files and symbols in scope; with none, the scope is what the developer's request names. After it:
guidance for this run (a tier preference, a symbol to look at hard). The guidance never reaches the command.

Every docstring is one of three tiers: **1 brief**, **2 compact**, **3 full**. The tier is decided per symbol
before a word of the docstring is written. The convention is `${CLAUDE_SKILL_DIR}/docstring_format.md`. It is
the project's format: no Google (`Args:`), numpy or Sphinx (`:param:`) style, whatever the existing code mixes.

## What a restyle touches

- **Only placeholders, prose paragraphs, blank docstrings and docstrings the command flags are rewritten.**
  Words such as "restyle", "tidy", "standardize" or "make consistent" cover these and nothing else.
- **A symbol without a docstring stays without one** unless the developer asks for new docstrings in so many
  words. A reviewer's "docs are thin", "you are in those files anyway", a deadline or a lead's wish is not that
  ask; neither is an empty module, which gets no module docstring. Name each undocumented symbol in the reply and
  ask whether to add docstrings to them.
- **"Consistent" means each docstring in its tier's layout, not one layout everywhere.** A docstring already in
  the layout its tier calls for, or in the full layout, stays byte for byte, even on a short function that
  would get compact if written fresh. Name the docstrings kept and why, so the developer sees they were read.
- **A caveat survives the restyle.** A usage constraint, side effect or failure the current docstring states is
  carried into the new one; a request to "keep it light" shortens wording, never drops a caveat.

## Procedure

1. **Measure.** Run the tier command with the Bash tool on each file in scope, naming the symbols in scope:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/skills/writing-docstrings/commands/docstring_tiers.py" <file> [<symbol> ...]
   ```

   Each line reports `lines=`, `forks=`, `suggest=`, `current=` and any flags (`long-lines`, `single-backticks`,
   `citation`, `section-order`, `unknown-label`, `misaligned`, `blank`, `separator-line`). `unknown-label` names
   a label outside the convention (`Args:`, `Logic:`); `misaligned` is a line indented left of the opening
   `"""`. The line limit is the project's `docstrings.line_length` (default 110). A one-line brief
   (`"""Summary."""`) is fine; a docstring that is blank or only separator characters is not, nor is a
   separator-only line anywhere except the dashed underline under a full-layout label. A `problem:` line (a
   symbol the file does not define, a file that does not parse) names the input to fix.

2. **Answer "1, 2 or 3?" for each symbol**, as one line in the reply, before its docstring when the docstring
   is pasted back: `<symbol>: tier <n> - <lines> lines, <forks> forks; <reason>`. The line goes to the
   developer, never into the file. The first match wins:
   - **3 full**: body over about 50 lines **and** two or more forks.
   - **1 brief**: no forks (one path: no branch, fallback, early return or raise of its own) **and** one summary
     line tells a caller everything. A usage constraint ("call once per process"), side effect or caveat the
     current docstring states makes it compact. A flag-like parameter does not change this.
   - **2 compact**: otherwise.

   A lazy-initialization guard (`if self._x is None:` that only fills a cached value) is not a fork. The
   command's `suggest=` counts forks the same way but cannot see caveats; read the body and the current
   docstring, and state the reason when the answer differs.

3. **Write the docstring** in that tier's layout (below).

4. **Re-run the command** on the same symbols: `current=` matches each tier and no flags remain.

## Tier 1: brief

```python
def refresh_fields(snapshot: Snapshot) -> Snapshot:
    """
    Refreshes *field changes* in a ``Snapshot``
    """
```

One short summary on its own line, third-person verb, between the opening and closing `"""`. No labels, no
`Parameters:` or `Arguments:` block.

## Tier 2: compact

```python
def column_index(table_path, *, leading=None, columns=None) -> Dict[str, int]:
    """Maps each column name of ``table_path`` to its position in a row.

    Rules:
        generated columns excluded,
        ``columns``, when given, keeps only the existing columns it names,
        ``leading`` (for example "rowid") comes first
    Returns:
        {column name: index}; empty when the table's columns cannot be listed
    Raises:
        ValueError when ``table_path`` is empty
    """
```

1. **Intro** on the opening `"""` line: one line, third-person verb. A property may use a noun phrase.
2. **One blank line**.
3. **Sections**: `Label:` at the docstring's indentation, items indented 4 more, no dashed underline, no blank
   line between sections. Only the labels that apply, always in this order:

| Order | Label                                | Holds                                                                            |
|-------|--------------------------------------|----------------------------------------------------------------------------------|
| 1     | `Operation:` / `Tries:` / `Columns:` | what the code does, step by step, or the shape it builds                         |
| 2     | `Rules:`                             | behavior conditions: lowercase fragments, each ending in a comma except the last |
| 3     | `Returns:`                           | the value, then the failure path ("empty when...", "logged and returns False")   |
| 4     | `Raises:`                            | `ExcType when <condition>`, one per line                                         |
| 5     | `Notes:`                             | why a rule exists, one item per reason                                           |

4. **Closing `"""`** on its own line.

No `Parameters:` section; a parameter whose behavior matters is named in double backticks inside an item.

## Tier 3: full

Read `${CLAUDE_SKILL_DIR}/docstring_format.md`, section "3. Full layout", and follow it: summary on the line
after `"""`, then dashed `Parameters:`, `Returns:`, `Raises:` and `Example:` sections.

## All tiers

- **Symbols** take double backticks (` ``name`` `); single backticks only in `#` comments.
- **Line length:** the project's `docstrings.line_length` (default 110), indentation included; a long item
  continues at its own indentation.
- **Citations** (report sections, PR numbers, review IDs such as "I2:", plan or spec references) are dropped
  from the docstring and from comments in the same body; the rule they annotate stays.
- **Accuracy:** every item is checked against the body. A defect the body shows (a counter that drifts, an
  unhandled empty input) is reported to the developer, not fixed in a docstring pass.
