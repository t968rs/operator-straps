---
name: write-plan
description: Use when a spec or agreed design for multi-step work needs an implementation plan, before touching code, or when an existing plan's items need their status recorded with evidence. Triggers on "write a plan", "plan this", "write-plan", "record TASK-3".
argument-hint: "<title> [--spec PATH] [--base BRANCH] [--no-fetch] [-- <guidance>]"
---

# write-plan: a plan whose claims are checked

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. Before
it: the plan title and the `new` flags (`--spec`, `--base`, `--no-fetch`), passed to `new` unchanged. After it:
guidance for writing the plan (scope, a constraint, files to read first); it never reaches a command.

A plan here is an ActionPlan JSON the driver checks, not prose. Every claim about existing code is an
**anchor** the driver opens; every search the plan relies on is a **sweep** the driver reruns; every test is
a **real file** the plan holds, and every item changes state only through `record`: an item with tests is
marked COMPLETE only when they pass on a throwaway worktree at the recorded commit or index tree, a
command-only item is recorded on the commit or tree alone (its commands are not run), and `--closed` needs a
rationale, no commit. Every status `record` writes is sealed. The PIP is the `NNNN_<title>_PIP.html` page,
rendered from the JSON and never edited by hand: open it from disk in a browser, where it reloads its
`<plan_id>/live.js` sidecar (the receipts and the DesignEvolution catalog) every few seconds, so a `record`
shows up without a render. A plan frozen before receipts keeps its markdown PIP.

`PLAN` below stands for `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/plan.py"`,
run with the Bash tool from the project checkout. Every refusal is a `problem:` line and exit 1.

## Steps

1. **Start.** `PLAN new "<title>" --spec <spec path>`. It prints the plan file, the PIP and the folder for
   planned test files, and records the base commit (merge base of the base branch and HEAD).
2. **Read before writing.** Open the spec, then every file the work touches and every consumer of a symbol
   the work changes (callers, registries, `setattr` or monkeypatch sites, strategy tables, `partial`s).
3. **Write the plan through the models.** Plan JSON is never edited by hand, not even one status or one flag
   (status changes only through `record`): the agent builds model objects, so a bad field fails when it is
   built, and `write` validates the whole plan again before it touches a file. Run one heredoc per revision
   (`new` prints the command line with the plugin path filled in):

   ```bash
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/lib" sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" - <<'EOF'
   from harness_lib import plan_api
   from harness_lib.plan_enums import ItemStatus
   from harness_lib.plan_models import ActionItem, Anchor, PlannedTest

   plan = plan_api.load("<id>")
   item = ActionItem(id="TASK-1", title="...", action="...", status=ItemStatus.PENDING,
                     evidence="not started", files=["src/x.py"],
                     anchors=[Anchor(at="src/x.py:12-18", expect="def f")],
                     tests=[PlannedTest(node="tests/test_x.py::test_f", red="ImportError")])
   plan_api.write(plan.model_copy(update={"items": [*plan.items, item]}, deep=True))
   EOF
   ```

   `write` refuses, listing every problem and writing nothing: an unknown plan id, a copy loaded before the file
   changed, a changed `base_commit` or `frozen`, a misspelled field, a duplicate item id and, on a frozen plan,
   any change to an execution field. The one case for a hand edit is a plan that fails to load (a
   `schema:` problem from every command); repair the JSON, then run `PLAN check`. The fields are the models of
   `harness_lib/plan_models.py`:

   | Field | Carries | Checked by `check` |
   |---|---|---|
   | `decisions[]` | each design question (id `D<n>`), its options and `chosen` (null = open) | chosen is one of its options |
   | `values[]` | every threshold, count or band copied from the spec or the code, with `assumes` | no value assumes a rejected option |
   | `formats[]` | every literal format another component parses, with `source` (an anchor at its producer or parser) | the source anchor |
   | `sweeps[]` | every search the plan relies on (id `S<n>`; old names, moved paths) with each hit file classified; the plans folder and the plan's own `source_document` are never hits | reruns the pattern; unclassified hits and stale classifications fail |
   | `items[].anchors` | `{at: "path:12-18", expect: "<text>"}` for each fact about existing code the item uses | opens the range, compares the text |
   | `items[].tests` | `{node, red}`: the pytest node and the exception that fails it before the work (`ImportError`, `AttributeError`, `AssertionError`, `NotImplementedError` or `TypeError`) | the node's file exists or is planned |
   | `items[].commands` | `{run, expect, writes}`: generation and verification commands | no commit SHA (use `{base}`, which `render` prints as the full base commit), no pytest run of a directory or of no file |
   | `items[].id`, `files`, `dependencies`, `model` | the item id (2-4 uppercase letters, a dash, digits and dots: `TASK-3`), its file set, order and implementing model | dependencies known ids, no cycle; model `haiku`, `sonnet` or `opus` |

4. **Write the planned tests** as real files under `<plans dir>/<plan_id>/tests/<repo-relative path>`, the full
   content each test file will have. No test code goes in the JSON or the PIP.
5. **`PLAN check <id>`** until it passes. A stale anchor means the plan's picture of the code is wrong: reread
   the code and fix the plan, not the anchor's text alone. `open:` lines are decisions still to settle.
6. **`PLAN red <id>`** until it passes. It lays the planned test files over a throwaway worktree at HEAD and
   runs each open item's nodes: each must fail with its planned exception. A test that passes proves nothing
   about the item; one that fails for another reason (a typo, a wrong import path) tests the wrong thing.
   Fix the test file or the planned `red`, never the check.
7. **Settle open decisions with the developer.** No decision defaults to an answer; an open one blocks freeze.
8. **`PLAN freeze <id>`**. It refuses any check problem, any open decision, any open item with neither a test
   nor a command, any red problem, and, on a first freeze, any item not `PENDING`. A first freeze stores the
   receipts scheme: the freeze digest covers every field but `frozen`, and the freeze writes the HTML page and
   its `live.js` (a plan started at this version has had the page since `new`; only the markdown PIP of a plan
   started before receipts gives way to them). Nothing writes a receipts plan after its freeze but a
   design change (a `write` followed by `freeze --refreeze`): `record` writes receipts
   (`<plans dir>/<plan_id>/receipts/<ITEM>.json`) and `live.js`, the plan JSON and its page stay as frozen,
   and the seal is on the receipt. `check` reports any edit to the plan, every receipt problem and the
   DesignEvolution catalog's problems.

   Plans frozen before receipts keep the sealed scheme, and nothing migrates them: after the freeze only
   `record` changes the plan; `check` reports any edit outside the execution fields (the `Mutable` fields of
   `plan_models`: item status, evidence, verification references and record; the plan's completed, frozen and
   markdown sync fields), and, on a plan frozen with the record scheme, any status without a sealed record (a
   hand-set status, a hand edit, a record copied from another item); a plan frozen before it still accepts the
   old `record --sha` shapes.

   A design change the developer asks for after the freeze, under either scheme, is a `write` of the changed
   plan plus `freeze --refreeze`, stated to the developer, and an entry in the plan's DesignEvolution through
   `evolution_api.add` (built as step 9 shows); a change found during execution goes through step 9 instead.
   A change found in spec review, before the plan exists, is entered (phase `spec-review`) once `PLAN new`
   has run, since `evolution_api` resolves the plan first. A refreeze is standard procedure, not a design ambiguity: ask the developer for the OK, then do it.

   A refreeze that changes a recorded item's files or tests breaks that item's seal (on its receipt, or on its
   record in a sealed plan) by design: the refreeze tolerates it and prints `re-record after refreeze: <ITEM>`,
   and `check` flags the item until `record` runs on it again. On a sealed plan, a refreeze still refuses a
   non-PENDING item with no record; a plan frozen before the record scheme still accepts the legacy shapes.
   Once an item is done, `check` and the refreeze read anchors and sweeps at the plan's base commit, since the
   done work has already changed the code they quote; a new anchor added mid-plan quotes the code at the base.
   A freeze before any item is done requires them to hold at the base as well as in the tree. A plan id that
   collides with one on the base branch moves the newer plan to the next free id; a plan already on the base
   branch is never renumbered to spare the newer one. Each plan id is unique in the plans folder, because
   `PLAN` resolves a plan by id and refuses a folder with two plans of one id.

   **What a record proves.** On a receipts plan, `record` seals each status it writes into the item's
   receipt: a sha256 over the receipt without its seal (outcome, date, evidence, and the deviations with the
   digest of each change they cite) and the item's planned files and tests as frozen, bound to the plan id
   and the item id. `check` refuses a receipt edited by hand, one copied from another item or plan, a citation
   of a change the catalog lacks or whose `items` do not list the item, and a cited change edited after the
   receipt. On a plan frozen before receipts, `record` seals each status into the plan JSON: a sha256 over the
   plan id, the item's id, status, evidence, files and tests, and the record (outcome and date) without its
   seal, so `check` refuses any status, evidence or record a hand edit set, and a record copied from another
   item or another plan. Under either scheme the record keeps the tree that was tested and the commit when
   there was one; neither is compared with HEAD, so staging with `harness:a-w`, a squash, a rebase or an amend
   leaves the plan valid. Whether the work is still in the code is a separate question with a separate
   command: `PLAN verify <id>` reruns the COMPLETE items' tests at HEAD, writes nothing, and belongs before the
   merge. `--staged` runs them on a snapshot of the index instead, for work recorded with `record --staged`
   and not yet committed. A broken seal is fixed by `record` on that item again; a failed `verify` is fixed in
   the code first, then by `record` on that item at the fixing commit or index. The gate of `record` refuses
   only an unfrozen plan and a broken freeze digest; `--sha` and `--staged` then apply the rules of step 10
   (dependencies done with valid records, a changed file, a matching working tree, passing nodes). `record`
   never refuses because another item, or the item itself, fails `check`. A hand edit that recomputes the
   hash, or restores an item's own earlier record, is not caught: the seal is a keyless hash, not a
   signature. A refreeze keeps the plan's scheme (receipts or sealed) when the plan stores it, when the digest
   proves a hand deleted it, or when the plan's copy at HEAD stores it; a scheme deleted by hand before the
   plan was ever committed can still downgrade it to the legacy shapes.

9. **Route a change found during execution to the plan's DesignEvolution.** On a receipts plan, work that
   departs from its item (a file outside the item's `files`, a test node run in place of a planned one) never
   changes the plan: record the change in `<plans dir>/<plan_id>/DesignEvolution.json` through
   `evolution_api.add`, then cite it on the record. Build the change through the models, so a bad field or
   an unknown category fails when it is built; `add` refuses a duplicate change id and an item the plan does
   not have, writing nothing. `evolution_api.next_id` names the next free id of a prefix (`EX` for a change
   found after execution started):

   ```bash
   PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/lib" sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" - <<'EOF'
   from harness_lib import evolution_api
   from harness_lib.evolution_enums import ChangePhase, IssueCategory, OutcomeCategory
   from harness_lib.evolution_models import (ChangeIssue, ChangeOriginal, DesignChange, NewOutcome,
                                             WhyNewOutcome)

   change_id = evolution_api.next_id("<id>", "EX")
   evolution_api.add("<id>", DesignChange(
       id=change_id, discovered_by="task-3 lane", phase=ChangePhase.post_exec_start, items=["TASK-3"],
       original=ChangeOriginal(doc="plan", location="TASK-3 files", indicated="only src/x.py changes"),
       issue=ChangeIssue(category=IssueCategory.signature_mismatch,
                         why_categorical="a caller outside the item's files",
                         why_free_form="src/y.py calls f() positionally; the new keyword breaks it"),
       new_outcome=NewOutcome(doc="plan", indicated="TASK-3 also updates the call in src/y.py"),
       why_new_outcome=WhyNewOutcome(category=OutcomeCategory.execution_blocker,
                                     free_form="without the caller change the planned test cannot pass")))
   print(change_id)
   EOF
   ```

   `doc` names a key of the catalog's `primary_documents` (`plan` always, `spec` when the plan has one). Then
   record with the deviation and its citation (`EX1` being the id the heredoc printed):
   `PLAN record <id> TASK-3 --staged --also src/y.py --cite EX1`. `--also PATH` is a file the item changed
   that its `files` do not name; `--substitute PLANNED=NODE` runs `NODE` in place of the planned node
   `PLANNED` (and `verify` reruns the substitute); `--cite ID` binds every uncited deviation before it to that
   change, which must list the item. The deviation flags need `--sha` or `--staged`; an uncited deviation is
   refused with the command that fixes it. The receipt keeps the digest of each cited change, so editing the
   change later makes `check` ask for that item's `record` again. A refreeze is for a design change the
   developer asks for, not for a change found during execution. A plan frozen before receipts has no
   deviation flags: a change there is a refreeze, with the developer's OK.

10. **Hand off** the PIP path for review and an execution method. For parallel execution,
    `PLAN lanes <id> | P2 plan -` (with `P2` as in `harness:parallel2`) turns the open items into lanes, waved
    by dependency and file overlap; `PLAN lanes <id>` refuses a plan with a broken freeze digest or a record
    problem, and `record` on the item it names repairs the record problem. A lane id is the item id in lower
    case with dots as hyphens (`TASK-3.2` is `task-3-2`), and its task is the item title alone: append the
    item's action, anchors, tests and commands to each lane prompt, with the instruction to copy each planned
    test file from `<plans dir>/<plan_id>/tests/<repo-relative path>` to its repo path first. On a receipts
    plan take that text from `plan_api.load(<id>).items` (the page is HTML, drawn for a browser, not for a
    prompt); on a plan frozen before receipts the markdown PIP carries the same fields under the item's
    heading. Each prompt also says that a lane that needs a deviation (a file outside its `files`, a test
    node other than a planned one) stops and reports it instead of widening its own scope. The main session
    then adds the change (step 9) once it is settled, has the deviation built, stages the lane with
    `P2 stage <lane> --include-undeclared` and records with the citation.

    parallel2 stages each lane's changes uncommitted in the target and deletes the `p2/<id>` lane branch, so
    staged lane work is recorded with `PLAN record <id> <ITEM> --staged` once it is in the index, or with
    `--sha` after the developer commits it. `--sha` may name any commit, a lane commit included, as long as
    the item's files in the working tree match it. `PLAN record <id> <ITEM> --sha <commit>` needs the item's
    dependencies done with valid records, one of the item's files changed between the plan base and the
    commit, the item's files unchanged since that commit, and the item's test nodes passing on a throwaway
    worktree at that commit. `--staged` needs the same of the index tree: the dependencies done with valid
    records, one of the item's files changed between the base and the index, no unstaged or untracked change
    to the item's files, and the nodes passing on a throwaway worktree at a snapshot of the index. An
    `--also` file and a substituted node's file count among the item's files for these rules. `--start`,
    `--blocked "<reason>"` and `--closed "<rationale>"` set the other states.

## What an item must carry

- **A symbol another component calls:** an anchor at each call site with the call expression as `expect`, and a
  test that runs that caller, not the symbol alone. A symbol swapped in by `setattr` or monkeypatch also gets
  an anchor at the swap and a test that runs the caller under the swap.
- **A format another component parses:** a `formats[]` entry citing the existing producer or parser, and a test
  that parses what the item emits.
- **A move, rename or split:** a sweep of the old name with every hit classified, and a test that every new
  reference resolves (function-local imports included), not only that the old one is gone. Leftovers git does
  not track (`__pycache__`, build output) survive a move: assert on tracked content, not on a path's absence.
- **A failure-path claim:** the test patches below the component whose failure is claimed and pins the
  exception type that leaves the public entry point.
- **A generation step:** a command with the files it writes, default outputs and working-directory side
  effects included, after reading the generator's entry point.
- **A command:** it obeys the project's instruction files (test scoping, runs reserved for the developer).

## Common mistakes

- On a receipts plan, a `write` to record a change found during execution: the plan stays as frozen, the
  change goes to `DesignEvolution.json` through `evolution_api.add`, and the receipt cites it (step 9). A
  `write` after the freeze breaks the freeze digest, and `record` refuses the plan until a refreeze.
- On a receipts plan, a lane that builds a deviation on its own: it stops and reports, and the main session
  adds the change before the record cites it.
- On a receipts plan, editing a DesignEvolution change a receipt already cites: `check` then asks for that
  item's `record` again.
- Editing the plan JSON by hand, "because it is one line": `write` validates and guards, a hand edit does not
  (the hand-edit exception is only a plan that fails to load).
- Changing an existing item's status by hand or through `write` (a new item is built PENDING): on a receipts
  plan the status lives in the item's receipt, which only `record` writes; on a plan frozen before receipts
  `record` owns the execution fields, and `write` refuses the change once the plan is frozen.
- Guessing a `red` exception instead of running `PLAN red`; the planned exception is what the run must show.
- Copying a commit SHA into a command: use `{base}`.
- `model_copy(update=...)` without `deep=True`: the copy shares its nested items with the loaded plan, and a
  later change to one changes the other.

## Related

- `${CLAUDE_PLUGIN_ROOT}/scripts/plan.py`: the driver; `--help` on each subcommand lists its options.
- `${CLAUDE_PLUGIN_ROOT}/lib/harness_lib/plan_models.py`: the models, the one definition of a plan.
- `${CLAUDE_PLUGIN_ROOT}/lib/harness_lib/receipt_models.py` and `evolution_models.py`: the receipt and the
  DesignEvolution models; `evolution_api.py` adds a change.
- `${CLAUDE_PLUGIN_ROOT}/schemas/ActionPlan.schema.json`: generated from the models.
- `harness:parallel2`: dispatches independent items in waves.
