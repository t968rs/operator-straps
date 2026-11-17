import type { Register } from 'claude-code'

import { registerStamp } from './stamp'

export const register: Register = on => registerStamp(on)
