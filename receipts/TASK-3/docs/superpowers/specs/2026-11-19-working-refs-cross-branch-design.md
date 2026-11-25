# Working refs across branches, retired and closed refs hidden

Refs: todo-k69m (#301). Follows `docs/superpowers/specs/2026-11-17-working-refs-banner-design.md` (plan 2025).
Date: 2026-11-19.

## Intent

The working line exists to show where work is in flight, so the developer can close it out, monitor it or clear
the list. Today an override (`/harness:working`) shows only on the branch it was set on, and it stays until
`--clear`, whether or not its TODO item was retired or its issue closed. On another branch the line goes blank
(or, with the mod not running, ccstatusline keeps printing the last branch's line with no sign it is stale).

The change: every live override shows on every branch, each other branch's refs bracketed and labeled with
that branch in a dark color; a ref leaves the line only when its TODO id is retired or its issue is closed.

This deliberately reverses one goal of the 2026-11-17 spec ("keep a branch's line from following the developer
onto another branch") for overrides only: the refs follow, labeled with the branch they belong to, so they never
read as the current branch's.

## Goals

- **Cross-branch overrides.** The current branch's own refs come first, unlabeled. Every other branch's
  override follows as `[ <branch> <refs> ]`, the branch name dark, most recently set first.
- **A length cap.** The line stops at a configured total length (`working_refs.max_chars`); other-branch
  segments that do not fit are dropped from the end and counted as ` +N`. The own segment and the plan links
  are never dropped. The cap applies to the line the mod builds; the widget's stale-branch stamp (below) is
  added on top of it.
- **TODO ids hide when retired.** A TODO id listed in the catalog's `retired_ids` is hidden from the line. The
  catalog that counts is the checked-out one, so an id retired on one branch shows again on a branch whose
  catalog has not retired it.
- **Issues hide when closed.** An issue GitHub reports as closed is hidden from the line. TODO ids and issues
  hide independently: `todo-k69m (301)` becomes `#301` when the item is retired and `todo-k69m` when the issue
  closes. A segment with every ref hidden is not drawn.
- **Issue state from two feeds.** The mod checks the issues it shows with `gh issue view <n> --json state`,
  cached and refreshed past `todo.gh.max_age_hours`; `todo_sync.py untracked` (the `sync-gh-todo` skill) also
  writes the complete open-issue list it already fetches, which the mod reads. The fresher answer per issue
  wins. Only `gh` answers CLOSED: the open list answers OPEN for the numbers it lists, and an issue missing
  from it (filed after the fetch, or a PR number) is due for a `gh` check, shown until `gh` reports it closed.
- **A branch-stamped line file.** The mod writes `<state_dir>/working-refs/line.json` (`version`, `branch`,
  `text`) beside `line.txt`; the ccstatusline command reads `line.json`, reads the checkout's current branch
  from the git HEAD file, and when the two differ prints the stamped branch dark before the text.
- **band-line** draws the bracketed segments with the branch name dim.

## Non-goals

- Plan refs and plan links stay as they are (rule 1 and rule 2 of `qualifies`). The smallest change toward
  keeping a non-qualifying plan link painted as a warning is recorded, deferred, in
  `docs/RESEARCH/working-refs/plan-link-stale-paint.md`.
- `overrides.json` is never rewritten by the hide rules: a retired id or closed issue is hidden, not deleted, so
  a reopened issue returns and `/harness:working --list` still shows what was stored.
- No pruning by `todo_sync.py retire`.
- "Every branch" means every branch of one checkout. `overrides.json`, `open_issues.json` and `issues.json`
  stay under each checkout's `state_dir` (the 2026-11-17 choice), so a `d-w` worktree session does not see
  the main checkout's overrides (developer decision, 2026-11-19).
- No way to clear another branch's override (`/harness:working --clear` acts on the current branch): an
  entry for a deleted branch stays until its refs retire or close. Deferred to a TODO item (developer
  decision, 2026-11-19).

## Anti-goals

- A status-line command that runs git or another child process on every repaint: the widget's node one-liner
  reads files only.
- A `gh` call on a prompt or tool call path: issue checks run after the dispatch (`later`), at most once per
  issue per `todo.gh.max_age_hours`.
- An issue hidden because `gh` failed: an issue with no known state shows.

## Constraints

- A new config key touches `plugins/harness/config/defaults.json`, `config/harness.schema.json`,
  `lib/harness_lib/config.py` and the README key table; the mod mirrors its default in `hooks/mirror.ts`, pinned
  by `tests/mods/test_working_refs_contract.py`. The mod also reads `todo.folder`, `todo.catalog`,
  `todo.gh.repo` and `todo.gh.max_age_hours`, each default mirrored the same way.
- Each file has one writer: the harness writes `overrides.json` and `todo-sync/open_issues.json`; the mod writes
  `line.txt`, `line.json` and `working-refs/issues.json`.
- `open_issues()` raises at `LIST_LIMIT`, so the open list is written only when complete.
- band-line keeps a local copy of the `WorkingLine` shape; the new segment field is optional there, so an older
  working-refs still draws through `text`.

## Approaches

| | A. Segments in the atom, mod renders both forms (**chosen**) | B. Mod stores raw overrides, each drawer formats |
|---|---|---|
| Atom | `WorkingLine.segments` plus the plain `text` | raw entries; band-line formats |
| ccstatusline | the mod writes the ANSI form to `line.json` | the node one-liner formats JSON (unreadable one-liner) |
| Cap and order | one place | duplicated per drawer |

A keeps formatting in the mod, which already owns both forms (`plainText`, `statusText`). The developer agreed to
A in conversation (2026-11-19).

## Decided

- Brackets: `[ ` and ` ]` around each other-branch segment; segments joined by a space after the own part's
  ` · ` separator.
- Order of other branches: `set_at` descending.
- Overflow: ` +N` after the last segment that fits.
- Dark color: ANSI 256-color 240 (`\x1b[38;5;240m` ... `\x1b[39m`) in the ccstatusline form; `dimColor` in
  band-line.
- A gh failure keeps the issue's last known state (a known CLOSED stays hidden); with none, the issue shows.
- `line.txt` keeps being written, unchanged in content, for configs that still read it.

## Left to the builder

- The default of `working_refs.max_chars` (a value that fits one status line at common widths).
- The `issues.json` cache shape, within the one-writer rule.
