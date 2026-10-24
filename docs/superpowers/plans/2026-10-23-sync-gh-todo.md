# sync-gh-todo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `harness:sync-gh-todo` finds open GitHub issues that no TODO catalog record mentions and adds one drafted item per issue, reusing the `todo_sync.py` renumbering path.

**Architecture:** `todo_sync.py` gains `untracked` (lists open issues absent from the catalog, with each issue's body, comments and the text of any linked PR review, written to a JSON file under `state_dir`) and `add --spec` (inserts drafted items, then rescores, re-sorts, renumbers and recounts through the existing `_renumber` / `_apply` path). A new skill runs `untracked` and dispatches `harness:todo-editor` with a new `sync` operation; the agent drafts the item fields from the issue and review text, runs `add`, then `render` and `check`.

**Tech Stack:** Python 3.11 standard library plus the existing `jsonschema`; `gh` CLI; pytest.

**Spec:** none written. The design was agreed in the conversation of 2026-10-23 and is under Design Decisions below. It implements rule G4 and the Phase 3 `fetch` idea of `docs/plans/2026-10-17-todo-sync-mod.md`, as an on-demand subcommand instead of a cache.

## Design Decisions

- One catalog item per open issue, even when a linked review holds many findings; the findings go into the item's `summary` and `proposed_change`. The developer splits later with `todo-edit --split`.
- A thin issue gets a best-guess item (severity, impact, size, blast radius chosen from the text); `needs_decision` is set when the guess is shaky. An issue that links a PR review gets the review's real text (review body and inline comments), not the link.
- An item whose only source is a `gh_issue` needs no `_IMPL_TODO.md` stub and no research folder (T3 checks only stubs and folders an item names; T4 checks the other direction).
- `gh` access lives in a new `harness_lib/todo_sync/gh.py` and is not extracted from `scripts/pr_review.py`: its review helpers sit in a 2000-line script whose tests patch `pr_review.run_gh`, so a move would break working code for no gain here. The few lines of review fetching are duplicated on purpose.
- Non-goals: a G4 rule inside `check`, an issue cache, closing or labelling issues, following links outside the issue's own repository.

## Global Constraints

- Python 3.11: `Optional[X]` / `Union[X, Y]`, never `X | Y`. No first or second person in comments or docstrings. Functions under 50 lines. Runtime dependencies: standard library, `jsonschema`, `referencing`, `pydantic>=2` only.
- Plugins stay generic: no consuming-project name, path or issue number in anything under `plugins/` (`tests/contract/test_no_repo_literals.py`). Tests use the `example/widgets` repo and small issue numbers.
- Data goes to the project: new files are written only under `<state_dir>/todo-sync/` (`cfg.path(cfg.state_dir)`); `plugin_root()` is read-only (`tests/contract/test_root_separation.py`).
- No new config key: `todo.gh.repo` already exists (`null` means the `origin` remote).
- Drivers activate, library code reads: the driver calls `activate(load_config(...))` once; library modules read `active()` inside functions only.
- Lint: `python -m ruff check --no-cache plugins tests tools` (line length 110). Tests: name files, never a directory.
- Bump `version` in `plugins/harness/.claude-plugin/plugin.json` from `0.24.0` to `0.25.0` (new skill).
- Claude saves files; the developer commits and pushes. Each task ends with a checkpoint that lists the changed files, never a commit.

## Review Focus

- An issue recorded only in a research entry's `issues` (strings such as `"102"`) or as a tracker child counts as tracked and is not listed. Pinned in Task 1.
- A review link into another repository is never fetched; a dismissed review and a review with a blank body and no inline comments contribute nothing. Pinned in Task 2.
- `gh` missing, unauthenticated or failing exits 2 with one `problem:` line and writes nothing. Pinned in Tasks 1 and 4.
- Running `add` twice for the same issue, or naming one issue twice in a spec, is refused rather than creating a second item. Pinned in Task 3.
- A spec item that sets a computed field (`id`, `rank`, `priority`, `depends_on`, `unblocks`, `sources`) is refused with the field named. Pinned in Task 3.

## File Structure

- Create `plugins/harness/lib/harness_lib/todo_sync/gh.py`: the `gh` subprocess seam (`run_gh`, `api_object`, `api_list`).
- Create `plugins/harness/lib/harness_lib/todo_sync/reviews.py`: review links in text, review fetching with a character budget.
- Create `plugins/harness/lib/harness_lib/todo_sync/issues.py`: open-issue listing, tracked-number coverage, the `untracked` rows and their file.
- Modify `plugins/harness/lib/harness_lib/todo_sync/reshape.py`: `add_items`, `apply_add`, `summary_lines` branch, `read_spec` key parameter.
- Modify `plugins/harness/scripts/todo_sync.py`: `untracked` and `add` subcommands and docstring.
- Modify `plugins/harness/agents/todo-editor.md`: the `sync` operation.
- Create `plugins/harness/skills/sync-gh-todo/SKILL.md`.
- Modify `README.md`, `plugins/harness/.claude-plugin/plugin.json`.
- Create `plugins/harness/lib/harness_lib/todo_sync/scaffold.py`: the starter catalog and `init_catalog` behind `todo_sync.py init` (Task 6).
- Create `docs/TODO/RepoToDo.json` and its first snapshot, and add the `todo` key to `.claude/harness.json` (Task 6).
- Tests: `tests/lib/test_todo_sync_issues.py`, `tests/lib/test_todo_sync_reviews.py`, `tests/lib/test_todo_sync_add.py`, `tests/scripts/test_todo_sync_intake.py`, `tests/skills/test_sync_gh_todo_skill_contract.py`, `tests/lib/test_todo_sync_scaffold.py`.

---

### Task 1: Open issues and tracked-number coverage

**Files:**
- Create: `plugins/harness/lib/harness_lib/todo_sync/gh.py`, `plugins/harness/lib/harness_lib/todo_sync/issues.py`
- Test: `tests/lib/test_todo_sync_issues.py`

**Interfaces:**
- Produces (`gh.py`): `run_gh(cwd: Path, args: Sequence[str]) -> str` returns stdout; raises `TodoSyncError("gh <label> failed: <stderr>")` on a non-zero exit, where `<label>` is `api <last arg>` for a `gh api` call and the first two args otherwise (`gh issue list failed: ...`), and `TodoSyncError("gh could not run (<exc>); install gh or check PATH")` on `OSError`. `api_object(cwd: Path, path: str) -> Dict[str, Any]` runs `gh api <path>`. `api_list(cwd: Path, path: str) -> List[Dict[str, Any]]` runs `gh api --paginate --jq .[] <path>` and parses one JSON object per output line. Every caller reaches them as `gh.run_gh(...)` through the module so tests can patch `harness_lib.todo_sync.gh.run_gh`.
- Produces (`issues.py`): `LIST_LIMIT = 1000`; `untracked_path(cfg: HarnessConfig) -> Path` (`<state_dir>/todo-sync/untracked.json`); `catalog_issue_numbers(catalog: Dict[str, Any]) -> Set[int]` (every `items[].gh_issues`, `related_gh_issues`, `sources[type=gh_issue].ref` as `#N`, `trackers[].number` and `children`, `close_candidates[].number`); `tracked_numbers(src: Sources) -> Set[int]` (that, plus the research catalog's `entries[].issues` entries, each coerced with `int()` when it is a digit string or int); `open_issues(cfg: HarnessConfig) -> List[Dict[str, Any]]`; `find_untracked(cfg: HarnessConfig) -> List[Dict[str, Any]]`; `write_untracked(cfg: HarnessConfig, rows: List[Dict[str, Any]]) -> Path`.
- Row shape of `find_untracked`: `{"number": int, "title": str, "url": str, "labels": [str], "body": str, "comments": [{"author": str, "body": str}], "reviews": [], "reviews_truncated": False, "review_errors": []}`; a null body becomes `""`. `review_errors` holds one `<link>: <reason>` line per linked review that could not be read (Task 2).

- [ ] **Step 1: Write the failing tests** in `tests/lib/test_todo_sync_issues.py`. Build the project with `_todo_helpers.build(make_project, files, cfg)`; a `_fake_gh(monkeypatch, issues)` helper patches `gh.run_gh` to return `json.dumps(issues)` for an args list starting `issue list` and records every args list.
  - `test_tracked_numbers_cover_every_record`: the shared fixture gives `tracked_numbers(Sources(cfg)) == {11, 101, 102, 103}`.
  - `test_research_entry_issues_count_as_tracked`: set `RESEARCH_REL` entry `issues` to `["205", 206]`; both numbers are in the result.
  - `test_find_untracked_lists_only_unrecorded_issues`: open issues 11, 101, 102, 103, 200 (200 with `labels: [{"name": "bug"}]`, `body: null`, one comment `{"author": {"login": "ann"}, "body": "hi"}`) give exactly one row whose `labels == ["bug"]`, `body == ""`, `comments == [{"author": "ann", "body": "hi"}]`.
  - `test_open_issues_ask_for_every_open_issue`: the recorded args hold `--state open`, `--limit 1000` and, with `todo.gh.repo` set to `example/widgets`, `--repo example/widgets`; without it no `--repo`.
  - `test_run_gh_reports_failure_and_missing_gh`: patch `gh.subprocess.run` to return a `CompletedProcess` with return code 1 and stderr `auth` (message contains `gh issue list failed` and `auth`), then to raise `OSError` (message contains `gh could not run`); both raise `TodoSyncError`.
  - `test_write_untracked_lands_under_state_dir`: the returned path equals `untracked_path(cfg)`, sits under `.claude/state/harness/todo-sync/`, and loads back to the rows.
- [ ] **Step 2: Run to verify failure.** `python -m pytest tests/lib/test_todo_sync_issues.py -q` fails with `ModuleNotFoundError` for `harness_lib.todo_sync.gh`.
- [ ] **Step 3: Implement `gh.py`** to the Interfaces above (`subprocess.run` with `encoding="utf-8"`, `errors="replace"`, `capture_output=True`, `text=True`).
- [ ] **Step 4: Implement `issues.py`.** `open_issues` runs `gh.run_gh(cfg.project_root, ["issue", "list", "--state", "open", "--limit", str(LIST_LIMIT), "--json", "number,title,url,labels,body,comments", *(["--repo", repo] if repo else [])])` and flattens each issue; it raises `TodoSyncError("untracked needs todo.folder")` when `cfg.todo.enabled` is false. `find_untracked` keeps the issues whose number is not in `tracked_numbers(Sources(cfg))`, sorted by number. `write_untracked` uses `write_atomic` from `report.py` with `json.dumps(rows, indent=2, ensure_ascii=False)`.
- [ ] **Step 5: Run to verify pass.** `python -m pytest tests/lib/test_todo_sync_issues.py -q` passes.
- [ ] **Step 6: Checkpoint.** `python -m ruff check --no-cache plugins/harness/lib/harness_lib/todo_sync tests/lib/test_todo_sync_issues.py` is clean; list the changed files.

---

### Task 2: Linked review text

**Files:**
- Create: `plugins/harness/lib/harness_lib/todo_sync/reviews.py`
- Modify: `plugins/harness/lib/harness_lib/todo_sync/issues.py` (`find_untracked` fills `reviews` and `reviews_truncated`)
- Test: `tests/lib/test_todo_sync_reviews.py`

**Interfaces:**
- Consumes: `gh.api_object`, `gh.api_list` (Task 1); the issue row shape.
- Produces: `REVIEW_CHARS = 20000`; `@dataclass(frozen=True) ReviewLink(pr: int, review_id: Optional[int])`; `review_links(texts: Iterable[str], slug: str) -> List[ReviewLink]` (matches `https://github.com/<slug>/pull/<N>` with an optional `#pullrequestreview-<id>`; any other repository is ignored; first occurrence order, deduplicated; `slug` compared case-insensitively); `slug_of(issue_url: str) -> str` (`owner/repo` of `https://github.com/<o>/<r>/issues/<N>`, else `""`); `fetch_reviews(cwd: Path, slug: str, links: Sequence[ReviewLink], budget: int = REVIEW_CHARS) -> Tuple[List[Dict[str, Any]], bool, List[str]]` returning the review dicts, a truncated flag and one `<link>: <reason>` line per link whose fetch raised `TodoSyncError` or `ValueError` (a deleted review, an issue number); such a link is skipped, not fatal.
- Review dict: `{"source": "https://github.com/<slug>/pull/<N>#pullrequestreview-<id>", "state": str, "author": str, "body": str, "comments": [{"path": str, "line": Optional[int], "author": str, "body": str}]}`. Endpoints: `repos/<slug>/pulls/<N>/reviews/<id>` and `.../comments` for a named review, `repos/<slug>/pulls/<N>/reviews` for a bare PR. A DISMISSED review, and a review with a blank body and no non-blank inline comment, are left out. The budget counts the characters of every body; once spent, later reviews are dropped and the flag is True.

- [ ] **Step 1: Write the failing tests** in `tests/lib/test_todo_sync_reviews.py`; a `_fake_api(monkeypatch, objects, lists)` helper patches `gh.api_object` and `gh.api_list` to answer by path.
  - `test_review_links_keep_only_this_repository`: text holding `https://github.com/example/widgets/pull/7#pullrequestreview-55`, the bare `.../pull/8`, a repeat of the first, and `https://github.com/other/thing/pull/9` gives `[ReviewLink(7, 55), ReviewLink(8, None)]`.
  - `test_slug_of_reads_owner_and_repo`: `https://github.com/example/widgets/issues/3` gives `example/widgets`; `https://example.com/x` gives `""`.
  - `test_named_review_returns_body_and_inline_comments`: the object `{"state": "COMMENTED", "body": "Overall notes", "user": {"login": "ann"}}` with one inline comment `{"path": "src/a.py", "line": 12, "body": "Rename this", "user": {"login": "ann"}}` gives one review dict with those values and `source` ending `#pullrequestreview-55`.
  - `test_bare_pr_reads_every_review_and_skips_dismissed_and_blank`: three reviews on PR 8 (one `DISMISSED`, one blank without comments, one with a body) give one review dict.
  - `test_budget_truncates_and_flags`: two reviews of 30 characters each with `budget=40` give one review and `True`.
  - `test_find_untracked_attaches_linked_reviews`: an untracked issue whose body holds a review URL (and whose repo comes from its `url`) gets `reviews` of length 1 and `reviews_truncated is False`; an untracked issue with no link keeps `reviews == []`.
- [ ] **Step 2: Run to verify failure.** `python -m pytest tests/lib/test_todo_sync_reviews.py -q` fails on the missing module.
- [ ] **Step 3: Implement `reviews.py`** to the Interfaces above; `api_list` results are dicts, `user.login` gives the author, an inline comment's line is `line` else `original_line` else `None`.
- [ ] **Step 4: Wire `find_untracked`** so each row's links come from `review_links([body, *comment bodies], slug_of(url))` and its `reviews`, `reviews_truncated`, `review_errors` from `fetch_reviews(cfg.project_root, slug, links)`.
- [ ] **Step 5: Run to verify pass.** `python -m pytest tests/lib/test_todo_sync_reviews.py tests/lib/test_todo_sync_issues.py -q` passes.
- [ ] **Step 6: Checkpoint.** Ruff on the changed files is clean; list them.

---

### Task 3: Add items and renumber

**Files:**
- Modify: `plugins/harness/lib/harness_lib/todo_sync/reshape.py`
- Test: `tests/lib/test_todo_sync_add.py`

**Interfaces:**
- Consumes: `catalog_issue_numbers` (Task 1); the private `_renumber`, `_apply`, `_method` of `reshape.py`; `recount`, `normalize_id` from `retire.py`.
- Produces: `Reshape` gains `added: Tuple[Tuple[str, int], ...] = ()` (new id, issue number); `read_spec(path: Path, key: str = "parts") -> List[Any]` (error text names `key`; default unchanged); `ADD_REQUIRED = ("issue", "url", "title", "kind", "summary", "proposed_change", "blast_radius", "loe", "impact", "severity", "why_ranked")`; `ADD_OPTIONAL = ("needs_decision", "decision_question", "status", "files", "related_gh_issues", "code_snippet")`; `add_items(catalog: Dict[str, Any], specs: Sequence[Any]) -> Reshape`; `apply_add(cfg: HarnessConfig, spec: Path, dry_run: bool = False) -> ReshapeResult`.
- `add_items` builds each item with keys in the schema's order: `id` (temporary `add-new-<n>`), `rank`, `title`, `kind`, `status` (default `OPEN`), `needs_decision` (default `False`), `decision_question` (default `None`), `tracker: None`, `sources: [{"type": "gh_issue", "ref": "#<issue>", "url": url}]`, `gh_issues: [issue]`, `related_gh_issues` (default `[]`), `catalog_entry_ids: []`, `summary`, `proposed_change`, `code_snippet` (only when given), `files` (default `[]`), `blast_radius`, `loe`, `impact`, `severity`, `priority` (computed), `depends_on: []`, `unblocks: []`, `why_ranked`. It then runs `_renumber`, raises the new ids into `Reshape.added`, removes them from `rescored`, drops them from `renames`, and adds `len(specs)` to `counts.sources_absorbed.gh_issue` when that count is an integer. Refusals raise `TodoSyncError`: a spec item that is not an object; a missing required key; a key outside required and optional (`item <n> sets <key>; add computes it or does not take it`); an `issue` that is not a positive integer; an `issue` already in `catalog_issue_numbers(catalog)`; one `issue` named twice (`issue #<n> appears twice in the spec`); an empty spec; an item `_renumber` cannot score (`cannot score ...`).
- `summary_lines` for `out.added` prints `added TODO-007 (#9), TODO-009 (#12); <n> item(s) now`, then the rescored, renumbered, rewrote and `next:` lines as for a split.

- [ ] **Step 1: Write the failing tests** in `tests/lib/test_todo_sync_add.py` using `copy.deepcopy(MIN_CATALOG)` from `_todo_helpers`. `_spec(issue=9, **over)` returns a full valid spec item (copy `TODO-001`'s `kind`, `blast_radius` S, `loe` S, `impact` `silent_wrong_output`, `severity` 5, so it outranks TODO-001).
  - `test_new_item_outranks_and_shifts_the_rest`: `add_items(catalog, [_spec()])` gives `added == (("TODO-001", 9),)`, `renames == {"TODO-001": "TODO-002", "TODO-002": "TODO-003", "TODO-003": "TODO-004"}`, item `TODO-001` has `gh_issues == [9]` and `sources[0]["ref"] == "#9"`, the old first item (now `TODO-002`) has `unblocks == ["TODO-003"]`.
  - `test_low_value_item_lands_last`: severity 1, `impact` `docs_tooling`, `loe` XL, blast `XL` gives `added == (("TODO-004", 9),)` and `renames == {}`.
  - `test_counts_follow_the_new_items`: `counts.items == 5`, `counts.sources_absorbed["gh_issue"] == 3` after adding issues 9 and 12.
  - `test_priority_is_computed_not_taken`: the new item's `priority.score` equals `score(item, method_from(catalog["ranking_method"]))[0]`.
  - parametrized `test_refusals` with a message fragment each: missing `why_ranked`; extra key `rank`; extra key `depends_on`; `issue` 11 (already an item); `issue` 101 (a tracker); `issue` 103 (a tracker child); `issue` 102 (a close candidate); the same issue twice; an empty list; `impact: "nonsense"` (cannot score).
  - `test_apply_add_writes_the_catalog_and_dry_run_does_not`: with `build(make_project, todo_files())`, write a spec file `{"items": [_spec()]}`; `apply_add(cfg, path, dry_run=True)` leaves the catalog file bytes unchanged; `apply_add(cfg, path)` leaves it holding 4 items with ids `TODO-001`..`TODO-004` in rank order, and `check(cfg, rules=["T6", "T7", "T9", "T10"])` reports no findings.
  - `test_read_spec_names_its_key`: a file without an `items` list raises `TodoSyncError` containing `'items'`.
- [ ] **Step 2: Run to verify failure.** `python -m pytest tests/lib/test_todo_sync_add.py -q` fails with `ImportError` for `add_items`.
- [ ] **Step 3: Implement** the Interfaces above in `reshape.py`; update its module docstring to name add. `apply_add` reuses `_apply(cfg, "add", lambda data: add_items(data, specs), dry_run)`; companion edits already take `renames` without the temporary ids.
- [ ] **Step 4: Run to verify pass.** `python -m pytest tests/lib/test_todo_sync_add.py tests/lib/test_todo_sync_reshape.py -q` passes (the second file proves split and refresh are unchanged).
- [ ] **Step 5: Checkpoint.** Ruff on the changed files is clean; list them.

---

### Task 4: Driver subcommands

**Files:**
- Modify: `plugins/harness/scripts/todo_sync.py`
- Test: `tests/scripts/test_todo_sync_intake.py`

**Interfaces:**
- Consumes: `find_untracked`, `write_untracked` (Tasks 1-2); `apply_add`, `reshape.summary_lines` (Task 3).
- Produces: `todo_sync.py untracked` prints `untracked: none` (exit 0, no file written) or `untracked: <n> open issue(s) in no catalog record`, one `#<number> <title>` line per issue and `wrote <path>`. `todo_sync.py add --spec PATH [--dry-run]` prints the `summary_lines` of the result. Both exit 2 with one `problem:` line on a `TodoSyncError`; the module docstring documents both.

- [ ] **Step 1: Write the failing tests** in `tests/scripts/test_todo_sync_intake.py`. Load the driver with `importlib.util.spec_from_file_location` and call `module.main([...])` in-process, with `gh.run_gh` patched and `capsys`; build projects with `_todo_helpers.build`.
  - `test_untracked_prints_the_issues_and_writes_the_file`: open issues 11 and 200 print `untracked: 1 open issue(s) in no catalog record`, a `#200 <title>` line and `wrote ...untracked.json`; the file holds one row.
  - `test_untracked_none_writes_nothing`: only tracked issues print `untracked: none`; the file does not exist.
  - `test_untracked_exits_2_when_gh_fails`: a patched `run_gh` raising `TodoSyncError("gh issue list failed: auth")` gives exit 2, stderr `problem: gh issue list failed: auth`, no file.
  - `test_untracked_needs_the_todo_folder`: a project without `todo.folder` gives exit 2 and `problem: untracked needs todo.folder`.
  - `test_add_dry_run_then_real`: a spec file with one valid item; `--dry-run` prints `added TODO-001 (#9)` and leaves the catalog unchanged; the real run changes it and prints `next: todo_sync.py render, then todo_sync.py check`.
  - `test_add_refusal_exits_2`: a spec item naming tracked issue 11 gives exit 2 and a `problem:` line containing `#11`.
- [ ] **Step 2: Run to verify failure.** `python -m pytest tests/scripts/test_todo_sync_intake.py -q` fails (invalid subcommand).
- [ ] **Step 3: Implement** the two subparsers (`add` takes `--spec` required and `--dry-run`) and their `_dispatch` branches, each in a function of its own under 50 lines; extend the module docstring.
- [ ] **Step 4: Run to verify pass.** `python -m pytest tests/scripts/test_todo_sync_intake.py tests/scripts/test_todo_sync.py -q` passes.
- [ ] **Step 5: Checkpoint.** Ruff on the changed files is clean; list them.

---

### Task 5: Agent operation, skill, docs and version

**Files:**
- Modify: `plugins/harness/agents/todo-editor.md`, `README.md`, `plugins/harness/.claude-plugin/plugin.json`
- Create: `plugins/harness/skills/sync-gh-todo/SKILL.md`
- Test: `tests/skills/test_sync_gh_todo_skill_contract.py`

**Interfaces:**
- Consumes: the `untracked` and `add` subcommands (Task 4).
- Produces: skill `harness:sync-gh-todo` with no arguments. Step 1 runs `sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/todo_sync.py" untracked`; `untracked: none` ends the run with that line; a `problem:` line is relayed and ends it. Step 2 dispatches one `Agent` call, `subagent_type="harness:todo-editor"`, `model="opus"`, with this prompt:

  ```
  Operation: sync
  Issues: #<n>, #<n>
  Project root: <absolute project root>
  Guidance: none
  ```

  Step 3 relays the reply and states that the edits are saved, not committed.
- The agent gains a `## sync` section: read `<state_dir>/todo-sync/untracked.json` in slices (never whole; Grep for `"number": <n>` and Read around it); for each listed issue draft one item, never merge issues; take severity, impact and `loe` from the catalog's own `ranking_method` scales; set `needs_decision` with a `decision_question` when the guess is shaky; when `reviews` is non-empty, write each review finding into `summary` as `<path>:<line>: <point>` (the review's own words, not its URL) and list the paths in `files`; verify claims with Grep and cite `path:line`, or write `unverified` in the summary; write `{"items": [...]}` to `<state_dir>/todo-sync/add.json` using only the keys `add` accepts; run `add --spec ... --dry-run`, then `add --spec ...`, then the existing **finish** steps. The `Operation` and reply blocks name `sync`; `Added:` carries `TODO-NNN for #N`, with ` (needs decision)` appended for an item with `needs_decision: true`, and the skill's report names those items. Stop conditions gain `untracked: none`, and the one spec fix before stopping on a `problem:` line applies to sync as well as split. The agent drafts from the `untracked.json` the skill's Step 1 wrote and reruns `untracked` only when that file is missing.

- [ ] **Step 1: Write the failing tests** in `tests/skills/test_sync_gh_todo_skill_contract.py`, in the style of `tests/skills/test_amend_commit_msg_skill_contract.py` (load `todo_sync._parser()` through `importlib`).
  - `test_skill_frontmatter_names_the_skill_and_no_arguments`: `name: sync-gh-todo`; no `argument-hint` line.
  - `test_skill_command_lines_parse`: every line of the skill starting with the launcher and `todo_sync.py` parses with the driver's parser (`args.command == "untracked"`).
  - `test_skill_dispatches_the_todo_editor_on_opus`: the body holds `harness:todo-editor` and `opus`, and its fenced prompt block has the lines starting `Operation:`, `Issues:`, `Project root:`, `Guidance:`.
  - `test_agent_documents_the_sync_operation`: the agent's `## sync` section mentions `untracked.json`, `add --spec`, `--dry-run`, `needs_decision`, `one item per issue` and `unverified`; the agent description names `sync`.
  - `test_agent_reply_block_is_unchanged`: the field names of the `## Reply` block still equal `("Operation", "Result", "Renumbered", "Prose fixed", "Added", "Stubs", "Resolved", "Close", "Open", "Check")` (keeps `tests/skills/test_todo_edit_skill_contract.py` valid).
- [ ] **Step 2: Run to verify failure.** `python -m pytest tests/skills/test_sync_gh_todo_skill_contract.py -q` fails on the missing skill.
- [ ] **Step 3: Write `SKILL.md` and the agent's `sync` section** to the Interfaces above, in the house style of `skills/todo-edit/SKILL.md` and `agents/todo-editor.md` (description lines start `Use when`; state what to do and why, no comparisons with other skills).
- [ ] **Step 4: Update `README.md`.** After the paragraph that ends `a stub with any unproven deliverable is kept and listed.` add a paragraph: `todo_sync.py untracked` lists open issues no catalog record mentions (item, tracker, child, close candidate, research entry) and writes their text, with linked PR review text, to `<state_dir>/todo-sync/untracked.json`; `todo_sync.py add --spec PATH [--dry-run]` inserts one drafted item per issue and renumbers; `/harness:sync-gh-todo` runs both through the `todo-editor` agent. Mirror wherever the README lists `harness:amend-commit-msg` among the skills (`Grep` for it first). Set `version` in `plugin.json` to `0.25.0`.
- [ ] **Step 5: Run to verify pass.** `python -m pytest tests/skills/test_sync_gh_todo_skill_contract.py tests/skills/test_todo_edit_skill_contract.py -q` passes.
- [ ] **Step 6: Whole-change checks, files named.** `python -m pytest tests/lib/test_todo_sync_issues.py tests/lib/test_todo_sync_reviews.py tests/lib/test_todo_sync_add.py tests/scripts/test_todo_sync_intake.py tests/scripts/test_todo_sync.py tests/lib/test_todo_sync_reshape.py tests/lib/test_todo_sync_retire.py tests/skills/test_sync_gh_todo_skill_contract.py tests/skills/test_todo_edit_skill_contract.py tests/contract/test_no_repo_literals.py tests/contract/test_root_separation.py tests/contract/test_hooks_json_paths.py -q` passes; `python -m ruff check --no-cache plugins tests tools` reports at most the pre-existing `plugins/harness/scripts/pr_review.py:23` E501; `claude plugin validate --strict plugins/harness` passes.
- [ ] **Step 7: Live check against a scratch project.** In a throwaway directory with `.claude/harness.json` (`{"todo": {"folder": "docs/_TODO"}}`) and a small valid catalog, run `todo_sync.py untracked` with the real `gh` against any repository the developer names, and report the output. Skipped, with the reason stated, when `gh` is not authenticated.
- [ ] **Step 8: Checkpoint.** List every changed file; the developer commits.

---

### Task 6: Starter catalog (`todo_sync.py init`)

Added after execution (commit 5fecd6e) so this repository could run `sync` against its own issues.

**Files:**
- Create: `plugins/harness/lib/harness_lib/todo_sync/scaffold.py`, `docs/TODO/RepoToDo.json` and its first snapshot
- Modify: `plugins/harness/scripts/todo_sync.py` (`init` subcommand and docstring), `.claude/harness.json` (`todo` key)
- Test: `tests/lib/test_todo_sync_scaffold.py`

**Interfaces:**
- Produces (`scaffold.py`): `STARTER_RANKING` (the default `ranking_method` tables); `starter_catalog(head_sha: str, today: dt.date) -> Dict[str, Any]` (an empty, schema-valid catalog whose `generated_from` records `head_sha`); `@dataclass(frozen=True) InitResult(catalog: Path, snapshot: Optional[Path])`; `init_catalog(cfg: HarnessConfig, today: Optional[dt.date] = None) -> InitResult`.
- `init_catalog` raises `TodoSyncError` without writing anything when `todo.folder` is unset, when the catalog already exists (`init never overwrites a catalog`), when `git rev-parse HEAD` gives no commit, or when the first snapshot name does not match `todo.snapshots.name_pattern`. Otherwise it writes the catalog and, when `todo.snapshots.dir` is set, renders the first snapshot.
- `todo_sync.py init` prints one `created <path>` line per written file; a `TodoSyncError` prints `problem: <reason>` and exits 2.

- [ ] **Tests** in `tests/lib/test_todo_sync_scaffold.py`: init writes a catalog and snapshot that `check` passes clean; the starter catalog is empty and records the commit; `head_sha` is the current commit; init refuses to overwrite a catalog, needs `todo.folder` and needs a commit; without a snapshots folder it writes the catalog only; a snapshot name outside `name_pattern` is refused before any file is written.

---

## Self-review notes

- Spec coverage: untracked detection (Tasks 1, 4), review text instead of links (Task 2), best-guess item for thin issues (Task 5 agent section), one item per issue (Tasks 3, 5), no stub step (Design Decisions; Task 3 builds `gh_issue` sources only), reuse of the refresh path (Task 3), skill (Task 5), version bump (Task 5).
- Types: `ReviewLink`, `Reshape.added`, `find_untracked` row shape and `read_spec(path, key)` are named once and used with the same signatures in later tasks.
- Proportion: five tasks, signatures and assertions only; bodies are left to the implementer.
