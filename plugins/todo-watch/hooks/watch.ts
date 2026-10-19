import type { EngineInterface } from 'claude-code'

import { isActive, readConfig, type TodoWatchConfig } from './config'
import { configPathOf, rootCandidates } from './root'

/** The project the watch serves: its root (forward slashes) and its harness configuration. */
export type Watch = { root: string; cfg: TodoWatchConfig }

const noop = (): undefined => undefined

/** Roots already found (null: none holds the file), by cwd and CLAUDE_PROJECT_DIR; a reload starts afresh. */
const roots = new Map<string, string | null>()

/** The first candidate (./root) whose `.claude/harness.json` reads, with its text; else undefined. */
async function findRoot($: EngineInterface, env: string | undefined, cwd: string | undefined) {
  for (const root of rootCandidates(env, cwd)) {
    const text = await $.fs.read(configPathOf(root)).catch(noop)
    if (typeof text === 'string') return { root, text }
  }
  return undefined
}

/** The root and its harness.json text, the root remembered per cwd; the file is read afresh each time. */
async function rootAndConfig($: EngineInterface): Promise<{ root: string; text: string } | undefined> {
  const env = await $.env.get('CLAUDE_PROJECT_DIR').catch(noop)
  const cwd = await $.session.cwd().catch(noop)
  const key = `${cwd ?? ''}\n${env ?? ''}`
  const known = roots.get(key)
  if (known === null) return undefined
  if (known !== undefined) {
    const text = await $.fs.read(configPathOf(known)).catch(noop)
    return typeof text === 'string' ? { root: known, text } : undefined
  }
  const found = await findRoot($, env, cwd)
  roots.set(key, found?.root ?? null)
  return found
}

/**
 * The watch for the session's project: active only when `.claude/harness.json` reads and `todo.catalog` is
 * a non-blank string; undefined otherwise. Never throws, never spawns a process. A function declaration:
 * the engine follows `$` past an import only into one.
 */
export async function resolveWatch($: EngineInterface): Promise<Watch | undefined> {
  const hit = await rootAndConfig($).catch(noop)
  if (hit === undefined) return undefined
  const cfg = readConfig(hit.text)
  return isActive(cfg) ? { root: hit.root, cfg } : undefined
}
