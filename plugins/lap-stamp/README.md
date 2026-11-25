# lap-stamp

An independent timer for every turn of the main conversation. The terminal already closes a long turn with its
own line (`Churned for 14m 30s`); this mod keeps its own clocks, stamps the result in the lower right corner
under the reply, and records every turn in a git-ignored JSONL file so the timings can be read back later.

Every hook fails open: an unreadable or malformed file, a refused host call or a bad row draws nothing and
blocks nothing. Malformed lines of the laps file are skipped, never rewritten.

## What the stamp shows

Faint (dim) text, right-aligned to the transcript width. A reply block's stamp sits on its own row under the
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
so the file is `.claude/state/harness/lap-stamp/laps.jsonl`, git-ignored through `.claude/state/`. Append-only,
one row (about 300 bytes) per turn, no rotation.

| Field | Meaning |
|-------|---------|
| `v` | Row version, `1`. |
| `session` | Session id. |
| `turn` | The host's turn id. |
| `kind` | `prompt` or `wake`. |
| `wake` | What woke the turn (the origin kind of the newest non-lap submission), else null. |
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
| `session.start`, `session.attach` | Loads the session's rows from the laps file into memory. |
| `prompt.submit` | Records a lap press, or the wake reason of a non-lap submission. |
| `turn.start`, `turn.complete` (the main conversation) | Records the start; at the stop, builds the row, appends it and adds it to memory. |
| Render of an assistant reply block | Stamps the block whose fingerprint matches a row. |
| Render of the `TurnDuration` line | Stamps it when exactly one empty-answer row matches its duration. |

## State

`$.state['lap-stamp']` (contract: `types/index.d.ts`) holds the session's rows and the pending press, so a state
change redraws the latest reply once its row exists.

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
