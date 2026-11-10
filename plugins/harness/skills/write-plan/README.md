# write-plan

Turn a spec into an implementation plan whose claims the tooling checks, then record each item's outcome with
evidence instead of a status someone typed. `SKILL.md` is the procedure the agent follows; this file is for
the developer who reads the plans, approves the freeze and commits the work.

## What a plan is

A plan is a JSON file (`NNNN_<title>_ActionPlan.json` in the project's plans folder) built through the models
in `harness_lib/plan_models.py`, never by hand. Each item carries what the driver can check:

| Part | What the driver does with it |
|---|---|
| **Anchors** (`path:12-18` plus the text expected there) | opens the range and compares the text, so a plan built on a stale picture of the code fails |
| **Sweeps** (a search plus every hit classified) | reruns the search; a new hit or a stale classification fails |
| **Planned tests** (real files under `<plans>/<id>/tests/`) | runs them before the work (`red`: each must fail the planned way) and after it (`record`: each must pass) |
| **Decisions** (`D1`, `D2`, ... with options) | an open decision blocks the freeze; the developer picks, not the agent |
| **Files, dependencies, model** | the item's file set, its order, and the model that implements it; `lanes` turns them into parallel waves |

The PIP (the human-readable plan) is rendered from the JSON. Never edit it: the next render overwrites it.

## Lifecycle

```
new --> write (models) --> check --> red --> decisions settled --> freeze
                                                                     |
               +-----------------------------------------------------+
               v
     implement item --> record (receipt) --> ... --> verify --> merge
               ^                                 |
               +---- design changed? evolution_api.add, cite it on the record
```

| Step | Command (`PLAN` = `plan.py`) | Writes |
|---|---|---|
| Start | `PLAN new "<title>" --spec <path>` | empty plan, its PIP, the planned-tests folder; pins the base commit |
| Author | `plan_api.write(...)` from a script | plan JSON and PIP, after validating the whole plan |
| Check | `PLAN check <id>` | nothing |
| Red | `PLAN red <id>` | nothing (runs the tests on a throwaway worktree) |
| Freeze | `PLAN freeze <id>` | the plan's `frozen` block, the HTML PIP and its `live.js` |
| Record | `PLAN record <id> <ITEM> --sha <rev>` or `--staged` | one receipt file per item, `live.js` |
| Other states | `--start`, `--blocked "<reason>"`, `--closed "<rationale>"` | a receipt |
| Render | `PLAN render <id>` | `live.js` (and the page if it is missing) |
| Verify | `PLAN verify <id> [--staged]` | nothing (reruns COMPLETE items' tests at HEAD or the index) |
| Lanes | `PLAN lanes <id>` | nothing (prints a `parallel2` plan of the open items) |

## Freezing

A freeze says "this is the plan we build". It refuses while `check` or `red` has a problem, while a decision is
open, or while an open item has neither a test nor a command. It stamps the plan with a digest and the commit
it was frozen at.

**After the freeze the plan JSON does not change.** Plans frozen from this version use the **receipts** scheme:

- `record` writes `<plans>/<id>/receipts/<ITEM>.json`, a sealed receipt holding the outcome, the tested tree,
  the commit (and the tag or branch name you passed, when it was not a bare SHA), the test nodes that ran, and
  any deviation. The plan JSON and the PIP are not touched.
- The PIP becomes `NNNN_<title>_PIP.html`. Open it from disk in a browser: it reloads `<id>/live.js` every few
  seconds, so a `record` in the terminal shows up on the page without a re-render.
- `live.js` is derived from the receipts and the DesignEvolution catalog. The driver keeps a `.gitignore` in
  the plan folder that lists it; after a pull, `PLAN render <id>` rebuilds it.

**Refreeze** is for a change of design: change the plan through `plan_api.write`, then
`PLAN freeze <id> --refreeze`. It is routine, not a failure, but the developer approves it. A refreeze that
changes a recorded item's files or tests breaks that item's receipt seal on purpose and prints
`re-record after refreeze: <ITEM>`; record that item again.

Plans frozen before receipts keep the **sealed** scheme: each record is stamped into the plan JSON itself, so
the JSON and the markdown PIP change on every `record`. Nothing migrates them; both schemes are read.

## Deviations: when the build differs from the plan

A receipt states how the work differed from its item, and each difference must cite a design change:

| Flag on `record` | Means |
|---|---|
| `--also PATH` | the item also changed a file its file list does not name |
| `--substitute PLANNED=NODE` | a planned test node was replaced by another (the replacement is what runs and what `verify` reruns) |
| `--cite ID` | the DesignEvolution change that explains the deviations before it on the command line |

Record the change first, through `evolution_api.add(<plan>, DesignChange(...))`; it lands in
`<plans>/<id>/DesignEvolution.json`. The receipt stores a digest of each cited change, so editing that change
later asks for the item to be recorded again. An uncited deviation is refused, with the command that fixes it.

## Git: commits, tags and the plan

Nothing in a receipt is compared with HEAD, so staging, squashing, rebasing or amending leaves the plan valid.
Whether the work is still in the code is `PLAN verify`'s question, asked before the merge.

A commit sequence that keeps the history readable:

1. **Spec**: `Docs(plans): specify <feature>`.
2. **Plan**: the plan JSON and its PIP: `Docs(plans): plan <feature>`. The planned test files under
   `<plans>/<id>/tests/` are local references and stay out of git; each lands at its repo path, committed,
   with the item that copies it there.
3. **Freeze**: commit right after `freeze`: the plan JSON, the new HTML PIP, the deleted markdown PIP and the
   plan folder's `.gitignore`: `Docs(plans): freeze plan <id>`. The committed copy is also what a later
   refreeze reads to keep the plan's scheme.
4. **Work**: one commit per item, or per wave when items land together. Record with `--staged` before the
   commit, or with `--sha <rev>` after it, and commit the receipt beside the code it describes (a receipt is
   not one of the item's files, so it never blocks the record).
5. **Design change**: the DesignEvolution entry goes in with the work that needed it.
6. **Before the merge**: `PLAN check <id>` and `PLAN verify <id>`.

**Tags.** `--sha` takes any revision. A tag (`--sha v1.4.0`) is kept in the receipt next to the full SHA, so
a receipt can say which release carried the item. A tag on a branch commit that is later squashed points at a
commit the base branch never gets; tag on the base branch after the merge when the tag should outlive the
branch. The receipt's tested tree stays the evidence either way.

## Parallel execution

`PLAN lanes <id> | parallel2.py plan -` waves the open items by dependency and file overlap. Each lane copies
its planned test files in first, builds in its own worktree and commits there; `parallel2.py stage` lands the
lane in the target's index uncommitted, and `PLAN record <id> <ITEM> --staged` records it from there.

A lane that finds it needs a deviation (a file outside its item, a different test node) stops and reports it
instead of building past the plan. The main session records the design change, stages the lane with
`parallel2.py stage <lane> --include-undeclared`, and records the item with `--also` or `--substitute` and the
`--cite` for that change.

## Related

- `SKILL.md`: the procedure the agent follows.
- `../../scripts/plan.py`: the driver; `--help` on each subcommand lists its options.
- `../../lib/harness_lib/plan_models.py`, `receipt_models.py`, `evolution_models.py`: the models.
- `../parallel2/README.md`: waves, worktrees and the probe.
