import type { EngineInterface, On } from 'claude-code'
import { atom, read, update } from 'claude-code'

import type { NoticeTone, NoticeView } from '../types'
import { isEmptyView } from './summary'

/**
 * The todo-watch band above the prompt, used when `todo.notice.style` is `banner` (the default): the top
 * items, then the sync status, shown at session start and kept until the Dismiss button is pressed. One live
 * view: a catalog or sync change rewrites it in place and never shows the band again. Functions taking `$`
 * are function declarations: the engine follows `$` past an import only into one.
 */

type Dollar = EngineInterface

const noticeAtom = atom({ plugin: 'todo-watch', key: 'notice' } as const, null)
const shownAtom = atom({ plugin: 'todo-watch', key: 'isNoticeShown' } as const, false)

const noop = (): undefined => undefined

/** Replaces the live view; a shown band draws it at once, a hidden one stays hidden. Never throws. */
export async function setNoticeView($: Dollar, view: NoticeView): Promise<void> {
  await update($, noticeAtom, () => view).catch(noop)
}

/** Shows the band (written even when already shown). Never throws. */
export async function showBand($: Dollar): Promise<void> {
  await update($, shownAtom, () => true).catch(noop)
}

/** Hides the band for the rest of the session. Never throws. */
export async function hideBand($: Dollar): Promise<void> {
  await update($, shownAtom, () => false).catch(noop)
}

/** Hides the band and forgets its view, as a session start does. Never throws. */
export async function resetBand($: Dollar): Promise<void> {
  await update($, shownAtom, () => false).catch(noop)
  await update($, noticeAtom, () => null).catch(noop)
}

/** The status `Text` color: a theme key, so a light terminal theme stays readable; dim when unavailable. */
const toneProps = (tone: NoticeTone): { color: 'success' | 'warning' } | { dimColor: true } =>
  tone === 'dim' ? { dimColor: true } : { color: tone === 'ok' ? 'success' : 'warning' }

/**
 * The band: each item line, cut at the terminal edge, then the status line with Dismiss beside it (beside the
 * last item line while there is no status); nothing while hidden, empty, or a survey shows.
 */
export function registerBand(on: On): void {
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey || !(await read($, shownAtom))) return next(e)
    const view = await read($, noticeAtom)
    if (view === null || isEmptyView(view)) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    const dismiss = <Button key="dismiss" label="Dismiss" role="dismiss" onPress={() => hideBand($)} />
    const { status } = view
    const lines = status === null ? view.items.slice(0, -1) : view.items
    const last = view.items[view.items.length - 1]
    return (
      <Box flexDirection="column">
        {lines.map(line => <Text wrap="truncate-end">{line}</Text>)}
        <Box>
          {status === null
            ? <Text wrap="truncate-end">{last} </Text>
            : <Text {...toneProps(status.tone)}>{status.text} </Text>}
          {dismiss}
        </Box>
      </Box>
    )
  })
}
