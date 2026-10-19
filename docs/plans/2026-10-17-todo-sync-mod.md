# TODO sync: a `todo-watch` mod plus a harness `todo_sync` engine

Design report for a new mod-based plugin that (1) summarizes a project's local TODO catalog and flags JSON/Markdown
pairs that drifted apart, and (2) keeps GitHub issue state and the repo's TODO JSON reconciled. The motivating
consumer is a project whose research catalog, plan pairs and issue tracker have already drifted (evidence below).
Nothing here names that project in plugin code: every path is a `.claude/harness.json` key (`CLAUDE.md:8-10`).

## Summary

- **Split the work by what each runtime is good at.** Sync rules live once, in Python, in the harness library
  (`harness_lib/todo_sync/`) behind one script (`scripts/todo_sync.py`). The same code runs from a harness
  SessionStart hook, from the new mod on demand, from a skill, and from a consumer GitHub Action. The mod
  (`plugins/todo-watch/`) only reads, gates and displays: a toast, a per-prompt context line, and a `/todo`
  command.
- **The mod calls Python without knowing where the harness lives.** The harness SessionStart hook writes a
  runner pointer (its resolved interpreter and script path) into the project's `state_dir`; the mod runs that
  pointer through its process API after a write to a watched file. No pointer, no checks: the mod still shows
  the TODO summary it reads itself.
- **No network in the hot path.** GitHub issue state comes from one `gh issue list` call, made only by
  `todo_sync.py fetch` (skill or explicit run) and cached under `state_dir`. The mod shows the cache's age.
- **Issue sync is hybrid and never pushes.** Local reconcile proposes JSON edits (an agent saves them, the
  developer commits) and prints `gh` commands for issue-side changes. A consumer Action on `issues` events plus
  a weekly schedule runs the same check in read-only mode and updates one sticky comment and the job summary.
  A bot PR stays an opt-in later phase.
- **Field ownership is fixed:** GitHub owns open/closed, close reason and title; the repo JSON owns status,
  rank, priority, blast radius and LoE. A mismatch is reported, never silently overwritten.
- **The TODO catalog contract is the consumer's shipped `RepoToDo.schema.json`.** Harness `TodoCatalog` v0
  adopts that shape (rank-derived `TODO-NNN` ids, no terminal item status, `trackers[]` and
  `close_candidates[]`) instead of inventing a second one; the rules below key on its field names.
- **Retire the one-shot issue mapping file.** All 36 issue numbers it maps already appear in the research
  catalog's `issues[]`, and 10 of its 15 rows carry a status that no longer matches the catalog.
- **MVP = Phases 0-2** (schema and config, local rule engine, mod): about 5-6 days. GitHub reconcile and the
  Action follow as Phases 3-4.

## Ecosystem map

### Motivating drift (consumer checkout, read 2026-10-17)

The left column is the 2026-06-26 catalog this design was first motivated by; the right column is the same
probe after the 2026-10-17 catalog refresh (`catalog_version` 1.3), which fixed most of the folder drift by hand.
The drift that remains, and the drift that hand refreshes keep reintroducing, is what the rules target.

| Observation | Before refresh (2026-06-26 catalog) | After refresh (2026-10-17) | Source |
|---|---|---|---|
| Research catalog entries | 29 (19 `FULLY_IMPLEMENTED`, 7 `PARTIALLY_IMPLEMENTED`, 3 `NOT_APPLICABLE`) | 50 (24 `FULLY_IMPLEMENTED`, 17 `PARTIALLY_IMPLEMENTED`, 7 `NOT_APPLICABLE`, 1 `BLOCKED`, 1 `NOT_IMPLEMENTED`) | `docs/RESEARCH/ResearchImplementationCatalog.json:3-4` (`catalog_version`, `generated`) |
| Top-level `docs/RESEARCH/<dir>` folders covered by no entry (`research_folder` or stub parent) | 21 of 43 | 1 of 44: `TODO/`, the snapshot folder this feature writes (S6 excludes it, see below) | read-only probe over the catalog and the folder listing |
| Entry `test-categorization-arcpy` folder | `docs/RESEARCH/TestCategorization`, which does not exist | repointed to `docs/RESEARCH/CICD/TestCategorization` (exists) | same probe |
| Terminal entries (`FULLY_IMPLEMENTED` / `NOT_APPLICABLE`) that still list issue numbers | 10 | 14; 2 of those issues (#1471, #1481) are open, and `RepoToDo.json` lists both under `close_candidates` | same probe plus `gh issue list --state open` |
| Issue mapping file (dated 2026-05-15) rows whose status the catalog has since changed | 9 of 15 | 10 of 15 (for example `cicd-freshness-tree-sha`: `NOT_IMPLEMENTED` in the map, `FULLY_IMPLEMENTED` in the catalog, 5 issues) | `docs/RESEARCH/ResearchImplementationCatalog_GitHubIssues.json` (`generated`, `issues_by_catalog_entry`) |
| Issue #1329 | `OPEN` although its fix shipped | still `OPEN` (`stateReason: REOPENED`); recorded under `RepoToDo.json` `close_candidates` | `gh issue view 1329` |
| Open issues in the consumer repo | 50 | 50 | `gh issue list --state open` |
| Stub/catalog coherence | checked only at pytest time | unchanged | `scripts/__tests__/discipline/test_research_impl_catalog.py:60-109` |
| Repo TODO catalog | none | `docs/RESEARCH/RepoToDo.json` (89 items, 3 trackers, 11 close candidates), validated by a closed draft-07 `docs/RESEARCH/RepoToDo.schema.json`; written by a generator script run through Bash, not by Write/Edit | `RepoToDo.json` `counts` |

### Artifacts

| Artifact | Path (config key) | Writer | Reader | Source of truth for |
|---|---|---|---|---|
| Repo TODO catalog | `docs/RESEARCH/RepoToDo.json` (`todo.catalog`) | consumer generator script run through Bash (ranked merge), developer edits | todo_sync, mod, snapshot renderer | item status, rank, priority, blast radius, LoE, source refs, trackers, close candidates |
| TODO catalog schema | `docs/RESEARCH/RepoToDo.schema.json` (`todo.catalog_schema`) | developer | todo_sync (T1) | the catalog shape; harness `TodoCatalog` v0 adopts it |
| TODO snapshot | `docs/RESEARCH/TODO/TODO_Snapshot_<YYYY_MMDD>.md` (`todo.snapshots.dir`) | `todo_sync.py render` | humans | nothing (derived; dated top-N view) |
| Research catalog | `docs/RESEARCH/ResearchImplementationCatalog.json` (`todo.research.catalog`) | agent, developer | consumer pytest, todo_sync | research entry implementation status, files to touch |
| Research stubs | `docs/RESEARCH/<DOMAIN>/_IMPL_TODO.md` (`todo.research.stub_name`) | agent | consumer pytest, todo_sync | nothing beyond the catalog (stub mirrors topic/status/loe, `FBS/_IMPL_TODO.md:5-8`) |
| Action plans | `<artifacts.plans>/*_ActionPlan.json` | agent | harness schema hook, todo_sync | item status and evidence (schema README: "JSON is the source of truth") |
| PIP Markdown | `<artifacts.plans>/*_PIP.md` | agent | humans, todo_sync | nothing beyond the plan JSON (checkboxes mirror item status) |
| Issue mapping file | `docs/RESEARCH/ResearchImplementationCatalog_GitHubIssues.json` | one-shot, 2026-05-15 | nobody live | nothing (retire) |
| GitHub issues | remote | developer, bots | `gh`, Action | open/closed, close reason, title, labels |
| Issue cache | `<state_dir>/todo-sync/gh_issues.json` | `todo_sync.py fetch` | todo_sync, mod | nothing (mirror with `fetched_at`) |
| Sync report | `<state_dir>/todo-sync/report.json` | `todo_sync.py check` | mod | nothing (derived) |
| Runner pointer | `<state_dir>/todo-sync/runner.json` | harness SessionStart hook | mod | interpreter and script path for this session |

### Data flow

```
                  GitHub issues (state, state_reason, title, labels)
                       |                                   |
     todo_sync.py fetch (1 gh call, manual/skill)     issues events + weekly schedule
                       v                                   v
     <state_dir>/todo-sync/gh_issues.json         consumer Action: todo_sync.py check --gh-live
                       |                                   |  sticky comment + job summary (read-only)
                       |                                   v
  +--------------------+------------------------------------------------------------+
  |  RepoToDo.json  <--catalog_entry_ids-->  ResearchImplementationCatalog.json  <--anchor-->  _IMPL_TODO.md
  |       | render                                                                   |
  |       v                                                                          |
  |  TODO/TODO_Snapshot_<date>.md        <plans>/*_ActionPlan.json <--section--> *_PIP.md
  +--------------------+------------------------------------------------------------+
                       |  todo_sync.py check (rules S*, P*, T*, G*)
                       v
            <state_dir>/todo-sync/report.json  <---  runner.json (harness SessionStart hook)
                       |
     todo-watch mod: toast, TODO_SYNC context line, /todo command  (reads RepoToDo.json directly
                                                                     for the summary)
```

## Mod behavior

Every behavior fails open, as `pr-review-watch` does (`plugins/pr-review-watch/README.md:7-9`): an unreadable
file, a missing harness config, a refused process run or a malformed report degrades to "nothing to show".

| # | Rule the developer wants visible or enforced | Behavior | Platform surface (cited) |
|---|---|---|---|
| M1 | TODO state is visible when a session starts | One toast built from `counts.by_status` and `counts.needs_decision`: `TODO 89 · 68 open · 12 partial · 1 blocked · 12 need a decision · top: TODO-001 · 4 out of sync` (`gh 3d old` suffix when the issue cache is past `todo.gh.max_age_hours`). The drift part appears only once a `report.json` newer than the session start has landed; before that the toast is the catalog-only summary, never stale drift and never `sync checks unavailable` while the pointer lookup is still pending (ordering contract under M6) | `session.start` (`plugins/pr-review-watch/hooks/tracker.ts:477`); `$.ui.toast(text)` (`tracker.ts:231`) |
| M2 | The model sees drift without anyone pasting it | `TODO_SYNC drift=4 P1=1 S5=1 T2=1 G2=1` added to the prompt context, only when it changed since the line last attached; re-forced after `/clear`, resume or main compaction | `prompt.submit` with `context` (`plugins/pr-review-watch/hooks/phase5Scan.ts:62,70-96`); resets (`phase5Scan.ts:98-107`) |
| M3 | Changing a watched file re-checks within the turn | Tool filter `Bash`, `PowerShell`, `Write`, `Edit`, `MultiEdit`, `NotebookEdit` (the `git-status` set). For `Write` / `Edit` / `MultiEdit` / `NotebookEdit`, gate on `file_path` (`notebook_path` for `NotebookEdit`) under a watched path. For `Bash` / `PowerShell`, which carry no path (the consumer's `RepoToDo.json` is written by a generator script), stat the watched files after the call returns (`$.fs.stat`; the `$.fs.list` entry `mtimeMs` for watched directories) and gate on any mtime newer than `report.json`. Either gate schedules one check run (single-flight, coalesced) through the runner pointer; never delays the tool result | `tool.call` with a tool filter (`plugins/git-status/hooks/status.ts:37,358`); `file_path` on Write/Edit (`status.test.ts:523-528`); `$.process.run` (`tracker.ts:83`); `$.clock.after(0, ...)` (`status.ts:281-287`); pacing pattern (`status.ts:183-272`) |
| M3b | Edits made outside the session (an IDE save) are re-checked too | On `prompt.submit` and `turn.complete`, run the same watched-file mtime versus `report.json` comparison and schedule the same coalesced check run when it trips | `prompt.submit` / `turn.complete` handlers; `$.fs.stat` (`phase5Scan.ts:33`) |
| M4 | New drift is noticed, old drift does not nag | Toast again only when the drift count rises, plus once when it reaches zero (`TODO sync clean`) | `$.ui.toast`; state atoms (`plugins/git-status/hooks/status.ts:22-23`) |
| M5 | Full detail on demand | `/todo` prints the top-N table and each drift finding (rule id, file, one-line reason, suggested fix) | `$.command.register` on `session.start`, `command.run` handler (`plugins/session-bookmark/hooks/bookmark.ts:195-205`) |
| M6 | Summary is available without the harness engine | The mod reads `todo.catalog` itself for counts and top-N; the `$.fs.stat` mtime gate here only decides when to re-read `todo.catalog` and `report.json` (it does not schedule checks; M3 / M3b do). Ordering contract: the mod looks up `runner.json` lazily, at `session.start` and, if missing, once more on the first `prompt.submit` or `turn.complete` (single-flight); the first check is scheduled through `$.clock.after(0, ...)` as in M3. Only after that retry also finds no pointer does the mod show `sync checks unavailable` instead of a drift count | `$.fs.read` (`tracker.ts:76`); `$.fs.stat` mtime gate (`phase5Scan.ts:33`) |
| M7 | (Phase 5, opt-in) a plan pair the session itself touched may not be left out of sync | `classic.Stop` blocks once when this session wrote an ActionPlan or PIP and P1 fails for that pair; the next stop passes | `classic.Stop` (`tracker.ts:484-489`); block-once precedent (`plugins/pr-review-watch/README.md:44`) |

Surfaces deliberately left out of the MVP:

- **Band above the prompt.** `pr-review-watch` already renders `ui.render` `AbovePrompt` and returns its own
  element instead of `next(e)` when it has text (`plugins/pr-review-watch/hooks/band.tsx:14-30`). Two mods
  returning elements for the same slot need a verified composition rule first (open decision D3).
- **Status line.** `git-status` owns `$.ui.status` (`plugins/git-status/hooks/status.ts:158-164`); a second
  writer would overwrite it.
- **File-watch events.** No mod in this repository subscribes to a file-system watch; refresh triggers are
  `session.start`, `tool.call`, `turn.complete`, `prompt.submit` and timers (`$.clock.every`,
  `status.ts:293`). Edits made outside the session (an IDE save) are picked up by rule M3b's mtime comparison
  on the next `prompt.submit` or `turn.complete`, not instantly.

### Where the checks run: Python, shelled out to, not TypeScript

| Criterion | Rules in TypeScript inside the mod | Rules in Python (`harness_lib.todo_sync`), mod runs them |
|---|---|---|
| One implementation for session, pytest, CI and Action | No: a GitHub Action and the consumer's pytest cannot run a mod | Yes: the script is stdlib plus `jsonschema` (already allowed, `CLAUDE.md:56-57`) |
| Schema validation of `RepoToDo.json` | Hand-rolled; the mod cannot read harness `schemas/` (an installed mod sits in its own cache, `plugins/pr-review-watch/hooks/config.ts:1-5`) | `jsonschema` against `schema_path(...)`, project pin first |
| Test realism | Mod test sandbox cannot read repository files (`plugins/pr-review-watch/README.md:160`); every file is mocked | `make_project` builds real throwaway projects (`CLAUDE.md:34-36`) |
| Latency | In-process, near zero | One interpreter start per check run; bounded by gating on watched paths and coalescing |
| Locating code at runtime | Not needed | Solved by the runner pointer written by the harness SessionStart hook (`sys.executable` of the `hpy`-resolved interpreter plus the script's absolute path) |

**Recommendation: Python.** The rules are the product; the toast is a view. Keeping them in one Python module
makes the session, the consumer's pytest gate, and the Action agree by construction. The mod keeps only cheap,
display-side logic (summary counts, line formatting, change detection) in TypeScript.

## Sync rules catalog

Severity `error` counts toward the drift number; `warn` is listed by `/todo` but excluded from the count unless
`todo.rules.warn_counts` is true. Rule groups switch off when their config key is null.

| Id | Rule | Severity | Needs |
|---|---|---|---|
| S1 | Each catalog entry with `stub_path` has that file, and its anchor line resolves to the entry id (mirrors `test_research_impl_catalog.py:76-96`) | error | `todo.research.*` |
| S2 | Every stub file under the research root is referenced by some entry's `stub_path` (mirrors `:99-109`) | error | `todo.research.*` |
| S3 | Entries in a non-terminal status carry an existing stub (mirrors `:60-73`, statuses at `:31`) | error | `todo.research.*` |
| S4 | A stub's header `status:` / `loe:` lines equal the catalog entry's `status` / `loe` (new; the stub header carries both, `docs/RESEARCH/FBS/_IMPL_TODO.md:5-8`) | error | `todo.research.*` |
| S5 | Each entry's `research_folder` exists | error | `todo.research.*` |
| S6 | Each top-level research folder is covered by an entry or listed in `todo.research.ignore_folders`. Excluded automatically: the top-level folder holding `todo.snapshots.dir`, and the one holding `todo.catalog`, when either sits in a research subfolder (1 uncovered today, `TODO/`, which this exclusion covers) | warn | `todo.research.*` |
| P1 | ActionPlan item `COMPLETE` or `CLOSED_NO_ACTION` has every checkbox in its PIP section (`markdown_section` heading) checked; an item in `PENDING` / `IN_PROGRESS` has at least one unchecked box. Sample in sync: `1596_BugFixesBatch_ActionPlan.json:61-77` (`BFX-3` `IN_PROGRESS`) against `1596_BugFixesBatch_PIP.md:18-21` (one box open) | error | `artifacts.plans` |
| P2 | A `COMPLETE` item's `evidence`, or one of its `verification_references`, contains a commit SHA (7-40 hex) | error | `artifacts.plans` |
| P3 | Every `*_ActionPlan.json` has its `documentation` PIP on disk, and every `*_PIP.md` has a sibling plan with the same prefix | warn | `artifacts.plans` |
| P4 | `markdown_sync_status: in_sync` (`plugins/harness/schemas/ActionPlan.schema.json:63-80`) is not claimed while P1 fails for that plan | error | `artifacts.plans` |
| T1 | `RepoToDo.json` validates against `todo.catalog_schema` (consumer: `docs/RESEARCH/RepoToDo.schema.json`, draft-07); when the key is null, against the harness `TodoCatalog.schema.json` | error | `todo.catalog` |
| T2 | The newest snapshot's header hash equals the hash of the current top-N canonical rows (id, rank, status, title). A snapshot with no `<!-- todo-snapshot ... -->` header, or one that does not parse, is a warn `snapshot not produced by render (no header)` and the hash comparison is skipped | warn | `todo.snapshots.dir` |
| T3 | Every item's `catalog_entry_ids[]` id resolves in the research catalog; every `sources[]` ref of type `research_folder` or `impl_stub` exists on disk | error | `todo.catalog` + `todo.research.catalog` |
| T4 | Every non-terminal research entry (status not `FULLY_IMPLEMENTED` / `NOT_APPLICABLE`) is referenced by at least one item through `catalog_entry_ids`. Each of the entry's `issues[]` (numeric strings, coerced to int) that the issue cache records as `OPEN` must be covered: it appears in the `gh_issues` or `related_gh_issues` of an item referencing the entry, or equals such an item's `tracker`, or is a `trackers[].number`, one of a tracker's `children`, or a `close_candidates[].number`. An issue missing from the cache is reported as unknown, not as a violation. Closed issues are not checked: the catalog keeps them in `issues[]` as history (the literal subset rule, with this coverage set, would fire on 9 of 19 non-terminal entries today, every missing issue closed; counting only the referencing items' `gh_issues` and `related_gh_issues`, it would fire on 11 of 19) | warn | both catalogs + issue cache |
| T5 | An item (every item is non-terminal: `OPEN` / `PARTIAL` / `NEEDS_DECISION` / `BLOCKED`) does not reference only terminal research entries; with `catalog_entry_ids` empty the rule does not apply (0 findings today) | error | both catalogs |
| T6 | Ids and ranks: ids are unique and equal `TODO-<rank>` (zero-padded to 3), ranks run 1..n in item order | error | `todo.catalog` |
| T7 | `depends_on` and `unblocks` are mutual inverses and name existing ids | error | `todo.catalog` |
| T8 | Every non-null item `tracker` names a `trackers[].number`, and each tracker's `child_todo_ids` equals the set of items pointing at it | error | `todo.catalog` |
| T9 | `counts` tally the items: the keys recomputable from the file (`items`, `needs_decision`, `trackers`, `close_candidates`, `by_status`, `by_impact`, `by_loe`); `sources_absorbed` and `merged_items` describe the generator's inputs and are not checked | error | `todo.catalog` |
| T10 | Rank drift: each item's `priority.score` and `priority.components` equal the values recomputed from the catalog's own `ranking_method` data (`value = severity * impact_weights[impact]`, `cost = loe_points[size] * blast_factors[level]`, `score = round(value / sqrt(cost) * (1 + bonus), 4)`, bonus `unblock_bonus` when `unblocks` is non-empty), and `rank` equals the item's position under that score plus the recorded tie breakers (severity, LoE points, primary source type, ref, item, title). Added by D15 | error | `todo.catalog` |
| G1 | Every `gh_issues` number of an item is closed (`completed`) but the item remains: propose removing the item, or adding the issue to `close_candidates` | error | issue cache |
| G2 | A `close_candidates[]` issue, or an issue in a terminal research entry's `issues[]`, is still open: print the close command from its `recommended_action` (#1329 class) | error | issue cache |
| G3 | An issue closed as `not_planned` still backs an item through `gh_issues`: propose removing the item | warn | issue cache |
| G4 | Open issues linked from no item (`gh_issues`, `related_gh_issues`, `tracker`), no `trackers[]` entry or child, no `close_candidates[]` entry and no catalog entry (untriaged count) | warn | issue cache |
| G5 | Issue cache older than `todo.gh.max_age_hours` | warn | issue cache |

T6-T9 check the cross-record rules that `RepoToDo.schema.json` states in its description but cannot express;
today the consumer's generator is their only enforcement.

Snapshot header convention (written by `render`, read by T2):

```
<!-- todo-snapshot source=docs/RESEARCH/RepoToDo.json top=10 rows_sha256=<hex> rendered=2026-10-17 -->
```

Hashing the canonical top-N rows instead of the whole JSON keeps a summary- or evidence-only edit from marking
the snapshot stale.

Adoption note: the consumer's existing `docs/RESEARCH/TODO/TODO_Snapshot_2026_1017.md` predates this
convention (it opens with `# Repo TODO Snapshot: Top 10` and no header comment), so T2 reports it as unhashed
until one `todo_sync.py render` pass, or a hand-added header, replaces it.

## Issue <-> JSON sync: options compared

| Criterion | (a) Action in consumer repo | (b) Local reconcile via `gh` | (c) Hybrid (recommended) |
|---|---|---|---|
| Trigger | `issues` events (opened, edited, closed, reopened, labeled) + weekly `schedule` + `workflow_dispatch` | skill or explicit script run | (b) for edits; (a) for visibility |
| Freshness | minutes after an issue changes | as fresh as the last fetch | both |
| Who writes repo JSON | a bot PR (only way without pushing to `dev`) | agent saves, developer commits | agent saves, developer commits; bot PR opt-in later |
| Push policy | a direct push to `dev` would break "agents never push"; `bump_version.yaml:14-21` shows the repo already lets an Action push to `main`, which this design does not copy | none | none in the default mode |
| Visibility when nobody opens a session | yes (sticky comment, job summary) | no | yes |
| Offline / no `gh` auth | n/a | fails open, G rules report `unavailable` | same |
| Rate limits | `GITHUB_TOKEN` budget; one list call per run | one GraphQL-backed list call per fetch; 50 open issues today | trivial in both halves |
| Code to maintain | YAML + script checkout | script + skill | same script in both; YAML is thin |
| LoE | M | M | M + S |

**Recommendation: (c), staged.** Ship (b) first: it fixes the drift where edits happen and needs no CI change.
Add the Action in check-only mode next. Layout: the consumer is checked out in the default workspace, and
`operator-straps` in a subdirectory (`actions/checkout` with `repository:` set to operator-straps, `ref:` set
to the pinned tag and `path: .straps`). A `setup-python` step (3.11) and `pip install jsonschema` (which brings
in `referencing`) follow; the job then runs
`python .straps/plugins/harness/scripts/todo_sync.py check --project "$GITHUB_WORKSPACE" --gh-live --format markdown`,
writes the job summary and updates one sticky comment on a pinned tracking issue. The sticky pattern already exists in the
consumer (`.github/workflows/checks.yaml:276` marker, `:325-427` list/update/create). A bot PR
(`bot/todo-sync` -> `dev`) is Phase 5 and off by default.

### Source of truth per field

| Field | Owner | On mismatch |
|---|---|---|
| open / closed, `state_reason`, `closed_at` | GitHub | G1-G3 propose removing an item or adding a `close_candidates` entry (the catalog has no terminal item status); JSON is never rewritten by fetch |
| title, labels | GitHub | mirrored in the issue cache under `state_dir`. The only titles committed to `RepoToDo.json` are the required verbatim `trackers[].title` and `close_candidates[].title`; they are allowed mirrors, and a mismatch with GitHub is a warn finding |
| item `status`, `rank`, `priority`, `blast_radius`, `loe`, `summary`, `proposed_change` | repo JSON | never pushed to GitHub; reconcile may print a suggested issue comment |
| research entry `status`, `issues[]` | research catalog | T4/T5 report disagreements with TODO items; no automatic edit |

### Linking

- **Authoritative link: the JSON.** `RepoToDo.json` items carry `gh_issues: [int]` (the issues the item
  resolves; the G rules key on these), `related_gh_issues: [int]` (cross-referenced, not resolved; counted as
  linked by T4 and G4, never by G1 or G3) and `tracker`; the top level carries `trackers[]` and
  `close_candidates[]`. Catalog entries keep their `issues[]` as numeric strings
  (`ResearchImplementationCatalog.schema.json:165-172`); the engine coerces both sides to int before comparing.
- **No reverse marker in issue bodies.** Item ids are rank-derived display labels (`TODO-NNN` equals `rank`)
  and change with every regeneration, so an id written into an issue body would point at a different item
  after the next re-rank. The Action already checks out the consumer, so it maps an issue number to an item by
  reading `RepoToDo.json` and scanning `gh_issues`. Item ids are never written outside the JSON. If a marker is
  wanted later, it needs a stable per-item key first: the consumer generator already computes one
  (`build_repo_todo.py` builds `key_to_id` from it) but drops it from the output; a schema bump would add it as
  a required, unique field, and the marker would point at that key.

### Conflict policy

1. Fetch never edits tracked files; it only rewrites the cache.
2. `reconcile` prints proposals grouped as **JSON edits** (applied by the agent through Edit, so the
   developer sees a normal diff) and **GitHub commands** (`gh issue close N --reason completed --comment ...`,
   printed for the developer; open decision D7).
3. A field owned by one side is never overwritten from the other. Disagreement is a finding, not a merge.
4. When both sides changed since the last fetch, the finding is marked `contested` and listed first.

### The stale mapping file

Retire it. Every one of its 36 issue numbers already appears in the catalog's `issues[]` (probe), so it carries
no unique link data; its `status` and `title_prefix` columns are a 2026-05-15 snapshot with 10 of 15 rows out of
date. Consumer PR: delete the file. `RepoToDo.schema.json` is closed (`additionalProperties: false`) and has no
`conventions` field, so `title_convention_*` (`ResearchImplementationCatalog_GitHubIssues.json:5-6`), if still
wanted, moves either into the consumer's docs or into a new top-level field added by a consumer schema bump. No
rule checks the mapping file in the meantime.

## Architecture

### Files to add (operator-straps)

| Path | Purpose |
|---|---|
| `plugins/harness/lib/harness_lib/todo_sync/__init__.py` | public API: `check(cfg) -> Report`, `render_snapshot(cfg, date)`, `fetch_issues(cfg)`, `reconcile(cfg) -> Proposals` |
| `plugins/harness/lib/harness_lib/todo_sync/sources.py` | loaders for TODO catalog, research catalog, stubs, plan pairs, issue cache (frozen dataclasses) |
| `plugins/harness/lib/harness_lib/todo_sync/rules.py` | one function per rule id, each `(Sources) -> List[Finding]`, under 50 lines |
| `plugins/harness/lib/harness_lib/todo_sync/pip_sections.py` | PIP parser: heading -> section key, checkbox states |
| `plugins/harness/lib/harness_lib/todo_sync/gh.py` | one `gh issue list --state all --limit N --json number,state,stateReason,title,labels,closedAt,updatedAt` call |
| `plugins/harness/lib/harness_lib/todo_sync/report.py` | report model, JSON writer (atomic replace), Markdown formatter for the Action |
| `plugins/harness/scripts/todo_sync.py` | driver: `check [--gh-live] [--format json|markdown] [--out] [--rules <ids>] [--fail-on error]`, `render`, `fetch`, `reconcile`, `runner`; `--rules` limits the run to the comma-separated rule ids (for example `S1,S2,S3`); exit 0 when no finding meets the `--fail-on` threshold, 1 when at least one does, and always 0 without `--fail-on` (further levels such as `warn` only if the report grows severities beyond `error` / `warn`); `activate(load_config(project_root(...)))` once (`CLAUDE.md:18-20`) |
| `plugins/harness/hooks/todo_sync_session.py` | SessionStart: write `runner.json` and return (no `check` run in the hook, so session start pays only one interpreter start, as the existing `session_rules.py` entry with no `timeout` key does); stand down silently when `todo.catalog` is null; registered in `plugins/harness/hooks/hooks.json` (`CLAUDE.md:26-27`). The mod schedules the first check (M6 ordering contract) |
| `plugins/harness/skills/todo-sync/SKILL.md` | `harness:todo-sync`: fetch, check, reconcile; applies JSON proposals, prints `gh` commands, re-renders the snapshot |
| `plugins/harness/schemas/catalogs/TodoCatalog.schema.json` | the TODO catalog shape, adopted from the consumer's shipped `RepoToDo.schema.json` (standalone catalog, like `CICDActionAudit`; PascalCase, schemas README "Conventions"); used by T1 only when `todo.catalog_schema` is null |
| `plugins/harness/schemas/TodoSyncReport.schema.json` | report contract the mod reads |
| `plugins/todo-watch/.claude-plugin/plugin.json` | manifest with `"types": "./types/index.d.ts"` (`plugins/git-status/.claude-plugin/plugin.json:8`) |
| `plugins/todo-watch/hooks/hooks.json` | `{ "modules": ["./register.ts"] }` (`plugins/git-status/hooks/hooks.json:1`) |
| `plugins/todo-watch/hooks/register.ts` | wires `registerSummary`, `registerChecks`, `registerContext`, `registerCommand` (shape of `plugins/pr-review-watch/hooks/register.ts:7-11`) |
| `plugins/todo-watch/hooks/config.ts` | mirrored defaults + `readConfig(text)` (pattern `plugins/pr-review-watch/hooks/config.ts:7-56`) |
| `plugins/todo-watch/hooks/root.ts`, `watch.ts` | project resolution; active only when `.claude/harness.json` reads and `todo.catalog` is set (pattern `plugins/pr-review-watch/hooks/watch.ts:45-54`) |
| `plugins/todo-watch/hooks/summary.ts` | pure: TODO JSON text -> counts and top-N; toast and context-line formatting |
| `plugins/todo-watch/hooks/checks.ts` | runner pointer read, gated and coalesced `$.process.run`, report read with mtime gate |
| `plugins/todo-watch/hooks/command.ts` | `/todo` |
| `plugins/todo-watch/hooks/*.test.ts` | one test file per module |
| `plugins/todo-watch/types/index.d.ts` | `PluginState['todo-watch']` (pattern `plugins/pr-review-watch/types/index.d.ts:57-72`) |
| `plugins/todo-watch/{tsconfig.json,.gitignore,README.md}` | as the other mods (`.gitignore` ignores the generated `.claude-plugin/types/`) |

Edits: `.claude-plugin/marketplace.json` (new plugin row), `.github/workflows/ci.yml:109` (add
`plugins/todo-watch` to the mod-test loop), `README.md:8-16,20-29` (plugin table, install line), `CLAUDE.md:3-4`
(mod count) and `CLAUDE.md:14-17` (generalize the mirror rule from `pr-review-watch` to "any mod that reads
the key"), `plugins/harness/schemas/README.md` (two new schema sections, same PR per its update protocol).

### Config keys (`.claude/harness.json`, new `todo` object)

Each key lands in the four places `CLAUDE.md:14-17` names: `config/defaults.json`, `config/harness.schema.json`,
the dataclass and builder in `lib/harness_lib/config.py` (beside `Artifacts`, `config.py:28-37`), and the README
key table. Defaults are generic so `tests/contract/test_no_repo_literals.py` stays green; a project with no
`todo` object gets an inactive feature.

| Key | Default | Used by |
|---|---|---|
| `todo.catalog` | `null` (feature off) | everything; mod mirror |
| `todo.catalog_schema` | `null` (harness `TodoCatalog.schema.json`) | T1 |
| `todo.top_n` | `10` | summary, snapshot; mod mirror |
| `todo.snapshots.dir` | `null` | T2, `render` |
| `todo.snapshots.name_pattern` | `TODO_Snapshot_(?P<date>\d{4}_?\d{2}_?\d{2})\.md` | T2 (newest by `date`, else mtime) |
| `todo.research.catalog` | `null` | S*, T3-T5 |
| `todo.research.stub_name` | `null` | S1-S4 |
| `todo.research.anchor_pattern` | `^catalog_entry:\s*\S+#(?P<id>[a-z0-9-]+)\s*$` | S1, S4 |
| `todo.research.ignore_folders` | `[]` (the folders holding `todo.snapshots.dir` and `todo.catalog` are excluded automatically) | S6 |
| `todo.plans.pairs` | `true` | P* (paths from `artifacts.plans`) |
| `todo.gh.repo` | `null` (the `origin` remote) | `fetch` |
| `todo.gh.max_age_hours` | `24` | G5; mod toast suffix; mod mirror |
| `todo.rules.disabled` | `[]` | `check` |
| `todo.rules.warn_counts` | `false` | drift number |
| `todo.inject_context` | `true` | mod M2; mod mirror |

The consumer's block would set `catalog`, `catalog_schema` (`docs/RESEARCH/RepoToDo.schema.json`),
`snapshots.dir`, `research.catalog`, `research.stub_name` and `research.ignore_folders` (empty today: its only
uncovered folder, `TODO/`, is excluded automatically); `artifacts.research` already exists (`plugins/harness/config/defaults.json`) and
stays the research root.

### Mod state

`PluginState['todo-watch']`: `summary` (counts, top-N, catalog mtime), `report` (drift count by rule, report
mtime, `gh_fetched_at`), `lastContext`, `lastToastDrift`. Atoms as in `plugins/git-status/hooks/status.ts:22-23`.

### TODO catalog schema (v0 = the consumer's shipped shape)

Harness `TodoCatalog` v0 adopts the consumer's `docs/RESEARCH/RepoToDo.schema.json` as shipped (89 items as of
2026-10-17), keeping its field names and enums. It is closed (`additionalProperties: false`) at every level.

- **Top level** (required): `generated`, `generated_from` (`description`, `head_sha`, optional `branch`),
  `ranking_method`, `counts`, `items[]`, `trackers[]`, `close_candidates[]`; optional `$schema`. There is no
  `catalog_version`, `catalog_date` or `conventions` field.
- **Item** (required): `id`, `rank`, `title`, `kind`, `status`, `needs_decision`, `decision_question`,
  `tracker`, `sources`, `gh_issues`, `related_gh_issues`, `catalog_entry_ids`, `summary`, `proposed_change`,
  `files`, `blast_radius`, `loe`, `impact`, `severity`, `priority`, `depends_on`, `unblocks`, `why_ranked`;
  the only optional field is `code_snippet`. `decision_question` is a non-empty string when `needs_decision`
  is true and null otherwise. There is no `notes` field and no plan link.
  - `id` is `TODO-NNN` (`^TODO-[0-9]{3}$`) and equals `rank`; `rank` runs 1..n over all items. Both are
    rank-derived display labels that change on every regeneration, not stable keys (see Linking).
  - `status` is `OPEN` / `PARTIAL` / `NEEDS_DECISION` / `BLOCKED`. There is no terminal status: a finished
    item leaves the file, and an issue whose work landed (`LIKELY_RESOLVED`) or whose target is gone (`STALE`)
    moves to `close_candidates`.
  - `sources[]` is `{type: gh_issue | impl_stub | research_folder, ref, item, url}`, with `type` and `ref`
    always required, `url` required for `gh_issue` and `item` for the other two types; `gh_issues` and
    `related_gh_issues` are int arrays; `tracker` is an int or null.
  - `priority` is `{score, components{...}}`; `blast_radius` is `{level: S | M | L | XL, reasoning,
    consumers[]}`; `loe` is `{size: XS | S | M | L | XL, reasoning}`.
- **Tracker** (all required): `number`, `title` (verbatim GitHub title), `url`, `children`,
  `child_todo_ids`, `status_note`, `recommended_action`.
- **Close candidate** (all required): `number`, `title` (verbatim GitHub title), `url`, `current_state`
  (`LIKELY_RESOLVED` / `STALE`), `evidence`, `recommended_action`, `related_todo_ids`.

Cross-record rules the schema states but cannot express are checked by T6-T9. The one consumer-side change on
adoption is the dialect: the consumer schema is draft-07, while new harness schemas use draft 2020-12
(`plugins/harness/schemas/README.md:230`). Until the consumer migrates, T1 validates against the consumer's own
file through `todo.catalog_schema`, so the harness copy and the consumer file can differ only in dialect.

## Testing

| Layer | Test file | Proves |
|---|---|---|
| Rules | `tests/lib/test_todo_sync_rules.py` | each rule id red and green on a `make_project` tree (stubs, catalogs, plan pairs, snapshot, issue cache) |
| PIP parser | `tests/lib/test_todo_sync_pip_sections.py` | heading-to-section mapping, nested checkboxes, `[x]` / `[X]` |
| Driver | `tests/scripts/test_todo_sync.py` | subcommands, exit codes (`check` exits 1 on error findings only with `--fail-on error`), Markdown output |
| Hook | `tests/hooks/test_todo_sync_session.py` | runner pointer written under `state_dir`, nothing written under the plugin root (`CLAUDE.md:11-13`), silent when `todo.catalog` is null, no `check` run from the hook |
| Schemas | `tests/schemas/test_todo_catalog_schema.py` | fixtures validate; README section present |
| Mirror | `tests/mods/test_todo_watch_config_mirror.py` | mirrored defaults equal `defaults.json` (pattern `tests/mods/test_pr_review_watch_config_mirror.py:22-58`) |
| Report contract | `tests/mods/test_todo_watch_report_contract.py` | the keys `checks.ts` reads exist in `TodoSyncReport.schema.json`; names `checks.ts` literally so `tools/select_tests.py` selects it (`CLAUDE.md:48-50`) |
| Mod | `plugins/todo-watch/hooks/*.test.ts` via the mod test runner (`CLAUDE.md:37`) | toast at start shows no drift part until a report newer than the session start lands; toast only on rise and at zero; context line on change and after `/clear`; Write outside watched paths spawns nothing; Bash that leaves watched mtimes unchanged spawns nothing, Bash that moves one schedules a run; an IDE-side mtime change trips M3b on `prompt.submit`; process timeout fails open; pointer that appears after `session.start` is picked up on the first `prompt.submit` and the first check runs; no runner pointer after that retry shows `sync checks unavailable`; `C:\` and `/repo` paths (mock world pattern `plugins/pr-review-watch/hooks/band.test.tsx:19-45`) |
| Strict validation | CI `plugins` job (`.github/workflows/ci.yml:100-109`) | manifest and hooks module load |

Consumer side (its own PRs): the existing pytest gate stays; the Action is exercised by `workflow_dispatch`
before its triggers are enabled, under the consumer's CI change discipline.

## Phased rollout

| Phase | Scope | LoE |
|---|---|---|
| 0 Contract | `TodoCatalog.schema.json` v0 (adopted from the consumer's `RepoToDo.schema.json`), `TodoSyncReport.schema.json`, `todo.*` keys in the four places, snapshot header convention | S (0.5-1 day) |
| 1 Local engine | `harness_lib/todo_sync` rules S1-S6, P1-P4, T1-T9; `todo_sync.py check|render|runner`; SessionStart hook; Python tests | M (2-2.5 days) |
| 2 Mod (MVP done) | `plugins/todo-watch` M1-M6; mirror and report contract tests; marketplace, CI loop, README, CLAUDE.md edits; version 0.1.0 | M (2 days) |
| 3 Issue reconcile, local | `gh.py`, `fetch`, `reconcile`, rules G1-G5, `harness:todo-sync` skill; consumer adopts `todo` config and retires the mapping file | M (2 days) |
| 4 Consumer Action | `todo_sync.yaml` in the consumer: `issues` + weekly schedule + dispatch; pinned checkout of this repo at `path: .straps`; `setup-python` 3.11 + `pip install jsonschema`; job summary + sticky comment; `permissions: issues: write, contents: read` | S-M (1-1.5 days) |
| 5 Optional | M7 Stop guard; band once composition with `pr-review-watch` is verified; bot PR mode; scheduled auto-fetch at session start when the cache is stale | S each (0.5-1 day) |

MVP (Phases 0-2): about 5-6 days. Full plan through Phase 4: about 8-9 days.

## Open decisions

| # | Decision | Recommended default |
|---|---|---|
| D1 | Plugin name | `todo-watch` (parallels `pr-review-watch`); the engine, script and skill are `todo_sync` / `todo-sync` |
| D2 | Where rules run | Python in the harness library; the mod is a view (reasons above) |
| D3 | Band above the prompt | Off; toast, context line and `/todo` only, until two mods sharing `AbovePrompt` is verified |
| D4 | Model-facing context line | On (`todo.inject_context: true`); attached only on change |
| D5 | Stop guard for plan pairs | Off in the MVP; Phase 5 opt-in, block once |
| D6 | When to fetch issues | Explicit (`harness:todo-sync` or `todo_sync.py fetch`); auto-fetch at session start only after the cache rules soak |
| D7 | Who changes GitHub issues | Developer runs the printed `gh` commands; agents edit only repo JSON |
| D8 | Action write mode | Read-only: job summary + one sticky comment; bot PR off |
| D9 | Issue mapping file | Retire (delete in a consumer PR; no rule for it) |
| D10 | Snapshot staleness basis | Hash of canonical top-N rows, not the whole file |
| D11 | Uncovered research folders (S6) | Warn, with an ignore list |
| D12 | Status ownership between the two catalogs | Research catalog owns implementation status of research entries; TODO catalog owns ranking and its own workflow status; T5 flags contradictions |
| D13 | Schema home | Harness `schemas/catalogs/TodoCatalog.schema.json`, adopted from the consumer's shipped shape; a project that keeps its schema beside the data (the consumer's `docs/RESEARCH/RepoToDo.schema.json`) names it in `todo.catalog_schema`, which T1 prefers |
| D14 | Consumer pytest gate | Keep `test_research_impl_catalog.py` as is; harness S1-S3 mirror it rather than replace it |
| D15 | Source of truth after bootstrap; where ranking lives | Settled in the kickoff (2026-10-19): the ranked catalog is the source of truth once it exists; the bootstrap generator's per-item override tables are not ported. The deterministic recompute of `priority.score` and `rank` is rule T10 inside `check` (the smaller change: no new subcommand, and drift shows up in the same report and toast). Discovering items stays agent work |

### Departures recorded during the Phase 0-2 build

| Where | Design said | Built | Why |
|---|---|---|---|
| `catalogs/TodoCatalog.schema.json` source refs | harness copy differs from the consumer schema only in dialect (D13) | also generalizes the `impl_stub` / `research_folder` `ref` patterns from a fixed `docs/RESEARCH/...` prefix to any repo-relative path, and the top-level description to name rules T6-T10 | the research root (`artifacts.research`) and stub name (`todo.research.stub_name`) are configurable, so a fixed prefix in the shared schema would reject other layouts; T3 checks that the refs exist |
| `todo_sync.py` | no alternate config path | global `--config PATH` reads a harness.json other than `<project>/.claude/harness.json` | acceptance runs against a scratch config without editing the consumer's real one |
| `todo_sync.py check` stdout | `--format json\|markdown` | adds `summary` (the default: one line `todo-sync drift=<n> error=<e> warn=<w> rules=<k> elapsed_ms=<ms>`); the report file is always written (`--out` overrides the path) | the mod ignores stdout and reads `report.json`; a person running the script wants one line |
| P2 SHA source | `evidence` only | `evidence` or any `verification_references` string (developer decision, 2026-10-19) | the ActionPlan schema names `verification_references` the home of durable proof; on the consumer 24 of 54 P2 hits had the SHA there. A 7-40 hex token cannot tell a tree SHA from a commit SHA |
| `--fail-on` levels | `error` (further levels only if severities grow) | `error` and `warn` (`warn`: any warn or error trips exit 1) (developer decision, 2026-10-19) | T2 stays a warn by design, so seeded snapshot drift needs a warn threshold to fail a run |
| Acceptance 1 (0 findings on the consumer today) | 0 findings | 53 errors, all real plan drift: P2 30 (COMPLETE items in 11 older plans with no SHA anywhere), P1 21 and P4 2 (plans 1149, 9043); S, T1, T3-T10 at 0 | developer decision, 2026-10-19: the engine stays strict and the consumer fixes the data in its own PR, or sets `todo.rules.disabled` meanwhile |
| P1 heading match | heading text starts with the `markdown_section` key | also strips leading markup and a literal `#`, drops a leading `Task` word, and accepts the key as a slug prefix at a hyphen boundary | the harness `PLANS_PIP_Template.md` prescribes `### Task {ID} — {Title}`, the ActionPlan schema's example key is `#task-fcc-1`, and real PIPs use `### #bblk-1 — ...`; the strict match produced 85 false `section not found` warns |
| P1 scope | every item | items with a null `markdown_section`, or whose section holds no checkbox, are out of scope; a non-null key naming no heading is a `warn` | old plans predate the section convention |
| S1 / S3 overlap | both report a missing stub | S3 reports a missing stub for non-terminal entries; S1 only for terminal ones | one file, one finding |
| Unreadable inputs | not specified | the first rule needing an unreadable file reports one error, later rules skip with `<label> unreadable`; a rule that raises on malformed input yields `rule could not run: ...` | no traceback reaches the report |
| T2 | hash compare | also stale when the header's `top` differs from `todo.top_n` | a changed `top_n` changes the canonical rows |
| T4 | catalog links plus the open-issue coverage | catalog-link half only in Phase 1 | the issue cache arrives in Phase 3 |
| T10 order | rank equals the position under score plus tie breakers | ordered by the recomputed score, so a score edit also reports the rank shift it causes; an item that cannot be scored skips the rank comparison | a rank check against stored scores would hide the shift |
| Runner pointer | `sys.executable` plus script path | `{schema_version, python, script, project, report, written_at}`; `project` and `report` with forward slashes | the mod needs the project argument and the report path without re-reading `harness.json` |
| todo-watch root | git top level of the session cwd, as pr-review-watch | nearest folder at or above the cwd holding `.claude/harness.json`, then `CLAUDE_PROJECT_DIR`; no `git` process | "a Write outside watched paths spawns no process" and "inactive spawns nothing" hold literally; a nested `harness.json` below the checkout root would win where harness_lib picks git's top level |
| todo-watch start toast | toast carries the drift part once a fresh report landed | the start toast is always catalog-only; the first fresh report with drift toasts once as a rise (M4); the `out of sync` / `sync clean` / `gh Nd old` suffixes show on the `/todo` summary line | one toast at start, never stale drift |
| todo-watch pacing | single-flight with an owed rerun, git-status gap | single-flight with an owed rerun, no minimum gap; the report is re-read after the mod's own run even when its mtime did not tick | a coarse file clock may not move between two runs |
| todo-watch rule order | examples list `G2` last | context line and toasts sort rule ids by letter, then number | deterministic order |
| todo-watch modules | separate `registerSummary` / `registerContext` | both live in `checks.ts`; one `session.start` hook in `register.ts` | the plugin validator refuses a second unmatched `session.start` hook |

## Risks

| Risk | Mitigation |
|---|---|
| Toast fatigue | Toast at session start, on drift rise and at zero; everything else behind `/todo` |
| Interpreter start latency on Windows after each watched write | Gate on watched paths in TypeScript before spawning; single-flight with an owed rerun (`status.ts:252-272` pattern); `$.clock.after(0, ...)` so the tool result is not delayed; time cap on the run |
| Runner pointer goes stale after a plugin update (versioned cache path) | Rewritten every SessionStart; the mod checks `$.fs.exists` on the script before running it |
| Duplicate S1-S3 logic (consumer pytest and harness) diverges | Accepted for the MVP: the consumer test keeps its own literal regex pinning the catalog path (D14; `test_research_impl_catalog.py:32-34`), stricter than the harness default `\S+#`. Optionally the consumer sets `todo.research.anchor_pattern` to the same literal. A later consumer PR can have its test call `todo_sync.py check --rules S1,S2,S3 --fail-on error` so only one copy of the logic remains |
| Two catalogs both claim a status | D12 ownership split plus T5 |
| Harness `TodoCatalog.schema.json` v0 and the consumer's shipped closed `RepoToDo.schema.json` diverge | The harness schema follows the shipped consumer schema, and T1 validates against the consumer's file through `todo.catalog_schema` (D13) |
| Item ids renumber on every regeneration | Ids never leave the JSON; no issue-body marker (Linking) |
| Engine type declarations are generated, not checked in (`plugins/pr-review-watch/.gitignore:1-2`) | Event field names used here are pinned by existing tests (`status.test.ts:523-528` for `file_path`, `tracker.test.ts:95` for `ui.toast`) |
| `gh` missing or unauthenticated | `fetch` fails open; G rules report `unavailable`; the Action uses `GITHUB_TOKEN` |
| Sticky comment noise on busy issue days | Update in place behind one marker; skip the write when the rendered body is unchanged |
| Consumer literals leaking into plugin defaults | All consumer values live in its `harness.json`; `tests/contract/test_no_repo_literals.py` guards the plugin tree |
| Mod read limit | Reads are small (`RepoToDo.json` ~301 KB, research catalog ~158 KB, report a few KB) against the 4 MiB limit noted in `plugins/pr-review-watch/README.md:105` |
