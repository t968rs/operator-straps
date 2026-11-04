import type { FsEntry } from 'claude-code'

import type { AgentRec, LogFailure, Run } from '../../types'
import type { Dispatch, Header, ReturnBlock } from './contract'
import type { FixerCounts } from './usageRow'
import type { Watch } from './watch'

/**
 * The contract between the generic core and a skill layer. Core records every `Agent` dispatch, folds
 * its usage and appends its usage row; a layer claims the dispatches its skill makes and adds what only it
 * knows (phases, bubbled ids, matrix rows, Stop rules). Layer members never receive the engine: core hands
 * them an `Io` of closures that `ioOf` (./watch) builds (Decision D1). Hooks a layer raises on its own
 * register in its `register<Name>Layer(on)` function, which `register.ts` calls directly (Decision D7); those
 * hooks get the engine from the engine itself and reach `Io` through `ioOf`. Types only.
 */

/** What one subagent turn (or a synchronous Agent result) contributes. */
export type Completion = {
  /** Tokens summed over every model request the turn made. */
  tokens: number
  /** Tokens of the last model request alone; absent when unknown (an errored result, or a background loop with no request reporting usage). */
  contextTokens?: number
  /** Model requests the turn made; absent when none was heard. */
  requests?: number
  toolUses: number
  durationMs: number
  model: string | null
  block: ReturnBlock | undefined
  isMeasured: boolean
  /** `ok`: a result the engine reported; `errored`: an error or unfinished Agent result; `denied`: never ran. */
  ending: 'ok' | 'errored' | 'denied'
}

/** Tracked runs by run id. */
export type Runs = Record<string, Run>

/** Who a claimed dispatch is: the run it joins and the agent it adds. */
export type Claim = Dispatch

/** The fields of an `Agent` tool answer the watch reads; the engine's union is wider. */
export type AgentAnswer = { result?: unknown; text?: string; isError?: true; deny?: string }

/** The fields of a Stop input the layers read. */
export type StopInput = { stop_hook_active: boolean; last_assistant_message?: string; session_id?: string }

/**
 * The host as a layer reaches it, bound to one harness project (`watch`). File and process access never
 * throws: a refused read is undefined, a refused write is false, a failed listing is empty. State access
 * names each key of the mod's state (types/index.d.ts), since the engine reads only atoms it can see
 * statically, and rejects as the engine does.
 */
export type Io = {
  readonly watch: Watch
  /** The file's text; undefined when it is missing or the read is refused. */
  readText(path: string): Promise<string | undefined>
  /** The folder's entries; empty when it is missing or the listing is refused. */
  listDir(path: string): Promise<FsEntry[]>
  /** Whether the path exists; undefined when the host cannot tell. */
  exists(path: string): Promise<boolean | undefined>
  /** The path's modification time in epoch ms; undefined when it cannot be read. */
  mtimeOf(path: string): Promise<number | undefined>
  /** Writes the whole file; false when the write is refused. */
  write(path: string, text: string): Promise<boolean>
  /** `git -C <watch.root> <args>`: its trimmed stdout on exit 0, else undefined. */
  gitLine(args: readonly string[]): Promise<string | undefined>
  toast(text: string): Promise<void>
  /** The engine clock, epoch ms. */
  now(): Promise<number>
  /** Tracked runs by run id. */
  runs(): Promise<Runs>
  updateRuns(change: (runs: Runs) => Runs): Promise<void>
  /** The run id of the latest layer-claimed dispatch; null before any. */
  activeRunId(): Promise<string | null>
  updateFailures(change: (failures: LogFailure[]) => LogFailure[]): Promise<void>
  /** Run keys of hot Phase 5 sentinels (the pr-review layer's). */
  setPhase5(keys: string[]): Promise<void>
  /** Tracked bubbled ids the active run's review JSON does not disposition (the pr-review layer's). */
  missing(): Promise<string[]>
  setMissing(ids: string[]): Promise<void>
}

/**
 * One skill layer.
 *
 * `identify` is pure and is called once per `Agent` call in a harness project, in the order of `LAYERS`, with
 * every header line of the prompt and the resolved project. The first layer that answers owns the run; its
 * `name` is recorded as the run's `claimedBy`. A dispatch no layer claims is still tracked and logged by core
 * as a run of its own (`claimedBy` unset), its row values read from the prompt's leading header block. A
 * layer whose claim keys (RUN_ID, AGENT_ID, AGENT_ROLE) any skill may print refuses a header whose `SKILL:`
 * names another skill (Decision D9).
 *
 * Per-run members go only to the layer named by the run's `claimedBy`, after core's own step: `foldRun`
 * (pure) inside the same state update that folds a completion into the agent, whether or not a project
 * resolves; `onComplete` for side effects once that fold is stored; `rowFields` for the outcome counts of the
 * agent's usage row; `resultContext` for the lines appended to a successful `Agent` result's `context`.
 *
 * Every-layer members go to each layer in `LAYERS` order: `onSettle` with the active run on core's refreshes
 * (after a claimed dispatch, on every turn end, before the Stop check), and `stopReason` after that refresh
 * at Stop, where the first reason blocks. A layer's own hooks may settle it alone (pr-review's shell and
 * session-start refreshes call only its own `onSettle`).
 *
 * A member that throws counts as no answer: core goes on with the next layer and its own step.
 */
export type Layer = {
  readonly name: string
  identify(subagentType: string | undefined, header: Header, watch: Watch | undefined): Claim | undefined
  foldRun?(run: Run, agentId: string, completion: Completion): Run
  onComplete?(io: Io, run: Run, agentId: string, completion: Completion): Promise<void>
  rowFields?(io: Io, run: Run, agent: AgentRec, completion: Completion): Promise<FixerCounts | undefined>
  resultContext?(io: Io, run: Run, agent: Claim, result: AgentAnswer): Promise<string[]>
  onSettle?(io: Io, run: Run | undefined): Promise<void>
  stopReason?(io: Io, stop: StopInput): Promise<string | undefined>
}
