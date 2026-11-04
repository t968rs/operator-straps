import type { AgentRec, Run } from '../../types'
import type { Dispatch } from './contract'
import type { Completion, Runs } from './layer'

/** Pure run transitions every layer shares: dispatch, completion and the usage-row claim. No `$`. */

/** What the `Agent` call itself says about the agent. */
export type DispatchMeta = { model?: string; effort?: string; subagentType?: string }

export const newAgent = (d: Dispatch, meta: DispatchMeta): AgentRec => ({
  id: d.agentId, role: d.role, model: meta.model ?? null, effort: meta.effort ?? null,
  tokens: 0, toolUses: 0, durationMs: 0, isMeasured: false, signal: null, counts: null, loggedAt: null,
  subagentType: meta.subagentType ?? null, usageLoggedAt: null, launchModel: null,
})

const newRun = (d: Dispatch, now: number, claimedBy: string | undefined): Run => ({
  runId: d.runId, skill: d.skill, pr: d.pr, phase: d.phase, runtimeDir: d.runtimeDir,
  agents: {}, bubbled: [], bubbledFrom: 'none', verdict: null, startedAt: now,
  ...(claimedBy === undefined ? {} : { claimedBy }),
})

/**
 * Records a dispatch: the run is created on first sight, owned by `claimedBy` (the claiming layer's name;
 * unset for a standalone run), and the phase follows the dispatch.
 */
export const applyDispatch = (
  runs: Readonly<Runs>,
  d: Dispatch,
  rec: AgentRec,
  now: number,
  claimedBy?: string,
): Runs => {
  const run = runs[d.runId] ?? newRun(d, now, claimedBy)
  const agents = { ...run.agents, [d.agentId]: rec }
  const next: Run = { ...run, pr: run.pr ?? d.pr, runtimeDir: run.runtimeDir ?? d.runtimeDir, phase: d.phase, agents }
  return { ...runs, [d.runId]: next }
}

const foldAgent = (a: AgentRec, c: Completion): AgentRec => ({
  ...a,
  tokens: a.tokens + c.tokens,
  toolUses: a.toolUses + c.toolUses,
  durationMs: a.durationMs + c.durationMs,
  model: c.model ?? a.model,
  isMeasured: a.isMeasured || c.isMeasured,
  signal: c.block?.signal ?? 'NO_BLOCK',
  counts: c.block?.counts ?? a.counts,
})

/** Folds a completion into its agent: usage adds up, the signal and counts follow the latest block. */
export const applyCompletion = (run: Run, agentId: string, c: Completion): Run => {
  const prev = run.agents[agentId]
  return prev === undefined ? run : { ...run, agents: { ...run.agents, [agentId]: foldAgent(prev, c) } }
}

/** The agent when it has returned and its usage row is not yet attempted; else undefined. */
export const usageToLog = (run: Run, agentId: string): AgentRec | undefined => {
  const a = run.agents[agentId]
  return a !== undefined && a.signal !== null && a.usageLoggedAt === null ? a : undefined
}

export const markUsageLogged = (run: Run, agentId: string, now: number): Run => {
  const a = run.agents[agentId]
  return a === undefined ? run : { ...run, agents: { ...run.agents, [agentId]: { ...a, usageLoggedAt: now } } }
}

/** `runs` with `fn` applied to one run; unchanged when that run is absent. */
export const withRun = (runs: Readonly<Runs>, runId: string, fn: (run: Run) => Run): Runs => {
  const cur = runs[runId]
  return cur === undefined ? runs : { ...runs, [runId]: fn(cur) }
}
