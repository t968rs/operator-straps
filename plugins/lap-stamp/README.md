# lap-stamp

An independent timer for every turn of the main conversation. The terminal already closes a long turn with its
own line (`Churned for 14m 30s`); this mod keeps its own clocks, stamps the result in the lower right corner
under the reply, and records every turn in a git-ignored JSONL file so the timings can be read back later.

Every hook fails open: an unreadable or malformed file, a refused host call or a bad row draws nothing and
blocks nothing. Malformed lines of the laps file are skipped, never rewritten.

## What the stamp shows

Rust-colored text (`#B7410E`, `STAMP_COLOR` in `hooks/render.tsx`), right-aligned to the transcript width. A reply block's stamp sits on its own row under the
block; a `TurnDuration` stamp sits on the same row as that line. The time is the local stop time, `HH:MM:SS`.

| Turn | Stamp |
|------|-------|
| `prompt`: the developer's message started it | `14:32:07 · lap 3m 12s` |
| `wake`: no developer prompt attached (a background agent finished, a task notification, a resume after compaction) | `14:41:55 · lap 38s · since prompt 9m 48s` |

A duration is `Ns` under a minute, `Mm Ss` under an hour and `Hh Mm` above. A wake turn with no prompt ever in
the session omits the `since prompt` part. The stamp shows the values stored in the row, never recomputed ones.

Older replies keep their stamps when the terminal redraws them (scrolling, the ctrl+o transcript, a resumed
session); the latest reply is stamped once its row exists.

Subagent, fork and teammate turns get no row and no stamp. The terminal's own `TurnDuration` line is left as
drawn, and the two timers may disagree: that is information, not a bug.

## Lap rules

- **Lap button.** The developer's own prompt: a `prompt.submit` whose origin is the terminal composer (typed or
  queued, slash commands and skills included) or the remote-control bridge. Every other origin (a task
  notification, a schedule, a peer session, a plugin's own submission) is not a lap press; its origin kind is
  kept as the turn's wake reason.
- **Turn start and kind.** `turn.start` on the main loop records the start. A press made while no turn runs
  anchors the turn that starts next; a press made while a turn runs anchors that turn only when the host reports
  it was delivered into it, else it anchors the turn after. Of several presses on one turn, the last counts. A
  press never anchors two turns.
- **Stop.** `turn.complete` on the main loop writes the row, for every reason (`answer`, `aborted`, `refusal`,
  `error`).
- **Values.** A `prompt` turn's lap runs from the press to the stop, so it may begin before the previous turn
  stopped when the prompt was queued. A `wake` turn's lap runs from its start to its stop, and `since prompt`
  runs from the newest prompt of the session, read back from the file after `/compact` or a restart.

## Matching a reply to its row

The render hook receives only a block's text, no turn id and no time. At `turn.complete` the row stores a hash
(FNV-1a 64, 16 lower-case hex chars) and the length of the normalized answer; at render each block is normalized
the same way (a `<context>...</context>` span dropped, line endings unified, trimmed) and stamped when hash and
length match a row of the current session. Only the block whose text is the answer, the reply's last text block,
can match.

- **Identical replies.** Several rows can share a hash, so every such copy gets one stamp listing all the
  candidates in file order, for example
  `identical replies: 14:32:07 lap 3m 12s | 14:41:55 lap 38s · since prompt 9m 48s` (a wake candidate adds its
  `since prompt`). Each copy's own entry is always among those listed; a stamp too wide wraps onto further
  right-aligned rows.
- **Turns with no final text.** An aborted turn or a turn of tool calls only still writes a row, with a null
  `answer_hash` and `answer_len` 0. Its stamp goes on that turn's `TurnDuration` line, matched by the line's
  duration against `stop_at - start_at` within 2000 ms, and only when exactly one row of the session falls in
  the window and it has an empty answer. Any other outcome draws nothing.
- **No file I/O at render.** The session's rows load into memory at `session.start` and `session.attach`, each
  `turn.complete` adds its row as it appends it, and the render hook reads only memory.

A stamp is never drawn on an uncertain match, and nothing is written into the reply text, the transcript or
the prompt.

## The laps file

One JSONL per checkout at `<state_dir>/lap-stamp/laps.jsonl`; `state_dir` defaults to `.claude/state/harness`,
so the file is `.claude/state/harness/lap-stamp/laps.jsonl`, git-ignored through `.claude/state/`. One row (about
300 bytes) per turn, no rotation. Rows are only ever added, but the host offers no append call: each stop reads
the whole file and writes it back with one more line, the existing lines kept verbatim. A file that exists but
cannot be read is left untouched, and that turn's row stays in memory only, until the session ends. The mod
assumes one writer per checkout; see Known limitations.

| Field | Meaning |
|-------|---------|
| `v` | Row version, `1`. |
| `session` | Session id. |
| `turn` | The host's turn id. |
| `kind` | `prompt` or `wake`. |
| `wake` | What woke the turn (the origin kind of the newest non-lap submission since the previous main-loop stop), else null. |
| `prompt_at` | The lap press, ISO 8601 with local offset; null on a wake turn. |
| `start_at`, `stop_at` | The turn's start and stop, ISO 8601 with local offset. |
| `last_prompt_at` | The newest `prompt_at` of the session, else null. |
| `lap_ms` | The lap in milliseconds. |
| `since_prompt_ms` | Milliseconds since the last prompt on a wake turn, else null. |
| `reason` | `answer`, `aborted`, `refusal` or `error`. |
| `answer_hash` | The answer's fingerprint hash; null for an empty answer. |
| `answer_len` | The normalized answer's length; 0 for an empty answer. |

The rows hold no absolute or local paths and no prompt or answer text, and the file alone is enough to
recompute every value a stamp shows.

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
| `state_dir` | `.claude/state/harness` | the folder holding `lap-stamp/laps.jsonl` |

`tests/mods/test_lap_stamp_config_mirror.py` fails when `defaults.json` changes the value without `config.ts`
following. The mod adds no key of its own.

## Hooks it registers

`hooks/hooks.json` loads `./register.ts`, which wires:

| Hook | Does |
|------|------|
| `session.start`, `session.attach` | Loads the session's rows from the laps file into memory; the first load in an active project also registers `/lap-times`, and a load that finds no project lets it pass on until the next load in a project registers it again. |
| `prompt.submit` | Records a lap press, or the wake reason of a non-lap submission. |
| `session.append` (door `delivery`, the main loop) | A lap press delivered into the running turn attaches to that turn and restarts its lap (D2); a `queue` row is not a delivery. |
| `turn.start`, `turn.complete` (the main conversation) | Records the start; at the stop, builds the row, appends it and adds it to memory. |
| Render of an assistant reply block | Stamps the block whose fingerprint matches a row. |
| Render of the `TurnDuration` line | Stamps it when exactly one empty-answer row matches its duration. |
| `command.run` (`/lap-times`) | Prints the lap times table (below); `/lap-times` is registered at the first `session.start` or `session.attach` in an active project. |

## /lap-times

`/lap-times [all] [N]` prints the laps as a markdown table under one summary line (scope, turn count, total lap,
longest lap). With no argument it shows the live session's turns: from memory, or from the laps file after a
`/clear` or a resume that raised no `session.start` (memory still holds the previous session then). `all` reads
every session from the laps file plus any turn whose write was refused, adds a date and a short session id, and
its summary names the session count. `N` keeps the newest
N rows (default 50); the `#` column still numbers each row's place in the whole list, and the summary adds
`last N shown` when rows are trimmed. Anything else prints the usage line. An empty scope prints a
`no turns recorded` line, and a laps file that does not read where the command needs it prints a one-line
failure.

```
lap-stamp · this session · 2 turns · lap total 1m 15s · longest 1m 10s

| # | Stop     | Kind   |    Lap | Since prompt | Wake              | Stop reason |
|--:|----------|--------|-------:|-------------:|-------------------|-------------|
| 1 | 14:00:05 | prompt |     5s |              |                   | answer      |
| 2 | 14:01:15 | wake   | 1m 10s |       1m 15s | task-notification | answer      |
```

Every cell is padded to its column's width and durations are right-aligned, so the table lines up as plain text
and still renders as markdown. Every line fits the terminal width at the moment the command runs when the stop
time and the lap alone fit: columns go least useful first (stop reason, wake, session, `#`, date, kind, since
prompt) until the table fits or only the stop time and the lap remain, and those two are never dropped, even
past the width. The summary line is cut with an ellipsis. The command answers without a model turn,
and its output stays out of the model's requests.

## State

`$.state['lap-stamp']` (contract: `types/index.d.ts`) holds three keys: `rows` (the session's rows), `clock` (the
lap clock: pending presses, the running turn, the consumed-press marker, the last prompt and the pending wake
reason) and `session` (the current session id). Render reads only `rows` and `session`, so a state change
redraws the latest reply once its row exists.

## Known limitations

These are readings of the host API that only a live session confirms, so each may differ from the host:

- The origin kinds that count as a lap press (the composer and the remote-control bridge) and the slash-command
  origin are read from the host API, not observed.
- Whether `prompt.submit` fires at Enter or at delivery for a queued composer prompt, and which event reports a
  mid-turn delivery, is unconfirmed; the lap rules above hold either way, but a press made during a running turn
  may anchor the next turn instead of this one.
- The drawn block text normalizes to the same text as the turn's `answer` only as far as the terminal's own
  rewriting is known (it hides a `<context>` block); any other rewrite makes that reply draw no stamp.
- The `TurnDuration` props (a duration and no id or text) are read from the host API, not observed.
- Whether a resumed session (`--resume`, `/resume`) keeps its session id decides whether its older rows are found.
- Identical replies list every candidate instead of picking one.
- Remote surfaces (mobile, web) are not covered: the stamp is a terminal feature.

These follow from the file write, not from a host reading:

- **Concurrent sessions can lose a row.** The laps file is shared by every session in the checkout, and the
  mod's serial queue orders writes only inside one session. When two sessions stop close together, both read the
  same text and the later write drops the other's row; the losing session keeps its row in memory, so its stamp
  still draws until that session ends, but the file never gets it back.
- **Each stop costs the whole file.** Nothing prunes the file, so every stop rereads and rewrites all history,
  in 3 MiB ranged reads once the file passes the host's 4 MiB answer. The write is a single call; if the host
  caps a write the way it caps a read, every later row stays memory-only, silently (fail open).

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
claude plugin install lap-stamp@operator-straps
```

For development, a `CLAUDE_CODE_PLUGIN_DIRS` entry in the user-level `~/.claude/settings.json` `env` block (or
`claude --plugin-dir <folder>` for one session) loads the folder with hot reload and replaces the marketplace
copy of the same-named mod. The variable is one string, `;`-separated on Windows: append to its existing value
rather than replacing it.

`.claude-plugin/types/` is generated by the engine on load and git-ignored; `tsconfig.json` extends it.
