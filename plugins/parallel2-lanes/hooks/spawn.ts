import type { AgentSpawnInput, EngineInterface, On } from 'claude-code'

import type { LaneRef, LaneState } from '../types'
import { briefPath, inlinePrompt, laneCwd, laneRef, markAgent, readState, readText, recordAgent, refreshRuns } from './lanes'

/**
 * The lane spawn: an Agent call whose prompt opens with a parallel2 `Brief: <path>` line starts with the
 * brief text inline, the plan's model for the lane and, for an implement lane, the lane worktree as its
 * working directory. Forks, teammates, resumes, workflow agents and any prompt whose brief or run state does
 * not read pass through unchanged.
 */

/** A recorded lane behind a spawn prompt, with the brief text. */
export type LaneHit = { ref: LaneRef; lane: LaneState; brief: string }

const noop = (): undefined => undefined

/** True for a spawn the mod never rewrites. */
const isOutOfScope = (e: AgentSpawnInput): boolean => Boolean(e.fork || e.isTeammate || e.resume || e.workflow)

/** The lane a spawn prompt names, its brief read; undefined when anything is missing. Never throws. */
export async function laneOfPrompt($: EngineInterface, prompt: string): Promise<LaneHit | undefined> {
  const path = briefPath(prompt)
  const ref = path === undefined ? undefined : laneRef(path)
  if (path === undefined || ref === undefined) return undefined
  const [brief, state] = [await readText($, path), await readState($, ref.stateFile)]
  const lane = state?.lanes.find(item => item.id === ref.laneId)
  return brief === undefined || lane === undefined ? undefined : { ref, lane, brief }
}

/** The spawn input for a lane: brief inline, the lane's model, the lane's worktree when it has one. */
export const laneSpawn = (e: AgentSpawnInput, hit: LaneHit): AgentSpawnInput => {
  const cwd = laneCwd(hit.lane)
  return { ...e, prompt: inlinePrompt(hit.brief, e.prompt), model: hit.lane.model || e.model, ...(cwd ? { cwd } : {}) }
}

/** The toast for a call that named a model other than the plan's; undefined when they agree. */
export const overrideNote = (e: AgentSpawnInput, hit: LaneHit): string | undefined =>
  e.model && hit.lane.model && e.model !== hit.lane.model
    ? `parallel2-lanes: lane ${hit.lane.id} runs on ${hit.lane.model}, the plan's model (the call named ${e.model})`
    : undefined

/** A resumed lane agent runs again: its lane reads `running` once the resume started. Never throws. */
export async function resumeLane($: EngineInterface, agentId: string): Promise<void> {
  if (await markAgent($, agentId, 'running').catch(noop)) await refreshRuns($).catch(noop)
}

export function registerSpawn(on: On): void {
  on('agent.spawn', async ($, e, next) => {
    if (e.resume) {
      const resumed = await next(e)
      await resumeLane($, e.resume.agentId)
      return resumed
    }
    const hit = isOutOfScope(e) ? undefined : await laneOfPrompt($, e.prompt).catch(noop)
    if (hit === undefined) return next(e)
    const note = overrideNote(e, hit)
    if (note) $.ui.toast(note)
    const started = await next(laneSpawn(e, hit))
    if (started.agentId) {
      await recordAgent($, started.agentId, hit.ref, 'running')
      await refreshRuns($)
    }
    return started
  }).catch((_$, e, next) => next(e))
}
