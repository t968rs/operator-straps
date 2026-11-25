/**
 * The one harness key the lap-stamp mod reads from `<project>/.claude/harness.json`, merged over a copy of the
 * harness plugin's `config/defaults.json` value: an installed mod sits in its own plugin cache folder and
 * cannot read that file. `tests/mods/test_lap_stamp_config_mirror.py` pins the copy. Pure: no `$`.
 */

export const DEFAULT_STATE_DIR = '.claude/state/harness'

/** The laps file, relative to `state_dir`: one JSONL per checkout in the mod's own folder. */
export const LAPS_PATH = 'lap-stamp/laps.jsonl'

/** The state folder, a project-relative POSIX path or an absolute one. */
export type LapConfig = {
  stateDir: string
}

type Json = Readonly<Record<string, unknown>>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

const clean = (p: string): string => p.trim().replace(/\\/g, '/').replace(/\/+$/, '')

/** A non-blank string value, cleaned; else the fallback. */
const pathOr = (v: unknown, fallback: string): string =>
  typeof v === 'string' && clean(v) !== '' ? clean(v) : fallback

const parse = (text: string): Json => {
  try {
    const data: unknown = JSON.parse(text)
    return isObject(data) ? data : {}
  } catch {
    return {}
  }
}

/**
 * The mod's view of a `harness.json` text: `state_dir` replaces its default. Malformed JSON or a wrong-typed
 * value keeps the default (the harness hooks report it).
 */
export const readConfig = (text: string): LapConfig => ({
  stateDir: pathOr(parse(text).state_dir, DEFAULT_STATE_DIR),
})

/**
 * The laps file under the project root: a relative `state_dir` is joined to the root, an absolute one (POSIX,
 * drive or UNC) is kept, as harness_lib's `cfg.path()` does.
 */
export const lapsPathOf = (root: string, cfg: LapConfig): string => {
  const base = /^([A-Za-z]:)?[\\/]/.test(cfg.stateDir) ? cfg.stateDir : `${clean(root)}/${cfg.stateDir}`
  return `${base}/${LAPS_PATH}`
}
