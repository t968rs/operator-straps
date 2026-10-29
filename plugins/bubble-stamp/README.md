# bubble-stamp

Keeps the bubble memo honest. The harness plugin's `bubble-memo` skill writes one memo per PR,
`PR_<N>_Bubbles.md`, listing the bubbled decisions as `Open`. When the developer answers a bubble, `pr-review`
records the outcome in the review JSON's `post_review_resolutions[]`. This mod copies that outcome into the memo,
so the memo shows what was decided without anyone editing it by hand.

Every hook fails open: an unreadable file, malformed JSON or memo, a missing project root or a refused host
call does nothing. No hook blocks or fails a tool call, a turn or a session start.

## Activation and configuration

The mod is active only in a project that holds `.claude/harness.json`, the harness plugin's per-project
configuration. Candidates follow the harness library's `project_root`: the git top level of the session cwd (a
linked worktree, or a subfolder of one), then `CLAUDE_PROJECT_DIR`, then the cwd itself; the first that holds
the file is the project root. Without the file every hook passes straight through.

It reads one key. An installed mod lives in its own plugin cache folder and cannot read the harness plugin's
`config/defaults.json`, so `hooks/config.ts` carries a copy of the default and merges the project's
`harness.json` over it (malformed JSON or a wrong-typed value keeps the default):

| Key | Default | Used for |
|-----|---------|----------|
| `artifacts.reviews` | `docs/PR_REVIEWS` | the folder holding the memos and the consolidated review JSON |

`tests/mods/test_bubble_stamp_config_mirror.py` fails when `defaults.json` changes the value without
`config.ts` following.

## Triggers

An active memo is one in `<artifacts.reviews>` named `PR_<N>_Bubbles.md` whose index still holds an `Open` row.
Each maps to its review JSON (the newest `<NNNN>_*.json` for N, zero-padded) and the mtime last seen. A memo
with no `Open` row, or without the memo anchors, is not active.

| Trigger | Does |
|---------|------|
| `session.start` | Lists `<artifacts.reviews>`, builds the active set, then checks it. |
| `tool.call` on `Bash` or `PowerShell` whose command names `pr_review.py` or `review_edit.py` | Lists the folder again (a memo may be new, a review JSON may have appeared), then checks. |
| `tool.call` on `Edit` or `Write` whose `file_path` is an active memo's review JSON | Checks. |
| `turn.complete` (the main conversation) | Checks. |

A check stats each active memo's review JSON and reads it only when the mtime moved. Any other tool call costs
one string test; an idle turn costs one `stat` per active memo. There is no poll timer.

## Stamp rule

For each id whose latest `post_review_resolutions[]` entry is `RESOLVED` or `CLOSED_NO_ACTION` and whose index
row is `Open`:

- index Status becomes `Decided`;
- the Decision cell reads `<STATUS> <date>: <evidence>`, the evidence verbatim on one line, `|` escaped;
- the Tracked in cell takes the first `#<n>` in the evidence; failing that the cell the developer filled;
  failing that the first 7 to 40 hex SHA (not the working-tree snapshot SHA); else `-`;
- the entry's `- **Decision:** open` line becomes `- **Decision:** <STATUS>, <date>. <evidence>`.

Nothing else in the file changes, and a second run changes nothing. A later entry of any other status reopens an
id, so `DOWNGRADED_TO_*` never stamps. The memo is re-read immediately before the write and stamped afresh when
it moved; it is written only when its text changed. A memo that exists but cannot be read is never overwritten;
a refused read or write is retried at the next trigger. A memo deleted while active (its read fails and a `stat`
fails too) leaves the active set. A refused folder listing keeps the active set as it was, and a memo whose
read the host refuses at a listing stays active; a memo that parsed and has no `Open` row, or lacks the anchors,
is dropped. One toast per check names the ids stamped.

`tests/mods/test_bubble_stamp_anchors_contract.py` pins the anchors the mod matches (table header, status words,
Decision line prefix, entry heading pattern) to `harness_lib/bubble_memo.py`.

## State

`$.state['bubble-stamp']` (contract: `types/index.d.ts`):

| Key | Meaning |
|-----|---------|
| `memos` | The active memos by file name: the memo path, its review JSON path (null while none exists) and the review JSON's mtime as last read. |

## Known limitations

- A memo created by a command that names neither `pr_review.py` nor `review_edit.py` is found at the next
  session start or the next such command, not the moment it appears.
- A stale `Open` row (an id renamed in the review JSON) keeps its memo active, at the cost of one `stat` per
  turn. The developer settles it by hand.
- Only the newest review JSON of a PR is watched; resolutions kept in an older one stay unstamped.
- A subagent's turn end is not a trigger; its shell and file tool calls are.
- Triggers are not coalesced: each matching shell call lists the folder and checks the memos, even when
  several arrive together (they run one after another).
- A review JSON is judged moved by its mtime alone; a rewrite that leaves the mtime unchanged (a coarse
  timestamp, a restored file) is not seen until the next write.
- Two sessions stamping the same memo at the same moment can lose one write: the second re-reads just before
  it writes, which narrows the window and does not close it.

## Checks

```
claude plugin validate --strict <mod folder>
claude plugin test <mod folder>
tsc -p <tsconfig>   # the tsconfig in the header of the engine's claude-code.d.ts, kept outside this folder
```

The plugin test sandbox cannot read repository files.

## Loading

Install from the `operator-straps` marketplace:

```
claude plugin marketplace add t968rs/operator-straps
claude plugin install bubble-stamp@operator-straps
```

For development, a `CLAUDE_CODE_PLUGIN_DIRS` entry in the user-level `~/.claude/settings.json` `env` block (or
`claude --plugin-dir <folder>` for one session) loads the folder with hot reload and replaces the marketplace
copy of the same-named mod. The variable is one string, `;`-separated on Windows: append to its existing value
rather than replacing it.

`.claude-plugin/types/` is generated by the engine on load and git-ignored; `tsconfig.json` extends it.
