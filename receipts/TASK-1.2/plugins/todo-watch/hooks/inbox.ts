import type { EngineInterface, ProcessRunResult, Timer } from 'claude-code'

import type { Runner } from './checks'

/**
 * The TODO inbox drain: `todo_sync.py add --inbox` adds every item a `harness:todo-editor` agent queued under
 * `<scratch_folder>/todo-inbox` to the catalog in one write. One drain runs at a time, with at most one owed
 * rerun (as ./checks paces its check runs); each drain's one-line outcome waits here as a pending summary until
 * a tool result or a prompt takes it to the main session. The triggers live in ./checks (a todo-editor's
 * Agent result, any subagent's turn end with an item queued, the prompt) and ./register (the session start);
 * hook waits are capped by the hook's budget (`waitCapMs`). This module imports nothing
 * from ./checks at run time, so the host (runner lookup, check refresh) comes in as `DrainHost`. Functions
 * taking `$` are function declarations: the engine follows `$` past an import only into one.
 */

type Dollar = EngineInterface

/** Longest a drain may take before it is killed and reported as failed, in milliseconds. */
export const DRAIN_TIMEOUT_MS = 60_000
/** The agent whose return drains the inbox. */
export const TODO_EDITOR = 'harness:todo-editor'
/** Prefix of the driver's one stdout line. */
export const INBOX_PREFIX = 'inbox: '
/** The driver's line when nothing was queued: no summary. */
export const INBOX_EMPTY = 'inbox: empty'
/** Suffix the driver gives a refused inbox file; such a file is never drained again. */
export const REJECTED_SUFFIX = '.rejected.json'
/** Hook budget kept back when a hook waits for a drain, so it returns before the engine gives up on it. */
export const BUDGET_MARGIN_MS = 1_000

/** What a drain needs from ./checks: the runner, looked up afresh, and a check refresh after a drain. */
export type DrainHost = { runner: () => Promise<Runner | undefined>; refresh: () => void }

const noop = (): undefined => undefined

// ---------------------------------------------------------------------------
// Pure

/** `inbox: drain failed: <reason>`. */
export const failedSummary = (reason: string): string => `${INBOX_PREFIX}drain failed: ${reason}`

/** The last non-blank line of a text, trimmed; undefined when there is none. */
export const lastLine = (text: string): string | undefined =>
  text.split(/\r?\n/).map(l => l.trim()).filter(l => l !== '').pop()

/**
 * A finished drain's summary: on exit 0 the stdout line starting `inbox: ` (none for `inbox: empty` or no
 * such line); on any other exit `inbox: drain failed: <last stderr line>` (the exit code when stderr is blank).
 */
export const drainSummary = (ran: ProcessRunResult): string | undefined => {
  if (ran.exitCode !== 0) return failedSummary(lastLine(ran.stderr) ?? `exit ${ran.exitCode}`)
  const line = ran.stdout.split(/\r?\n/).map(l => l.trim()).find(l => l.startsWith(INBOX_PREFIX))
  return line === undefined || line === INBOX_EMPTY ? undefined : line
}

/** The summary of a drain whose process call rejected: a timeout, or a child that never ran. */
export const rejectedSummary = (err: unknown): string =>
  failedSummary(/timed? out/i.test(String(err instanceof Error ? err.message : err)) ? 'timed out' : 'did not run')

/**
 * How long a hook may wait for a drain: its remaining budget (`next.budget.remainingMs`) less
 * `BUDGET_MARGIN_MS`, from 0 to `DRAIN_TIMEOUT_MS`; `DRAIN_TIMEOUT_MS` when the budget reads no finite number.
 */
export const waitCapMs = (remainingMs: number): number =>
  Number.isFinite(remainingMs)
    ? Math.min(DRAIN_TIMEOUT_MS, Math.max(0, remainingMs - BUDGET_MARGIN_MS))
    : DRAIN_TIMEOUT_MS

/**
 * Whether an inbox entry is a queued item: a `*.json` that is neither hidden (a put, or a drain's claim, in
 * progress) nor rejected.
 */
export const isQueuedName = (name: string): boolean =>
  name.endsWith('.json') && !name.startsWith('.') && !name.endsWith(REJECTED_SUFFIX)

// ---------------------------------------------------------------------------
// State

/**
 * One drain at a time. `isRunning`: the driver process has started, so a request now is owed one rerun after
 * it; a request before that folds into the drain, which lists the inbox afresh anyway.
 */
const pacing = { isBusy: false, isRunning: false, isOwed: false }
/** Resolvers of `whenIdle` callers, released once no drain is in flight or owed. */
const idleWaiters: Array<() => void> = []
/** Summaries no tool result or prompt has carried yet, oldest first. */
const pending: string[] = []

/**
 * The summaries waiting, oldest first, taken at once so no two carriers attach the same line; a carrier that
 * fails to attach some hands them back with `restorePending`.
 */
export const takePending = (): string[] => pending.splice(0)

/** Puts summaries a carrier did not attach back ahead of any that landed since, so none is lost. */
export const restorePending = (lines: readonly string[]): void => {
  pending.unshift(...lines)
}

/** Whether a drain is in flight (or about to start). */
export const isDraining = (): boolean => pacing.isBusy

/** Resolves once no drain is in flight or owed; at once when idle. */
export const whenIdle = (): Promise<void> =>
  pacing.isBusy ? new Promise<void>(resolve => idleWaiters.push(resolve)) : Promise.resolve()

// ---------------------------------------------------------------------------
// Drains: one in flight, an owed rerun

/** Runs `todo_sync.py add --inbox`; its summary, undefined when nothing was queued. */
async function runDrain($: Dollar, r: Runner): Promise<string | undefined> {
  const argv = [r.python, r.script, 'add', '--inbox', '--project', r.project]
  return $.process.run(argv, { timeoutMs: DRAIN_TIMEOUT_MS }).then(drainSummary, rejectedSummary)
}

/** One drain: the runner looked up, the run, the summary kept; a check refresh when it did anything. */
async function drainCycle($: Dollar, host: DrainHost): Promise<void> {
  const runner = await host.runner().catch(noop)
  if (runner === undefined) return
  pacing.isRunning = true
  const summary = await runDrain($, runner)
  // A drain that keeps failing repeats on every subagent turn end: one waiting copy of its line is enough.
  if (summary === undefined || pending.includes(summary)) return
  pending.push(summary)
  host.refresh()
}

/**
 * Asks for a drain and resolves once the drain covering the request has ended (an owed rerun included). The
 * request is marked before the first await, so a `whenIdle` right after it waits for the drain.
 */
export function requestDrain($: Dollar, host: DrainHost): Promise<void> {
  if (pacing.isBusy) {
    if (pacing.isRunning) pacing.isOwed = true
    return whenIdle()
  }
  pacing.isBusy = true
  const idle = whenIdle()
  void drainCycle($, host)
    .catch(noop)
    .finally(() => finishDrain($, host))
  return idle
}

/** Ends a drain and starts the one owed, if any; else releases the idle waiters. */
function finishDrain($: Dollar, host: DrainHost): void {
  pacing.isBusy = false
  pacing.isRunning = false
  if (pacing.isOwed) {
    pacing.isOwed = false
    void requestDrain($, host)
    return
  }
  for (const resolve of idleWaiters.splice(0)) resolve()
}

/**
 * Waits for a drain in flight (or owed), at most `capMs` (see `waitCapMs`); never throws. A `$.clock` wait
 * counts against the hook's budget, as a plain await does, hence the cap.
 */
export async function awaitDrain($: Dollar, capMs: number): Promise<void> {
  if (!pacing.isBusy) return
  const hold: { timer?: Timer } = {}
  const cap = new Promise<void>(resolve => {
    try {
      hold.timer = $.clock.after(capMs, resolve)
    } catch {
      resolve()
    }
  })
  await Promise.race([whenIdle(), cap])
  hold.timer?.cancel()
}

// ---------------------------------------------------------------------------
// The inbox folder

/** Whether the inbox folder lists a queued item (`isQueuedName`); false when it is missing. */
export async function hasQueued($: Dollar, dir: string): Promise<boolean> {
  const entries = await $.fs.list(dir).catch(() => [])
  return entries.some(e => e.kind === 'file' && isQueuedName(e.name))
}
