import type { Register } from 'claude-code'

import { registerBand } from './band'
import { registerSpawn } from './spawn'

export const register: Register = on => {
  registerSpawn(on)
  registerBand(on)
}
