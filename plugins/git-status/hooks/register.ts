import type { Register } from 'claude-code'

import { registerStatus } from './status'

export const register: Register = on => {
  registerStatus(on)
}
