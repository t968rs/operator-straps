import type { EngineInterface } from 'claude-code'
import { atom, read, update } from 'claude-code'

import type { AgentPhase, LaneRef, LaneState, LaneView, RunState, RunView } from '../types'

export const spawnedAtom = atom({ plugin: 'parallel2-lanes', key: 'spawned' } as const, {})
export const agentsAtom = atom({ plugin: 'parallel2-lanes', key: 'agents' } as const, {})
export const runsAtom = atom({ plugin: 'parallel2-lanes', key: 'runs' } as const, [])

/**
 * Reading parallel2's files: the `Brief: <path>` line a dispatch row hands the session, the brief, and the
 * run state beside it. Pure helpers first; functions taking `$` are function declarations (the engine
 * follows `$` past an import only into one) and never throw.
 */

const BRIEF_LINE = /^\s*Brief:\s*(\S.*?)\s*$/
const BRIEF_PATH = /^(.*)\/parallel2\/([^/]+)\/([a-z0-9][a-z0-9-]*)\.md$/

const noop = (): undefined => undefined

/** The path on the prompt's first non-blank line when it reads `Brief: <path>`; else undefined. */
export const briefPath = (prompt: string): string | undefined => {
  const first = prompt.split(/\r?\n/).find(line => line.trim() !== '')
  return first?.match(BRIEF_LINE)?.[1]
}

/** The run state file and lane id a brief path names: `<folder>/parallel2/<slug>/<lane>.md`. */
export const laneRef = (path: string): LaneRef | undefined => {
  const match = path.replace(/\\/g, '/').match(BRIEF_PATH)
  if (!match) return undefined
  return { stateFile: `${match[1]}/parallel2/${match[2]}.json`, laneId: match[3] ?? '' }
}

/** The key of a lane across runs: `<stateFile>#<laneId>`. */
export const laneKey = (ref: LaneRef): string => `${ref.stateFile}#${ref.laneId}`

const textOrNull = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null)

const laneOf = (raw: unknown): LaneState | undefined => {
  if (typeof raw !== 'object' || raw === null) return undefined
  const lane = raw as Record<string, unknown>
  if (typeof lane.id !== 'string' || typeof lane.status !== 'string') return undefined
  return {
    id: lane.id, kind: String(lane.kind ?? ''), model: String(lane.model ?? ''), status: lane.status,
    wave: typeof lane.wave === 'number' ? lane.wave : null, worktree: textOrNull(lane.worktree),
  }
}

/** A run state file's text as the mod reads it; undefined when it is not one. */
export const parseState = (text: string): RunState | undefined => {
  try {
    const data = JSON.parse(text) as { target?: unknown; lanes?: unknown }
    if (typeof data.target !== 'string' || !Array.isArray(data.lanes)) return undefined
    const lanes = data.lanes.map(laneOf)
    return lanes.every(Boolean) ? { target: data.target, lanes: lanes as LaneState[] } : undefined
  } catch {
    return undefined
  }
}

/** The brief text first, then the prompt as the session wrote it (its `Brief:` line included). */
export const inlinePrompt = (brief: string, prompt: string): string => `${brief.trimEnd()}\n\n${prompt}`

/**
 * The directory a lane agent runs in: a live implement lane's worktree; undefined for any other lane and for
 * a cleaned lane, whose recorded worktree is gone (the driver's `has_live_worktree` rule).
 */
export const laneCwd = (lane: LaneState): string | undefined =>
  lane.kind === 'implement' && lane.status !== 'cleaned' && lane.worktree ? lane.worktree : undefined

/** The band's view of a run: every lane with its agent phase from this session, if any. */
export const viewOf = (stateFile: string, state: RunState, agents: Record<string, AgentPhase>): RunView => ({
  stateFile,
  target: state.target,
  lanes: state.lanes.map((lane): LaneView => ({
    id: lane.id, wave: lane.wave, status: lane.status, agent: agents[laneKey({ stateFile, laneId: lane.id })] ?? null,
  })),
})

const laneText = (lane: LaneView): string => `${lane.id} ${lane.status}${lane.agent ? ` (${lane.agent})` : ''}`

/** `parallel2 <target>: w1 a dispatched (running), b staged · w2 c planned`; lanes without a wave go last. */
export const formatRun = (run: RunView): string => {
  const waves = [...new Set(run.lanes.map(lane => lane.wave))].sort((a, b) => (a ?? Infinity) - (b ?? Infinity))
  const parts = waves.map(wave => {
    const lanes = run.lanes.filter(lane => lane.wave === wave).map(laneText).join(', ')
    return wave === null ? lanes : `w${wave} ${lanes}`
  })
  return `parallel2 ${run.target}: ${parts.join(' · ')}`
}

/** A file's text; undefined when it cannot be read. */
export async function readText($: EngineInterface, path: string): Promise<string | undefined> {
  const value = await $.fs.read(path).catch(noop)
  return typeof value === 'string' ? value : undefined
}

/** The run state at `stateFile`; undefined when it is gone or unreadable. */
export async function readState($: EngineInterface, stateFile: string): Promise<RunState | undefined> {
  const text = await readText($, stateFile)
  return text === undefined ? undefined : parseState(text)
}

/** Records a started lane agent: its lane by agent id, and the lane's phase. Never throws. */
export async function recordAgent($: EngineInterface, agentId: string, ref: LaneRef, phase: AgentPhase) {
  await update($, spawnedAtom, spawned => ({ ...spawned, [agentId]: ref })).catch(noop)
  await update($, agentsAtom, agents => ({ ...agents, [laneKey(ref)]: phase })).catch(noop)
}

/** Sets the phase of a known lane agent's lane; false when the agent runs no lane. Never throws. */
export async function markAgent($: EngineInterface, agentId: string, phase: AgentPhase): Promise<boolean> {
  const ref = (await read($, spawnedAtom).catch(noop))?.[agentId]
  if (ref === undefined) return false
  await update($, agentsAtom, agents => ({ ...agents, [laneKey(ref)]: phase })).catch(noop)
  return true
}

/** Rereads every run a lane agent was spawned for; a run whose state file is gone drops out. Never throws. */
export async function refreshRuns($: EngineInterface): Promise<void> {
  const spawned = (await read($, spawnedAtom).catch(noop)) ?? {}
  const agents = (await read($, agentsAtom).catch(noop)) ?? {}
  const runs: RunView[] = []
  for (const stateFile of new Set(Object.values(spawned).map(ref => ref.stateFile))) {
    const state = await readState($, stateFile)
    if (state !== undefined) runs.push(viewOf(stateFile, state, agents))
  }
  await update($, runsAtom, () => runs).catch(noop)
}
