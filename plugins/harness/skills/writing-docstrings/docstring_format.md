# Docstring Format Convention

Python docstrings use one of three layouts, chosen per symbol by its size and forks:

| Tier | Layout      | For                                                          |
|------|-------------|--------------------------------------------------------------|
| 1    | **Brief**   | a single-purpose function with no forks                      |
| 2    | **Compact** | everything between 1 and 3 (the common case)                 |
| 3    | **Full**    | a large function with forks                                  |

All three follow the shared rules at the end of this document.

---

## Choosing the tier

Answer for each symbol, in this order; the first match wins:

1. **Full (3)** when the body runs over about 50 lines **and** has two or more forks.
2. **Brief (1)** when the body has no forks **and** one summary line tells a caller everything they need. A usage
   constraint ("call once per process"), a side effect or a caveat the caller must know makes it compact. An
   extra flag-like parameter does not change this.
3. **Compact (2)** otherwise.

A **fork** is a point where the body can end differently: an `if` / `elif`, a conditional expression
(`x if c else y`), an `except` handler, each `case` of a `match`, a `raise` or `assert`, or a `return` that
does not end the function. A `return` ends the function when it is the last statement, or the last statement
of a branch of a final `if`, `with`, `try` or `match`. Comprehension filters are not forks, and neither is a
lazy-initialization guard: an `if x is None:` (or `if not x:`) with no `else`, `x` a name or attribute, whose
body only assigns `x` (imports aside).

The skill's tier command counts body lines and forks per function, suggests the tier, names the current layout
and flags format issues. The suggestion is a starting point; a symbol may take a different tier when the rule
above, applied by reading the body, says so.

---

## 1. Brief layout

### Structure

```python
def refresh_fields(snapshot: Snapshot) -> Snapshot:
    """
    Refreshes *field changes* in a ``Snapshot``
    """
```

### Rules

- One short summary, on its own line between the opening and closing `"""`, or on a single line with them
  (`"""Summary."""`).
- Never blank or separator characters only (`""""""`, a line of `-----`).
- Third-person verb: "Refreshes", "Stores", "Returns".
- No labels and no sections; no `Arguments:` or `Parameters:` block, even for a flag-like parameter.
- A summary that needs a second line, or a condition the caller must know, means the symbol is compact (2).

---

## 2. Compact layout

### Structure

```
def function_name(param1: str, param2: int) -> ReturnType:
    """One-line intro: a third-person verb phrase saying what the function does.

    Operation:
        first step,
        second step
    Rules:
        a behavior condition,
        another behavior condition
    Returns:
        the value; the failure path ("empty when...", "None when...")
    Raises:
        ValueError when <condition>
    Notes:
        why a rule exists
    """
```

### Intro

- Sits on the opening `"""` line.
- One line, third-person verb: "Builds", "Orders", "Returns", "Creates".
- A property, or a module's central function, may use a noun phrase: "Parsed header of ``path``, read on first
  access."
- Followed by one blank line when sections follow.

### Sections

Each section is a `Label:` at the docstring's indentation, with its items indented 4 more. No dashed underline and
no blank line between sections. Use only the labels that apply, always in this order:

| Order | Label                                | Holds                                                                            |
|-------|--------------------------------------|----------------------------------------------------------------------------------|
| 1     | `Operation:` / `Tries:` / `Columns:` | what the code does, step by step, or the shape it builds                         |
| 2     | `Rules:`                             | behavior conditions: lowercase fragments, each ending in a comma except the last |
| 3     | `Returns:`                           | the value, then the failure path                                                 |
| 4     | `Raises:`                            | `ExcType when <condition>`, one per line                                         |
| 5     | `Notes:`                             | why a rule exists, one item per reason                                           |

### Parameters

No `Parameters:` section; the signature carries the types. A parameter whose behavior matters is named in double
backticks inside the intro or an item.

### Reference

```python
def column_index(
        table_path: Path, *, leading: Union[str, List[str]] = None, columns: List[str] = None
) -> Dict[str, int]:
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

---

## 3. Full layout

### Structure

```
def function_name(param1: str, param2: int) -> ReturnType:
    """
    One-sentence summary describing what the function does.
    Additional context can follow on subsequent lines when the summary
    alone is insufficient to describe intent or usage constraints.

    Parameters:
    -----------
        param1: (str) Description of what param1 represents.
        param2: (int) Description of what param2 represents.

    Returns:
    --------
    ReturnType: Description of what is returned and relevant semantics.

    Raises:
    -------
        ValueError: The condition that raises it.

    Example:
    --------
        result = function_name("value", 42)
        downstream_call(result)
    """
```

### Summary

- Starts on the line after the opening `"""`.
- Begins with a third-person verb ("Creates", "Returns", "Validates", "Builds").
- Multi-sentence summaries are allowed when context is genuinely needed.

### Section headers

Each header is `HeaderName:` followed by a dashed underline on the next line, as wide as the header including
its colon. Sections are separated by one blank line.

### Parameters

Each parameter is indented 4 spaces: `param_name: (type) Description.`

- The type is in parentheses, inline with the name.
- An `Optional` parameter notes its default: `(Optional[str], default None)`.
- A multi-line description indents to align with the description start.

### Returns

`TypeName: Description.` at the docstring's indentation. A return that is `None` on one path and a value on
another documents both: `Optional[str]: The matched column name, or None if no match was found.`

### Raises

Each exception indented 4 spaces: `ExcType: The condition that raises it.`

### Example

Code indented 4 spaces, showing a realistic call and, when the return value's use is non-obvious, the next
downstream call.

### Reference

```python
def merge_column_map(source_table: str, target_table: str) -> ColumnMap:
    """
    Creates a column map for an append that matches columns between
    the source and target tables by name. It is meant for appends whose
    column definitions differ slightly between source and target, where
    a positional append would misplace values.

    Parameters:
    -----------
        source_table: (str) Path to the source table to copy from.
        target_table: (str) Path to the target table to append to.

    Returns:
    --------
    ColumnMap: A column map that can be passed directly to the append call.

    Example:
    --------
        column_map = merge_column_map("source.db/rows", "target.db/rows")
        append_rows(
            source="source.db/rows",
            target="target.db/rows",
            column_map=column_map,
        )
    """
```

---

## Shared rules

### Voice

Third person throughout; no "I", "we" or "you".

### Symbol references

A symbol, parameter, path or literal value in a docstring takes double backticks (` ``name`` `), the
reStructuredText inline literal that renders as code. Single backticks (`` `name` ``) are reStructuredText
interpreted text, which renders as italics; they belong in `#` comments, which no renderer touches.

### Line length

Every line, indentation included, fits the project's configured docstring line length
(`docstrings.line_length`, default 110). A long intro is shortened; a long item continues on the next line at the
item's own indentation.

### Separator lines

A line of only separator characters (`-`, `=`, `_`, `*`, `#`, `~`, `+`, `.`, `:`, `;`, `|`) appears only as the
dashed underline directly below a full-layout section label. No docstring is blank or made of separators alone.

### Citations

Docstrings, and the comments in the same body, carry no review or artifact citations: no report sections
("(report Section 3C, C1)"), PR numbers ("PR #1522"), review issue IDs ("I2:", "C1", "M3"), or plan, spec and
research-doc references. The rule or reason a citation annotated is stated on its own.

### Existing docstrings

| Existing docstring                                     | Treatment when the code is touched                                       |
|--------------------------------------------------------|--------------------------------------------------------------------------|
| Already in the layout its tier calls for               | kept as is, except the lines the tier command flags                      |
| Already in the full layout                             | kept as is, except the lines the tier command flags                      |
| A single-line `"""Summary."""` on a brief-tier symbol  | kept as is, except the lines the tier command flags                      |
| Placeholder ("Push.", "Get desc.", "Generate tables.") | rewritten from the body, in its tier's layout                            |
| Prose paragraph                                        | rewritten in its tier's layout; for full, sections added below the prose |
| No docstring                                           | none added unless asked                                                  |

A line the tier command flags (a long line, a citation, single backticks) changes even in a docstring kept as
is, and only as far as the flag requires; every other line stays byte for byte.

Content carried into a restyled docstring keeps its meaning; every item is checked against the body.

## What to Avoid

| Anti-pattern                                             | Correct form                                                 |
|----------------------------------------------------------|--------------------------------------------------------------|
| Brief: a `Parameters:` / `Arguments:` block              | The summary alone                                            |
| Compact: intro on the line after `"""`                   | Intro on the opening `"""` line                              |
| Compact: dashed underline under a label                  | `Label:` alone                                               |
| Compact: `Parameters:` block listing every argument      | Name a parameter in an item only where its behavior matters  |
| Compact: `Notes:` before another section                 | `Notes:` last                                                |
| Compact sections on a no-fork, single-purpose helper     | Brief                                                        |
| Full layout on a short function                          | Compact                                                      |
| `Returns` naming only the success value                  | Add the empty / False / None path                            |
| Sphinx (`:param x:`) or Google (`Args:`) style           | Not used                                                     |
| A citation such as "(report Section 3D)" or "I2:"        | The rule stated without the citation                         |
