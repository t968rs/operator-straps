import type {
  EngineInterface,
  PromptSubmitResult,
  Register,
  SessionCompactInput,
  SessionCompactResult,
} from 'claude-code'
import { atom, read, update } from 'claude-code'

import type { GitSnapshot } from '../types'

/**
 * Cross-platform git status line and per-prompt git context.
 *
 * The project root is `git rev-parse --show-toplevel` from the session cwd (else CLAUDE_PROJECT_DIR);
 * the per-prompt line is attached only when it changed since the last one attached. Every failure path
 * (no root, no git, not a repo) clears the status and never throws.
 */

type Dollar = EngineInterface

const gitState = atom({ plugin: 'git-status', key: 'git' } as const, null)
const lastContext = atom({ plugin: 'git-status', key: 'lastContext' } as const, '')

/** Minimum gap between two background git runs, in milliseconds. */
export const MIN_GAP_MS = 2000
/** Background refresh period while the session is open, in milliseconds. */
export const TICK_MS = 60_000
const MAX_STATUS = 80
const MAX_BRANCH = 32
const GIT_TIMEOUT_MS = 10_000
/**
 * Longest wait, in milliseconds, a prompt gives a background git run in flight before it runs its own:
 * that wait is no `$` call of the hook's, so it counts against the hook's 10 s budget.
 */
export const TAIL_WAIT_MS = 2000
const REFRESH_TOOLS = /^(Bash|PowerShell|Edit|Write|MultiEdit|NotebookEdit)$/

// ---------------------------------------------------------------------------
// Pure parsing and formatting

/** Parses `git status --porcelain=v2 --branch` output; unknown lines are ignored. */
export const parsePorcelain = (stdout: string): GitSnapshot => {
  const out: GitSnapshot = {
    branch: '', upstream: null, ahead: 0, behind: 0, staged: 0, unstaged: 0, untracked: 0,
  }
  for (const raw of stdout.split(/\r?\n/)) parseLine(raw, out)
  return out
}

/** Folds one porcelain line into `out`. */
const parseLine = (line: string, out: GitSnapshot): void => {
  let m: RegExpMatchArray | null
  if ((m = line.match(/^# branch\.head (.+)$/))) out.branch = m[1] ?? ''
  else if ((m = line.match(/^# branch\.upstream (.+)$/))) out.upstream = m[1] ?? null
  else if ((m = line.match(/^# branch\.ab \+(\d+) -(\d+)$/))) {
    out.ahead = Number(m[1])
    out.behind = Number(m[2])
  } else if ((m = line.match(/^[12] (.)(.) /))) {
    if (m[1] !== '.') out.staged++
    if (m[2] !== '.') out.unstaged++
  } else if (/^u /.test(line)) out.unstaged++
  else if (/^\? /.test(line)) out.untracked++
}

/** Whole-string truncation with an ellipsis. */
const clip = (text: string, max: number): string => (text.length <= max ? text : `${text.slice(0, max - 1)}…`)

/** The branch segment: name, then ahead/behind or "no upstream". */
const branchSegment = (g: GitSnapshot): string => {
  const head = `⎇ ${clip(g.branch || '?', MAX_BRANCH)}`
  if (g.upstream === null) return `${head} no upstream`
  return g.ahead > 0 || g.behind > 0 ? `${head} ↑${g.ahead} ↓${g.behind}` : head
}

/** The working-tree segment: non-zero counts, or "clean". */
const treeSegment = (g: GitSnapshot): string => {
  const parts: string[] = []
  if (g.staged > 0) parts.push(`+${g.staged}`)
  if (g.unstaged > 0) parts.push(`~${g.unstaged}`)
  if (g.untracked > 0) parts.push(`?${g.untracked}`)
  return parts.length === 0 ? 'clean' : parts.join(' ')
}

/** The commit-count segment: commits only the remote has (behind), then commits only the local branch has (ahead). */
const commitsSegment = (g: GitSnapshot): string => ` -- commits(R,L):${g.behind},${g.ahead}`

/** The status line, at most 80 characters; the commit counts are kept whole and the rest is clipped to fit. */
export const formatStatus = (g: GitSnapshot): string => {
  const commits = commitsSegment(g)
  return clip(`${branchSegment(g)} · ${treeSegment(g)}`, MAX_STATUS - commits.length) + commits
}

/** The prompt context line under a GIT_STATE tag. */
export const formatContext = (g: GitSnapshot): string => {
  const dirty = g.staged > 0 || g.unstaged > 0 || g.untracked > 0
  return (
    `GIT_STATE BRANCH=${g.branch} UPSTREAM=${g.upstream ?? 'none'} AHEAD=${g.ahead} BEHIND=${g.behind}` +
    ` STAGED=${g.staged} UNSTAGED=${g.unstaged} UNTRACKED=${g.untracked} DIRTY=${dirty}`
  )
}

/** A path with forward slashes and no trailing slash; undefined when blank. */
export const cleanPath = (p: string | undefined): string | undefined => {
  const out = (p ?? '').trim().replace(/\\/g, '/').replace(/\/+$/, '')
  return out === '' ? undefined : out
}

/**
 * The executable a `statusLine` setting starts when its command runs ccstatusline (a quoted first word
 * unquoted); undefined for any other setting.
 */
export const delegateExecutable = (statusLine: unknown): string | undefined => {
  if (typeof statusLine !== 'object' || statusLine === null) return undefined
  const command = (statusLine as { command?: unknown }).command
  if (typeof command !== 'string' || !/(^|[\s/\\"'])ccstatusline(@|\.|\s|"|'|$)/.test(command)) return undefined
  const first = command.trim().match(/^"([^"]+)"|^'([^']+)'|^(\S+)/)
  return first?.[1] ?? first?.[2] ?? first?.[3]
}

/** The PATH separator: `;` when the value holds one or starts with a drive letter, else `:`. */
const pathSeparator = (rawPath: string): string => (rawPath.includes(';') || /^[A-Za-z]:[\\/]/.test(rawPath) ? ';' : ':')

/**
 * Files that would be `exe`, each with the Windows launcher suffixes: `exe` itself when it names a folder,
 * else `exe` under every PATH folder.
 */
export const executableCandidates = (exe: string, rawPath: string | undefined): string[] => {
  const names = [exe, `${exe}.cmd`, `${exe}.exe`]
  if (/[\\/]/.test(exe)) return names
  const dirs = (rawPath ?? '').split(pathSeparator(rawPath ?? '')).map(d => cleanPath(d))
  return dirs.filter((d): d is string => d !== undefined).flatMap(d => names.map(n => `${d}/${n}`))
}

/** Where to ask git for the top level, in order: the session cwd, then CLAUDE_PROJECT_DIR (no repeats). */
export const rootStarts = (rawEnv: string | undefined, rawCwd: string | undefined): string[] => {
  const out: string[] = []
  for (const c of [cleanPath(rawCwd), cleanPath(rawEnv)]) {
    if (c !== undefined && !out.some(o => o.toLowerCase() === c.toLowerCase())) out.push(c)
  }
  return out
}

// ---------------------------------------------------------------------------
// Host access (kept in this file: the engine follows `$` past an import only into function declarations)

/** Top levels already answered, by start folder (a reload starts afresh). */
const toplevels = new Map<string, string>()

/** `git rev-parse --show-toplevel` from `start`; undefined on any failure. */
const toplevelOf = async ($: Dollar, start: string): Promise<string | undefined> => {
  const known = toplevels.get(start)
  if (known !== undefined) return known
  const argv = ['git', '-C', start, 'rev-parse', '--show-toplevel']
  const ran = await $.process.run(argv, { timeoutMs: GIT_TIMEOUT_MS }).catch(() => undefined)
  const top = ran === undefined || ran.exitCode !== 0 ? undefined : cleanPath(ran.stdout)
  if (top !== undefined) toplevels.set(start, top)
  return top
}

/** The project root: the first start folder git answers for; undefined when none does. Never throws. */
const resolveRoot = async ($: Dollar): Promise<string | undefined> => {
  const env = await $.env.get('CLAUDE_PROJECT_DIR').catch(() => undefined)
  const cwd = await $.session.cwd().catch(() => undefined)
  for (const start of rootStarts(env, cwd)) {
    const top = await toplevelOf($, start)
    if (top !== undefined) return top
  }
  return undefined
}

/** Runs git status; undefined on any failure (git missing, not a repo, timeout). */
const runGitStatus = async ($: Dollar, root: string): Promise<GitSnapshot | undefined> => {
  const argv = ['git', '-C', root, 'status', '--porcelain=v2', '--branch']
  const ran = await $.process
    .run(argv, { timeoutMs: GIT_TIMEOUT_MS, env: { GIT_OPTIONAL_LOCKS: '0' } })
    .catch(() => undefined)
  if (ran === undefined || ran.exitCode !== 0) return undefined
  const snap = parsePorcelain(ran.stdout)
  return snap.branch === '' ? undefined : snap
}

/** A full snapshot, or undefined when the root or git is unavailable. */
const takeSnapshot = async ($: Dollar): Promise<GitSnapshot | undefined> => {
  const root = await resolveRoot($)
  return root === undefined ? undefined : runGitStatus($, root)
}

/** Sets or clears the status line, swallowing a refusal. */
const showStatus = async ($: Dollar, text: string | undefined): Promise<void> => {
  try {
    await $.ui.status(text)
  } catch {
    // a surface that draws no status line
  }
}

/** Executable lookups already answered, by executable and PATH (a reload starts afresh). */
const lookups = new Map<string, boolean>()

/** The PATH value: `PATH`, else `Path` (its Windows spelling); undefined when neither is set. */
const readPath = async ($: Dollar): Promise<string | undefined> =>
  (await $.env.get('PATH').catch(() => undefined)) ?? $.env.get('Path').catch(() => undefined)

/** Whether `exe` is a file, as given or under a PATH folder; the answer is kept per PATH. */
const isInstalled = async ($: Dollar, exe: string): Promise<boolean> => {
  const rawPath = await readPath($)
  const key = `${exe}\n${rawPath ?? ''}`
  const known = lookups.get(key)
  if (known !== undefined) return known
  let found = false
  for (const candidate of executableCandidates(exe, rawPath)) {
    if (await $.fs.exists(candidate).catch(() => false)) {
      found = true
      break
    }
  }
  lookups.set(key, found)
  return found
}

/**
 * Whether ccstatusline draws the status line: the merged `statusLine` setting runs it and its executable is
 * installed. The mod's own line then stays clear. Never throws.
 */
const isDelegated = async ($: Dollar): Promise<boolean> => {
  const statusLine = await $.settings.read({ key: 'statusLine' }).catch(() => undefined)
  const exe = delegateExecutable(statusLine)
  return exe === undefined ? false : isInstalled($, exe)
}

/** Stores the snapshot and draws (or clears) the status line; never throws. */
const publish = async ($: Dollar, snap: GitSnapshot | undefined): Promise<void> => {
  await update($, gitState, () => snap ?? null).catch(() => undefined)
  if (snap === undefined) return showStatus($, undefined)
  const isClear = await isDelegated($).catch(() => false)
  return showStatus($, isClear ? undefined : formatStatus(snap))
}

/** Snapshot then publish; swallows every error. */
const refreshNow = async ($: Dollar): Promise<GitSnapshot | undefined> => {
  const snap = await takeSnapshot($).catch(() => undefined)
  await publish($, snap).catch(() => undefined)
  return snap
}

// ---------------------------------------------------------------------------
// Coalescing: one git run in flight, at least MIN_GAP_MS between background starts

/** Per-load refresh bookkeeping (a reload starts afresh). */
const pacing = {
  /** A background run is scheduled or in flight. */
  isBusy: false,
  /** Background git is running now (past the pacing wait): a request then is owed a run after it. */
  isRunning: false,
  isOwed: false,
  lastStart: Number.NEGATIVE_INFINITY,
  /** The next prompt gets the context line even when unchanged: a new conversation, or a compacted one. */
  isContextForced: true,
  /** Tail of the git runs, background and foreground: each starts after the one before settled. */
  gitTail: Promise.resolve() as Promise<unknown>,
  /** Git runs chained on `gitTail` that have not settled. */
  inFlight: 0,
  tick: undefined as { cancel: () => void } | undefined,
}

/**
 * Snapshot and publish after any run in flight settles, so git never runs twice at once and the
 * last run started is the last one published.
 */
const serialRefresh = ($: Dollar): Promise<GitSnapshot | undefined> => {
  const run = pacing.gitTail.then(() => refreshNow($))
  track(run)
  return run
}

/** Chains `run` onto the tail and counts it in flight until it settles. */
const track = (run: Promise<unknown>): void => {
  pacing.inFlight += 1
  const settled = run.catch(() => undefined).finally(() => {
    pacing.inFlight -= 1
  })
  pacing.gitTail = Promise.all([pacing.gitTail, settled]).catch(() => undefined)
}

/** Waits for the runs in flight, at most TAIL_WAIT_MS; returns at once when none is. Never throws. */
const awaitTail = async ($: Dollar, signal: AbortSignal): Promise<void> => {
  if (pacing.inFlight === 0) return
  const stop = new AbortController()
  const timer = $.clock.sleep(TAIL_WAIT_MS, { signal: AbortSignal.any([signal, stop.signal]) })
  try {
    await Promise.race([pacing.gitTail, timer.catch(() => undefined)])
  } finally {
    stop.abort()
  }
}

/**
 * The prompt's own snapshot: after the runs in flight when they settle within TAIL_WAIT_MS, else at
 * once beside them (git status takes no lock: GIT_OPTIONAL_LOCKS=0).
 */
const promptRefresh = async ($: Dollar, signal: AbortSignal): Promise<GitSnapshot | undefined> => {
  await awaitTail($, signal)
  const run = refreshNow($)
  track(run)
  return run
}

/** Milliseconds left before a background run may start. */
const gapLeft = async ($: Dollar): Promise<number> => pacing.lastStart + MIN_GAP_MS - (await $.clock.now())

/** One paced background run; a refused wait rejects, which ends the cycle rather than hanging it. */
const cycle = async ($: Dollar): Promise<void> => {
  for (let wait = await gapLeft($); wait > 0; wait = await gapLeft($)) await $.clock.sleep(wait)
  pacing.lastStart = await $.clock.now()
  pacing.isRunning = true
  await serialRefresh($)
}

/** Asks for a background refresh and returns at once; folds into a run already in flight. */
const requestRefresh = ($: Dollar): void => {
  if (pacing.isBusy) {
    // a run still waiting out its gap will read the newer state anyway
    if (pacing.isRunning) pacing.isOwed = true
    return
  }
  pacing.isBusy = true
  void cycle($)
    .catch(() => undefined)
    .finally(() => finishCycle($))
}

/** Ends a run and starts the one owed, if any. */
const finishCycle = ($: Dollar): void => {
  pacing.isBusy = false
  pacing.isRunning = false
  if (!pacing.isOwed) return
  pacing.isOwed = false
  requestRefresh($)
}

/** Records a foreground run, so the next background one keeps its distance. */
const noteForegroundRun = async ($: Dollar): Promise<void> => {
  const now = await $.clock.now().catch(() => undefined)
  if (now !== undefined) pacing.lastStart = Math.max(pacing.lastStart, now)
}

/** Schedules a refresh after the current dispatch, so the caller's result is not delayed. */
const refreshLater = ($: Dollar): void => {
  try {
    $.clock.after(0, () => requestRefresh($))
  } catch {
    // no timer: this refresh is skipped
  }
}

/** (Re)starts the periodic refresh; a timer costs no model tokens. */
const startTicking = ($: Dollar): void => {
  try {
    pacing.tick?.cancel()
    pacing.tick = $.clock.every(TICK_MS, () => requestRefresh($))
  } catch {
    pacing.tick = undefined
  }
}

// ---------------------------------------------------------------------------
// Prompt context

/** A fresh snapshot's context line when it should be attached to this prompt; records nothing. */
const promptContext = async ($: Dollar, signal: AbortSignal): Promise<string | undefined> => {
  await noteForegroundRun($)
  const snap = await promptRefresh($, signal)
  if (snap === undefined) return undefined
  const line = formatContext(snap)
  if (pacing.isContextForced) return line
  const previous = await read($, lastContext).catch(() => '')
  return previous === line ? undefined : line
}

/** Records `line` as attached, once the prompt entered with it and the dispatch did not move on. */
const recordAttached = async (
  $: Dollar,
  line: string,
  result: PromptSubmitResult,
  signal: AbortSignal,
): Promise<void> => {
  if (signal.aborted || result.drop !== undefined || !(result.context ?? []).includes(line)) return
  pacing.isContextForced = false
  await update($, lastContext, () => line).catch(() => undefined)
}

/** Session-end reasons after which the same process goes on with a fresh conversation. */
const FRESH_CONVERSATION = new Set<string>(['clear', 'resume'])

/** Whether a compaction result replaced the main conversation (its GIT_STATE line may be gone). */
const isMainCompaction = (e: SessionCompactInput, result: SessionCompactResult): boolean =>
  result.skip === undefined && e.agentId === undefined && e.trigger !== 'precompute'

/** Forces the context line on the next prompt after `/clear`, a resume, or a main compaction. */
const registerContextResets = (on: Parameters<Register>[0]): void => {
  on('session.end', async ($, e, next) => {
    if (FRESH_CONVERSATION.has(e.reason)) pacing.isContextForced = true
    return next(e)
  }).catch((_$, e, next) => next(e))

  on('session.compact', async ($, e, next) => {
    const result = await next(e)
    if (isMainCompaction(e, result)) pacing.isContextForced = true
    return result
  }).catch((_$, e, next) => next(e))
}

// ---------------------------------------------------------------------------
// Registration

/** Registers the status line, its refresh triggers and the per-prompt git context. */
export const registerStatus = (on: Parameters<Register>[0]): void => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    startTicking($)
    refreshLater($)
    return started
  })

  on('tool.call', { tool: REFRESH_TOOLS }, async ($, e, next) => {
    const result = await next(e)
    refreshLater($)
    return result
  }).catch((_$, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    refreshLater($)
    return result
  })

  on('prompt.submit', async ($, e, next) => {
    const line = await promptContext($, next.signal).catch(() => undefined)
    if (line === undefined || next.signal.aborted) return next(e)
    const result = await next({ ...e, context: [...(e.context ?? []), line] })
    await recordAttached($, line, result, next.signal)
    return result
  }).catch((_$, e, next) => next(e))

  registerContextResets(on)
}
