import type { Register } from 'claude-code'

import { registerCore } from './core/tracker'
import { LAYERS } from './layers/index'
import { registerPrReviewLayer } from './layers/pr-review/layer'

/**
 * The composition root, the one file that wires the core and the layers: the core with the layer list, then
 * each layer's own hooks by a direct call (Decision D7: the engine refuses `on` passed through an object).
 */
export const register: Register = on => {
  registerCore(on, LAYERS)
  registerPrReviewLayer(on)
}
