import type { AgentSpawnInput, On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

import { briefPath, formatRun, inlinePrompt, laneRef, parseState, viewOf } from './lanes'

const FOLDER = 'C:/repo/.claude/state/harness/parallel2'
const STATE = `${FOLDER}/feat-x.json`
const BRIEF = `${FOLDER}/feat-x/task1.md`
const TREE = 'C:/trees/p2-task1'
const BRIEF_TEXT = '## Pre-Authorized Tools\n- Read\n\nWorking directory: C:/trees/p2-task1\n'

const lane = (id: string, over: Record<string, unknown> = {}) => ({
  id, kind: 'implement', model: 'haiku', wave: 1, status: 'dispatched', worktree: `C:/trees/p2-${id}`, ...over,
})

const stateText = (lanes: unknown[] = [lane('task1'), lane('rev', { kind: 'review', worktree: null })]) =>
  JSON.stringify({ target: 'feat-x', lanes })

// ---------------------------------------------------------------------------
// The world beneath the plugin

type World = {
  files: Map<string, string>
  spawned: AgentSpawnInput[]
  toasts: string[]
  /** Every file read throws. */
  isDiskBroken: boolean
}

/** Answers file reads from memory, records each spawn that reaches the engine and each toast. */
const world = (on: On, files: Record<string, string> = { [BRIEF]: BRIEF_TEXT, [STATE]: stateText() }): World => {
  const w: World = { files: new Map(Object.entries(files)), spawned: [], toasts: [], isDiskBroken: false }
  on('fs.read', (_$, e) => {
    if (w.isDiskBroken) throw new Error('disk gone')
    // the engine hands the hook an OS-native path (backslashes on Windows)
    const text = w.files.get(e.path.replace(/\\/g, '/'))
    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  on('agent.spawn', (_$, e) => {
    w.spawned.push(e)
    return { model: e.model ?? 'inherit', agentId: `agent-${w.spawned.length}` }
  })
  on('ui.toast', (_$, e) => {
    w.toasts.push(e.text)
    return { value: undefined }
  })
  return w
}

const dispatch = (prompt: string, model?: string) => ({ prompt, description: 'lane', ...(model ? { model } : {}) })

// ---------------------------------------------------------------------------
// Pure: the Brief line, the paths, the state

describe('briefPath and laneRef', () => {
  test('the first non-blank line names the brief', async () => {
    expect(briefPath(`\n  Brief: ${BRIEF}  \nthen work`)).toBe(BRIEF)
    expect(briefPath('do the work\nBrief: x.md')).toBeUndefined()
  })

  test('a brief path under parallel2/<slug>/ names its state file and lane', async () => {
    expect(laneRef(BRIEF)).toEqual({ stateFile: STATE, laneId: 'task1' })
    expect(laneRef('C:\\repo\\.claude\\state\\harness\\parallel2\\feat-x\\task-2.md'))
      .toEqual({ stateFile: STATE, laneId: 'task-2' })
  })

  test('any other path names no lane', async () => {
    expect(laneRef('C:/repo/docs/brief.md')).toBeUndefined()
    expect(laneRef(`${FOLDER}/feat-x/Task1.md`)).toBeUndefined()
    expect(laneRef(`${FOLDER}/feat-x.json`)).toBeUndefined()
  })
})

describe('parseState', () => {
  test('reads the target and every lane', async () => {
    const state = parseState(stateText())
    expect(state?.target).toBe('feat-x')
    expect(state?.lanes.map(item => [item.id, item.worktree])).toEqual([['task1', TREE], ['rev', null]])
  })

  test('anything else is no state', async () => {
    expect(parseState('{nope')).toBeUndefined()
    expect(parseState(JSON.stringify({ target: 'x' }))).toBeUndefined()
    expect(parseState(JSON.stringify({ target: 'x', lanes: [{ id: 'a' }] }))).toBeUndefined()
  })
})

describe('inlinePrompt and formatRun', () => {
  test('the brief comes first and the prompt is kept whole', async () => {
    expect(inlinePrompt('brief\n\n', `Brief: ${BRIEF}`)).toBe(`brief\n\nBrief: ${BRIEF}`)
  })

  test('a run reads by wave, agent phases in parentheses', async () => {
    const state = parseState(stateText([lane('a'), lane('b', { status: 'staged' }), lane('c', { wave: 2, status: 'planned' })]))
    const view = viewOf(STATE, state!, { [`${STATE}#a`]: 'running' })
    expect(formatRun(view)).toBe('parallel2 feat-x: w1 a dispatched (running), b staged · w2 c planned')
  })
})

// ---------------------------------------------------------------------------
// The spawn

describe('a lane spawn', () => {
  test('an implement lane starts with its brief, the plan model and its worktree', async ($, on) => {
    const w = world(on)
    const started = await $.agent.spawn(dispatch(`Brief: ${BRIEF}\nStart now.`))
    expect(started.agentId).toBe('agent-1')
    const e = w.spawned[0]!
    expect(e.prompt).toBe(`${BRIEF_TEXT.trimEnd()}\n\nBrief: ${BRIEF}\nStart now.`)
    expect(e.model).toBe('haiku')
    expect(e.cwd).toBe(TREE)
    expect(w.toasts).toEqual([])
  })

  test('a read-only lane keeps the session directory', async ($, on) => {
    const brief = `${FOLDER}/feat-x/rev.md`
    const w = world(on, { [brief]: 'review brief', [STATE]: stateText() })
    await $.agent.spawn(dispatch(`Brief: ${brief}`, 'haiku'))
    expect(w.spawned[0]!.prompt.startsWith('review brief')).toBe(true)
    expect(w.spawned[0]!.cwd).toBeUndefined()
  })

  test('the plan model wins over another model the call names, with a toast', async ($, on) => {
    const w = world(on)
    await $.agent.spawn(dispatch(`Brief: ${BRIEF}`, 'opus'))
    expect(w.spawned[0]!.model).toBe('haiku')
    expect(w.toasts).toEqual([
      "parallel2-lanes: lane task1 runs on haiku, the plan's model (the call named opus)",
    ])
  })

  test('a prompt without a Brief line passes through untouched', async ($, on) => {
    const w = world(on)
    await $.agent.spawn(dispatch('Review the diff.', 'sonnet'))
    expect(w.spawned[0]!.prompt).toBe('Review the diff.')
    expect(w.spawned[0]!.model).toBe('sonnet')
    expect(w.spawned[0]!.cwd).toBeUndefined()
  })

  test('a missing brief, a missing state or an unknown lane passes through', async ($, on) => {
    const w = world(on, { [STATE]: stateText() })
    await $.agent.spawn(dispatch(`Brief: ${BRIEF}`, 'sonnet'))
    await $.agent.spawn(dispatch(`Brief: ${FOLDER}/feat-x/ghost.md`, 'sonnet'))
    w.files.set(BRIEF, BRIEF_TEXT)
    w.files.delete(STATE)
    await $.agent.spawn(dispatch(`Brief: ${BRIEF}`, 'sonnet'))
    expect(w.spawned.map(e => [e.prompt.startsWith('Brief:'), e.model])).toEqual([
      [true, 'sonnet'], [true, 'sonnet'], [true, 'sonnet'],
    ])
  })

  test('a broken file system never blocks the spawn', async ($, on) => {
    const w = world(on)
    w.isDiskBroken = true
    const started = await $.agent.spawn(dispatch(`Brief: ${BRIEF}`, 'sonnet'))
    expect(started.agentId).toBe('agent-1')
    expect(w.spawned[0]!.prompt).toBe(`Brief: ${BRIEF}`)
  })
})
