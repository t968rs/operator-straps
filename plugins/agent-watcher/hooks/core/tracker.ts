import type { EngineInterface, On } from 'claude-code'
import { atom, read, update } from 'claude-code'

import type { AgentRec, Run } from '../../types'
import { under } from './config'
import {
  leadingHeader, parseHeader, parseReturnBlock, standaloneRunId, type Dispatch, type Header,
} from './contract'
import { appendValid, recordFailures, serialize, type RowCheck } from './jsonl'
import type { AgentAnswer, Completion, Io, Layer, Runs, StopInput } from './layer'
import {
  applyCompletion, applyDispatch, markUsageLogged, newAgent, usageToLog, withRun, type DispatchMeta,
} from './runs'
import {
  buildUsageRow, NO_COUNTS, unclaimedDispatch, validateUsageRow, type FixerCounts, type UsageRow,
} from './usageRow'
import { ioOf, resolveWatch, type Watch } from './watch'

/**
 * The generic core of agent-watcher: tracks every `Agent` dispatch (Decision D5), the ones a layer claims and
 * the unclaimed ones, read from the prompt's leading header block (./usageRow `unclaimedDispatch`); folds
 * subagent usage, appends one agent usage row per returned dispatch, and hands each claimed run to its layer
 * and the refresh and Stop check to every layer (./layer). Active only in a project holding
 * `.claude/harness.json` (./watch). Every host failure, and every layer member that throws, degrades to doing
 * nothing; no hook throws into a tool call, a turn or a stop.
 */

type Dollar = EngineInterface
/** Which agent of which run a completion belongs to. */
export type Key = { runId: string; agentId: string }
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
type Usage = {
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
  model: string
}
type TurnEnd = { answer: string; durationMs: number; usage?: Usage }
/** A tracked dispatch: who it is, the project, and the layer that claimed it (none for an unclaimed run). */
type Tracked = { d: Dispatch; w: Watch; layer: Layer | undefined }

const runsAtom = atom({ plugin: 'agent-watcher', key: 'runs' } as const, {})
const activeAtom = atom({ plugin: 'agent-watcher', key: 'active' } as const, null)
const loopsAtom = atom({ plugin: 'agent-watcher', key: 'loops' } as const, {})

const noop = (): undefined => undefined
/** Tool calls per subagent loop id, counted for background launches. */
const toolUses = new Map<string, number>()
/** Numbers the unclaimed runs of this process, so same-second dispatches never share a run id. */
let standaloneSeq = 0

/** A layer member's answer, or undefined when it throws or rejects: one layer never stops another. */
const attempt = async <T>(call: () => Promise<T> | undefined): Promise<T | undefined> => {
  try {
    return await call()
  } catch {
    return undefined
  }
}

// ---------------------------------------------------------------------------
// Run state through Io (shared with the layers)

export const runOf = async (io: Io, runId: string): Promise<Run | undefined> => (await io.runs())[runId]

export const updateRun = (io: Io, runId: string, fn: (run: Run) => Run): Promise<void> =>
  io.updateRuns(runs => withRun(runs, runId, fn))

/** The run dispatched most recently by a layer-claimed dispatch; undefined before any. */
export const activeRun = async (io: Io): Promise<Run | undefined> => {
  const id = await io.activeRunId()
  return id === null ? undefined : runOf(io, id)
}

/** The layer that claimed the run (`claimedBy`); undefined for an unclaimed run or an unknown name. */
export const layerOf = (layers: readonly Layer[], run: Run | undefined): Layer | undefined =>
  run?.claimedBy === undefined ? undefined : layers.find(l => l.name === run.claimedBy)

// ---------------------------------------------------------------------------
// Identity

/** The first layer's claim on a dispatch, with that layer; undefined when none claims it. */
const claimOf = (
  layers: readonly Layer[],
  subagentType: string | undefined,
  header: Header,
  w: Watch | undefined,
): [Dispatch, Layer] | undefined => {
  for (const layer of layers) {
    try {
      const d = layer.identify(subagentType, header, w)
      if (d !== undefined) return [d, layer]
    } catch {
      continue
    }
  }
  return undefined
}

/**
 * The tracked identity of any `Agent` dispatch in a harness project, with that project and its claiming
 * layer; else undefined (outside a harness project). A layer's claim names the run, read from every header
 * line of the prompt; a dispatch no layer claims is a run of its own under a generated id (Decision D10),
 * its row values read from the leading header block (Decisions D3, D11).
 */
async function trackedDispatch(
  $: Dollar,
  layers: readonly Layer[],
  subagentType: string | undefined,
  prompt: string,
): Promise<Tracked | undefined> {
  const w = await resolveWatch($).catch(noop)
  if (w === undefined) return undefined
  const claim = claimOf(layers, subagentType, parseHeader(prompt), w)
  if (claim !== undefined) return { d: claim[0], w, layer: claim[1] }
  const runId = standaloneRunId(await $.clock.now(), ++standaloneSeq)
  return { d: unclaimedDispatch(subagentType, leadingHeader(prompt), runId), w, layer: undefined }
}

// ---------------------------------------------------------------------------
// Dispatch and completion

/** The run as `applyDispatch` stored it, plus an unclaimed dispatch's logged run id and fields. */
export const withRowIdentity = (runs: Readonly<Runs>, d: Dispatch): Runs =>
  withRun(runs, d.runId, run => ({
    ...run,
    ...(d.logRunId === undefined ? {} : { logRunId: d.logRunId }),
    ...(d.fields === undefined ? {} : { fields: d.fields }),
  }))

/** Records the dispatch; only a claimed one becomes the active run the band and the layers follow. */
async function recordDispatch($: Dollar, t: Tracked, meta: DispatchMeta): Promise<void> {
  const { d } = t
  const now = await $.clock.now()
  const rec = newAgent(d, meta)
  await update($, runsAtom, runs => withRowIdentity(applyDispatch(runs, d, rec, now, t.layer?.name), d))
  if (t.layer !== undefined) await update($, activeAtom, () => d.runId)
}

/** An unclaimed run holds one agent; once its usage row is attempted the run is dropped, bounding state. */
async function dropUnclaimed($: Dollar, runId: string): Promise<void> {
  await update($, runsAtom, runs => {
    const run = runs[runId]
    if (run === undefined || run.claimedBy !== undefined) return runs
    return Object.fromEntries(Object.entries(runs).filter(([id]) => id !== runId))
  })
}

/** The completion folded into its agent, then the claiming layer's `foldRun` (skipped when it throws). */
export const foldInto = (layers: readonly Layer[], run: Run, agentId: string, c: Completion): Run => {
  const folded = applyCompletion(run, agentId, c)
  const foldRun = layerOf(layers, run)?.foldRun
  if (foldRun === undefined) return folded
  try {
    return foldRun(folded, agentId, c)
  } catch {
    return folded
  }
}

/** The claiming layer's side effects for a stored fold. */
export const completeLayer = async (
  io: Io,
  layers: readonly Layer[],
  key: Key,
  c: Completion,
): Promise<void> => {
  const run = await runOf(io, key.runId)
  const layer = layerOf(layers, run)
  if (run !== undefined) await attempt(() => layer?.onComplete?.(io, run, key.agentId, c))
}

/** Folds the completion, lets the claiming layer follow it, logs the usage row; an unclaimed run then goes. */
async function complete(
  $: Dollar,
  w: Watch | undefined,
  layers: readonly Layer[],
  key: Key,
  c: Completion,
): Promise<void> {
  try {
    await update($, runsAtom, runs => withRun(runs, key.runId, run => foldInto(layers, run, key.agentId, c)))
    if (w === undefined) return
    const io = ioOf($, w)
    await completeLayer(io, layers, key, c)
    await logUsage(io, layers, key, c)
  } finally {
    await dropUnclaimed($, key.runId)
  }
}

const textOf = (r: AgentResult): string => (r.content ?? []).map(b => b.text ?? '').join('\n')

/** Maps the loop to its agent and keeps the model the engine launched it with. */
async function registerLoop($: Dollar, loopId: string, key: Key, model: string | null): Promise<void> {
  await update($, loopsAtom, loops => ({ ...loops, [loopId]: [key.runId, key.agentId] as [string, string] }))
  await update($, runsAtom, runs => withRun(runs, key.runId, run => {
    const a = run.agents[key.agentId]
    return a === undefined ? run : { ...run, agents: { ...run.agents, [key.agentId]: { ...a, launchModel: model } } }
  }))
}

/** Folds an Agent tool result: usage now when synchronous, a loop registration when backgrounded. */
async function recordResult(
  $: Dollar,
  w: Watch,
  layers: readonly Layer[],
  key: Key,
  r: AgentAnswer,
): Promise<void> {
  const res = (r.deny === undefined && r.isError !== true ? r.result : undefined) as AgentResult | undefined
  if (res?.status === 'async_launched' && res.agentId !== undefined) {
    return registerLoop($, res.agentId, key, res.resolvedModel ?? null)
  }
  const isDone = res?.status === 'completed'
  await complete($, w, layers, key, {
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
async function recordLoopEnd($: Dollar, layers: readonly Layer[], loopId: string, e: TurnEnd): Promise<void> {
  const used = toolUses.get(loopId) ?? 0
  toolUses.delete(loopId)
  const hit = (await read($, loopsAtom))[loopId]
  if (hit === undefined) return
  await update($, loopsAtom, loops => Object.fromEntries(Object.entries(loops).filter(([k]) => k !== loopId)))
  await complete($, await resolveWatch($), layers, { runId: hit[0], agentId: hit[1] }, {
    tokens: usageTokens(e.usage), toolUses: used, durationMs: e.durationMs, model: e.usage?.model ?? null,
    block: parseReturnBlock(e.answer), isMeasured: e.usage !== undefined, ending: 'ok',
  })
}

// ---------------------------------------------------------------------------
// Usage rows

const USAGE_CHECK: RowCheck<UsageRow> = {
  label: 'usage log', problems: validateUsageRow, cellOf: r => `${r.run_id}/${r.agent_id}`,
}

/** Claims the agent's usage row inside one atom update, so a second fold never appends it again. */
const claimUsage = async (io: Io, key: Key, now: number): Promise<[Run, AgentRec] | undefined> => {
  const box: { hit?: [Run, AgentRec] } = {}
  await updateRun(io, key.runId, r => {
    box.hit = undefined
    const a = usageToLog(r, key.agentId)
    if (a === undefined) return r
    box.hit = [r, a]
    return markUsageLogged(r, key.agentId, now)
  })
  return box.hit
}

/** Outcome counts from the claiming layer's `rowFields`; none when it has no answer or throws. */
export const countsFor = async (
  io: Io,
  layers: readonly Layer[],
  run: Run,
  agent: AgentRec,
  c: Completion,
): Promise<FixerCounts> => {
  const layer = layerOf(layers, run)
  return (await attempt(() => layer?.rowFields?.(io, run, agent, c))) ?? NO_COUNTS
}

/** One usage row per returned dispatch; a denied dispatch never ran and writes none. */
export const logUsage = async (io: Io, layers: readonly Layer[], key: Key, c: Completion): Promise<void> => {
  if (c.ending === 'denied') return
  const now = await io.now()
  const hit = await claimUsage(io, key, now)
  if (hit === undefined) return
  const [run, claimed] = hit
  const counts = await countsFor(io, layers, run, claimed, c)
  // The engine's model: this completion's, else the background launch's, else the requested one.
  const agent = { ...claimed, model: c.model ?? claimed.launchModel ?? claimed.model }
  // The usage schema's `pr` is a PR number or null: a local run logs null; its run_id carries the key.
  const pr = typeof run.pr === 'number' ? run.pr : null
  // Only an unclaimed run logs header fields, under its header RUN_ID when it gave one.
  const isUnclaimed = run.claimedBy === undefined
  const row = buildUsageRow({
    runId: (isUnclaimed ? run.logRunId : undefined) ?? run.runId, skill: run.skill, pr, agent, ending: c.ending,
    isMeasured: c.isMeasured, loggedAt: now, counts, ...(isUnclaimed && run.fields !== undefined ? { fields: run.fields } : {}),
  })
  const path = under(io.watch.root, io.watch.cfg.agentUsagePath)
  await serialize(async () => recordFailures(io, await appendValid(io, path, [row], USAGE_CHECK, now), 'usage'))
}

// ---------------------------------------------------------------------------
// Fan-out to the layers

/** Every layer settles the active run (re-reads its disk state, appends rows that became due). */
export const settleLayers = async (io: Io, layers: readonly Layer[]): Promise<void> => {
  const run = await activeRun(io)
  for (const layer of layers) await attempt(() => layer.onSettle?.(io, run))
}

/** `settleLayers` for the session's project; nothing outside a harness project. */
async function refresh($: Dollar, layers: readonly Layer[]): Promise<void> {
  const w = await resolveWatch($)
  if (w !== undefined) await settleLayers(ioOf($, w), layers)
}

/** The first Stop reason any layer gives, in layer order; a layer that throws gives none. */
export const stopReasonOf = async (
  io: Io,
  layers: readonly Layer[],
  e: StopInput,
): Promise<string | undefined> => {
  for (const layer of layers) {
    const reason = await attempt(() => layer.stopReason?.(io, e))
    if (reason !== undefined) return reason
  }
  return undefined
}

/** The Stop block the layers owe after a refresh, or undefined; nothing outside a harness project. */
async function stopBlockFor($: Dollar, layers: readonly Layer[], e: StopInput): Promise<string | undefined> {
  const w = await resolveWatch($)
  if (w === undefined) return undefined
  const io = ioOf($, w)
  await settleLayers(io, layers).catch(noop)
  return stopReasonOf(io, layers, e)
}

/** The lines the claiming layer appends to a successful Agent result's context; none on a throw. */
export const contextFor = async (
  io: Io,
  layers: readonly Layer[],
  d: Dispatch,
  r: AgentAnswer,
): Promise<string[]> => {
  const run = await runOf(io, d.runId).catch(noop)
  const layer = layerOf(layers, run)
  if (run === undefined) return []
  return (await attempt(() => layer?.resultContext?.(io, run, d, r))) ?? []
}

// ---------------------------------------------------------------------------
// Hooks

/** Tool-call hooks: every Agent dispatch, and per-loop tool counts. */
const registerToolHooks = (on: On, layers: readonly Layer[]): void => {
  on('tool.call', { tool: 'Agent' }, async ($, e, next) => {
    const t = await trackedDispatch($, layers, e.subagent_type, e.prompt)
    if (t === undefined) return next(e)
    const { d, w } = t
    const io = ioOf($, w)
    await recordDispatch($, t, { model: e.model, effort: e.effort, subagentType: e.subagent_type }).catch(noop)
    const r = await next(e)
    await recordResult($, w, layers, { runId: d.runId, agentId: d.agentId }, r).catch(noop)
    if (t.layer !== undefined) await settleLayers(io, layers).catch(noop)
    // Refusals inline (not a helper) so the checker narrows `r` to a result that takes context.
    if (r.deny !== undefined || r.isError === true) return r
    const lines = await contextFor(io, layers, d, r).catch(() => [] as string[])
    return lines.length === 0 ? r : { ...r, context: [...(r.context ?? []), ...lines] }
  })

  on('tool.call', ($, e, next) => {
    if (e.agentId !== undefined) toolUses.set(e.agentId, (toolUses.get(e.agentId) ?? 0) + 1)
    return next(e)
  })
}

/** Turn and Stop hooks: loop usage, refreshes and the Stop guard. */
const registerLifecycleHooks = (on: On, layers: readonly Layer[]): void => {
  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    if (e.agentId !== undefined) await recordLoopEnd($, layers, e.agentId, e).catch(noop)
    await refresh($, layers).catch(noop)
    return r
  })

  on('classic.Stop', async ($, e, next) => {
    const r = await next(e)
    if (r.block !== undefined) return r
    const block = await stopBlockFor($, layers, e).catch(noop)
    return block === undefined ? r : { ...r, block }
  })
}

/** Registers the core hooks; `layers` claim dispatches and receive the fan-out, in order. */
export const registerCore = (on: On, layers: readonly Layer[]): void => {
  registerToolHooks(on, layers)
  registerLifecycleHooks(on, layers)
}
