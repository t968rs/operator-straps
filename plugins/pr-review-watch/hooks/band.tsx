import type { On } from 'claude-code'
import { atom, read } from 'claude-code'

import { bandText } from './runs'

/**
 * The row above the prompt: the active review run and hot Phase 5 sentinels. Reads state only. It wraps what
 * the hooks beneath drew, so another mod's band (band-line's oStraps banner) stays on screen with it.
 */

const runsAtom = atom({ plugin: 'pr-review-watch', key: 'runs' } as const, {})
const activeAtom = atom({ plugin: 'pr-review-watch', key: 'active' } as const, null)
const phase5Atom = atom({ plugin: 'pr-review-watch', key: 'phase5' } as const, [])
const missingAtom = atom({ plugin: 'pr-review-watch', key: 'missing' } as const, [])

export const registerBand = (on: On): void => {
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const id = await read($, activeAtom)
    const runs = await read($, runsAtom)
    const missing = await read($, missingAtom)
    const run = id === null ? null : (runs[id] ?? null)
    const text = bandText({ run, phase5: await read($, phase5Atom), missing })
    if (text === undefined) return next(e)
    const below = await next(e).catch(() => undefined)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        <Text color={missing.length > 0 ? 'warning' : 'subtle'}>
          {text}
        </Text>
        {below}
      </Box>
    )
  })
}
