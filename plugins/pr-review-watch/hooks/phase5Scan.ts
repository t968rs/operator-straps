import type { EngineInterface, FsEntry, On, SessionCompactInput, SessionCompactResult } from 'claude-code'
import { atom, update } from 'claude-code'

import { sentinelDirOf, under } from './config'
import { isHot, isSentinelName, parseSentinel, SENTINEL_PREFIX, type SentinelText } from './sentinels'
import { resolveWatch } from './watch'

/**
 * Phase 5 sentinels on disk: the scan of `<state_dir>/pr-review` the band, the Stop guard and the
 * per-prompt `PHASE5_PENDING=` context line share. Every failure degrades to "no sentinel". Functions
 * taking `$` are function declarations: the engine follows `$` past an import only into one.
 */

type Dollar = EngineInterface

/** A hot sentinel's PR id and the session that armed it (null when unowned). */
export type HotSentinel = { pr: string; owner: string | null }

const phase5Atom = atom({ plugin: 'pr-review-watch', key: 'phase5' } as const, [])

const noop = (): undefined => undefined
const byName = (a: FsEntry, b: FsEntry): number => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0)

/** Write time of one sentinel in unix seconds: line 2, else the listed mtime, else the stat mtime. */
async function sentinelBasis(
  $: Dollar,
  path: string,
  entry: FsEntry,
  text: SentinelText | undefined,
): Promise<number | undefined> {
  if (text !== undefined && text.writtenAt !== null) return text.writtenAt
  const listed = entry.mtimeMs > 0 ? entry.mtimeMs : undefined
  const mtimeMs = listed ?? (await $.fs.stat(path).catch(noop))?.mtimeMs
  return mtimeMs !== undefined && mtimeMs > 0 ? Math.floor(mtimeMs / 1000) : undefined
}

/** One sentinel when hot; undefined when stale or without any usable age. */
async function hotSentinel($: Dollar, dir: string, entry: FsEntry, now: number): Promise<HotSentinel | undefined> {
  const path = `${dir}/${entry.name}`
  const raw = await $.fs.read(path).catch(noop)
  const text = typeof raw === 'string' ? parseSentinel(raw) : undefined
  const basis = await sentinelBasis($, path, entry, text)
  if (basis === undefined || !isHot(basis, now)) return undefined
  return { pr: text?.pr ?? entry.name.slice(SENTINEL_PREFIX.length), owner: text?.sessionId ?? null }
}

/** Hot sentinels in `dir` (absolute), sorted by file name; empty when the folder is absent. */
export async function scanPhase5($: Dollar, dir: string): Promise<HotSentinel[]> {
  const entries = await $.fs.list(dir).catch(() => [] as FsEntry[])
  const named = entries.filter(e => e.kind !== 'dir' && isSentinelName(e.name)).sort(byName)
  if (named.length === 0) return []
  const now = Math.floor((await $.clock.now()) / 1000)
  const hot: HotSentinel[] = []
  for (const entry of named) {
    const found = await hotSentinel($, dir, entry, now).catch(noop)
    if (found !== undefined) hot.push(found)
  }
  return hot
}

/** The prompt context line for hot sentinel PR ids. */
export const phase5Context = (ids: readonly string[]): string => `PHASE5_PENDING=${ids.join(',')}`

// ---------------------------------------------------------------------------
// Per-prompt context

/** The line last attached in this conversation; '' forces the next non-empty one on. */
const context = { lastAttached: '' }

/** This prompt's line when hot sentinels exist and it differs from the one last attached. */
async function promptLine($: Dollar): Promise<string | undefined> {
  const w = await resolveWatch($)
  if (w === undefined) return undefined
  const ids = (await scanPhase5($, under(w.sentinelRoot, sentinelDirOf(w.cfg)))).map(s => s.pr)
  await update($, phase5Atom, () => ids).catch(noop)
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
