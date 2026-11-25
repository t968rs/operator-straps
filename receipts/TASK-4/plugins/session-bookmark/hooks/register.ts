import type { Register } from 'claude-code'

import { registerBookmark } from './bookmark'
import { registerSessionHook } from './session_hook'

export const register: Register = on => {
  registerBookmark(on)
  registerSessionHook(on)
}
