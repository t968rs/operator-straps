import type { EngineInterface, FsEntry, On } from 'claude-code'
import { atom, read, update } from 'claude-code'

import type { AgentRec, LogFailure, Phase, Run } from '../types'
import {
  keywordBlock, mentionsBubble, missingFromReview, readReview, reviewFileFor, sidecarIds, stopBlock, verdictPrefix,
  type ReviewDoc,
} from './bubbles'
import { runtimeBaseOf, sentinelDirOf, under } from './config'
import {
  identify, identifyStandalone, isDefinedAgent, parseReturnBlock, prOfRunId, standaloneRunId, startedAtOfRunId,
  type Dispatch,
} from './contract'
import { appendRows, buildRow, validateRow, type MatrixRow } from './matrixRow'
import { scanPhase5, type HotSentinel } from './phase5Scan'
import {
  applyCompletion, applyDispatch, currentRunId, fixerBubbledIds, markLogged, markUsageLogged, newAgent, planPhase,
  recoverReviewers, reviewersSettled, reviewersToLog, settle, usageToLog, withDiskPhase, type Completion,
} from './runs'
import { blocksSession } from './sentinels'
import {
  blockCounts, buildUsageRow, NO_COUNTS, preferCounts, reportCounts, validateUsageRow, type FixerCounts,
  type UsageRow,
} from './usageRow'
import { resolveWatch, type Watch } from './watch'

/**
 * Engine glue for pr-review-watch: tracks pr-team / pr-review `Agent` dispatches and the standalone dispatches
 * of every other defined agent, folds subagent usage, appends invocation-matrix rows (reviewers) and agent
 * usage rows (every tracked agent), and guards Stop on undispositioned bubbled
 * ids. Active only in a project holding `.claude/harness.json` (./watch); its paths and base branch
 * come from that file. Every host
 * failure degrades to doing nothing; no hook throws into a tool call, a turn or a stop.
 */

type Dollar = EngineInterface
type Key = { runId: string; agentId: string }
/** The fields of an Agent tool result the watch reads; the engine's union is wider. */
type AgentResult = {
  status?: string
  agentId?: string
  totalTokens?: number
  totalToolUseCount?: number
  totalDurationMs?: number
  resolvedModel?: string
  content?: readonly { type: string; text?: string }[]
}
/** The fields of a tool result the watch reads. */
type ToolAnswer = { result?: unknown; text?: string; isError?: true; deny?: string }
type Usage = {
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
  model: string
}
type TurnEnd = { answer: string; durationMs: number; usage?: Usage }

const runsAtom = atom({ plugin: 'pr-review-watch', key: 'runs' } as const, {})
const activeAtom = atom({ plugin: 'pr-review-watch', key: 'active' } as const, null)
const loopsAtom = atom({ plugin: 'pr-review-watch', key: 'loops' } as const, {})
const failuresAtom = atom({ plugin: 'pr-review-watch', key: 'failures' } as const, [])
const phase5Atom = atom({ plugin: 'pr-review-watch', key: 'phase5' } as const, [])
const missingAtom = atom({ plugin: 'pr-review-watch', key: 'missing' } as const, [])

/** A shell command that drives pr-review's script; its result can move a run's phase or bubbles. */
const PR_REVIEW_SCRIPT = /pr_review\.py/
const MARKER = '.matrix_owner'
const GIT_TIMEOUT_MS = 10_000
const MAX_FAILURES = 20
export const OWNER_NOTE =
  '[pr-review-watch] Matrix rows for this run are recorded by the pr-review-watch mod; ' +
  'skip the manual JSONL append (pr-review Phase 3 Step 4).'

const noop = (): undefined => undefined
/** Tool calls per subagent loop id, counted for background launches. */
const toolUses = new Map<string, number>()
/** Serializes matrix and usage appends: parallel returns never interleave a read-modify-write. */
let flushTail: Promise<unknown> = Promise.resolve()
/** Numbers the standalone runs of this process, so same-second dispatches never share a run id. */
let standaloneSeq = 0

// ---------------------------------------------------------------------------
// Host access

const readText = async ($: Dollar, path: string): Promise<string | undefined> => {
  const raw = await $.fs.read(path).catch(noop)
  return typeof raw === 'string' ? raw : undefined
}

const listDir = ($: Dollar, path: string): Promise<FsEntry[]> => $.fs.list(path).catch(() => [] as FsEntry[])

const gitLine = async ($: Dollar, root: string, args: readonly string[]): Promise<string | undefined> => {
  const ran = await $.process.run(['git', '-C', root, ...args], { timeoutMs: GIT_TIMEOUT_MS }).catch(noop)
  return ran !== undefined && ran.exitCode === 0 ? ran.stdout.trim() : undefined
}

/** The configured base branch, else the branch `origin/HEAD` names, else `main` (resolve_base_branch). */
const baseBranchFor = async ($: Dollar, w: Watch): Promise<string> => {
  if (w.cfg.baseBranch !== null) return w.cfg.baseBranch
  const head = await gitLine($, w.root, ['symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD'])
  const slash = head?.indexOf('/') ?? -1
  return head !== undefined && slash > 0 ? head.slice(slash + 1) : 'main'
}

/** `<merge-base> -- <branch> (pr-review-watch auto)`; empty (which fails validation) when git fails. */
const devCommitFor = async ($: Dollar, w: Watch): Promise<string> => {
  const sha = await gitLine($, w.root, ['merge-base', 'HEAD', await baseBranchFor($, w)])
  const branch = (await gitLine($, w.root, ['rev-parse', '--abbrev-ref', 'HEAD'])) ?? '?'
  return sha === undefined ? '' : `${sha} -- ${branch} (pr-review-watch auto)`
}

// ---------------------------------------------------------------------------
// Sentinels and review JSON

const scanSentinels = ($: Dollar, w: Watch): Promise<HotSentinel[]> =>
  scanPhase5($, under(w.sentinelRoot, sentinelDirOf(w.cfg)))

/** The newest review JSON for a PR, unless it is older than `sinceMs`. */
const loadReviewFor = async ($: Dollar, w: Watch, pr: number, sinceMs: number): Promise<ReviewDoc | undefined> => {
  const dir = under(w.root, w.cfg.reviewsDir)
  const hit = reviewFileFor(pr, await listDir($, dir))
  if (hit === undefined || hit.mtimeMs < sinceMs) return undefined
  const text = await readText($, `${dir}/${hit.name}`)
  return text === undefined ? undefined : readReview(text)
}

/** The run's review JSON: newest for its PR and not older than the run. */
const loadReview = ($: Dollar, w: Watch, run: Run): Promise<ReviewDoc | undefined> =>
  run.pr === null ? Promise.resolve(undefined) : loadReviewFor($, w, run.pr, run.startedAt)

const loadSidecar = async ($: Dollar, w: Watch, run: Run): Promise<string[] | null> => {
  if (run.runtimeDir === null) return null
  const text = await readText($, `${under(w.root, run.runtimeDir)}/bubble_ups.json`)
  return text === undefined ? null : sidecarIds(text)
}

/** What a pr-review run directory says: the `plan.json` phase and the fixer-bubbled ids. */
type RunDisk = { phase: Phase | undefined; fixerBubbled: string[] }
const NO_RUN_DISK: RunDisk = { phase: undefined, fixerBubbled: [] }

/**
 * The pr-review run directory under `artifacts.scratch` (`<NNNN>/current` names the active run,
 * `<NNNN>/<RUN_ID>/` holds it), only while the PR folder's `current` names this run.
 */
const prReviewRunDir = async ($: Dollar, w: Watch, run: Run): Promise<string | undefined> => {
  if (run.skill !== 'pr-review' || run.pr === null) return undefined
  const prDir = `${under(w.root, w.cfg.scratchDir)}/${String(run.pr).padStart(4, '0')}`
  return currentRunId(await readText($, `${prDir}/current`)) === run.runId ? `${prDir}/${run.runId}` : undefined
}

const fixerReports = async ($: Dollar, dir: string): Promise<string[]> => {
  const names = (await listDir($, dir)).filter(e => e.kind === 'file' && e.name.endsWith('.json')).map(e => e.name)
  const texts = await Promise.all(names.sort().map(name => readText($, `${dir}/${name}`)))
  return texts.filter((t): t is string => t !== undefined)
}

const loadRunDisk = async ($: Dollar, w: Watch, run: Run): Promise<RunDisk> => {
  const dir = await prReviewRunDir($, w, run)
  if (dir === undefined) return NO_RUN_DISK
  const plan = await readText($, `${dir}/plan.json`)
  const phase = plan === undefined ? undefined : planPhase(plan)
  return { phase, fixerBubbled: fixerBubbledIds(await fixerReports($, `${dir}/fixes`)) }
}

// ---------------------------------------------------------------------------
// State updates

const runOf = async ($: Dollar, runId: string): Promise<Run | undefined> => (await read($, runsAtom))[runId]

const updateRun = ($: Dollar, runId: string, fn: (run: Run) => Run): Promise<unknown> =>
  update($, runsAtom, runs => {
    const cur = runs[runId]
    return cur === undefined ? runs : { ...runs, [runId]: fn(cur) }
  })

type DispatchMeta = { model?: string; effort?: string; subagentType?: string }

const recordDispatch = async ($: Dollar, d: Dispatch, meta: DispatchMeta): Promise<void> => {
  const now = await $.clock.now()
  await update($, runsAtom, runs => applyDispatch(runs, d, newAgent(d, meta), now))
  if (d.skill !== 'standalone') await update($, activeAtom, () => d.runId)
}

/** A standalone run holds one agent; once its usage row is attempted the run is dropped, bounding state. */
const dropStandalone = ($: Dollar, runId: string): Promise<unknown> =>
  update($, runsAtom, runs => {
    if (runs[runId]?.skill !== 'standalone') return runs
    return Object.fromEntries(Object.entries(runs).filter(([id]) => id !== runId))
  })

/** Writes the pending ownership marker once the orchestrator's plan is in. */
const claimMatrix = async ($: Dollar, key: Key, signal: string | undefined): Promise<void> => {
  if (key.agentId !== 'orchestrator_plan' || signal !== 'DONE') return
  const run = await runOf($, key.runId)
  const w = await resolveWatch($)
  if (run === undefined || run.runtimeDir === null || w === undefined) return
  await $.fs.write(`${under(w.root, run.runtimeDir)}/${MARKER}`, 'pending\n').catch(noop)
}

const complete = async ($: Dollar, key: Key, c: Completion): Promise<void> => {
  await updateRun($, key.runId, run => applyCompletion(run, key.agentId, c))
  await claimMatrix($, key, c.block?.signal)
  await logUsage($, key, c)
  await dropStandalone($, key.runId)
}

const textOf = (r: AgentResult): string => (r.content ?? []).map(b => b.text ?? '').join('\n')

/** Maps the loop to its agent and keeps the model the engine launched it with. */
const registerLoop = async ($: Dollar, loopId: string, key: Key, model: string | null): Promise<void> => {
  await update($, loopsAtom, loops => ({ ...loops, [loopId]: [key.runId, key.agentId] as [string, string] }))
  await updateRun($, key.runId, run => {
    const a = run.agents[key.agentId]
    return a === undefined ? run : { ...run, agents: { ...run.agents, [key.agentId]: { ...a, launchModel: model } } }
  })
}

/** Folds an Agent tool result: usage now when synchronous, a loop registration when backgrounded. */
const recordResult = async ($: Dollar, key: Key, r: ToolAnswer): Promise<void> => {
  const res = (r.deny === undefined && r.isError !== true ? r.result : undefined) as AgentResult | undefined
  if (res?.status === 'async_launched' && res.agentId !== undefined) {
    return registerLoop($, res.agentId, key, res.resolvedModel ?? null)
  }
  const isDone = res?.status === 'completed'
  await complete($, key, {
    tokens: isDone ? (res.totalTokens ?? 0) : 0,
    toolUses: isDone ? (res.totalToolUseCount ?? 0) : 0,
    durationMs: isDone ? (res.totalDurationMs ?? 0) : 0,
    model: res?.resolvedModel ?? null,
    block: isDone ? parseReturnBlock(r.text ?? textOf(res)) : undefined,
    isMeasured: isDone,
    ending: r.deny !== undefined ? 'denied' : isDone ? 'ok' : 'errored',
  })
}

const usageTokens = (u: Usage | undefined): number =>
  u === undefined ? 0 : u.input_tokens + u.output_tokens + u.cache_read_input_tokens + u.cache_creation_input_tokens

/** A background subagent's turn ended: its usage, tool count and report complete the agent. */
const recordLoopEnd = async ($: Dollar, loopId: string, e: TurnEnd): Promise<void> => {
  const used = toolUses.get(loopId) ?? 0
  toolUses.delete(loopId)
  const hit = (await read($, loopsAtom))[loopId]
  if (hit === undefined) return
  await update($, loopsAtom, loops => Object.fromEntries(Object.entries(loops).filter(([k]) => k !== loopId)))
  await complete($, { runId: hit[0], agentId: hit[1] }, {
    tokens: usageTokens(e.usage), toolUses: used, durationMs: e.durationMs, model: e.usage?.model ?? null,
    block: parseReturnBlock(e.answer), isMeasured: e.usage !== undefined, ending: 'ok',
  })
}

// ---------------------------------------------------------------------------
// JSONL append (matrix and usage log)

/** Keeps the failures and toasts them; `noun` names the row kind (`matrix`, `usage`). */
const recordFailures = async ($: Dollar, failures: readonly LogFailure[], noun: string): Promise<void> => {
  if (failures.length === 0) return
  await update($, failuresAtom, prev => [...prev, ...failures].slice(-MAX_FAILURES)).catch(noop)
  const first = failures[0]
  const text = `pr-review-watch: ${failures.length} ${noun} row(s) not appended (${first?.cell}: ${first?.reason})`
  await Promise.resolve($.ui.toast(text)).catch(noop)
}

/**
 * The JSONL text to append to: '' when the file is missing, undefined when it exists (or its existence
 * is unknown) but cannot be read, so a whole-file write would drop its rows.
 */
const readJsonl = async ($: Dollar, path: string): Promise<string | undefined> => {
  const isThere = await $.fs.exists(path).catch(() => true)
  return isThere ? readText($, path) : ''
}

/** How one JSONL file checks and names its rows; `label` starts the failure reasons. */
type RowCheck<R> = { label: string; problems: (r: R) => string[]; cellOf: (r: R) => string }

const MATRIX_CHECK: RowCheck<MatrixRow> = { label: 'matrix', problems: validateRow, cellOf: r => r.cell }
const USAGE_CHECK: RowCheck<UsageRow> = {
  label: 'usage log', problems: validateUsageRow, cellOf: r => `${r.run_id}/${r.agent_id}`,
}

/**
 * Appends valid rows to `path`; returns the failures (invalid rows, or every row when the file cannot be
 * read or the write is refused). An unreadable file is never overwritten.
 */
const appendValid = async <R extends object>(
  $: Dollar,
  path: string,
  rows: readonly R[],
  check: RowCheck<R>,
  now: number,
): Promise<LogFailure[]> => {
  const checked = rows.map(r => ({ r, why: check.problems(r) }))
  const good = checked.filter(x => x.why.length === 0).map(x => x.r)
  const failures = checked.filter(x => x.why.length > 0)
    .map(x => ({ cell: check.cellOf(x.r), reason: x.why.join('; '), at: now }))
  if (good.length === 0) return failures
  const existing = await readJsonl($, path)
  const isWritten =
    existing !== undefined && (await $.fs.write(path, appendRows(existing, good)).then(() => true, () => false))
  if (isWritten) return failures
  const reason = existing === undefined ? `${check.label} unreadable; not overwritten` : `${check.label} write refused`
  return [...failures, ...good.map(r => ({ cell: check.cellOf(r), reason, at: now }))]
}

const writeRows = ($: Dollar, w: Watch, rows: readonly MatrixRow[], now: number): Promise<LogFailure[]> =>
  appendValid($, under(w.root, w.cfg.matrixPath), rows, MATRIX_CHECK, now)

// ---------------------------------------------------------------------------
// Usage rows

/** Claims the agent's usage row inside one atom update, so a second fold never appends it again. */
const claimUsage = async ($: Dollar, key: Key, now: number): Promise<[Run, AgentRec] | undefined> => {
  const box: { hit?: [Run, AgentRec] } = {}
  await updateRun($, key.runId, r => {
    box.hit = undefined
    const a = usageToLog(r, key.agentId)
    if (a === undefined) return r
    box.hit = [r, a]
    return markUsageLogged(r, key.agentId, now)
  })
  return box.hit
}

/**
 * Outcome counts: closer and pr-team fixers from the return block; a pr-review fixer from its run's
 * waves.json and fixes/<id>.json, falling back to the block; other roles none.
 */
const countsFor = async (
  $: Dollar,
  w: Watch,
  run: Run,
  agent: AgentRec,
  c: Completion,
): Promise<FixerCounts> => {
  if (agent.role === 'closer' || (agent.role === 'fixer' && run.skill === 'pr-team')) return blockCounts(c.block)
  if (agent.role !== 'fixer') return NO_COUNTS
  const dir = await prReviewRunDir($, w, run).catch(noop)
  const read = (rel: string): Promise<string | undefined> =>
    dir === undefined ? Promise.resolve(undefined) : readText($, `${dir}/${rel}`)
  const [waves, report] = await Promise.all([read('waves.json'), read(`fixes/${agent.id}.json`)])
  return preferCounts(reportCounts(waves, report, agent.id), blockCounts(c.block))
}

/** One usage row per returned dispatch; a denied dispatch never ran and writes none. */
const logUsage = async ($: Dollar, key: Key, c: Completion): Promise<void> => {
  if (c.ending === 'denied') return
  const w = await resolveWatch($)
  if (w === undefined) return
  const now = await $.clock.now()
  const hit = await claimUsage($, key, now)
  if (hit === undefined) return
  const [run, claimed] = hit
  const counts = await countsFor($, w, run, claimed, c)
  // The engine's model: this completion's, else the background launch's, else the requested one.
  const agent = { ...claimed, model: c.model ?? claimed.launchModel ?? claimed.model }
  const row = buildUsageRow({
    runId: run.runId, skill: run.skill, pr: run.pr, agent, ending: c.ending, isMeasured: c.isMeasured,
    loggedAt: now, counts,
  })
  const path = under(w.root, w.cfg.agentUsagePath)
  flushTail = flushTail
    .then(async () => recordFailures($, await appendValid($, path, [row], USAGE_CHECK, now), 'usage'))
    .catch(noop)
  await flushTail
}

/**
 * Claims the run's unlogged reviewers: marks them logged inside one atom update and returns them, so an
 * overlapping refresh finds nothing left to claim and never appends the same rows again.
 */
const claimReviewers = async ($: Dollar, runId: string, now: number): Promise<AgentRec[]> => {
  let claimed: AgentRec[] = []
  await updateRun($, runId, r => {
    claimed = reviewersToLog(r)
    return claimed.length === 0 ? r : markLogged(r, claimed.map(a => a.id), now)
  })
  return claimed
}

const flushNow = async ($: Dollar, w: Watch, runId: string): Promise<void> => {
  const run = await runOf($, runId)
  const prefix = verdictPrefix(run?.verdict ?? null)
  if (run === undefined || run.pr === null || prefix === undefined || !reviewersSettled(run)) return
  const now = await $.clock.now()
  const agents = await claimReviewers($, runId, now)
  if (agents.length === 0) return
  const devCommit = await devCommitFor($, w)
  const pr = run.pr
  const rows = agents.map(agent => buildRow({ pr, agent, verdictPrefix: prefix, devCommit }))
  await recordFailures($, await writeRows($, w, rows, now), 'matrix')
  if (run.runtimeDir === null) return
  const stamp = `logged ${new Date(now).toISOString()}\n`
  await $.fs.write(`${under(w.root, run.runtimeDir)}/${MARKER}`, stamp).catch(noop)
}

const flush = ($: Dollar, w: Watch, runId: string): Promise<unknown> => {
  flushTail = flushTail.then(() => flushNow($, w, runId)).catch(noop)
  return flushTail
}

// ---------------------------------------------------------------------------
// Refresh, recovery, stop

/** Re-reads disk for the active run: sentinels, verdict, bubbled set, missing ids; flushes rows. */
const refreshWith = async ($: Dollar, w: Watch): Promise<void> => {
  const phase5 = (await scanSentinels($, w).catch(() => [] as HotSentinel[])).map(s => s.pr)
  await update($, phase5Atom, () => phase5)
  const id = await read($, activeAtom)
  const run = id === null ? undefined : await runOf($, id)
  if (run === undefined) {
    await update($, missingAtom, () => [])
    return
  }
  const review = await loadReview($, w, run)
  const sidecar = await loadSidecar($, w, run)
  const disk = await loadRunDisk($, w, run).catch(() => NO_RUN_DISK)
  await updateRun($, run.runId, r => withDiskPhase(settle(r, review, sidecar, disk.fixerBubbled), disk.phase))
  const settled = await runOf($, run.runId)
  const tracked = settled === undefined || settled.bubbledFrom === 'review_json' ? [] : settled.bubbled
  await update($, missingAtom, () => missingFromReview(tracked, review))
  if (review !== undefined) await flush($, w, run.runId)
}

/** `refreshWith` for the session's project; nothing outside a harness project. */
const refresh = async ($: Dollar): Promise<void> => {
  const w = await resolveWatch($)
  if (w !== undefined) await refreshWith($, w)
}

/**
 * A run rebuilt from its runtime dir: plan reviewers joined with terminals rows. Its start is the run id's
 * stamp, so an older review JSON for the same PR is never taken for its verdict; no stamp, no recovery.
 */
const recoveredRun = async ($: Dollar, w: Watch, runId: string): Promise<Run | undefined> => {
  const runtimeDir = `${runtimeBaseOf(w.cfg)}/${runId}`
  const dir = under(w.root, runtimeDir)
  const plan = await readText($, `${dir}/dispatch_plan_review.json`)
  const pr = prOfRunId(runId)
  const startedAt = startedAtOfRunId(runId)
  if (plan === undefined || pr === null || startedAt === null) return undefined
  const agents = recoverReviewers(plan, (await readText($, `${dir}/terminals.jsonl`)) ?? '')
  return {
    runId, skill: 'pr-team', pr, phase: 'consolidate', runtimeDir,
    agents: Object.fromEntries(agents.map(a => [a.id, a])), bubbled: [], bubbledFrom: 'none', verdict: null,
    startedAt,
  }
}

/** Rows for a pr-team run a previous session claimed but never logged. */
const recoverRun = async ($: Dollar, w: Watch, runId: string): Promise<void> => {
  const run = await recoveredRun($, w, runId)
  if (run === undefined) return
  await update($, runsAtom, runs => (runs[runId] === undefined ? { ...runs, [runId]: run } : runs))
  const review = await loadReview($, w, run)
  if (review === undefined) return
  await updateRun($, runId, r => settle(r, review, null))
  await flush($, w, runId)
}

const recoverPending = async ($: Dollar): Promise<void> => {
  const w = await resolveWatch($)
  if (w === undefined) return
  const known = await read($, runsAtom)
  const base = under(w.root, runtimeBaseOf(w.cfg))
  for (const entry of await listDir($, base)) {
    if (entry.kind !== 'dir' || known[entry.name] !== undefined) continue
    const marker = await readText($, `${base}/${entry.name}/${MARKER}`)
    if (marker?.startsWith('pending')) await recoverRun($, w, entry.name).catch(noop)
  }
}

const activeRun = async ($: Dollar): Promise<Run | undefined> => {
  const id = await read($, activeAtom)
  return id === null ? undefined : runOf($, id)
}

type PrReview = [number, ReviewDoc | undefined]

/**
 * The active review for the keyword check: the tracked run's PR, else that of the first hot sentinel
 * blocking the stopping session (`blocksSession`; another session's sentinel is not this one's review).
 */
const keywordReview = async (
  $: Dollar,
  w: Watch,
  run: Run | undefined,
  sessionId: string | undefined,
): Promise<PrReview | undefined> => {
  if (run !== undefined && run.pr !== null) return [run.pr, await loadReview($, w, run)]
  const hot = await scanSentinels($, w).catch(() => [] as HotSentinel[])
  const pr = Number(hot.find(s => blocksSession(s.owner, sessionId))?.pr)
  return Number.isInteger(pr) && pr >= 1 ? [pr, await loadReviewFor($, w, pr, 0)] : undefined
}

type StopInput = { stop_hook_active: boolean; last_assistant_message?: string; session_id?: string }

/** Tracked bubbled ids out of the review JSON (pr-team), then the "bubble" keyword rule (any review). */
const stopReason = async ($: Dollar, w: Watch, e: StopInput): Promise<string | undefined> => {
  const run = await activeRun($)
  const missing = await read($, missingAtom)
  const tracked =
    run?.skill === 'pr-team' ? stopBlock(run.pr, missing, run.bubbledFrom, e.stop_hook_active) : undefined
  if (tracked !== undefined || !mentionsBubble(e.last_assistant_message)) return tracked
  const hit = await keywordReview($, w, run, e.session_id)
  return hit === undefined ? undefined : keywordBlock(hit[0], e.last_assistant_message, hit[1], e.stop_hook_active)
}

/** The Stop block the watch owes, or undefined; nothing outside a harness project. */
const stopBlockFor = async ($: Dollar, e: StopInput): Promise<string | undefined> => {
  const w = await resolveWatch($)
  if (w === undefined) return undefined
  await refreshWith($, w).catch(noop)
  return stopReason($, w, e)
}

// ---------------------------------------------------------------------------
// Hooks

/** A shell call that ran pr-review's script refreshes, so the band moves within a turn. */
const afterShell = async ($: Dollar, command: string | undefined): Promise<void> => {
  if (PR_REVIEW_SCRIPT.test(command ?? '')) await refresh($).catch(noop)
}

/** Whether the mod holds a run it can log rows for: recorded in state, with a PR. */
const ownsRows = async ($: Dollar, runId: string): Promise<boolean> =>
  ((await runOf($, runId).catch(noop))?.pr ?? null) !== null

/** A defined agent that carries no run header gets a run of its own, under a fresh id. */
const standaloneFor = async ($: Dollar, subagentType: string | undefined): Promise<Dispatch | undefined> =>
  identifyStandalone(subagentType, standaloneRunId(await $.clock.now(), ++standaloneSeq))

/**
 * The tracked identity of a dispatch in a harness project, with that project; else undefined. A run header
 * names the run; a defined agent without one is a standalone run.
 */
const trackedDispatch = async (
  $: Dollar,
  subagentType: string | undefined,
  prompt: string,
): Promise<[Dispatch, Watch] | undefined> => {
  if (identify(subagentType, prompt, '') === undefined && !isDefinedAgent(subagentType)) return undefined
  const w = await resolveWatch($).catch(noop)
  if (w === undefined) return undefined
  const d = identify(subagentType, prompt, runtimeBaseOf(w.cfg)) ?? (await standaloneFor($, subagentType))
  return d === undefined ? undefined : [d, w]
}

/** Tool-call hooks: tracked Agent dispatches, per-loop tool counts and shell refreshes. */
const registerToolHooks = (on: On): void => {
  on('tool.call', { tool: 'Agent' }, async ($, e, next) => {
    const hit = await trackedDispatch($, e.subagent_type, e.prompt)
    if (hit === undefined) return next(e)
    const [d, w] = hit
    await recordDispatch($, d, { model: e.model, effort: e.effort, subagentType: e.subagent_type }).catch(noop)
    const r = await next(e)
    await recordResult($, { runId: d.runId, agentId: d.agentId }, r).catch(noop)
    if (d.skill !== 'standalone') await refreshWith($, w).catch(noop)
    // Refusals inline (not a helper) so the checker narrows `r` to a result that takes context.
    if (d.skill !== 'pr-review' || d.role !== 'reviewer' || r.deny !== undefined || r.isError === true) return r
    if (!(await ownsRows($, d.runId))) return r
    return { ...r, context: [...(r.context ?? []), OWNER_NOTE] }
  })

  on('tool.call', ($, e, next) => {
    if (e.agentId !== undefined) toolUses.set(e.agentId, (toolUses.get(e.agentId) ?? 0) + 1)
    return next(e)
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const r = await next(e)
    await afterShell($, e.command)
    return r
  })

  on('tool.call', { tool: 'PowerShell' }, async ($, e, next) => {
    const r = await next(e)
    await afterShell($, e.command)
    return r
  })
}

/** Turn, session and Stop hooks: loop usage, recovery, refreshes and the Stop guard. */
const registerLifecycleHooks = (on: On): void => {
  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    if (e.agentId !== undefined) await recordLoopEnd($, e.agentId, e).catch(noop)
    await refresh($).catch(noop)
    return r
  })

  on('session.start', async ($, e, next) => {
    const r = await next(e)
    await recoverPending($).catch(noop)
    await refresh($).catch(noop)
    return r
  })

  on('classic.Stop', async ($, e, next) => {
    const r = await next(e)
    if (r.block !== undefined) return r
    const block = await stopBlockFor($, e).catch(noop)
    return block === undefined ? r : { ...r, block }
  })
}

export const registerTracker = (on: On): void => {
  registerToolHooks(on)
  registerLifecycleHooks(on)
}
