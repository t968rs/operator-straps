---
name: writing-docstrings
description: Use when writing, restyling or reformatting Python docstrings, when a docstring is a placeholder such as "Push.", "Get desc." or "Generate tables.", when a docstring is a paragraph of prose describing behavior rules, or when choosing a docstring layout (brief, compact or full).
argument-hint: "<path> [<path> ...] [<symbol> ...] [--include-new | -in] [--parallel | -p] [-- <guidance>]"
---

# writing-docstrings: the session reads the request, the docstring-writer agent writes

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. Before
it: paths, symbols and flags for the driver. After it: guidance for this run (a tier preference, a symbol to
read hard); it never reaches the driver and rides on every dispatch prompt as the last line.

The docstrings are written by the `harness:docstring-writer` agent, which carries the three-tier convention
(`${CLAUDE_SKILL_DIR}/docstring_format.md`) and the tier command. The session turns the request into driver
arguments, dispatches the rows the driver prints and relays the replies. **The session never edits a
docstring itself**: not one placeholder, not "just this once" before a merge, not because an agent for one
line looks wasteful. The agent is the one place the convention is applied, measured and checked.

## Read the request

| Argument | Means |
|---|---|
| `<path>` | a `.py` file (every function in it), a folder (its git-tracked `.py` files) |
| `file.py::name` | that file, narrowed to `name` (a function, method or qualname such as `C.h`) |
| `<symbol>` | a bare name; narrows the one file in scope |
| `--include-new`, `-in` | the agent also writes docstrings for the undocumented functions in scope |
| `--parallel`, `-p` | one agent per file, after a tool probe |

- Resolve what the request names into paths with Grep or Glob; when the files still cannot be told, ask.
- **`-in` only on an explicit ask** for new docstrings ("add docstrings", "document the undocumented
  functions"), or for functions the session wrote itself in this task: then `-in` with each new function as
  `file.py::name`, so the agent writes those and nothing else. "Restyle", "tidy", "make consistent", "docs are
  thin", "you're in those files anyway" or a deadline never set it: without `-in` the agent lists the
  undocumented functions, and the reply asks the developer.
- **The request's other instructions travel as guidance.** "Keep it light", "look hard at `open_pool`", "the
  caveat must survive": with no `--` tail, those words become the `Developer guidance:` line, verbatim where
  possible.
- A question about which layout to use ("brief, compact or full?") is answered from
  `${CLAUDE_SKILL_DIR}/docstring_format.md` and the tier rules there, without a dispatch.

## Procedure

1. **Run the driver** with the Bash tool:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/skills/writing-docstrings/commands/docstring_dispatch.py" <paths and symbols> [-in] [-p]
   ```

   Each row is an `agent=harness:docstring-writer model=<m>` line and its prompt lines; rows are separated by
   one blank line. A `problem:` line (a missing path, an unknown symbol, a file named both whole and with
   `::`) names the input to fix; nothing was printed and no probe written.

2. **Probe first under `-p`.** With two or more files the first row ends in `Probe: yes` (model `haiku`).
   Dispatch it alone. Its reply is two lines, `Probe tier:` and `Probe edit:`. Any `BLOCKED`, or a permission
   prompt the developer saw, stops the run: fix the rule with the `update-config` skill and run the driver
   again. Whatever the outcome, then remove the probe files:

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/skills/writing-docstrings/commands/docstring_dispatch.py" --clear-probe
   ```

3. **Dispatch every work row in one message**, one call per row, with the row's model, never another:

   ```
   Agent(subagent_type="harness:docstring-writer", model=<model from the row>, prompt=<the row's lines after the agent= line>)
   ```

   When there is guidance, each prompt gains one last line, newlines folded to spaces:
   `Developer guidance: <text>`.

4. **Relay the replies unedited**, concatenated in row order under `-p`. The session does not re-read the
   files to second-guess them; it reads them only to paste docstrings back when the developer asks.

## Parallel runs without worktrees

`-p` departs from `harness:parallel2`: the agents edit the checkout directly, with no worktree per lane. One
file per agent keeps the lanes disjoint by construction, and a worktree, a staging step and a cleanup per file
cost more than the edits they would isolate. The probe row stands in for the parallel2 probe: it meets the
same Edit allow rules as the work rows, because each probe file sits in a folder the work rows edit.
