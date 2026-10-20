# TODO Notice Layout and Snapshot Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The todo-watch notice shows the next N TODO items first with a small colored sync line below, stays
until dismissed, and the TODO snapshot links each item id to its `_IMPL_TODO.md`.

**Architecture:** A new `todo.notice.items` key (and a `banner` default style) flows through the harness config
and the todo-watch mirror. todo-watch keeps one live `NoticeView` (item lines plus a toned status), recomputed on
every catalog, report or checks-status change; session start shows it once (band until Dismiss, or one toast),
and sync changes never show, re-show or post anything. On the harness side a stub resolver maps each catalog
item to its `_IMPL_TODO.md` files, and the snapshot table links the id.

**Tech Stack:** Python 3.11 (`harness_lib`, pytest), TypeScript mod (`claude-code` engine API, `claude plugin test`).

**Spec:** `docs/superpowers/specs/2026-10-20-todo-notice-and-snapshot-links-design.md`

## Global Constraints

- Python 3.11; `Optional[X]` / `Union[X, Y]`, never `X | Y`; functions under 50 lines; no first or second person
  in comments or docstrings.
- Plugins stay generic: no consuming-project names or paths under `plugins/` (`tests/contract/test_no_repo_literals.py`).
- A new config key touches defaults, schema, dataclass + builder, README key table, and the todo-watch mirror.
- Tests run by file, never a directory. Lint: `python -m ruff check --no-cache plugins tests tools`.
- Versions: `harness` 0.10.0 -> 0.11.0 (Task 1); `todo-watch` 0.3.0 -> 0.4.0 (Task 3).
- `/todo` (M5) and the `TODO_SYNC` context line (M2) do not change: `formatSummary`, `SyncSuffix`,
  `syncSegments`, `CLEAN_TEXT` and the `CATALOG_LINE` test constant stay.
- The agent saves files; the developer commits. Each task ends with a checkpoint listing its files.

## Review Focus

1. **A catalog shorter than `todo.notice.items`, or empty/unreadable:** fewer item lines, or only the status
   line; an empty view (no items, no status) shows nothing at all, never an empty toast or a bare Dismiss.
   Pinned in Tasks 2 and 3.
2. **A title with newlines, tabs or 200 characters:** one line, clipped with an ellipsis. Pinned in Task 2.
3. **Sync changes while the band shows, and after Dismiss:** while shown, one live copy with the newest status
   (including `sync checks unavailable` after a failed runner retry); after Dismiss nothing comes back; toast
   mode never posts after start. Pinned in Task 3.
4. **A stub path with spaces, parentheses or `|`, a title with `[`/`]`/`|`:** the link still resolves and the
   table keeps its columns. Pinned in Task 4.
5. **A project with `todo.stub_name: null`, or a missing research root, or a stale `impl_stub` ref:** `render`
   still works; links come only from routes that apply, and never point at a missing file. Pinned in Task 4.

---

### Task 1: The `todo.notice.items` key and the banner default

**Files:**
- Modify: `plugins/harness/config/defaults.json` (`todo.notice`), `plugins/harness/config/harness.schema.json`
  (`todo.notice` and its description at line 155, `todo.top_n` description at line 110),
  `plugins/harness/lib/harness_lib/config.py` (`TodoConfig` line 117, builder line 360), `README.md` (rows at
  212-213 plus a new row), `plugins/todo-watch/hooks/config.ts`, `plugins/harness/.claude-plugin/plugin.json` (0.11.0)
- Test: `tests/lib/test_config.py`, `tests/mods/test_todo_watch_config_mirror.py`,
  `plugins/todo-watch/hooks/config.test.ts`

**Interfaces:**
- Produces: `TodoConfig.notice_items: int` (Python); `DEFAULT_NOTICE_ITEMS = 3`, `MAX_NOTICE_ITEMS = 10`,
  `DEFAULT_NOTICE_STYLE = 'banner'`, `TodoWatchConfig.noticeItems: number` (TS).

- [ ] **Step 1: Write the failing tests**

`tests/lib/test_config.py`: the defaults assertion (line 184) becomes
`assert (todo.notice_style, todo.notice_toast_seconds, todo.notice_items) == ("banner", 60.0, 3)`;
`test_todo_notice_toast_seconds_override` (line 233) passes `{"notice": {"style": "toast", "toast_seconds": 12.5}}`;
new `test_todo_notice_items_override` loads `{"todo": {"notice": {"items": 5}}}` and asserts `notice_items == 5`;
`{"notice": {"items": 0}}`, `{"notice": {"items": 11}}` and `{"notice": {"items": 2.5}}` join the
`test_todo_rejects_bad_values` list.

`tests/mods/test_todo_watch_config_mirror.py`: map `("todo", "notice", "items")` to
`("DEFAULT_NOTICE_ITEMS", ts_number)` and expect `"DEFAULT_NOTICE_ITEMS": cfg.todo.notice_items`.

`config.test.ts`: `readConfig('{}')` gives `noticeStyle: 'banner'` and `noticeItems: 3`;
`{"todo":{"notice":{"items":5}}}` gives 5; `0`, `11`, `2.5` and `"5"` each give 3.

- [ ] **Step 2: Run** `python -m pytest tests/lib/test_config.py tests/mods/test_todo_watch_config_mirror.py -q`
  and `claude plugin test plugins/todo-watch`. Expected: failures naming `notice_items`, `noticeItems`,
  `DEFAULT_NOTICE_ITEMS` or the `banner` default.

- [ ] **Step 3: Implement.** `defaults.json`: `"notice": {"style": "banner", "toast_seconds": 60, "items": 3}`.
  Schema: `"items": {"type": "integer", "minimum": 1, "maximum": 10, "description": "How many top TODO items,
  by rank, the todo-watch notice lists."}`; the `notice` description names the new layout; the `top_n`
  description drops "The start notice shows only the rank-1 title". `config.py`: `notice_items: int`, built as
  `int(t["notice"]["items"])`. README: the `todo.notice.style` row names `banner` as default; new row
  ``| `todo.notice.items` | `3` | how many top items the `todo-watch` notice lists, by rank, 1 to 10 |``.
  `config.ts`: the constants, an `itemsOr(v, fallback)` accepting an integer in 1..`MAX_NOTICE_ITEMS`, and
  `noticeItems` in `readConfig`.

- [ ] **Step 4: Run the Step 2 commands.** Expected: all pass.

- [ ] **Step 5: Checkpoint.**

---

### Task 2: The notice view (pure text, `summary.ts`)

**Files:**
- Modify: `plugins/todo-watch/hooks/summary.ts`, `plugins/todo-watch/types/index.d.ts`
- Test: `plugins/todo-watch/hooks/summary.test.ts`

**Interfaces:**
- Consumes: `TodoSummary` (`top: TodoRow[]`), `SyncReport` (`drift`), `SyncStatus` (`'pending' | 'found' | 'unavailable'`).
- Produces (exported from `summary.ts`; types in `types/index.d.ts`):
  - `type NoticeTone = 'ok' | 'warn' | 'dim'`
  - `type NoticeView = { items: string[]; status: { text: string; tone: NoticeTone } | null }`
  - `formatNotice(summary: TodoSummary | null, report: Pick<SyncReport, 'drift'> | null, status: SyncStatus, count: number): NoticeView`
  - `noticeText(view: NoticeView): string`, `isEmptyView(view: NoticeView): boolean`
  - `NOTICE_TOAST_SEP = '\n'`, `IN_SYNC_TEXT = '✓ in sync'`, `MAX_NOTICE_TITLE = 80`.
  - `parseCatalog(text, rows, mtimeMs)`: unchanged signature; callers pass how many rows to keep (Task 3).

- [ ] **Step 1: Write the failing tests** in `summary.test.ts`, with `rows(n)` building `TodoRow`s ranked 1..n
  titled `Item <k>`:
  - `items by rank, at most count`: `formatNotice(summary({ top: rows(5) }), { drift: 0 }, 'found', 3).items`
    equals `['1  Item 1', '2  Item 2', '3  Item 3']`.
  - `a short or missing catalog gives fewer lines`: `rows(2)` with count 3 gives 2 items;
    `formatNotice(null, { drift: 0 }, 'found', 3)` equals `{ items: [], status: { text: '✓ in sync', tone: 'ok' } }`.
  - `a messy title folds to one clipped line`: title `` `a\n\tb ${'x'.repeat(200)}` `` gives one line starting
    `1  a b x`, with no `\n`/`\t`, ending in `…`, at most `3 + 80` characters.
  - `status by report and checks state`: drift 5 -> `{ text: '5 out of sync', tone: 'warn' }`; no report and
    `found` -> `null`; no report and `unavailable` -> `{ text: 'sync checks unavailable', tone: 'dim' }`.
  - `toast text joins items then status`: `noticeText` of two items and `✓ in sync` is `'1  A\n2  B\n✓ in sync'`.
  - `ten long items still end with the whole status`: ten 80-character items plus `12 out of sync` ends with
    `'\n12 out of sync'`.
  - `an empty view`: `isEmptyView(formatNotice(null, null, 'found', 3))` is true; with a status, false.

- [ ] **Step 2: Run** `claude plugin test plugins/todo-watch`. Expected: FAIL, `formatNotice` not exported.

- [ ] **Step 3: Implement** in `summary.ts`. Item line `` `${rank}  ${title}` ``, title whitespace-folded and
  clipped to `MAX_NOTICE_TITLE`. Status: a report wins (0 -> ok `IN_SYNC_TEXT`, N -> warn
  `` `${N} out of sync` ``); without one, `unavailable` -> dim `UNAVAILABLE_TEXT`, else `null`. `noticeText`
  joins the item lines and the status text with `NOTICE_TOAST_SEP`, with no further clip. This task only adds;
  the removals land in Task 3 with their last callers.

- [ ] **Step 4: Run** `claude plugin test plugins/todo-watch`. Expected: the new tests pass, the old ones still pass.

- [ ] **Step 5: Checkpoint.**

---

### Task 3: Band and toast wiring (`band.tsx`, `checks.ts`)

**Files:**
- Modify: `plugins/todo-watch/hooks/band.tsx`, `plugins/todo-watch/hooks/checks.ts`,
  `plugins/todo-watch/hooks/summary.ts`, `plugins/todo-watch/hooks/testWorld.ts`,
  `plugins/todo-watch/types/index.d.ts`, `plugins/todo-watch/README.md` (M1, M4, M7 rows and lines 105 and 117),
  `plugins/todo-watch/.claude-plugin/plugin.json` (0.4.0)
- Test: `plugins/todo-watch/hooks/band.test.tsx`, `plugins/todo-watch/hooks/checks.test.ts`,
  `plugins/todo-watch/hooks/summary.test.ts`, `plugins/todo-watch/hooks/watch.test.ts`

**Interfaces:**
- Consumes: Task 2's `NoticeView`, `formatNotice`, `noticeText`, `isEmptyView`; Task 1's `noticeItems`.
- Produces (from `band.tsx`): `setNoticeView($, view: NoticeView): Promise<void>`, `showBand($): Promise<void>`
  (writes even when already shown), `hideBand($): Promise<void>`, `resetBand($): Promise<void>`. Atoms
  `notice` (`NoticeView | null`) and `isNoticeShown` (`boolean`) replace `notices: string[]` in `types/index.d.ts`.
- Removes: `driftToast`, `CLEAN_TOAST`, `MAX_TOAST` (`summary.ts`) and their tests (`summary.test.ts:128-150`);
  `MAX_NOTICES`, `postNotice`, `clearNotices` (`band.tsx`); the `lastToastDrift` atom (`checks.ts:213`) and its
  `types/index.d.ts` entry. `formatSummary` and `CATALOG_LINE` stay (`/todo`).

- [ ] **Step 1: Write the failing tests.**
  - `testWorld.ts`: add `START_NOTICE` (the `noticeText` of the fixture catalog's start view, no report); keep
    the last value written to the `notice` atom and, when `isNoticeShown` is set true, push its `noticeText` to
    `w.notices` and `w.band`.
  - `band.test.tsx`: drop the `MAX_NOTICES` import; match band lines by the item text (`/^\d+  /`) and the
    status `Text`, not `/TODO/` (lines 34, 57, 80, 100), so the `toBeUndefined` checks at 49, 57, 66 and 91 test
    the real thing. Replace the stacking test with:
    - **one live copy:** banner, reports with drift 1, 3, 2, then 0; after each the band holds the item lines
      plus one status `Text`: `1 out of sync`, `3 out of sync`, `2 out of sync`, `✓ in sync`.
    - **catalog edit while shown:** rewrite the catalog's rank-1 title; the band's first line follows.
    - **unavailable while shown:** no runner at start, the retry fails; the status reads `sync checks unavailable`.
    - **Dismiss is final for the session:** press `dismiss`, then drift 4, then 0; the band stays empty. A second
      `start` shows it again.
    - **layout and color:** item lines before the status; status `Text` `color` is the theme key `success` for
      clean, `warning` for drift, and `dimColor` for unavailable; item `Text`s carry `wrap="truncate-end"`.
    - **height:** `"notice": {"items": 1}` renders one item line; `"top_n": 2, "notice": {"items": 3}` renders 3.
    - **empty view:** unreadable catalog, no runner: the band stays empty and `w.toasts` is empty.
    - **default style:** with no `notice` block, `start` fills the band and `w.toasts` stays empty.
  - `checks.test.ts`: the notice assertions at 162, 172, 178, 184, 192, 256, 426, 439, 479 and 518 expect
    `START_NOTICE`; the `/todo` head assertions at 164, 193, 196, 207 keep `CATALOG_LINE`; replace the M4 block
    (218-260, including the banner `w.band` case at 249) with: toast mode posts exactly one toast at `start` and
    none for later reports with drift 2, 3 or 0; the M2 notice assertion at 292 is dropped.
  - `watch.test.ts`: lines 11, 19, 25 expect `START_NOTICE`.

- [ ] **Step 2: Run** `claude plugin test plugins/todo-watch`. Expected: FAIL on the new band and checks tests.

- [ ] **Step 3: Implement.**
  - `checks.ts`: `refreshView($, w)` writes `formatNotice(summary, report, session.status, w.cfg.noticeItems)`
    through `setNoticeView`. Call it after the summary atom updates (`refreshCatalog`), after `applyReport`
    stores a report, and after each `session.status` assignment: `runCycle` (line 345), `resetSession` (416),
    `startWatch` (445) and `retryLookup` (458). `refreshCatalog` parses `Math.max(w.cfg.topN, w.cfg.noticeItems)`
    rows; `formatTodoBody` slices its table to `topN`.
  - `showNotice($, cfg)`: returns at once on an empty view; banner -> `showBand`; toast ->
    `$.ui.toast(noticeText(view), { timeoutMs: cfg.toastMs })`. Only `startWatch` calls it, after the first
    `refreshView`. `applyReport` stores the report and calls `refreshView`, nothing else. `resetSession` calls
    `resetBand`.
  - `band.tsx`: when shown and the view is not empty, each item as `<Text wrap="truncate-end">`, then
    `<Box><Text color|dimColor>{status} </Text><Button Dismiss/></Box>` (the space inside the `Text`; Dismiss
    beside the last item line when `status` is null). Dismiss calls `hideBand`.
  - README rows: M1 (start notice layout and default banner), M4 (sync changes only update the status line),
    M7 and the `notices` state rows (one live view, `notice` and `isNoticeShown`).

- [ ] **Step 4: Run** `claude plugin test plugins/todo-watch` and `claude plugin validate --strict plugins/todo-watch`.
  Expected: all pass.

- [ ] **Step 5: Real-session toast check (developer, interactive).** In a consuming project with
  `todo.notice.style: toast`, run `claude --plugin-dir E:/automation/operator-straps/plugins/todo-watch` and look
  at the start toast. If its lines run together, set `NOTICE_TOAST_SEP = ' · '`, update the Task 2 toast test,
  and rerun Step 4.

- [ ] **Step 6: Checkpoint.**

---

### Task 4: Snapshot item links (`todo_sync`)

**Files:**
- Create: `plugins/harness/lib/harness_lib/todo_sync/stub_links.py`
- Modify: `plugins/harness/lib/harness_lib/todo_sync/report.py` (`_table_row`, `snapshot_markdown`),
  `plugins/harness/lib/harness_lib/todo_sync/__init__.py` (`render_snapshot`)
- Test: Create `tests/lib/test_todo_sync_stub_links.py`; modify `tests/scripts/test_todo_sync.py`

**Interfaces:**
- Consumes: `Sources(cfg)`, `Sources.stub(rel) -> Stub` (`anchor.value` is the entry id),
  `Sources.stub_files()`, `Sources.entries()`, `cfg.todo.stub_name` (may be null), `cfg.path(rel)`.
- Produces:
  - `item_stubs(src: Sources, item: Dict[str, Any]) -> List[str]`: repo-relative POSIX stub paths, each
    `posixpath.normpath`-ed, distinct, existing on disk, in route order: (1) `impl_stub` refs; (2)
    `<research_folder ref>/<stub_name>`; (3) for each `catalog_entry_ids` entry, its research entry's
    `stub_path`, then every stub whose anchor id is that entry. Routes 2 and 3's anchor scan are skipped when
    `stub_name` is null; route 3's anchor scan is skipped when the research root does not exist.
  - `link_target(stub_rel: str, from_dir_rel: str) -> str`: POSIX path relative to `from_dir_rel`, with space,
    `(`, `)`, `<`, `>` and `|` percent-encoded (`%20`, `%28`, `%29`, `%3C`, `%3E`, `%7C`).
  - `snapshot_markdown(header, top, top_n, rendered, links: Optional[Sequence[Sequence[str]]] = None)`;
    `links[k]` holds the link targets of row `top[k]` (by row position, so two rows sharing an id never
    share links).

- [ ] **Step 1: Write the failing tests** in `tests/lib/test_todo_sync_stub_links.py`, building projects with
  `_todo_helpers.build` and editing `todo_files()`:
  - `test_impl_stub_source_wins`: `sources: [{"type": "impl_stub", "ref": STUB_REL}]` -> `[STUB_REL]`.
  - `test_research_folder_holds_the_stub`: `{"type": "research_folder", "ref": "docs/RESEARCH/Alpha"}` -> `[STUB_REL]`.
  - `test_entry_id_matches_a_stub`: no sources, `catalog_entry_ids: ["alpha-loader"]` -> `[STUB_REL]`.
  - `test_one_stub_by_three_routes_is_one_link`: all three routes plus a `./docs/RESEARCH/Alpha/_IMPL_TODO.md`
    impl_stub ref -> `[STUB_REL]`.
  - `test_missing_impl_stub_falls_through`: impl_stub ref `docs/RESEARCH/Gone/_IMPL_TODO.md` plus entry id
    `alpha-loader` -> `[STUB_REL]`.
  - `test_two_stubs_in_route_order`: a Beta stub (anchor `beta-cache`), impl_stub ref to Beta plus entry id
    `alpha-loader` -> `["docs/RESEARCH/Beta/_IMPL_TODO.md", STUB_REL]`.
  - `test_no_stub_is_empty`: only a `gh_issue` source -> `[]`.
  - `test_null_stub_name_uses_impl_stub_only`: config `{"folder": TODO_DIR, "stub_name": None}`, an item with an
    impl_stub ref and a research folder -> only the impl_stub path.
  - `test_link_target`: `link_target(STUB_REL, SNAP_DIR) == "../../Alpha/_IMPL_TODO.md"`;
    `link_target("docs/RESEARCH/A B (x)/_IMPL_TODO.md", SNAP_DIR) == "../../A%20B%20%28x%29/_IMPL_TODO.md"`.

  In `tests/scripts/test_todo_sync.py`:
  - extend `test_render_then_t2_is_clean`: TODO-002's cell contains `[TODO-002](../../Alpha/_IMPL_TODO.md) `
    then its title; TODO-001's and TODO-003's cells have no `](`; T2 still reports nothing.
  - `test_render_extra_stubs_and_escaping`: an item with two stubs and the title `a | [b](c)` renders
    `[<id>](<t1>) a \| \[b\]\(c\) [2](<t2>)` and the row still has 7 cells.
  - `test_render_with_null_stub_name`: `stub_name: null` renders without error.

- [ ] **Step 2: Run** `python -m pytest tests/lib/test_todo_sync_stub_links.py tests/scripts/test_todo_sync.py -q`.
  Expected: FAIL, `stub_links` not found.

- [ ] **Step 3: Implement.** `stub_links.py` holds `item_stubs` and `link_target` (`posixpath.relpath`, then
  the percent-encoding). In `report.py`, the Item cell is `[id](t1) title [2](t2) [3](t3)` when the id has
  targets, else today's `id title`; the title is `_cell`-escaped with `[`, `]`, `(` and `)` backslash-escaped too,
  except inside backtick code spans, which stay verbatim (a backslash there renders literally); targets are
  already safe. `render_snapshot` builds one `Sources(cfg)` and a list parallel to the top rows, each entry
  `[link_target(s, todo.snapshots.dir) for s in item_stubs(src, item)]` (empty for a non-string id), and
  passes it; links are keyed by row position, never by id. `item_stubs` treats a non-list `sources` or
  `catalog_entry_ids` as empty, dedupes by the on-disk spelling, and emits that spelling.

- [ ] **Step 4: Run** the Step 2 command plus
  `python -m pytest tests/contract/test_no_repo_literals.py tests/contract/test_root_separation.py tests/lib/test_todo_sync_rules_todo.py -q`
  and `python -m ruff check --no-cache plugins tests tools`. Expected: all pass, ruff clean.

- [ ] **Step 5: Checkpoint.**
