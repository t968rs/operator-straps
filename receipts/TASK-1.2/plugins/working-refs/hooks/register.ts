import type { Register } from 'claude-code'

import { registerWatch, startScan } from './watch'

const noop = (): undefined => undefined

export const register: Register = on => {
  // One session.start hook (the engine refuses two without a matcher): the first scan, after the dispatch.
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await startScan($).catch(noop)
    return started
  })
  registerWatch(on)
}
