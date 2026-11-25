---
name: spec-it
description: Use when a developer asks to build, add, design, spec or brainstorm new work (a feature, a skill, a flag, a behavior change) before any plan exists, or asks for a spec, a brief or a design for write-plan to start from. Triggers on "let's build", "spec this", "spec sheet", "brief for the plan", "design this", "brainstorm", "spec-it".
argument-hint: "<title> [-- <guidance>]"
---

# spec-it: a short spec sheet, then the plan

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. Before
it: the sheet's title (taken from the request when none is given). After it: guidance for this run, applied to
the session's own clarification and writing. It never reaches a command.

A spec sheet is the design step: the developer's request in a short paragraph, then the outcomes the plan must
reach (Goals) and must not cause (Avoid), one line each. `harness:write-plan` takes it as `--spec` and owns
everything after: files, items, tests, structure. The sheet holds no ids, issue numbers, URLs or code, so it
never needs syncing with the plan and stands on its own in a scenario fixture. The model refuses the ids,
issue numbers, URLs and code fences; function, field and module names in prose pass it, and keeping them out
is this skill's Outcomes rule below. The model caps a page at 500 lines; aim for 250 or fewer, and most
requests fit in 40.

## Rules

- **One short clarification round, then the sheet.** Ask only the questions whose answers change a goal or an
  avoid line, all in one message, each answerable in a word or a line. Never lay out alternative designs,
  option menus with a recommendation, decision lists, section-by-section design for approval, file or test
  lists, scope estimates or release steps: those are the plan's work, and an invitation to "brainstorm",
  "think it through" or "do the design" asks for the sheet, not for them. A deadline or a slow earlier design
  is a reason for a shorter round, never for a longer one.
- **Outcomes, not implementation.** A goal or avoid line states what a developer can observe when the work is
  done: a command's output, a refusal, a file that appears, a thing that stays unchanged. It names no
  function, class, field, module, test file or code layout, unless the developer set that name as a
  requirement of the result (a flag, a config key, a command the developer named). Implementation notes the
  developer offers, even with "paste them in" or "be specific, it saves the plan writer time", go to the
  plan: hand them over as the `-- <guidance>` tail of the `next:` write-plan command, and say so.
- **Do not read the code to design.** Read only what tells which outcomes the request means (the README or
  SKILL.md of the thing named). A premise the request gets wrong is a question, not a design finding.
- **One outcome per line.** A line that a plan item could half-pass holds two outcomes: split it. "and",
  "also", "while" and a second sentence are the usual seams. Each "never", "do not", "without" or "must not"
  of the request becomes its own Avoid line, never a clause inside a goal and never a nested bullet.
- **Only what the developer asked for or confirmed.** A fork the request leaves open (which format, which
  destination, which of two meanings) is a question, never an assumed default, even marked "assumed" and
  even when the developer is away and says not to wait: a sheet that needs a guessed goal is not written
  until the answer comes, and the reply ends with the question. Nothing is added to round the sheet out;
  an extra goal worth having is offered as a question.
- **TODO ids and issues ride as refs, never as guidance.** The sheet cannot hold the TODO ids and issue
  numbers the request says the work answers ("this is todo-k69m", "fixes #301"), and write-plan records a
  plan's refs only from `--refs`: guidance text never becomes a ref. Pass each one to `check --refs`, so the
  `next:` line carries it. An id the developer names as unrelated, or only mentions, stays out.

## Steps

1. **Read the request.** Take the title, the outcomes asked for and every "never" or "do not" in it.
2. **Clarify.** When a fork is open, ask its questions in one message and stop; write the sheet once they are
   answered. When none is open, write the sheet now, without a question round.
3. **Write the sheet through the API.** Never Edit or Write the page by hand: `write_sheet` validates the
   whole sheet and renders the only layout `check` accepts. Pass `replace=True` to rewrite a sheet already
   written from the same title and date. To revise an existing sheet, whatever its date, load it and rewrite
   it in place, so its title, date and path stay:
   `write_sheet(load_sheet("<sheet path>").model_copy(update={"goals": [...]}), replace=True)`.
   `new_sheet` dates a sheet today, so building the revision through it writes a second page beside the old.

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/skill_api.py" spec_it_api <<'PY'
   sheet = new_sheet(
       title="<title>",
       request="<the request, restated in a few sentences>",
       goals=["<one outcome the plan must reach>", "<another>"],
       avoid=["<one outcome the plan must not cause>"],
   )
   print(write_sheet(sheet).as_posix())
   PY
   ```

   A refusal is one `problem:` line naming what to fix: a field, a line that appears twice, the page length,
   or an existing sheet (which `replace=True` rewrites). Fix it and run the heredoc again.
4. **Check it.**

   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/spec_it.py" check <sheet path> [--refs <todo id or #issue> ...]
   ```

   It prints `check [ok]` with the line, goal and avoid counts, a `warn:` line past the 250-line target and a
   `next:` line naming the write-plan command, each ref a quoted `--refs` token on it; `problem:` lines and
   exit 1 otherwise, a ref that is neither a TODO id nor an issue number included.
5. **Hand off.** Show the developer the sheet and the `next:` line as `check` printed it, refs included, with
   any implementation notes appended as its `-- <guidance>` tail. The plan starts from the sheet as written.

## Judgment

| Situation | Call |
|---|---|
| "Brainstorm this with me", "do the design pass", "the usual design" | Ask the open questions or write the sheet; no options, sections or design document. |
| The developer pastes how to build it | Goals keep the outcome; the notes ride to write-plan as guidance. |
| "Be specific: name the functions and fields" | Outcomes only in the sheet; offer the names as write-plan guidance. |
| A request joins several asks with "and" | One goal line per ask; each "do not" an Avoid line. |
| The request leaves a fork open and the developer is offline | Ask the question and write no sheet that guesses it. |
| "Round it out with whatever else it needs" | Write the asked goals; offer extras as questions, not lines. |
| A `problem:` line from the API or `check` | Fix what it names (a field, a repeated line, the length, an existing sheet) and rerun; never edit the page by hand. |
| "This is todo-k69m and fixes #301" | Keep both out of the sheet; `check --refs todo-k69m '#301'`, so `next:` carries them. |
| "#288 is linked but unrelated, leave it out" | No ref for #288; refs only for what the work answers. |
| The developer asks to change a sheet written on an earlier day | `load_sheet` it, `model_copy` the changed fields, `write_sheet(..., replace=True)`; never `new_sheet` a second copy. |

## Related

- `${CLAUDE_PLUGIN_ROOT}/lib/harness_lib/spec_it_models.py`: the sheet's fields, banned patterns and
  page layout.
- `${CLAUDE_PLUGIN_ROOT}/skills/write-plan/SKILL.md`: the plan that takes the sheet as `--spec`.
- `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`: the `--` guidance split.
