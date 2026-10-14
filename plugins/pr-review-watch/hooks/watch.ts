import type { EngineInterface } from 'claude-code'

import { readConfig, type WatchConfig } from './config'
import { HARNESS_CONFIG_REL, rootCandidates } from './root'

/**
 * The project the watch serves: its root (forward slashes), its harness configuration, and the main
 * checkout per-repository state (Phase 5 sentinels) lives under; the root itself outside a linked worktree.
 */
export type Watch = { root: string; cfg: WatchConfig; sentinelRoot: string }

const GIT_TIMEOUT_MS = 10_000

const noop = (): undefined => undefined

/** Top levels already answered, by start folder (a reload starts afresh). */
const toplevels = new Map<string, string>()

/** `git rev-parse --show-toplevel` from `start`; undefined on any failure. */
async function toplevelOf($: EngineInterface, start: string | undefined): Promise<string | undefined> {
  if (start === undefined || start.trim() === '') return undefined
  const known = toplevels.get(start)
  if (known !== undefined) return known
  const argv = ['git', '-C', start, 'rev-parse', '--show-toplevel']
  const ran = await $.process.run(argv, { timeoutMs: GIT_TIMEOUT_MS }).catch(noop)
  const top = ran === undefined || ran.exitCode !== 0 ? '' : ran.stdout.trim()
  if (top === '') return undefined
  toplevels.set(start, top)
  return top
}

/** Main checkout of `root`'s repository (`git rev-parse --git-common-dir` minus `/.git`); else `root`. */
async function mainCheckoutOf($: EngineInterface, root: string): Promise<string> {
  const argv = ['git', '-C', root, 'rev-parse', '--path-format=absolute', '--git-common-dir']
  const ran = await $.process.run(argv, { timeoutMs: GIT_TIMEOUT_MS }).catch(noop)
  const common = ran === undefined || ran.exitCode !== 0 ? '' : ran.stdout.trim().replace(/\\/g, '/')
  return common.endsWith('/.git') ? common.slice(0, -'/.git'.length) : root
}

/**
 * The first candidate root (./root) whose `.claude/harness.json` reads, with that file's configuration;
 * undefined when none does, which leaves the watch inactive. Never throws. Function declarations: the
 * engine follows `$` past an import only into one.
 */
export async function resolveWatch($: EngineInterface): Promise<Watch | undefined> {
  const env = await $.env.get('CLAUDE_PROJECT_DIR').catch(noop)
  const cwd = await $.session.cwd().catch(noop)
  const top = await toplevelOf($, cwd).catch(noop)
  for (const root of rootCandidates(env, cwd, top)) {
    const text = await $.fs.read(`${root}/${HARNESS_CONFIG_REL}`).catch(noop)
    if (typeof text === 'string') return { root, cfg: readConfig(text), sentinelRoot: await mainCheckoutOf($, root) }
  }
  return undefined
}
