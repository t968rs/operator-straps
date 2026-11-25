# Serialize TODO catalog writes: a catalog lock, a scratch inbox and a consolidating mod

Issue #277 (todo-udx4). Branch `1159-FEAT-serialize-catalog-writes`.

## Intent

A session that needs six TODO items runs six `harness:todo-editor` agents one at a time, because
`todo_sync.py` has no write lock and parallel `add` runs race on `RepoToDo.json`. Each write is atomic
(`write_atomic`, `plugins/harness/lib/harness_lib/todo_sync/report.py:89-100`), but two read-modify-write
runs (`reshape.py:543-551`, `retire.py:180-187`) can overlap, and the later one silently drops the earlier
one's item.

The developer wants:

1. **Parallel adds.** Several agents draft items at once; none of them reads or writes the whole catalog.
2. **Consolidation outside the main session.** A mod writes the drafted entries into the catalog as the
   agents return, so the main session spends almost no context on it.
3. **Safe writes.** No writer, script, mod or agent, can lose another writer's change.

## Goals

- A **catalog lock** in `harness_lib` that every `todo_sync.py` catalog write holds, plus a **lease** form
  an agent holds for a whole retire, split or refresh run.
- A **`scratch_folder` config key** (default `docs/_scratch/`, issue #277 goal 2); TODO agents write add
  specs to `<scratch_folder>/todo-inbox/`, one file per drafted item.
- **`todo_sync.py inbox put`**: validates one add spec and writes it to the inbox atomically. With
  `--file-issue` it files the GitHub issue first and stores `issue` and `url` in the spec.
- **`todo_sync.py add --inbox`**: under the lock, adds every inbox spec to the catalog in one write, renders
  the snapshot, runs the catalog check, deletes the accepted files, keeps rejected ones with their reason,
  and prints one summary line.
- **The `todo-watch` mod** runs `add --inbox` when a `harness:todo-editor` agent returns, one run in flight
  with at most one owed rerun, and hands the summary line to the main session.

## Non-goals

- Parallel retire, split or refresh agents. They stay one at a time, serialized by the lease the
  todo-editor takes for the run (Decided, item 13).
- Typed script operations for the agent's prose edits (close candidates, tracker notes, rewording).
  Considered as "Layer 2" and dropped: the inbox removes adds from the hand-edit path, and the lease
  covers the rest.
- Removing or editing a single bookmark note (todo-545g). `add_note.py` can adopt the lock later; it is not
  part of this branch.
- Locks for the plan JSON, `DesignEvolution.json` or review JSON.

## Anti-goals

- A TypeScript port of id drawing, ranking or scoring. The mod runs `todo_sync.py`; it never writes
  `RepoToDo.json` itself.
- An inbox file the consolidator can read half-written.
- A failed consolidation that loses a drafted item. A rejected spec stays on disk with its reason.
- Filing a GitHub issue from a hook. The agent files it (`inbox put --file-issue`), where a failure is
  visible and retried in the agent's own run.
- A harness that needs the mod. Without `todo-watch`, the inbox still drains (see Decided, item 7).

## Constraints

- Python 3.11, `Optional` / `Union`, functions under 50 lines, no first or second person in comments.
- Standard library only for the lock (no `filelock` dependency). The same-host pid liveness check uses
  `os.kill(pid, 0)` on POSIX only: on Windows Python maps it to `TerminateProcess`, so Windows checks through
  `ctypes` (`OpenProcess` plus `GetExitCodeProcess`).
- The lock protocol is readable from TypeScript (`fs` open with `wx`), even though the mod does not take the
  lock itself in this design.
- A new config key touches the four places of the project CLAUDE.md checklist, plus the `todo-watch` mirror
  in `plugins/todo-watch/hooks/config.ts` (`tests/mods/test_todo_watch_config_mirror.py`).
- Plugins stay generic; the inbox and lock files live under the consuming project.

## Approaches

| | Approach | Trade-off |
|---|---|---|
| A | **Lock only.** Agents run `todo_sync.py add` directly in parallel; each run holds the lock. | Smallest. The agent still reads and hand-edits the catalog during its run, so its prose edits are unprotected, and every agent's reply carries catalog context. |
| B | **Inbox + mod + lock (picked).** Agents write specs to the inbox; the mod consolidates under the lock; retire, split and refresh hold a lease. | Meets every #277 goal. Adds a config key, two subcommands and mod work; the agent no longer knows the new item's id when it replies. |
| C | **B plus typed operations** for every prose edit (Layer 2). | Allows parallel retire and split and kills hand edits entirely; roughly five more subcommands for little gain while those runs stay rare. |

The developer picked B and dropped Layer 2.

## Decided

1. **Inbox is the primary add path** (developer). `harness:add-todo` and `harness:sync-gh-todo` agents never
   write the catalog.
2. **The agent files the issue; the mod writes the data** (developer). `inbox put --file-issue` reuses
   `issues.file_issue` and `issues.issue_body` (`todo_sync/issues.py:154`, `:166`).
3. **Lock protocol: an `O_CREAT | O_EXCL` lock file** under `<state_dir>/locks/`, named after the catalog's
   repo-relative path. The body records pid, host, owner, mode (`write` or `lease`) and the acquire time.
   A waiter retries with jitter up to a timeout (default 10 s) and then refuses, naming the holder. *(My
   call: readable from Node, survives as a visible file for diagnosis; OS byte-range locks are not
   reachable from a mod.)*
4. **Staleness.** A `write` lock is stale when its pid is dead on the same host or it is older than 60 s
   (holds last milliseconds). A `lease` is stale only by age (default 30 min), since the process that
   acquired it has exited; `todo_sync.py lease break` is the developer's manual override. *(My call.)*
5. **Lease.** `todo_sync.py lease acquire --owner <text>` prints a token; the holder passes `--lease
   <token>` to its own `retire`, `split` and `refresh` runs, which proceed under it; every other writer,
   the mod included, waits or refuses. `lease release <token>` ends it. *(My call.)*
6. **Release recounts.** `lease release` reruns the catalog recount, so a hand-appended close candidate no
   longer leaves `counts.close_candidates` short (the T9 error seen twice on 2026-11-13). *(My call.)*
7. **Drain fallback.** After the agent returns, the add-todo and sync-gh-todo skills run `todo_sync.py add
   --inbox` once. With the mod active it prints `inbox: empty`; without it, it does the consolidation. The
   lock makes the two consolidators safe. *(My call: the mod is an optional plugin, and the harness must
   not depend on it.)*
8. **Per-file acceptance.** `add --inbox` validates each inbox file on a working copy, oldest first; a file
   that fails (for example `issue #N is already in the catalog`, `reshape.py:256`, when two agents drafted
   the same issue) is renamed `<name>.rejected.json` with a `<name>.reason.txt` beside it; the accepted
   ones land in one catalog write. *(My call.)*
9. **`write_atomic` retries `os.replace`** a few times on `PermissionError`, which Windows raises while
   another process (an IDE indexer, a reader) holds the target open. *(My call.)*
10. **The mod drains at `session.start` too**, so files left by a crashed session are not stranded. *(My
    call.)*
11. **`add --inbox` renders and checks.** Inside the same lock hold it renders the snapshot and runs the
    catalog check in-process, and the summary line carries the check result. The mod runs one process per
    drain, and the agent's own `TS render` / `TS check` finish steps leave the add and sync paths, since the
    agent returns before its item lands (rule T2, `rules_todo.py:78-94`, would warn on a stale render). *(My
    call.)*
12. **One inbox file per item** (issue #277 goal 3: "todo agents write a single todo entry to scratch").
    sync-gh-todo stays one agent per run reading the one `untracked.json`, and writes one file per issue, so
    a duplicate rejects only its own item; per-file acceptance is per-item acceptance. Fanning sync out to
    several agents is not part of this branch.
13. **The agent holds the lease.** The todo-editor's retire, split and refresh runs start with `lease acquire`
    and end with `lease release` before the reply, so the mod's drain on that return finds the lock free and
    clears any adds queued meanwhile. `retire`, `split` and `refresh` without `--lease` still run under a
    plain write lock (a developer at the CLI); the serialization of agents comes from the agent text, not from
    a refusal. *(My call.)*
14. **`scratch_folder` is a top-level harness key, independent of `artifacts.scratch`** (issue #277 goal 2
    names it a `harness` config key with default `docs/_scratch/`). `artifacts.scratch` keeps its own default
    and meaning. `<scratch_folder>/todo-inbox/` joins `history_paths` (`harness_lib/history.py:20-25`) and the
    default exclusions (`harness_lib/default_exclusions.py:29-40`), so a pending inbox file is neither a
    retired-id reference nor a dirty-tree failure. *(My call for the two lists.)*
15. **Timeouts are module constants, not config keys**: the 10 s wait, the 60 s write-lock staleness and
    the 30 min lease age. They tune the protocol, not a project, and no driver reads them from a project.
    *(My call; each becomes a key later without breaking anything.)*
16. **`migrate-ids` takes a lease for its own run** (acquired and released inside the command), since its
    `git grep` and file rewrites can outlast the 60 s write-lock staleness. `init` takes the write lock.
    Every catalog-writing subcommand then holds the lock in some mode, which the tests assert. *(My call.)*
17. **Mod trigger (spike, 2026-11-13).** The mod wraps `on('tool.call', { tool: 'Agent' })` for
    `subagent_type === 'harness:todo-editor'`, as `agent-watcher` does (`tracker.ts:549-569`):
    - **Foreground return** (result `status: 'completed'`): drain right after `next(e)` and append the summary
      line to the result's `context`.
    - **Background launch** (result `status: 'async_launched'` with `agentId`, `tracker.ts:396-397`): record
      the `agentId`. Its loop end fires `turn.complete` with that `agentId` (`tracker.ts:589-591`); the mod
      starts the drain there. The completion notification then enters the main session through
      `prompt.submit` with `e.origin.kind === 'task-notification'` (engine types, `PromptOrigin`); the mod
      awaits the in-flight drain (bounded by the drain timeout) and attaches the pending summary line to that
      prompt's `context`, the way the `TODO_SYNC` line is attached today (`todo-watch/hooks/checks.ts:571-577`).
      A summary not delivered there rides the next `prompt.submit`.
    - The `turn.complete` hook joins todo-watch's existing one (`checks.ts:560-566`), which today returns early
      for a subagent loop. *(Spike result; the hook placement is the builder's.)*

## Left to the builder

- Inbox file naming (UTC stamp plus a random suffix is enough) and the summary line's exact wording.
- Whether `inbox put` runs a full `add` dry run against the current catalog or only schema validation.
  A full dry run catches most rejections while the agent can still fix them.
- The todo-editor, add-todo and sync-gh-todo text: the reply no longer names the new id; it says the item is
  queued, and the mod's or the fallback's summary line names it. The todo-editor's retire, split and refresh
  text gains the lease acquire and release steps (Decided, item 13); the todo-edit skill text is unchanged.
- Tests: the lock (contention, stale write lock, stale lease, token passthrough), `inbox put`,
  `add --inbox` (accept, reject, mixed), the config key, the mod's single-flight run and its mirror.
- The plugin version bumps and the release notes file.
