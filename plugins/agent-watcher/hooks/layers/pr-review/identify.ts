import type { Phase, Skill } from '../../../types'
import { parseHeader, type Dispatch, type Header } from '../../core/contract'
import { keyOfRunId, toRunKey } from './runKey'

/**
 * Which pr-team / pr-review `Agent` dispatch a prompt header names (the harness pr-team skill's
 * `canonical_prompt_template.md` and the rows `pr_review.py` prints): `RUN_ID`, then `MODE` for the pr-team
 * orchestrator and fixer agents, else `AGENT_ID` / `AGENT_ROLE` for a reviewer, fixer or (pr-review only)
 * refuter slot. Pure: no `$`.
 */

/** Phase, agent id and role per pr-team agent family and MODE. */
const MODES: Readonly<Record<string, Readonly<Record<string, readonly [Phase, string, string]>>>> = {
  orchestrator: {
    PLAN: ['plan', 'orchestrator_plan', 'orchestrator'],
    CONSOLIDATE: ['consolidate', 'orchestrator_consolidate', 'orchestrator'],
  },
  fixer: { PLAN: ['fix-plan', 'fixer_plan', 'planner'], CLOSEOUT: ['closeout', 'closer', 'closer'] },
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
  const pr = toRunKey(h.PR_NUMBER) ?? keyOfRunId(runId)
  return { runId, skill: 'pr-team', agentId, role, pr, runtimeDir: h.RUNTIME_DIR ?? null, phase }
}

/** The runtime dir an OUTPUT_FILE slot sits in, else `<runtimeBase>/<runId>`. */
const runtimeDirOf = (h: Header, runId: string, runtimeBase: string): string => {
  const m = (h.OUTPUT_FILE ?? '').match(/^(.*)[\\/]outputs[\\/][^\\/]+$/)
  return m?.[1] ?? `${runtimeBase}/${runId}`
}

/**
 * The `AGENT_ROLE` values of pr-review's adversarial refuters (harness `review_briefs.py` `REFUTER_ROLE`,
 * `CODE_REFUTER_ROLE`, pinned by `tests/mods/test_agent_watcher_adversarial_mirror.py`; agent
 * `harness:adversarial-reviewer`): one token each, so they match ROLE_PATTERN.
 */
export const REFUTER_ROLES = ['refuter', 'code_refuter'] as const
const REFUTERS: readonly string[] = REFUTER_ROLES

/** Roles a slot dispatch may carry: reviewer and fixer anywhere, a refuter only with a `PR:` line. */
const isSlotRole = (role: string | undefined, isReview: boolean): role is string =>
  role === 'reviewer' || role === 'fixer' || (isReview && REFUTERS.includes(role ?? ''))

/**
 * A slot dispatch (`AGENT_ID:` / `AGENT_ROLE:`): pr-review when a `PR:` line is present. The `PR:` value is
 * the run key, a PR number or a review-local `local-<label>` key. A refuter (findings or code) is a
 * pr-review slot of the review phase; pr-team has none.
 */
const slotDispatch = (h: Header, runId: string, runtimeBase: string): Dispatch | undefined => {
  const { AGENT_ID: agentId, AGENT_ROLE: role } = h
  const isReview = h.PR !== undefined
  if (!agentId || !isSlotRole(role, isReview)) return undefined
  const pr = (isReview ? toRunKey(h.PR) : null) ?? keyOfRunId(runId)
  const skill: Skill = isReview ? 'pr-review' : 'pr-team'
  const runtimeDir = isReview ? null : runtimeDirOf(h, runId, runtimeBase)
  return { runId, skill, agentId, role, pr, runtimeDir, phase: role === 'fixer' ? 'fix' : 'review' }
}

/** The skills whose dispatches the layer claims; a header naming another (`SKILL:`) is never claimed. */
const OWN_SKILLS: readonly (string | undefined)[] = [undefined, 'pr-review', 'pr-team']

/**
 * The pr-team / pr-review identity of a parsed header, or undefined for any other dispatch. A header whose
 * `SKILL:` is present and names neither pr-review nor pr-team belongs to that skill, whatever RUN_ID,
 * AGENT_ID and AGENT_ROLE it carries (Decision D9). `runtimeBase` is the project's pr-team runtime folder,
 * used when a pr-team slot names no OUTPUT_FILE.
 */
export const identifyHeader = (
  subagentType: string | undefined,
  h: Header,
  runtimeBase: string,
): Dispatch | undefined => {
  const runId = h.RUN_ID
  if (runId === undefined || runId === '' || !OWN_SKILLS.includes(h.SKILL)) return undefined
  return h.MODE !== undefined ? modeDispatch(subagentType ?? '', h, runId) : slotDispatch(h, runId, runtimeBase)
}

/** `identifyHeader` over a whole prompt. */
export const identify = (
  subagentType: string | undefined,
  prompt: string,
  runtimeBase: string,
): Dispatch | undefined => identifyHeader(subagentType, parseHeader(prompt), runtimeBase)
