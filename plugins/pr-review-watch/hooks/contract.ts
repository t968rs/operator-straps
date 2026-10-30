import type { Counts, Phase, Skill } from '../types'

/**
 * Parsers for pr-team / pr-review `Agent` prompts and return-contract blocks (the harness pr-team skill's
 * `return_contract.md` and `canonical_prompt_template.md`). Pure: no `$`.
 */

/** Header fields of an `Agent` prompt: `KEY=value` and `KEY: value` lines at column 1. */
export type Header = Readonly<Record<string, string>>

/** Who a tracked `Agent` dispatch is. */
export type Dispatch = {
  runId: string
  skill: Skill
  agentId: string
  role: string
  pr: number | null
  runtimeDir: string | null
  phase: Phase
}

/**
 * A parsed return-contract block; `fixed` / `bubbled` are null when the block has no `FIXED:` / `BUBBLED:`
 * line, `edited` when `EDITED:` is absent or not a count.
 */
export type ReturnBlock = {
  signal: string
  role: string | null
  counts: Counts | null
  fixed: string[] | null
  bubbled: string[] | null
  edited: number | null
  output: string | null
  notes: string | null
}

export const MODEL_FAMILIES = ['haiku', 'sonnet', 'opus'] as const
export type ModelFamily = (typeof MODEL_FAMILIES)[number]

const HEADER_LINE = /^([A-Z][A-Z_]*)(?:=|: )(.*)$/
const BLOCK_LINE = /^([A-Z][A-Z_]*):(?: (.*))?$/
const COUNTS_VALUE = /^findings=(\d+) critical=(\d+) important=(\d+) minor=(\d+)$/
const ISSUE_ID = /^[CIM]\d+$/
const RUN_ID_PR = /^pr(\d{1,7})_\d{8}T\d{6}Z$/
const RUN_ID_STAMP = /^pr\d{1,7}_(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/

/** Phase, agent id and role per pr-team agent family and MODE. */
const MODES: Readonly<Record<string, Readonly<Record<string, readonly [Phase, string, string]>>>> = {
  orchestrator: {
    PLAN: ['plan', 'orchestrator_plan', 'orchestrator'],
    CONSOLIDATE: ['consolidate', 'orchestrator_consolidate', 'orchestrator'],
  },
  fixer: { PLAN: ['fix-plan', 'fixer_plan', 'planner'], CLOSEOUT: ['closeout', 'closer', 'closer'] },
}

/** Key/value lines matching `pattern`; the first occurrence of a key wins. */
const fieldsOf = (lines: readonly string[], pattern: RegExp): Record<string, string> => {
  const out: Record<string, string> = {}
  for (const line of lines) {
    const m = line.trimEnd().match(pattern)
    const key = m?.[1]
    if (key !== undefined && !(key in out)) out[key] = (m?.[2] ?? '').trim()
  }
  return out
}

export const parseHeader = (prompt: string): Header => fieldsOf(prompt.split(/\r?\n/), HEADER_LINE)

/** A positive integer PR number, or null. */
export const toPr = (raw: string | undefined): number | null =>
  raw !== undefined && /^\d+$/.test(raw) && Number(raw) >= 1 ? Number(raw) : null

/** The PR a run id names (`pr1122_20260518T060416Z`), or null. */
export const prOfRunId = (runId: string): number | null => toPr(runId.match(RUN_ID_PR)?.[1])

/** Epoch ms of the UTC stamp a run id carries (`pr1122_20260518T060416Z`), or null when absent or invalid. */
export const startedAtOfRunId = (runId: string): number | null => {
  const m = runId.match(RUN_ID_STAMP)
  if (m === null) return null
  const [y, mo, d, h, mi, s] = m.slice(1).map(Number) as [number, number, number, number, number, number]
  const ms = Date.UTC(y, mo - 1, d, h, mi, s)
  const back = new Date(ms)
  return back.getUTCMonth() === mo - 1 && back.getUTCDate() === d && h < 24 && mi < 60 && s < 60 ? ms : null
}

/** The agent family a pr-team subagent type names, or undefined. */
const familyOf = (subagentType: string): string | undefined =>
  /orchestrator/.test(subagentType) ? 'orchestrator' : /fixer/.test(subagentType) ? 'fixer' : undefined

/** A pr-team `MODE=` dispatch to the orchestrator or fixer agent. */
const modeDispatch = (subagentType: string, h: Header, runId: string): Dispatch | undefined => {
  const family = familyOf(subagentType)
  const hit = family === undefined ? undefined : MODES[family]?.[h.MODE ?? '']
  if (hit === undefined) return undefined
  const [phase, agentId, role] = hit
  const pr = toPr(h.PR_NUMBER) ?? prOfRunId(runId)
  return { runId, skill: 'pr-team', agentId, role, pr, runtimeDir: h.RUNTIME_DIR ?? null, phase }
}

/** The runtime dir an OUTPUT_FILE slot sits in, else `<runtimeBase>/<runId>`. */
const runtimeDirOf = (h: Header, runId: string, runtimeBase: string): string => {
  const m = (h.OUTPUT_FILE ?? '').match(/^(.*)[\\/]outputs[\\/][^\\/]+$/)
  return m?.[1] ?? `${runtimeBase}/${runId}`
}

/** A slot dispatch (`AGENT_ID:` / `AGENT_ROLE:`): pr-review when a `PR:` line is present. */
const slotDispatch = (h: Header, runId: string, runtimeBase: string): Dispatch | undefined => {
  const { AGENT_ID: agentId, AGENT_ROLE: role } = h
  if (!agentId || (role !== 'reviewer' && role !== 'fixer')) return undefined
  const isReview = h.PR !== undefined
  const pr = (isReview ? toPr(h.PR) : null) ?? prOfRunId(runId)
  const skill: Skill = isReview ? 'pr-review' : 'pr-team'
  const runtimeDir = isReview ? null : runtimeDirOf(h, runId, runtimeBase)
  return { runId, skill, agentId, role, pr, runtimeDir, phase: role === 'reviewer' ? 'review' : 'fix' }
}

/**
 * Every agent the marketplace defines, as Claude Code names the type: `<plugin>:<file stem>` for each file in a
 * plugin's `agents` folder. `tests/mods/test_pr_review_watch_usage_contract.py` pins the list to those files.
 */
export const DEFINED_AGENTS = [
  'harness:bubble-memo-investigator', 'harness:bubble-memo-reviewer', 'harness:messenger', 'harness:pr-fixer',
  'harness:pr-reviewer', 'harness:pr-team-fixer', 'harness:pr-team-orchestrator', 'harness:roast-my-code',
  'harness:strap-judge', 'harness:strap-scenario-runner', 'harness:todo-editor',
] as const

export const isDefinedAgent = (subagentType: string | undefined): boolean =>
  (DEFINED_AGENTS as readonly (string | undefined)[]).includes(subagentType)

/** `standalone_<UTC yyyymmddTHHMMSSZ>_<seq>`: one run per dispatch; `seq` tells same-second dispatches apart. */
export const standaloneRunId = (now: number, seq: number): string =>
  `standalone_${new Date(now).toISOString().replace(/\.\d+Z$/, 'Z').replace(/[-:]/g, '')}_${seq}`

/**
 * A defined agent dispatched outside any run header: its own run, its agent id the type's name after the
 * plugin prefix, role `other`. Undefined for any other agent type.
 */
export const identifyStandalone = (subagentType: string | undefined, runId: string): Dispatch | undefined =>
  subagentType === undefined || !isDefinedAgent(subagentType)
    ? undefined
    : {
      runId, skill: 'standalone', agentId: subagentType.slice(subagentType.indexOf(':') + 1), role: 'other', pr: null,
      runtimeDir: null, phase: 'done',
    }

/**
 * The tracked identity of an `Agent` call, or undefined for any other dispatch. `runtimeBase` is the
 * project's pr-team runtime folder, used when a pr-team slot names no OUTPUT_FILE.
 */
export const identify = (
  subagentType: string | undefined,
  prompt: string,
  runtimeBase: string,
): Dispatch | undefined => {
  const h = parseHeader(prompt)
  const runId = h.RUN_ID
  if (runId === undefined || runId === '') return undefined
  return h.MODE !== undefined ? modeDispatch(subagentType ?? '', h, runId) : slotDispatch(h, runId, runtimeBase)
}

/** Comma-separated issue ids; malformed entries dropped. */
export const idList = (raw: string): string[] =>
  raw.split(',').map(s => s.trim()).filter(s => ISSUE_ID.test(s))

/** A COUNTS value, or null when absent or malformed. */
export const parseCounts = (raw: string | undefined): Counts | null => {
  const m = raw?.match(COUNTS_VALUE)
  if (!m) return null
  return { findings: Number(m[1]), critical: Number(m[2]), important: Number(m[3]), minor: Number(m[4]) }
}

/** Indexes of column-1 `---` fence lines. */
const fences = (lines: readonly string[]): number[] => lines.flatMap((l, i) => (l.trimEnd() === '---' ? [i] : []))

const toBlock = (f: Readonly<Record<string, string>>): ReturnBlock => ({
  signal: f.SIGNAL ?? '',
  role: f.AGENT_ROLE ?? null,
  counts: parseCounts(f.COUNTS),
  fixed: f.FIXED === undefined ? null : idList(f.FIXED),
  bubbled: f.BUBBLED === undefined ? null : idList(f.BUBBLED),
  edited: /^\d+$/.test(f.EDITED ?? '') ? Number(f.EDITED) : null,
  output: f.OUTPUT ?? null,
  notes: f.NOTES ?? null,
})

/** The last fenced block that carries a SIGNAL line; undefined when there is none. */
export const parseReturnBlock = (text: string): ReturnBlock | undefined => {
  const lines = text.split(/\r?\n/)
  const at = fences(lines)
  for (let i = at.length - 1; i >= 1; i--) {
    const f = fieldsOf(lines.slice((at[i - 1] ?? 0) + 1, at[i]), BLOCK_LINE)
    if (f.SIGNAL) return toBlock(f)
  }
  return undefined
}

/** The family token in a model id, case-insensitive; undefined when none appears. */
export const modelFamily = (raw: string | null | undefined): ModelFamily | undefined => {
  const id = (raw ?? '').toLowerCase()
  return MODEL_FAMILIES.find(t => id.includes(t))
}
