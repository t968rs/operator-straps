import type { Register } from 'claude-code'

import { registerBand } from './band'
import { registerPhase5Context } from './phase5Scan'
import { registerTracker } from './tracker'

export const register: Register = on => {
  registerTracker(on)
  registerPhase5Context(on)
  registerBand(on)
}
