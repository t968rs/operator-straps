import type { AgentRec, Counts, Phase, Run } from '../types'
import { allDispositioned, type ReviewDoc } from './bubbles'
import type { Dispatch, ReturnBlock } from './contract'

/** Pure state transitions over tracked runs, plus the band text. No `$`. */

/** What one subagent turn (or a synchronous Agent result) contributes. */
export type Completion = {
  tokens: number
  toolUses: number
  durationMs: number
  model: string | null
  block: ReturnBlock | undefined
  isMeasured: boolean
}

const PHASE_LABEL: Readonly<Record<Phase, string>> = {
  plan: 'planning', review: 'reviewers', consolidate: 'consolidating', 'fix-plan': 'fix planning',
  fix: 'fixers', closeout: 'closeout', done: 'done',
}

export const newAgent = (d: Dispatch, meta: { model?: string; effort?: string }): AgentRec => ({
  id: d.agentId, role: d.role, model: meta.model ?? null, effort: meta.effort ?? null,
  tokens: 0, toolUses: 0, durationMs: 0, isMeasured: false, signal: null, counts: null, loggedAt: null,
})

const newRun = (d: Dispatch, now: number): Run => ({
  runId: d.runId, skill: d.skill, pr: d.pr, phase: d.phase, runtimeDir: d.runtimeDir,
  agents: {}, bubbled: [], bubbledFrom: 'none', verdict: null, startedAt: now,
})

/** Records a dispatch: the run is created on first sight, the phase follows the dispatch. */
export const applyDispatch = (
  runs: Readonly<Record<string, Run>>,
  d: Dispatch,
  rec: AgentRec,
  now: number,
): Record<string, Run> => {
  const run = runs[d.runId] ?? newRun(d, now)
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

/** The closer's DONE ends the run; its BUBBLED list becomes the run's bubbled set. */
const applyCloser = (run: Run, block: ReturnBlock): Run => {
  const closed: Run = block.signal === 'DONE' ? { ...run, phase: 'done' } : run
  return block.bubbled === null ? closed : { ...closed, bubbled: block.bubbled, bubbledFrom: 'closer' }
}

export const applyCompletion = (run: Run, agentId: string, c: Completion): Run => {
  const prev = run.agents[agentId]
  if (prev === undefined) return run
  const next: Run = { ...run, agents: { ...run.agents, [agentId]: foldAgent(prev, c) } }
  return agentId === 'closer' && c.block !== undefined ? applyCloser(next, c.block) : next
}

const withBubbled = (run: Run, ids: string[], from: 'bubble_ups' | 'review_json'): Run =>
  run.bubbledFrom === 'closer' ? run : { ...run, bubbled: ids, bubbledFrom: from }

/** pr-review's bubbled set: the review's `bubbles`, plus fixer-bubbled ids no resolution has closed. */
export const prReviewBubbled = (review: ReviewDoc | undefined, fixerBubbled: readonly string[]): string[] => {
  const closed = review?.closed ?? []
  return [...new Set([...(review?.bubbles ?? []), ...fixerBubbled.filter(id => !closed.includes(id))])]
}

/**
 * Folds what disk says: verdict, bubbled set (closer > sidecar > pr-review's review JSON and fixer
 * reports), completion. `fixerBubbled`: ids bubbled in a pr-review run's `fixes/*.json`.
 */
export const settle = (
  run: Run,
  review: ReviewDoc | undefined,
  sidecar: string[] | null,
  fixerBubbled: readonly string[] = [],
): Run => {
  const isPrReview = run.skill === 'pr-review'
  if (review === undefined && sidecar === null && !(isPrReview && fixerBubbled.length > 0)) return run
  const base: Run = review === undefined ? run : { ...run, verdict: review.verdict }
  const bubbled =
    sidecar !== null ? withBubbled(base, sidecar, 'bubble_ups')
      : isPrReview ? withBubbled(base, prReviewBubbled(review, fixerBubbled), 'review_json')
        : base
  return review !== undefined && allDispositioned(review) ? { ...bubbled, phase: 'done' } : bubbled
}

/** The phase a pr-review run's `plan.json` records wins over the dispatch-derived one; none keeps it. */
export const withDiskPhase = (run: Run, phase: Phase | undefined): Run =>
  phase === undefined || phase === run.phase ? run : { ...run, phase }

const reviewers = (run: Run): AgentRec[] => Object.values(run.agents).filter(a => a.role === 'reviewer')

export const reviewersSettled = (run: Run): boolean => reviewers(run).every(a => a.signal !== null)

export const reviewersToLog = (run: Run): AgentRec[] =>
  reviewers(run).filter(a => a.signal !== null && a.loggedAt === null)

export const markLogged = (run: Run, ids: readonly string[], now: number): Run => ({
  ...run,
  agents: Object.fromEntries(
    Object.entries(run.agents).map(([k, a]) => [k, ids.includes(k) ? { ...a, loggedAt: now } : a]),
  ),
})

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)
const str = (v: unknown): string | null => (typeof v === 'string' ? v : null)

const parseJson = (text: string): unknown => {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

/** Reviewer terminals rows by agent id. */
const terminalsByAgent = (text: string): Map<string, Record<string, unknown>> => {
  const out = new Map<string, Record<string, unknown>>()
  for (const line of text.split(/\r?\n/)) {
    const row = parseJson(line)
    if (isRecord(row) && row.agent_role === 'reviewer' && typeof row.agent_id === 'string') out.set(row.agent_id, row)
  }
  return out
}

const countsOf = (v: unknown): Counts | null => {
  if (!isRecord(v)) return null
  const n = (k: string): number => (typeof v[k] === 'number' ? (v[k] as number) : 0)
  return { findings: n('findings'), critical: n('critical'), important: n('important'), minor: n('minor') }
}

const recovered = (agent: Record<string, unknown>, row: Record<string, unknown>): AgentRec => ({
  id: String(agent.id), role: 'reviewer', model: str(agent.model), effort: str(agent.effort),
  tokens: 0, toolUses: 0, durationMs: 0, isMeasured: false,
  signal: str(row.signal) ?? 'NO_BLOCK', counts: countsOf(row.counts), loggedAt: null,
})

/** Reviewers rebuilt after a restart: plan `agents[]` that have a reviewer terminals row. */
export const recoverReviewers = (planText: string, terminalsText: string): AgentRec[] => {
  const plan = parseJson(planText)
  const agents = isRecord(plan) && Array.isArray(plan.agents) ? plan.agents.filter(isRecord) : []
  const rows = terminalsByAgent(terminalsText)
  return agents.flatMap(a => {
    const row = typeof a.id === 'string' ? rows.get(a.id) : undefined
    return row === undefined ? [] : [recovered(a, row)]
  })
}

const isPhase = (v: unknown): v is Phase => typeof v === 'string' && Object.hasOwn(PHASE_LABEL, v)

/** A pr-review `plan.json`'s `phase`; undefined when absent, unknown or the text is not JSON. */
export const planPhase = (planText: string): Phase | undefined => {
  const plan = parseJson(planText)
  return isRecord(plan) && isPhase(plan.phase) ? plan.phase : undefined
}

/** The `current` run id of a pr-review PR folder: its first line, trimmed; undefined when blank. */
export const currentRunId = (text: string | undefined): string | undefined =>
  text?.split(/\r?\n/)[0]?.trim() || undefined

/** Ids bubbled across pr-review fixer reports (`fixes/*.json` `bubbled[].id`), first-seen order. */
export const fixerBubbledIds = (reportTexts: readonly string[]): string[] => {
  const ids = reportTexts.flatMap(text => {
    const doc = parseJson(text)
    const bubbled = isRecord(doc) && Array.isArray(doc.bubbled) ? doc.bubbled : []
    return bubbled.flatMap(b => (isRecord(b) && typeof b.id === 'string' ? [b.id] : []))
  })
  return [...new Set(ids)]
}

const progress = (run: Run, role: string): string => {
  const agents = Object.values(run.agents).filter(a => a.role === role)
  return `${agents.filter(a => a.signal !== null).length}/${agents.length}`
}

const phaseLabel = (run: Run): string => {
  if (run.phase === 'review') return `reviewers ${progress(run, 'reviewer')}`
  if (run.phase === 'fix') return `fixers ${progress(run, 'fixer')}`
  return PHASE_LABEL[run.phase]
}

/** The run's phase, then the Phase 5 marker when its PR's sentinel is hot. */
const phaseText = (run: Run, isPhase5: boolean): string =>
  isPhase5 ? `${phaseLabel(run)} · Phase 5 pending` : phaseLabel(run)

const runText = (run: Run, phase5: readonly string[], missing: readonly string[]): string => {
  const parts = [`PR #${run.pr ?? '?'}`, phaseText(run, phase5.includes(String(run.pr)))]
  if (run.bubbled.length > 0) parts.push(`${run.bubbled.length} bubbled`)
  if (missing.length > 0) parts.push(`bubbles[] missing ${missing.join(',')}`)
  return parts.join(' · ')
}

export type BandInput = { run: Run | null; phase5: readonly string[]; missing: readonly string[] }

/** One band line: the active run (unless done), then any other hot sentinel; undefined when empty. */
export const bandText = (b: BandInput): string | undefined => {
  const run = b.run !== null && b.run.phase !== 'done' ? b.run : null
  const others = b.phase5
    .filter(pr => run === null || pr !== String(run.pr))
    .map(pr => `PR #${pr} · Phase 5 pending`)
  const lines = run === null ? others : [runText(run, b.phase5, b.missing), ...others]
  return lines.length === 0 ? undefined : lines.join(' | ')
}
