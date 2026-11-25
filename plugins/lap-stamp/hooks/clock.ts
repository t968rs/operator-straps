/**
 * The lap clock: pure reducers over `ClockState`, one per host event the mod reads. A lap press is the
 * developer's own `prompt.submit` (D1); it anchors the turn it starts or is delivered into, the last press
 * counting (D2); a stopped turn yields its `Timing` (D4). No `$`, no I/O: epoch ms in, new state out.
 */

import type { ClockState, PendingPress, RunningTurn, Timing } from '../types'

/** `prompt.submit` origin kinds that press the lap button (V1). Every other kind is a wake reason. */
export const LAP_PRESS_ORIGINS = ['composer', 'bridge'] as const

/** A fresh clock: nothing pending, no turn running, no prompt known. */
export const EMPTY_CLOCK: ClockState = {
  pending: [],
  running: null,
  consumedAt: null,
  lastPromptAt: null,
  pendingWake: null,
}

/** A `prompt.submit` from one of these origin kinds is a lap press. */
export function isLapPress(originKind: string): boolean {
  return (LAP_PRESS_ORIGINS as readonly string[]).includes(originKind)
}

/** The later of two optional epoch ms values. */
function newest(a: number | null, b: number | null): number | null {
  if (a === null) return b
  if (b === null) return a
  return Math.max(a, b)
}

/** A press still able to anchor a turn: made after the consumed-press marker. */
function isFresh(p: PendingPress, consumedAt: number | null): boolean {
  return consumedAt === null || p.at > consumedAt
}

/** The newest fresh pending press made at or before `by`; null when none. */
function newestPress(state: ClockState, by: number): PendingPress | null {
  let best: PendingPress | null = null
  for (const p of state.pending) {
    if (p.at <= by && isFresh(p, state.consumedAt) && (best === null || p.at >= best.at)) best = p
  }
  return best
}

/** Pending presses newer than `after` (a used or consumed press); all of them when `after` is null. */
function keepAfter(pending: readonly PendingPress[], after: number | null): PendingPress[] {
  return pending.filter(p => after === null || p.at > after)
}

/**
 * A `prompt.submit`: a lap press joins the pending queue; any other origin becomes the wake reason of the
 * next turn that starts without a press.
 */
export function submitted(state: ClockState, e: { originKind: string; at: number }): ClockState {
  if (!isLapPress(e.originKind)) return { ...state, pendingWake: e.originKind }
  return { ...state, pending: [...state.pending, { at: e.at, origin: e.originKind }] }
}

/**
 * The host reports a lap press delivered into the running turn at `at`: the newest fresh press made by then
 * attaches to that turn and restarts its lap from the press's own time (D2). Older presses drop; presses
 * made after `at` stay pending. No running turn or no such press changes nothing.
 */
export function delivered(state: ClockState, at: number): ClockState {
  const run = state.running
  if (run === null) return state
  const p = newestPress(state, at)
  if (p === null || (run.attachedAt !== null && p.at <= run.attachedAt)) return state
  return {
    ...state,
    running: { ...run, attachedAt: p.at },
    pending: keepAfter(state.pending, p.at),
  }
}

/**
 * A turn still running when another starts lost its `turn.complete`: its attached press still counts as used,
 * so it raises the consumed-press marker and the session's newest used press.
 */
function foldLostRun(state: ClockState): ClockState {
  const used = state.running === null ? null : state.running.attachedAt
  if (used === null) return state
  return {
    ...state,
    consumedAt: newest(state.consumedAt, used),
    lastPromptAt: newest(state.lastPromptAt, used),
  }
}

/**
 * A main-loop `turn.start`: the newest fresh pending press attaches (a `prompt` turn), else the turn is a
 * `wake` carrying the pending wake reason. The wake reason clears either way; stale presses drop. A turn
 * still running is dropped without a timing, its press folded in as used.
 */
export function started(prev: ClockState, turnId: string, at: number): ClockState {
  const state = foldLostRun(prev)
  const p = newestPress(state, Number.POSITIVE_INFINITY)
  const running: RunningTurn = {
    turnId,
    startAt: at,
    attachedAt: p === null ? null : p.at,
    wake: p === null ? state.pendingWake : null,
  }
  const cut = p === null ? state.consumedAt : p.at
  return { ...state, running, pending: keepAfter(state.pending, cut), pendingWake: null }
}

/**
 * The values a stopped turn records (D4). `lastPromptAt` is the session's newest used press after this stop.
 * A wall clock that went backwards clamps a duration to 0.
 */
function timingOf(run: RunningTurn, stopAt: number, lastPromptAt: number | null): Timing {
  const promptAt = run.attachedAt
  const isPrompt = promptAt !== null
  return {
    kind: isPrompt ? 'prompt' : 'wake',
    wake: isPrompt ? null : run.wake,
    promptAt,
    startAt: run.startAt,
    stopAt,
    lastPromptAt,
    lapMs: Math.max(0, stopAt - (isPrompt ? promptAt : run.startAt)),
    sincePromptMs: isPrompt || lastPromptAt === null ? null : Math.max(0, stopAt - lastPromptAt),
  }
}

/**
 * A main-loop `turn.complete`: the running turn's timing, its press marked consumed and recorded as the
 * session's newest prompt. A stop for no running turn, or for another turn id, returns the state unchanged
 * and a null timing.
 */
export function stopped(
  state: ClockState,
  turnId: string,
  at: number,
): { state: ClockState; timing: Timing | null } {
  const run = state.running
  if (run === null || run.turnId !== turnId) return { state, timing: null }
  const consumedAt = newest(state.consumedAt, run.attachedAt)
  const lastPromptAt = newest(state.lastPromptAt, run.attachedAt)
  return {
    state: { ...state, running: null, consumedAt, lastPromptAt, pending: keepAfter(state.pending, consumedAt) },
    timing: timingOf(run, at, lastPromptAt),
  }
}

/**
 * Seeds the clock with the newest `prompt_at` read back from the laps file (D4), so `since prompt` survives
 * `/compact` and a restart. That press was used by a stopped turn, so it also moves the consumed-press marker.
 */
export function seedLastPrompt(state: ClockState, at: number | null): ClockState {
  if (at === null) return state
  const consumedAt = newest(state.consumedAt, at)
  return {
    ...state,
    lastPromptAt: newest(state.lastPromptAt, at),
    consumedAt,
    pending: keepAfter(state.pending, consumedAt),
  }
}
