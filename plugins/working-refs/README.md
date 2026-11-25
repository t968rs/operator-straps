# working-refs

The plans, TODO ids and issues the current branch works on, then every other branch's override, as one line:
the ccstatusline widget prints it from a file, and band-line draws it from state.

```
plan 2025 · todo-k69m banner (301)
plans 2024, 2025 · todo-k69m banner, todo-zz11 (301, 315)
plan 2027 · todo-x7ty stop_gates (301) · [ 1168-todo-banner todo-48q2 ] [ (detached) #315 ] +1
```

- Plan links come first, each plan number an OSC 8 link to its `<prefix>_PIP.html` page in the line file.
- The own refs are the branch's override entry when it has one (`/harness:working`), else the union of the
  qualifying plans' `refs`. Plan links are never overridden.
- Each TODO id is labelled with its catalog item's `keyword` (`todo-x7ty stop_gates`); an id whose item has no
  keyword, or that the catalog does not list, prints alone. In the line file each label (the id alone when it
  has none) is drawn in its TODO's own color: ANSI 256 color 39, 170, 36, 214, 141, 72, 203 or 178, picked by
  the FNV-1a 32-bit hash of the id, so a TODO keeps its color across branches and segments. The
  `/harness:working` reply stays unlabelled.
- The other pieces of the line file are colored too (ANSI 256 colors): each plan number by how far its plan
  is (below), each issue number 180, another branch's name 246, and the punctuation (the word `plan` or
  `plans`, the separators, commas, brackets, the parentheses around issues and `+N`) 240. Only the
  ccstatusline form (`line.txt`, the `text` of `line.json`) is colored; the plain `text` band-line reads is
  unchanged, and the cap measures the plain text.
- A plan number steps through the ramp 51, 45, 74, 67, 243 as its items finish: step 0 (51) when no item is
  done or the plan has no items, step 4 (243) when every item is done, else step 1 + floor(3 * done / total)
  (45, 74 or 67). The ramp shares no color with the TODO palette.
- An item is done when its receipt `<artifacts.plans>/<id>/receipts/<ITEM>.json`, naming that item, has an
  outcome kind of `complete` or `closed`. An item with no valid receipt (absent, unreadable, naming another
  item, or without an outcome kind) is done when its own status is `COMPLETE` or `CLOSED_NO_ACTION`. A
  `started` or `blocked` receipt is not done, whatever the item's status says. A plan id that two plan files
  on the line share gets no receipts progress, since the receipts belong to neither for certain: each such
  plan counts its item statuses alone. The receipt-else-status fallback applies to each item, which differs
  from the harness: `plan.py status` (`plan_receipts.status_view`) counts an item of a receipts-scheme plan
  with no receipt as `PENDING`, and reads receipts only for a plan whose `frozen.records` is `receipts`
  (`book_for`). The line counts receipts for any plan on it, whatever its `frozen.records` scheme, so a
  `COMPLETE` item with no receipt, or a leftover receipts folder, can show more progress on the line than on
  the plan page.
- Every other branch's override follows as `[ <branch> <refs> ]`, most recently set first (`set_at`), the
  branch name in color 246 in the line file and dim in band-line. Segments past `working_refs.max_chars`
  fold into a trailing ` +N`; the plans and the own refs are never cut, and with no own part the first
  segment always shows.
- Nothing qualifies and no branch has a visible override: the line is empty, and the widget prints nothing.

## What hides

An override's refs leave the line without the override file changing (`/harness:working --list` still shows
them); plan refs never hide, since a plan leaves through its archive tag.

- **A TODO id** hides when the checked-out catalog (`todo.folder` / `todo.catalog`) lists it in `retired_ids`.
  The catalog is the one in this checkout, so an id retired on one branch shows again on a branch whose
  catalog has not retired it.
- **An issue** hides only when `gh issue view <n> --json state` answered CLOSED (or MERGED, for a pull
  request number, recorded as CLOSED). Two feeds answer: the mod's
  own cache (`working-refs/issues.json`) and the open-issue list `todo_sync.py untracked` (`sync-gh-todo`)
  writes (`todo-sync/open_issues.json`), which answers OPEN for the numbers it holds. The fresher answer wins.
  An issue missing from the list (filed after the fetch, or a PR number) is no answer: it shows until `gh`
  reports it closed.
- A recheck pass runs `gh` for each override issue whose last answer is older than `todo.gh.max_age_hours`
  (in the checkout, `--repo` when `todo.gh.repo` is set, 10 s timeout). A failed `gh` run keeps the last known state
  (a known CLOSED stays hidden), records UNKNOWN (shown) when nothing is known, and waits the same age before
  the next try. A run that succeeds with output that is not JSON, or a state other than OPEN, CLOSED or
  MERGED, is an answer: it records UNKNOWN over a known CLOSED, and the issue shows again. The pass runs after every scan and, in an idle session, at the prompt once an issue falls due.
- A segment whose refs all hide is not drawn.

Every branch means every branch of one checkout: `overrides.json` and both issue files live under the
checkout's own `state_dir` (with a relative `state_dir`; an absolute one is shared, and every checkout then sees
the same overrides), so a `d-w` worktree session does not see the main checkout's overrides.

## Which plans show

A plan is a `<prefix>_ActionPlan.json` in `artifacts.plans` with its `<prefix>_PIP.html` beside it (a plan
whose page is markdown has nothing to link and is skipped). It shows when it has no
`archive/plan/<id>-<slug>/` tag and either:

1. its `branch` is the current branch (never on a detached HEAD), or
2. its `base_commit` is the merge base of HEAD and its `base_branch`, resolved as `plan.py new` recorded it,
   without a fetch: `origin/<base>` when it exists and local `<base>` does not contain it, else `<base>`;
   then `git merge-base <tip> HEAD`. One resolution per distinct base branch per scan; a failed git call is
   no match.

The branch comes from git-status's `git` snapshot, so the mod lists `git-status` under `dependencies`. Before
the first snapshot, rule 1 and the overrides wait; rule 2 still applies.

## Activation and configuration

The project root is the session cwd or the nearest folder above it holding `.claude/harness.json`, then
`CLAUDE_PROJECT_DIR`; with no such file anywhere, the cwd with the default folders. These harness keys are read,
their defaults mirrored in `hooks/mirror.ts` (pinned by `tests/mods/test_working_refs_contract.py`); a
wrong-typed value keeps the default:

| Key | Default | Use |
|-----|---------|-----|
| `state_dir` | `.claude/state/harness` | The override file, the line files and the issue cache live under `<state_dir>/working-refs/`; the open-issue list under `<state_dir>/todo-sync/`. |
| `artifacts.plans` | `docs/PLANS` | The folder scanned for plans and their pages. |
| `todo.folder`, `todo.catalog` | `null`, `RepoToDo.json` | The catalog whose `retired_ids` hide TODO ids and whose items' `keyword`s label them; with no folder nothing retires and no id is labelled. |
| `todo.gh.repo` | `null` | Passed to `gh` as `--repo`; null lets `gh` resolve the checkout's repository. |
| `todo.gh.max_age_hours` | `24` | The age past which an override issue is rechecked with `gh`. |
| `working_refs.max_chars` | `120` | The total length of the line; other-branch segments past it fold into ` +N`. |

## Hooks

| Hook | Does |
|------|------|
| `session.start` | Forgets the last session and scans, after the dispatch. |
| `state.set` git-status `git` | Scans when the snapshot names another branch than the last scan used. |
| `prompt.submit` | After the dispatch: scans when the snapshot's branch, `git rev-parse HEAD` or the archive tags moved (git only while a plan was read; a rebase or a merge from the base moves HEAD), or the files did; starts a `gh` recheck once an override issue fell due. |
| `tool.call` Bash, PowerShell, Edit, MultiEdit, Write | After the call: scans when the plans folder's signature, the receipts of the plans on the line (the name, size and mtime of each `.json` in their `<id>/receipts/` folders; no other plan's folder is listed) or the mtime of the override file, the catalog or the open-issue list moved. |

The plans folder's signature is the name, size and mtime of each `*_ActionPlan.json` and `*_PIP.html`, so a
plan rewritten in place counts; the folder's own mtime does not move then. Every git call runs through
`$.process.run` with a 10 s timeout and never throws, and so does every `gh` call; scans run one at a time, a
request during one owed after it, and recheck passes the same way. A recheck that changes whether an issue
hides requests a scan.

## State

`$.state['working-refs']` (contract: `types/index.d.ts`):

| Key | Meaning |
|-----|---------|
| `line` | The branch's working line (`plans`, each with its link and its `done` and `total` item counts; own refs, their keyword `labels` and formatted plain `refs`, `head`, the drawn `others` segments each with its `labels` and `issues`, `more`, plain `text`); null before the first scan and while nothing qualifies and no branch's override shows. Written only when it changed. |

## Files

| Path | Writer | Contents |
|------|--------|----------|
| `<state_dir>/working-refs/overrides.json` | `/harness:working` only | `{ "version": 1, "branches": { <branch>: { "todo_ids", "issues", "set_at" } } }`; a detached HEAD keys as `(detached)`. |
| `<state_dir>/working-refs/line.txt` | this mod only | The ccstatusline form of the line, no trailing newline; empty when there is no line. Kept for widgets that still read it. |
| `<state_dir>/working-refs/line.json` | this mod only | `{ "version": 1, "branch", "text" }`: the ccstatusline form stamped with the branch it was built for; the widget prints the stamp dark when the checkout's HEAD names another branch. Not written before git-status's first snapshot. |
| `<state_dir>/working-refs/issues.json` | this mod only | `{ "version": 1, "issues": { <n>: { "state", "checked_at", "tried_at" } } }`: the `gh` answers for override issues. |
| `<state_dir>/todo-sync/open_issues.json` | `todo_sync.py untracked` only | `{ "version": 1, "fetched_at", "open": [...] }`: every open issue at the last complete listing. |
| `<artifacts.plans>/<id>/receipts/<ITEM>.json` | `plan.py record` (read only here) | The receipt of a plan item; its `item` and `outcome.kind` decide whether the item counts as done. Read for the plans on the line only. |

The files live under the checkout's own `state_dir`, so each worktree has its own line; an absolute `state_dir`
is kept as given, so every checkout then shares them. After every scan the rendered text is compared with
`line.txt`'s contents (not with the atom, which starts null in each session) and rewritten on any difference,
so the `session.start` scan empties a `line.txt` another branch or an earlier session left. `line.json` follows
the same rule only after a scan that has a git-status snapshot; before the first snapshot an earlier session's
`line.json` stays as it was, and its branch stamp tells the widget it is stale. An absent file is not created
for an empty line.

## Known limitations

- A plan qualifies on any checkout whose merge base with its `base_branch` equals `base_commit`, which
  includes sibling branches cut from the same commit and the base branch itself until it moves. A branch
  rebased or merged forward onto its base loses the plan unless the plan's `branch` names it.
- A closed issue keeps showing for up to `todo.gh.max_age_hours` after its last answer; without a working
  `gh` (not installed, not authenticated, offline) it never hides.
- Nothing prunes the override of a deleted branch, and `/harness:working --clear` drops only the current
  branch's override: the segment stays until all its refs hide.
- Writes by other tools or processes, and a HEAD moved from another terminal, reach the line only at the
  next prompt or the next Bash, PowerShell, Edit, MultiEdit or Write call. The override file, catalog and
  open list are compared by mtime alone, so a rewrite that keeps the mtime is missed.
- Archive tags and `origin/<base>` are read from the local copies, never fetched: a plan archived on another
  clone shows until its tag is fetched, and a stale `origin/<base>` can miss the merge-base rule.
- The harness key defaults, the receipts folder name (`RECEIPTS_DIR`) and the done outcome kinds and statuses
  (`DONE_OUTCOMES`, `DONE_STATUSES`) are copied into `hooks/mirror.ts`; the contract test keeps them aligned in
  this repository, but an installed working-refs and harness at different versions can disagree on the receipts
  layout or on which outcomes and statuses count as done.

## Checks

```
claude plugin validate --strict <mod folder>
claude plugin test <mod folder>
```

The `state.set` hook on git-status's snapshot is not covered by `claude plugin test` (the test engine refuses
a test's own `$.state.set`); the tests move the snapshot beneath and let the next prompt read it. Check the
hook in a live session with git-status loaded: a `git switch` shows the other branch's line before the next
prompt.

## Loading

```
claude plugin marketplace add t968rs/operator-straps
claude plugin install git-status@operator-straps
claude plugin install working-refs@operator-straps
```

For development, a `CLAUDE_CODE_PLUGIN_DIRS` entry in the user-level `~/.claude/settings.json` `env` block (or
`claude --plugin-dir <folder>` for one session) loads the folder with hot reload and replaces the marketplace
copy of the same-named mod. The variable is one string, `;`-separated on Windows: append to its existing value
rather than replacing it.

`.claude-plugin/types/` is generated by the engine on load and git-ignored; `tsconfig.json` extends it.
