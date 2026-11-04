import type { EngineInterface, On } from 'claude-code'
import { atom, read } from 'claude-code'

import { formatRun, markAgent, refreshRuns } from './lanes'

/**
 * The lane band above the prompt: one line per parallel2 run a lane agent was spawned for this session,
 * each lane with its recorded status and, for a lane agent of this session, `(running)` or `(returned)`.
 * Runs are reread after a lane spawn, at every turn end (a lane agent's marks it returned) and after a Bash
 * or PowerShell call that names `parallel2.py`; a run whose state file is gone (cleaned up) drops out.
 */

const noop = (): undefined => undefined

// declared here as well as in ./lanes: the engine lists a module's state reads from atoms of its own file
const runsAtom = atom({ plugin: 'parallel2-lanes', key: 'runs' } as const, [])

/** True for a shell command that runs the parallel2 driver. */
export const namesDriver = (command: unknown): boolean =>
  typeof command === 'string' && command.includes('parallel2.py')

/** Rereads the runs after the current call returns; inline when the clock refuses. Never throws. */
export async function refreshSoon($: EngineInterface): Promise<void> {
  try {
    $.clock.after(0, () => refreshRuns($))
  } catch {
    await refreshRuns($).catch(noop)
  }
}

export function registerBand(on: On): void {
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId) await markAgent($, e.agentId, 'returned').catch(noop)
    await refreshRuns($).catch(noop)
    return result
  }).catch((_$, e, next) => next(e))

  on('tool.call', { tool: /^(Bash|PowerShell)$/ }, async ($, e, next) => {
    const result = await next(e)
    if (namesDriver((e as { command?: unknown }).command)) await refreshSoon($)
    return result
  }).catch((_$, e, next) => next(e))

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const runs = await read($, runsAtom)
    if (runs.length === 0) return next(e)
    const below = await next(e).catch(() => undefined)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {runs.map(run => <Text color="subtle" wrap="truncate-end">{formatRun(run)}</Text>)}
        {below}
      </Box>
    )
  })
}
