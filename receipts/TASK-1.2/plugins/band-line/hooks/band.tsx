import type { On } from 'claude-code'
import { atom, read } from 'claude-code'

import type { WorkingLine } from '../types'
import { formatBanner, needsAttention, NO_FIGURES } from './banner'

/**
 * The oStraps banner above the prompt: git-status's snapshot, then the session's model and context window.
 * Reads state only; the band redraws when git-status writes its snapshot or ./banner the session figures. It
 * wraps whatever the hooks beneath drew, so another mod's band (agent-watcher's) stays on screen under it.
 */

const gitAtom = atom({ plugin: 'git-status', key: 'git' } as const, null)
const sessionAtom = atom({ plugin: 'band-line', key: 'session' } as const, NO_FIGURES)
/** working-refs's working line; it stays null while that mod is absent or has nothing to show. */
const refsAtom = atom({ plugin: 'working-refs', key: 'line' } as const, null)

/**
 * The working line's pieces, as the producer composes its plain text, with each branch name dim. A line
 * without `others` (an older working-refs) is its `text`.
 */
type Part = string | { dim: string }

const workingPieces = (line: WorkingLine): Part[] => {
  const { others, head = '', more = 0 } = line
  if (!others) return [line.text]
  const parts: Part[] = []
  if (head) parts.push(head)
  if (head && others.length > 0) parts.push(' · ')
  others.forEach((s, i) => {
    if (i > 0) parts.push(' ')
    parts.push('[ ', { dim: s.branch }, ` ${s.refs} ]`)
  })
  if (more > 0) parts.push(`${head || others.length > 0 ? ' ' : ''}+${more}`)
  return parts
}

/**
 * The pieces to draw. Their plain join must equal the producer's `text`, which is the one copy of the format;
 * when it does not, the line draws `text` as it is, plain, so the band never shows different characters.
 */
const workingParts = (line: WorkingLine): Part[] => {
  const parts = workingPieces(line)
  const joined = parts.map(p => (typeof p === 'string' ? p : p.dim)).join('')
  return joined === line.text ? parts : [line.text]
}

export const registerBand = (on: On): void => {
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const git = await read($, gitAtom)
    if (git === null) return next(e)
    const text = formatBanner(git, await read($, sessionAtom), e.props.bodyColumns)
    const refs = await read($, refsAtom)
    const below = await next(e).catch(() => undefined)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        <Text color={needsAttention(git) ? 'warning' : 'subtle'}>{text}</Text>
        {refs?.text ? (
          <Text color="subtle">
            {workingParts(refs).map((p, i) => (typeof p === 'string' ? p : <Text key={i} dimColor>{p.dim}</Text>))}
          </Text>
        ) : null}
        {below}
      </Box>
    )
  })
}
