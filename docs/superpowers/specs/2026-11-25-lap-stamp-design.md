# Lap stamp: an independent per-turn timer under each reply

Full design. Scope: a new TypeScript mod under `plugins/lap-stamp/` that times each main-conversation turn
with its own clocks, records every turn in a git-ignored JSONL file, and draws a right-aligned stamp under
the reply that turn produced, on the latest reply and on every older reply the terminal redraws.

## Intent

The terminal already closes a long turn with its own line (`Churned for 14m 30s · done 00:04`). The developer
wants a timer that does not depend on it: a stopwatch whose lap button is the developer's own message, read
off when the turn stops, stamped in the lower right corner of the reply, and kept on disk so the timings can be
read back later. Every turn gets one row, and a stamp whenever its reply can be matched with certainty,
including turns the developer did not start (a background agent finishing, a task notification, a resume after
compaction).

## Goals

- Every main-conversation turn that ends gets one JSONL row, and one stamp wherever a drawn block or line can be
  matched (D7, D8).
- A prompted turn's stamp shows the stop time and the lap: `14:32:07 · lap 3m 12s`.
- A turn with no lap press attached to it (a wake-up, D2) shows the stop time, the lap from the wake-up, and the
  time since the developer's last real prompt: `14:41:55 · lap 38s · since prompt 9m 48s`.
- Older replies keep their stamps when the terminal redraws them (scrolling, the ctrl+o transcript, a resumed
  session).
- The JSONL alone is enough to recompute every value a stamp shows.

## Non-goals

- Subagent, fork and teammate turns: no row, no stamp (`agentId` present on the turn event).
- The terminal's own `TurnDuration` line is left as drawn; the mod never shows or computes from that line's
  `durationMs` or `turn.complete`'s `durationMs`. D8 uses the former only as a match key. Disagreement between
  the two timers is information, not a bug.
- Remote surfaces (mobile, web): the stamp is a terminal feature. Another surface may draw it or not; nothing
  is built for one.
- No aggregate views, reports or charts over the JSONL.
- No config key in this round.

## Anti-goals

- A stamp under the wrong reply. A stamp never shows a value that is not this reply's own; an uncertain match
  draws nothing, except D7's candidate list, which always includes the copy's own entry.
- The stamp reaching the model: nothing is written into the reply text, the transcript or the prompt.
- A tracked log: the JSONL never enters git, and its rows carry no absolute or local paths.
- A slow transcript: the render hook does no file I/O.

## Approaches

How a redrawn reply finds its row. A render hook for `AssistantMessage` receives only the block's `text`,
`isFirstOfReply` and its viewport rows: no turn id, no time.

| | Matching | Trade-off |
|---|---|---|
| **A. Text fingerprint (picked)** | At `turn.complete` the row stores a hash of the normalized `answer`; the render hook hashes each block's normalized `text` and stamps the block whose hash matches a row | Nothing enters the model's context; works after a resume from the JSONL alone. The drawn text may differ from `answer` (the terminal hides a `<context>` block), so both sides are normalized the same way, and a miss draws nothing |
| B. Stamp inside the reply | Rewrite the answer (or the appended transcript row) to carry the stamp | Survives every redraw for free, but the stamp reaches the model each turn and may be echoed; the API does not state that a main-loop answer can be rewritten |
| C. Ordinal | nth drawn reply maps to nth row | The transcript draws only what is in view and redraws on scroll, so the count drifts. Dropped |

The developer picked A.

## Decided

**D1. Lap button.** The developer's own prompt is the lap button: a `prompt.submit` whose `origin.kind` is
`composer` (Enter at the terminal, typed or queued, slash commands and skills included) or the remote-control
bridge (the developer typing from another device) records `prompt_at` (wall clock, ms). Every other origin
(`task-notification`, a schedule, a peer session, a plugin's own submission, `unclassified`) is not a lap press;
its origin kind is kept as the pending wake reason. (The bridge and slash-command origin kinds are the design
session's reading of the host API, flagged for the developer; the builder confirms them on a live session.)

**D2. Turn start and kind.** `turn.start` on the main loop (`agentId` absent) records `start_at` and the
`turnId`. A lap press belongs to the turn it starts or is delivered into, the developer's literal rule ("the
last prompt hits the lap button"):
- a press made while no main-loop turn runs anchors the turn that starts next;
- a press made while turn N runs anchors N only when the host reports it was delivered into N (it then restarts
  N's lap); with no such report it stays pending and anchors the turn that starts after N stops;
- of several presses attached to one turn, the last one counts.

The mod keeps one consumed-press marker, the `prompt_at` of the last press a stopped turn used, so a pending
press never anchors two turns. A turn is `prompt` when a press is attached to it; otherwise it is `wake`.
Whether `prompt.submit` fires at Enter or at delivery for a queued composer prompt, and which host event
reports a mid-turn delivery, is for the builder to confirm on a live session; when it fires at delivery, a
press made during a running turn is a delivery into that turn.

**D3. Stop.** `turn.complete` on the main loop records `stop_at` and writes the row. Every reason writes a row
(`answer`, `aborted`, `refusal`, `error`); `reason` goes in the row.

**D4. Values.**
- `prompt` turn: `lap = stop_at - prompt_at`, `prompt_at` being the last press attached to the turn (D2), which
  may precede the previous turn's stop when the prompt was queued during it.
- `wake` turn: `lap = stop_at - start_at`; `since_prompt = stop_at - last_prompt_at`, where `last_prompt_at` is
  the newest `prompt_at` of the session (read back from the JSONL when the mod's memory holds none, so it
  survives `/compact` and a restart). No prompt ever in the session: `since_prompt` is null and not drawn.

**D5. The file.** One JSONL per checkout at `<state_dir>/lap-stamp/laps.jsonl` (`state_dir` defaults to
`.claude/state/harness`, so `.claude/state/harness/lap-stamp/laps.jsonl`, already git-ignored through
`.claude/state/`). Append-only, one row per turn. Row fields:
`v` (row version), `session` (session id), `turn` (turnId), `kind` (`prompt` | `wake`), `wake` (what woke the
turn when the host says, else null), `prompt_at`, `start_at`, `stop_at`, `last_prompt_at` (ISO 8601 with local
offset), `lap_ms`, `since_prompt_ms`, `reason`, `answer_hash`, `answer_len` (null and 0 for an empty answer,
D8). No paths, no prompt or answer text.

**D6. Stamp format.** Local time `HH:MM:SS`, then ` · lap <dur>`, then for a wake turn ` · since prompt <dur>`.
`<dur>` is `Ns` under a minute, `Mm Ss` under an hour, `Hh Mm` above. Faint (dim) text, right-aligned to the
transcript width, on its own row under the matched block.

**D7. Matching (approach A).** Normalize: drop any `<context>...</context>` span, unify line endings, trim.
Hash: a short stable hash (FNV-1a 64 or similar) of the normalized text, plus its length. The render hook
stamps a block when its hash and length match a row of the current session; it draws the row's own values,
never recomputed ones. When several rows of the session share a hash (identical replies), the hook cannot
tell which copy it draws, so every such copy gets one stamp listing all the candidates in file order:
`identical replies: 14:32:07 lap 3m 12s | 14:41:55 lap 38s` (a wake candidate adds its `since prompt`).
Nothing shown is false, and each copy's own entry is always among those listed. (The developer picked this
over no stamp and over a latest-row stamp with a marker.) Rows with an empty `answer` (D8) are never hash
candidates.

**D8. Turns with no final text.** An empty `answer` (an aborted turn, a turn of tool calls only) still writes a
row. Its stamp goes on that turn's `TurnDuration` line when the terminal draws one, right-aligned on the same
row; with no such line the row is recorded and nothing is drawn. The `TurnDuration` props carry no id or
text, so the line is matched by its `durationMs` against `stop_at - start_at` of every row of the session,
answered or not, within a tolerance (about 2 s); it is stamped only when exactly one row falls within the
tolerance and that row has an empty answer. That is a match key only: the stamp still shows the mod's own
values. Any other outcome (no row, two or more rows, or one answered row) draws nothing. An empty-answer row
stores a null `answer_hash` and `answer_len` 0. (The `TurnDuration` props are the design session's reading of
the host API; the builder confirms them on a live session.)

**D9. Memory, not disk, at render time.** The session's rows load into memory at `session.start` (and
`session.attach`), and each `turn.complete` adds its row to memory as it appends it. The render hook reads only
memory.

**D10. Fail open.** An unreadable or malformed file, a refused host call or a bad row draws nothing and blocks
nothing; malformed lines are skipped, never rewritten.

## Builder's calls (proposed, tunable)

- Mod name `lap-stamp`, layout like the other mods: `hooks/register.ts`, pure modules beside their tests,
  `types/index.d.ts`, `README.md`, `.claude-plugin/plugin.json`, a marketplace entry.
- Activation like `bubble-stamp`: active only where `.claude/harness.json` exists. `state_dir` is mirrored in
  the mod and pinned against `plugins/harness/config/defaults.json` by `tests/mods/test_lap_stamp_*` (the
  `session-bookmark` pattern).
- Which block in a multi-block reply carries the stamp: the block whose text is the `answer` (the reply's last
  text block); earlier text blocks of the same reply never match because their text is not the answer.
- `wake` value: the `origin.kind` of the newest non-lap `prompt.submit` since the previous main-loop stop
  (`task-notification`, `scheduled-trigger`, `peer`, ...), else null (a post-compaction resume or a
  continuation with no submission).
- The latest reply's stamp appears once its row exists: the render hook reads the rows from `$.state`, and a
  state change redraws it.
- The ctrl+o view (`isExpanded`) draws the stamp the same way.
- No rotation of the JSONL; rows are about 300 bytes.
- An identical-replies stamp too wide for the transcript wraps onto further right-aligned rows rather than
  dropping candidates, since a dropped candidate could be the copy's own.

## Left to the builder

- Confirming on a live session that the drawn `AssistantMessage.text` of the last block normalizes to the
  same text as `turn.complete.answer`, and adjusting the normalization when it does not (this is the one
  place approach A can fail silently).
- Whether a resumed session (`--resume`, `/resume`) keeps its session id; if not, how its rows are found.
- Exact right-alignment within the host's `Box`/`Text` layout.
- Tests: the pure modules (normalize, hash, format, row build, kind decision, hash lookup with the candidate list, the TurnDuration tolerance match) under the mod's
  test runner; the mirror test under `tests/mods/`.
- Release notes, plugin version and marketplace entry per the repo's release rules.
- Repo-wide docs for a tenth mod: the mod count and list in `CLAUDE.md` and `README.md` (and the mod in
  `README.md`'s layout), a `lap-stamp` line in `CLAUDE.md`'s config-key mirror rule naming the file that mirrors
  `state_dir` and its `tests/mods/test_lap_stamp_*` test, the `CHANGELOG.md` [Unreleased] entry and the
  `docs/RELEASES/v<X.Y.Z>.md` file.
