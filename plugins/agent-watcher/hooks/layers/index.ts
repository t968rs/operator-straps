import type { Layer } from '../core/layer'
import { prReviewLayer } from './pr-review/layer'

/**
 * Every layer the core consults, in claim order: the first whose `identify` answers owns a dispatch. Each
 * layer's own hooks register by a direct call in `register.ts`, never through this list (Decision D7).
 */
export const LAYERS: readonly Layer[] = [prReviewLayer]
