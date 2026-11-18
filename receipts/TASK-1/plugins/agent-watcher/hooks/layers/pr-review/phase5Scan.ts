import type { EngineInterface, FsEntry, On, SessionCompactInput, SessionCompactResult } from 'claude-code'

import { under } from '../../core/config'
import type { Io } from '../../core/layer'
import { ioOf, resolveWatch } from '../../core/watch'
import { sentinelDirOf } from './config'
import { isHot, isSentinelName, parseSentinel, SENTINEL_PREFIX, type SentinelText } from './sentinels'

/**
 * Phase 5 sentinels on disk: the scan of `<state_dir>/pr-review` the band, the Stop guard and the
 * per-prompt `PHASE5_PENDING=` context line share. Every failure degrades to "no sentinel". The scan reads
 * through `Io`; the one function taking `$` (`promptLine`) is a function declaration, since the engine
 * follows `$` past an import only into one.
 */

type Dollar = EngineInterface

/**
 * A hot sentinel's run key (a PR number, or `local-<label>` for a review-local run, as text) and the session
 * that armed it (null when unowned).
 */
export type HotSentinel = { pr: string; owner: string | null }

const noop = (): undefined => undefined
const byName = (a: FsEntry, b: FsEntry): number => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0)

/** Write time of one sentinel in unix seconds: line 2, else the listed mtime, else the stat mtime. */
const sentinelBasis = async (
  io: Io,
  path: string,
  entry: FsEntry,
  text: SentinelText | undefined,
): Promise<number | undefined> => {
  if (text !== undefined && text.writtenAt !== null) return text.writtenAt
  const listed = entry.mtimeMs > 0 ? entry.mtimeMs : undefined
  const mtimeMs = listed ?? (await io.mtimeOf(path))
  return mtimeMs !== undefined && mtimeMs > 0 ? Math.floor(mtimeMs / 1000) : undefined
}

/** One sentinel when hot; undefined when stale or without any usable age. */
const hotSentinel = async (io: Io, dir: string, entry: FsEntry, now: number): Promise<HotSentinel | undefined> => {
  const path = `${dir}/${entry.name}`
  const raw = await io.readText(path)
  const text = raw === undefined ? undefined : parseSentinel(raw)
  const basis = await sentinelBasis(io, path, entry, text)
  if (basis === undefined || !isHot(basis, now)) return undefined
  return { pr: text?.pr ?? entry.name.slice(SENTINEL_PREFIX.length), owner: text?.sessionId ?? null }
}

/** Hot sentinels in `dir` (absolute), sorted by file name; empty when the folder is absent. */
export const scanPhase5 = async (io: Io, dir: string): Promise<HotSentinel[]> => {
  const entries = await io.listDir(dir)
  const named = entries.filter(e => e.kind !== 'dir' && isSentinelName(e.name)).sort(byName)
  if (named.length === 0) return []
  const now = Math.floor((await io.now()) / 1000)
  const hot: HotSentinel[] = []
  for (const entry of named) {
    const found = await hotSentinel(io, dir, entry, now).catch(noop)
    if (found !== undefined) hot.push(found)
  }
  return hot
}

/** The hot sentinels of the project `io` serves: `<state_dir>/pr-review` under the main checkout. */
export const scanSentinels = (io: Io): Promise<HotSentinel[]> =>
  scanPhase5(io, under(io.watch.sentinelRoot, sentinelDirOf(io.watch.cfg)))

/** The prompt context line for hot sentinel run keys. */
export const phase5Context = (ids: readonly string[]): string => `PHASE5_PENDING=${ids.join(',')}`

// ---------------------------------------------------------------------------
// Per-prompt context

/** The line last attached in this conversation; '' forces the next non-empty one on. */
const context = { lastAttached: '' }

/** This prompt's line when hot sentinels exist and it differs from the one last attached. */
async function promptLine($: Dollar): Promise<string | undefined> {
  const w = await resolveWatch($)
  if (w === undefined) return undefined
  const io = ioOf($, w)
  const ids = (await scanSentinels(io)).map(s => s.pr)
  await io.setPhase5(ids).catch(noop)
  if (ids.length === 0) context.lastAttached = ''
  const line = ids.length === 0 ? undefined : phase5Context(ids)
  return line === context.lastAttached ? undefined : line
}

/** Session-end reasons after which the same process goes on with a fresh conversation. */
const FRESH_CONVERSATION = new Set<string>(['clear', 'resume'])

/** Whether a compaction result replaced the main conversation (its context line may be gone). */
const isMainCompaction = (e: SessionCompactInput, result: SessionCompactResult): boolean =>
  result.skip === undefined && e.agentId === undefined && e.trigger !== 'precompute'

/** Attaches `PHASE5_PENDING=<ids>` to a prompt while sentinels are hot, once per change of the set. */
export const registerPhase5Context = (on: On): void => {
  on('prompt.submit', async ($, e, next) => {
    const line = await promptLine($).catch(noop)
    if (line === undefined || next.signal.aborted) return next(e)
    const result = await next({ ...e, context: [...(e.context ?? []), line] })
    if (result.drop === undefined && (result.context ?? []).includes(line)) context.lastAttached = line
    return result
  }).catch((_$, e, next) => next(e))

  on('session.end', async ($, e, next) => {
    if (FRESH_CONVERSATION.has(e.reason)) context.lastAttached = ''
    return next(e)
  }).catch((_$, e, next) => next(e))

  on('session.compact', async ($, e, next) => {
    const result = await next(e)
    if (isMainCompaction(e, result)) context.lastAttached = ''
    return result
  }).catch((_$, e, next) => next(e))
}
