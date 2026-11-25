import type { EngineInterface, On } from 'claude-code'

import { todoText } from './checks'
import { resolveWatch } from './watch'

/**
 * The `/todo` command (M5): registered at `session.start` only in an active project; prints the catalog
 * summary, the top-N table and the sync findings. Outside an active project the command is not registered
 * and a `/todo` of another source passes through.
 */

export const COMMAND = 'todo'
export const COMMAND_DESCRIPTION = 'Show the TODO catalog summary, its top items and the sync findings'
export const UNAVAILABLE_COMMAND_TEXT = 'todo-watch: TODO state unavailable.'

const noop = (): undefined => undefined

/** Whether this load registered the command. */
const command = { isRegistered: false }

/**
 * Registers `/todo` once per load when the watch is active (wired into `session.start` by ./register).
 * Never throws. A function declaration: the engine follows `$` past an import only into one.
 */
export async function registerTodoCommand($: EngineInterface): Promise<void> {
  const w = await resolveWatch($).catch(noop)
  if (w === undefined || command.isRegistered) return
  await $.command
    .register({ name: COMMAND, description: COMMAND_DESCRIPTION })
    .then(() => {
      command.isRegistered = true
    })
    .catch(noop)
}

/** Answers `/todo` while registered; passes it on otherwise. */
export const registerCommand = (on: On): void => {
  on('command.run', { command: COMMAND }, async ($, e, next) => {
    if (!command.isRegistered) return next(e)
    return { text: (await todoText($)) ?? UNAVAILABLE_COMMAND_TEXT }
  }).catch((_$, e, next) => (command.isRegistered ? { text: UNAVAILABLE_COMMAND_TEXT } : next(e)))
}
