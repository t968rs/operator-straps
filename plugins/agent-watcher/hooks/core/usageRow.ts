import type { AgentRec, Skill } from '../../types'
import { holdsPath, modelFamily, typeName, type Dispatch, type Header, type ReturnBlock } from './contract'

/**
 * Rows for the project's agent usage log (harness `agent_usage_path`), validated against the rules of the
 * harness plugin's `schemas/agent_usage.schema.json`, and the row identity of a dispatch no layer claims. The
 * constants below are pinned to that schema by `tests/mods/test_agent_watcher_usage_contract.py`. Pure: no `$`.
 */

export const USAGE_REQUIRED = [
  'logged_at', 'run_id', 'pr', 'skill', 'role', 'agent_id', 'subagent_type', 'model', 'model_family', 'effort',
  'tokens', 'tool_uses', 'duration_s', 'signal', 'notes',
] as const
export const USAGE_COUNT_FIELDS = ['issues_assigned', 'issues_fixed', 'issues_bubbled', 'files_touched'] as const
/** `context_tokens` and `requests` are optional only because older rows lack them; every new row carries both. */
export const USAGE_OPTIONAL = ['fields', 'context_tokens', 'requests'] as const
export const USAGE_COUNTED_ROLES = ['fixer', 'closer'] as const
export const USAGE_MODEL_FAMILIES = ['haiku', 'sonnet', 'opus', 'unknown'] as const
export const LOGGED_AT_PATTERN = '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?Z$'
export const SKILL_PATTERN = '^[a-z][a-z0-9-]*$'
export const ROLE_PATTERN = '^[a-z][a-z0-9_-]*$'
export const FIELD_KEY_PATTERN = '^[A-Z][A-Z_]*$'
export const FIELD_VALUE_PATTERN = '^[^/\\\\]*$'
export const FIELD_VALUE_MAX = 200
/** Columns that never hold a path separator (Decision D8 beyond `fields`); `signal` is also capped. */
export const PATH_FREE_COLUMNS = ['run_id', 'agent_id', 'signal', 'notes'] as const
/** The signal logged in place of a SIGNAL value that holds a path separator. */
export const PATH_SIGNAL = 'UNRECOGNIZED'

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
  /** An unclaimed dispatch's header fields (`logFields`); a claimed row passes none. */
  fields?: Readonly<Record<string, string>>
}

/** Header keys and values of a row, as the log holds them. */
export type RowFields = Readonly<Record<string, string>>

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
  context_tokens: number | null
  requests: number | null
  tool_uses: number
  duration_s: number
  signal: string
  notes: string
  fields?: RowFields
} & Partial<FixerCounts>

const isCountedRole = (role: unknown): boolean => (USAGE_COUNTED_ROLES as readonly unknown[]).includes(role)
const whole = (n: number): number => Math.max(0, Math.round(n))

// ---------------------------------------------------------------------------
// Header fields and the unclaimed identity (Decisions D8, D11)

const SKILL = new RegExp(SKILL_PATTERN)
const ROLE = new RegExp(ROLE_PATTERN)
const FIELD_KEY = new RegExp(FIELD_KEY_PATTERN)
const FIELD_VALUE = new RegExp(FIELD_VALUE_PATTERN)
/** Header keys an unclaimed dispatch's identity reads. */
const CONSUMED = new Set(['SKILL', 'RUN_ID', 'AGENT_ROLE', 'AGENT_ID', 'PR'])

/** Length in code points, as the schema's `maxLength` counts. */
const lengthOf = (value: string): number => Array.from(value).length

/** A value cut to FIELD_VALUE_MAX code points: the first 197 and `...`. */
export const capValue = (value: string): string =>
  lengthOf(value) <= FIELD_VALUE_MAX ? value : `${Array.from(value).slice(0, FIELD_VALUE_MAX - 3).join('')}...`

/**
 * The fields a row may log (Decision D8): a value holding a path separator is dropped with its key, every
 * other value is capped; undefined when none survive.
 */
export const logFields = (raw: Header): RowFields | undefined => {
  const kept = Object.entries(raw).filter(([, v]) => !holdsPath(v))
  return kept.length === 0 ? undefined : Object.fromEntries(kept.map(([k, v]) => [k, capValue(v)]))
}

/** The header SKILL with a leading `<plugin>:` stripped, when it matches SKILL_PATTERN. */
const skillOf = (raw: string | undefined): string | undefined => {
  const name = raw?.replace(/^[^:\s]+:/, '')
  return name !== undefined && SKILL.test(name) ? name : undefined
}

/** AGENT_ROLE when it matches ROLE_PATTERN and is not `fixer` or `closer` (their counts need a layer). */
const roleOf = (raw: string | undefined): string | undefined =>
  raw !== undefined && ROLE.test(raw) && !isCountedRole(raw) ? raw : undefined

/** A RUN_ID or AGENT_ID value for its column: non-empty and free of path separators. */
const idOf = (raw: string | undefined): string | undefined =>
  raw !== undefined && raw !== '' && !holdsPath(raw) ? raw : undefined

/** PR when it is a positive integer a JSON number holds exactly; else undefined (the row falls back). */
const prOf = (raw: string | undefined): number | undefined => {
  const n = /^[1-9][0-9]*$/.test(raw ?? '') ? Number(raw) : NaN
  return Number.isSafeInteger(n) ? n : undefined
}

/** The leading-block keys a row keeps: every key not consumed, and each consumed key whose value fell back. */
const leftoverOf = (h: Header, fellBack: ReadonlySet<string>): Header =>
  Object.fromEntries(Object.entries(h).filter(([k]) => !CONSUMED.has(k) || fellBack.has(k)))

/**
 * A dispatch no layer claims (Decision D11), under its generated state key `runId`: skill, role, run id,
 * agent id and PR from the leading header block, each falling back (`standalone`, `other`, `runId`, the
 * type's name, null) instead of failing the row; a raw value that fell back stays in `fields` under D8.
 */
export const unclaimedDispatch = (subagentType: string | undefined, h: Header, runId: string): Dispatch => {
  const picked = {
    SKILL: skillOf(h.SKILL), AGENT_ROLE: roleOf(h.AGENT_ROLE), RUN_ID: idOf(h.RUN_ID), AGENT_ID: idOf(h.AGENT_ID),
    PR: prOf(h.PR),
  }
  const fellBack = new Set(Object.entries(picked).filter(([k, v]) => v === undefined && k in h).map(([k]) => k))
  const fields = logFields(leftoverOf(h, fellBack))
  return {
    runId, skill: picked.SKILL ?? 'standalone', agentId: picked.AGENT_ID ?? typeName(subagentType),
    role: picked.AGENT_ROLE ?? 'other', pr: picked.PR ?? null, runtimeDir: null, phase: 'done',
    ...(picked.RUN_ID === undefined ? {} : { logRunId: picked.RUN_ID }),
    ...(fields === undefined ? {} : { fields }),
  }
}

const notesFor = (role: string, signal: string, i: UsageInput): string => {
  const base = `agent-watcher auto row; ${role} ${signal}`
  if (i.ending === 'errored') return `${base}; usage not measured; agent errored`
  return i.isMeasured ? base : `${base}; usage not measured`
}

/** An agent's SIGNAL as the log holds it: PATH_SIGNAL when it holds a path separator, else capped. */
export const signalOf = (raw: string): string => holdsPath(raw) ? PATH_SIGNAL : capValue(raw)

export const buildUsageRow = (i: UsageInput): UsageRow => {
  const a = i.agent
  const signal = i.ending === 'errored' ? 'ERROR' : signalOf(a.signal ?? 'NO_BLOCK')
  const row: UsageRow = {
    logged_at: new Date(i.loggedAt).toISOString(), run_id: i.runId, pr: i.pr, skill: i.skill, role: a.role,
    agent_id: a.id, subagent_type: a.subagentType, model: a.model, model_family: modelFamily(a.model) ?? 'unknown',
    effort: a.effort ?? 'default', tokens: whole(a.tokens),
    context_tokens: a.contextTokens === undefined ? null : whole(a.contextTokens),
    requests: a.requests === undefined ? null : whole(a.requests), tool_uses: whole(a.toolUses),
    duration_s: whole(a.durationMs) / 1000, signal, notes: notesFor(a.role, signal, i),
  }
  const fields = i.fields === undefined ? undefined : logFields(i.fields)
  const withFields = fields === undefined ? row : { ...row, fields }
  return isCountedRole(a.role) ? { ...withFields, ...i.counts } : withFields
}

// ---------------------------------------------------------------------------
// Validation

type Row = Readonly<Record<string, unknown>>

const ALLOWED = new Set<string>([...USAGE_REQUIRED, ...USAGE_COUNT_FIELDS, ...USAGE_OPTIONAL])
const LOGGED_AT = new RegExp(LOGGED_AT_PATTERN)
export const NON_EMPTY = ['run_id', 'agent_id', 'effort', 'signal'] as const
const STRINGS = ['logged_at', 'skill', 'role', 'model_family', 'notes', ...NON_EMPTY] as const
export const NULLABLE_STRINGS = ['subagent_type', 'model'] as const
const ENUMS: readonly [string, readonly string[]][] = [['model_family', USAGE_MODEL_FAMILIES]]
const PATTERNS: readonly [string, RegExp][] = [['skill', SKILL], ['role', ROLE], ['logged_at', LOGGED_AT]]

const isCount = (v: unknown): boolean => Number.isInteger(v) && (v as number) >= 0

/** `fields`, when present: an object of FIELD_KEY_PATTERN keys and capped, path-free string values. */
const fieldsProblems = (row: Row): string[] => {
  if (!('fields' in row)) return []
  const f = row.fields
  if (typeof f !== 'object' || f === null || Array.isArray(f)) return ['fields: not an object']
  return Object.entries(f as Record<string, unknown>).flatMap(([k, v]) => [
    ...(FIELD_KEY.test(k) ? [] : [`fields.${k}: key not uppercase`]),
    ...(typeof v !== 'string' ? [`fields.${k}: not a string`]
      : lengthOf(v) > FIELD_VALUE_MAX ? [`fields.${k}: over ${FIELD_VALUE_MAX} characters`]
        : FIELD_VALUE.test(v) ? [] : [`fields.${k}: holds a path separator`]),
  ])
}

/** Type checks on the string fields that are present. */
const stringProblems = (row: Row): string[] => [
  ...STRINGS.filter(k => k in row && typeof row[k] !== 'string').map(k => `${k}: not a string`),
  ...NON_EMPTY.filter(k => row[k] === '').map(k => `${k}: empty`),
  ...NULLABLE_STRINGS.filter(k => k in row && row[k] !== null && typeof row[k] !== 'string')
    .map(k => `${k}: not a string or null`),
]

/** PATH_FREE_COLUMNS hold no path separator; `signal` is at most FIELD_VALUE_MAX code points. */
const pathProblems = (row: Row): string[] => [
  ...PATH_FREE_COLUMNS.filter(k => typeof row[k] === 'string' && !FIELD_VALUE.test(row[k] as string))
    .map(k => `${k}: holds a path separator`),
  ...(typeof row.signal === 'string' && lengthOf(row.signal) > FIELD_VALUE_MAX
    ? [`signal: over ${FIELD_VALUE_MAX} characters`] : []),
]

/** Enum and pattern checks on string fields that are present. */
const valueProblems = (row: Row): string[] => [
  ...ENUMS.flatMap(([k, options]) =>
    typeof row[k] === 'string' && !options.includes(row[k] as string)
      ? [`${k}: '${String(row[k])}' is not one of ${options.join('/')}`] : []),
  ...PATTERNS.flatMap(([k, pattern]) =>
    typeof row[k] === 'string' && !pattern.test(row[k] as string)
      ? [`${k}: '${String(row[k])}' does not match ${pattern.source}`] : []),
]

/** Range checks on the numeric fields that are present. */
const numberProblems = (row: Row): string[] => {
  const out = (['tokens', 'tool_uses'] as const).filter(k => k in row && !isCount(row[k]))
    .map(k => `${k}: not a non-negative integer`)
  const ctx = row.context_tokens
  if ('context_tokens' in row && ctx !== null && !isCount(ctx)) out.push('context_tokens: not a non-negative integer or null')
  const req = row.requests
  if ('requests' in row && req !== null && !(isCount(req) && (req as number) >= 1)) {
    out.push('requests: not a positive integer or null')
  }
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
  ...pathProblems(row),
  ...numberProblems(row),
  ...countProblems(row),
  ...fieldsProblems(row),
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

/** `primary`, with each null field taken from `fallback`. */
export const preferCounts = (primary: FixerCounts, fallback: FixerCounts): FixerCounts => ({
  issues_assigned: primary.issues_assigned ?? fallback.issues_assigned,
  issues_fixed: primary.issues_fixed ?? fallback.issues_fixed,
  issues_bubbled: primary.issues_bubbled ?? fallback.issues_bubbled,
  files_touched: primary.files_touched ?? fallback.files_touched,
})
