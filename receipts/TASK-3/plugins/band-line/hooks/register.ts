import type { Register } from 'claude-code'

import { registerBand } from './band'
import { registerBanner } from './banner'

export const register: Register = on => {
  registerBanner(on)
  registerBand(on)
}
