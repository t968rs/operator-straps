import type { Register } from 'claude-code'

import { registerChecks, registerContext, startSession } from './checks'
import { registerCommand, registerTodoCommand } from './command'

const noop = (): undefined => undefined

export const register: Register = on => {
  // One session.start hook (the engine refuses two without a matcher): the command, then the summary toast.
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await registerTodoCommand($).catch(noop)
    await startSession($).catch(noop)
    return started
  })
  registerChecks(on)
  registerContext(on)
  registerCommand(on)
}
