import type { AgentRec, Skill } from '../types'
import { modelFamily, type ReturnBlock } from './contract'

/**
 * Rows for the project's agent usage log (harness `agent_usage_path`), validated against the rules of the
 * harness plugin's `schemas/pr_review_agent_usage.schema.json`. The constants below are pinned to that
 * schema by `tests/mods/test_pr_review_watch_usage_contract.py`. Pure: no `$`.
 */

export const USAGE_REQUIRED = [
  'logged_at', 'run_id', 'pr', 'skill', 'role', 'agent_id', 'subagent_type', 'model', 'model_family', 'effort',
  'tokens', 'tool_uses', 'duration_s', 'signal', 'notes',
] as const
export const USAGE_COUNT_FIELDS = ['issues_assigned', 'issues_fixed', 'issues_bubbled', 'files_touched'] as const
export const USAGE_ROLES = ['reviewer', 'fixer', 'orchestrator', 'planner', 'closer', 'other'] as const
export const USAGE_COUNTED_ROLES = ['fixer', 'closer'] as const
export const USAGE_SKILLS = ['pr-review', 'pr-team', 'standalone'] as const
export const USAGE_MODEL_FAMILIES = ['haiku', 'sonnet', 'opus', 'unknown'] as const
export const LOGGED_AT_PATTERN = '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?Z$'

/** Fixer outcome counts; null means unknown, never zero. */
export type FixerCounts = {
  issues_assigned: number | null
  issues_fixed: number | null
  issues_bubbled: number | null
  files_touched: number | null
}
export const NO_COUNTS: FixerCounts = {
  issues_assigned: null, issues_fixed: null, issues_bubbled: null, files_touched: null,
}

/** How the dispatch ended: a result the engine reported, or an errored Agent result. */
export type Ending = 'ok' | 'errored'

export type UsageInput = {
  runId: string
  skill: Skill
  pr: number | null
  agent: AgentRec
  ending: Ending
  isMeasured: boolean
  loggedAt: number
  counts: FixerCounts
}

export type UsageRow = {
  logged_at: string
  run_id: string
  pr: number | null
  skill: Skill
  role: string
  agent_id: string
  subagent_type: string | null
  model: string | null
  model_family: string
  effort: string
  tokens: number
  tool_uses: number
  duration_s: number
  signal: string
  notes: string
} & Partial<FixerCounts>

const isCountedRole = (role: unknown): boolean => (USAGE_COUNTED_ROLES as readonly unknown[]).includes(role)
const whole = (n: number): number => Math.max(0, Math.round(n))

const notesFor = (role: string, signal: string, i: UsageInput): string => {
  const base = `pr-review-watch auto row; ${role} ${signal}`
  if (i.ending === 'errored') return `${base}; usage not measured; agent errored`
  return i.isMeasured ? base : `${base}; usage not measured`
}

export const buildUsageRow = (i: UsageInput): UsageRow => {
  const a = i.agent
  const signal = i.ending === 'errored' ? 'ERROR' : (a.signal ?? 'NO_BLOCK')
  const row: UsageRow = {
    logged_at: new Date(i.loggedAt).toISOString(), run_id: i.runId, pr: i.pr, skill: i.skill, role: a.role,
    agent_id: a.id, subagent_type: a.subagentType, model: a.model, model_family: modelFamily(a.model) ?? 'unknown',
    effort: a.effort ?? 'default', tokens: whole(a.tokens), tool_uses: whole(a.toolUses),
    duration_s: whole(a.durationMs) / 1000, signal, notes: notesFor(a.role, signal, i),
  }
  return isCountedRole(a.role) ? { ...row, ...i.counts } : row
}

// ---------------------------------------------------------------------------
// Validation

type Row = Readonly<Record<string, unknown>>

const ALLOWED = new Set<string>([...USAGE_REQUIRED, ...USAGE_COUNT_FIELDS])
const LOGGED_AT = new RegExp(LOGGED_AT_PATTERN)
export const NON_EMPTY = ['run_id', 'agent_id', 'effort', 'signal'] as const
const STRINGS = ['logged_at', 'skill', 'role', 'model_family', 'notes', ...NON_EMPTY] as const
export const NULLABLE_STRINGS = ['subagent_type', 'model'] as const
const ENUMS: readonly [string, readonly string[]][] = [
  ['skill', USAGE_SKILLS], ['role', USAGE_ROLES], ['model_family', USAGE_MODEL_FAMILIES],
]

const isCount = (v: unknown): boolean => Number.isInteger(v) && (v as number) >= 0

/** Type checks on the string fields that are present. */
const stringProblems = (row: Row): string[] => [
  ...STRINGS.filter(k => k in row && typeof row[k] !== 'string').map(k => `${k}: not a string`),
  ...NON_EMPTY.filter(k => row[k] === '').map(k => `${k}: empty`),
  ...NULLABLE_STRINGS.filter(k => k in row && row[k] !== null && typeof row[k] !== 'string')
    .map(k => `${k}: not a string or null`),
]

/** Enum and pattern checks on string fields that are present. */
const valueProblems = (row: Row): string[] => {
  const out = ENUMS.flatMap(([k, options]) =>
    typeof row[k] === 'string' && !options.includes(row[k] as string)
      ? [`${k}: '${String(row[k])}' is not one of ${options.join('/')}`] : [])
  if (typeof row.logged_at === 'string' && !LOGGED_AT.test(row.logged_at)) out.push('logged_at: not an ISO UTC time')
  return out
}

/** Range checks on the numeric fields that are present. */
const numberProblems = (row: Row): string[] => {
  const out = (['tokens', 'tool_uses'] as const).filter(k => k in row && !isCount(row[k]))
    .map(k => `${k}: not a non-negative integer`)
  const pr = row.pr
  const isPr = Number.isInteger(pr) && (pr as number) >= 1
  if ('pr' in row && pr !== null && !isPr) out.push('pr: not a positive integer or null')
  const d = row.duration_s
  if ('duration_s' in row && !(typeof d === 'number' && Number.isFinite(d) && d >= 0)) {
    out.push('duration_s: not a non-negative number')
  }
  return out
}

/** Count fields: required (count or null) on fixer and closer rows, absent on every other role. */
const countProblems = (row: Row): string[] => {
  if (!isCountedRole(row.role)) {
    return USAGE_COUNT_FIELDS.filter(k => k in row).map(k => `${k}: only on fixer and closer rows`)
  }
  return USAGE_COUNT_FIELDS.flatMap(k =>
    !(k in row) ? [`${k}: missing`] : row[k] !== null && !isCount(row[k]) ? [`${k}: not a count or null`] : [])
}

/** Every way the row breaks the schema; empty when it validates. */
export const validateUsageRow = (row: Row): string[] => [
  ...Object.keys(row).filter(k => !ALLOWED.has(k)).map(k => `${k}: not in the schema`),
  ...USAGE_REQUIRED.filter(k => !(k in row)).map(k => `${k}: missing`),
  ...stringProblems(row),
  ...valueProblems(row),
  ...numberProblems(row),
  ...countProblems(row),
]

// ---------------------------------------------------------------------------
// Fixer counts

/** Counts from a fixer or closer return block; `issues_assigned` is never in a block. */
export const blockCounts = (b: ReturnBlock | undefined): FixerCounts => ({
  issues_assigned: null,
  issues_fixed: b?.fixed?.length ?? null,
  issues_bubbled: b?.bubbled?.length ?? null,
  files_touched: b?.edited ?? null,
})

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const parseJson = (text: string | undefined): unknown => {
  if (text === undefined) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

/** The length of a fixer's `issue_ids` in a pr-review `waves.json`; null when absent or malformed. */
const assignedIn = (wavesText: string | undefined, agentId: string): number | null => {
  const doc = parseJson(wavesText)
  const waves = isRecord(doc) && Array.isArray(doc.waves) ? doc.waves : []
  const fixer = waves.flatMap(w => (Array.isArray(w) ? w : [])).find(f => isRecord(f) && f.id === agentId)
  return isRecord(fixer) && Array.isArray(fixer.issue_ids) ? fixer.issue_ids.length : null
}

/** Distinct `files` across a report's `fixed` entries. */
const editedFiles = (fixed: readonly unknown[]): number =>
  new Set(fixed.flatMap(e => (isRecord(e) && Array.isArray(e.files) ? e.files : []))).size

/** Counts from a pr-review fixer's `waves.json` entry and its `fixes/<agentId>.json` report. */
export const reportCounts = (
  wavesText: string | undefined,
  reportText: string | undefined,
  agentId: string,
): FixerCounts => {
  const report = parseJson(reportText)
  const fixed = isRecord(report) && Array.isArray(report.fixed) ? report.fixed : null
  const bubbled = isRecord(report) && Array.isArray(report.bubbled) ? report.bubbled : null
  return {
    issues_assigned: assignedIn(wavesText, agentId),
    issues_fixed: fixed?.length ?? null,
    issues_bubbled: bubbled?.length ?? null,
    files_touched: fixed === null ? null : editedFiles(fixed),
  }
}

/** `primary`, with each null field taken from `fallback`. */
export const preferCounts = (primary: FixerCounts, fallback: FixerCounts): FixerCounts => ({
  issues_assigned: primary.issues_assigned ?? fallback.issues_assigned,
  issues_fixed: primary.issues_fixed ?? fallback.issues_fixed,
  issues_bubbled: primary.issues_bubbled ?? fallback.issues_bubbled,
  files_touched: primary.files_touched ?? fallback.files_touched,
})
