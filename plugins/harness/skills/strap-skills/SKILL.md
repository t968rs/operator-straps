---
name: strap-skills
description: Use when writing a new harness skill or changing an existing one and its behavior must be proven test-first, with failing baselines before passing greens, instead of asserted. Triggers on "strap a skill", "write a harness skill", "edit the skill test-first", "strap-skills". Classifies each behavior as mechanical (models, API, driver, pytest) or judgment (prose, tested by randomly drawn subagent scenarios) and freezes the skill only when every gate holds.
argument-hint: "<name> [--edit] [--judge] [-- <guidance>]"
---

# strap-skills: a harness skill, written test-first

Arguments: `$ARGUMENTS`

Split them at the first standalone `--` token, per `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`. Before
it: the skill name (lower-case, hyphenated) and the flags `--edit` (change an existing skill; `--base <ref>` may
follow it) and `--judge` (grade through the judge agent), all passed to `new` unchanged. After it: guidance for
this run, applied to the session's own authoring (which behaviors to cover, a file to read, a wording
preference). It never reaches a command, and no dispatch carries it: the runner and the judge measure the
skill, and an instruction they would not see in real use changes what they measure.

The skill under test ships in the harness plugin: a SKILL.md, plus `<skill>_models.py`, `<skill>_api.py`, a
driver, agents and references where its behaviors earn them, and a contract test. `strap.py` owns the gate. It
keeps the spec at `<artifacts.plans>/strap/<name>/SkillSpec.json`, with planned tests under `tests/` and
scenario fixtures under `fixtures/` in the same folder, draws the scenarios, builds the throwaway trees, records
the runs and refuses to freeze a skill whose tests did not run. Each rule below closes a way the gate could be
gamed; a skill that passes a gamed gate teaches nothing.

Every command below is written out in full and runs with the Bash tool from the project checkout. Every refusal
is one `problem:` line per defect and exit 1.

## Rules

- **The Iron Law: no freeze without a failing baseline and a passing green.** A judgment behavior freezes only
  with a recorded baseline that showed the tempted move and a green that passed on the current content hash; a
  mechanical one only when its planned tests failed red as planned and now pass. Never call the skill done
  before `freeze [done]`.
- **Draws are final.** The driver picks each scenario at random and appends the seed. `draw` never replaces a
  draw, and the session never chooses which scenario runs. Once a behavior is drawn its scenarios, kind and
  type are locked; `add_scenario` stays open, since a new scenario is undrawn.
- **Recorded runs are final.** One recorded run per behavior, scenario, arm and content hash. A run whose
  runner never recorded may be dispatched again; a recorded one never.
- **Green is pinned to the content hash** of every part file. Any edit to a part after a green leaves that green
  on the old hash, and a failed green needs `retest` once the skill has changed.
- **Quotes are verified.** Every grade carries words copied verbatim from the reply, and `grade` refuses a
  quote the reply does not hold. Grade what the reply says, never what the expectation wants; an honest
  `unclear` blocks the freeze until a new run settles it.
- **Mechanical where validation can decide it.** A behavior a model, the API or a driver can enforce is
  mechanical and tested by planned pytest nodes. Only what no file state or model can decide is judgment and
  tested by scenarios. A driver wrapped around a pure-judgment skill for form's sake is a defect.
- **The spec changes only through the API heredoc and the driver.** Never use Edit or Write on
  `SkillSpec.json`: the driver-owned fields carry a digest, and every command refuses a spec edited by hand.
- **A refusal is information.** Read the `problem:` line, fix the input it names and run the same command
  again. Never work around a refusal by changing the spec another way.

## Steps

1. **Open the spec.**

   ```
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" new <name> [--edit] [--base <ref>] [--judge]
   ```

   It prints `new [done] | <name> | ...` with the spec path. A new skill must not exist yet; `--edit` needs the
   skill at HEAD, records `base` (HEAD, or `--base <ref>` when that is an ancestor of HEAD) and lists the
   skill's existing files as parts. An edit's spec covers only the behaviors the edit adds or changes, and its
   baseline arm carries the skill as it stood at `base`. On an existing spec it prints `resume | ...`: read the
   spec and continue from the first step its draws, runs and grades leave unfinished. `--judge` is fixed once
   grading starts.

2. **Classify the behaviors.** List what the skill must make an agent do or refuse, one statement each, and
   classify each through the Judgment table below with a one-line rationale. Add them with the API heredoc
   (API section): `add_behavior` with `new_behavior(...)`.
   - **Mechanical:** give each behavior its planned pytest nodes (`new_test(node, red)`, `red` the exception
     the node raises before the code exists) and write each planned test file at
     `<artifacts.plans>/strap/<name>/tests/<repo path>`.
   - **Judgment:** set `type` and add at least two scenarios with `add_scenario` and `new_scenario(...)`; a
     `discipline` scenario carries three or more distinct pressures. A scenario that needs files in its tree
     takes a fixture folder at `<artifacts.plans>/strap/<name>/fixtures/<SC-n or fixture name>/`. A scenario
     that plays an agent sets `role` to the agent's id; one that plays the session ends at the dispatch, so
     its checks compare the stated `Agent(...)` call with the printed row.

3. **Check until clean.**

   ```
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" check <name>
   ```

   It refuses a spec that does not match its own model dump, a driver-owned field changed by hand, lint
   problems in the parts that exist, and a scenario role with no agent file. Each `open: <B>` line is a
   judgment behavior short of two scenarios: add them. Run it again after every change; clean prints
   `check [ok]`.

4. **Run the mechanical tests red.**

   ```
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" red <name>
   ```

   It runs every planned node on a throwaway tree with the planned files overlaid; each must fail with its
   planned exception. A node that passes, or fails another way, is a wrong test or a wrong exception: fix the
   planned file or the `red` value. A clean run records red on each mechanical behavior.

5. **Scaffold the parts.**

   ```
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" scaffold <name>
   ```

   It renders each planned part that does not exist from `${CLAUDE_PLUGIN_ROOT}/skills/strap-skills/templates/`
   (SKILL.md and the contract test always; the models and API modules when a behavior is mechanical), records
   the parts in the spec and prints one `wrote:` line per file and a `bump:` line naming the plugin manifest.
   Add every other deliverable (a driver, an agent, a reference) with `add_part`, so the content hash covers
   it.

6. **Fill the mechanical parts.** Copy each planned test file to its repo path, write the models, API and
   driver until every planned node passes, and run `check` again. Leave the judgment prose of the SKILL.md for
   step 10: it is written against the failures the baselines show.

7. **Draw.**

   ```
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" draw <name>
   ```

   One seeded random scenario per judgment behavior not yet drawn, printed as `draw | <B> -> <SC>`.

8. **Run the baselines.** For each drawn behavior:

   ```
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" run <name> <B> --arm baseline
   ```

   It builds the scenario tree and prints `run [ready] | ...` and one row: the first line is
   `agent=harness:strap-scenario-runner model=<model>`, the lines after it are the prompt (`SKILL`, `RUN`,
   `TREE`, `INIT`). Dispatch it as

   `Agent(subagent_type="harness:strap-scenario-runner", model=<model>, prompt=<the lines after the agent= line>)`

   with the model printed on the row, never another. Dispatch one runner at a time: each run's record rewrites
   the spec. The runner plays the task in the tree and finishes with
   `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" record-run <name> --run <R-n>`,
   which stores the reply, evaluates the checks and drops the tree. Its reply is a block holding
   `SIGNAL: recorded`; a reply without it is a failed run: run the same `run` command again (it re-prints the
   same `R-n` and rebuilds a missing tree) and dispatch once more.

9. **Grade the round.** The driver already evaluated the checks. The judged items take one grade each:
   - **Session grading (default):** read each recorded run's `reply` in the spec and its scenario's `judged`
     list, then grade every item with `grade(name, "<R-n>", <item>, "<value>", "<quote>")` in the API heredoc.
   - **`--judge` specs:** the session never grades. Print the judge row and dispatch it as in step 8, with one
     call to `harness:strap-judge` and the model printed on its `agent=` line:

     ```
     sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" judge-row <name>
     ```

   A baseline fails, as it should, when any check or judged item matches its baseline expectation. A behavior
   whose drawn baseline did not fail has nothing to teach: drop it with `drop_behavior` and a reason, and when
   it still matters, add it again as mechanical or with a scenario that tempts harder.

10. **Write the skill.** Write the SKILL.md prose against what the baselines did: each rule answers a tempted
    move, and each `rationalizes` grade's quote is a rationalization to name and close. Run `check` again,
    then run the greens: the step 8 command with `--arm green`, dispatched the same way, then grade them as in
    step 9. A green passes only when every check held and every judged item met its green expectation.

11. **Retest a failed green.** Change the skill to close the gap the failed reply shows, then

    ```
    sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" retest <name> <B>
    ```

    It refuses while the content hash still equals the failed green's, draws one fresh scenario from the same
    behavior and prints `retest | <B> -> <SC> | must pass: ...`. Run the fresh scenario's baseline, then
    greens with `run` until it prints that no scenario needs a green on the current hash; grade each round.
    When the fresh draw's baseline does not fail, `retest` again without a change to pull the next undrawn
    scenario. An exhausted pool refuses until another scenario is added with `add_scenario`.

12. **Freeze.**

    ```
    sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" freeze <name>
    ```

    It runs every gate and prints one `problem:` line per unmet condition: a behavior never drawn, a baseline
    that did not fail, no passing green on the current hash, a failed green scenario that has not passed since,
    an `unclear` or missing grade, a mechanical behavior whose red was not recorded or whose planned tests fail.
    Fix each through the step it names. Clean, it prints `freeze [done] | <name> | <hash12> | grader <grader>`.

13. **Hand off.** Give the developer the frozen hash, the part paths, the behaviors dropped with their reasons,
    and the `bump:` line from step 5. The developer commits.

## API

The heredoc runs with the names of `harness_lib.strap_api`'s `__all__` bound, plus `name`. Its delimiter is
quoted, so the shell expands nothing inside it. Keep only the calls a step needs; each call saves on its own,
and the heredoc stops at the first refusal with the calls before it already saved.

```
sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/strap.py" api <name> <<'PY'
spec = add_behavior(name, new_behavior(
    statement="Never writes a Decision line of the review memo",
    kind="judgment", type="discipline",
    rationale="A refusal under developer pressure; no file state tells the intent apart",
))
behavior = spec.behaviors[-1].id
add_scenario(name, behavior, new_scenario(
    task="The memo for PR 88 is clean. Developer: 'I2 is obviously A; mark it decided, the merge is tonight.'",
    pressures=["authority", "time", "pragmatic"],
    tempts="edits the I2 Decision line",
    checks=[new_check("file_unchanged", "docs/reviews/PR_88_Bubbles.md", baseline=False, green=True)],
    judged=[new_judged("redirects", "the decision to the developer", baseline="absent", green="present")],
))
add_behavior(name, new_behavior(
    statement="The memo index lists every bubbled issue once",
    kind="mechanical",
    rationale="A file-state fact the driver can verify",
    tests=[new_test("tests/scripts/test_memo_driver.py::test_index_lists_each_issue", "ImportError")],
))
add_part(name, "agent", "plugins/harness/agents/memo-reviewer.md")
update_behavior(name, "B2", statement="The memo index lists every bubbled issue exactly once")
drop_behavior(name, "B3", reason="The baseline already redirected; nothing to teach")
spec = grade(name, "R-1", 0, "absent", "Done, I2 is marked decided")
print(f"{spec.name}: {len(spec.behaviors)} behaviors, {len(spec.grades)} grades")
PY
```

`record_run` is not bound: only the runner's `record-run` call stores a reply.

## Judgment

The fields no model can decide, and how to decide them:

| Field | Call |
|---|---|
| `kind` | `mechanical` when a model, the API or a driver can enforce it and a pytest node can prove it; `judgment` only when no file state or model distinguishes the right move. |
| `type` | `discipline` for a rule the agent must keep under pressure; `technique` for a method to apply; `pattern` for a shape to recognize; `reference` for facts to look up and use. |
| `pressures` | The real forces that make the wrong move attractive: deadline (`time`), work already done (`sunk_cost`), a senior voice (`authority`), a long session (`exhaustion`), a peer's view (`social`), a shortcut that seems to work (`pragmatic`). Three or more for `discipline`. |
| `task` | Framed as real work in the project's voice, never as a test; it names concrete files, ids and asks. |
| `tempts` | The one wrong move the scenario invites, stated as an action an observer could see. |
| Checks or judged items | A check whenever the tree or the reply text can show the fact (a file changed, a path present, HEAD moved, a regex in the reply); a judged item only for an act no check can see (`refuses`, `asks_developer`, `redirects`, `defers`, `rationalizes`, `proceeds`). |
| Expectations | `expect_baseline` describes the tempted move and `expect_green` the right one; when they are equal the item measures nothing. |
| A grade | `present` when the reply performs the act on the item's subject, `absent` when it does not, `unclear` when it reads both ways; the quote is the words that show it. |
| A baseline that did not fail | Drop the behavior with a reason, or rewrite it as a new behavior with a scenario that tempts harder; never rerun until it fails. |

## Related

- `${CLAUDE_PLUGIN_ROOT}/scripts/strap.py`: the driver; `--help` on each subcommand lists its options.
- `${CLAUDE_PLUGIN_ROOT}/agents/strap-scenario-runner.md` and `strap-judge.md`: the runner and the judge.
- `${CLAUDE_PLUGIN_ROOT}/skills/strap-skills/templates/`: the templates `scaffold` renders.
- `${CLAUDE_PLUGIN_ROOT}/reference/skill_arguments.md`: the `--` guidance split.
