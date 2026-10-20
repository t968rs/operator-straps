import { describe, expect, test } from 'claude-code/testing'

import type { Run } from '../types'
import { readReview } from './bubbles'
import { identify, parseReturnBlock } from './contract'
import {
  applyCompletion, applyDispatch, bandText, currentRunId, fixerBubbledIds, markLogged, markUsageLogged, newAgent,
  planPhase, prReviewBubbled, recoverReviewers, reviewersSettled, reviewersToLog, settle, usageToLog,
  withDiskPhase,
} from './runs'

const RUN = 'pr1526_20261009T120000Z'
/** The pr-team runtime base under the harness default state_dir. */
const BASE = '.claude/state/harness/pr-team/_runtime'
const slot = (id: string, role = 'reviewer') =>
  identify('x', `AGENT_ID: ${id}\nAGENT_ROLE: ${role}\nRUN_ID: ${RUN}`, BASE)!
const done = (counts: string) =>
  parseReturnBlock(`---\nSIGNAL: DONE\nAGENT_ROLE: reviewer\nCOUNTS: ${counts}\nOUTPUT: o\n---`)
const ZERO = 'findings=0 critical=0 important=0 minor=0'

const twoReviewers = (): Run => {
  let runs: Record<string, Run> = {}
  for (const id of ['r1', 'r2']) runs = applyDispatch(runs, slot(id), newAgent(slot(id), { model: 'opus' }), 100)
  return runs[RUN]!
}

describe('usage claims', () => {
  const finished = (): Run => applyCompletion(twoReviewers(), 'r1', {
    tokens: 1, toolUses: 1, durationMs: 1, model: null, block: done(ZERO), isMeasured: true, ending: 'ok',
  })

  test('an agent with a signal is claimable once; a running or unknown one never', async () => {
    const run = finished()
    expect(usageToLog(run, 'r1')?.id).toBe('r1')
    expect(usageToLog(run, 'r2')).toBeUndefined()
    expect(usageToLog(run, 'nope')).toBeUndefined()
    const marked = markUsageLogged(run, 'r1', 500)
    expect(marked.agents.r1?.usageLoggedAt).toBe(500)
    expect(marked.agents.r2?.usageLoggedAt).toBeNull()
    expect(usageToLog(marked, 'r1')).toBeUndefined()
  })

  test('dispatching the same id again starts a fresh, unclaimed agent', async () => {
    const marked = markUsageLogged(finished(), 'r1', 500)
    const again = applyDispatch({ [RUN]: marked }, slot('r1'), newAgent(slot('r1'), { subagentType: 't' }), 600)
    expect(again[RUN]?.agents.r1).toMatchObject({ usageLoggedAt: null, signal: null, subagentType: 't' })
  })
})

describe('dispatch and completion', () => {
  test('first dispatch creates the run; agents accumulate', async () => {
    const run = twoReviewers()
    expect(run.pr).toBe(1526)
    expect(run.phase).toBe('review')
    expect(run.startedAt).toBe(100)
    expect(run.runtimeDir).toBe(`${BASE}/${RUN}`)
    expect(Object.keys(run.agents)).toEqual(['r1', 'r2'])
    expect(run.agents.r1?.model).toBe('opus')
  })

  test('completion folds usage, signal and counts; usage accumulates', async () => {
    const c = {
      tokens: 10, toolUses: 2, durationMs: 1500, model: 'claude-opus-5-5',
      block: done('findings=1 critical=1 important=0 minor=0'), isMeasured: true, ending: 'ok' as const,
    }
    const run = applyCompletion(applyCompletion(twoReviewers(), 'r1', c), 'r1', { ...c, block: undefined })
    expect(run.agents.r1).toMatchObject({
      tokens: 20, toolUses: 4, durationMs: 3000, model: 'claude-opus-5-5', isMeasured: true, signal: 'NO_BLOCK',
    })
    expect(run.agents.r1?.counts?.critical).toBe(1)
  })

  test('closer DONE sets the bubbled set and ends the run', async () => {
    let runs: Record<string, Run> = { [RUN]: twoReviewers() }
    const closer = identify('pr-team-fixer', `MODE=CLOSEOUT\nRUN_ID=${RUN}`, BASE)!
    runs = applyDispatch(runs, closer, newAgent(closer, {}), 200)
    const block = parseReturnBlock('---\nSIGNAL: DONE\nAGENT_ROLE: fixer\nFIXED: C1\nBUBBLED: I2,M3\nEDITED: 1\nOUTPUT: o\n---')
    const run = applyCompletion(runs[RUN]!, 'closer', {
      tokens: 0, toolUses: 0, durationMs: 0, model: null, block, isMeasured: true, ending: 'ok' as const,
    })
    expect([run.phase, run.bubbled, run.bubbledFrom]).toEqual(['done', ['I2', 'M3'], 'closer'])
  })
})

describe('settle', () => {
  const doc = (over: Record<string, unknown>) =>
    readReview(JSON.stringify({ issues: { important: [{ id: 'I2' }] }, ...over }))

  test('verdict copied; sidecar bubbles win over review bubbles; closer wins over both', async () => {
    const run = settle(twoReviewers(), doc({ verdict: 'READY TO MERGE', bubbles: ['I9'] }), ['I2'])
    expect([run.verdict, run.bubbled, run.bubbledFrom]).toEqual(['READY TO MERGE', ['I2'], 'bubble_ups'])
    const closed = settle({ ...run, bubbled: ['M1'], bubbledFrom: 'closer' }, doc({}), ['I2'])
    expect(closed.bubbled).toEqual(['M1'])
  })

  test('pr-review takes bubbles from the review; all dispositioned ends the run', async () => {
    const run: Run = { ...twoReviewers(), skill: 'pr-review', runtimeDir: null }
    expect(settle(run, doc({ bubbles: ['I2'] }), null)).toMatchObject({
      bubbled: ['I2'], bubbledFrom: 'review_json', phase: 'done',
    })
    expect(settle(run, undefined, null)).toEqual(run)
  })
})

describe('logging bookkeeping', () => {
  test('settled only when every reviewer returned; logged agents leave the queue', async () => {
    const c = { tokens: 1, toolUses: 1, durationMs: 1, model: null, block: done(ZERO), isMeasured: true, ending: 'ok' as const }
    const one = applyCompletion(twoReviewers(), 'r1', c)
    expect(reviewersSettled(one)).toBe(false)
    const both = applyCompletion(one, 'r2', c)
    expect(reviewersSettled(both)).toBe(true)
    expect(reviewersToLog(both).map(a => a.id)).toEqual(['r1', 'r2'])
    expect(reviewersToLog(markLogged(both, ['r1'], 5)).map(a => a.id)).toEqual(['r2'])
  })

  test('recoverReviewers joins plan agents with reviewer terminals rows', async () => {
    const plan = JSON.stringify({ agents: [{ id: 'r1', model: 'opus', effort: 'high' }, { id: 'r2', model: 'inherit' }] })
    const terminals = [
      JSON.stringify({
        agent_id: 'r1', agent_role: 'reviewer', signal: 'DONE', counts: { findings: 2, critical: 0, important: 1, minor: 1 },
      }),
      'not json',
      JSON.stringify({ agent_id: 'f1', agent_role: 'fixer', signal: 'DONE' }),
    ].join('\n')
    const [r1, ...rest] = recoverReviewers(plan, terminals)
    expect(rest).toEqual([])
    expect(r1).toMatchObject({
      id: 'r1', role: 'reviewer', model: 'opus', effort: 'high', signal: 'DONE', isMeasured: false, tokens: 0,
    })
    expect(r1?.counts?.findings).toBe(2)
    expect(recoverReviewers('junk', terminals)).toEqual([])
  })
})

describe('bandText', () => {
  test('nothing to show', async () => {
    expect(bandText({ run: null, phase5: [], missing: [] })).toBeUndefined()
    expect(bandText({ run: { ...twoReviewers(), phase: 'done' }, phase5: [], missing: [] })).toBeUndefined()
  })

  test('reviewer progress, Phase 5, bubbled count and missing ids', async () => {
    expect(bandText({ run: twoReviewers(), phase5: [], missing: [] })).toBe('PR #1526 · reviewers 0/2')
    const fixing: Run = { ...twoReviewers(), phase: 'fix', bubbled: ['I2', 'M3', 'M4'] }
    expect(bandText({ run: fixing, phase5: ['1526'], missing: ['M4'] })).toBe(
      'PR #1526 · fixers 0/0 · Phase 5 pending · 3 bubbled · bubbles[] missing M4',
    )
    expect(bandText({ run: null, phase5: ['1400', '1526'], missing: [] })).toBe(
      'PR #1400 · Phase 5 pending | PR #1526 · Phase 5 pending',
    )
  })

  test('a hot sentinel follows the phase instead of replacing it; fixer progress shows', async () => {
    let runs: Record<string, Run> = { [RUN]: twoReviewers() }
    for (const id of ['w1_fix_1', 'w1_fix_2']) runs = applyDispatch(runs, slot(id, 'fixer'), newAgent(slot(id, 'fixer'), {}), 300)
    const c = { tokens: 0, toolUses: 0, durationMs: 0, model: null, block: undefined, isMeasured: true, ending: 'ok' as const }
    const fixing = applyCompletion(runs[RUN]!, 'w1_fix_1', c)
    expect(bandText({ run: fixing, phase5: ['1526'], missing: [] })).toBe('PR #1526 · fixers 1/2 · Phase 5 pending')
    expect(bandText({ run: fixing, phase5: [], missing: [] })).toBe('PR #1526 · fixers 1/2')
    const at = (phase: Run['phase']) => bandText({ run: { ...fixing, phase }, phase5: ['1526'], missing: [] })
    expect(at('consolidate')).toBe('PR #1526 · consolidating · Phase 5 pending')
    expect(at('fix-plan')).toBe('PR #1526 · fix planning · Phase 5 pending')
    expect(at('done')).toBe('PR #1526 · Phase 5 pending')
  })
})

describe('pr-review run directory', () => {
  const prReview = (): Run => ({ ...twoReviewers(), skill: 'pr-review', runtimeDir: null })
  const review = (over: Record<string, unknown>) =>
    readReview(JSON.stringify({ issues: { critical: [{ id: 'C1' }], important: [{ id: 'I2' }, { id: 'I9' }] }, ...over }))

  test('bubbled = review bubbles plus fixer bubbles not closed by their latest resolution', async () => {
    const doc = review({
      bubbles: ['I2'],
      post_review_resolutions: [{ id: 'C1', status: 'RESOLVED' }, { id: 'M5', status: 'RESOLVED' }, { id: 'M5', status: 'UNRESOLVED' }],
    })
    expect(settle(prReview(), doc, null, ['I9', 'C1', 'I2', 'M5'])).toMatchObject({
      bubbled: ['I2', 'I9', 'M5'], bubbledFrom: 'review_json',
    })
    expect(prReviewBubbled(doc, [])).toEqual(['I2'])
  })

  test('fixer bubbles count before the review JSON is read; pr-team ignores them', async () => {
    expect(settle(prReview(), undefined, null, ['I9']).bubbled).toEqual(['I9'])
    expect(settle(twoReviewers(), undefined, null, ['I9'])).toEqual(twoReviewers())
    const doc = review({ bubbles: ['I2'] })
    expect(settle(twoReviewers(), doc, null, ['I9']).bubbled).toEqual([])
  })

  test('the plan.json phase wins over the dispatch phase; absent or unknown keeps it', async () => {
    expect(withDiskPhase(prReview(), 'fix-plan').phase).toBe('fix-plan')
    expect(withDiskPhase(prReview(), undefined).phase).toBe('review')
    expect(planPhase(JSON.stringify({ run_id: RUN, pr: 1526, phase: 'consolidate' }))).toBe('consolidate')
    expect(planPhase(JSON.stringify({ run_id: RUN, pr: 1526 }))).toBeUndefined()
    expect(planPhase(JSON.stringify({ phase: 'toString' }))).toBeUndefined()
    expect(planPhase(JSON.stringify({ phase: 'merging' }))).toBeUndefined()
    expect(planPhase('{oops')).toBeUndefined()
  })

  test('current run id and fixer report parsing tolerate junk', async () => {
    expect(currentRunId(`${RUN}\r\n`)).toBe(RUN)
    expect(currentRunId('  \n')).toBeUndefined()
    expect(currentRunId(undefined)).toBeUndefined()
    const reports = [
      JSON.stringify({ fixer: 'w1_fix_1', fixed: [{ id: 'C1' }], bubbled: [{ id: 'I9', classification: 'out_of_scope', reason: 'r' }] }),
      'not json',
      JSON.stringify({ fixer: 'w1_fix_2', bubbled: [{ id: 'M12' }, { id: 3 }, 'x', { id: 'I9' }] }),
      JSON.stringify({ fixer: 'w1_fix_3', bubbled: null }),
    ]
    expect(fixerBubbledIds(reports)).toEqual(['I9', 'M12'])
  })
})
