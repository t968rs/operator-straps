---
name: efficient-file-reading
description: Use when reading source files longer than 150 lines, when the same file has already been read earlier in the conversation, or when searching for a specific symbol, function, class, or section. Prevents redundant full-file reads by enforcing a Grep-first workflow before issuing Read calls.
---

# Efficient File Reading

## Overview

Reading a 500-line file to find a 20-line function wastes tokens and slows every agent task.
Core principle: **locate first, then read only what is needed.**

## Pattern

```
Step 1 — Grep to get line number
Grep pattern="class RunSampling"  →  line 247

Step 2 — Read only that section
Read processing.py offset=247 limit=60
```

## Rules

| Situation | Action |
|-----------|--------|
| Unknown location in a large file | Grep first to get line number, then partial Read |
| File already read earlier this session | Reuse the line range from the earlier read — do not re-read in full |
| File under ~150 lines | Full read is fine |
| File has a module-level docstring or TOC | Read lines 1–30 first to orient, then target the section |
| Need multiple symbols from same file | One Grep per symbol, then one partial Read per section |

## Quick Reference

```
# Find a class
Grep pattern="class PipelineConfig"         →  returns file + line

# Find a function
Grep pattern="def run_processing"           →  returns file + line

# Find a constant / Enum member
Grep pattern="SamplingMethod\."             →  returns usages + definition

# Read a section (60 lines starting at 247)
Read path/to/file.py offset=247 limit=60

# Orient in a new large file (top 30 lines only)
Read path/to/file.py offset=1 limit=30
```

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `Read bigfile.py` with no offset/limit | Grep for the target symbol first, then partial Read |
| Re-reading the same file three steps later | Note line ranges when first reading; reference them later |
| Grepping for a symbol, getting line 312, then `Read` from line 1 | Set `offset=312`, not 1 |
| Scanning only top half of file and missing the definition | Let Grep search the whole file; read only the match |

## Notes

- `offset` is 1-based (line 1 = first line of file).
- `limit` is a line count, not an end-line number. `offset=247 limit=60` reads lines 247–306.
- When unsure how long a section is, start with `limit=80` and extend if the closing delimiter is not reached.
