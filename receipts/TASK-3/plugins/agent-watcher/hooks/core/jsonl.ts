import type { LogFailure } from '../../types'
import type { Io } from './layer'

/**
 * Append-only JSONL files (the usage log, a layer's matrix): validate, append through a whole-file write,
 * keep and toast what failed. An unreadable file is never overwritten. Appends from every layer share one
 * queue, so parallel returns never interleave a read-modify-write.
 */

const MAX_FAILURES = 20

const noop = (): undefined => undefined

/** The tail of the append queue. */
let tail: Promise<unknown> = Promise.resolve()

/** Runs `task` after every queued append; a failed task never stops the queue. */
export const serialize = (task: () => Promise<unknown>): Promise<unknown> => {
  tail = tail.then(task).catch(noop)
  return tail
}

/** The JSONL text with rows appended, one compact object per line. */
export const appendRows = (existing: string, rows: readonly object[]): string => {
  if (rows.length === 0) return existing
  const head = existing === '' || existing.endsWith('\n') ? existing : `${existing}\n`
  return head + rows.map(r => `${JSON.stringify(r)}\n`).join('')
}

/** How one JSONL file checks and names its rows; `label` starts the failure reasons. */
export type RowCheck<R> = { label: string; problems: (r: R) => string[]; cellOf: (r: R) => string }

/** Keeps the failures and toasts them; `noun` names the row kind (`matrix`, `usage`). */
export const recordFailures = async (io: Io, failures: readonly LogFailure[], noun: string): Promise<void> => {
  if (failures.length === 0) return
  await io.updateFailures(prev => [...prev, ...failures].slice(-MAX_FAILURES)).catch(noop)
  const first = failures[0]
  await io.toast(`agent-watcher: ${failures.length} ${noun} row(s) not appended (${first?.cell}: ${first?.reason})`)
}

/**
 * The JSONL text to append to: '' when the file is missing, undefined when it exists (or its existence
 * is unknown) but cannot be read, so a whole-file write would drop its rows.
 */
const readJsonl = async (io: Io, path: string): Promise<string | undefined> =>
  ((await io.exists(path)) ?? true) ? io.readText(path) : ''

/**
 * Appends valid rows to `path`; returns the failures (invalid rows, or every row when the file cannot be
 * read or the write is refused). An unreadable file is never overwritten.
 */
export const appendValid = async <R extends object>(
  io: Io,
  path: string,
  rows: readonly R[],
  check: RowCheck<R>,
  now: number,
): Promise<LogFailure[]> => {
  const checked = rows.map(r => ({ r, why: check.problems(r) }))
  const good = checked.filter(x => x.why.length === 0).map(x => x.r)
  const failures = checked.filter(x => x.why.length > 0)
    .map(x => ({ cell: check.cellOf(x.r), reason: x.why.join('; '), at: now }))
  if (good.length === 0) return failures
  const existing = await readJsonl(io, path)
  const isWritten = existing !== undefined && (await io.write(path, appendRows(existing, good)))
  if (isWritten) return failures
  const reason = existing === undefined ? `${check.label} unreadable; not overwritten` : `${check.label} write refused`
  return [...failures, ...good.map(r => ({ cell: check.cellOf(r), reason, at: now }))]
}
