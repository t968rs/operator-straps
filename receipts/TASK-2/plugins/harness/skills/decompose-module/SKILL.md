---
name: decompose-module
description: Use when cataloging a large Python module for decomposition, when asked to find unused functions in a file, when planning to break a monolith module into smaller modules, or when a file exceeds 500 lines and needs triage into keep/relocate/delete buckets.
---

# Decompose Module

## Overview

Catalog every symbol in a monolith module, measure external usage, and classify each as **keep-and-relocate**, **delete**, or **needs-review**. The output is a structured catalog (JSON + Word document) that a human reviews before any code moves.

**Core principle:** Collect all data mechanically first. Apply deterministic rules for clear cases. Flag ambiguous cases for human review. Never guess.

## When to Use

- Module exceeds ~500 lines and mixes multiple concerns
- User asks to catalog, inventory, or triage a module
- Planning a decomposition or refactor of a utility file
- User asks "what in this file is actually used?"

**When NOT to use:**
- Single-concern modules that are just long (one class, coherent API)
- Files the user wants to *read* or *understand*, not decompose
- Refactors where the target structure is already decided (use a plan skill instead)

---

## Four-Stage Pipeline

This skill uses a multi-model pipeline. Each stage has a designated model and clear handoff.

```
STAGE 1: PRE-FILTER (Haiku)     STAGE 2: FINALIZE (Opus)    STAGE 3: WRITE (Haiku x2)    STAGE 4: FEEDBACK
┌─────────────────────────┐     ┌──────────────────────┐    ┌─────────────────────┐       ┌──────────────────┐
│ Phase 1: Inventory      │     │ Review pre-filter    │    │ Agent A: catalog.json│       │ User reviews docx│
│ Phase 2: Usage Search   │──►  │ Correct errors       │──► │ Agent B: report.docx │──►    │ Extract comments │
│ Phase 3: Context Gather │     │ Finalize relocations │    │ (parallel dispatch)  │       │ Update catalog   │
│ Phase 4: Disposition    │     │ Resolve ambiguities  │    └─────────────────────┘       └──────────────────┘
└─────────────────────────┘     └──────────────────────┘
      mechanical                      judgment                     templated                   human loop
```

**Stage 1** produces a pre-filter JSON with evidence for every classification. Haiku does the legwork.
**Stage 2** reviews Haiku's output, corrects false positives/negatives, finalizes relocation targets. Opus makes the judgment calls.
**Stage 3** takes Opus's finalized catalog and produces output artifacts. Two Haiku agents run in parallel: one writes the JSON catalog, one writes the Word document.
**Stage 4** incorporates human feedback from Word doc comments into the catalog before planning begins.

---

## Orchestration: Single Opus Context Window

All three stages execute within **one Opus conversation**. Opus never leaves and re-enters. The sequence:

```
Opus receives user request
  │
  ├─ Read module TOC (first 30 lines)          ← ~300 tokens
  ├─ Grep symbol count (def/class/constant)    ← ~200 tokens
  │
  ├─ Dispatch Haiku: Stage 1 agents            ← fan-out
  │     (Phase 1+3 concurrent, then Phase 2 parallel search, then Phase 4)
  │
  ├─ Receive pre-filter JSON                   ← ~3,000 tokens for ~50 symbols
  │
  ├─ Stage 2: Review + finalize                ← Opus reasoning, same context
  │     (verify evidence, assign relocation targets, resolve ambiguity)
  │
  ├─ Dispatch Haiku x2: Stage 3 agents         ← fan-out (parallel)
  │     Agent A: write catalog JSON
  │     Agent B: write Word document
  │
  └─ Done. Report to user. Await feedback on the Word doc.
```

**Stage 4 (separate session or continuation):**

```
User says "I've added comments to the docx"
  │
  ├─ Extract comments from .docx (Python zipfile + xml.etree)
  │     unzip → word/comments.xml → parse w:comment elements
  │
  ├─ Map each comment to a catalog section via anchor text
  │
  ├─ Present extracted comments for confirmation
  │
  └─ Update catalog JSON + regenerate artifacts as needed
```

**Why this works:** Opus reads ~4,000 tokens of structured data (TOC + pre-filter JSON + sibling map), not the full module. The 2,388-line file is only ever read by Haiku via grep + targeted offset/limit reads. Opus's single context window covers setup, review, and dispatch -- no re-ingestion.

**What Opus does NOT read:**
- The full module file (Haiku reads it in pieces)
- Individual caller files (Haiku verified imports in Phase 2)
- The Word document template (Haiku follows the docx skill)

**Haiku prompt template for Stage 1:**

Include in every Stage 1 Haiku dispatch:
1. The full Phase 1-4 instructions from this skill (copy the relevant sections)
2. The module path and file path
3. The symbol range to process (e.g., "symbols at lines 1-283" or "symbols: get_np, get_exists_checker, ...")
4. The pre-filter output JSON format (from the "Pre-Filter Output Format" section)
5. Exclusion patterns: the module itself, worktree copies (`.claude/worktrees/` and any other worktree directory inside the project), `__pycache__`

**Haiku prompt template for Stage 3:**

Include in every Stage 3 Haiku dispatch:
1. The finalized catalog JSON (entire content)
2. For Agent A (JSON): the absolute path of `catalogs/Decompose.catalog.schema.json` (see "Catalog schema" below) + output path
3. For Agent B (Word doc): the document structure and formatting rules from the "Agent B: Word Document" section + the `docx` skill reference

**Catalog schema:** resolve `catalogs/Decompose.catalog.schema.json` against the project's pinned copy first
(`<schemas_dir>/catalogs/` from `.claude/harness.json`), else the plugin's `${CLAUDE_PLUGIN_ROOT}/schemas/catalogs/`.
It extends `catalogs/SymbolCatalog.base.schema.json` via `allOf`/`$ref`; both files must sit side by side and be
readable by the validator.

**Output directory:** `<artifacts.research>` from `.claude/harness.json` (project-relative).

---

## Stage 1: Pre-Filter (Haiku)

Dispatch Haiku subagents for Phases 1-4. These are mechanical -- no judgment required.

### Phase 1: Inventory

**Goal:** List every public symbol with its location, kind, and size.

**Steps:**
1. Count total lines (`wc -l`)
2. Grep for ALL definition patterns with line numbers:
   - Functions: `^def `
   - Classes: `^class `
   - Module-level constants: `^[A-Z][A-Z_0-9]+ =` (uppercase names assigned at module scope)
   - **Exclude** from constants: logger/printer bindings (`DEBUG`, `AM`, `LOG`, `LOGGER`), dunder names (`__all__`), and single-letter names. These are infrastructure, not public API symbols.
3. Read the first 30 lines for module-level docstring/TOC
4. For each symbol, read just its signature + docstring (use `offset`/`limit`)
5. Note any section-comment headers (e.g., `## === Section Name ===`)

**Inventory completeness rule:** Count ALL symbol types. Constants count as symbols. If the grep finds 8 functions and 2 constants, the inventory has 10 symbols, not 8.

**Output per symbol:**

```
name, kind (function|class|context_manager|constant|private_function),
line_start, line_end, line_count, docstring_summary (one line)
```

**Efficiency rule:** Never read the entire file in one pass if it exceeds 150 lines. Use grep to locate, then targeted reads.

---

### Phase 2: Usage Search

**Goal:** For each symbol, count how many files import or reference it *outside the module itself*.

**Steps:**
1. Split symbols into groups of 10-15
2. Dispatch parallel search agents, one per group
3. Each agent runs a TWO-PASS search per symbol:

**Pass 1 (definitive):** Grep for the explicit import statement:
```
from <module_path> import <symbol>
```
Every file matching Pass 1 is a CONFIRMED caller. This is the only evidence that counts as 100% confidence.

**Pass 2 (verification required):** Grep for bare references: `<module_name>.<symbol>` and standalone `<symbol>`. For each Pass 2 hit:
- Read the file's import block (first 30 lines)
- If the file imports from the target module, it is a confirmed caller
- If the file defines its OWN function/variable with the same name, it is a FALSE POSITIVE -- discard it
- If the file imports the same name from a DIFFERENT module, it is a FALSE POSITIVE -- discard it

4. Exclude: the module itself, worktree copies (`.claude/worktrees/`), `__pycache__`
5. Report per symbol: name, confirmed caller count, list of confirmed file paths

**Critical:** Search the project's entire source tree, not just the parent package.

**False positive traps:** These patterns produce false positives. Verify every one:
- A standalone module with the same name as a function (e.g., `create_regular_grid.py` vs function `create_regular_grid`) -- the module is a replacement, not a caller, unless it contains `from helpers import create_regular_grid`
- A file that instantiates the same class directly (e.g., `ExistsChecker()`) vs importing a factory function (`get_exists_checker`) -- these are different symbols
- Test files that mock or patch the symbol name without importing it

---

### Phase 3: Context Gather

**Goal:** Understand the neighborhood -- what sibling modules exist, what they do.

**Steps:**
1. Glob the parent package and its siblings: `parent_pkg/**/*.py`
2. Read the first 20-30 lines of each sibling module (docstring/imports reveal purpose)
3. If a tool registry or package map exists, read it
4. Build a lookup: `{module_path: one_line_purpose}`

This gives Stage 2 a menu of existing relocation targets.

---

### Phase 4: Disposition (Initial)

**Goal:** Classify each symbol using deterministic rules. No judgment calls, no hedging, no "likely."

Apply these rules IN ORDER. Every symbol gets exactly one disposition.

#### Rule 1: Confirmed external callers exist

```
IF external_usage_count >= 1 (from Phase 2 CONFIRMED callers only):
    disposition = "keep_and_relocate"
```

#### Rule 2: Zero external callers, but used internally by a Rule 1 symbol

```
IF external_usage_count == 0:
    Grep for this symbol's name WITHIN the same module file.
    IF a symbol already classified as "keep_and_relocate" calls this symbol:
        disposition = "keep_internal"
        note = "travels with <calling_symbol>"

    The grep must find an actual CALL SITE (e.g., `get_np()`, not just a comment or string).
```

#### Rule 3: Zero external callers, not used by any kept symbol

```
IF external_usage_count == 0 AND no kept symbol calls it:
    disposition = "delete"
```

#### Rule 4: Zero external callers, but only caller is ALSO being deleted

```
IF external_usage_count == 0 AND the only internal caller is itself disposition="delete":
    disposition = "delete"
    note = "internal caller <X> is also unused"
```

This prevents a chain of unused functions keeping each other alive. If A calls B, and A has 0 external callers, both are "delete" -- B does not get saved by A.

**CRITICAL -- Apply Rule 4 AFTER completing Rules 1-3 for ALL symbols.** Then do a second pass:
For every symbol classified as `keep_internal` in the first pass, check: is the symbol it "travels with" itself classified as `delete`? If yes, change the keep_internal symbol to `delete`.

**Worked example:**
1. `create_regular_grid` has 0 confirmed external callers (superseded by module). Rule 3 → `delete`.
2. `get_np` has 0 external callers. `create_regular_grid` calls `get_np()` at line 234. First pass Rule 2 → `keep_internal` (travels with create_regular_grid).
3. **Second pass Rule 4 check:** `get_np` travels with `create_regular_grid`, but `create_regular_grid` is `delete`. Therefore `get_np` → `delete`, note: "internal caller create_regular_grid is also unused."

A `keep_internal` symbol is only valid if the symbol it travels with is `keep_and_relocate`. If the parent is `delete`, the child is also `delete`.

#### Supersession check (apply before Rule 1)

Before counting a file as a confirmed caller, check for this pattern:
- A standalone module exists with the SAME NAME as the symbol (e.g., `create_regular_grid.py` for function `create_regular_grid`)
- That standalone module does NOT contain `from <source_module> import <symbol>`

If both conditions are true, the standalone module is a REPLACEMENT, not a caller. Do not count it. Add a note: "superseded by `<module_path>`."

#### Evidence requirements

Each disposition must cite its evidence:
- `"delete"` requires: "0 confirmed callers (Phase 2), 0 internal call sites (grep within file)"
- `"keep_internal"` requires: "called by `<symbol>` at line `<N>` in same file"
- `"keep_and_relocate"` requires: "confirmed import in `<file1>`, `<file2>`, ..."

### Pre-Filter Output Format

Stage 1 produces a JSON file with this structure:

```json
{
  "module_path": "dotted.import.path",
  "file_path": "relative/path.py",
  "total_lines": 2388,
  "prefilter_date": "2026-04-03",
  "symbols": [
    {
      "name": "symbol_name",
      "kind": "function",
      "line_start": 84,
      "line_end": 91,
      "line_count": 8,
      "docstring_summary": "One-line summary.",
      "external_usage_count": 0,
      "external_usage_files": [],
      "disposition": "delete",
      "evidence": "0 confirmed callers (Phase 2 Pass 1: 0 hits). 0 internal call sites.",
      "notes": ""
    }
  ],
  "sibling_modules": {
    "pkg/selections.py": "Selection utilities",
    "pkg/workspace.py": "Workspace creation and management"
  },
  "section_headers": [
    {"label": "Utility", "line_range": [1, 283]},
    {"label": "Workspace", "line_range": [284, 410]}
  ]
}
```

**Critical fields for Stage 2:** `evidence` must contain the raw search results (Pass 1 hit count, Pass 2 verification outcomes). This allows Opus to audit the classification without re-running searches.

---

## Stage 2: Finalize (Opus)

Opus reviews the pre-filter JSON and produces the finalized catalog. This is where judgment happens.

### Review Checklist

For each symbol in the pre-filter:

1. **Verify evidence matches disposition.** If Haiku wrote "0 confirmed callers" but listed files in `external_usage_files`, flag the contradiction.
2. **Check for false positives in `keep_and_relocate`.** Read the listed caller files' import blocks if any seem suspicious.
3. **Check for false negatives in `delete`.** For high-value symbols (classes, large functions), run a quick verification grep.
4. **Resolve supersession cases.** If a standalone module exists with the same name, verify it is a replacement.

### Relocation Recommendations

For each `keep_and_relocate` symbol, Opus assigns 1-3 target modules with confidence tiers.

#### Tier 1: HIGH confidence (deterministic)

| Heuristic | Rule | Example |
|-----------|------|---------|
| **Single caller** | If exactly 1 external file uses it, suggest inlining there | `gen_near` -> `smooth_simp.py` (sole caller) |
| **Name match** | If a sibling module name overlaps the symbol's domain keyword, suggest it | `selecting` -> `selections.py` |
| **Already exists** | If the symbol is imported by a module that clearly owns that domain, suggest it | `create_field_mapping_for_append` -> `append_with_mapping.py` |

#### Tier 2: MEDIUM confidence (heuristic)

| Heuristic | Rule | Example |
|-----------|------|---------|
| **Caller cluster** | If 60%+ of callers are in one package, suggest that package | Workspace functions -> `data_mgmt` |
| **Size threshold** | If `line_count > 200`, suggest a new standalone module | `HandleSmallFeatures` (353 lines) -> new `small_features.py` |
| **Co-dependency** | If symbols A and B call each other, they must move together; suggest a shared target | `create_clear_workspace` + `clear_a_folder` |

#### Tier 3: NEEDS REVIEW (ambiguous)

If none of the above heuristics match, or if two heuristics conflict:

```json
{
  "disposition": "keep_and_relocate",
  "confidence": "needs_review",
  "relocation_candidates": [],
  "notes": "4 callers across 3 packages; no dominant cluster. Requires human decision."
}
```

**Never guess.** An empty `relocation_candidates` with an honest note is better than a wrong suggestion.

### Dependency Chains

After assigning targets, verify:
- If symbol A calls symbol B (internal), both go to the same target
- If symbol A is imported by the module suggested as B's target, check for circular imports
- List all "must move together" pairs explicitly

### Finalized Catalog Output

Opus produces the complete catalog JSON conforming to `catalogs/Decompose.catalog.schema.json` (see "Catalog schema" below). This includes:
- Corrected dispositions (with audit trail if changed from pre-filter)
- Relocation candidates with confidence tiers and rationale
- Dependency chains
- Category groupings (from section headers)
- Summary statistics

---

## Stage 3: Write Artifacts (Haiku x2)

Dispatch two Haiku agents in parallel. Each receives the finalized catalog JSON as input.

### Agent A: Catalog JSON

Write the catalog JSON file to `<artifacts.research>/<module_name>_catalog.json`. The content is the finalized catalog from Stage 2 -- this agent formats and validates it against `catalogs/Decompose.catalog.schema.json` (see "Catalog schema" below).

### Agent B: Word Document (Required)

Generate a `.docx` report via `docx-js` (`npm install docx`). Use the finalized catalog JSON as the sole data source.

**Document structure:**

1. **Title page**: Module name, catalog date, total lines, total symbols
2. **Executive Summary**: Total symbols, used/unused counts, one-sentence verdict
3. **Category Breakdown**: One section per category (from section headers or inferred groupings)
   - Table per category: Symbol | Kind | Lines | Usages | Disposition | Target
4. **Recommended Relocation Map**: Target Module | Symbols | Total Lines
5. **Deletion Candidates**: Symbol | Lines | Reason
6. **Dependency Chains to Preserve**: "must move together" pairs with explanation

**Formatting rules:**
- Color-code dispositions: **blue** for RELOCATE, **red** for DELETE, **gray** for INTERNAL
- US Letter page size (12240 x 15840 DXA), 1-inch margins
- Arial font, 12pt body, heading styles for TOC compatibility
- Page numbers in footer
- Use `LevelFormat.BULLET` for lists (never unicode bullets)
- Tables use `WidthType.DXA` (never percentage), `ShadingType.CLEAR` for shading

### Optional: Markdown Report

If requested, also produce a Markdown report at `<artifacts.research>/<module_name>_catalog_report.md` following this structure:

```
# <Module Name> Decomposition Catalog

## Executive Summary
- Total symbols, used/unused counts, line counts
- One-sentence verdict (e.g., "Module can be eliminated entirely")

## Category Breakdown
For each category:
- Table: Symbol | Kind | Lines | Usages | Disposition | Target

## Recommended Relocation Map
- Table: Target Module | Symbols | Total Lines

## Deletion Candidates
- Table: Symbol | Lines | Reason

## Dependency Chains to Preserve
- List of "must move together" pairs with explanation
```

### Optional: JSON Schema

If generating a schema, include it as a separate file. The catalog JSON should validate against it.

---

## Stage 4: Incorporate Feedback

After Stage 3 artifacts are delivered, the user reviews the Word document and adds feedback as **Word comments**.
When the user says "I've added comments to the docx" (or similar), extract and incorporate that feedback.

### Why Comments (Not Inline Text)

Word comments live in a dedicated `word/comments.xml` inside the docx ZIP archive. Each comment has an author,
date, and anchor — making extraction unambiguous. Inline text edits require diffing the entire document body
against the original, which is fragile and error-prone for generated documents.

**Instruct the user to add feedback as Word comments, not inline text edits.**

### Extracting Comments from a .docx

A `.docx` file is a ZIP archive. Comments are in `word/comments.xml`. Use Python stdlib only (no external
dependencies):

```python
import zipfile
import xml.etree.ElementTree as ET

WML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

def extract_docx_comments(docx_path: str) -> list:
    """Extract all comments from a .docx file. Returns list of dicts."""
    comments = []
    with zipfile.ZipFile(docx_path, "r") as zf:
        if "word/comments.xml" not in zf.namelist():
            return comments
        with zf.open("word/comments.xml") as f:
            tree = ET.parse(f)
    for c in tree.getroot().findall(f"{{{WML}}}comment"):
        texts = [t.text for t in c.iter(f"{{{WML}}}t") if t.text]
        comments.append({
            "id": c.attrib.get(f"{{{WML}}}id"),
            "author": c.attrib.get(f"{{{WML}}}author"),
            "date": c.attrib.get(f"{{{WML}}}date", ""),
            "text": " ".join(texts),
        })
    return comments
```

**To find what each comment is anchored to**, parse `word/document.xml` for `w:commentRangeStart` /
`w:commentRangeEnd` markers and collect the text between them:

```python
def extract_comment_anchors(docx_path: str) -> dict:
    """Map comment IDs to their anchored text in the document body."""
    anchors = {}
    with zipfile.ZipFile(docx_path, "r") as zf:
        with zf.open("word/document.xml") as f:
            tree = ET.parse(f)
    root = tree.getroot()
    # Find all commentRangeStart elements and their IDs
    starts = {el.attrib.get(f"{{{WML}}}id"): el
              for el in root.iter(f"{{{WML}}}commentRangeStart")}
    ends = {el.attrib.get(f"{{{WML}}}id"): el
            for el in root.iter(f"{{{WML}}}commentRangeEnd")}
    # For each comment, collect text between start and end markers
    # (simplified: collect all w:t text in the same paragraph)
    for cid in starts:
        parent_para = starts[cid].getparent() if hasattr(starts[cid], "getparent") else None
        if parent_para is not None:
            texts = [t.text for t in parent_para.iter(f"{{{WML}}}t") if t.text]
            anchors[cid] = " ".join(texts)
    return anchors
```

### Incorporating Feedback

1. Extract comments using the functions above
2. Present extracted comments to the user for confirmation ("I found N comments -- here they are")
3. Map each comment to the relevant catalog section (by anchor text or section heading)
4. Update the catalog JSON with user decisions (changed dispositions, relocation overrides, etc.)
5. If dispositions changed, regenerate the relocation map

**Do NOT regenerate the Word doc** after feedback -- the user's annotated copy is the review artifact.
Update only the JSON catalog and markdown report (if one exists).

---

## Common Mistakes

| Mistake | What Happens | Fix |
|--------|-------------|-----|
| Reading the entire 2000-line file at once | Context overflow, missed symbols | Grep for symbols first, then targeted reads with offset/limit |
| Searching only the parent package for usages | Misses distant callers; undercounts | Search the entire source tree |
| Counting bare-name grep hits without verifying the import | False positives inflate usage counts | Always verify Pass 2 hits against the file's import block (Phase 2) |
| Counting a same-named module as a "caller" | A file `create_X.py` is the replacement for function `create_X`, not a caller | Apply supersession check: does the file actually `import` the function? |
| Counting `ExistsChecker()` as usage of `get_exists_checker` | Different symbols with related names | Pass 1 grep for exact import string is the only safe count |
| Marking internal helpers as "delete" | Breaks used symbols that depend on them | Grep for the symbol within the file; check if any Rule 1 symbol calls it |
| Chains of unused functions keeping each other alive | `A` calls `B`, both unused, but `B` gets "keep_internal" | Apply Rule 4: if A is also "delete", B does not get saved |
| Skipping constants in inventory | Undercounts total symbols | Grep for `^[A-Z][A-Z_0-9]+ =` alongside `^def` and `^class` |
| Counting logger/printer bindings as constants | `DEBUG`, `AM`, `LOG` shift the symbol window and crowd out real API symbols | Exclude infrastructure bindings: loggers, printers, single-letter names, dunder names |
| Classifying a helper as keep_internal when its parent is delete | Rule 4 not applied; dead chain survives | After Rules 1-3, do a SECOND PASS: every keep_internal must have a keep_and_relocate parent |
| Guessing relocation targets when heuristics don't match | Wrong suggestions erode trust in the catalog | Output `"needs_review"` with an honest note. Empty candidates is correct. |
| Using hedging language ("likely", "probably", "seems") | Creates ambiguity; invites judgment calls | State evidence: "0 confirmed callers" or "confirmed import in X.py" |
| Haiku attempting relocation recommendations | Low accuracy; wastes tokens on judgment calls | Stage 1 produces pre-filter only. Relocation is Opus's job (Stage 2). |

---

## Quick Reference

| Stage | Phase | Model | Input | Output |
|-------|-------|-------|-------|--------|
| 1 | 1. Inventory | Haiku | Module file | Symbol list with locations |
| 1 | 2. Usage Search | Haiku | Symbol list | Usage counts + file lists |
| 1 | 3. Context | Haiku | Package tree | Sibling module purposes |
| 1 | 4. Disposition | Haiku | Symbols + usages | Initial delete / keep_internal / keep_and_relocate |
| 2 | Review + Relocation | Opus | Pre-filter JSON | Finalized catalog with relocation targets |
| 3 | Write JSON | Haiku | Finalized catalog | `<module>_catalog.json` |
| 3 | Write Word doc | Haiku | Finalized catalog | `<module>_catalog_report.docx` |
| 4 | Extract feedback | Any | User-annotated .docx | Comment list mapped to sections |
| 4 | Update catalog | Any | Comments + catalog JSON | Revised `<module>_catalog.json` |
