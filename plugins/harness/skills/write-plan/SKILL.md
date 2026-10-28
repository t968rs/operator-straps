---
name: write-plan
description: Use when a spec or agreed design for multi-step work needs an implementation plan, before touching code, or when an existing plan's items need their status recorded with evidence. Triggers on "write a plan", "plan this", "write-plan", "record TASK-3".
argument-hint: "<title> [--spec PATH] [--base BRANCH] [-- <guidance>]"
---

# write-plan: a plan whose claims are checked

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. Before
it: the plan title and the `new` flags (`--spec`, `--base`, `--no-fetch`), passed to `new` unchanged. After it:
guidance for writing the plan (scope, a constraint, files to read first); it never reaches a command.

A plan here is an ActionPlan JSON the driver checks, not prose. Every claim about existing code is an
**anchor** the driver opens; every search the plan relies on is a **sweep** the driver reruns; every test is
a **real file** the plan holds, and every item is marked done only by `record`, which reruns its tests at the
commit. The PIP markdown is rendered from the JSON and never edited by hand.

`PLAN` below stands for `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/plan.py"`,
run with the Bash tool from the project checkout. Every refusal is a `problem:` line and exit 1.

## Steps

1. **Start.** `PLAN new "<title>" --spec <spec path>`. It prints the plan file, the PIP and the folder for
   planned test files, and records the base commit (merge base of the base branch and HEAD).
2. **Read before writing.** Open the spec, then every file the work touches and every consumer of a symbol
   the work changes (callers, registries, `setattr` or monkeypatch sites, strategy tables, `partial`s).
3. **Write the plan JSON** (Edit or Write on the plan file; before `freeze` this is the authoring path). The
   fields, all in `ActionPlan.schema.json`:

   | Field | Carries | Checked by `check` |
   |---|---|---|
   | `decisions[]` | each design question, its options and `chosen` (null = open) | chosen is one of its options |
   | `values[]` | every threshold, count or band copied from the spec or the code, with `assumes` | no value assumes a rejected option |
   | `formats[]` | every literal format another component parses, with `source` (an anchor at its producer or parser) | the source anchor |
   | `sweeps[]` | every search the plan relies on (old names, moved paths) with each hit file classified | reruns the pattern; unclassified hits and stale classifications fail |
   | `items[].anchors` | `{at: "path:12-18", expect: "<text>"}` for each fact about existing code the item uses | opens the range, compares the text |
   | `items[].tests` | `{node, red}`: the pytest node and the exception that fails it before the work | the node's file exists or is planned |
   | `items[].commands` | `{run, expect, writes}`: generation and verification commands | no commit SHA (use `{base}`), no pytest run of a directory or of no file |
   | `items[].files`, `dependencies`, `model` | the item's file set, order and implementing model | known ids, no cycle |

4. **Write the planned tests** as real files under `<plans dir>/<plan_id>/tests/<repo-relative path>`, the full
   content each test file will have. No test code goes in the JSON or the PIP.
5. **`PLAN check <id>`** until it passes. A stale anchor means the plan's picture of the code is wrong: reread
   the code and fix the plan, not the anchor's text alone. `open:` lines are decisions still to settle.
6. **Settle open decisions with the developer.** No decision defaults to an answer; an open one blocks freeze.
7. **`PLAN freeze <id>`**. It refuses any check problem, any open decision and any open item with neither a
   test nor a command. After the freeze only `record` changes the plan; `check` reports any other edit. A
   change of design after the freeze is an edit plus `freeze --refreeze`, stated to the developer.
8. **Hand off** the PIP path for review and an execution method. Each implemented item is recorded with
   `PLAN record <id> <ITEM> --sha <commit>`: it needs the item's dependencies done, the commit reachable from
   HEAD and changing one of the item's files, the item's files unchanged since that commit, and the item's
   test nodes passing. `--start`, `--blocked "<reason>"` and `--closed "<rationale>"` set the other states.

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

## Related

- `${CLAUDE_PLUGIN_ROOT}/scripts/plan.py`: the driver; `--help` on each subcommand lists its options.
- `${CLAUDE_PLUGIN_ROOT}/schemas/ActionPlan.schema.json`: the plan's fields.
- `harness:parallel2`: dispatches independent items in waves.
