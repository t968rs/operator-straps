import type { AgentRec } from '../types'
import { MODEL_FAMILIES, modelFamily } from './contract'

/**
 * Rows for the project's invocation matrix (harness `matrix_path`), validated against the rules of the
 * harness plugin's `schemas/pr_review_invocation_test_matrix.schema.json`. The constants below are pinned
 * to that schema by `tests/mods/test_pr_review_watch_matrix_contract.py`. Pure: no `$`.
 */

export const MATRIX_REQUIRED = [
  'cell', 'pr', 'model_family', 'effort', 'dev_commit', 'dispatch_shape', 'tokens', 'tool_uses', 'duration_s',
  'findings_count', 'C_count', 'I_count', 'M_count', 'other_count', 'verdict_prefix', 'notes',
] as const
export const MATRIX_OPTIONAL = ['phase4_script', 'legacy'] as const
export const DISPATCH_SHAPES = ['parallel', 'inline'] as const
export const DEV_COMMIT_PATTERN = '^[0-9a-f]{40}( -- .*)?$'

export type MatrixRow = {
  cell: string
  pr: number
  model_family: string
  effort: string
  dev_commit: string
  dispatch_shape: 'parallel'
  tokens: number
  tool_uses: number
  duration_s: number
  phase4_script: null
  findings_count: number
  C_count: number
  I_count: number
  M_count: number
  other_count: number
  verdict_prefix: string
  notes: string
}

export type RowInput = { pr: number; agent: AgentRec; verdictPrefix: string; devCommit: string }

const STRING_FIELDS = [
  'cell', 'model_family', 'effort', 'dev_commit', 'dispatch_shape', 'verdict_prefix', 'notes',
] as const
const COUNT_FIELDS = [
  'tokens', 'tool_uses', 'findings_count', 'C_count', 'I_count', 'M_count', 'other_count',
] as const
const ALLOWED = new Set<string>([...MATRIX_REQUIRED, ...MATRIX_OPTIONAL])
const DEV_COMMIT = new RegExp(DEV_COMMIT_PATTERN)

const notesFor = (a: AgentRec): string => {
  const base = `pr-review-watch auto row; ${a.role} ${a.signal ?? 'pending'}`
  return a.isMeasured ? base : `${base}; usage not measured (session restarted mid-run)`
}

const whole = (n: number): number => Math.max(0, Math.round(n))

export const buildRow = (i: RowInput): MatrixRow => {
  const { agent: a } = i
  const c = a.counts
  return {
    cell: `pr${i.pr}_${a.id}`, pr: i.pr, model_family: modelFamily(a.model) ?? a.model ?? 'unknown',
    effort: a.effort ?? 'default', dev_commit: i.devCommit, dispatch_shape: 'parallel',
    tokens: whole(a.tokens), tool_uses: whole(a.toolUses), duration_s: whole(a.durationMs) / 1000,
    phase4_script: null, findings_count: c?.findings ?? 0, C_count: c?.critical ?? 0, I_count: c?.important ?? 0,
    M_count: c?.minor ?? 0, other_count: 0, verdict_prefix: i.verdictPrefix, notes: notesFor(a),
  }
}

const isCount = (v: unknown): boolean => Number.isInteger(v) && (v as number) >= 0
const isOneOf = (v: string, options: readonly string[]): boolean => options.includes(v)

/** Range checks on numeric fields that are present. */
const numberProblems = (row: Readonly<Record<string, unknown>>): string[] => {
  const out: string[] = []
  if ('pr' in row && !(Number.isInteger(row.pr) && (row.pr as number) >= 1)) out.push('pr: not a positive integer')
  const d = row.duration_s
  const isDuration = typeof d === 'number' && Number.isFinite(d) && d >= 0
  if ('duration_s' in row && !isDuration) out.push('duration_s: not a non-negative number')
  return out
}

/** Enum, pattern and optional-field checks on fields that are present with the right primitive type. */
const valueProblems = (row: Readonly<Record<string, unknown>>): string[] => {
  const out = numberProblems(row)
  const m = row.model_family
  if (typeof m === 'string' && !isOneOf(m, MODEL_FAMILIES)) {
    out.push(`model_family: '${m}' is not one of ${MODEL_FAMILIES.join('/')}`)
  }
  const s = row.dispatch_shape
  if (typeof s === 'string' && !isOneOf(s, DISPATCH_SHAPES)) {
    out.push(`dispatch_shape: '${s}' is not one of ${DISPATCH_SHAPES.join('/')}`)
  }
  if (row.legacy !== true && typeof row.dev_commit === 'string' && !DEV_COMMIT.test(row.dev_commit)) {
    out.push('dev_commit: does not start with a 40-char merge-base SHA')
  }
  const p4 = row.phase4_script
  if ('phase4_script' in row && p4 !== null && typeof p4 !== 'string') out.push('phase4_script: not a string or null')
  if ('legacy' in row && typeof row.legacy !== 'boolean') out.push('legacy: not a boolean')
  return out
}

/** Every way the row breaks the schema; empty when it validates. */
export const validateRow = (row: Readonly<Record<string, unknown>>): string[] => [
  ...Object.keys(row).filter(k => !ALLOWED.has(k)).map(k => `${k}: not in the schema`),
  ...MATRIX_REQUIRED.filter(k => !(k in row)).map(k => `${k}: missing`),
  ...STRING_FIELDS.filter(k => k in row && typeof row[k] !== 'string').map(k => `${k}: not a string`),
  ...COUNT_FIELDS.filter(k => k in row && !isCount(row[k])).map(k => `${k}: not a non-negative integer`),
  ...valueProblems(row),
]

/** The JSONL text with rows appended, one compact object per line. */
export const appendRows = (existing: string, rows: readonly object[]): string => {
  if (rows.length === 0) return existing
  const head = existing === '' || existing.endsWith('\n') ? existing : `${existing}\n`
  return head + rows.map(r => `${JSON.stringify(r)}\n`).join('')
}
