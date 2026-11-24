import type { EngineInterface, Register } from 'claude-code'

import { stateDirOf, stateFileOf } from './notes'

/**
 * Optional session hook: a goal, free text or a TODO item, turned into the session's goal.
 *
 * `add_todo.py hook` and `add_note.py goal` (harness plugin) write the hook switch,
 * `<state_dir>/session-bookmark/hook.json`: `{ "version": 1, "hook": { "goal", "start_time", "todo_id", ... },
 * "fired": null }`, with `todo_id` null for a free-text goal. While
 * `fired` is null, the end of the next main-loop turn queues `/goal <goal>` through `$.command.run`, which
 * runs once the session is idle, then stamps `fired` with the time, so the goal is set once. `/goal` is the engine's session-scoped Stop hook: its evaluator keeps the session going until the
 * condition holds, and `/goal clear` ends it. An installed mod cannot read the harness plugin, so the path,
 * version and keys are copied here; `tests/mods/test_session_bookmark_hook_contract.py` pins them against
 * `harness_lib.add_todo_api`. Every failure leaves the switch armed and the turn's result as it was; the hook
 * never throws past `next`.
 */

type Dollar = EngineInterface

export const HOOK_PATH = 'session-bookmark/hook.json'
export const HOOK_SCHEMA_VERSION = 1
/** The longest goal sent, in code points: `/goal` refuses a longer condition, and the harness caps the armed condition at the same length. */
export const MAX_GOAL_CHARS = 500
/** The built-in command the switch fires. */
export const GOAL_COMMAND = 'goal'
/** The switch key stamped once the goal was queued; null while armed. */
export const FIRED_KEY = 'fired'
/** How long one `git rev-parse` may run (the bookmark's git timeout). */
const GIT_TIMEOUT_MS = 5000

/** An armed switch as the mod acts on it: the goal text and the item it names (null for a free-text goal). */
export type HookSwitch = { goal: string; todoId: string | null; startTime: number }

type Json = Readonly<Record<string, unknown>>

const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

const parse = (text: string): unknown => {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

// ---------------------------------------------------------------------------
// Pure

/** The switch file under `root`; an absolute `stateDir` is kept as it is (the notes path rule). */
export const hookFileOf = (root: string, stateDir: string): string => stateFileOf(root, stateDir, HOOK_PATH)

/** The goal cut to the limit in code points (as the harness counts it), whitespace folded; null when blank. */
const goalText = (value: unknown): string | null => {
  const text = typeof value === 'string' ? value.split(/\s+/).join(' ').trim() : ''
  return text === '' ? null : Array.from(text).slice(0, MAX_GOAL_CHARS).join('')
}

/**
 * The switch when it is armed: right version, a usable goal, `fired` null or absent. Null for a fired,
 * malformed or foreign file.
 */
export const armedSwitch = (text: string): HookSwitch | null => {
  const data = parse(text)
  if (!isObject(data) || data.version !== HOOK_SCHEMA_VERSION || !isObject(data.hook)) return null
  if (data[FIRED_KEY] !== null && data[FIRED_KEY] !== undefined) return null
  const goal = goalText(data.hook.goal)
  if (goal === null) return null
  const todoId = typeof data.hook.todo_id === 'string' && data.hook.todo_id !== '' ? data.hook.todo_id : null
  const startTime = typeof data.hook.start_time === 'number' ? data.hook.start_time : 0
  return { goal, todoId, startTime }
}

/** The file's text with `fired` stamped `{ at }` (epoch ms); the input unchanged when it is not an object. */
export const markFired = (text: string, at: number): string => {
  const data = parse(text)
  return isObject(data) ? `${JSON.stringify({ ...data, [FIRED_KEY]: { at } }, null, 2)}\n` : text
}

// ---------------------------------------------------------------------------
// Host access (kept in this file: `$` is not passed across an import)

/** Folders to look in, in order: the session cwd, then CLAUDE_PROJECT_DIR; blanks and repeats dropped. */
const rootCandidates = async ($: Dollar): Promise<string[]> => {
  const cwd = await $.session.cwd().catch(() => undefined)
  const env = await $.env.get('CLAUDE_PROJECT_DIR').catch(() => undefined)
  return [...new Set([cwd, env].filter((p): p is string => p !== undefined && p.trim() !== ''))]
}

/** The git top level of `root`, where the harness writers put the switch; null when it is no repository. */
const gitTop = async ($: Dollar, root: string): Promise<string | null> => {
  const ran = await $.process
    .run(['git', '-C', root, 'rev-parse', '--show-toplevel'],
      { timeoutMs: GIT_TIMEOUT_MS, env: { GIT_OPTIONAL_LOCKS: '0' } })
    .catch(() => undefined)
  const top = ran === undefined || ran.exitCode !== 0 ? '' : ran.stdout.trim()
  return top === '' ? null : top
}

/**
 * Folders that may hold the switch: the top level of the first candidate inside a repository (the root the
 * harness writers resolve, as `bookmark.ts` does for the notes), else the raw candidates. Never throws.
 */
const switchRoots = async ($: Dollar): Promise<string[]> => {
  const candidates = await rootCandidates($)
  for (const root of candidates) {
    const top = await gitTop($, root)
    if (top !== null) return [top]
  }
  return candidates
}

/** The first root's switch path and text; undefined when no root holds one. Never throws. */
const findSwitch = async ($: Dollar): Promise<{ path: string; text: string } | undefined> => {
  for (const root of await switchRoots($)) {
    const clean = root.replace(/\\/g, '/')
    const config = await $.fs.read(`${clean}/.claude/harness.json`).catch(() => undefined)
    const path = hookFileOf(clean, stateDirOf(config))
    const text = await $.fs.read(path).catch(() => undefined)
    if (typeof text === 'string') return { path, text }
  }
  return undefined
}

/** Per-load guard: a switch (by start time) is tried at most once per load, so a refusal does not loop. */
const tried = new Set<number>()

/** The toast's tail when the goal was set but the switch could not be stamped fired. */
export const STAMP_FAILED = 'could not mark the switch fired (add_note.py goal --clear removes it)'

/** Shows one toast; a refused toast is dropped. Never throws. */
const toast = ($: Dollar, text: string): void => {
  try {
    $.ui.toast(text)
  } catch {
    // a refused toast changes nothing else
  }
}

/**
 * Stamps the switch fired when its text is still the one read before `/goal` was queued; a switch re-armed or
 * removed meanwhile is left as it is. Throws when the read or the write fails.
 */
const stampFired = async ($: Dollar, found: { path: string; text: string }): Promise<void> => {
  const current = await $.fs.read(found.path).catch(() => undefined)
  if (current !== found.text) return
  await $.fs.write(found.path, markFired(found.text, await $.clock.now()))
}

/**
 * Queues `/goal` for an armed switch and stamps it fired. A rejected run leaves it armed for the next load and
 * says so in a toast; a stamp that fails after the goal was set says that instead, since the next load would
 * set the goal again until the switch is cleared. Never throws.
 */
const fire = async ($: Dollar): Promise<void> => {
  const found = await findSwitch($)
  const armed = found === undefined ? null : armedSwitch(found.text)
  if (found === undefined || armed === null || tried.has(armed.startTime)) return
  tried.add(armed.startTime)
  const item = armed.todoId === null ? '' : ` for ${armed.todoId}`
  try {
    await $.command.run({ command: GOAL_COMMAND, args: armed.goal })
  } catch {
    toast($, `session-bookmark: could not set the goal${item}`)
    return
  }
  try {
    await stampFired($, found)
  } catch {
    toast($, `session-bookmark: goal set${item}; ${STAMP_FAILED}`)
  }
}

// ---------------------------------------------------------------------------
// Registration

/**
 * Registers the hook switch's trigger: the end of each main-loop turn, so a switch armed during a turn (the
 * add-todo run that wrote it) sets the goal as soon as the session is idle. `$.command.run` rejects inside a
 * hook the turn waits on, so `fire` starts without being awaited, after `next`. `session.start` and
 * `prompt.submit` are `bookmark.ts`'s; a second unmatched hook on either is refused at load.
 */
export const registerSessionHook = (on: Parameters<Register>[0]): void => {
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined) void fire($).catch(() => undefined)
    return result
  }).catch((_$, e, next) => next(e))
}
