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
| **Planned registry entries** (`<plans>/<id>/registry_entries.json`, with `tests.planned_registry` set) | upserts them into the throwaway tree's registry for `red`, and into the live registry per item (`register`), so the live registry never lists a test file that does not exist yet |
| **Decisions** (`D1`, `D2`, ... with options) | an open decision blocks the freeze; the developer picks, not the agent |
| **Files, dependencies, model** | the item's file set, its order, and the model that implements it; `lanes` turns them into parallel waves |

The PIP (the human-readable plan) is rendered from the JSON. Never edit it: the next `plan_api.write`, freeze
or refreeze rebuilds it, and so does `render` on any plan but a frozen receipts plan (there `render` writes
the page only when it is missing).

## Lifecycle

```
new --> write (models) --> check --> red --> decisions settled --> freeze
                                                                     |
               +-----------------------------------------------------+
               v
     implement item --> record (receipt) --> ... --> verify --> merge --> archive (on ask)
               ^                                 |
               +---- design changed? evolution_api.add, cite it on the record
```

| Step | Command (`PLAN` = `plan.py`) | Writes |
|---|---|---|
| Start | `PLAN new "<title>" --spec <path> [--refs '<ids and issues>']` | empty plan, its PIP, the planned-tests folder; pins the base commit |
| Author | `plan_api.write(...)` from a script | plan JSON and PIP, after validating the whole plan |
| Check | `PLAN check <id>` | nothing |
| Red | `PLAN red <id>` | nothing (runs the tests on a throwaway worktree) |
| Freeze | `PLAN freeze <id>` | a `freezes/plan/<id>-<slug>/r1.<k>-freeze.json` ledger entry and its tree tag, the plan's `ledger` field, the HTML PIP and its `live.js` |
| Lock | `PLAN lock <id>` (on the developer's ask, after the freeze commit) | a `lock` ledger entry and its tree tag |
| Unlock | `PLAN unlock <id> --arm "<reason>"`, then `PLAN unlock <id>` | an `arm` entry, then an `unlock` entry |
| Relink | `PLAN relink <id> [--to REF]` | the plan's `base_commit`, a `relink` entry and a `base/<stem>/r1-<m>` tag |
| Archive | `PLAN archive <id> [--remote]` (on the developer's explicit ask, after the PR merges) | one `archive/<stem>/r1` (or `r1-<m>`) tag over a commit holding the folded objects; the folded local tags are deleted |
| Record | `PLAN record <id> <ITEM> --sha <rev>` or `--staged` | one receipt file per item, `live.js` |
| Other states | `--start`, `--blocked "<reason>"`, `--closed "<rationale>"` | a receipt |
| Render | `PLAN render <id>` | `live.js` (and the page if it is missing) |
| Verify | `PLAN verify <id> [--staged]` | nothing (reruns COMPLETE items' tests at HEAD or the index) |
| Lanes | `PLAN lanes <id>` | nothing (prints a `parallel2` plan of the open items) |
| Register | `PLAN register <id> <ITEM>` (after the item copied its planned tests) | the item's planned entries in the live `tests.registry`, through `tests.planned_registry` |

## Freezing

A freeze says "this is the plan we build". It refuses while `check` or `red` has a problem, while a decision is
open, or while an open item has neither a test nor a command. It writes a write-once ledger entry,
`<plans>/freezes/plan/<id>-<slug>/r1.<k>-freeze.json`, holding the digest, the record scheme, the base and the
tree of the plan JSON, its planned tests and its `registry_entries.json` (no commit), and tags that tree `freeze/<stem>/r1.<k>-tree`. The
plan JSON drops its `frozen` block and carries the static `ledger` field (the stem `plan/<id>-<slug>`); the
stamp is read from the ledger's last `freeze` entry. A plan frozen before the ledger keeps its in-file stamp
until its next refreeze moves it into the ledger.

**Locked** is the state after `PLAN lock <id>`, which runs only on the developer's ask once the freeze is
committed. A Locked plan refuses `plan_api.write` and `freeze`, and a hook denies hand edits to the plan JSON,
its planned tests, its `registry_entries.json` and the ledger; `record`, `verify`, `lanes` and `render` run as before. A design change
takes `PLAN unlock <id> --arm "<reason>"` (on the developer's OK), then `PLAN unlock <id>`, then
`plan_api.write`, `freeze --refreeze` and, once that is committed, `lock` again. After a rebase or squash moves
the base off HEAD's history (`check` prints `off-history:`), `PLAN relink <id>` re-points `base_commit` on the
developer's request and leaves the plan Frozen or Locked. It refuses a base where the plan's anchors or
sweeps fail; a base squashed inside another pull request has no counterpart, so the plan stays off-history.

**After the freeze the plan JSON changes only through a refreeze.** Plans frozen from this version use the **receipts** scheme:

- `record` writes `<plans>/<id>/receipts/<ITEM>.json`, a sealed receipt holding the outcome, the tested tree,
  the commit (and the tag or branch name you passed, when it was not a bare SHA), the test nodes that ran, and
  any deviation. The plan JSON and the PIP are not touched.
- The PIP is `NNNN_<title>_PIP.html`. A plan started at this version has the page from `new` on; only a plan
  started before receipts swaps its markdown PIP for the page at the first freeze. Below its header the page
  lists every task heading with its live badge (the Status list). A page written before this layout keeps its
  old look until it is written again: by `plan_api.write`, by `freeze --refreeze`, or by deleting it and running
  `PLAN render <id>` (render writes a frozen receipts plan's page only when it is missing). Open it from disk in a
  browser: it reloads `<id>/live.js` every few seconds, so a `record` in the terminal shows up on the page
  without a re-render.
- `live.js` is derived from the receipts and the DesignEvolution catalog. The driver keeps a `.gitignore` in
  the plan folder that lists it; after a pull, `PLAN render <id>` rebuilds it, and an a-w attach rebuilds it in the target.

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
   with the item that copies it there. `registry_entries.json` is tracked with the plan, and each entry
   reaches the live registry in that same item's commit (`PLAN register`), never in a commit of its own.
3. **Freeze**: commit right after `freeze`: the plan JSON, its HTML PIP, its `registry_entries.json` when the
   plan has one, and the new `freezes/plan/...` ledger entry (on a plan started before receipts, also the
   markdown PIP the freeze deleted), since `lock` refuses while a file of the last freeze is uncommitted:
   `Docs(plans): freeze plan <id>`. When the developer asks for a lock, `PLAN lock <id>` runs after this
   commit, and its `lock` entry is committed next. The committed copy is
   also what a later refreeze reads to keep the plan's scheme. Committing the plan folder's `.gitignore` is
   optional: whenever the driver rebuilds `live.js` (record, freeze, render, `evolution_api`, or an a-w attach that lands the plan's files) it adds the
   `live.js` line when the file is missing or lacks it, so a repository may ignore the file instead.
4. **Work**: one commit per item, or per wave when items land together. Record with `--staged` before the
   commit, or with `--sha <rev>` after it, and commit the receipt beside the code it describes (a receipt is
   not one of the item's files, so it never blocks the record).
5. **Design change**: the DesignEvolution entry goes in with the work that needed it.
6. **Before the merge**: `PLAN check <id>` and `PLAN verify <id>`.
7. **After the PR merges**: on the developer's explicit ask, `PLAN archive <id> [--remote]` folds the plan's
   base, receipt and ledger entry tags into one `archive/<stem>/r1` tag and deletes the folded local tags; the
   developer runs the `push:` line it prints and, with `--remote`, the `remote:` line that deletes the folded
   tags from the remote. The delete is local only: without the `remote:` line the next `git fetch` or
   `git pull` restores every pushed folded tag by tag auto-follow and a later archive folds them again, so a
   plan whose tags were pushed archives with `--remote` and the developer runs both lines.

**Tags.** The drivers create the plan's tags themselves (annotated, local), in the same command:
`base/<stem>/r1` on the base commit (`r1-<m>` for a relinked base), `freeze/` and `lock/<stem>/r1.<k>-tree` on
each entry's tree, `-commit` on the commit that added an entry file once it is committed, and
`receipt/<stem>/<ITEM>-commit` or `-tree` on what `record` tested; after the PR merges, `PLAN archive` folds
them all into one `archive/<stem>/r1` tag (`r1-<m>` for a later archive). A command prints one
`tag: <name> -> <sha7>` line per tag it created and then one `push: git push origin <names>` line, which the
developer runs to share them, since tree tags never travel with `push --follow-tags`. Receipt tags stay
local and no push line names them. A tag name already on another object refuses the command before anything
is written. `--sha` still takes any revision, and a tag passed there (`--sha v1.4.0`) is kept in the receipt
next to the full SHA. Driver tags sit on main-line commits, so a release version is read with
`git describe --match 'v*'`. The receipt's tested tree stays the evidence either way.

## Parallel execution

`PLAN lanes <id> | parallel2.py plan -` waves the open items by dependency and file overlap. Each lane copies
its planned test files in first and, when the plan has `registry_entries.json`, runs `PLAN register <id> <ITEM>`
and the `guard:` files it prints so its own test runs pass, but leaves the registry out of its commit: the
registry is not one of the lane's files, and lanes of one wave would collide on it. The lane builds in its
own worktree and commits there; `parallel2.py stage` lands the lane in the target's index uncommitted. The
main session then runs `PLAN register <id> <ITEM>` and its `guard:` files in the target and stages the
registry, so the entry joins the item's commit, and `PLAN record <id> <ITEM> --staged` records it from there.

A lane that finds it needs a deviation (a file outside its item, a different test node) stops and reports it
instead of building past the plan. The main session records the design change, stages the lane with
`parallel2.py stage <lane> --include-undeclared`, and records the item with `--also` or `--substitute` and the
`--cite` for that change.

## Related

- `SKILL.md`: the procedure the agent follows.
- `../../scripts/plan.py`: the driver; `--help` on each subcommand lists its options.
- `../../lib/harness_lib/plan_models.py`, `receipt_models.py`, `evolution_models.py`: the models.
- `../parallel2/README.md`: waves, worktrees and the probe.
