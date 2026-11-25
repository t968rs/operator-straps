# Working refs and plan links in the banner

Issues: #301 (TODO item todo-k69m) and its sub-issue #315. Date: 2026-11-17.

## Intent

While working a branch, the developer wants the TODO ids, the GitHub issues and the plan behind that branch kept
on screen, for example `plan 2024 · todo-k69m (301)`, with each plan a link to its local HTML page (#315, "like
the PR link" Claude Code shows). Today the refs are tracked by hand in session-bookmark notes, which have no
branch scope and are read only at compaction.

## Goals

- Show the current branch's plans (as links), TODO ids and issue numbers in a project-level ccstatusline status
  line (the developer runs ccstatusline today at user level, `npx -y ccstatusline@latest`; the widget goes in
  each project's own config). **ccstatusline is the primary surface.**
- Show the same line in band-line, as a second line of its band, for projects on that banner.
- Fill the line automatically from the plans folder; a manual command overrides the refs.
- Keep a branch's line from following the developer onto another branch.

## Non-goals

- git-status's own fallback line does not get the refs.
- No parsing of branch names (local branches carry a sequence prefix, not an issue number) and no reading of
  session-bookmark notes.
- No change to the bookmark-notes items: todo-v8mh (#279), todo-545g (#272), todo-v62t (#305).
- No `/goal` integration (todo-jq3x, #282) and no `bin/` wrapper (todo-cvm4, #283); see Related items.

## Anti-goals

- A line that shows another branch's plan as if it were this branch's, beyond the base-commit rule below.
- A status-line command that is slow on every repaint (the developer's config repaints every 10 s with
  `customCommandCacheTtlSeconds: 0`).
- Plan links that never leave the banner.

## Constraints

- Plugins stay generic; the mod copies `state_dir` and `artifacts.plans` defaults from harness and a test pins
  the copy (the `session-bookmark` `notes.ts` and `todo-watch` `config.ts` pattern).
- Data goes under the consuming project (`<state_dir>/working-refs/`); plugin roots are read-only.
- Mods can run git (`$.process.run`, `plugins/git-status/hooks/status.ts:155`), write files (`$.fs.write`,
  `plugins/agent-watcher/hooks/core/watch.ts:110`) and track mtimes (`plugins/todo-watch/hooks/checks.ts:249`).
- ccstatusline has a `custom-command` widget that runs `commandPath` (verified in the installed build's
  `dist`); `customCommandCacheTtlSeconds` is a ccstatusline config key.
- On a receipts plan the freeze digest hashes every plan field but `frozen`
  (`plugins/harness/lib/harness_lib/plan_doc.py:219-228`), so a field added to a frozen plan breaks `check`.
- `plan.py archive` writes only tags (`archive/<stem>/r1`, stem `plan/<id>-<slug>`), no file
  (`plugins/harness/scripts/plan.py:139-153`, `plugins/harness/lib/harness_lib/plan_archive.py:162-163`).

## Approaches

| | A. Mod renders, widget prints (**chosen**) | B. Mod stores, Python widget renders | C. No mod; `plan.py` writes, widget matches |
|---|---|---|---|
| Qualifying check | new mod | new mod | widget, every repaint |
| On disk | `refs.json` plus the rendered line | `refs.json` | `refs.json` from `plan.py` |
| Widget `commandPath` | a `node -e` one-liner printing a file | `hpy` + harness script; needs a stable path (#283) | same as B |
| Repaint cost | one file read | a Python start | a Python start plus git calls |

The developer chose **A**: the widget holds no code and needs no plugin path; matching lives in the one place that
watches the folder and knows the branch. Its cost: the override (written by a harness skill) and the plan hits
(written by the mod) meet in `refs.json`, so a contract test pins that shape on both sides. B and C put an
interpreter start on every repaint; C also contradicts the developer's mod design and misses a rebase until the
next `plan.py` write.

## Decided design

### 1. `refs` on the plan (harness)

- `plan.py new` takes `--refs todo-k69m,#301` (comma-separated; TODO ids canonicalized as `todo_sync` does,
  issues as integers). The ActionPlan JSON gains a structured top-level `refs`: `{todo_ids: [...], issues:
  [...]}`, in the plan model, the ActionPlan schema and `plan_api.write`. **Distinct field, never scraped from
  prose** (developer's decision).
- A TODO id given with no issue gets its `gh_issues` from the catalog when the line is built.

### 2. The `working-refs` mod (new, ninth mod)

- **Watches** `artifacts.plans` (default mirrored from harness, overridden by the project's `harness.json`).
  A new or rewritten `*_PIP.html` triggers a check. The mod also scans the folder at `session.start` and when
  git-status's branch moves.
- **Reads the sibling `<prefix>_ActionPlan.json`**, not the HTML: `branch`, `base_branch`, the full
  `base_commit` and `refs`. The HTML shows the same branch and a 7-character base but is presentation.
- **A plan qualifies** for the current branch when either holds (developer's rule; two ways to qualify):
  1. its `branch` equals the current branch, or
  2. its `base_commit` equals `git merge-base HEAD <plan.base_branch>`.

  **and** no `archive/<stem>/` tag exists (archive is the developer's chosen removal trigger). Tags are checked
  with one `git for-each-ref` during each scan and on `prompt.submit`, since archive writes no file.
- **Every qualifying plan shows**: several plans give several links.
- **Writes** `<state_dir>/working-refs/refs.json`, keyed by branch:
  `{version, branches: {<branch>: {plans: [{id, page, set_at}], override: {todo_ids, issues, set_at} | null}}}`,
  and the rendered line for the checkout (a plain text file the widget prints), and holds the line in a state
  atom for band-line.
- **Line**: plan links first, then refs: `plan 2024 · todo-k69m (301)`; several plans `plans 2024, 2025 · ...`.
  Refs are the override when set, else the union of the qualifying plans' `refs`. Empty when nothing qualifies
  and no override is set (the widget prints nothing).

### 3. `/harness:working` (harness skill, the override)

`/harness:working todo-k69m [#301] | --clear | --list`. Its script writes the current branch's `override` in
`refs.json` (canonicalized ids; catalog `gh_issues` fill a TODO id with no issue). `--clear` removes the
override, so the plan refs show again. Plan links are not affected by the override. The mod notices the
`refs.json` mtime and re-renders.

### 4. ccstatusline (banner-status)

**Project-level** (developer's decision): the plans folder and `state_dir` are per-project config, so the widget
lives in the project's `.claude/ccstatusline.json`, never the user's home config. `/banner-status:setup-statusline`
adds a `custom-command` widget on its own line (a third line in `ccstatusline.defaults.json`) whose `commandPath`
prints the rendered line file, or nothing when it is absent. The skill resolves the project's `state_dir` when
it writes the widget, so a custom `state_dir` is honored.

A project whose `.claude/ccstatusline.json` already exists keeps it today (the skill never overwrites it); the
skill gains an opt-in step that adds only the working-refs widget to an existing project file, after a yes. A
project with no `statusLine` (this repository) runs the skill once; its project setting then wins over the
user-level status line in that project only.

The rendered line file's path in `commandPath` is relative to the checkout root when ccstatusline runs the
command in the session's cwd, so a worktree session prints its own checkout's line; otherwise it is absolute
and a worktree shows the main checkout's line (a known limit). The spike below decides which.

### 5. band-line

Reads the `working-refs` mod's state atom (as it reads git-status's `git`) and draws the line as a second line of
its Box; `formatBanner`'s one-line width budget is untouched. Without the mod installed the atom holds its
default and nothing extra is drawn.

## Related items (in the plan as references, not built)

| Item | Issue | Relation |
|---|---|---|
| todo-k69m | #301 | Built: this design. Retire after merge. |
| (none in catalog) | #315 | Built: the plan links. Add to the catalog on the next sync. |
| todo-cvm4 | #283 | A `bin/` wrapper; not needed under approach A. |
| todo-v8mh | #279 | Branch-scoped bookmark notes; shares the branch-key idea, separate store. |
| todo-jq3x | #282 | A later `/goal` hook could write the override; gated on whether an agent can set `/goal`. |
| todo-v62t | #305 | No-model-turn print of notes; same concern as `--list`. |

todo-545g (#272) and todo-ys3k (#204) are out of scope; todo-4zhu and todo-w3ck are retired.

## Builder's calls (marked as such)

- **Refs on a frozen plan**: `refs` is set at `new` (or by `plan_api.write` before freeze); after freeze the
  override covers changes, so `refs` is not exempted from the digest. *(designer's call)*
- **HTML-only plans qualify**: a plan whose `documentation` is a markdown PIP has no page to link and is skipped.
  *(designer's call)*
- **Mod depends on git-status** for the branch and its moves; it runs git itself for merge-base and tags.
  *(designer's call)*
- **Rebases and new commits**: git-status's snapshot carries no HEAD SHA (`plugins/git-status/hooks/status.ts:42-63`),
  so the mod runs `git rev-parse HEAD` on `prompt.submit` with the tag check and rescans when HEAD moved; rule 2
  then follows a rebase or a merge from the base without a branch switch. git-status is not changed.
  *(designer's call)*
- **Files per checkout**: `refs.json` and the rendered line live under each checkout's own `state_dir`
  (`cfg.path`, not `main_worktree`). git refuses one branch in two worktrees, so per-checkout files keyed by
  branch never collide and lose no override. A detached-HEAD worktree (`harness:d-w`) keys its entry as
  `(detached)` in its own file; rule 1 cannot match there, rule 2 still does, and `/harness:working` writes the
  `(detached)` override for that checkout. *(designer's call)*
- **Link format**: try an OSC 8 hyperlink (visible text `plan 2024`, target the page's `file:///` URL) in both
  ccstatusline and band-line; fall back to the bare path where the escape is stripped. **Needs a spike.**
- **Widget command**: a portable `node -e` one-liner; whether ccstatusline runs it in the session's cwd (so a
  relative state path works in worktrees) or needs the absolute project path is **unverified; spike with the
  link format.** The spike is the plan's first item, since its answer sets the widget path, the link format in
  both surfaces and the setup-statusline change.
- Module split inside the mod, names, test layout, and the release notes and version bumps (new plugin, harness,
  band-line and banner-status minors) are the builder's.
