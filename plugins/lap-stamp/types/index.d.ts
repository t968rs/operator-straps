/** Why a turn stopped, as `turn.complete` reports it. */
export type StopReason = 'answer' | 'aborted' | 'refusal' | 'error'

/**
 * One line of `<state_dir>/lap-stamp/laps.jsonl`: one turn. Keys are snake_case as on disk. Timestamps are ISO 8601
 * with the local offset. No paths, no prompt or answer text.
 */
export type LapRow = {
  /** Row version. */
  v: 1
  /** Session id. */
  session: string
  /** The host's turn id. */
  turn: string
  /** `prompt` when a lap press anchors the turn, else `wake`. */
  kind: 'prompt' | 'wake'
  /** What woke a `wake` turn when the host says (an origin kind), else null. */
  wake: string | null
  /** The lap press the turn used; null on a `wake` turn. */
  prompt_at: string | null
  start_at: string
  stop_at: string
  /** Newest prompt of the session when the turn stopped; null when the session had none. */
  last_prompt_at: string | null
  /** `stop_at - prompt_at` on a `prompt` turn, `stop_at - start_at` on a `wake` turn. */
  lap_ms: number
  /** `stop_at - last_prompt_at` on a `wake` turn with a prompt behind it, else null. */
  since_prompt_ms: number | null
  reason: StopReason
  /** FNV-1a 64 of the normalized answer; null for an empty answer. */
  answer_hash: string | null
  /** Length of the normalized answer; 0 for an empty answer. */
  answer_len: number
}

/** One turn's timing in epoch ms, before it becomes a row. */
export type Timing = {
  kind: 'prompt' | 'wake'
  wake: string | null
  promptAt: number | null
  startAt: number
  stopAt: number
  lastPromptAt: number | null
  lapMs: number
  sincePromptMs: number | null
}

/** A lap press waiting for a turn: its wall clock (epoch ms) and the `prompt.submit` origin kind. */
export type PendingPress = {
  at: number
  origin: string
}

/** The running main-loop turn. `attachedAt` is the lap press anchoring it (epoch ms), null while none. */
export type RunningTurn = {
  turnId: string
  startAt: number
  attachedAt: number | null
  wake: string | null
}

/** The clock the mod keeps between host events. Epoch ms throughout. */
export type ClockState = {
  pending: PendingPress[]
  running: RunningTurn | null
  /** Newest press a stopped or lost turn used, or the file recorded; a press at or before it never anchors another turn. Null when none. */
  consumedAt: number | null
  /** Newest press a turn used (or the file recorded); null when none. */
  lastPromptAt: number | null
  /** Origin kind of the latest non-press submission, kept as the wake reason of the next turn. */
  pendingWake: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'lap-stamp': {
      /** The session's rows, in file order. */
      rows: LapRow[]
      clock: ClockState
      /** Current session id; null until `session.start`, `session.attach` or the first recorded stop. */
      session: string | null
    }
  }
}
