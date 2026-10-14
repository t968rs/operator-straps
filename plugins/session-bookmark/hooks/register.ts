import type { Register } from 'claude-code'

import { registerBookmark } from './bookmark'

export const register: Register = on => {
  registerBookmark(on)
}
