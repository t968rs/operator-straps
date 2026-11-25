import type { Register } from 'claude-code'

import { registerLap } from './lap'
import { registerRender } from './render'

export const register: Register = on => {
  registerLap(on)
  registerRender(on)
}
