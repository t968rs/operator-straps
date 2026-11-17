import type { AgentRec } from '../../../types'
import { MODEL_FAMILIES, modelFamily } from '../../core/contract'
import { keyOfRunId, toRunKey, type RunKey } from './runKey'

/**
 * Rows for the project's invocation matrix (harness `matrix_path`), validated against the rules of the
 * harness plugin's `schemas/pr_review_invocation_test_matrix.schema.json`. The constants below are pinned
 * to that schema by `tests/mods/test_agent_watcher_matrix_contract.py`. Pure: no `$`.
 */

export const MATRIX_REQUIRED = [
  'cell', 'pr', 'model_family', 'effort', 'dev_commit', 'dispatch_shape', 'tokens', 'tool_uses', 'duration_s',
  'findings_count', 'C_count', 'I_count', 'M_count', 'other_count', 'verdict_prefix', 'notes',
] as const
export const MATRIX_OPTIONAL = ['phase4_script', 'legacy'] as const
export const DISPATCH_SHAPES = ['parallel', 'inline', 'workflow'] as const
export const DEV_COMMIT_PATTERN = '^[0-9a-f]{40}( -- .*)?$'

export type MatrixRow = {
  cell: string
  pr: number
  model_family: string
  effort: string
  dev_commit: string
  dispatch_shape: 'parallel' | 'workflow'
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

const UNMEASURED = 'usage not measured (no model request heard, or session restarted mid-run)'

const notesFor = (a: AgentRec): string => {
  const base = `agent-watcher auto row; ${a.role} ${a.signal ?? 'pending'}`
  return a.isMeasured ? base : `${base}; ${UNMEASURED}`
}

const whole = (n: number): number => Math.max(0, Math.round(n))

/** The family token of a model id; else the id itself, or `unknown`, which fails R4 rather than guessing. */
const familyOf = (model: string | null): string => modelFamily(model) ?? model ?? 'unknown'

export const buildRow = (i: RowInput): MatrixRow => {
  const { agent: a } = i
  const c = a.counts
  return {
    cell: `pr${i.pr}_${a.id}`, pr: i.pr, model_family: familyOf(a.model),
    effort: a.effort ?? 'default', dev_commit: i.devCommit, dispatch_shape: 'parallel',
    tokens: whole(a.tokens), tool_uses: whole(a.toolUses), duration_s: whole(a.durationMs) / 1000,
    phase4_script: null, findings_count: c?.findings ?? 0, C_count: c?.critical ?? 0, I_count: c?.important ?? 0,
    M_count: c?.minor ?? 0, other_count: 0, verdict_prefix: i.verdictPrefix, notes: notesFor(a),
  }
}

// ---------------------------------------------------------------------------
// Workflow rows: the mod cannot tie a Workflow agent's loop to its slot, and SPK-1 found no usage row for
// one, so each slot a pr-review `capture -a` Workflow call plans gets one row of zero counts, written from the
// call's args.

/** One slot an adversarial Workflow call plans: its slot id, AGENT_ROLE and model. */
export type WorkflowSlot = { id: string; role: string; model: string | null }

/** The slots of an adversarial Workflow call and the run key and run id its args name. */
export type WorkflowPlan = { runKey: RunKey; runId: string; slots: WorkflowSlot[] }

/**
 * What the mod reads of `capture -a`'s args (harness `review_adversarial.workflow_args`): the run keys, the
 * slot arrays (`WORKFLOW_GROUPS[i]` holds slots of role `WORKFLOW_ROLES[i]`, the AGENT_ROLE its prompt
 * names) and each entry's keys. `tests/mods/test_agent_watcher_adversarial_mirror.py` pins them.
 */
export const WORKFLOW_ARG_KEYS = ['run_key', 'run_id'] as const
export const WORKFLOW_GROUPS = ['reviewers', 'code', 'refute'] as const
export const WORKFLOW_ROLES = ['reviewer', 'code_refuter', 'refuter'] as const
export const WORKFLOW_SLOT_KEYS = ['id', 'model'] as const
const [RUN_KEY, RUN_ID] = WORKFLOW_ARG_KEYS
const [SLOT_ID, SLOT_MODEL] = WORKFLOW_SLOT_KEYS

export const WORKFLOW_VERDICT = 'N/A (unobserved)'
export const WORKFLOW_UNOBSERVED = 'unobserved: workflow agent'

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

/** The args object: as given, or parsed from a JSON string; undefined for anything else. */
const argsObject = (args: unknown): Record<string, unknown> | undefined => {
  if (typeof args !== 'string') return isRecord(args) ? args : undefined
  try {
    const parsed: unknown = JSON.parse(args)
    return isRecord(parsed) ? parsed : undefined
  } catch {
    return undefined
  }
}

/** The group's slots; entries without a string id are skipped. */
const groupSlots = (entries: unknown, role: string): WorkflowSlot[] =>
  (Array.isArray(entries) ? entries : []).filter(isRecord)
    .filter(e => typeof e[SLOT_ID] === 'string' && e[SLOT_ID] !== '')
    .map(e => ({ id: e[SLOT_ID] as string, role, model: typeof e[SLOT_MODEL] === 'string' ? e[SLOT_MODEL] : null }))

/** A `run_key` as text: a string as given, a number (a PR) as its digits; undefined for anything else. */
const keyText = (v: unknown): string | undefined =>
  typeof v === 'string' ? v : typeof v === 'number' ? String(v) : undefined

/** The run key of `run_key` when `run_id` is a valid run id naming that same key; else null. */
const matchedKey = (a: Record<string, unknown>): RunKey | null => {
  const runKey = toRunKey(keyText(a[RUN_KEY]))
  const runId = typeof a[RUN_ID] === 'string' ? a[RUN_ID] : ''
  return runKey !== null && keyOfRunId(runId) === runKey ? runKey : null
}

/**
 * The plan a Workflow call's args carry (`run_key`, `run_id`, `reviewers`, `code`, `refute`), or undefined
 * when they are not pr-review's adversarial args: no valid run key, a `run_id` that is not a run id of that
 * key, or no `reviewers` array.
 */
export const workflowPlan = (args: unknown): WorkflowPlan | undefined => {
  const a = argsObject(args)
  const runKey = a === undefined ? null : matchedKey(a)
  if (a === undefined || runKey === null || !Array.isArray(a[WORKFLOW_GROUPS[0]])) return undefined
  const slots = WORKFLOW_GROUPS.flatMap((key, i) => groupSlots(a[key], WORKFLOW_ROLES[i] ?? 'other'))
  return { runKey, runId: a[RUN_ID] as string, slots }
}

export type WorkflowRowInput = { pr: number; slot: WorkflowSlot; devCommit: string }

/** A Workflow slot's row: counts and duration 0, the slot's model family, notes naming it unobserved. */
export const buildWorkflowRow = (i: WorkflowRowInput): MatrixRow => ({
  cell: `pr${i.pr}_${i.slot.id}`, pr: i.pr, model_family: familyOf(i.slot.model),
  effort: 'default', dev_commit: i.devCommit, dispatch_shape: 'workflow', tokens: 0, tool_uses: 0, duration_s: 0,
  phase4_script: null, findings_count: 0, C_count: 0, I_count: 0, M_count: 0, other_count: 0,
  verdict_prefix: WORKFLOW_VERDICT, notes: `agent-watcher auto row; ${i.slot.role}; ${WORKFLOW_UNOBSERVED}`,
})

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
