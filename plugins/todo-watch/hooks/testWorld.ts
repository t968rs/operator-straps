/**
 * The mocked world beneath todo-watch for the hook tests (never imported by ./register): files by path,
 * the harness engine behind `$.process.run`, band notices, command registrations and the tools a call
 * reaches.
 * The plugin test sandbox reads no repository file, so every `$` call the mod makes is answered here.
 * Paths are keyed without a drive letter (or the host prefix the engine resolves one onto) and case-folded,
 * so `C:/repo` and `/repo` roots share one world on a Windows or a POSIX host (`keyOf`).
 */

import type { FsEntry, On, ProcessRunInit, ProcessRunResult } from 'claude-code'
import type { Engine, MockClock } from 'claude-code/testing'
import { mock } from 'claude-code/testing'

export const NOW = 1_800_000_000_000
export const SCRIPT = '/plugins/harness/scripts/todo_sync.py'
export const PYTHON = '/usr/bin/python3'
export const TODO_DIR = 'docs/RESEARCH/_TODO'
export const CATALOG_REL = `${TODO_DIR}/RepoToDo.json`
export const RESEARCH_CATALOG_REL = `${TODO_DIR}/ResearchImplementationCatalog.json`
export const SNAPSHOTS_REL = `${TODO_DIR}/Snapshots`
export const SYNC_REL = '.claude/state/harness/todo-sync'

/** The whole `todo` block a project needs: every other path takes its default under the folder. */
export const CONFIG = { todo: { folder: TODO_DIR } }

/** How the engine's check run ends. */
export type EngineMode = 'ok' | 'timeout' | 'fail'

export type WorldOpts = {
  /** The project root env and cwd answer with; `/repo` when not given. */
  root?: string
  /** The session cwd; the root when not given. */
  cwd?: string
  /** The environment; CLAUDE_PROJECT_DIR is the root when not given. */
  env?: Record<string, string>
  /** `harness.json` at the root: an object, a raw text, or null for no file. */
  config?: Record<string, unknown> | string | null
  /** Whether `runner.json` is there from the start. */
  hasRunner?: boolean
  /** The TODO catalog text; null for no file. */
  catalog?: string | null
}

type Rec = { text: string; mtimeMs: number }

export type World = {
  root: string
  files: Map<string, Rec>
  /** Every `$.fs.read` path, as asked. */
  reads: string[]
  /** Every `$.process.run` argv. */
  runs: string[][]
  /** Every `$.process.run` init (timeout, env), index for index with `runs`. */
  inits: Array<ProcessRunInit | undefined>
  /** Every notice posted to the band, in order (a clear posts none). */
  notices: string[]
  commands: string[]
  descriptions: string[]
  /** `$.command.register` is refused. */
  isRegisterRefused: boolean
  clock: MockClock
  engine: { mode: EngineMode; drift: number; byRule: Record<string, number>; isHeld: boolean; reports: number }
  /** Check runs held while `engine.isHeld`: release them in order. */
  held: Array<() => void>
  /** Writes a file; its mtime is the clock's now unless given. */
  setFile: (path: string, text: string, mtimeMs?: number) => void
  /** Moves a file's mtime to the clock's now unless given. */
  touch: (path: string, mtimeMs?: number) => void
  addRunner: () => void
  /** Runs inside the Bash tool beneath, before it answers. */
  onBash: () => void
}

/**
 * A path's host-independent key: forward slashes, case-folded, everything up to and including a drive letter
 * dropped. On Windows the engine resolves a drive-less path (`/repo`) onto the current drive (`E:/repo`); on
 * Linux it resolves a drive-letter path (`C:/repo`) against the plugin folder (`/.../todo-watch/C:/repo`).
 * Both spellings key as `/repo`, so the mocked files answer the path the hook asked for on either host.
 */
export const keyOf = (p: string): string =>
  p.replace(/\\/g, '/').replace(/^(?:[^]*?\/)?[A-Za-z]:(?=\/|$)/, '').toLowerCase()
const ran = (stdout: string, exitCode = 0): ProcessRunResult => ({
  exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})

export const catalogText = (items = 89): string =>
  JSON.stringify({
    counts: { items, needs_decision: 12, by_status: { OPEN: 68, PARTIAL: 12, NEEDS_DECISION: 8, BLOCKED: 1 } },
    items: [
      { id: 'TODO-002', rank: 2, title: 'Second', status: 'PARTIAL', priority: { score: 70 } },
      { id: 'TODO-001', rank: 1, title: 'First', status: 'OPEN', priority: { score: 88 } },
    ],
  })

export const CATALOG_LINE = 'TODO 89 · 68 open · 12 partial · 1 blocked · 12 need a decision · top: First'

/**
 * A TodoSyncReport as the engine writes it, with generated_at floored to whole seconds: the coarsest stamp the
 * mod accepts (an engine writing seconds only), which the start gate must still let through.
 */
export const reportText = (generatedMs: number, drift: number, byRule: Record<string, number>): string =>
  JSON.stringify({
    schema_version: 1, generated_at: new Date(Math.floor(generatedMs / 1000) * 1000).toISOString(),
    rules_run: Object.keys(byRule),
    rules_skipped: [], drift, by_rule: byRule, counts: { error: drift, warn: 0 }, gh_fetched_at: null,
    findings: Object.keys(byRule).map(rule => ({
      rule, severity: 'error', counted: true, file: 'docs/PLANS/a_PIP.md', line: 3, subject: 'X-1',
      message: `${rule} broke`, fix: null,
    })),
  })

/** Entries directly under `dir`: its files, and its subfolders (mtime 0, as a listing gives them). */
const listing = (files: Map<string, Rec>, dir: string): FsEntry[] => {
  const prefix = `${keyOf(dir)}/`
  const out = new Map<string, FsEntry>()
  for (const [key, rec] of files) {
    if (!key.startsWith(prefix)) continue
    const rest = key.slice(prefix.length)
    const name = rest.split('/')[0] ?? rest
    const isFile = !rest.includes('/')
    out.set(name, {
      name, kind: isFile ? 'file' : 'dir', size: isFile ? rec.text.length : 0, mtimeMs: isFile ? rec.mtimeMs : 0,
      isLink: false,
    })
  }
  return [...out.values()]
}

const isDir = (files: Map<string, Rec>, path: string): boolean =>
  [...files.keys()].some(k => k.startsWith(`${keyOf(path)}/`))

function fsHooks(on: On, w: World): void {
  on('fs.read', (_$, e) => {
    w.reads.push(e.path)
    const rec = w.files.get(keyOf(e.path))
    return rec === undefined ? { deny: 'ENOENT' } : { value: rec.text }
  })
  on('fs.stat', (_$, e) => {
    const rec = w.files.get(keyOf(e.path))
    if (rec !== undefined) return { value: { kind: 'file', size: rec.text.length, mtimeMs: rec.mtimeMs, isLink: false } }
    if (isDir(w.files, e.path)) return { value: { kind: 'dir', size: 0, mtimeMs: NOW - 3_600_000, isLink: false } }
    return { deny: 'ENOENT' }
  })
  on('fs.exists', (_$, e) => ({ value: w.files.has(keyOf(e.path)) || isDir(w.files, e.path) }))
  on('fs.list', (_$, e) => (isDir(w.files, e.path) ? { value: listing(w.files, e.path) } : { deny: 'ENOENT' }))
}

/** The engine's check run: writes the report (unless it fails) and answers per `engine.mode`. */
async function check(w: World): Promise<{ value: ProcessRunResult } | { deny: string }> {
  if (w.engine.isHeld) await new Promise<void>(resolve => w.held.push(resolve))
  if (w.engine.mode === 'timeout') return { deny: 'process timed out after 20000 ms' }
  if (w.engine.mode === 'fail') return { value: ran('', 2) }
  const now = w.clock.now()
  // a distinct mtime per report, as the mocked clock stands still between calls
  w.engine.reports += 1
  const text = reportText(now, w.engine.drift, w.engine.byRule)
  w.setFile(`${w.root}/${SYNC_REL}/report.json`, text, now + w.engine.reports)
  return { value: ran('{"ignored": true}') }
}

function engineHooks(on: On, w: World): void {
  on('process.run', async (_$, e) => {
    w.runs.push([...e.argv])
    w.inits.push(e.init)
    return e.argv[2] === 'check' ? check(w) : { value: ran('', 128) }
  })
  on('state.set', { plugin: 'todo-watch', key: 'notices' }, (_$, e, next) => {
    const list = e.value
    if (list.length > 0) w.notices.push(list[list.length - 1])
    return next(e)
  })
  on('command.register', (_$, e) => {
    if (w.isRegisterRefused) return { deny: 'name taken' }
    w.commands.push(e.name)
    w.descriptions.push(e.description)
    return { value: { command: e.name } }
  })
}

/** Core's echo for the session events the hooks pass on, and the tools beneath. */
function bottoms(on: On, w: World): void {
  on('prompt.submit', (_$, e) => ({ text: e.text, context: e.context }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
  on('session.compact', (_$, e) => ({ messages: e.messages }))
  on('tool.call', { tool: /^(Bash|PowerShell)$/ }, () => {
    w.onBash()
    return { result: { stdout: '', stderr: '', interrupted: false } } as never
  })
  on('tool.call', { tool: 'Write' }, (_$, e) => {
    w.setFile(e.file_path, e.content)
    const result = { type: 'create', filePath: e.file_path, content: e.content, structuredPatch: [], originalFile: null }
    return { result } as never
  })
  on('tool.call', { tool: /^(Edit|NotebookEdit)$/ }, () => ({ result: {} }) as never)
}

function seed(w: World, opts: WorldOpts): void {
  const config = opts.config === undefined ? CONFIG : opts.config
  if (config !== null) {
    w.setFile(`${w.root}/.claude/harness.json`, typeof config === 'string' ? config : JSON.stringify(config), 1)
  }
  const catalog = opts.catalog === undefined ? catalogText() : opts.catalog
  if (catalog !== null) w.setFile(`${w.root}/${CATALOG_REL}`, catalog, NOW - 60_000)
  w.setFile(`${w.root}/${RESEARCH_CATALOG_REL}`, '{}', NOW - 60_000)
  w.setFile(`${w.root}/docs/PLANS/a_ActionPlan.json`, '{}', NOW - 60_000)
  w.setFile(`${w.root}/${SNAPSHOTS_REL}/TODO_Snapshot_2026_1017.md`, '# x', NOW - 60_000)
  w.setFile(SCRIPT, '# engine', 1)
  if (opts.hasRunner !== false) w.addRunner()
}

/** Builds the world on the test's `on`. */
export function world(on: On, opts: WorldOpts = {}): World {
  const root = opts.root ?? '/repo'
  const files = new Map<string, Rec>()
  const w: World = {
    root, files, reads: [], runs: [], inits: [], notices: [], commands: [], descriptions: [], isRegisterRefused: false,
    held: [],
    clock: mock.clock(on, { now: NOW }),
    engine: { mode: 'ok', drift: 0, byRule: {}, isHeld: false, reports: 0 },
    setFile: (path, text, mtimeMs) => files.set(keyOf(path), { text, mtimeMs: mtimeMs ?? w.clock.now() }),
    touch: (path, mtimeMs) => {
      const rec = files.get(keyOf(path))
      if (rec !== undefined) files.set(keyOf(path), { ...rec, mtimeMs: mtimeMs ?? w.clock.now() })
    },
    addRunner: () => w.setFile(`${root}/${SYNC_REL}/runner.json`, JSON.stringify({
      schema_version: 1, python: PYTHON, script: SCRIPT, project: root,
      report: `${root}/${SYNC_REL}/report.json`, written_at: new Date(NOW).toISOString(),
    })),
    onBash: () => undefined,
  }
  mock.env(on, opts.env ?? { CLAUDE_PROJECT_DIR: root })
  on('session.cwd', () => ({ value: opts.cwd ?? root }))
  fsHooks(on, w)
  engineHooks(on, w)
  bottoms(on, w)
  seed(w, opts)
  return w
}

/** The check runs among the process runs. */
export const checkRuns = (w: World): string[][] => w.runs.filter(argv => argv[2] === 'check')

// ---------------------------------------------------------------------------
// Raising events

export const submit = { text: 'hello', wait: false, origin: { kind: 'composer' } } as const

/** `session.start`, then every wait due now (the first check included). */
export async function start($: Engine, w: World): Promise<void> {
  await $.session.start({ cwd: w.root, surface: null, isInteractive: false })
  await w.clock.settle()
}

/** A prompt, then the work it scheduled; answers the context it entered with. */
export async function prompt($: Engine, w: World): Promise<readonly string[]> {
  const out = await $.prompt.submit(submit)
  await w.clock.settle()
  return 'context' in out ? (out.context ?? []) : []
}

export async function turnEnd($: Engine, w: World): Promise<void> {
  await $.turn.complete({ answer: 'ok', durationMs: 5, isAborted: false, turnId: 't1', reason: 'answer' })
  await w.clock.settle()
}

export async function runTodo($: Engine): Promise<string> {
  const r = await $.command.run({
    command: 'todo', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 },
  })
  return r.text ?? ''
}
