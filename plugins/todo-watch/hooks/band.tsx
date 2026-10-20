import type { EngineInterface, On } from 'claude-code'
import { atom, read, update } from 'claude-code'

/**
 * The todo-watch band above the prompt: the summary and drift notices, kept until the Dismiss button is
 * pressed (a toast leaves on a timer the engine caps at a minute). Functions taking `$` are function
 * declarations: the engine follows `$` past an import only into one.
 */

type Dollar = EngineInterface

/** Notices the band keeps; a newer one pushes the oldest out. */
export const MAX_NOTICES = 3

const noticesAtom = atom({ plugin: 'todo-watch', key: 'notices' } as const, [])

const noop = (): undefined => undefined

/** Adds `text` as the band's newest notice. Never throws. */
export async function postNotice($: Dollar, text: string): Promise<void> {
  await update($, noticesAtom, list => [...list, text].slice(-MAX_NOTICES)).catch(noop)
}

/** Empties the band. Never throws. */
export async function clearNotices($: Dollar): Promise<void> {
  await update($, noticesAtom, () => []).catch(noop)
}

/** The band: each notice on its own line, Dismiss after the newest; nothing while empty or a survey shows. */
export function registerBand(on: On): void {
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const notices = await read($, noticesAtom)
    if (e.props.hasSurvey || notices.length === 0) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    const older = notices.slice(0, -1)
    const newest = notices[notices.length - 1]
    return (
      <Box flexDirection="column">
        {older.map(line => <Text dimColor>{line}</Text>)}
        <Box>
          <Text>{newest} </Text>
          <Button key="dismiss" label="Dismiss" role="dismiss" onPress={() => clearNotices($)} />
        </Box>
      </Box>
    )
  })
}
