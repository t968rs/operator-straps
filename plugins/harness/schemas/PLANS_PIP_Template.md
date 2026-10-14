# PR Implementation Plan (PIP) Template

**File location:** `<plans dir>/{PLAN_ID}_{Title}_PIP.md` (`<plans dir>` is the project's `artifacts.plans`, default `docs/PLANS`)
**Companion ActionPlan:** `<plans dir>/{PLAN_ID}_{Title}_ActionPlan.json`
**Schemas:** `ActionPlan.schema.json` (unified) and `prAttributes.schema.json` (PR-association fragment), read from the project's pinned schemas directory when present, else the harness plugin's `schemas/`

> **PLAN_ID** is a zero-padded 4-digit sequence number (e.g., `0001`, `0023`) that counts up within `<plans dir>`. The same number prefixes both the PIP markdown and the ActionPlan JSON for a plan.

## Header

```markdown
# Plan {PLAN_ID}: {Title}

> **For agentic workers:** Use [superpowers:subagent-driven-development](link) to execute task-by-task with two-stage review (spec compliance, then code quality).

**Plan ID:** {PLAN_ID}
**Plan created:** YYYY-MM-DD
**Execution model:** [serial | parallel (3 worktrees: A=CI, B=workflow, C=tests) | staged (phase 1, 2, 3)]
**Primary branch:** {branch} → {base_branch}    ← optional; per-PR branches live in PR Attributes below

## PR Attributes

One block per associated PR. Omit this section entirely for project-scoped plans (research, refactor, incident).

- **PR #{N}** (`{branch} → {base_branch}`)
  - Review: `docs/PR_REVIEWS/{NNNN}_{Title}.json`
  - PIP: `docs/PLANS/{PLAN_ID}_{Title}_PIP.md` (this file)
  - Merged: YYYY-MM-DD (or `open`)

- **PR #{M}** (`{branch} → {base_branch}`)
  - Review: `docs/PR_REVIEWS/{MMMM}_{Title}.json`
  - PIP: same
  - Merged: `open`

---
```

## Goal Section

```markdown
## Goal

One sentence: what does executing this plan accomplish?

Example: "Resolve 10 code review findings (2 critical, 5 important, 3 minor) from PR #512 test reorganization."
```

## JSON ↔ Markdown Contract Section (Template Block)

```markdown
## JSON ↔ Markdown Contract

- ActionPlan JSON is the source of truth for:
  - TODO checklist content (`items[].action`)
  - implementation-progress state (`items[].status`, `items[].evidence`)
  - verification references (`items[].verification_references`)
- PIP Markdown expands those JSON keys with visual flow, rationale, and evidence detail.
- If implementation deviates from JSON, update JSON first, then sync Markdown in the same task cycle.
- Markdown may lag briefly during execution, but it must be synchronized before branch close.
```

## Executive Summary (Optional)

```markdown
## Summary

Brief overview of the work:
- Count of items by priority
- High-level approach (e.g., "Split work across 3 parallel worktrees to avoid merge conflicts")
- Expected test pass rate before/after
```

## Task Structure

Each task maps to ONE ActionPlan item (one issue ID).

**Item IDs follow the pattern `[A-Z]{2,4}-[0-9.]+`** — 2-4 uppercase letters + `-` + digits and/or periods. Examples: `CRS-1`, `TASK-3.2`, `BUG-789`. Severity lives in the ActionPlan's `priority` field, not encoded in the ID.

```markdown
### Task {ID} — {Title}

**ActionPlan item:** the `items[]` entry with `id: {ID}`
**Markdown section key:** `{ID}` (copy to `items[].markdown_section`)
**Priority:** critical | important | minor | null
**Files to touch:**
- Create: `path/to/new_file.py`
- Modify: `path/to/existing.py:123-145`

**Worktree:** {free string or null}    ← if parallel execution

- [ ] **Step 1: {Action Description}**

Run: `exact command here`

Expected output:
```
output snippet
```

- [ ] **Step 2: {Verification}**

Run: `pytest tests/test_file.py::test_name -v`

Expected: `PASS` (N/N passed)

#### Verification references (mirror `items[].verification_references`)

- Commit: `abc1234`
- Test: `pytest tests/...`
- CI run: `https://github.com/.../actions/runs/...`
- Artifact/doc anchor: `<plans dir>/...#task-{id}`

#### Evidence details (expands `items[].evidence`)

Brief explanation of what the references prove, tradeoffs, and any caveats.

- [ ] **Step 3: Commit**

```bash
git -C "/path/to/worktree" add file1 file2
git -C "/path/to/worktree" commit -m "fix: resolve CRS-1 — add test to CI allowlist"
```

---
```

## Parallel Worktree Example

```markdown
## Worktree A: CI Configuration (Critical items CRS-1, CRS-2)

### Task A1: CRS-1 — test_points.py silently dropped from CI allowlist

- [ ] **Step 1:** Edit `.github/workflows/checks.yaml`
- [ ] **Step 2:** Add missing entry to `tests=()` array
- [ ] **Step 3:** Run linter: `ruff check .github/workflows/`
- [ ] **Step 4:** Commit and push

## Worktree B: Workflow Hardening (Important items CRS-3, CRS-4)

### Task B1: CRS-3 — bump_version.yaml: no None-guard on regex match

- [ ] **Step 1:** Edit `.github/workflows/bump_version.yaml`
- [ ] **Step 2:** Add `if not m: sys.exit('...')`
- [ ] **Step 3:** Test: `python -c "..."`
- [ ] **Step 4:** Commit and push

## Worktree C: Test Reorganization (Important CRS-5 through CRS-7, Minor CRS-8 through CRS-10)

### Task C1: CRS-5 — behavior_module fixture should live in conftest.py

- [ ] **Step 1:** Create `tests/points/conftest.py`
- [ ] **Step 2:** Move fixture from source
- [ ] **Step 3:** Update 5 importing files
- [ ] **Step 4:** Run tests: `pytest tests/points/test_points.py -v`
- [ ] **Step 5:** Commit
```

## Serial Execution Example

```markdown
## Sequential Execution

### Task 1: CRS-1 — Critical Issue

[steps...]

### Task 2: CRS-2 — Critical Issue

[steps...]

### Task 3: CRS-3 — Important Issue

[steps...]
```

## Final Section

```markdown
## Verification

Run full test suite after all worktrees merge or all serial tasks complete:

```bash
pytest tests/ -v
```

Expected: All N tests pass.

## Merge/Integration

After all tasks complete and tests pass:

1. Merge worktrees back to feature branch (or all serial changes committed)
2. Push feature branch: `git push origin feature_branch`
3. Open/update PR in GitHub
4. Update `<plans dir>/{PLAN_ID}_{Title}_ActionPlan.json`:
   - Mark items COMPLETE with evidence (commit SHA + test output or rationale)
   - Add/update the relevant entry in `pr_attributes[]`
```

---

## Schema Rules

1. **Every ActionPlan item maps to exactly one Task in the PIP** (and vice versa)
2. **Item IDs follow `^[A-Z]{2,4}-[0-9.]+$`** — severity is captured in the `priority` field, not the ID
3. **Every Task has numbered Steps with:**
   - Exact bash command (or code snippet)
   - Expected output
   - Verification command where applicable
4. **Every Task ends with a Commit step** — do not accumulate uncommitted changes
5. **Worktree labels in Task headings** if parallel execution (free string — `A`/`B`/`C` is a common convention, but not enforced)
6. **Step checkbox format:** `- [ ] **Step N:** {Description}`
7. **No vague language:** "run tests" ✗ → "run `pytest tests/points/test_points.py -v`" ✓
8. **Commit messages reference the item ID:** "fix: resolve CRS-1 — ..." or "chore: address CRS-7 — ..."
9. **PR Attributes section** appears once, near the top; each associated PR gets one block with review, pip, and merge status. Project-scoped plans (no PRs) omit the section entirely.
10. **Plan ID** is the 4-digit zero-padded sequence number; **both** the PIP and the ActionPlan filename carry it as prefix, and the ActionPlan JSON carries it in the `plan_id` field
11. **Per-task section key** should mirror `items[].markdown_section` so each JSON item has one Markdown section for expansion
12. **Verification references section** should expand the JSON `verification_references` list, not replace it
