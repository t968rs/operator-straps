import type { Register } from 'claude-code'

import { registerInterpreter } from './interpreter'
import { registerScope } from './scope'

/**
 * The interpreter rewrite registers first, so it runs outermost and the scope hook judges the rewritten
 * command. Each feature registers nothing while its option is unset.
 */
export const register: Register = (on, options) => {
  registerInterpreter(on, typeof options.python === 'string' ? options.python : undefined)
  registerScope(on, options.require_test_file === true)
}
