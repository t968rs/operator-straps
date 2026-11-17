import { describe, expect, test } from 'claude-code/testing'

import type { Run } from '../../types'
import { parseReturnBlock, type Dispatch } from './contract'
import type { Completion } from './layer'
import {
  applyCompletion, applyDispatch, markUsageLogged, newAgent, usageToLog, withRun,
} from './runs'

const RUN = 'run_1'
const dispatch = (agentId: string, over: Partial<Dispatch> = {}): Dispatch => ({
  runId: RUN, skill: 'pr-team', agentId, role: 'reviewer', pr: 7, runtimeDir: 'rt', phase: 'review', ...over,
})
const done: Completion = {
  tokens: 10, toolUses: 2, durationMs: 1500, model: 'claude-opus-5-5', isMeasured: true, ending: 'ok',
  block: parseReturnBlock('---\nSIGNAL: DONE\nCOUNTS: findings=1 critical=1 important=0 minor=0\n---'),
}
const runOf = (runs: Record<string, Run>): Run => runs[RUN]!

describe('applyDispatch', () => {
  test('the first dispatch creates the run with its claimer; later ones add agents and move the phase', async () => {
    const one = applyDispatch({}, dispatch('a'), newAgent(dispatch('a'), { model: 'opus', effort: 'high' }), 100, 'x')
    expect(runOf(one)).toMatchObject({
      runId: RUN, skill: 'pr-team', pr: 7, phase: 'review', runtimeDir: 'rt', startedAt: 100, claimedBy: 'x',
      bubbled: [], bubbledFrom: 'none', verdict: null,
    })
    expect(runOf(one).agents.a).toMatchObject({ model: 'opus', effort: 'high', signal: null, usageLoggedAt: null })
    const fix = dispatch('b', { phase: 'fix', pr: null, runtimeDir: null })
    const two = applyDispatch(one, fix, newAgent(fix, {}), 200, 'y')
    expect(runOf(two)).toMatchObject({ phase: 'fix', pr: 7, runtimeDir: 'rt', startedAt: 100, claimedBy: 'x' })
    expect(Object.keys(runOf(two).agents)).toEqual(['a', 'b'])
  })

  test('a standalone run records no claimer', async () => {
    const d = dispatch('messenger', { skill: 'standalone', role: 'other', pr: null, runtimeDir: null, phase: 'done' })
    expect('claimedBy' in runOf(applyDispatch({}, d, newAgent(d, {}), 1))).toBe(false)
  })
})

describe('applyCompletion', () => {
  const base = (): Run => runOf(applyDispatch({}, dispatch('a'), newAgent(dispatch('a'), {}), 1))

  test('usage adds up; signal and counts follow the latest block', async () => {
    const run = applyCompletion(applyCompletion(base(), 'a', done), 'a', { ...done, block: undefined })
    expect(run.agents.a).toMatchObject({
      tokens: 20, toolUses: 4, durationMs: 3000, model: 'claude-opus-5-5', isMeasured: true, signal: 'NO_BLOCK',
    })
    expect(run.agents.a?.counts?.critical).toBe(1)
  })

  test('contextTokens follows the latest completion that reports one', async () => {
    const first = applyCompletion(base(), 'a', { ...done, contextTokens: 50 })
    expect(first.agents.a?.contextTokens).toBe(50)
    const kept = applyCompletion(first, 'a', done)
    expect(kept.agents.a?.contextTokens).toBe(50)
    expect(applyCompletion(kept, 'a', { ...done, contextTokens: 70 }).agents.a?.contextTokens).toBe(70)
    expect('contextTokens' in (applyCompletion(base(), 'a', done).agents.a ?? {})).toBe(false)
  })

  test('requests add up over completions that report them', async () => {
    const one = applyCompletion(base(), 'a', { ...done, requests: 2 })
    expect(applyCompletion(one, 'a', done).agents.a?.requests).toBe(2)
    expect(applyCompletion(one, 'a', { ...done, requests: 3 }).agents.a?.requests).toBe(5)
    expect('requests' in (applyCompletion(base(), 'a', done).agents.a ?? {})).toBe(false)
  })

  test('an agent the run does not hold leaves the run as it is', async () => {
    const run = base()
    expect(applyCompletion(run, 'nope', done)).toBe(run)
  })
})

describe('usage claims', () => {
  test('a returned agent is claimable once; a running or unknown one never', async () => {
    const run = applyCompletion(runOf(applyDispatch({}, dispatch('a'), newAgent(dispatch('a'), {}), 1)), 'a', done)
    expect(usageToLog(run, 'a')?.id).toBe('a')
    expect(usageToLog(run, 'nope')).toBeUndefined()
    const marked = markUsageLogged(run, 'a', 500)
    expect(marked.agents.a?.usageLoggedAt).toBe(500)
    expect(usageToLog(marked, 'a')).toBeUndefined()
    expect(markUsageLogged(run, 'nope', 500)).toBe(run)
  })

  test('withRun changes one run and ignores an unknown id', async () => {
    const runs = applyDispatch({}, dispatch('a'), newAgent(dispatch('a'), {}), 1)
    expect(withRun(runs, RUN, r => ({ ...r, verdict: 'v' }))[RUN]?.verdict).toBe('v')
    expect(withRun(runs, 'other', r => ({ ...r, verdict: 'v' }))).toBe(runs)
  })
})
