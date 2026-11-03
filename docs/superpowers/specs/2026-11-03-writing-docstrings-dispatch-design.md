# writing-docstrings dispatches a defined agent

Issue #175 (TODO-014). Date: 2026-11-03. Branch: `1117-writing-docstrings` (from `main` at 577f516).

## Intent

`harness:writing-docstrings` runs its whole procedure in the main session today: the tier command output, every
file read and every docstring edit land in that context. The change moves the work into a defined agent,
`harness:docstring-writer`, and leaves the session one job: turning the developer's request into explicit
arguments. A driver turns those arguments into dispatch rows, so the mechanical part (flags, file resolution,
the per-file split) is code with pytest coverage rather than prose the session must follow.

## Goals

- The skill dispatches `harness:docstring-writer` with an explicit model; the agent measures, states the tier
  lines, writes and re-measures.
- The session interprets intent before dispatch: which files and symbols, whether new docstrings were asked
  for, and the guidance for the run.
- `--include-new` / `-in` (default off) pre-answers the undocumented-symbols question, so the agent never needs
  to ask the developer mid-run.
- `--parallel` / `-p` (default off) splits the work into one dispatch per file.

## Non-goals

- No change to the tier rules, the layouts, `docstring_format.md` or `docstring_tiers.py` output.
- No `harness:parallel2` worktrees for `-p` (Decision D5).
- No second dispatch to add docstrings after the developer answers; the developer reruns with `-in`.

## Anti-goals (a failure even if it runs)

- The agent adds a docstring to an undocumented symbol without `New docstrings: yes` in its prompt.
- The session sets `-in` because the request said "restyle", "tidy", "standardize" or "make consistent".
- Two `-p` agents edit the same file.
- The session edits a docstring itself, or re-reads the agent's files to second-guess its reply.

## Constraints

- Plugin stays generic; the driver activates the project config once and writes only under the project
  (the probe file of D5), never under `plugin_root()` (`tests/contract/test_root_separation.py`).
- Scripts run through `hpy`; agents are dispatched as `harness:<name>`; skill-local files as
  `${CLAUDE_SKILL_DIR}/...`. The agent file cannot use `${CLAUDE_SKILL_DIR}`: it names
  `${CLAUDE_PLUGIN_ROOT}/skills/writing-docstrings/docstring_format.md`.
- The guidance tail never lands on a command line (`reference/skill_arguments.md`): the driver prints rows
  without it and the session appends the `Developer guidance:` line to each prompt.
- The change goes through `harness:strap-skills --edit`. That needs `"strap": {"target": "harness"}` in
  `.claude/harness.json`; 0.51.0 carries the key and is on `main` since PR #188, so the line lands first, with
  the CLAUDE.md "Strapping a harness skill" paragraph updated to say it is in place.
- The harness plugin version bumps (0.51.0 to 0.52.0).

## Approaches

| # | Approach | Trade-off |
|---|---|---|
| 1 | Agent owns the procedure; SKILL.md prose parses the flags and fills one prompt block (todo-edit pattern) | Fewest files; flag and split rules testable only by scenario runs |
| 2 | Agent owns the procedure; a driver parses the arguments and prints one dispatch row per agent (pr-review `capture` / strap `run` pattern) | One more driver and a small model; flags, path resolution and the split become mechanical behaviors under pytest |
| 3 | Procedure stays in the skill folder as `procedure.md`, read by a thin agent each run | Convention stays in one folder; an extra read per run and agent behavior defined outside the agent |

**Chosen: 2** (developer's pick). It follows the CLAUDE.md rule that a setting a driver can read and act on
belongs in the driver, not in skill prose, and it splits mechanical from judgment behaviors the way the strap
gate grades them.

## Decisions

Developer decisions are marked (developer); the rest are design calls, marked (call), open to correction.

- **D1 Arguments** (call): `<path> [<path> ...] [<symbol> ...] [--include-new | -in] [--parallel | -p]
  [-- <guidance>]`.
  - A token that names an existing `.py` file or a directory is a path; a directory expands to the git-tracked
    `.py` files under it, sorted.
  - Each file in scope carries its own scope: `all` (every function and method) or a list of names.
  - A bare path token puts its file (or each expanded file) in scope as `all`.
  - `file.py::name` puts `file.py` in scope narrowed to the names given for it; no separate path token is
    needed. A file named both bare and with `::` is a `problem:` line (ambiguous scope).
  - Bare symbols are allowed only when exactly one file is in scope (the current `<file> [<symbol> ...]` form
    keeps working, as that file's list); bare symbols with two or more files are a `problem:` line.
  - Every named symbol is checked against the file before any row prints (the API's `report` and `unmatched`),
    so no `-p` agent meets an unknown symbol mid-run.
  - A path outside the project, a missing path, a directory with no tracked `.py` file, a file that does not
    parse, an unknown symbol and an unknown flag are `problem:` lines, exit 1, nothing printed on stdout.
  - Scope is functions and methods only, the units the tier command reports. Module and class docstrings are
    out of scope for this change: never added, and an existing one is left as it is.
- **D2 `--include-new` / `-in`** (developer): default off. The prompt carries `New docstrings: yes|no`. Off: the
  agent leaves undocumented symbols undocumented and lists them under `Undocumented (rerun with
  --include-new):`. On: the agent writes one for each undocumented function or method in its file's scope
  (D1), tier line first; a file listed with names gets docstrings only on those names.
- **D3 Session intent** (developer goal, call on detail): the session maps the request onto D1's arguments. It
  may Grep or Glob to resolve a named function or module to a path; it does not run the tier command or read
  the files' docstrings. Only `-in`, or the developer asking for new docstrings in so many words, sets `-in`;
  restyle words never do. The words may sit in the request or in the `--` guidance tail: interpreting them is
  the session's job, so the session passes `-in` to the driver and the agent never sees a guidance line that
  contradicts `New docstrings:`. When the request names no files and the session cannot resolve one, it asks.
- **D4 `--parallel` / `-p`** (developer): default off. Off: one row covering every file. On: one row per file,
  each with that file's symbols. With one file in scope `-p` yields one row, silently.
- **D5 Parallel edits land in the checkout** (developer, on the recommendation): one file per agent makes file
  sets disjoint by construction, which is the collision guarantee `harness:parallel2` checks, so worktrees add
  setup and staging for nothing. The other parallel2 prong stays: before a `-p` dispatch of two or more rows,
  the driver writes `_docstring_probe.py` in the first target file's folder (developer, on the
  recommendation: the probe then meets the same Edit allow rules as the real rows, which a file under
  `state_dir` would not) and prints a probe row (the same agent, model `haiku`, `New docstrings: yes`, scope
  the probe file). The session dispatches it alone first, then removes the probe file with a driver
  subcommand whatever the outcome; a driver run that finds a stale probe file removes it before writing a new
  one. A tool prompt or denial stops the run and is fixed with the `update-config` skill before the real rows
  go. SKILL.md states this departure from the parallel2 rule and the reason. The probe file is written and
  removed only under the project, never under `plugin_root()`.
- **D6 Model** (call): `opus` for every work row, in both modes (tiering turns on reading caveats, the
  judgment behaviors B6-B8). The agent frontmatter names `opus` as the fallback only; the row's model is
  always passed.
- **D7 Row format** (call): the existing `agent=<type> model=<m>` first line, then prompt lines, rows
  separated by a blank line:

  ```
  agent=harness:docstring-writer model=opus
  Project root: <abs>
  New docstrings: yes | no
  Scope: <abs path>: all
  Scope: <abs path>: <name>, <name>
  ```

  One `Scope:` line per file in the row, in path order.

  The probe row adds `Probe: yes`. Lines and order are a pydantic model in `writing_docstrings_models.py`; the
  agent's brief names the same lines.
- **D8 Agent reply** (call): per file, in this order: tier lines (`<symbol>: tier <n> - <lines> lines, <forks>
  forks; <reason>`), `Rewritten:`, `Kept (in layout):` with the reason, `Undocumented (rerun with
  --include-new):` (absent under `yes`), `Defects (not fixed):`, and `Check:` with the final tier-command result
  (every `current=` matches its tier, no flags left, or what remains). The session relays one reply as it
  stands; for `-p` it concatenates the replies in row order, unedited.
- **D9 Agent tools** (call): `Read, Edit, Grep, Bash`. The agent edits only the files on its `Scope:` lines;
  Bash is for the tier command through `hpy` and read-only git.

## Parts

| Part | Change |
|---|---|
| `plugins/harness/agents/docstring-writer.md` | New. Holds the procedure now in SKILL.md: what a restyle touches, measure, tier answer, tier layouts, all-tier rules, re-measure; plus the prompt lines (D7), the `New docstrings` rule (D2), the edit scope (D9) and the reply (D8). |
| `plugins/harness/skills/writing-docstrings/SKILL.md` | Rewritten as: split the arguments, interpret intent (D3), run the dispatch driver, probe when `-p` prints one, dispatch every row in one message with the guidance line appended, relay. States the D5 departure. Keeps the `Use when` description (the triggers do not change). |
| `plugins/harness/skills/writing-docstrings/commands/docstring_dispatch.py` | New driver, next to `docstring_tiers.py`: parses D1, prints D7 rows on stdout, `problem:` lines on stderr. |
| `plugins/harness/lib/harness_lib/writing_docstrings_models.py` | Adds the request and row models (D7). |
| `plugins/harness/lib/harness_lib/writing_docstrings_api.py` | Adds path resolution and row planning; exported in `__all__`. |
| `tests/skills/test_writing_docstrings_skill_contract.py` | The tier-command, flag-name and threshold pins move from the SKILL.md body to the agent file; new pins: SKILL.md runs the dispatch driver through `hpy` and dispatches `harness:docstring-writer`. |
| new driver and API tests | Flag parsing, `::` scoping, directory expansion, the bare-symbol refusal, `-p` split and single-file fallback, probe file and row, each `problem:` line. |
| `tests/contract/test_root_separation.py` | A `docstring-dispatch` case: a `-p` run over two files writes the probe beside the first, under the project, and nothing under `plugins/`. |
| `README.md` | Skills-table row names the agent and the two flags. |
| `.claude/harness.json`, `CLAUDE.md` | The `strap.target` line and the updated paragraph (Constraints). |
| `plugins/harness/.claude-plugin/plugin.json` | 0.52.0. |

## Strap

`strap.py new writing-docstrings --edit` against HEAD. The edit spec covers the behaviors the change adds or
moves:

- mechanical: D1 parsing and refusals, D4 split, D5 probe file and row, D7 row lines, the contract pins;
- judgment: D3 (the session does not set `-in` from restyle words; a scenario with "make these consistent" over
  a file with undocumented functions), and B6-B8, whose prose moves from SKILL.md to the agent file, so their
  greens are pinned to a new content hash and need fresh runs.

## Left to the builder

- `strap.py new --edit` resumes an existing spec, and the one at `docs/plans/strap/writing-docstrings/` is a
  frozen `new` spec whose B6-B8 scenarios play the session role; moving them onto `docstring-writer` role
  scenarios needs a fresh edit spec. How the old one is set aside follows what the driver accepts.
- Exact wording of the agent file and SKILL.md, and the names of the new models and functions.
- Whether the probe file content is a fixed literal in the driver or a template next to it.
