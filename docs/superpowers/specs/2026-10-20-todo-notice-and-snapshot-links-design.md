# TODO notice layout and snapshot links

Date: 2026-10-20. Branch: `0015-TOAST-format` (from `main` at `18f883f`). Tracks issue #32 plus one
snapshot request from the developer.

**Status: frozen 2026-10-20 after the review patch.** This file is a snapshot of the design. The plan,
`docs/superpowers/plans/2026-10-20-todo-notice-and-snapshot-links.md`, is the source of truth from here on.

## Intent

The todo-watch notice should answer one question at a glance: what to work on next. The sync state of the
TODO catalog is a side check and should read as one: small, colored, below the items. Issue #32 asks for a
configurable height, the items above the stats, and research into a notice that stays.

The dated TODO snapshot (`TODO_Snapshot_YYYY_MMDD.md`) should let a reader click from an item straight to its
`_IMPL_TODO.md`.

## Part A: the todo-watch notice (plugin `todo-watch`, config in `harness`)

### What the developer chose

The layout is option B from the mockup session:

```
1  Add height option to todo-watch toast
2  Link snapshot items to their _IMPL_TODO.md
3  Narrow select_tests import closure
✓ in sync  [Dismiss]
```

- **Top:** the next items, one per line, `<rank>  <title>`, ordered by rank. Ranks, not ids.
- **Bottom:** one small line with only the sync status: green `✓ in sync` when the latest fresh report has
  zero drift, yellow `<N> out of sync` when it has drift. No item counts, no status counts (`/todo` keeps
  them). Then the Dismiss button (banner only).
- **Item count is a setting** (the issue's "height"), default 3.
- **Sync status never drives the notice** (developer, 2026-10-20: "sync status should not influence the TODO
  appearance at all. I basically want it there all the time, unless dismissed"). The notice shows at session
  start and stays until Dismiss; a sync change only updates the bottom line's text and color. No drift
  notice ever shows, re-shows or posts on its own.
- **Banner becomes the default style** (author's call, following "there all the time"): a toast leaves after
  at most a minute. `todo.notice.style: toast` keeps working and posts one plain-text toast at session start.
- **Sticky:** the banner already stays until Dismiss; that is the sticky answer for #32.

### Platform facts (checked against `plugins/todo-watch/.claude-plugin/types/claude-code/index.d.ts`)

- `$.ui.toast(text, { timeoutMs })` takes one plain string: no color, no styling. The engine caps the timeout
  at a minute (`MAX_TOAST_SECONDS = 60` in `hooks/config.ts`). Where the transcript prints to scrollback, a
  toast is one line on the notification bar. A toast therefore cannot be sticky or colored.
- The band (`hooks/band.tsx`, `ui.render` on `AbovePrompt`) renders `Box`/`Text`/`Button`, so color,
  dimming and several lines are available there.

### Behavior

1. **The notice content is live** (author's call): one view, recomputed whenever the catalog summary, the
   latest fresh report or the checks status changes, from the summary's top rows (`summaryAtom`, parsed by
   `parseCatalog`), the report (`reportAtom`) and `session.status`. A visible band therefore follows catalog edits and
   every sync change; only session start and Dismiss change whether it is visible (step 4).
2. **Item lines:** the first `todo.notice.items` rows by rank, each `<rank>  <title>` with the title folded
   to one line and clipped to 80 characters (author's call; today's summary clip is 60). A catalog with fewer items shows fewer lines; an empty or unreadable catalog
   shows no item lines.
3. **Status line:**
   - fresh report, drift 0: `✓ in sync`, green.
   - fresh report, drift N > 0: `<N> out of sync`, yellow.
   - no fresh report yet: no status line (nothing is known yet).
   - checks unavailable: `sync checks unavailable`, dim.
   The `gh <age> old` segment leaves the notice; `/todo` keeps it.
4. **When it shows:** once, at session start (also after `/clear` or a resume, which start a session). Banner:
   the band shows and stays until Dismiss, its content live per step 1. Toast: one toast with the view as it
   stands at start (usually no status line yet, since the first report lands later). Drift rising, falling,
   reaching zero or checks becoming unavailable never shows, re-shows or posts anything. The drift-notice
   machinery (`driftToast`, `CLEAN_TOAST`, the `lastToastDrift` atom) goes away.
5. **Toast text:** the item lines, then the status text, joined with newlines. Builder check: confirm in a
   real session whether the toast box draws `\n` as line breaks; if it does not, join with ` · ` instead.
   The status line is never clipped (author's call): item titles keep their per-line clip (step 2) and the
   old whole-text 160-character `MAX_TOAST` clip does not apply to the notice (the engine draws 2000).
6. **Dismiss** hides the band for the rest of the session. The next session start shows it again.
7. **An empty view** (no item lines and no status, as with an unreadable catalog before any report) shows
   nothing: no empty toast, no band holding only Dismiss.
8. **Colors use theme keys** (author's call, after review): `success` for in sync, `warning` for drift, dim for
   unavailable, so a light terminal theme stays readable. Item lines truncate at the terminal edge instead of
   wrapping.

### New config key: `todo.notice.items`

- Integer, default **3**, minimum 1, maximum 10. The mod parses `max(todo.top_n, todo.notice.items)` catalog
  rows, so a small `top_n` never caps the notice; `/todo` still shows `top_n` rows. The `top_n` schema
  description loses its stale "start notice shows only the rank-1 title" sentence.
- Touches, per the repo rule: `plugins/harness/config/defaults.json`, `config/harness.schema.json`, the todo
  notice dataclass and builder in `lib/harness_lib/config.py`, the README key table, and the mirror in
  `plugins/todo-watch/hooks/config.ts` (checked by `tests/mods/test_todo_watch_config_mirror.py`).
- Out-of-range or non-integer values fall back to the default in the mod, the same way `toast_seconds` does.

### Things that stay as they are

- The `TODO_SYNC` prompt context line (M2) and `/todo` (M5) are unchanged.
- README: the todo-watch M4 row (drift notices) is rewritten to say sync changes only update the status line;
  the `todo.notice.style` row names `banner` as the default.

## Part B: snapshot item links (plugin `harness`, `todo_sync`)

### What the developer chose

- In the snapshot table's `Item` column, the item **id** becomes a relative link to that item's
  `_IMPL_TODO.md`. The title stays plain text: `[TODO-001](../../Pylint/_IMPL_TODO.md) Pylint error catalog`.
- An item with no stub stays plain text (no GitHub-issue fallback for now).

### Finding an item's stub (revised after review)

Final rule, superseding the route list below where they differ: paths are `posixpath.normpath`-ed before
deduping; route 3 first takes each listed research entry's own `stub_path`, then stubs whose anchor names the
entry; with `todo.stub_name` null only route 1 runs, and without a research root route 3's anchor scan is
skipped, so `render` never fails on a config that renders today.

Collect every distinct existing stub across all three routes, in this route order (the first one found
becomes the id's link; see "More than one stub"):

1. a `sources[]` entry with `type: impl_stub`: its `ref`, when the file exists.
2. a `sources[]` entry with `type: research_folder`: `<ref>/<todo.stub_name>`, when that file exists.
3. a stub (any `todo.stub_name` file under the research root, `Sources.stub_files()`) whose
   `catalog_entry:` anchor id is one of the item's `catalog_entry_ids` (`Sources.stub()` parses the anchor).

Within one route, keep the order the catalog lists sources or entry ids in.

Measured on the real consuming catalog (82 items, 19 stubs): direct 26, folder 30, entry id 10, none 16;
2 items resolve to more than one distinct stub.

### More than one stub (the builder-facing call, marked as such)

The id links to the first stub found. Each further distinct stub follows the title as a numbered link,
`[2](<path>)`, `[3](<path>)`. This was proposed in the conversation and not objected to; it is the author's
call, not an explicit developer decision.

### Link form

- Relative to the snapshot file's folder (`todo.snapshots.dir`), POSIX separators, so it works in an IDE
  preview and on GitHub.
- Space, `(`, `)`, `<`, `>` and `|` in a target are percent-encoded (`../../A%20B/_IMPL_TODO.md`), which more
  previewers accept than the `<...>` form and keeps a `|` from splitting the table cell (author's call, after
  review).
- The title stays escaped by `_cell` (pipes) and also gets `[`, `]`, `(`, `)` backslash-escaped, so a title
  never forms a second live link. Ids are schema-pinned to `^TODO-[0-9]{3,}$` and need no escaping.

### Things that stay as they are

- Column set and order (`Rank | Item | Kind | Blast | LoE | Score | GH`), the header comment line, and the
  file name.
- Rule T2: it hashes `[id, rank, status, title]` rows from the catalog and never reads the table text, so
  links do not change the hash or trip T2.

## Goals

- The notice shows the next 1-N items first and the sync state small and colored below.
- One setting controls how many items show.
- Snapshot ids click through to their stubs.

## Non-goals

- Coloring the toast (the platform does not support it).
- A toast that stays longer than the engine's one-minute cap.
- GitHub-issue links for stub-less items.
- Changing `/todo` or the `TODO_SYNC` context line.
- Changing which items count as "next" (the order stays rank order, every status included, as today).

## Anti-goals

- A notice that grows: the band must never stack copies of the summary or old drift lines.
- A snapshot link that points at a file missing at render time. A stub moved or deleted after the render is
  out of scope (author's call): the snapshot is a dated point-in-time file, the next `render` fixes it, and
  no rule re-checks links.
- Any project path or name inside the plugins (`tests/contract/test_no_repo_literals.py`).

## Constraints

- Repo rules in `CLAUDE.md`: the four-place config key rule plus the mod mirror; plugins stay generic; data
  goes to the project. Python 3.11, `Optional`/`Union`, functions under 50 lines.
- Tests: Python by file (`tests/lib/test_todo_sync_*.py`, `tests/scripts/test_todo_sync.py`,
  `tests/lib/test_config.py`, `tests/mods/test_todo_watch_config_mirror.py`); the mod with
  `claude plugin test plugins/todo-watch`; manifests with `claude plugin validate --strict`.
- Version bumps: `harness` 0.10.0 -> 0.11.0 (new key, snapshot output change); `todo-watch` 0.3.0 -> 0.4.0
  (notice layout change).

## Left to the builder

- Whether the band state becomes a small record (`{ visible, ... }`) or keeps a list; the anti-goal above is
  what matters.
- The toast line separator, decided by the real-session check in Behavior step 5.
- Where the stub resolver lives inside `todo_sync` (a function beside `render_snapshot`, or on `Sources`).
