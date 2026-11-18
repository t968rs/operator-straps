/**
 * The core harness keys the watch reads from `<project>/.claude/harness.json` (`state_dir`,
 * `agent_usage_path`), merged over copies of the harness plugin's `config/defaults.json` values: an installed
 * mod sits in its own plugin cache folder and cannot read that file. The parsed file is kept whole for the
 * layers, which read their own keys from it (`layers/<name>/config.ts`).
 * `tests/mods/test_agent_watcher_config_mirror.py` pins the copies. Pure: no `$`.
 */

export const DEFAULT_STATE_DIR = '.claude/state/harness'
export const DEFAULT_AGENT_USAGE_PATH = 'docs/_harness/agent_usage.jsonl'

/** Project-relative POSIX paths of the core keys. */
export type CoreConfig = {
  stateDir: string
  agentUsagePath: string
}

/** A parsed `harness.json`: its top-level object, `{}` when the text is not a JSON object. */
export type HarnessJson = Readonly<Record<string, unknown>>

export const isObject = (v: unknown): v is HarnessJson => typeof v === 'object' && v !== null && !Array.isArray(v)

const clean = (p: string): string => p.trim().replace(/\\/g, '/').replace(/\/+$/, '')

/** A non-blank string value, cleaned; else the fallback. */
export const pathOr = (v: unknown, fallback: string): string =>
  typeof v === 'string' && clean(v) !== '' ? clean(v) : fallback

export const parseHarness = (text: string): HarnessJson => {
  try {
    const data: unknown = JSON.parse(text)
    return isObject(data) ? data : {}
  } catch {
    return {}
  }
}

/** The core keys of a parsed `harness.json`; a missing, blank or wrong-typed value keeps the default. */
export const coreConfigOf = (data: HarnessJson): CoreConfig => ({
  stateDir: pathOr(data.state_dir, DEFAULT_STATE_DIR),
  agentUsagePath: pathOr(data.agent_usage_path, DEFAULT_AGENT_USAGE_PATH),
})

/**
 * The core view of a `harness.json` text: each key it reads replaces its default. Malformed JSON or a
 * wrong-typed value keeps the default (the harness hooks report it).
 */
export const readConfig = (text: string): CoreConfig => coreConfigOf(parseHarness(text))

/**
 * A configured path against the project root: a relative one is joined to it, an absolute one (POSIX,
 * drive or UNC) is kept, as harness_lib's `cfg.path()` does.
 */
export const under = (root: string, path: string): string =>
  /^([A-Za-z]:)?[\\/]/.test(path) ? path : `${root}/${path}`
