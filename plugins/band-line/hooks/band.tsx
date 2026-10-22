import type { On } from 'claude-code'
import { atom, read } from 'claude-code'

import { formatBanner, needsAttention, NO_FIGURES } from './banner'

/**
 * The oStraps banner above the prompt: git-status's snapshot, then the session's model and context window.
 * Reads state only; the band redraws when git-status writes its snapshot or ./banner the session figures. It
 * wraps whatever the hooks beneath drew, so another mod's band (pr-review-watch's) stays on screen under it.
 */

const gitAtom = atom({ plugin: 'git-status', key: 'git' } as const, null)
const sessionAtom = atom({ plugin: 'band-line', key: 'session' } as const, NO_FIGURES)

export const registerBand = (on: On): void => {
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const git = await read($, gitAtom)
    if (git === null) return next(e)
    const text = formatBanner(git, await read($, sessionAtom), e.props.bodyColumns)
    const below = await next(e).catch(() => undefined)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        <Text color={needsAttention(git) ? 'warning' : 'subtle'}>{text}</Text>
        {below}
      </Box>
    )
  })
}
