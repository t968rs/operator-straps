import type { EngineInterface, FsEntry } from 'claude-code'
import { atom, read, update } from 'claude-code'

import { coreConfigOf, parseHarness, type CoreConfig, type HarnessJson } from './config'
import type { Io } from './layer'
import { HARNESS_CONFIG_REL, rootCandidates } from './root'

/**
 * The project the watch serves: its root (forward slashes), its core configuration, the whole parsed
 * `harness.json` (layers read their own keys from it), and the main checkout per-repository state (Phase 5
 * sentinels) lives under; the root itself outside a linked worktree.
 */
export type Watch = { root: string; cfg: CoreConfig; harness: HarnessJson; sentinelRoot: string }

const GIT_TIMEOUT_MS = 10_000

const runsAtom = atom({ plugin: 'agent-watcher', key: 'runs' } as const, {})
const activeAtom = atom({ plugin: 'agent-watcher', key: 'active' } as const, null)
const failuresAtom = atom({ plugin: 'agent-watcher', key: 'failures' } as const, [])
const phase5Atom = atom({ plugin: 'agent-watcher', key: 'phase5' } as const, [])
const missingAtom = atom({ plugin: 'agent-watcher', key: 'missing' } as const, [])

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
    if (typeof text !== 'string') continue
    const harness = parseHarness(text)
    return { root, cfg: coreConfigOf(harness), harness, sentinelRoot: await mainCheckoutOf($, root) }
  }
  return undefined
}

/** `git -C <root> <args>`: its trimmed stdout on exit 0, else undefined. */
async function gitLine($: EngineInterface, root: string, args: readonly string[]): Promise<string | undefined> {
  const ran = await $.process.run(['git', '-C', root, ...args], { timeoutMs: GIT_TIMEOUT_MS }).catch(noop)
  return ran !== undefined && ran.exitCode === 0 ? ran.stdout.trim() : undefined
}

/** The state members of an `Io`: one closure per state key, each over an atom the engine can see. */
function stateOf($: EngineInterface): Pick<
  Io, 'runs' | 'updateRuns' | 'activeRunId' | 'updateFailures' | 'setPhase5' | 'missing' | 'setMissing'
> {
  return {
    runs: () => read($, runsAtom),
    updateRuns: async change => {
      await update($, runsAtom, change)
    },
    activeRunId: () => read($, activeAtom),
    updateFailures: async change => {
      await update($, failuresAtom, change)
    },
    setPhase5: async keys => {
      await update($, phase5Atom, () => keys)
    },
    missing: () => read($, missingAtom),
    setMissing: async ids => {
      await update($, missingAtom, () => ids)
    },
  }
}

/**
 * The host for one project, as closures over `$`: what core hands a layer in place of the engine
 * (Decision D1). A function declaration, so the engine follows `$` into it from any module.
 */
export function ioOf($: EngineInterface, watch: Watch): Io {
  return {
    watch,
    readText: async path => {
      const raw = await $.fs.read(path).catch(noop)
      return typeof raw === 'string' ? raw : undefined
    },
    listDir: path => $.fs.list(path).catch(() => [] as FsEntry[]),
    exists: path => $.fs.exists(path).catch(noop),
    mtimeOf: async path => (await $.fs.stat(path).catch(noop))?.mtimeMs,
    write: (path, text) => $.fs.write(path, text).then(() => true, () => false),
    gitLine: args => gitLine($, watch.root, args),
    toast: text => Promise.resolve($.ui.toast(text)).then(noop, noop),
    now: () => $.clock.now(),
    ...stateOf($),
  }
}
