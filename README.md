# `operator-straps`

[![ci](https://github.com/t968rs/operator-straps/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/t968rs/operator-straps/actions/workflows/ci.yml)

**Give Claude Code a repeatable process for reviewing PRs, applying fixes, and preparing changes for handoff.**

Install the workflows you need: review a PR with multiple agents, carry findings through fix waves and closeout,
draft commit messages and PR summaries from the diff, or start work in an isolated worktree. Add optional plugins
to track review progress, keep Git state visible, preserve context through compaction, and scope pytest runs.

[Choose a workflow](#what-you-can-do) · [Install](#install) · [Configure a project](#configure-a-project)

## What you can do

| Your goal | Use | What you get | Agent 'Ensurance' |
|---|---|---|---|
| Review a PR and work through its findings | `harness`: `pr-review` or `pr-team` | Multiple reviewers, a consolidated review, branch checks before fixes, and fix waves with recorded resolutions. `pr-team` keeps finding details out of the main session's context. | • Configured agent-use Python runtime via `hpy`.<br>• Branch checks before fixes; schema validation on review writes.<br>• `Stop` hook blocks a stop attempt while the review session has an active Phase 5 sentinel. |
| Draft a commit message or organize a branch's changes | `harness`: `c-msg`, `branch-commit-msg`, `amend-commit-msg` | A message for the pending change, a proposed breakdown into commits, or an amendment of that breakdown (rewritten messages, files moved between blocks), saved in your project's artifact folders. | • Configured Python runtime via `hpy`.<br>• Build checks file coverage and message format before saving the draft. |
| Explain a PR to the next reviewer | `harness`: `pr-sum` | A summary grounded in PR metadata and the diff. `--level 1\|2\|3` sets how much it draws (1 prose only, 2 flows and Changed Symbols, the default, 3 more diagram types); `--min-viz` at level 3 holds the session until the summary holds the diagram blocks. | • Script captures PR metadata, commits, file lists, and counts.<br>• Build requires a title, summary, and descriptions covering the listed non-artifact files. |
| Start a task in an isolated checkout | `harness`: `d-w` | A detached-HEAD worktree cut from HEAD, an integration branch, or another ref. | • Script resolves the base ref to a commit and creates a detached worktree.<br>• Failed integration-branch fetches stop creation; directory collisions get a fresh path. |
| See where an agent-driven review stands | `pr-review-watch` | A review progress band, pending-fix context, reviewer matrix rows and a per-agent usage log (every dispatch of an agent this marketplace defines), and a Stop guard for unrecorded escalated issues. | • `Stop` guard checks that escalated issues are recorded in the review.<br>• Usage rows come from engine measurements and must pass schema validation before append. |
| Keep the current branch and working tree in view | `git-status` | Git state checked on each prompt, changed state added as `GIT_STATE` context, and a fallback Git status line. | • Prompt hooks recheck Git state and inject changed state.<br>• Git context is reinjected after clear, resume, or main-conversation compaction.<br>• The fallback line gives way to ccstatusline or `band-line`. |
| Choose how the Git banner looks | `banner-status`: `setup-statusline`, or `band-line` | ccstatusline as the project's status line (git branch and uncommitted changes, then model, thinking effort and context window; no prefix), or an `oStraps:` band above the prompt with the model and context window. ccstatusline is an optional dependency: it needs Node.js and npm, and `setup-statusline` offers to run `npm install -g ccstatusline@~2.2.32` for you. `band-line` needs no install. | • The skill writes `.claude/settings.json` `statusLine` and `.claude/ccstatusline.json` only after the user approves each edit.<br>• `band-line` reads the `git-status` snapshot; neither draws without `git-status`. |
| Carry working context through compaction | `session-bookmark`, with `harness`: `add-bookmark` | Git state, recent prompts, your session notes (`/harness:add-bookmark <note>`, `--list`, `--clear`) and your `/compact` instructions added to the compacted conversation. | • Compaction hooks capture Git state, the last three prompts, the stored notes, and `/compact` instructions.<br>• Bookmark is appended to the compacted transcript and retained in session state.<br>• The session itself writes each note, so a reference such as "the current status" becomes the facts it stands for; a script stores it (at most 20 notes, 300 characters each). |
| Keep a project's TODO catalog and its sync checks in view | `todo-watch` | The next TODO items and a live sync status line in a band above the prompt (kept until dismissed), a `TODO_SYNC` drift line in prompt context, and `/todo` with the top items and every finding. | • Active only when `.claude/harness.json` sets `todo.folder`.<br>• Watched-file edits re-run the harness `todo_sync` checks; every hook fails open. |
| Run targeted tests with the intended Python | `pytest-scope` | Optional rewriting of bare `pytest` to your chosen interpreter and rejection of runs without an explicit test file or node ID. | • When configured, Bash hooks rewrite recognized pytest commands to the selected Python.<br>• Scope hooks reject broad runs when `require_test_file=true`; `/pytest-broad-ok` allows one override. |

## Agent process standardization

The `harness` plugin packages the procedure as skills, scripts, agents, and hooks. You configure the project's
test layout, guard suites, base branch, and output folders once in `.claude/harness.json`; subsequent runs
use the same process with those project settings.

For example, a PR review follows five phases:

```mermaid
flowchart LR
    accTitle: Agent process standardization for PR review
    accDescr: Project configuration supplies guards, branch rules, and output paths to a shared five-phase process. Capture and guards lead to reviewers, consolidated findings, branch verification, then fix waves and closeout. The review and resolutions are saved in the consuming project.
    config["Project configuration<br/>.claude/harness.json"]
    capture["1 · Capture<br/>PR facts + guards"]
    review["2 · Review<br/>Scoped reviewers"]
    findings["3 · Consolidate<br/>Findings + verdict"]
    safety["4 · Verify branch<br/>Before code changes"]
    fixes["5 · Fix + close out<br/>Waves + resolutions"]
    artifacts["Project artifacts<br/>Review + resolution record"]

    capture --> review --> findings --> safety --> fixes
    config -. "guard suites" .-> capture
    config -. "branch rules" .-> safety
    config -. "output paths" .-> artifacts
    findings --> artifacts
    fixes --> artifacts

    classDef settings fill:#eef2ff,stroke:#6366f1,color:#1e1b4b
    classDef process fill:#f0fdfa,stroke:#0f766e,color:#134e4a
    classDef gate fill:#fff7ed,stroke:#c2410c,color:#7c2d12
    classDef result fill:#eff6ff,stroke:#2563eb,color:#1e3a8a
    class config settings
    class capture,review,findings,fixes process
    class safety gate
    class artifacts result
```

Skills define the steps, scripts validate structured review artifacts, and hooks check workflow conditions.
Branch safety is checked immediately before fixes. Ambiguous issues are escalated for your decision, and
closeout records how findings were handled. Review data stays in your project; plugin code stays in its cache.

The companion plugins are installed separately and are independent of one another, except that `band-line`
reads `git-status`'s snapshot (it lists `git-status` as a dependency) and the ccstatusline line from
`banner-status` replaces `git-status`'s own line only when ccstatusline is installed. Installing
`banner-status` does not install ccstatusline: run `/banner-status:setup-statusline`, which offers
`npm install -g ccstatusline@~2.2.32` (Node.js and npm required), or run that command yourself first.
Until then `git-status` keeps drawing its fallback line.
`pr-review-watch` is active only in projects with `.claude/harness.json`.
`pytest-scope` takes effect only when one of its options is set.
`todo-watch` is active only when `.claude/harness.json` sets `todo.folder`.

## Install

For the review, commit, summary, and worktree workflows, install `harness`:

```sh
claude plugin marketplace add t968rs/operator-straps
claude plugin install harness@operator-straps
```

Add any companion plugins you want:

```sh
claude plugin install pr-review-watch@operator-straps
claude plugin install git-status@operator-straps
claude plugin install banner-status@operator-straps
claude plugin install band-line@operator-straps
claude plugin install session-bookmark@operator-straps
claude plugin install pytest-scope@operator-straps --config python=C:/path/to/env/python.exe --config require_test_file=true
claude plugin install todo-watch@operator-straps
```

After configuring your project below, open Claude Code in that repository and invoke a workflow, for example:

```text
/harness:pr-review 123
/harness:c-msg
/harness:pr-sum 123
/harness:d-w HEAD
/harness:add-bookmark keep the public API frozen until PR 60 merges
```

Replace `123` with your PR number. `pr-review` carries findings into fixes and closeout, so use it when you
want the full review-and-fix workflow. `c-msg` and `pr-sum` save drafts in the configured artifact folders.

### add-bookmark

`/harness:add-bookmark` stores session notes that survive compaction. The session-bookmark mod prints them in its
compaction bookmark, above the `/compact` instructions, so a constraint or reminder stays visible after the summary.

```text
/harness:add-bookmark keep the public API frozen until PR 60 merges
/harness:add-bookmark --list
/harness:add-bookmark --clear
```

| Form | Effect |
|---|---|
| `/harness:add-bookmark <note text>` | Store one note |
| `/harness:add-bookmark --list` | Print the stored notes, numbered |
| `/harness:add-bookmark --clear` | Drop every stored note |

- The session that runs the command writes the stored line, not a separate agent, so a note that points at the
  conversation (`the current status of the banner options`, `what we built`) is stored as the branch, versions,
  ids and pending checks it refers to, in the same turn. Text that already stands alone is stored as written,
  apart from quoting and length.
- A project holds at most 20 notes; `--clear` frees the slots. A note longer than 300 characters or a blank note is refused.
- Notes are stored per project in `session-bookmark/notes.json` under `state_dir` (default `.claude/state/harness`).
  Add that folder to `.gitignore`, as with the other runtime state.
- The notes file is versioned (`"version": 1`). A file that is not JSON or has another version is refused rather than
  overwritten; run `--clear` to reset it.
- For what the compaction bookmark prints and how the mod reads the notes, see `plugins/session-bookmark/README.md`.

### amend-commit-msg

`/harness:amend-commit-msg` amends the commit breakdown that `branch-commit-msg` drafted, instead of redrafting it.
The session that runs it knows what changed since the draft, which the forked `branch-commit-msg` agent does not.

```text
/harness:amend-commit-msg -- the review fixes landed; restate blocks 2 and 3
/harness:amend-commit-msg --base HEAD~3 -- move tests/test_x.py into the runtime block
```

- Arguments before ` -- ` are the `branch-commit-msg` capture arguments (`REF`, `--base REF`, `--no-fetch`) and
  name the TXT to amend. Text after it says what to change. `--fresh` and `--pending` are refused.
- A missing TXT is an error (`no TXT to amend: <path>`), never a silent redraft. A `--base` amendment needs the
  `<branch>_<sha7>.txt` of that base.
- Files move between blocks with `branch_commit_msg.py move`, which carries each file's `file: what changed`
  bullet with it. `build` rejects any bullet whose file is not in its block.
- The replaced TXT is kept as `<name>.txt.bak`, one generation.

This repository enables its own plugins in `.claude/settings.json` from the published marketplace (the same
`t968rs/operator-straps` GitHub source as above), so sessions here run the cached copy from the pushed default
branch, not the checkout. Edits under `plugins/` take effect only after merge, version bump and
`claude plugin marketplace update operator-straps`; to exercise them before that, run
`claude --plugin-dir plugins/<name>` or add the checkout as a local marketplace (`claude plugin marketplace add ./`).

Installing from `/plugin` inside a session opens a dialog for each unset option instead; the CLI install takes
`--config KEY=VALUE`. `pytest-scope` options (see `plugins/pytest-scope/README.md`):

| Option | Default | Meaning |
|---|---|---|
| `python` | unset | Absolute path of the interpreter bare `pytest` runs under. Unset: no rewrite |
| `require_test_file` | `false` | Deny pytest calls with no test path or a directory path |

`harness` options (`claude plugin configure harness`):

| Option | Default | Meaning |
|---|---|---|
| `python` | unset | Interpreter for harness scripts and hooks. Needs `jsonschema`, `referencing`, `pydantic>=2` |
| `bash_discipline` | `true` | Deny Bash commands chained with `&&` or `;` |
| `inject_rules` | `true` | Add `rules/HARNESS_RULES.md` to the session context at start |

### Python

Every hook and script runs through `plugins/harness/scripts/hpy`, which picks the first interpreter that starts:
`HARNESS_PY` (project settings `env`), then the `python` option, then `python`, then `py -3`. It skips the Windows
Store `python3` stub. It does not probe for `jsonschema` / `referencing` / `pydantic`; the code that needs them
reports a missing module itself: the schema hook stands down with a one-line warning, and `pr-review` /
`pr-team` (whose driver models reviews in pydantic and validates them with jsonschema / referencing) check all
three before any subcommand runs and exit 1 with one `problem:` line naming the first one missing. Commit, summary and
worktree tooling need only the standard library.

## Configure a project

Create `.claude/harness.json` in the consuming repository. Every key is optional; objects merge key by key over
`plugins/harness/config/defaults.json`, arrays and scalars replace. The schema is
`plugins/harness/config/harness.schema.json`.

```json
{
  "base_branch": "dev",
  "integration_branches": ["dev", "main"],
  "exclusions": "reference/machine_generated_exclusions.json",
  "artifacts": {"reviews": "docs/PR_REVIEWS", "plans": "docs/PLANS", "summaries": "docs/PR_SUMMARIES"},
  "tests": {"roots": ["src/tests/"], "registry": "src/tests/registry.json", "registry_names": ["registry.json"]},
  "review": {
    "guard_suite": ["src/tests/guards/test_ci_workflows.py"],
    "structural_guard_prefixes": [".github/workflows/"],
    "domain_pointers": [{"prefix": "src/geo/", "pointer": "Geometry code never imports the GIS runtime at module level."}]
  },
  "commit_buckets": [
    {"bucket": "Runtime", "prefixes": ["src/pkg/"]},
    {"bucket": "Test", "prefixes": ["src/tests/"]}
  ],
  "auto_approve_python_c": true,
  "worktree_root": "~/worktrees/{repo}",
  "runlogs": {"dir": "logs/test_runs"},
  "todo": {"folder": "docs/RESEARCH/_TODO"}
}
```

TODO sync needs only `todo.folder`. With it set, the catalog is `<folder>/RepoToDo.json`, snapshots go to
`<folder>/Snapshots`, and `<folder>/RepoToDo.schema.json` and `<folder>/ResearchImplementationCatalog.json` are
used when they exist (a name set explicitly must exist); stubs are `_IMPL_TODO.md` files under `artifacts.research`. Set a key below only to depart
from that layout.

Finished items leave the catalog through `todo_sync.py retire ID [ID ...] [--dry-run]`: ids follow rank (rule T6),
so it renumbers the rest, rescores, recounts and rewrites moved ids in the research catalog and stubs, then lists
what the catalog cannot record by itself (issues to add as close candidates, trackers to revisit, and other files
naming a TODO id). `todo_sync.py split ID --spec PATH` replaces one item with the parts in a spec file (field
overrides laid over a copy of the item) and `todo_sync.py refresh` rescores and re-sorts after hand edits; both
renumber and rewrite ids the same way. `/harness:todo-edit --retire 1, 3 [--delete-retired] | --split 001 |
--refresh` runs any of the three through the `todo-editor` agent, which also writes the split parts,
close-candidate evidence and the prose that named a moved id. A retirement also updates the implementation
status in the affected stubs and research entries, and the reply names each stub's new state, the research
entries now fully resolved and the issues that can close. With `--delete-retired`, the agent also sets an entry
to `FULLY_IMPLEMENTED` and deletes its stub, but only after it ran a check for every deliverable in the stub;
a stub with any unproven deliverable is kept and listed.

| Key | Default | Used by |
|---|---|---|
| `base_branch` | `origin/HEAD`, else `main` | merge bases, `d-w`, `pr-review-watch` |
| `integration_branches` | base branch + `main` | `d-w` (fetch-and-cut targets) |
| `state_dir` | `.claude/state/harness` | Phase 5 sentinels, pr-team runtime, session-bookmark notes (`session-bookmark/notes.json`), parallel2 runs (`parallel2/`) (gitignore it) |
| `agent_usage_path` | `docs/_harness/pr_review_agent_usage.jsonl` | `pr-review-watch` (one usage row per defined-agent dispatch: model, tokens, runtime, fixer counts) |
| `artifacts.*` | `docs/PR_REVIEWS`, `docs/PLANS`, ... | review, plan, summary and commit-message output |
| `tests.*` | `tests/`, common test-file pattern | review bucketing, commit grouping |
| `tests.timings` | `null` | pr-review fixer briefs: a JSON report whose `tests` rows carry `file` (repo-relative POSIX, spelled exactly as the registry entry's `file`) and `duration` (seconds), summed per file; missing or unreadable means no runtime deferral. Stock pytest JSON reports key rows by nodeid with per-phase durations and do not match |
| `tests.fixer_test_seconds` | `null` (no runtime rule) | pr-review fixer briefs: a registered test summing over this many seconds in `tests.timings` is deferred (listed, not run; `closeout` prints it). With `tests.timings` missing or unusable, the ceiling is inactive and `waves` prints a `deferral:` notice |
| `tests.defer_flags` | `[]` | pr-review fixer briefs: dotted registry-entry paths (e.g. `properties.super_slow`); `true` at any of them defers the test |
| `review.*` | empty | Phase 1 guard suites, lens catalog, reviewer-brief rule pointers |
| `commit_buckets` | generic `src/`, `tests/`, `docs/` rules | `c-msg`, `branch-commit-msg` grouping |
| `exclusions` | `.claude/review_exclusions.json` | pr-review clean-tree checks and review capture ignore machine-generated files. At the default path the file is written on first use (`pr_review.py capture`, `pr_review.py config` when it prints `exclusions`, `phase4_branch_safety.py`, and `git_status_filter_excluded.py` run without a path argument) with patterns for `artifacts.reviews`, `artifacts.summaries`, `artifacts.scratch`, `artifacts.commit_messages`, `state_dir` and the files `matrix_path` and `agent_usage_path`; an existing file is never overwritten, and the folders the harness writes stay exempt in memory even when the file (seeded by an earlier version, or your own list) lacks their rows; a run with `--exclusions-fixture` takes its list as given. The folder rows cover the whole subtree (`fnmatch` `*` crosses `/`), so point `artifacts.scratch`, `artifacts.reviews` and `artifacts.summaries` at dedicated folders: a broad value such as `docs` hides every docs change from the clean-tree check and review capture. When `.claude/` is not writable (a read-only checkout, or a file named `.claude`) the seed is skipped and the first use fails with `Exclusions file not found`; create the file by hand or set `exclusions` to `null`. The clean-tree check runs `git status --porcelain --untracked-files=all`, so a seeded file in an untracked `.claude/` matches its own pattern. Name another file to keep your own list (it must exist), or set `null` to filter nothing |
| `auto_approve_python_c` | `false` | `approve_python_c` hook |
| `worktree_root` | `~/.config/superpowers/worktrees/{repo}` | `d-w`, `parallel2` |
| `runlogs.dir` | `null` (the skill then needs `--dir`) | `check-runlogs` (newest run log; every subfolder at any depth, dated archives included, is searched too) |
| `runlogs.name_pattern` | a name ending in `<YYYY-MM-DD>[_<HHMMSS>].txt` or `.log` | `check-runlogs` (named groups `date`, optional `time`) |
| `todo.folder` | `null` (feature off) | the one key a project sets to turn TODO sync on: the project-relative folder holding the TODO catalog and its companions. Every `todo` path below is relative to it (`..` allowed; a path that climbs above the project root fails config load) |
| `todo.catalog` | `RepoToDo.json` | `todo_sync.py`, its SessionStart hook, `todo-watch` (ranked TODO catalog JSON) |
| `todo.catalog_schema` | `RepoToDo.schema.json` (used when present, else the harness `catalogs/TodoCatalog.schema.json`) | rule T1 (validated under the schema's own draft); `null` always uses the harness copy; a name the project sets must exist (config load fails) |
| `todo.stub_name` | `_IMPL_TODO.md` (`null`: S1-S4 off) | stub file name under the research root (`artifacts.research`) |
| `todo.top_n` | `10` | `todo-watch` `/todo` table, `todo_sync.py render` |
| `todo.snapshots.dir` | `Snapshots` (`null`: T2 and `render` off) | rule T2, `todo_sync.py render` (creates the folder) |
| `todo.snapshots.name_pattern` | `TODO_Snapshot_<YYYY_MMDD>.md` | rule T2 (named group `date`; newest by date, else mtime) |
| `todo.research.catalog` | `ResearchImplementationCatalog.json` (used when present; absent or `null`: S rules, T3-T5 off) | research catalog JSON; a name the project sets must exist (config load fails) |
| `todo.research.anchor_pattern` | `catalog_entry: <path>#<id>` | rules S1, S4 (named group `id`) |
| `todo.research.ignore_folders` | `[]` | rule S6 (the folders holding the catalog and the snapshots are excluded automatically) |
| `todo.plans.pairs` | `true` | rules P1-P4 over `artifacts.plans` |
| `todo.gh.repo` | `null` (the `origin` remote) | issue fetch (Phase 3) |
| `todo.gh.max_age_hours` | `24` | rule G5 (Phase 3), `todo-watch` `/todo` summary age suffix |
| `todo.rules.disabled` | `[]` | `todo_sync.py check` skips these rule ids |
| `todo.rules.warn_counts` | `false` | warn findings count toward the drift number |
| `todo.inject_context` | `true` | `todo-watch` per-prompt `TODO_SYNC` line |
| `todo.notice.style` | `banner` | how `todo-watch` shows its session-start notice (the top items, then the sync status): `banner` (a band above the prompt, kept until Dismiss, its status line live) or `toast` (one toast at start, leaves on a timer) |
| `todo.notice.toast_seconds` | `60` (the engine's ceiling) | how long a `todo-watch` toast stays, above 0 and at most 60; unused with `banner` |
| `todo.notice.items` | `3` | how many top items the `todo-watch` notice lists, by rank, 1 to 10 |

`schemas_dir` (default `.claude/agent-schemas`) pins project copies of the review schemas; anything missing
there falls back to the plugin's `schemas/`.

Two layout rules hold everywhere:

- **Data goes to the project, code stays in the plugin.** No hook or script writes under the plugin directory
  (it is a versioned cache once installed); `tests/contract/test_root_separation.py` enforces it.
- **Phase 5 sentinels are per repository.** They live under the main checkout's `state_dir`, so a fixer arming
  one from a linked worktree gates the session in the main checkout, and the reverse.

## Develop

```
python -m pip install -r requirements-dev.txt
python -m pytest tests/<area>/test_<name>.py -q
python -m ruff check plugins tests
claude plugin validate plugins/<name>
claude plugin test plugins/<name>
```

To run a working copy instead of the installed release, point `CLAUDE_CODE_PLUGIN_DIRS` (user settings `env`)
at the plugin folders of a checkout.

| Path | Holds |
|---|---|
| `plugins/harness/lib/harness_lib/` | importable library: config, project roots, review/commit/summary engines, validation |
| `plugins/harness/{scripts,hooks}/` | entry points; each puts `../lib` on `sys.path` |
| `plugins/harness/skills/`, `agents/` | skill and agent markdown; agents dispatch as `harness:<name>` |
| `plugins/harness/{config,schemas,rules,reference}/` | defaults + config schema, review schemas, session rules, commit format |
| `plugins/<mod>/hooks/` | TypeScript mods, each with its own `*.test.ts` |
| `tests/` | pytest suite; `make_project` builds throwaway consuming projects |
| `docs/PROVENANCE.md` | where every file came from |

`tests/contract/` holds the guards that keep the plugins generic: no consumer literals, no writes under the
plugin root, every `hooks.json` command resolvable.
