import type {
  EngineInterface,
  On,
  PromptSubmitInput,
  PromptSubmitResult,
  SessionCompactInput,
  SessionCompactResult,
} from 'claude-code'
import { atom, read, update } from 'claude-code'

import type { NoticeView, SyncFinding, SyncReport, TodoSummary } from '../types'
import { resetBand, setNoticeView, showBand } from './band'
import { inboxDirOf, isAbsolute, syncDirOf, under, type TodoWatchConfig } from './config'
import {
  awaitDrain, type DrainHost, hasQueued, isDraining, requestDrain, restorePending, takePending, TODO_EDITOR,
  waitCapMs,
} from './inbox'
import {
  contextLineFor, formatNotice, formatTodoBody, ghAgeText, isEmptyView, noticeText, parseCatalog,
  type SyncStatus,
} from './summary'
import { resolveWatch, type Watch } from './watch'

/**
 * Engine glue for todo-watch: the start notice and its live view, the runner pointer, gated and coalesced
 * check runs, the sync report (re-read only when its mtime moved) and the TODO_SYNC prompt line, plus the
 * triggers of the inbox drain (./inbox): a todo-editor agent's return and the prompt that carries its summary.
 * Active only in a project whose `.claude/harness.json` sets `todo.folder` (./watch). Every host failure
 * degrades to showing nothing; no hook throws into a tool call, a prompt or a turn. Functions taking `$`
 * are function declarations: the engine follows `$` past an import only into one.
 */

type Dollar = EngineInterface

// ---------------------------------------------------------------------------
// Contracts with the harness todo_sync engine (pinned by tests/mods/test_todo_watch_report_contract.py)

/** TodoSyncReport `schema_version` the mod reads; another version is ignored. */
export const REPORT_SCHEMA_VERSION = 1
/** Top-level report keys the mod reads: each must be present. */
export const REPORT_KEYS = [
  'schema_version', 'generated_at', 'drift', 'by_rule', 'counts', 'gh_fetched_at', 'findings',
] as const
/** `counts` keys the mod reads. */
export const COUNT_KEYS = ['error', 'warn'] as const
/** Finding keys the mod reads; `findingOf` reads each through `field`, which accepts no other key. */
export const FINDING_KEYS = [
  'rule', 'severity', 'counted', 'file', 'line', 'subject', 'message', 'fix',
] as const
/** Finding keys that must be present; the rest default to null. */
export const FINDING_REQUIRED = ['rule', 'severity', 'counted', 'file', 'message'] as const
/** Finding severities the mod accepts; a finding with another one is skipped. */
export const SEVERITIES = ['error', 'warn'] as const
/**
 * `rules_skipped` reason of a rule left out by `check --rules`: a report carrying it covers a subset of the
 * rules, not the whole project, and is ignored.
 */
export const SUBSET_REASON = 'not selected'
/** Runner pointer `schema_version` the mod reads. */
export const RUNNER_SCHEMA_VERSION = 1
/** Runner pointer keys that must be non-blank; `report` is optional. */
export const RUNNER_KEYS = ['python', 'script', 'project'] as const

/** Longest a check run may take before it is killed and fails open, in milliseconds. */
export const CHECK_TIMEOUT_MS = 20_000
/** Tools whose calls may change a watched file. */
export const WATCH_TOOLS = /^(Bash|PowerShell|Edit|Write|MultiEdit|NotebookEdit)$/
const SHELL_TOOLS = /^(Bash|PowerShell)$/

/** The interpreter, script, project and report the harness SessionStart hook recorded. */
export type Runner = { python: string; script: string; project: string; report: string | undefined }

type Json = Readonly<Record<string, unknown>>

const noop = (): undefined => undefined
const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)
const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0
const nonBlank = (v: unknown): string | undefined =>
  typeof v === 'string' && v.trim() !== '' ? v.trim() : undefined
const stringOrNull = (v: unknown): string | null => (typeof v === 'string' ? v : null)

const parseJson = (text: string): unknown => {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

// ---------------------------------------------------------------------------
// Pure: runner pointer and report

/** The runner pointer (`runner.json`); undefined when malformed or of another version. */
export const parseRunner = (text: string): Runner | undefined => {
  const data = parseJson(text)
  if (!isObject(data) || data.schema_version !== RUNNER_SCHEMA_VERSION) return undefined
  const [python, script, project] = RUNNER_KEYS.map(k => nonBlank(data[k]))
  if (python === undefined || script === undefined || project === undefined) return undefined
  return { python, script, project, report: nonBlank(data.report) }
}

type FindingKey = (typeof FINDING_KEYS)[number]
type Severity = (typeof SEVERITIES)[number]

/** A finding's value at one of `FINDING_KEYS`. */
const field = (v: Json, key: FindingKey): unknown => v[key]

const isSeverity = (v: unknown): v is Severity => SEVERITIES.some(s => s === v)

/** One finding; undefined when a required key is missing or mistyped. */
const findingOf = (v: unknown): SyncFinding | undefined => {
  if (!isObject(v) || !FINDING_REQUIRED.every(k => k in v)) return undefined
  const [rule, severity, counted, message] = [field(v, 'rule'), field(v, 'severity'), field(v, 'counted'),
    field(v, 'message')]
  if (typeof rule !== 'string' || typeof message !== 'string' || typeof counted !== 'boolean') return undefined
  if (!isSeverity(severity)) return undefined
  const line = field(v, 'line')
  return {
    rule, severity, counted, message, line: isCount(line) && line > 0 ? line : null,
    file: stringOrNull(field(v, 'file')), subject: stringOrNull(field(v, 'subject')),
    fix: stringOrNull(field(v, 'fix')),
  }
}

/** Whether a report's `rules_skipped` marks a `check --rules` run (`SUBSET_REASON`). */
const isSubsetRun = (skipped: unknown): boolean =>
  Array.isArray(skipped) && skipped.some(s => isObject(s) && s.reason === SUBSET_REASON)

/** Counted findings per rule id, positive whole numbers only. */
const byRuleOf = (v: Json): Record<string, number> =>
  Object.fromEntries(Object.entries(v).filter(([, n]) => isCount(n) && n > 0)) as Record<string, number>

/**
 * A TodoSyncReport text as the mod reads it; undefined when malformed, of another version, or written by a
 * `check --rules` run (its drift covers only the selected rules).
 */
export const parseReport = (text: string, mtimeMs: number): SyncReport | undefined => {
  const data = parseJson(text)
  if (!isObject(data) || !REPORT_KEYS.every(k => k in data)) return undefined
  if (data.schema_version !== REPORT_SCHEMA_VERSION || typeof data.generated_at !== 'string') return undefined
  if (isSubsetRun(data.rules_skipped)) return undefined
  const { drift, by_rule: byRule, counts, findings } = data
  if (!isCount(drift) || !isObject(byRule) || !isObject(counts) || !Array.isArray(findings)) return undefined
  return {
    generatedAt: data.generated_at, drift, byRule: byRuleOf(byRule),
    errors: isCount(counts[COUNT_KEYS[0]]) ? (counts[COUNT_KEYS[0]] as number) : 0,
    warns: isCount(counts[COUNT_KEYS[1]]) ? (counts[COUNT_KEYS[1]] as number) : 0,
    ghFetchedAt: stringOrNull(data.gh_fetched_at),
    findings: findings.map(findingOf).filter((f): f is SyncFinding => f !== undefined),
    mtimeMs,
  }
}

/** When the report was made: `generated_at`, else its file mtime. */
export const reportTimeMs = (r: SyncReport): number => {
  const at = Date.parse(r.generatedAt)
  return Number.isFinite(at) ? at : r.mtimeMs
}

// ---------------------------------------------------------------------------
// Pure: watched paths

/** The files a change to which re-checks: catalog, catalog schema, research catalog. */
export const watchedFiles = (w: Watch): string[] =>
  [w.cfg.catalog, w.cfg.catalogSchema, w.cfg.researchCatalog]
    .filter((p): p is string => p !== null)
    .map(p => under(w.root, p))

/** The folders under which a change re-checks: research, plans, snapshots. */
export const watchedDirs = (w: Watch): string[] =>
  [w.cfg.researchDir, w.cfg.plansDir, w.cfg.snapshotsDir]
    .filter((p): p is string => p !== null)
    .map(p => under(w.root, p))

/** Forward slashes, `.` and `..` folded, no trailing slash; the `/`, `//` or `C:/` head kept. */
export const normalPath = (raw: string): string => {
  const p = raw.trim().replace(/\\/g, '/')
  const head = /^([A-Za-z]:\/|\/\/|\/)/.exec(p)?.[0] ?? ''
  const segs: string[] = []
  for (const s of p.slice(head.length).split('/')) {
    if (s === '' || s === '.') continue
    if (s === '..' && segs.length > 0 && segs[segs.length - 1] !== '..') segs.pop()
    else segs.push(s)
  }
  return `${head}${segs.join('/')}`
}

const isWindowsStyle = (p: string): boolean => /^([A-Za-z]:|\/\/)/.test(p)

/**
 * Whether a tool's path (absolute, or relative to the project root) is a watched file or lies under a
 * watched folder; case-insensitive on a Windows-style root.
 */
export const isWatchedPath = (w: Watch, raw: string): boolean => {
  if (raw.trim() === '') return false
  const path = normalPath(isAbsolute(raw.trim()) ? raw : `${w.root}/${raw}`)
  const fold = isWindowsStyle(w.root) || isWindowsStyle(path)
  const key = (p: string): string => (fold ? normalPath(p).toLowerCase() : normalPath(p))
  const target = fold ? path.toLowerCase() : path
  return (
    watchedFiles(w).some(f => key(f) === target) ||
    watchedDirs(w).some(d => target.startsWith(`${key(d)}/`))
  )
}

/** The path a file tool names: `file_path`, or `notebook_path` for NotebookEdit; undefined for a shell. */
type PathCall = { tool: unknown; file_path?: unknown; notebook_path?: unknown }

export const pathOfCall = (e: PathCall): string | undefined => {
  const raw = String(e.tool) === 'NotebookEdit' ? e.notebook_path : e.file_path
  return typeof raw === 'string' ? raw : undefined
}

// ---------------------------------------------------------------------------
// State

const summaryAtom = atom({ plugin: 'todo-watch', key: 'summary' } as const, null)
const reportAtom = atom({ plugin: 'todo-watch', key: 'report' } as const, null)
const lastContextAtom = atom({ plugin: 'todo-watch', key: 'lastContext' } as const, '')

/** Per-load session bookkeeping (a reload starts afresh; its `session.start` fires again). */
const session = {
  startedAtMs: undefined as number | undefined,
  status: 'pending' as SyncStatus,
  /** The runner lookup in flight, so a retry is made once. */
  lookup: undefined as Promise<Runner | undefined> | undefined,
  runner: undefined as Runner | undefined,
  catalogMtime: undefined as number | undefined,
  reportMtime: undefined as number | undefined,
  lastCheckStart: undefined as number | undefined,
  /** The next prompt gets the context line even when unchanged: a new conversation, or a compacted one. */
  isContextForced: true,
}

/**
 * One check run at a time. `isRunning`: the engine process has started, so a request now is owed one run
 * after it; a request before that folds into the run, which reads the files afresh anyway.
 */
const pacing = { isBusy: false, isRunning: false, isOwed: false }

// ---------------------------------------------------------------------------
// Host access

async function readText($: Dollar, path: string): Promise<string | undefined> {
  const raw = await $.fs.read(path).catch(noop)
  return typeof raw === 'string' ? raw : undefined
}

async function mtimeOf($: Dollar, path: string): Promise<number | undefined> {
  const st = await $.fs.stat(path).catch(noop)
  return st === undefined ? undefined : st.mtimeMs
}

/**
 * Shows the start notice as `todo.notice.style` says: the band, kept until Dismiss with its view live, or one
 * toast of the view as it stands for `todo.notice.toast_seconds` (a click takes it off sooner, the pointer
 * over it holds it). An empty view shows nothing. Never throws.
 */
async function showNotice($: Dollar, cfg: TodoWatchConfig, view: NoticeView): Promise<void> {
  if (isEmptyView(view)) return
  if (cfg.noticeStyle === 'banner') return showBand($)
  try {
    void Promise.resolve($.ui.toast(noticeText(view), { timeoutMs: cfg.toastMs })).catch(noop)
  } catch {
    // a surface that draws no toast
  }
}

/**
 * Recomputes the notice view from the summary, the fresh report and the checks status, and stores it: a
 * shown band follows it; nothing is shown again. Never throws.
 */
async function refreshView($: Dollar, w: Watch): Promise<NoticeView> {
  const summary = await read($, summaryAtom).catch(() => null)
  const report = await read($, reportAtom).catch(() => null)
  const view = formatNotice(summary, report, session.status, w.cfg.noticeItems)
  await setNoticeView($, view)
  return view
}

/** Runs `fn` after the current dispatch, so no tool result or prompt waits on it. */
function later($: Dollar, fn: () => Promise<unknown>): void {
  try {
    $.clock.after(0, () => {
      void fn().catch(noop)
    })
  } catch {
    // no timer: this pass is skipped
  }
}

const runnerPathOf = (w: Watch): string => `${under(w.root, syncDirOf(w.cfg))}/runner.json`
const reportPathOf = (w: Watch): string =>
  session.runner?.report ?? `${under(w.root, syncDirOf(w.cfg))}/report.json`

/** The runner pointer, when it reads and its script exists; undefined otherwise. */
async function lookupRunner($: Dollar, w: Watch): Promise<Runner | undefined> {
  const text = await readText($, runnerPathOf(w))
  const runner = text === undefined ? undefined : parseRunner(text)
  if (runner === undefined) return undefined
  return (await $.fs.exists(runner.script).catch(() => false)) ? runner : undefined
}

// ---------------------------------------------------------------------------
// Catalog and report

/**
 * Re-reads the catalog when its mtime moved, keeping enough rows for `/todo` and the notice; an unreadable
 * or malformed one clears the summary. A re-read recomputes the notice view.
 */
async function refreshCatalog($: Dollar, w: Watch): Promise<TodoSummary | null> {
  const path = under(w.root, w.cfg.catalog ?? '')
  const mtime = await mtimeOf($, path)
  if (mtime !== undefined && mtime === session.catalogMtime) return read($, summaryAtom)
  session.catalogMtime = mtime
  const text = mtime === undefined ? undefined : await readText($, path)
  const rows = Math.max(w.cfg.topN, w.cfg.noticeItems)
  const summary = text === undefined ? null : (parseCatalog(text, rows, mtime ?? 0) ?? null)
  await update($, summaryAtom, () => summary)
  await refreshView($, w)
  return summary
}

/** Stores a fresh report and recomputes the notice view; shows nothing. */
async function applyReport($: Dollar, w: Watch, report: SyncReport): Promise<void> {
  await update($, reportAtom, () => report)
  await refreshView($, w)
}

/**
 * The session start floored to the whole second: the earliest `generated_at` a fresh report may carry, as
 * an engine that writes whole seconds stamps a check finishing in the start's own second before the start.
 */
export const startGateMs = (startedAtMs: number): number => Math.floor(startedAtMs / 1000) * 1000

/**
 * Re-reads the report when its mtime moved (always after a check run of the mod's own, `isForced`, as a
 * coarse file clock may not move between two runs); one older than the session start's second is ignored.
 */
async function refreshReport($: Dollar, w: Watch, isForced = false): Promise<void> {
  const path = reportPathOf(w)
  const mtime = await mtimeOf($, path)
  if (mtime === undefined || (mtime === session.reportMtime && !isForced)) return
  session.reportMtime = mtime
  const text = await readText($, path)
  const report = text === undefined ? undefined : parseReport(text, mtime)
  if (report === undefined || reportTimeMs(report) < startGateMs(session.startedAtMs ?? 0)) return
  await applyReport($, w, report)
}

// ---------------------------------------------------------------------------
// Check runs: one in flight, an owed rerun

/** Runs `todo_sync.py check`; true on exit 0, false on any failure (refusal, timeout, non-zero exit). */
async function runEngine($: Dollar, r: Runner): Promise<boolean> {
  const argv = [r.python, r.script, 'check', '--project', r.project]
  return $.process.run(argv, { timeoutMs: CHECK_TIMEOUT_MS }).then(ran => ran.exitCode === 0, () => false)
}

/** One check: the pointer looked up again (it may have gone stale), the run, then the re-reads. */
async function runCycle($: Dollar): Promise<void> {
  const w = await resolveWatch($)
  const runner = w === undefined ? undefined : await lookupRunner($, w)
  if (w === undefined || runner === undefined) return
  session.runner = runner
  session.status = 'found'
  await refreshView($, w)
  session.lastCheckStart = await $.clock.now()
  pacing.isRunning = true
  const isOk = await runEngine($, runner)
  await refreshCatalog($, w).catch(noop)
  if (isOk) await refreshReport($, w, true)
}

/** Asks for a check run and returns at once; folds into a run already scheduled or in flight. */
function requestCheck($: Dollar): void {
  if (pacing.isBusy) {
    if (pacing.isRunning) pacing.isOwed = true
    return
  }
  pacing.isBusy = true
  void runCycle($)
    .catch(noop)
    .finally(() => finishCycle($))
}

/** Ends a run and starts the one owed, if any. */
function finishCycle($: Dollar): void {
  pacing.isBusy = false
  pacing.isRunning = false
  if (!pacing.isOwed) return
  pacing.isOwed = false
  requestCheck($)
}

/** The newest mtime among the entries of `dir`, and of its subfolders' entries `depth` levels further down. */
async function newestListed($: Dollar, dir: string, depth: number): Promise<number> {
  let newest = Number.NEGATIVE_INFINITY
  for (const entry of await $.fs.list(dir).catch(() => [])) {
    newest = Math.max(newest, entry.mtimeMs)
    if (depth > 0 && entry.kind === 'dir') {
      newest = Math.max(newest, await newestListed($, `${dir}/${entry.name}`, depth - 1))
    }
  }
  return newest
}

/**
 * The newest mtime among the watched files, the watched folders and their top-level entries; under the
 * research folder one level deeper too, where the `<DOMAIN>/<stub>` files live, so an in-place stub edit
 * outside the session trips the probe.
 */
async function newestWatchedMtime($: Dollar, w: Watch): Promise<number> {
  let newest = Number.NEGATIVE_INFINITY
  for (const path of [...watchedFiles(w), ...watchedDirs(w)]) {
    newest = Math.max(newest, (await mtimeOf($, path)) ?? newest)
  }
  const research = under(w.root, w.cfg.researchDir)
  for (const dir of watchedDirs(w)) {
    newest = Math.max(newest, await newestListed($, dir, dir === research ? 1 : 0))
  }
  return newest
}

/** Schedules a check when a watched mtime is newer than the last check start (else the last report). */
async function probeWatched($: Dollar, w: Watch): Promise<void> {
  if (session.status !== 'found') return
  const basis = session.lastCheckStart ?? session.reportMtime ?? Number.NEGATIVE_INFINITY
  if ((await newestWatchedMtime($, w)) > basis) requestCheck($)
}

// ---------------------------------------------------------------------------
// Session start and the runner retry

/** Forgets the previous start's report and band; the start time is now. */
async function resetSession($: Dollar, w: Watch): Promise<void> {
  session.startedAtMs = await $.clock.now()
  session.status = 'pending'
  session.lookup = undefined
  session.runner = undefined
  session.catalogMtime = undefined
  session.reportMtime = undefined
  session.lastCheckStart = undefined
  session.isContextForced = true
  await update($, reportAtom, () => null).catch(noop)
  await resetBand($)
  await refreshView($, w)
}

/**
 * `session.start` (wired in ./register): the start notice (items, no status before a fresh report), then the
 * runner lookup and the first check. Never throws.
 */
export async function startSession($: Dollar): Promise<void> {
  await startWatch($).catch(noop)
}

async function startWatch($: Dollar): Promise<void> {
  const w = await resolveWatch($)
  if (w === undefined) return
  await resetSession($, w)
  await refreshCatalog($, w).catch(noop)
  await showNotice($, w.cfg, await refreshView($, w))
  const runner = await lookupRunner($, w).catch(noop)
  if (runner === undefined) return
  session.runner = runner
  session.status = 'found'
  await refreshView($, w)
  later($, async () => requestCheck($))
}

/** The one retry of a runner pointer missing at `session.start` (single-flight): found, else unavailable. */
async function retryLookup($: Dollar, w: Watch): Promise<void> {
  if (session.status !== 'pending') return
  if (session.startedAtMs === undefined) session.startedAtMs = await $.clock.now()
  const isFirst = session.lookup === undefined
  session.lookup ??= lookupRunner($, w).catch(noop)
  const runner = await session.lookup
  if (!isFirst || session.status !== 'pending') return
  session.runner = runner
  session.status = runner === undefined ? 'unavailable' : 'found'
  await refreshView($, w)
  if (runner !== undefined) later($, async () => requestCheck($))
}

/** Prompt and turn triggers (M3b): the retry, then, after the dispatch, the catalog and the mtime probe. */
async function onTrigger($: Dollar, w: Watch): Promise<void> {
  await retryLookup($, w)
  later($, async () => {
    await refreshCatalog($, w).catch(noop)
    await probeWatched($, w)
  })
}

// ---------------------------------------------------------------------------
// Prompt context

/** This prompt's TODO_SYNC line when it should be attached; records nothing. */
async function promptLine($: Dollar): Promise<string | undefined> {
  const w = await resolveWatch($)
  if (w === undefined) return undefined
  await onTrigger($, w)
  await refreshReport($, w).catch(noop)
  if (!w.cfg.injectContext) return undefined
  const line = contextLineFor(await read($, reportAtom), session.status)
  if (line === undefined || session.isContextForced) return line
  return (await read($, lastContextAtom).catch(() => '')) === line ? undefined : line
}

/** Records `line` as attached, once the prompt entered with it and the dispatch did not move on. */
async function recordAttached($: Dollar, line: string, result: PromptSubmitResult, signal: AbortSignal) {
  if (signal.aborted || result.drop !== undefined || !(result.context ?? []).includes(line)) return
  session.isContextForced = false
  await update($, lastContextAtom, () => line).catch(noop)
}

/** Session-end reasons after which the same process goes on with a fresh conversation. */
const FRESH_CONVERSATION = new Set<string>(['clear', 'resume'])

/** Whether a compaction result replaced the main conversation (its TODO_SYNC line may be gone). */
const isMainCompaction = (e: SessionCompactInput, result: SessionCompactResult): boolean =>
  result.skip === undefined && e.agentId === undefined && e.trigger !== 'precompute'

// ---------------------------------------------------------------------------
// The /todo body

/** The `/todo` text for the session's project, catalog and report re-read when moved; undefined inactive. */
export async function todoText($: Dollar): Promise<string | undefined> {
  const w = await resolveWatch($)
  if (w === undefined) return undefined
  const summary = await refreshCatalog($, w).catch(() => null)
  await refreshReport($, w).catch(noop)
  const report = await read($, reportAtom)
  const now = await $.clock.now()
  const ghAge = report === null ? undefined : ghAgeText(report.ghFetchedAt, now, w.cfg.ghMaxAgeHours)
  const sync = report === null ? {} : { drift: report.drift, ghAge }
  return formatTodoBody(summary, report, session.status, sync, w.cfg.topN)
}

// ---------------------------------------------------------------------------
// Tool calls (M3)

type CallSeen = { tool: string; path: string | undefined; isRefused: boolean }

/** After a watching tool's call: a file tool on a watched path checks; a shell call probes mtimes. */
async function afterToolCall($: Dollar, call: CallSeen): Promise<void> {
  const w = await resolveWatch($)
  if (w === undefined) return
  if (SHELL_TOOLS.test(call.tool)) return probeWatched($, w)
  if (!call.isRefused && call.path !== undefined && isWatchedPath(w, call.path)) requestCheck($)
}

// ---------------------------------------------------------------------------
// Inbox drains (./inbox)

/** What an Agent result carries that the drain trigger reads. */
type AgentOutcome = { status?: unknown }

/** The drain's host: the runner pointer looked up afresh (it may have gone stale), a check after a drain. */
function drainHostOf($: Dollar): DrainHost {
  return {
    runner: async () => {
      const w = await resolveWatch($)
      return w === undefined ? undefined : lookupRunner($, w)
    },
    refresh: () => requestCheck($),
  }
}

/** Starts a drain (marked in flight before this returns); resolves once it has ended. Never rejects. */
function startDrain($: Dollar): Promise<void> {
  return requestDrain($, drainHostOf($)).catch(noop)
}

/**
 * A foreground todo-editor returned: starts a drain unless one is running (its own turn end started the one
 * covering its items; an item queued after that drain listed the inbox gets its rerun from its writer's turn
 * end), and waits for it at most `capMs`; the summaries waiting, taken only while the dispatch is live (an
 * abandoned one leaves them for a prompt to take).
 */
async function drainForResult($: Dollar, signal: AbortSignal, capMs: number): Promise<string[]> {
  if (!isDraining()) void startDrain($)
  await awaitDrain($, capMs)
  return signal.aborted ? [] : takePending()
}

/**
 * Starts a drain, without waiting on it, when the inbox folder lists a queued item: at `session.start` (wired
 * in ./register, after `startSession`) and at any subagent's turn end. Never throws.
 */
export async function drainQueued($: Dollar): Promise<void> {
  const w = await resolveWatch($).catch(noop)
  if (w === undefined || !(await hasQueued($, under(w.root, inboxDirOf(w.cfg))).catch(() => false))) return
  void startDrain($)
}

/** This prompt's inbox summaries, taken; a task notification first waits for a drain in flight, up to `capMs`. */
async function inboxLines($: Dollar, isNotification: boolean, capMs: number): Promise<string[]> {
  if (isNotification) await awaitDrain($, capMs)
  return takePending()
}

/**
 * Hands back the summaries the prompt did not enter with: all of them when the dispatch was abandoned or the
 * prompt dropped, else those missing from its context.
 */
function restoreUnattached(lines: readonly string[], result: PromptSubmitResult, signal: AbortSignal): void {
  if (signal.aborted || result.drop !== undefined) return restorePending(lines)
  const context = result.context ?? []
  restorePending(lines.filter(line => !context.includes(line)))
}

/** The prompt as received, for a dispatch already abandoned: `next` is not called after that. */
const asReceived = (e: PromptSubmitInput): PromptSubmitResult =>
  ({ text: e.text, context: e.context, origin: e.origin })

// ---------------------------------------------------------------------------
// Registration

/** Tool and turn hooks: gated check runs, the M3b mtime probe and the inbox drain triggers. */
export const registerChecks = (on: On): void => {
  on('tool.call', { tool: WATCH_TOOLS }, async ($, e, next) => {
    const result = await next(e)
    const isRefused = result.deny !== undefined || result.isError === true
    const call: CallSeen = { tool: String(e.tool), path: pathOfCall(e), isRefused }
    later($, () => afterToolCall($, call))
    return result
  }).catch((_$, e, next) => next(e))

  // No `.catch` fallback: `next` is called once, first, and the body below it does not throw. Past the budget
  // the engine keeps that `next` result; the drain wait is capped short of the budget all the same.
  on('tool.call', { tool: 'Agent' }, async ($, e, next) => {
    const result = await next(e)
    if (e.subagent_type !== TODO_EDITOR) return result
    // Refusals inline (not a helper) so the checker narrows `result` to one that takes context.
    if (result.deny !== undefined || result.isError === true) return result
    if ((result.result as AgentOutcome | undefined)?.status !== 'completed') return result
    const capMs = waitCapMs(next.budget.remainingMs)
    const lines = await drainForResult($, next.signal, capMs).catch(() => [] as string[])
    return lines.length === 0 ? result : { ...result, context: [...(result.context ?? []), ...lines] }
  })

  // A subagent's turn end (foreground, background or continued) drains what it queued: the listing starts
  // before `next`, so the drain is in flight before the turn end returns and a task notification waits for it.
  on('turn.complete', async ($, e, next) => {
    const queued = e.agentId === undefined ? undefined : drainQueued($).catch(noop)
    const result = await next(e)
    if (queued !== undefined) {
      await queued
      return result
    }
    const w = await resolveWatch($).catch(noop)
    if (w !== undefined) await onTrigger($, w).catch(noop)
    return result
  })
}

/**
 * The TODO_SYNC line on prompts (M2) and its re-force after `/clear`, a resume or a main compaction; the inbox
 * summaries waiting, taken (a task notification first waits for a drain in flight, within the hook's budget)
 * and handed back when the prompt did not enter with them. Once the dispatch is abandoned (its budget spent,
 * the `.catch` having run `next`) the body never calls `next`.
 */
export const registerContext = (on: On): void => {
  on('prompt.submit', async ($, e, next) => {
    const line = await promptLine($).catch(noop)
    const isNotification = e.origin?.kind === 'task-notification'
    const capMs = waitCapMs(next.budget.remainingMs)
    const inbox = await inboxLines($, isNotification, capMs).catch(() => [] as string[])
    if (next.signal.aborted) {
      restorePending(inbox)
      return asReceived(e)
    }
    const lines = line === undefined ? inbox : [line, ...inbox]
    if (lines.length === 0) return next(e)
    let result: PromptSubmitResult
    try {
      result = await next({ ...e, context: [...(e.context ?? []), ...lines] })
    } catch (err) {
      restorePending(inbox)
      throw err
    }
    restoreUnattached(inbox, result, next.signal)
    if (line !== undefined) await recordAttached($, line, result, next.signal).catch(noop)
    return result
  }).catch((_$, e, next) => next(e))

  on('session.end', async ($, e, next) => {
    if (FRESH_CONVERSATION.has(e.reason)) session.isContextForced = true
    return next(e)
  }).catch((_$, e, next) => next(e))

  on('session.compact', async ($, e, next) => {
    const result = await next(e)
    if (isMainCompaction(e, result)) session.isContextForced = true
    return result
  }).catch((_$, e, next) => next(e))
}
