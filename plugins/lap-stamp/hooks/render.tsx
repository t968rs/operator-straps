import type { EngineInterface, On } from 'claude-code'
import { atom, read } from 'claude-code'

import type { LapRow } from '../types'
import { blockStamp, durationRow, rowsForBlock, stampText, wrapRight } from './stamp'

/**
 * The stamps drawn in the transcript. A reply block whose text matches rows of the current session gains
 * rust-colored (STAMP_COLOR), right-aligned stamp rows under the engine's own drawing (D6, D7); a `TurnDuration` line whose duration matches
 * one empty-answer row gains its stamp right-aligned on the same row (D8). The rows come from `$.state` alone,
 * never the disk (D9); reading them subscribes the drawing, so a new row redraws the reply it belongs to. A
 * summary block, a miss, an uncertain match or any failure draws the engine's tree untouched (D10).
 */

// declared here: the engine lists a module's state reads from atoms of its own file
const rowsAtom = atom({ plugin: 'lap-stamp', key: 'rows' } as const, [])
const sessionAtom = atom({ plugin: 'lap-stamp', key: 'session' } as const, null)

/** The stamp's text color: rust, between oxblood and dark orange, legible on dark and light themes. */
export const STAMP_COLOR = '#B7410E'

/** The mod's memory as render reads it: the rows held and the current session id. */
export type Memory = { rows: readonly LapRow[]; session: string | null }

/**
 * Where render takes the memory from in place of `$.state`. Only tests pass one: the host grants `$.state` to
 * the hooks module that spells the reads, and hooks a test registers are not that module.
 */
export type MemorySource = () => Promise<Memory>

/** The memory in `$.state`; reading it while a site draws subscribes that site to both values. */
async function stateMemory($: EngineInterface): Promise<Memory> {
  const session = await read($, sessionAtom)
  const rows = await read($, rowsAtom)
  return { rows, session }
}

/** The rows of the current session; none while no session is known. */
export const currentRows = (memory: Memory): LapRow[] =>
  memory.session === null ? [] : memory.rows.filter(r => r.session === memory.session)

/** The current session's rows from memory; none when the read fails. */
async function sessionRows($: EngineInterface, source: MemorySource | undefined): Promise<LapRow[]> {
  try {
    return currentRows(source === undefined ? await stateMemory($) : await source())
  } catch {
    return []
  }
}

/** The stamp a reply block draws; null for a miss. A session with no rows never fingerprints the block. */
async function replyStamp($: EngineInterface, source: MemorySource | undefined, text: string): Promise<string | null> {
  const rows = await sessionRows($, source)
  if (rows.length === 0) return null
  return blockStamp(rowsForBlock(rows, text))
}

/** The stamp a `TurnDuration` line draws; null unless exactly one empty-answer row lies within the tolerance. */
async function durationStamp(
  $: EngineInterface,
  source: MemorySource | undefined,
  durationMs: number,
): Promise<string | null> {
  const hit = durationRow(await sessionRows($, source), durationMs)
  return hit === null ? null : stampText(hit)
}

/**
 * A stamp's rows: wrapped to the transcript width by `wrapRight`, the padding left to the enclosing Box's
 * right alignment so a site narrower than the viewport still fits them. No width known: one row.
 */
export const stampLines = (stamp: string, columns: number | undefined): string[] =>
  wrapRight(stamp, columns ?? 0).map(line => line.trimStart())

/** Reply blocks: the engine's drawing, then the stamp rows right-aligned beneath it. */
function registerReplyStamp(on: On, source: MemorySource | undefined): void {
  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    if (e.props.isSummary === true) return next(e)
    const stamp = await replyStamp($, source, e.props.text).catch(() => null)
    if (stamp === null) return next(e)
    const original = await next(e)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {original}
        <Box flexDirection="column" alignItems="flex-end">
          {stampLines(stamp, e.viewport?.columns).map(line => <Text color={STAMP_COLOR}>{line}</Text>)}
        </Box>
      </Box>
    )
  }).catch((_$, e, next) => next(e))
}

/** `TurnDuration` lines: the engine's line and the stamp on one row, the stamp at the right edge. */
function registerDurationStamp(on: On, source: MemorySource | undefined): void {
  on('ui.render', { component: 'TurnDuration' }, async ($, e, next) => {
    const stamp = await durationStamp($, source, e.props.durationMs).catch(() => null)
    if (stamp === null) return next(e)
    const original = await next(e)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="row" justifyContent="space-between" gap={1}>
        {original}
        <Text color={STAMP_COLOR}>{stamp}</Text>
      </Box>
    )
  }).catch((_$, e, next) => next(e))
}

/**
 * Registers the transcript stamps: under matched reply blocks and on matched `TurnDuration` lines. The mod
 * passes no `source`, so the rows come from `$.state`; a test passes one (MemorySource).
 */
export function registerRender(on: On, source?: MemorySource): void {
  registerReplyStamp(on, source)
  registerDurationStamp(on, source)
}
