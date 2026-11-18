# Frozen plans stay frozen: receipts, a plan-bound DesignEvolution, a live HTML PIP

Issue: https://github.com/t968rs/operator-straps/issues/258. Branch `2150-plan-refreeze`.
Lineage: `main --> 1150-canned-messages --> 2150-plan-refreeze`.

## Intent

A frozen plan is edited all through its execution. `plan.py record` writes each item's status, evidence and
sealed record into the plan JSON and re-renders the PIP; a small change found mid-build (an extra file, a test
that has to differ from the planned one) goes in through `plan_api.write` plus `freeze --refreeze`, which reruns
`check` and `red` and breaks the seal of every item whose files or tests moved, so those items are recorded
again. The loop is write, freeze, then implement / record / refreeze until done.

The plan is not wrong when this happens. What the agent needs is a place to say what changed and why, and a
place to put proof of done, neither of which is the plan. `DesignEvolution.json` was meant to be the first
(`plugins/harness/rules/HARNESS_RULES.md:118`); it has a schema and no code. Receipts become the second.

After this change a frozen plan file, and the PIP rendered at its freeze, are never written again during
execution. Ticks, commit evidence and test results go to receipts; small changes go to the plan's
DesignEvolution; a receipt that differs from its plan item cites the DesignEvolution entry that explains the
difference. A refreeze remains for a real design change, on the developer's ask, never as a step of execution.

## Goals

- `record` writes a receipt file and nothing else of the plan: not the plan JSON, not the PIP.
- A change found during execution is recorded as a `DesignChange` in the plan's `DesignEvolution.json`
  through a validating API, without touching the plan.
- A receipt may differ from its item (an extra file, a substituted test node) only by citing a
  `DesignChange` that exists and names that item. `record` runs the substituted nodes in place of the planned
  ones.
- `check`, `verify`, `lanes` and the dependency gate read status from receipts.
- The PIP is an HTML page rendered once at freeze. Opened from disk (`file://`) it shows live progress:
  receipts and DesignEvolution entries arrive through a derived script file it reloads on a timer.
- Plans frozen before this change keep working unchanged.

## Non-goals

- Changing what `check` proves about a plan's claims (anchors, sweeps, decisions, red).
- Detecting files an item touched without declaring them. A commit may carry several items; the driver does
  not attribute files to items. A receipt declares its extra files; the citation is the accountability.
- Rewriting finished plans 0001-1012 to the new scheme.
- Ad-hoc plans not made by `plan.py` (the `{PR}_ActionPlan.json` / `{PR}_PIP.md` pair in `HARNESS_RULES.md`
  "Agent accountability"): their rule is untouched.

## Anti-goals

- Any execution step that writes the frozen plan JSON or its PIP.
- Models that are dictionaries with a type name. Every shape below is a class with typed fields and
  validation; every nested object is its own class (`DesignChange.issue` is a `ChangeIssue`, never a dict).
- A PIP that needs a running process to show anything.

## Approaches considered

1. **Keep records in the plan, make refreeze cheaper.** Leaves the plan edited on every tick; rejected by the
   developer: the plan must divorce from execution edits, tick marks and commit evidence included.
2. **Receipts, with the plan re-derived through applied DesignEvolution entries** (the driver applies each
   entry to the item before judging its receipt). Machine-applying free-form changes needs a change grammar
   for every field; rejected in conversation.
3. **Receipts that cite DesignEvolution entries** (chosen). The plan stays as frozen; the receipt says how
   the work differed and points at the entry that explains it; the driver checks the citation and runs the
   substituted tests.

For the live PIP: a local server (`plan.py view`) and a Claude Code pane mod were weighed against a static
HTML page reading a derived `.js` sidecar. The developer chose the sidecar. A spike on 2026-11-10 confirmed
Firefox on `file://` reloads a sibling `<script src>` on a timer and sees new contents, with and without a
cache-busting query.

## Files of a plan

All under the project's `artifacts.plans` (default `docs/plans`), for plan `NNNN`:

| Path | Written by | When |
|---|---|---|
| `NNNN_<Title>_ActionPlan.json` | `plan_api.write`, `plan.py freeze` | before freeze; again only on a refreeze |
| `NNNN_<Title>_PIP.html` | `plan.py render`, `freeze` | before freeze; at freeze; at a refreeze |
| `NNNN/tests/<repo path>` | the agent | before freeze (unchanged) |
| `NNNN/DesignEvolution.json` | `evolution_api.add` | any time |
| `NNNN/receipts/<ITEM>.json` | `plan.py record` | each record of that item (replaced) |
| `NNNN/live.js` | `record`, `evolution_api.add`, `render`, `freeze` | after each of those writes |

One receipt file per item (design call: a re-record replaces one small file, and records of different items
never touch the same file, whichever checkout writes them). `live.js` is derived and listed in `.gitignore`
(design call: it duplicates tracked data; any `record`, `render` or evolution write rebuilds it, and
`plan.py render` rebuilds it on a fresh checkout).

## Models

All pydantic `BaseModel`, closed (`extra="forbid"`), in the style of `plan_models.py`. Enums in
`plan_enums.py` (or a new `evolution_enums.py`); schemas generated from the models.

### DesignEvolution (`harness_lib/evolution_models.py`)

```python
class ChangePhase(str, Enum):        # unchanged values
    SPEC_REVIEW = "spec-review"; PR_BOT_REVIEW = "pr-bot-review"
    PLAN_REVIEW = "plan-review"; POST_EXEC_START = "post-exec-start"

class IssueCategory(str, Enum): ...   # the twelve values of the current schema
class OutcomeCategory(str, Enum): ... # the nine values of the current schema

class ChangeOriginal(BaseModel):
    """What the source document indicated before the change."""
    doc: str                          # a key of DesignEvolution.primary_documents (validated)
    location: str
    indicated: str

class ChangeIssue(BaseModel):
    """The problem found in the original."""
    category: IssueCategory
    why_categorical: str
    why_free_form: str

class NewOutcome(BaseModel):
    doc: str                          # a primary_documents key (validated)
    indicated: str

class WhyNewOutcome(BaseModel):
    category: OutcomeCategory
    free_form: str

class DesignChange(BaseModel):
    id: str                           # ^(S|PR|P|EX|CX)\d+$ ; the 1-2 digit cap is lifted
    discovered_by: str
    phase: ChangePhase
    items: List[str] = []             # plan item ids the change touches; validated against the plan
    original: ChangeOriginal
    issue: ChangeIssue
    new_outcome: NewOutcome
    why_new_outcome: WhyNewOutcome
    date: str                         # _DATE

class FindingRef(BaseModel):
    id: str                           # must name a change
    rationale: str

class EvolutionSummary(BaseModel):
    """Optional until the PR closes; counts are computed, not typed by hand."""
    highest_impact_finding: Optional[FindingRef] = None
    most_embarrassing_finding: Optional[FindingRef] = None
    lessons: List[str] = []

class DesignEvolution(BaseModel):
    plan_id: str                      # the plan this catalog belongs to
    feature: str
    issue: Optional[int] = None
    pr: Optional[int] = None          # unknown until the PR exists
    branch_lineage: str
    primary_documents: Dict[str, str] # key -> repo-relative path; the plan is always "plan"
    id_conventions: Optional[IdConventions] = None
    changes: List[DesignChange] = []
    summary: Optional[EvolutionSummary] = None

    def counts(self) -> EvolutionCounts: ...   # by phase / issue category / outcome category, computed
```

**Plan-bound only (developer's decision).** This catalog replaces the general one: a DesignEvolution exists
only as `<artifacts.plans>/NNNN/DesignEvolution.json`, and `plan_id` is required. A change found at spec
review, before `plan.py new`, is entered (phase `spec-review`) once the plan exists; the spec itself stays
frozen after its review patch. `evolution_api` needs a plan. Old-shape `DesignEvolution.json` files elsewhere
in a consuming project are read by no code before or after this change; they simply stop being the
convention.

Changes from the current schema: `category_enums` is dropped (the enums are the single source; the old
instance-level copy only restated them); `pr` and `summary` become optional; the summary's three `by_*` count
maps are computed by `counts()` instead of stored; `plan_id`, `DesignChange.items` and `DesignChange.date` are
added; the id cap of 99 is lifted. No instance of the old schema exists in the repo, so nothing migrates.
`IdConventions` is a class with `comment: Optional[str]` and a `prefixes: Dict[str, str]` map (prefix to
meaning), replacing the open `additionalProperties` object.

`plugins/harness/schemas/catalogs/DesignEvolutionCatalog.schema.json` is regenerated from `DesignEvolution`,
pinned by a test like `tests/contract/test_plan_schema_generated.py`.

### Receipts (`harness_lib/receipt_models.py`)

```python
class ExtraFile(BaseModel):
    """A path the item's work changed beyond its planned files."""
    path: str
    change: str                       # a DesignChange id naming this item

class TestSubstitution(BaseModel):
    """A planned node replaced by another; record runs `node` in place of `planned`."""
    planned: str                      # one of the item's planned nodes
    node: str                         # pytest node id
    change: str                       # a DesignChange id naming this item

class Deviations(BaseModel):
    extra_files: List[ExtraFile] = []
    substitutions: List[TestSubstitution] = []

class Receipt(BaseModel):
    plan_id: str
    item: str
    outcome: Outcome                  # the existing Completed | Started | Blocked | Closed union
    evidence: str
    deviations: Deviations = Deviations()
    ref: Optional[str] = None         # a tag or branch name given to record --sha, kept for display
    date: str
    seal: str                         # sha256, see below
```

`Outcome`, `Provenance` and `PassedTests` are the existing classes of `plan_models.py`, reused unchanged.

**Seal.** sha256 over canonical JSON of the receipt without `seal`, plus the item's planned `files` and
`tests` as frozen. Consequences as today: a hand edit of any receipt field, a receipt copied to another item or
plan, or a refreeze that changes the item's planned files or tests, breaks the seal; the repair is `record`
again.

## Driver changes (`plugins/harness/scripts/plan.py`)

- **Record scheme.** `RecordScheme` gains `RECEIPTS`. A first `freeze` sets `frozen.records = RECEIPTS`. A plan
  frozen as `SEALED` or legacy keeps its scheme and every behavior it has today, refreeze included.
- **`record`** on a `RECEIPTS` plan writes `NNNN/receipts/<ITEM>.json` and `live.js` and nothing else. Its
  rules are today's (`--sha`, `--staged`, `--start`, `--blocked`, `--closed`; dependency gate; base-diff rule;
  clean item paths; tests on a throwaway worktree), with two additions:
  - `--also PATH --cite ID` (repeatable): an extra file. It joins the item's paths for the base-diff and
    clean-path rules and is stored as an `ExtraFile`.
  - `--substitute PLANNED=NODE --cite ID` (repeatable): the run uses `NODE` in place of `PLANNED`; stored as a
    `TestSubstitution`.
  - Each cited id must exist in the plan's DesignEvolution and list the item in `items`; otherwise `record`
    refuses with a `problem:` line naming the id and the item.
  - `--sha` accepts any revision (tag, branch, SHA); a non-SHA revision is kept in `ref`.
- **`check`** on a `RECEIPTS` plan: the plan JSON must equal its freeze digest with no exception (no field is
  mutable after freeze; `completed`, `markdown_sync_status` and `markdown_last_updated` are not written on
  this scheme). Every receipt must parse, match its seal, name a plan item, and cite only entries that exist
  and name its item. A receipt for an unknown item is a problem. Status is read from receipts; an item without
  one is PENDING. The DesignEvolution file, when present, must validate (ids unique, `items` known, `doc`
  keys in `primary_documents`, summary finding ids known).
- **`verify`**, **`lanes`** and the dependency gate read status from receipts and run substituted nodes.
  Every other status read on a `RECEIPTS` plan goes through receipts too (`red`'s open items, `claims_rev`,
  `unproven_items`, `started_items`); the plan JSON's own `status` fields stay PENDING forever there.
- **`freeze --refreeze`** on a `RECEIPTS` plan keeps the receipts; a receipt whose seal the refreeze broke is
  printed as `re-record after refreeze: <ITEM>`, as today.
- **`plan_api.write`** refuses any change to a frozen `RECEIPTS` plan except through the refreeze path
  (`write` then `freeze --refreeze`), as today.
- **`render`** writes the PIP HTML and `live.js`.

## Parallel lanes (developer's decision)

A lane's file set stays the item's `files` plus its planned test files (`plan_lanes.py` `lane_files`), and
`parallel2.py stage` keeps refusing paths outside it. Lanes never write the plan's DesignEvolution. A lane
whose work needs a deviation (an extra file, a substituted test) stops and reports it in its result. The main
session then adds the `DesignChange` through `evolution_api.add`, stages the lane with the existing
`parallel2.py stage <lane> --include-undeclared`, and records the item with `--also` / `--substitute` and
`--cite`. One writer for the catalog means one id sequence and no merge of the catalog file. `plan_lanes.py`
and `parallel2.py` do not change; the lane prompt text in write-plan step 9 gains the stop-and-report rule.

## evolution_api (`harness_lib/evolution_api.py`)

The agent's write path, in the style of `plan_api`: `load(plan_id)`, `add(plan_id, change: DesignChange)`,
`write(evolution)`. `add` assigns nothing implicitly: the id is the agent's, checked for the prefix and
uniqueness; `items` are checked against the plan; `date` defaults to today. Each write validates the whole
catalog and rebuilds `live.js`. A first `add` on a plan without a catalog creates it from the plan
(`plan_id`, `primary_documents.plan`, `primary_documents.spec` from `source_document`, `branch_lineage` from
the plan's branch and base branch).

## PIP HTML (`harness_lib/plan_render.py`)

- One self-contained `NNNN_<Title>_PIP.html`: inline CSS and JS, no network, no external assets. The plan's
  content (header, decisions, values, sweeps, items with action, anchors, tests, commands, files) is rendered
  into the page at freeze.
- A `<script src="NNNN/live.js">` defines `window.PLAN_LIVE = {receipts: [...], evolution: {...}}`. The page
  reloads that script every few seconds (remove and re-add the element) and redraws only the live parts:
  each item's status and boxes, its receipt (provenance, passed or substituted nodes, extra files with their
  citations), and the DesignEvolution entries, each linked from the items it names.
- A missing `live.js` (fresh checkout before any `render`) shows the plan with every item PENDING and a note
  naming `plan.py render NNNN`.
- The markdown PIP renderer stays for plans frozen before this change; `render` picks the format by scheme.

## Other consumers

- `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py`: P1 (PIP checkboxes against status) and P4
  (`markdown_sync_status` claim) skip `RECEIPTS` plans, whose PIP cannot drift from their status; P2 accepts a
  sealed COMPLETE receipt; P3 pairs `_PIP.html` as it pairs `_PIP.md`.
- `plugins/todo-watch/hooks/checks.ts` `isWatchedPath`: also watches `NNNN/receipts/*.json` and
  `NNNN/DesignEvolution.json`.
- `plugins/harness/lib/harness_lib/plan_models.py` `PrAttributes.pip_document`: the pattern accepts `.html`.
- `.gitignore`: `docs/plans/*/live.js` (path from `artifacts.plans`; the project's own ignore line, plus a line
  in the README telling consuming projects to add theirs).
- `plugins/harness/rules/HARNESS_RULES.md` "Plans and specs": the DesignEvolution line is replaced: changes
  that alter a plan's design go to `<artifacts.plans>/NNNN/DesignEvolution.json` through `evolution_api`,
  and a receipt that differs from its item cites one; "beside the plan's research notes" goes.
- Release: the DesignEvolution schema changes shape (closed model, `plan_id` required, `category_enums`
  gone). Whether that counts as a breaking change across the marketplace, and so a major release, is the
  developer's call when the release is suggested.
- Schemas: `ActionPlan.schema.json` and `DesignEvolutionCatalog.schema.json` regenerated; a new
  `Receipt.schema.json`; `schemas/README.md` and `PLANS_PIP_Template.md` updated.
- `plugins/harness/.claude-plugin/plugin.json`: minor bump; `docs/RELEASES/` notes.

## write-plan SKILL.md

`write-plan` has a frozen strap spec (`docs/plans/strap/write-plan/SkillSpec.json`, behaviors B1-B8, all
mechanical). The SKILL.md edit goes through `harness:strap-skills`: the changed text, the behaviors it adds
(receipts, citations, substitutions, the HTML PIP), and a refreeze of that spec. The text changes:

- Step 8's "after the freeze only `record` changes the plan" becomes: after the freeze nothing changes the
  plan; `record` writes receipts.
- A new step between 8 and 9: a change found during execution goes to the plan's DesignEvolution through
  `evolution_api.add`, and the receipt cites it (`--also`, `--substitute`, `--cite`). A refreeze is for a design
  change the developer asks for.
- Step 9 (lanes): a lane that needs a deviation stops and reports it; the main session adds the change,
  stages with `--include-undeclared` and records with the citation.
- "The PIP markdown is rendered from the JSON and never edited by hand" becomes the HTML PIP, opened from disk.

## Tests

New files, each on a `make_project` repo:

- `tests/lib/test_evolution_models.py`: every class validates and rejects its own shape; `DesignChange.issue`
  is a `ChangeIssue` instance after parsing; unknown `doc` keys, duplicate ids, unknown summary finding ids
  are refused; `counts()`.
- `tests/lib/test_evolution_api.py`: `add` creates the catalog from the plan, refuses an unknown item, a
  duplicate id, a bad prefix; rebuilds `live.js`.
- `tests/lib/test_receipt_models.py`: seal changes with every covered field, the item's planned files and
  tests included.
- `tests/scripts/test_plan_receipts.py`: on a `RECEIPTS` plan, `record` leaves the plan JSON and PIP
  byte-identical and writes the receipt and `live.js`; `check` passes; a hand edit of a receipt fails `check`;
  a hand edit of any plan field fails `check`; `--also` and `--substitute` with a valid citation pass and the
  substitute is the node run; an uncited or wrongly cited deviation is refused; `verify` runs substituted
  nodes; the dependency gate reads receipts; `lanes` lists only items without a COMPLETE receipt; refreeze
  prints `re-record after refreeze` for a changed item.
- `tests/scripts/test_plan_receipts_legacy.py`: a `SEALED` plan and a legacy plan behave exactly as today.
- `tests/lib/test_plan_render_html.py`: the page is self-contained (no `http`), names `NNNN/live.js`, renders
  every item and decision; a missing `live.js` renders the PENDING fallback note.
- `tests/lib/todo_sync/` additions for P1-P4 on a `RECEIPTS` plan.
- Schema-generation pins for the two new or regenerated schemas.

## Left to the builder

- Module placement and function names; `plan.py` is near its function-size limits, so receipt reading and
  the citation rules belong in a library module beside `plan_record.py`.
- The page's layout and styling, within: self-contained, readable without JS (plan content static), live
  parts redrawn from `PLAN_LIVE`.
- The reload interval (a few seconds).
- Error wording, as long as each names the item, the id and the command that fixes it.

## Process

Implemented through `harness:write-plan` against this spec; the write-plan SKILL.md change rides a
`harness:strap-skills` refreeze of the write-plan spec.
