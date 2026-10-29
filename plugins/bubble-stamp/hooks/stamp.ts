import type { EngineInterface, FsEntry, On } from 'claude-code'
import { atom, read, update } from 'claude-code'

import type { ActiveMemo } from '../types'
import { under } from './config'
import { MEMO_SUFFIX, openIds, stampMemo, type Resolution } from './memo'
import { closedResolutions, reviewFileFor } from './review'
import { resolveWatch, type Watch } from './watch'

/**
 * Engine glue for bubble-stamp: keeps the memos of the reviews folder that still hold an `Open` row, and when
 * a trigger (a pr_review.py / review_edit.py shell call, an Edit or Write of a memo's review JSON, a finished
 * turn) finds that review JSON moved, stamps the memo with the ids its `post_review_resolutions` closed. Active
 * only in a project holding `.claude/harness.json` (./watch). Every host failure degrades to doing nothing; no
 * hook throws into a tool call, a turn or a session start. Functions taking `$` are function declarations: the
 * engine follows `$` past an import only into one.
 */

type Dollar = EngineInterface
type Memos = Record<string, ActiveMemo>
/** One memo after a check: its new record (undefined: leaves the active set) and the ids it stamped. */
type Outcome = { next: ActiveMemo | undefined; stamped: string[] }
/** What stamping a memo file did; undefined when the file could not be read or written. */
type Stamped = { stamped: string[]; isOpen: boolean }

const memosAtom = atom({ plugin: 'bubble-stamp', key: 'memos' } as const, {})

/** A shell command that drives pr-review's script or the review editor; its result can close an id. */
const REVIEW_SCRIPT = /pr_review\.py|review_edit\.py|bubble_memo\.py/

const regexEscaped = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const MEMO_NAME = new RegExp(`^PR_(\\d+)${regexEscaped(MEMO_SUFFIX)}$`)

const noop = (): undefined => undefined

/** Serializes checks: parallel triggers never interleave a read-modify-write of a memo or the state. */
let tail: Promise<unknown> = Promise.resolve()

const serial = <T>(work: () => Promise<T>): Promise<T> => {
  const run = tail.then(work, work)
  tail = run.catch(noop)
  return run
}

/** The PR number a memo file name carries (`PR_<N>_Bubbles.md`); undefined for any other name. */
export const memoPrOf = (name: string): number | undefined => {
  const digits = MEMO_NAME.exec(name)?.[1]
  return digits === undefined ? undefined : Number(digits)
}

/** A path as compared: forward slashes, lower case (Windows hosts spell one file several ways). */
const pathKey = (p: string): string => p.trim().replace(/\\/g, '/').toLowerCase()

// ---------------------------------------------------------------------------
// Host access

async function readText($: Dollar, path: string): Promise<string | undefined> {
  const raw = await $.fs.read(path).catch(noop)
  return typeof raw === 'string' ? raw : undefined
}

async function activeMemos($: Dollar): Promise<Memos> {
  try {
    return await read($, memosAtom)
  } catch {
    return {}
  }
}

async function notify($: Dollar, text: string): Promise<void> {
  await Promise.resolve($.ui.toast(text)).catch(noop)
}

// ---------------------------------------------------------------------------
// Active memos

/**
 * The record of one listed memo file. Undefined when the file parsed and lacks the anchors or has no Open row;
 * a read the host refused keeps `prior` (undefined for a memo not yet known).
 */
async function memoRecord(
  $: Dollar,
  dir: string,
  entry: FsEntry,
  entries: readonly FsEntry[],
  prior: ActiveMemo | undefined,
): Promise<ActiveMemo | undefined> {
  const pr = memoPrOf(entry.name)
  if (pr === undefined || entry.kind === 'dir') return undefined
  const memo = `${dir}/${entry.name}`
  const text = await readText($, memo)
  if (text === undefined) return prior
  if (openIds(text).length === 0) return undefined
  const hit = reviewFileFor(pr, entries)
  const review = hit === undefined ? null : `${dir}/${hit.name}`
  const isSame = prior !== undefined && prior.review === review
  return { memo, review, mtimeMs: isSame ? prior.mtimeMs : 0 }
}

/**
 * Lists the reviews folder and replaces the active set; a memo's last-seen mtime survives while its review JSON
 * stays. A refused listing keeps the set as it was.
 */
async function discover($: Dollar, w: Watch): Promise<void> {
  const dir = under(w.root, w.cfg.reviewsDir)
  const entries = await $.fs.list(dir).catch(noop)
  if (entries === undefined) return
  const prior = await activeMemos($)
  const found: Memos = {}
  for (const entry of entries) {
    const rec = await memoRecord($, dir, entry, entries, prior[entry.name]).catch(noop)
    if (rec !== undefined) found[entry.name] = rec
  }
  await update($, memosAtom, () => found).catch(noop)
}

// ---------------------------------------------------------------------------
// Stamping

/** A memo that could not be read: one that cannot be statted either is gone and leaves the set; else it is retried. */
async function unreadableMemo($: Dollar, memo: string): Promise<Stamped | undefined> {
  const st = await $.fs.stat(memo).catch(noop)
  return st === undefined ? { stamped: [], isOpen: false } : undefined
}

/**
 * Stamps `memo` with `closed`. The memo is read, stamped in memory, then read again just before the write and
 * stamped afresh when it moved in between; it is written only when its text changed. Undefined when it exists
 * but cannot be read, or the write is refused: an unreadable memo is never overwritten.
 */
async function stampFile($: Dollar, memo: string, closed: readonly Resolution[]): Promise<Stamped | undefined> {
  const first = await readText($, memo)
  if (first === undefined) return unreadableMemo($, memo)
  const trial = stampMemo(first, closed)
  if (trial.text === first) return { stamped: [], isOpen: openIds(first).length > 0 }
  const fresh = await readText($, memo)
  if (fresh === undefined) return unreadableMemo($, memo)
  const out = fresh === first ? trial : stampMemo(fresh, closed)
  if (out.text === fresh) return { stamped: [], isOpen: openIds(fresh).length > 0 }
  const isWritten = await $.fs.write(memo, out.text).then(() => true, () => false)
  return isWritten ? { stamped: out.stamped, isOpen: openIds(out.text).length > 0 } : undefined
}

/** One memo: stat its review JSON, read it only when the mtime moved, stamp what it closes. */
async function checkOne($: Dollar, m: ActiveMemo): Promise<Outcome> {
  const unchanged: Outcome = { next: m, stamped: [] }
  if (m.review === null) return unchanged
  const st = await $.fs.stat(m.review).catch(noop)
  if (st === undefined || st.mtimeMs === m.mtimeMs) return unchanged
  const text = await readText($, m.review)
  if (text === undefined) return unchanged
  const resolved = closedResolutions(text)
  if (resolved === undefined) return unchanged
  const seen: ActiveMemo = { ...m, mtimeMs: st.mtimeMs }
  if (resolved.length === 0) return { next: seen, stamped: [] }
  const done = await stampFile($, m.memo, resolved)
  if (done === undefined) return unchanged
  return { next: done.isOpen ? seen : undefined, stamped: done.stamped }
}

const noticeOf = (stamped: ReadonlyArray<readonly [string, readonly string[]]>): string =>
  `bubble-stamp: stamped ${stamped.map(([name, ids]) => `${ids.join(', ')} in ${name}`).join('; ')}`

/** Checks every active memo; one toast names the ids stamped. */
async function checkAll($: Dollar): Promise<void> {
  const memos = await activeMemos($)
  const names = Object.keys(memos)
  if (names.length === 0) return
  const next: Memos = {}
  const stamped: Array<readonly [string, readonly string[]]> = []
  for (const name of names) {
    const m = memos[name]
    if (m === undefined) continue
    const out = await checkOne($, m).catch((): Outcome => ({ next: m, stamped: [] }))
    if (out.next !== undefined) next[name] = out.next
    if (out.stamped.length > 0) stamped.push([name, out.stamped])
  }
  await update($, memosAtom, () => next).catch(noop)
  if (stamped.length > 0) await notify($, noticeOf(stamped))
}

/** Lists the reviews folder, then checks every active memo. */
async function scan($: Dollar): Promise<void> {
  const w = await resolveWatch($)
  if (w === undefined) return
  await discover($, w)
  await checkAll($)
}

// ---------------------------------------------------------------------------
// Triggers

/** A shell call that ran the review script or the review editor: a memo may be new, a review JSON moved. */
async function afterShell($: Dollar, command: string): Promise<void> {
  if (!REVIEW_SCRIPT.test(command)) return
  await serial(() => scan($)).catch(noop)
}

/** A file tool call: checks when it touched an active memo's review JSON. */
async function afterFile($: Dollar, path: string): Promise<void> {
  const key = pathKey(path)
  const memos = await activeMemos($)
  if (!Object.values(memos).some(m => m.review !== null && pathKey(m.review) === key)) return
  await serial(() => checkAll($)).catch(noop)
}

/** Registers the stamp hooks; each runs after the host handled the event and never changes its result. */
export function registerStamp(on: On): void {
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const r = await next(e)
    await afterShell($, e.command).catch(noop)
    return r
  })

  on('tool.call', { tool: 'PowerShell' }, async ($, e, next) => {
    const r = await next(e)
    await afterShell($, e.command).catch(noop)
    return r
  })

  on('tool.call', { tool: 'Edit' }, async ($, e, next) => {
    const r = await next(e)
    await afterFile($, e.file_path).catch(noop)
    return r
  })

  on('tool.call', { tool: 'Write' }, async ($, e, next) => {
    const r = await next(e)
    await afterFile($, e.file_path).catch(noop)
    return r
  })

  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    if (e.agentId === undefined) await serial(() => checkAll($)).catch(noop)
    return r
  })

  on('session.start', async ($, e, next) => {
    const r = await next(e)
    await serial(() => scan($)).catch(noop)
    return r
  })
}
