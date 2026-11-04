import type { On } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import type { Engine } from 'claude-code/testing'

import { namesDriver } from './band'

const FOLDER = 'C:/repo/.claude/state/harness/parallel2'
const STATE = `${FOLDER}/feat-x.json`
const brief = (id: string) => `${FOLDER}/feat-x/${id}.md`
const NOW_MS = 1_800_000_000_000

const lane = (id: string, over: Record<string, unknown> = {}) => ({
  id, kind: 'implement', model: 'haiku', wave: 1, status: 'dispatched', worktree: `C:/trees/p2-${id}`, ...over,
})

const stateText = (lanes: unknown[]) => JSON.stringify({ target: 'feat-x', lanes })

// ---------------------------------------------------------------------------
// The world beneath the plugin

type World = { files: Map<string, string>; reads: number }

/** File reads from memory, the engine's spawn, turn end, Bash and PowerShell tools and band beneath the plugin. */
const world = (on: On): World => {
  const w: World = {
    files: new Map([
      [STATE, stateText([lane('task1'), lane('task2'), lane('task3', { wave: 2, status: 'planned', worktree: null })])],
      [brief('task1'), 'brief one'], [brief('task2'), 'brief two'],
    ]),
    reads: 0,
  }
  on('fs.read', (_$, e) => {
    w.reads += 1
    // the engine hands the hook an OS-native path (backslashes on Windows)
    const text = w.files.get(e.path.replace(/\\/g, '/'))
    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  let spawns = 0
  on('agent.spawn', (_$, e) => ({ model: e.model ?? 'inherit', agentId: `agent-${(spawns += 1)}` }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '', interrupted: false } }))
  on('tool.call', { tool: 'PowerShell' }, () => ({ result: { stdout: '', stderr: '', interrupted: false } }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.render', ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  return w
}

const BAND = {
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 120, scroll: { offset: 0, bodyRows: 10 }, view: {} },
} as const

/** The band's run lines now; empty when it draws none. */
const bandLines = async ($: Engine, hasSurvey = false): Promise<string[]> => {
  const ui = await $.ui.mount({ plugin: 'parallel2-lanes', surface: 'terminal', ...BAND, props: { ...BAND.props, hasSurvey } })
  const found = await ui.findAll({ type: 'Text', text: /^parallel2 / })
  await ui.unmount()
  return found.map(node => node.text ?? '')
}

const spawnLane = ($: Engine, id: string) => $.agent.spawn({ prompt: `Brief: ${brief(id)}`, description: id })

const turnEnd = ($: Engine, agentId?: string) =>
  $.turn.complete({ answer: 'done', durationMs: 5, isAborted: false, turnId: 't1', reason: 'answer', ...(agentId ? { agentId } : {}) })

// ---------------------------------------------------------------------------

describe('namesDriver', () => {
  test('a command running parallel2.py', async () => {
    expect(namesDriver('sh "C:/p/hpy" "C:/p/scripts/parallel2.py" --repo "C:/r" stage task1')).toBe(true)
    expect(namesDriver('git status')).toBe(false)
    expect(namesDriver(undefined)).toBe(false)
  })
})

describe('the lane band', () => {
  test('no lane spawned this session: no band', async ($, on) => {
    world(on)
    await turnEnd($)
    expect(await bandLines($)).toEqual([])
  })

  test('a spawned lane shows running beside the run\'s other lanes', async ($, on) => {
    world(on)
    await spawnLane($, 'task1')
    expect(await bandLines($)).toEqual([
      'parallel2 feat-x: w1 task1 dispatched (running), task2 dispatched · w2 task3 planned',
    ])
  })

  test('a lane agent\'s turn end marks it returned', async ($, on) => {
    world(on)
    await spawnLane($, 'task1')
    await spawnLane($, 'task2')
    await turnEnd($, 'agent-2')
    expect(await bandLines($)).toEqual([
      'parallel2 feat-x: w1 task1 dispatched (running), task2 dispatched (returned) · w2 task3 planned',
    ])
  })

  test('a driver call rereads the run once the call returns', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const w = world(on)
    await spawnLane($, 'task1')
    w.files.set(STATE, stateText([lane('task1', { status: 'staged' }), lane('task2')]))
    await $.tool.call({ tool: 'Bash', command: 'sh hpy scripts/parallel2.py stage task1' })
    await clock.settle()
    expect(await bandLines($)).toEqual(['parallel2 feat-x: w1 task1 staged (running), task2 dispatched'])
  })

  test('a driver call through PowerShell rereads the run as well', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const w = world(on)
    await spawnLane($, 'task1')
    w.files.set(STATE, stateText([lane('task1', { status: 'staged' }), lane('task2')]))
    await $.tool.call({ tool: 'PowerShell', command: 'sh hpy scripts/parallel2.py stage task1' })
    await clock.settle()
    expect(await bandLines($)).toEqual(['parallel2 feat-x: w1 task1 staged (running), task2 dispatched'])
  })

  test('another Bash call reads nothing', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const w = world(on)
    await spawnLane($, 'task1')
    const before = w.reads
    await $.tool.call({ tool: 'Bash', command: 'git status' })
    await clock.settle()
    expect(w.reads).toBe(before)
  })

  test('a cleaned-up run drops out of the band', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const w = world(on)
    await spawnLane($, 'task1')
    w.files.delete(STATE)
    await $.tool.call({ tool: 'Bash', command: 'sh hpy scripts/parallel2.py cleanup --all' })
    await clock.settle()
    expect(await bandLines($)).toEqual([])
  })

  test('a survey hides the band', async ($, on) => {
    world(on)
    await spawnLane($, 'task1')
    expect(await bandLines($, true)).toEqual([])
  })

  test('a resumed lane agent reads running again', async ($, on) => {
    world(on)
    await spawnLane($, 'task1')
    await turnEnd($, 'agent-1')
    await $.agent.spawn({ prompt: 'keep going', description: 'resume', resume: { agentId: 'agent-1' } } as never)
    expect(await bandLines($)).toEqual([
      'parallel2 feat-x: w1 task1 dispatched (running), task2 dispatched · w2 task3 planned',
    ])
  })
})
