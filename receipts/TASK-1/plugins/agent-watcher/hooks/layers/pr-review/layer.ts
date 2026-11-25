import type { EngineInterface, On } from 'claude-code'

import type { AgentRec, Phase, Run } from '../../../types'
import { under } from '../../core/config'
import type { Header } from '../../core/contract'
import { appendValid, recordFailures, serialize, type RowCheck } from '../../core/jsonl'
import type { Claim, Completion, Io, Layer, StopInput } from '../../core/layer'
import { activeRun, runOf, updateRun } from '../../core/tracker'
import { blockCounts, preferCounts, type FixerCounts } from '../../core/usageRow'
import { ioOf, resolveWatch, type Watch } from '../../core/watch'
import { registerBand } from './band'
import {
  keywordBlock, mentionsBubble, missingFromReview, readReview, reviewFileFor, sidecarIds, stopBlock, verdictPrefix,
  type ReviewDoc,
} from './bubbles'
import { prReviewConfigOf, runtimeBaseOf, type PrReviewConfig } from './config'
import { identifyHeader } from './identify'
import {
  buildRow, buildWorkflowRow, validateRow, workflowPlan, type MatrixRow, type WorkflowPlan,
} from './matrixRow'
import { registerPhase5Context, scanSentinels, type HotSentinel } from './phase5Scan'
import {
  closeRun, currentRunId, fixerBubbledIds, markLogged, planPhase, recoverReviewers, reportCounts, reviewersSettled,
  reviewersToLog, settle, withDiskPhase,
} from './runs'
import { keyOfRunId, runDirName, startedAtOfRunId, toRunKey, type RunKey } from './runKey'
import { blocksSession } from './sentinels'

/**
 * The pr-review layer: claims pr-team and pr-review dispatches, follows their phases and bubbled ids, owns
 * the invocation-matrix rows (reviewers, and the zero-count rows of an adversarial Workflow's slots) and
 * guards Stop on undispositioned bubbled ids. Core calls the `prReviewLayer` members with an `Io`; the hooks
 * the engine raises on their own (shell refresh, Workflow rows, recovery, the prompt line, the band) register
 * in `registerPrReviewLayer(on)`. Its paths and base branch come from `harness.json` (./config). Every host
 * failure degrades to doing nothing.
 */

type Dollar = EngineInterface

/** The layer's name: what a run it claims records as `claimedBy`. */
const LAYER_NAME = 'pr-review'

/** A shell command that drives pr-review's script; its result can move a run's phase or bubbles. */
const PR_REVIEW_SCRIPT = /pr_review\.py/
const MARKER = '.matrix_owner'
export const OWNER_NOTE =
  '[agent-watcher] Matrix rows for this run are recorded by the agent-watcher mod; ' +
  'skip the manual JSONL append (pr-review Phase 3 Step 4).'

const noop = (): undefined => undefined
const cfgOf = (io: Io): PrReviewConfig => prReviewConfigOf(io.watch.harness)

// ---------------------------------------------------------------------------
// Git

/** The configured base branch, else the branch `origin/HEAD` names, else `main` (resolve_base_branch). */
const baseBranchFor = async (io: Io): Promise<string> => {
  const base = cfgOf(io).baseBranch
  if (base !== null) return base
  const head = await io.gitLine(['symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD'])
  const slash = head?.indexOf('/') ?? -1
  return head !== undefined && slash > 0 ? head.slice(slash + 1) : 'main'
}

/** `<merge-base> -- <branch> (agent-watcher auto)`; empty (which fails validation) when git fails. */
const devCommitFor = async (io: Io): Promise<string> => {
  const sha = await io.gitLine(['merge-base', 'HEAD', await baseBranchFor(io)])
  const branch = (await io.gitLine(['rev-parse', '--abbrev-ref', 'HEAD'])) ?? '?'
  return sha === undefined ? '' : `${sha} -- ${branch} (agent-watcher auto)`
}

// ---------------------------------------------------------------------------
// Review JSON and run folders

/** The newest review JSON for a run key (PR number or local key), unless it is older than `sinceMs`. */
const loadReviewFor = async (io: Io, key: RunKey, sinceMs: number): Promise<ReviewDoc | undefined> => {
  const dir = under(io.watch.root, cfgOf(io).reviewsDir)
  const hit = reviewFileFor(key, await io.listDir(dir))
  if (hit === undefined || hit.mtimeMs < sinceMs) return undefined
  const text = await io.readText(`${dir}/${hit.name}`)
  return text === undefined ? undefined : readReview(text)
}

/** The run's review JSON: newest for its run key and not older than the run. */
const loadReview = (io: Io, run: Run): Promise<ReviewDoc | undefined> =>
  run.pr === null ? Promise.resolve(undefined) : loadReviewFor(io, run.pr, run.startedAt)

const loadSidecar = async (io: Io, run: Run): Promise<string[] | null> => {
  if (run.runtimeDir === null) return null
  const text = await io.readText(`${under(io.watch.root, run.runtimeDir)}/bubble_ups.json`)
  return text === undefined ? null : sidecarIds(text)
}

/** What a pr-review run directory says: the `plan.json` phase and the fixer-bubbled ids. */
type RunDisk = { phase: Phase | undefined; fixerBubbled: string[] }
const NO_RUN_DISK: RunDisk = { phase: undefined, fixerBubbled: [] }

/**
 * The pr-review run directory under `artifacts.scratch` (`<NNNN>/current` names the active run,
 * `<NNNN>/<RUN_ID>/` holds it; a local run's folder is its key, `local-<label>/`), only while the key
 * folder's `current` names this run.
 */
const prReviewRunDir = async (io: Io, run: Run): Promise<string | undefined> => {
  if (run.skill !== 'pr-review' || run.pr === null) return undefined
  const prDir = `${under(io.watch.root, cfgOf(io).scratchDir)}/${runDirName(run.pr)}`
  return currentRunId(await io.readText(`${prDir}/current`)) === run.runId ? `${prDir}/${run.runId}` : undefined
}

const fixerReports = async (io: Io, dir: string): Promise<string[]> => {
  const names = (await io.listDir(dir)).filter(e => e.kind === 'file' && e.name.endsWith('.json')).map(e => e.name)
  const texts = await Promise.all(names.sort().map(name => io.readText(`${dir}/${name}`)))
  return texts.filter((t): t is string => t !== undefined)
}

const loadRunDisk = async (io: Io, run: Run): Promise<RunDisk> => {
  const dir = await prReviewRunDir(io, run)
  if (dir === undefined) return NO_RUN_DISK
  const plan = await io.readText(`${dir}/plan.json`)
  const phase = plan === undefined ? undefined : planPhase(plan)
  return { phase, fixerBubbled: fixerBubbledIds(await fixerReports(io, `${dir}/fixes`)) }
}

// ---------------------------------------------------------------------------
// Completion and usage counts

/** The closer's block closes the run, inside core's fold update (pure). */
const foldRun = (run: Run, agentId: string, c: Completion): Run => closeRun(run, agentId, c.block)

/** The orchestrator's DONE plan writes the pending ownership marker. */
const onComplete = async (io: Io, run: Run, agentId: string, c: Completion): Promise<void> => {
  if (agentId !== 'orchestrator_plan' || c.block?.signal !== 'DONE' || run.runtimeDir === null) return
  await io.write(`${under(io.watch.root, run.runtimeDir)}/${MARKER}`, 'pending\n')
}

/**
 * Outcome counts: closer and pr-team fixers from the return block; a pr-review fixer from its run's
 * waves.json and fixes/<id>.json, falling back to the block; other roles none.
 */
const rowFields = async (io: Io, run: Run, agent: AgentRec, c: Completion): Promise<FixerCounts | undefined> => {
  if (agent.role === 'closer' || (agent.role === 'fixer' && run.skill === 'pr-team')) return blockCounts(c.block)
  if (agent.role !== 'fixer') return undefined
  const dir = await prReviewRunDir(io, run).catch(noop)
  const read = (rel: string): Promise<string | undefined> =>
    dir === undefined ? Promise.resolve(undefined) : io.readText(`${dir}/${rel}`)
  const [waves, report] = await Promise.all([read('waves.json'), read(`fixes/${agent.id}.json`)])
  return preferCounts(reportCounts(waves, report, agent.id), blockCounts(c.block))
}

// ---------------------------------------------------------------------------
// Matrix rows

const MATRIX_CHECK: RowCheck<MatrixRow> = { label: 'matrix', problems: validateRow, cellOf: r => r.cell }

/**
 * Claims the run's unlogged reviewers: marks them logged inside one atom update and returns them, so an
 * overlapping refresh finds nothing left to claim and never appends the same rows again.
 */
const claimReviewers = async (io: Io, runId: string, now: number): Promise<AgentRec[]> => {
  let claimed: AgentRec[] = []
  await updateRun(io, runId, r => {
    claimed = reviewersToLog(r)
    return claimed.length === 0 ? r : markLogged(r, claimed.map(a => a.id), now)
  })
  return claimed
}

/**
 * Whether a run logs matrix rows: only a run keyed by a PR number. The matrix schema keys rows by PR number, so
 * a review-local run (`local-<label>`) logs none.
 */
const logsMatrix = (run: Run | undefined): run is Run & { pr: number } => typeof run?.pr === 'number'

const flushNow = async (io: Io, runId: string): Promise<void> => {
  const run = await runOf(io, runId)
  const prefix = verdictPrefix(run?.verdict ?? null)
  if (!logsMatrix(run) || prefix === undefined || !reviewersSettled(run)) return
  const now = await io.now()
  const agents = await claimReviewers(io, runId, now)
  if (agents.length === 0) return
  const devCommit = await devCommitFor(io)
  const pr = run.pr
  const rows = agents.map(agent => buildRow({ pr, agent, verdictPrefix: prefix, devCommit }))
  const path = under(io.watch.root, cfgOf(io).matrixPath)
  await recordFailures(io, await appendValid(io, path, rows, MATRIX_CHECK, now), 'matrix')
  if (run.runtimeDir === null) return
  await io.write(`${under(io.watch.root, run.runtimeDir)}/${MARKER}`, `logged ${new Date(now).toISOString()}\n`)
}

const flush = (io: Io, runId: string): Promise<unknown> => serialize(() => flushNow(io, runId))

/** Marks a run id's Workflow rows as attempted, in the run's folder under `artifacts.scratch`. */
const WORKFLOW_MARKER = '.workflow_rows'

const workflowMarkerOf = (io: Io, pr: number, runId: string): string =>
  `${under(io.watch.root, cfgOf(io).scratchDir)}/${runDirName(pr)}/${runId}/${WORKFLOW_MARKER}`

/**
 * One zero-count row per slot an adversarial Workflow call plans (`buildWorkflowRow`), appended when the call
 * is made: the mod cannot tie a Workflow agent's loop to its slot, and SPK-1 found no usage row for one, so no
 * later event fills the counts in. Attempted once per run id: the marker is written before the append, and a
 * second call for the same run id finds it. A run keyed by a local key logs none, as `logsMatrix` rules for
 * dispatched reviewers.
 */
const logWorkflowNow = async (io: Io, plan: WorkflowPlan): Promise<void> => {
  const pr = plan.runKey
  if (typeof pr !== 'number' || plan.slots.length === 0) return
  const marker = workflowMarkerOf(io, pr, plan.runId)
  if ((await io.readText(marker)) !== undefined) return
  await io.write(marker, `attempted ${new Date(await io.now()).toISOString()}\n`)
  const devCommit = await devCommitFor(io)
  const rows = plan.slots.map(slot => buildWorkflowRow({ pr, slot, devCommit }))
  const path = under(io.watch.root, cfgOf(io).matrixPath)
  await recordFailures(io, await appendValid(io, path, rows, MATRIX_CHECK, await io.now()), 'matrix')
}

const logWorkflow = (io: Io, plan: WorkflowPlan): Promise<unknown> => serialize(() => logWorkflowNow(io, plan))

// ---------------------------------------------------------------------------
// Settle, recovery, stop

/** Re-reads disk for the active run: sentinels, verdict, bubbled set, missing ids; flushes rows. */
const onSettle = async (io: Io, run: Run | undefined): Promise<void> => {
  const phase5 = (await scanSentinels(io).catch(() => [] as HotSentinel[])).map(s => s.pr)
  await io.setPhase5(phase5)
  if (run === undefined) {
    await io.setMissing([])
    return
  }
  const review = await loadReview(io, run)
  const sidecar = await loadSidecar(io, run)
  const disk = await loadRunDisk(io, run).catch(() => NO_RUN_DISK)
  await updateRun(io, run.runId, r => withDiskPhase(settle(r, review, sidecar, disk.fixerBubbled), disk.phase))
  const settled = await runOf(io, run.runId)
  const tracked = settled === undefined || settled.bubbledFrom === 'review_json' ? [] : settled.bubbled
  await io.setMissing(missingFromReview(tracked, review))
  if (review !== undefined) await flush(io, run.runId)
}

/**
 * A run rebuilt from its runtime dir: plan reviewers joined with terminals rows. Its start is the run id's
 * stamp, so an older review JSON for the same PR is never taken for its verdict; no stamp, no recovery.
 * Recovery exists to log matrix rows, so a run id without a PR number (a local key) is not recovered.
 */
const recoveredRun = async (io: Io, runId: string): Promise<Run | undefined> => {
  const runtimeDir = `${runtimeBaseOf(io.watch.cfg)}/${runId}`
  const dir = under(io.watch.root, runtimeDir)
  const plan = await io.readText(`${dir}/dispatch_plan_review.json`)
  const pr = keyOfRunId(runId)
  const startedAt = startedAtOfRunId(runId)
  if (plan === undefined || typeof pr !== 'number' || startedAt === null) return undefined
  const agents = recoverReviewers(plan, (await io.readText(`${dir}/terminals.jsonl`)) ?? '')
  return {
    runId, skill: 'pr-team', pr, phase: 'consolidate', runtimeDir,
    agents: Object.fromEntries(agents.map(a => [a.id, a])), bubbled: [], bubbledFrom: 'none', verdict: null,
    startedAt, claimedBy: LAYER_NAME,
  }
}

/** Rows for a pr-team run a previous session claimed but never logged. */
const recoverRun = async (io: Io, runId: string): Promise<void> => {
  const run = await recoveredRun(io, runId)
  if (run === undefined) return
  await io.updateRuns(runs => (runs[runId] === undefined ? { ...runs, [runId]: run } : runs))
  const review = await loadReview(io, run)
  if (review === undefined) return
  await updateRun(io, runId, r => settle(r, review, null))
  await flush(io, runId)
}

const recoverPending = async (io: Io): Promise<void> => {
  const known = await io.runs()
  const base = under(io.watch.root, runtimeBaseOf(io.watch.cfg))
  for (const entry of await io.listDir(base)) {
    if (entry.kind !== 'dir' || known[entry.name] !== undefined) continue
    const marker = await io.readText(`${base}/${entry.name}/${MARKER}`)
    if (marker?.startsWith('pending')) await recoverRun(io, entry.name).catch(noop)
  }
}

type PrReview = [RunKey, ReviewDoc | undefined]

/**
 * The active review for the keyword check: the tracked run's key, else that of the first hot sentinel
 * blocking the stopping session (`blocksSession`; another session's sentinel is not this one's review).
 */
const keywordReview = async (
  io: Io,
  run: Run | undefined,
  sessionId: string | undefined,
): Promise<PrReview | undefined> => {
  if (run !== undefined && run.pr !== null) return [run.pr, await loadReview(io, run)]
  const hot = await scanSentinels(io).catch(() => [] as HotSentinel[])
  const key = toRunKey(hot.find(s => blocksSession(s.owner, sessionId))?.pr)
  return key === null ? undefined : [key, await loadReviewFor(io, key, 0)]
}

/** Tracked bubbled ids out of the review JSON (pr-team), then the "bubble" keyword rule (any review). */
const stopReason = async (io: Io, e: StopInput): Promise<string | undefined> => {
  const run = await activeRun(io)
  const missing = await io.missing()
  const tracked =
    run?.skill === 'pr-team' ? stopBlock(run.pr, missing, run.bubbledFrom, e.stop_hook_active) : undefined
  if (tracked !== undefined || !mentionsBubble(e.last_assistant_message)) return tracked
  const hit = await keywordReview(io, run, e.session_id)
  return hit === undefined ? undefined : keywordBlock(hit[0], e.last_assistant_message, hit[1], e.stop_hook_active)
}

/** The ownership note for a pr-review reviewer whose run is recorded with a PR number (`logsMatrix`). */
const resultContext = async (_io: Io, run: Run, agent: Claim): Promise<string[]> =>
  agent.skill === 'pr-review' && agent.role === 'reviewer' && logsMatrix(run) ? [OWNER_NOTE] : []

/** A pr-team or pr-review header; the pr-team runtime base follows the project's `state_dir`. */
const identify = (subagentType: string | undefined, header: Header, watch: Watch | undefined) =>
  identifyHeader(subagentType, header, watch === undefined ? '' : runtimeBaseOf(watch.cfg))

export const prReviewLayer: Layer = {
  name: LAYER_NAME, identify, foldRun, onComplete, rowFields, resultContext, onSettle, stopReason,
}

// ---------------------------------------------------------------------------
// Hooks of the layer's own

/** Settles the active run for the session's project; nothing outside a harness project. */
async function refreshLayer($: Dollar): Promise<void> {
  const w = await resolveWatch($)
  if (w === undefined) return
  const io = ioOf($, w)
  await onSettle(io, await activeRun(io))
}

/** A shell call that ran pr-review's script refreshes, so the band moves within a turn. */
async function afterShell($: Dollar, command: string | undefined): Promise<void> {
  if (PR_REVIEW_SCRIPT.test(command ?? '')) await refreshLayer($).catch(noop)
}

/** Recovers the pr-team runs a previous session claimed but never logged, then refreshes. */
async function recoverThenRefresh($: Dollar): Promise<void> {
  const w = await resolveWatch($)
  if (w === undefined) return
  const io = ioOf($, w)
  await recoverPending(io).catch(noop)
  await onSettle(io, await activeRun(io)).catch(noop)
}

/** The fields of a Workflow call and its answer the layer reads; the engine's types are wider. */
type WorkflowCall = { args?: unknown; agentId?: string; resumeFromRunId?: unknown }
type ToolAnswer = { deny?: unknown; isError?: unknown; result?: unknown }

/** Whether the tool launched the workflow: not refused, not errored, no `result.error` (a failed syntax check). */
const launched = (answer: ToolAnswer): boolean => {
  const result = answer.result
  const failed =
    typeof result === 'object' && result !== null && 'error' in result && result.error !== undefined
  return answer.deny === undefined && answer.isError !== true && !failed
}

/**
 * The main session's Workflow call that launched: the zero-count rows for the slots its args plan. A call
 * that did not launch, a resume (`resumeFromRunId`) or a call a subagent makes logs none.
 */
async function afterWorkflow($: Dollar, call: WorkflowCall, answer: ToolAnswer): Promise<void> {
  if (call.agentId !== undefined || call.resumeFromRunId !== undefined || !launched(answer)) return
  const plan = workflowPlan(call.args)
  const w = plan === undefined ? undefined : await resolveWatch($)
  if (plan === undefined || w === undefined) return
  await logWorkflow(ioOf($, w), plan)
}

/** Shell refreshes, Workflow rows, session-start recovery, the per-prompt Phase 5 line and the band. */
export const registerPrReviewLayer = (on: On): void => {
  on('tool.call', { tool: 'Workflow' }, async ($, e, next) => {
    const r = await next(e)
    await afterWorkflow($, e as unknown as WorkflowCall, r).catch(noop)
    return r
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

  on('session.start', async ($, e, next) => {
    const r = await next(e)
    await recoverThenRefresh($).catch(noop)
    return r
  })

  registerPhase5Context(on)
  registerBand(on)
}
