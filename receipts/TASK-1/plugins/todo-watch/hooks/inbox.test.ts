import type { ProcessRunResult } from 'claude-code'
import type { Engine } from 'claude-code/testing'
import { describe, expect, test } from 'claude-code/testing'

import { DRAIN_TIMEOUT_MS, drainSummary, isQueuedName, rejectedSummary, waitCapMs } from './inbox'
import {
  agentTurnEnd, checkRuns, completedAgent, dispatch, drainRuns, INBOX_REL, launchedAgent, notify, prompt, PYTHON,
  SCRIPT, start, submit, world, type World,
} from './testWorld'

const ADDED = 'inbox: added 1 item(s): todo-k7qf (#12); check drift=0'
const LEASE = 'problem: catalog lease held by another writer (token abc)'

const ran = (stdout: string, exitCode = 0, stderr = ''): ProcessRunResult => ({
  exitCode, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false,
})

/** A task notification prompt, raised and not awaited: the hook may still be waiting for a drain. */
const notifyLater = ($: Engine) => $.prompt.submit({ ...submit, origin: { kind: 'task-notification' } })

/** A todo-editor dispatch, raised and not awaited. */
const dispatchLater = ($: Engine) =>
  $.tool.call({ tool: 'Agent', description: 'd', prompt: 'p', subagent_type: 'harness:todo-editor' })

/** Releases the held drain and lets every drain after it run free. */
async function release(w: World): Promise<void> {
  w.drain.isHeld = false
  w.drainHeld.shift()?.()
  await w.clock.settle()
}

/** How many times `line` appears across the given contexts. */
const count = (line: string, ...contexts: ReadonlyArray<readonly string[] | undefined>): number =>
  contexts.flatMap(c => c ?? []).filter(l => l === line).length

// ---------------------------------------------------------------------------
// Pure

describe('drainSummary', () => {
  test('exit 0: the inbox line, none when empty or missing', async () => {
    expect(drainSummary(ran(`${ADDED}\n`))).toBe(ADDED)
    expect(drainSummary(ran(`warming up\r\n${ADDED}\r\n`))).toBe(ADDED)
    expect(drainSummary(ran('inbox: empty\n'))).toBeUndefined()
    expect(drainSummary(ran(''))).toBeUndefined()
  })

  test('another exit: the last stderr line, else the exit code', async () => {
    expect(drainSummary(ran('', 2, `noise\n${LEASE}\n\n`))).toBe(`inbox: drain failed: ${LEASE}`)
    expect(drainSummary(ran(`${ADDED}\n`, 1, ''))).toBe('inbox: drain failed: exit 1')
  })

  test('a rejected call is a timeout or a child that never ran', async () => {
    expect(rejectedSummary(new Error('process timed out after 60000 ms'))).toBe('inbox: drain failed: timed out')
    expect(rejectedSummary('spawn ENOENT')).toBe('inbox: drain failed: did not run')
  })
})

describe('isQueuedName', () => {
  test('a json item counts; a hidden put in progress, a rejected file or another file does not', async () => {
    expect(isQueuedName('20261115T100000000000Z-01-ab12.json')).toBe(true)
    expect(isQueuedName('.20261115T100000000000Z-01-ab12.json')).toBe(false)
    expect(isQueuedName('20261115T100000000000Z-01-ab12.rejected.json')).toBe(false)
    expect(isQueuedName('20261115T100000000000Z-01-ab12.reason.txt')).toBe(false)
  })
})

describe('waitCapMs', () => {
  test('the remaining budget less a second, from 0 to the drain timeout', async () => {
    expect(waitCapMs(10_000)).toBe(9_000)
    expect(waitCapMs(500)).toBe(0)
    expect(waitCapMs(120_000)).toBe(DRAIN_TIMEOUT_MS)
    expect(waitCapMs(Number.POSITIVE_INFINITY)).toBe(DRAIN_TIMEOUT_MS)
  })
})

// ---------------------------------------------------------------------------
// Hooks

describe('a todo-editor return drains the inbox', () => {
  test('a foreground return drains now and appends the summary to the tool result', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.drain.stdout = `${ADDED}\n`
    w.agent = completedAgent()
    expect(await dispatch($, w)).toEqual([ADDED])
    expect(drainRuns(w)).toEqual([[PYTHON, SCRIPT, 'add', '--inbox', '--project', '/repo']])
    const at = w.runs.findIndex(argv => argv[2] === 'add')
    expect(w.inits[at]?.timeoutMs).toBe(DRAIN_TIMEOUT_MS)
    expect(checkRuns(w).length).toBe(2)
    expect(await prompt($, w)).not.toContain(ADDED)
  })

  test('another agent, a refused or errored dispatch, or a backgrounded one drains nothing', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.agent = completedAgent()
    expect(await dispatch($, w, 'harness:messenger')).toEqual([])
    w.agent = { deny: 'no' }
    expect(await dispatch($, w)).toEqual([])
    w.agent = { ...completedAgent(), isError: true }
    expect(await dispatch($, w)).toEqual([])
    w.agent = launchedAgent('loop-bg')
    expect(await dispatch($, w)).toEqual([])
    expect(drainRuns(w)).toEqual([])
  })

  test('a subagent turn end drains what is queued; the next task notification waits and carries the line', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.drain.stdout = `${ADDED}\n`
    await agentTurnEnd($, w, 'loop-bg')
    expect(drainRuns(w)).toEqual([])
    w.queueItem()
    w.drain.isHeld = true
    await agentTurnEnd($, w, 'loop-bg')
    expect(drainRuns(w).length).toBe(1)
    const entered = notifyLater($)
    await w.clock.settle()
    await release(w)
    const out = await entered
    expect('context' in out ? out.context : []).toContain(ADDED)
    expect(await notify($, w)).not.toContain(ADDED)
  })

  test('two returns while a drain runs give one owed rerun', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.queueItem()
    w.drain.isHeld = true
    await agentTurnEnd($, w, 'a1')
    await agentTurnEnd($, w, 'a2')
    await agentTurnEnd($, w, 'a3')
    expect(drainRuns(w).length).toBe(1)
    await release(w)
    expect(drainRuns(w).length).toBe(2)
    await w.clock.settle()
    expect(drainRuns(w).length).toBe(2)
  })

  test('a notification waits at most its cap; the line then rides the next prompt', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.queueItem()
    w.drain.stdout = `${ADDED}\n`
    w.drain.isHeld = true
    await agentTurnEnd($, w, 'loop-bg')
    const entered = notifyLater($)
    await w.clock.settle()
    await w.clock.advance(DRAIN_TIMEOUT_MS)
    const out = await entered
    expect('context' in out ? out.context ?? [] : []).not.toContain(ADDED)
    await release(w)
    expect(await prompt($, w)).toContain(ADDED)
    expect(await prompt($, w)).not.toContain(ADDED)
  })

  test('a foreground return while a drain runs waits for it: the line attached once, one drain', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.queueItem()
    w.drainOuts = [`${ADDED}\n`]
    w.drain.stdout = 'inbox: empty\n'
    w.drain.isHeld = true
    await agentTurnEnd($, w, 'loop-other')
    w.agent = completedAgent()
    const call = dispatchLater($)
    await w.clock.settle()
    await release(w)
    const out = await call
    expect(out.context ?? []).toEqual([ADDED])
    expect(drainRuns(w).length).toBe(1)
    expect(await notify($, w)).not.toContain(ADDED)
  })

  test('a notification and a foreground return waiting on one drain: the line lands on one of them', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.queueItem()
    w.drainOuts = [`${ADDED}\n`]
    w.drain.stdout = 'inbox: empty\n'
    w.drain.isHeld = true
    await agentTurnEnd($, w, 'loop-bg')
    w.agent = completedAgent()
    const call = dispatchLater($)
    const entered = notifyLater($)
    await w.clock.settle()
    await release(w)
    const [tool, sent] = [await call, await entered]
    const later = await prompt($, w)
    expect(count(ADDED, tool.context, 'context' in sent ? sent.context : [], later)).toBe(1)
    expect(drainRuns(w).length).toBe(1)
  })

  test('a drain that keeps failing waits as one line, not one per turn end', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.queueItem()
    w.drain = { ...w.drain, stdout: '', stderr: `${LEASE}\n`, exitCode: 1 }
    await agentTurnEnd($, w, 'a1')
    await w.clock.settle()
    await agentTurnEnd($, w, 'a2')
    await w.clock.settle()
    expect(drainRuns(w).length).toBe(2)
    expect(count(`inbox: drain failed: ${LEASE}`, await prompt($, w))).toBe(1)
    expect(checkRuns(w).length).toBe(2)
  })

  test('an empty stdout or inbox: empty attaches nothing', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.agent = completedAgent()
    expect(await dispatch($, w)).toEqual([])
    w.drain.stdout = ''
    expect(await dispatch($, w)).toEqual([])
    expect(drainRuns(w).length).toBe(2)
    expect(checkRuns(w).length).toBe(1)
    expect((await notify($, w)).filter(l => l.startsWith('inbox: '))).toEqual([])
  })

  test('a failed drain attaches the last stderr line; a timeout says so', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.agent = completedAgent()
    w.drain = { ...w.drain, stdout: '', stderr: `${LEASE}\n`, exitCode: 2 }
    expect(await dispatch($, w)).toEqual([`inbox: drain failed: ${LEASE}`])
    w.drain = { ...w.drain, isTimeout: true }
    expect(await dispatch($, w)).toEqual(['inbox: drain failed: timed out'])
  })
})

describe('session start', () => {
  test('an empty inbox spawns no drain', async ($, on) => {
    const w = world(on)
    await start($, w)
    expect(drainRuns(w)).toEqual([])
  })

  test('hidden or rejected files are not queued; a queued item drains, its line on the next prompt', async ($, on) => {
    const w = world(on)
    w.setFile(`${w.root}/${INBOX_REL}/.20261115T100000000000Z-01-ab12.json`, '{}')
    w.setFile(`${w.root}/${INBOX_REL}/20261115T090000000000Z-01-cd34.rejected.json`, '{}')
    await start($, w)
    expect(drainRuns(w)).toEqual([])
    w.queueItem('20261115T100000000000Z-02-ef56.json')
    w.drain.stdout = `${ADDED}\n`
    await start($, w)
    expect(drainRuns(w).length).toBe(1)
    expect(await prompt($, w)).toContain(ADDED)
    expect(await prompt($, w)).not.toContain(ADDED)
  })
})
