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
marked COMPLETE only when they pass on a throwaway worktree at a commit that changed its files, a command-only
item is recorded on the commit alone (its commands are not run), and `--closed` needs a rationale, no commit.
The PIP markdown is rendered from the JSON and never edited by hand.

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
   | `sweeps[]` | every search the plan relies on (id `S<n>`; old names, moved paths) with each hit file classified | reruns the pattern; unclassified hits and stale classifications fail |
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
   nor a command, any red problem, and, on a first freeze, any item not `PENDING`. After the freeze only
   `record` changes the plan; `check` reports any edit outside the execution fields (the `Mutable` fields of
   `plan_models`: item status, evidence and verification references; the plan's completed, frozen and
   markdown sync fields), and any COMPLETE item without the commit and tree `record` writes. A change of
   design after the freeze is a `write` of the changed plan plus `freeze --refreeze`, stated to the developer.
   A refreeze is standard procedure, not a design ambiguity: ask the developer for the OK, then do it. A plan id
   that collides with one on the base branch moves the newer plan to the next free id; a plan already on the base
   branch is never renumbered to spare the newer one. Each plan id is unique in the plans folder, because `PLAN`
   resolves a plan by id and refuses a folder with two plans of one id.
9. **Hand off** the PIP path for review and an execution method. For parallel execution,
   `PLAN lanes <id> | P2 plan -` (with `P2` as in `harness:parallel2`) turns the open items into lanes, waved
   by dependency and file overlap. A lane id is the item id in lower case with dots as hyphens (`TASK-3.2`
   is `task-3-2`), and its task is the item title alone: append the item's PIP section (action, anchors,
   tests, commands) to each lane prompt, with the instruction to copy each planned test file from
   `<plans dir>/<plan_id>/tests/<repo-relative path>` to its repo path first. parallel2 stages each lane's
   changes uncommitted in the target and deletes the `p2/<id>` lane branch, so `record` waits until the
   developer commits the staged work, and `--sha` names that commit, never the lane commit. Each implemented
   item is recorded with `PLAN record <id> <ITEM> --sha <commit>`: it needs the item's dependencies done, the
   commit reachable from HEAD with one of the item's files changed between the plan base and it, the item's
   files unchanged since that commit, and the item's test nodes passing on a throwaway worktree at that
   commit. `--start`,
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

- Editing the plan JSON by hand, "because it is one line": `write` validates and guards, a hand edit does not
  (the hand-edit exception is only a plan that fails to load).
- Changing an existing item's status by hand or through `write` (a new item is built PENDING): `record` owns the
  execution fields, and `write` refuses the change once the plan is frozen.
- Guessing a `red` exception instead of running `PLAN red`; the planned exception is what the run must show.
- Copying a commit SHA into a command: use `{base}`.
- `model_copy(update=...)` without `deep=True`: the copy shares its nested items with the loaded plan, and a
  later change to one changes the other.

## Related

- `${CLAUDE_PLUGIN_ROOT}/scripts/plan.py`: the driver; `--help` on each subcommand lists its options.
- `${CLAUDE_PLUGIN_ROOT}/lib/harness_lib/plan_models.py`: the models, the one definition of a plan.
- `${CLAUDE_PLUGIN_ROOT}/schemas/ActionPlan.schema.json`: generated from the models.
- `harness:parallel2`: dispatches independent items in waves.
