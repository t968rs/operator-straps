import type { Counts, Phase, Skill } from '../../types'

/**
 * Parsers for `Agent` prompt headers and return-contract blocks (the harness pr-team skill's
 * `return_contract.md`), the defined-agent list and the generated run id of an unclaimed dispatch. Pure: no `$`.
 */

/** Header fields of an `Agent` prompt: `KEY=value` and `KEY: value` lines at column 1. */
export type Header = Readonly<Record<string, string>>

/** Who a tracked `Agent` dispatch is. */
export type Dispatch = {
  /** The run's state key: a layer's RUN_ID, or the generated id of a dispatch no layer claims. */
  runId: string
  skill: Skill
  agentId: string
  role: string
  /**
   * The run key a layer names (pr-review: a PR number, or a `local-<label>` key for a review-local run); null
   * when the run names none.
   */
  pr: number | string | null
  runtimeDir: string | null
  phase: Phase
  /** An unclaimed dispatch's logged `run_id` when it differs from `runId` (its header RUN_ID). */
  logRunId?: string
  /** An unclaimed dispatch's usage-row `fields`; absent when none survive. */
  fields?: Readonly<Record<string, string>>
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

/** Every header line anywhere in the prompt: what a layer claims from (pr-review and pr-team headers). */
export const parseHeader = (prompt: string): Header => fieldsOf(prompt.split(/\r?\n/), HEADER_LINE)

/**
 * The prompt's leading header block (Decision D3): the run of header lines at its top, after any blank
 * lines, ending at the first line that is not one. A `SIGNAL:`-style line in the body is never part of it.
 */
export const leadingHeader = (prompt: string): Header => {
  const lines = prompt.split(/\r?\n/)
  const start = lines.findIndex(l => l.trim() !== '')
  if (start < 0) return {}
  const end = lines.findIndex((l, i) => i >= start && !HEADER_LINE.test(l.trimEnd()))
  return fieldsOf(lines.slice(start, end < 0 ? lines.length : end), HEADER_LINE)
}

/**
 * Every agent the marketplace defines, as Claude Code names the type: `<plugin>:<file stem>` for each file in a
 * plugin's `agents` folder. `tests/mods/test_agent_watcher_usage_contract.py` pins the list to those files. Data
 * only since every dispatch is tracked (Decision D5).
 */
export const DEFINED_AGENTS = [
  'harness:bubble-memo-investigator', 'harness:bubble-memo-reviewer', 'harness:docstring-writer',
  'harness:messenger', 'harness:pr-fixer', 'harness:pr-reviewer', 'harness:pr-team-fixer',
  'harness:pr-team-orchestrator', 'harness:roast-my-code', 'harness:strap-judge',
  'harness:strap-scenario-runner', 'harness:todo-editor',
] as const

export const isDefinedAgent = (subagentType: string | undefined): boolean =>
  (DEFINED_AGENTS as readonly (string | undefined)[]).includes(subagentType)

/**
 * `standalone_<UTC yyyymmddTHHMMSSZ>_<seq>`: the state key of a dispatch no layer claims, one run per dispatch;
 * `seq` tells same-second dispatches apart.
 */
export const standaloneRunId = (now: number, seq: number): string =>
  `standalone_${new Date(now).toISOString().replace(/\.\d+Z$/, 'Z').replace(/[-:]/g, '')}_${seq}`

/** The agent type's name after any `<plugin>:` prefix; `general-purpose` when the call names none. */
export const typeName = (subagentType: string | undefined): string =>
  subagentType?.slice(subagentType.indexOf(':') + 1) || 'general-purpose'

/** Whether a value holds a path separator (`/` or `\`): such a value never reaches the log (Decision D8). */
export const holdsPath = (value: string): boolean => /[\\/]/.test(value)

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
