# Plan item records: sealed, tree-referenced, verified on demand

Issue: https://github.com/t968rs/operator-straps/issues/225. Branch `1132-git-tree-plans`.

## Intent

`plan.py record --sha` ties each COMPLETE item to a commit, and `check` (plus every `record`) fails the plan when
that commit is not an ancestor of HEAD. Staging with `harness:a-w`, a squash, a rebase or an amend all break the
link, and the tools then refuse to repair it: `record` runs the same check first, `plan_api.write` refuses status
changes on a frozen plan, and the only exit is a hand edit the write-plan skill forbids.

The commit check was a proxy. Its docstring (`plugins/harness/scripts/plan.py:191`) says its job is catching a
hand-set status. Ancestry answered that question only while history stayed linear. The fix separates the three
jobs the check was doing and gives each the tool that actually answers it.

## The three jobs

| Job | Question | Answered by | Where |
|---|---|---|---|
| Anti-forgery | Did `record` write this status, or a hand edit? | A seal: sha256 over the record and the item fields it vouches for | `check`, every run |
| Provenance | What exactly was tested? | The tree SHA, plus the commit when one existed | stored in the record; displayed, never compared with HEAD |
| Still present | Is the work still in the code now? | Rerunning the COMPLETE items' tests | `plan.py verify`, on demand (before merge) |

`check` stops consulting git history for item status. Shared files across items, later items editing an earlier
item's file, and later PRs touching a finished plan's files no longer matter to `check`.

## Goals

- Re-recording any item, COMPLETE included, needs no hand edit and is never blocked by a broken seal, its own
  or another item's. The dependency gate stays (see Driver changes).
- A plan recorded in a worktree, staged with `a-w`, then committed (squashed or not) passes `check` with no
  further step. The same holds after amend or rebase of the recorded commit.
- `record --staged` records work that is staged but not committed (the `a-w` default).
- Every status `record` writes is sealed, not only COMPLETE: a hand-set CLOSED_NO_ACTION is as much a claim as a
  hand-set COMPLETE.
- `verify` reruns the COMPLETE items' tests at HEAD and reports per item, writing nothing.

## Non-goals

- Cryptographic tamper-proofing. The seal is a keyless sha256, the same strength as the freeze digest and the
  strap `SkillSpec` seal: it catches hand edits and copied records, not an agent that deliberately recomputes the
  hash. A keyed HMAC was rejected: plans are tracked files read on several machines, and a per-machine key would
  break `check` everywhere but the recording machine.
- Drift detection by blob comparison. Rejected in the design conversation: shared files make it report false
  drift on most plans (0006 shares 52 files across 5 items).
- Rewriting the finished plans 0001-0008.

## Anti-goals

- `check` that fails a finished plan because unrelated later work moved on.
- Models that are dictionaries with a type name. Every shape below is a class with typed fields and validation,
  and each concept (the seal, the provenance, the test run, each outcome) is its own class.

## Approaches considered

1. **Tree SHA as the authoritative reference, compared per item with HEAD blobs** (the issue's proposal).
   Survives rewrites but reports false drift whenever items share files or later work edits them.
2. **Keep the commit, add a fallback search by tree** (find any reachable commit whose tree matches). Fails on
   staged work and on squashes that fold several items into one tree.
3. **Seal + provenance + on-demand verify** (chosen by the developer). Splits the three jobs; nothing in `check`
   depends on history shape.

## Models (`plugins/harness/lib/harness_lib/plan_models.py`)

Each class is closed (`extra="forbid"`) unless noted. SHA fields reuse `_SHA40`; the seal uses a 64-hex pattern.

```python
class RecordSource(str, Enum):          # plan_enums.py
    COMMIT = "commit"                   # record --sha
    STAGED = "staged"                   # record --staged

class Provenance(BaseModel):
    """Where the recorded code came from: always a tree, a commit only when one existed."""
    source: RecordSource
    tree: Sha40
    commit: Optional[Sha40] = None       # required when source is COMMIT, absent when STAGED (validator)

class TestRun(BaseModel):
    """The planned nodes that passed on a throwaway worktree at the provenance tree."""
    nodes: List[NonEmpty] = Field(min_length=1)
    command: NonEmpty                    # the pytest command line as run, for the PIP

class Completed(BaseModel):
    outcome: Literal["complete"]
    provenance: Provenance
    tests: Optional[TestRun] = None      # None for a command-only item

class Started(BaseModel):
    outcome: Literal["started"]

class Blocked(BaseModel):
    outcome: Literal["blocked"]
    reason: NonEmpty

class Closed(BaseModel):
    outcome: Literal["closed"]
    rationale: NonEmpty

Outcome = Annotated[Union[Completed, Started, Blocked, Closed], Field(discriminator="outcome")]

class ItemRecord(BaseModel):
    """What `plan.py record` wrote for one item, and the seal that proves it wrote it."""
    outcome: Outcome
    date: str                            # _DATE
    seal: str                            # 64 hex

    def expected_seal(self, plan_id: str, item: ActionItem) -> str: ...
    def status(self) -> ItemStatus: ...  # the status the outcome implies
```

`ActionItem` gains `record: Annotated[Optional[ItemRecord], Mutable()] = None`. Being `Mutable`, it is left out of
the freeze digest, and `plan_api.write` already refuses to change mutable item fields on a frozen plan, so only
`record` can write it.

**What the seal covers**: canonical JSON (sorted keys, the `frozen_digest` separators) of `plan_id`, the item
`id`, `status`, `evidence`, the item's `files` and `tests`, and the record without `seal`. Consequences:

- A hand edit of status or evidence, or of any record field, breaks the seal.
- A record copied onto another item or into another plan breaks the seal (id and plan id are inside).
- A refreeze that changes an item's tests or files breaks that item's seal: the old proof was for different
  tests. `check` says to re-record it.

`verification_references` stays in the model for old plans and is no longer written by `record`.

`Frozen` gains `records: Optional[RecordScheme] = None`, a one-member enum (`SEALED`) in `plan_enums.py`. `freeze`
and `freeze --refreeze` set it to `SEALED` unless an item still carries a legacy shape (see Legacy items).
`Frozen` is `Mutable` and open, so the new field does not move any existing freeze digest. (Builder call: the
marker scopes legacy acceptance to plans frozen by the old driver.)

## Driver changes (`plugins/harness/scripts/plan.py`)

- **`record --sha <rev>`**: resolves the commit (no ancestry requirement), takes its tree, requires one of the
  item's paths to differ between the base and that tree, requires the item's paths in the working tree to match
  the commit (today's `commit_problems` rule), runs the item's nodes on a throwaway worktree at the commit, and
  writes a `Completed` record with `Provenance(source=COMMIT, tree, commit)`.
- **`record --staged`** (new, mutually exclusive with `--sha`): tree from `git write-tree`; the same base-diff
  rule against that tree; the item's paths must have no unstaged or untracked changes; the tests run on a
  throwaway worktree at a dangling `commit-tree` of that tree with HEAD as parent (the `parallel2.py:328`
  pattern, same snapshot identity), which no ref keeps; `Provenance(source=STAGED, tree, commit=None)`.
- **`--start`, `--blocked`, `--closed`** write `Started`, `Blocked`, `Closed` records, sealed the same way.
- **Gate**: `record` refuses only an unfrozen plan and a broken freeze digest. Seal problems on any item, the
  target included, never block `record`: re-recording is the repair.
- **Dependencies** (call): `--sha` and `--staged` keep `dependency_problems`, and a dependency counts as done
  only when its status is DONE **and** its record passes `record_problems` (sealed, or an accepted legacy shape).
  A hand-set COMPLETE upstream therefore unlocks nothing.
- **Refreeze** (call): `freeze --refreeze` tolerates seal mismatches on items that have a record (a refreeze that
  changed an item's files or tests breaks its seal by design) and prints each as
  `re-record after refreeze: <ITEM>`; the items keep their status, and `check` keeps flagging them until
  `record` runs. A missing record on a non-PENDING item still refuses the refreeze. Without this, a refreeze
  that edits a COMPLETE item's tests deadlocks: the refreeze refuses the broken seal and `record` refuses the
  broken digest.
- **`check`**: `completion_problems` becomes `record_problems`: for every item not PENDING, the record must exist,
  its seal must match, and its outcome must imply the item's status. The message for each says
  `record <plan> <ITEM> ...` again. `check` runs no git command for item status.
- **`claims_rev`** is unchanged (anchors and sweeps read at the base once any item is done).
- **`verify <plan> [--staged]`** (new, read-only): for each COMPLETE item with tests, runs its nodes on one
  throwaway worktree at HEAD (or at a snapshot of the index with `--staged`), prints one line per item
  (`TASK-2 pass` / `TASK-2 FAIL: <tail>`), exits 1 when any fails. It writes nothing to the plan; a failure is
  fixed in code or by re-recording after the fix.
- **`lanes`** keeps its `require_frozen` gate with the new rule (digest only).

## Legacy items

Items recorded before this change carry no `record`: a COMPLETE item has `verification_references` of the form
`[sha40, "tree <sha40>", ...]`, and an IN_PROGRESS, BLOCKED or CLOSED_NO_ACTION item has evidence only (the old
`--start`, `--blocked`, `--closed` wrote no references).

Legacy acceptance applies **only on a plan whose `frozen.records` is unset** (frozen by the old driver). There,
`check` accepts a COMPLETE item whose `refs[0]` is 40 hex and `refs[1]` is `tree <40 hex>`, with no git lookup,
and any other non-PENDING item with non-empty evidence. That keeps 0001-0008 passing, including plans whose
commits a squash merge has already orphaned, and keeps other projects' in-flight plans valid after the upgrade.
On a plan frozen by the new driver (`records` is `SEALED`), every non-PENDING item needs a sealed record and
pasted references do not pass.

A re-record replaces the legacy shape with a sealed record. A refreeze sets `records` to `SEALED` once no legacy
item remains, so an old plan moves to the strict rule as soon as its last legacy item is re-recorded (plan 0002,
with 12 legacy items and STR-11 open, stays on the legacy rule until then). (Builder call: the old plans are
finished work, and the risk left there, a hand-pasted legacy reference, is accepted.)

## Other consumers

- `plugins/harness/lib/harness_lib/plan_render.py:125`: the PIP shows the record (outcome, source, tree7,
  commit7, test command) instead of raw references; legacy references still render as today.
- `plugins/harness/lib/harness_lib/todo_sync/rules_plans.py:74` (P2): a COMPLETE item with a `Completed` record
  passes; legacy items keep the hex search.
- `plugins/harness/schemas/ActionPlan.schema.json`: regenerated from the models (`schema_text`).
  `plugins/harness/schemas/README.md` and `PLANS_PIP_Template.md` updated where they describe
  `verification_references`.
- Fixtures under `tests/fixtures/plan_models/` and `tests/fixtures/agent_schemas/` regenerated where the schema
  copy is pinned.
- `plugins/harness/.claude-plugin/plugin.json`: minor bump.

## write-plan SKILL.md text

The opening paragraph's claim "an item with tests is marked COMPLETE only when they pass on a throwaway worktree
at a commit that changed its files" is restated, and a section is added after step 8:

> **What a record proves.** `record` seals each status it writes: a sha256 over the item's id, status,
> evidence, files, tests and record, so `check` refuses any status, evidence or record a hand edit set, and a
> record copied from another item. The record keeps the tree that was tested and the commit when there was one;
> neither is compared with HEAD, so staging with `a-w`, a squash, a rebase or an amend leaves the plan valid.
> Whether the work is still in the code is a separate question with a separate command:
> `PLAN verify <id>` reruns the COMPLETE items' tests at HEAD, writes nothing, and belongs before the merge.
> A broken seal or a failed `verify` is fixed by `record` on that item again; `record` never refuses because
> another item, or the item itself, fails `check`.

Step 9 changes "`record` waits until the developer commits the staged work, and `--sha` names that commit" to:
staged lane work is recorded with `record <id> <ITEM> --staged` once it is in the index, or with `--sha` after
the developer commits it.

## Tests

New and changed nodes in `tests/scripts/test_plan_driver.py` and `tests/lib/test_plan_models.py`, each on a
`make_project` repo:

- Models: each outcome class validates and rejects its own shape; `Provenance` rejects COMMIT without a commit
  and STAGED with one; `ItemRecord.status()` per outcome; the seal changes with each covered field.
- Hand edit of status, evidence or any record field fails `check`; a record copied to another item fails `check`.
- **Staged attach**: record on worktree commits, stage the result onto the branch uncommitted, commit: `check`
  passes. Also record with `--staged` before the commit, then commit: `check` passes.
- **Squash**: two items recorded on two commits, squash both into one: `check` passes.
- **Amend**: record on a commit, amend it: `check` passes.
- Re-record a COMPLETE item: succeeds, the record is replaced, and it succeeds even while another item's seal
  is broken.
- Refreeze changing an item's tests breaks that item's seal and nothing else; the refreeze succeeds, prints
  `re-record after refreeze`, and a `record` of the item then makes `check` pass.
- A dependency with a hand-set COMPLETE (no record) does not unlock its dependent.
- Legacy shapes: accepted on a plan with `frozen.records` unset; refused on a `SEALED` plan; a refreeze leaves
  `records` unset while a legacy item remains and sets it once none does.
- `verify`: passes on a clean plan; fails, naming the item, after the item's code is reverted; writes nothing.
- Legacy references pass `check` with no git lookup.
- todo_sync P2 accepts a sealed `Completed` record.

## Left to the builder

- Function names and module placement inside `plan.py` (the `record` section is near its 50-line function
  limit; a `plan_record.py` library module beside `plan_red.py` is fine).
- The exact PIP rendering of a record.
- Error wording, as long as each names the item and the `record` command that fixes it.

## Process

Implemented through `harness:write-plan` (plan 0009) against this spec. The write-plan SKILL.md edit describes
driver behavior the plan's tests prove, so it rides in the plan as a docs item, not a strap spec.
