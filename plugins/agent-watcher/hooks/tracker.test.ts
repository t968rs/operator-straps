import type { Engine } from 'claude-code/testing'
import type { On, ProcessRunResult } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import type { Run } from '../types'
import { DEFINED_AGENTS, parseReturnBlock, type Dispatch } from './core/contract'
import type { Io, Layer } from './core/layer'
import { applyCompletion, applyDispatch, newAgent } from './core/runs'
import {
  completeLayer, contextFor, countsFor, foldInto, logUsage, settleLayers, STEP_TALLY_CAP, stopReasonOf,
} from './core/tracker'
import { OWNER_NOTE, prReviewLayer } from './layers/pr-review/layer'

/**
 * Engine-level behavior of the tracker: what reaches the matrix and agent usage JSONL files, the
 * ownership marker and the Stop decision. Files, git, env and the Agent tool sit beneath the plugin, answered from memory.
 */

const ROOT = '/repo'
const RUN = 'pr1526_20261009T120000Z'
/** The harness defaults: state_dir `.claude/state/harness`, matrix_path under `docs/_harness`. */
const DIR = `.claude/state/harness/pr-team/_runtime/${RUN}`
const SENTINELS = `${ROOT}/.claude/state/harness/pr-review`
const MATRIX = `${ROOT}/docs/_harness/pr_review_invocation_test_matrix.jsonl`
const USAGE = `${ROOT}/docs/_harness/agent_usage.jsonl`
const REVIEW = `${ROOT}/docs/PR_REVIEWS/1526_watch.json`
const HARNESS = `${ROOT}/.claude/harness.json`
const PR_REVIEW_PY = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py"'
const SHA = '0123456789abcdef0123456789abcdef01234567'
const NOW = 1_800_000_000_000
const ZERO = 'findings=0 critical=0 important=0 minor=0'

type Files = Map<string, { text: string; mtimeMs: number }>
/** `unreadable`: paths that exist but whose read is refused (a lock, an OS refusal, over 4 MiB). */
type Seen = {
  files: Files; unreadable: Set<string>; toasts: string[]; agentCalls: number; git: string[][]
  /** The usage a model request answers with, by `<turnId>/<index>`; none answers null. */
  stepUsage: Map<string, Record<string, unknown>>
}
/** `config`: the `.claude/harness.json` text at ROOT (null: no file); `originHead`: symbolic-ref's answer. */
type Opts = { config?: string | null; originHead?: string }

const ran = (stdout: string): ProcessRunResult => ({
  exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})
const reviewerPrompt = (id: string, extra = ''): string =>
  `AGENT_ID: ${id}\nAGENT_ROLE: reviewer\nRUN_ID: ${RUN}\n${extra}`
const doneBlock = (counts: string): string =>
  `prose\n---\nSIGNAL: DONE\nAGENT_ROLE: reviewer\nCOUNTS: ${counts}\nOUTPUT: o\n---`
const completed = (text: string, model = 'claude-opus-5-5') => ({
  result: {
    status: 'completed', agentId: 'loop-x', totalTokens: 1000, totalToolUseCount: 7, totalDurationMs: 2500,
    resolvedModel: model, content: [{ type: 'text', text }], prompt: '',
  },
  text,
})

/** A host path as the test keys it: Windows hosts hand the hooks `C:\repo\...` for `/repo/...`. */
const slash = (p: string): string => p.replace(/\\/g, '/').replace(/^[A-Za-z]:/, '')

/** A directory's entries: its own files, and one `dir` entry per subfolder that holds a file. */
const listed = (files: Files, dir: string) => {
  const prefix = `${dir}/`
  const entries = new Map<string, { kind: 'file' | 'dir'; mtimeMs: number }>()
  for (const [p, f] of files) {
    if (!p.startsWith(prefix)) continue
    const [name = '', ...rest] = p.slice(prefix.length).split('/')
    entries.set(name, rest.length === 0 ? { kind: 'file', mtimeMs: f.mtimeMs } : { kind: 'dir', mtimeMs: 0 })
  }
  return [...entries].map(([name, x]) => ({ name, kind: x.kind, size: 1, mtimeMs: x.mtimeMs, isLink: false }))
}

/** git's answer: ROOT as top level, the merge-base SHA, `origin/HEAD` (exit 1 when unset), else the branch. */
const gitAnswer = (argv: readonly string[], opts: Opts): ProcessRunResult => {
  if (argv.includes('--show-toplevel')) return ran(`${ROOT}\n`)
  if (argv.includes('merge-base')) return ran(`${SHA}\n`)
  if (!argv.includes('symbolic-ref')) return ran('dev\n')
  return opts.originHead === undefined ? { ...ran(''), exitCode: 1 } : ran(`${opts.originHead}\n`)
}

/** Files, clock, env, git and the Agent tool beneath the plugin. */
const world = (on: On, agentAnswer: (prompt: string) => unknown, opts: Opts = {}): Seen => {
  const seen: Seen = { files: new Map(), unreadable: new Set(), toasts: [], agentCalls: 0, git: [], stepUsage: new Map() }
  const config = opts.config === undefined ? '{}' : opts.config
  if (config !== null) seen.files.set(HARNESS, { text: config, mtimeMs: 1 })
  mock.env(on, { CLAUDE_PROJECT_DIR: ROOT })
  mock.clock(on, { now: NOW })
  on('session.cwd', () => ({ value: ROOT }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('fs.read', (_$, e) => {
    const path = slash(e.path)
    if (seen.unreadable.has(path)) return { deny: `EBUSY ${e.path}` }
    const f = seen.files.get(path)
    return f === undefined ? { deny: `ENOENT ${e.path}` } : { value: f.text }
  })
  on('fs.exists', (_$, e) => ({ value: seen.files.has(slash(e.path)) }))
  on('fs.write', (_$, e) => {
    seen.files.set(slash(e.path), { text: e.text, mtimeMs: NOW })
    return { value: undefined }
  })
  on('fs.stat', (_$, e) => ({ deny: `ENOENT ${e.path}` }))
  on('fs.list', (_$, e) => ({ value: listed(seen.files, slash(e.path)) }))
  on('process.run', (_$, e) => {
    seen.git.push([...e.argv])
    return { value: gitAnswer(e.argv, opts) }
  })
  on('ui.toast', (_$, e) => {
    seen.toasts.push(e.text)
    return { value: undefined }
  })
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('turn.step', async function* (_$, e) {
    yield { kind: 'text', index: 0, text: 'hi' } as never
    const usage = seen.stepUsage.get(`${e.turnId}/${e.index}`) ?? null
    return { turnId: e.turnId, index: e.index, answer: 'hi', toolUses: [], stopReason: 'end_turn', usage } as never
  })
  on('tool.call', { tool: 'Agent' }, (_$, e) => {
    seen.agentCalls++
    return agentAnswer(e.prompt) as never
  })
  return seen
}

const dispatch = ($: Engine, prompt: string, subagentType = 'superpowers:code-reviewer') =>
  $.tool.call({ tool: 'Agent', description: 'r', prompt, subagent_type: subagentType, model: 'opus' })

/** A usage whose four counts total `n`. */
const usageOf = (n: number) => ({
  input_tokens: n - 3, output_tokens: 1, cache_read_input_tokens: 1, cache_creation_input_tokens: 1, model: 'claude-opus-5-5',
})

/** A stream read to its end: its chunks and the value it returned. */
const drain = async <C, R>(s: AsyncGenerator<C, R>): Promise<{ chunks: C[]; result: R }> => {
  const chunks: C[] = []
  for (;;) {
    const r = await s.next()
    if (r.done === true) return { chunks, result: r.value }
    chunks.push(r.value)
  }
}

/**
 * Model requests in a loop (`agentId`; undefined is the main loop), one per total (null: a request that
 * reported no usage), each stream read to its end.
 */
const steps = async ($: Engine, seen: Seen, agentId: string | undefined, ...totals: (number | null)[]): Promise<void> => {
  for (const [index, n] of totals.entries()) {
    const turnId = `s-${agentId ?? 'main'}`
    if (n === null) seen.stepUsage.delete(`${turnId}/${index}`)
    else seen.stepUsage.set(`${turnId}/${index}`, usageOf(n))
    await drain($.turn.step({
      turnId, index, model: 'claude-opus-5-5', messageCount: 1, ...(agentId === undefined ? {} : { agentId }),
    }))
  }
}

const mainTurnEnd = ($: Engine, turnId: string) =>
  $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId, reason: 'answer' })

const writeReview = (seen: Seen, body: Record<string, unknown>): void => {
  seen.files.set(REVIEW, { text: JSON.stringify(body), mtimeMs: NOW + 1 })
}

const jsonlRows = (seen: Seen, path: string): Record<string, unknown>[] =>
  (seen.files.get(path)?.text ?? '').split('\n').filter(Boolean).map(l => JSON.parse(l) as Record<string, unknown>)
const matrixRows = (seen: Seen): Record<string, unknown>[] => jsonlRows(seen, MATRIX)
const usageRows = (seen: Seen): Record<string, unknown>[] => jsonlRows(seen, USAGE)

describe('Agent hook', () => {
  test('a built-in dispatch passes through untouched and logs a generic row', async ($, on) => {
    const seen = world(on, () => completed('hi'))
    const r = await dispatch($, 'find files', 'Explore')
    expect(r.context ?? []).toEqual([])
    expect(seen.agentCalls).toBe(1)
    expect(seen.files.has(MATRIX)).toBe(false)
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({
      skill: 'standalone', role: 'other', agent_id: 'Explore', subagent_type: 'Explore', pr: null, signal: 'NO_BLOCK',
    })
    expect('fields' in (usageRows(seen)[0] ?? {})).toBe(false)
  })

  test('pr-review reviewer results carry the ownership note', async ($, on) => {
    world(on, () => completed(doneBlock(ZERO)))
    const r = await dispatch($, reviewerPrompt('runtime', 'PR: 1526'))
    expect(r.context ?? []).toContain(OWNER_NOTE)
  })

  test('pr-review fixer results carry no ownership note', async ($, on) => {
    world(on, () => completed('fixes applied'))
    const r = await dispatch($, `AGENT_ID: w1_fix_1\nAGENT_ROLE: fixer\nRUN_ID: ${RUN}\nPR: 1526`, 'pr-fixer')
    expect(r.context ?? []).not.toContain(OWNER_NOTE)
  })

  test('no ownership note when the run could not be recorded', async ($, on) => {
    world(on, () => completed(doneBlock(ZERO)))
    on('state.set', (_$, e, next) =>
      e.plugin === 'agent-watcher' && e.key === 'runs' ? { deny: 'state store full' } : next(e),
    )
    const r = await dispatch($, reviewerPrompt('runtime', 'PR: 1526'))
    expect(r.context ?? []).not.toContain(OWNER_NOTE)
  })
})

describe('matrix rows', () => {
  test('one measured row per reviewer once the review has a verdict; attempted once', async ($, on) => {
    const seen = world(on, p => completed(doneBlock(p.includes('r1') ? 'findings=2 critical=1 important=1 minor=0' : ZERO)))
    await steps($, seen, 'loop-x', 1000)
    await dispatch($, reviewerPrompt('r1'))
    await steps($, seen, 'loop-x', 1000)
    await dispatch($, reviewerPrompt('r2'))
    expect(seen.files.has(MATRIX)).toBe(false)
    writeReview(seen, { verdict: 'NOT READY TO MERGE: 1 critical', issues: { critical: [{ id: 'C1' }] } })
    await mainTurnEnd($, 't1')
    const rows = matrixRows(seen)
    expect(rows.map(r => r.cell)).toEqual(['pr1526_r1', 'pr1526_r2'])
    expect(rows[0]).toMatchObject({
      tokens: 1000, tool_uses: 7, duration_s: 2.5, model_family: 'opus', C_count: 1, verdict_prefix: 'NOT READY TO MERGE',
    })
    expect(rows[0]?.dev_commit).toBe(`${SHA} -- dev (agent-watcher auto)`)
    expect(rows[1]).toMatchObject({ tokens: 1000 })
    await mainTurnEnd($, 't2')
    expect(matrixRows(seen)).toHaveLength(2)
  })

  test('overlapping refreshes after the verdict append one row per reviewer', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '', interrupted: false } }) as never)
    await dispatch($, reviewerPrompt('r1'))
    await dispatch($, reviewerPrompt('r2'))
    writeReview(seen, { verdict: 'READY TO MERGE', issues: {} })
    const script = (sub: string) =>
      $.tool.call({ tool: 'Bash', command: `${PR_REVIEW_PY} ${sub}`, description: 'd' } as never)
    await Promise.all([script('waves 1526'), script('bubbles 1526'), script('closeout 1526'), mainTurnEnd($, 't1')])
    expect(matrixRows(seen).map(r => r.cell)).toEqual(['pr1526_r1', 'pr1526_r2'])
  })

  test('background launch: usage comes from the subagent loop turn', async ($, on) => {
    const seen = world(on, () => ({
      result: { status: 'async_launched', agentId: 'loop-1', description: 'r', prompt: '', outputFile: 'f', resolvedModel: 'claude-sonnet-5-5' },
      text: 'launched',
    }))
    on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '', interrupted: false } }) as never)
    await dispatch($, reviewerPrompt('r1'))
    await $.tool.call({ tool: 'Bash', command: 'ls', agentId: 'loop-1' } as never)
    await $.turn.complete({
      answer: doneBlock(ZERO), durationMs: 4000, isAborted: false, turnId: 'tA', reason: 'answer', agentId: 'loop-1',
      usage: { input_tokens: 10, output_tokens: 20, cache_read_input_tokens: 30, cache_creation_input_tokens: 40, model: 'claude-sonnet-5-5' },
    })
    writeReview(seen, { verdict: 'READY TO MERGE', issues: {} })
    await mainTurnEnd($, 'tB')
    expect(matrixRows(seen)[0]).toMatchObject({ tokens: 100, tool_uses: 1, duration_s: 4, model_family: 'sonnet' })
  })

  test('an invalid row is not appended and is toasted', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO), 'claude-fable-5-1'))
    await $.tool.call({ tool: 'Agent', description: 'r', prompt: reviewerPrompt('r1'), subagent_type: 'x' })
    writeReview(seen, { verdict: 'READY TO MERGE', issues: {} })
    await mainTurnEnd($, 't')
    expect(matrixRows(seen)).toEqual([])
    expect(seen.toasts.join('\n')).toContain('model_family')
  })

  test('rows append after the rows already in the matrix', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    seen.files.set(MATRIX, { text: '{"cell":"old_row"}\n', mtimeMs: 1 })
    await dispatch($, reviewerPrompt('r1'))
    writeReview(seen, { verdict: 'READY TO MERGE', issues: {} })
    await mainTurnEnd($, 't')
    expect(matrixRows(seen).map(r => r.cell)).toEqual(['old_row', 'pr1526_r1'])
  })

  test('an existing matrix that cannot be read is left untouched and the rows are toasted', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    seen.files.set(MATRIX, { text: '{"cell":"old_row"}\n', mtimeMs: 1 })
    seen.unreadable.add(MATRIX)
    await dispatch($, reviewerPrompt('r1'))
    writeReview(seen, { verdict: 'READY TO MERGE', issues: {} })
    await mainTurnEnd($, 't')
    expect(seen.files.get(MATRIX)?.text).toBe('{"cell":"old_row"}\n')
    expect(seen.toasts.join('\n')).toContain('matrix unreadable')
  })

  test('orchestrator PLAN writes the pending ownership marker', async ($, on) => {
    const seen = world(on, () => completed('---\nSIGNAL: DONE\nAGENT_ROLE: reviewer\nOUTPUT: plan.json\n---'))
    await dispatch($, `MODE=PLAN\nPR_NUMBER=1526\nRUN_ID=${RUN}\nRUNTIME_DIR=${DIR}`, 'pr-team-orchestrator')
    expect(seen.files.get(`${ROOT}/${DIR}/.matrix_owner`)?.text).toBe('pending\n')
  })
})

describe('agent usage rows', () => {
  const PR_DIR = `${ROOT}/docs/_scratch/pr_review/1526`
  const fixerPrompt = (id: string) => `AGENT_ID: ${id}\nAGENT_ROLE: fixer\nRUN_ID: ${RUN}\nPR: 1526`
  const fixerBlock = (fixed: string, bubbled: string, edited: number) =>
    `---\nSIGNAL: DONE\nAGENT_ROLE: fixer\nFIXED: ${fixed}\nBUBBLED: ${bubbled}\nEDITED: ${edited}\nOUTPUT: o\n---`
  const launchedAs = (agentId: string) => ({
    result: { status: 'async_launched', agentId, description: 'r', prompt: '', outputFile: 'f', resolvedModel: 'claude-sonnet-5-5' },
    text: 'launched',
  })
  const loopEnd = ($: Engine, agentId: string, usage?: Record<string, unknown>) =>
    $.turn.complete({
      answer: doneBlock(ZERO), durationMs: 4000, isAborted: false, turnId: `t-${agentId}`, reason: 'answer', agentId,
      ...(usage === undefined ? {} : { usage }),
    } as never)

  test('a reviewer row is written on return, before any verdict', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    await steps($, seen, 'loop-x', 1000)
    await dispatch($, reviewerPrompt('r1', 'PR: 1526'), 'harness:pr-reviewer')
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({
      run_id: RUN, pr: 1526, skill: 'pr-review', role: 'reviewer', agent_id: 'r1', subagent_type: 'harness:pr-reviewer',
      model: 'claude-opus-5-5', model_family: 'opus', tokens: 1000, context_tokens: 1000, requests: 1, tool_uses: 7, duration_s: 2.5,
      signal: 'DONE',
    })
    expect(seen.files.has(MATRIX)).toBe(false)
  })

  test('pr-review fixer counts come from waves.json and its report', async ($, on) => {
    const seen = world(on, () => completed('---\nSIGNAL: FAIL\nAGENT_ROLE: fixer\nREASON: r\n---'))
    seen.files.set(`${PR_DIR}/current`, { text: `${RUN}\n`, mtimeMs: NOW })
    const waves = { waves: [[{ id: 'w1_fix_1', issue_ids: ['M1', 'I2', 'C3'] }]] }
    seen.files.set(`${PR_DIR}/${RUN}/waves.json`, { text: JSON.stringify(waves), mtimeMs: NOW })
    const report = {
      fixer: 'w1_fix_1', fixed: [{ id: 'M1', what: 'w', files: ['a.py', 'b.py'] }],
      bubbled: [{ id: 'I2', classification: 'out_of_scope', reason: 'r' }],
    }
    seen.files.set(`${PR_DIR}/${RUN}/fixes/w1_fix_1.json`, { text: JSON.stringify(report), mtimeMs: NOW })
    await dispatch($, fixerPrompt('w1_fix_1'), 'harness:pr-fixer')
    expect(usageRows(seen)[0]).toMatchObject({
      role: 'fixer', signal: 'FAIL', issues_assigned: 3, issues_fixed: 1, issues_bubbled: 1, files_touched: 2,
    })
  })

  test('a pr-review fixer with no report falls back to its block, then null', async ($, on) => {
    const seen = world(on, () => completed(fixerBlock('M1', '', 1)))
    await dispatch($, fixerPrompt('w1_fix_1'), 'harness:pr-fixer')
    expect(usageRows(seen)[0]).toMatchObject({
      issues_assigned: null, issues_fixed: 1, issues_bubbled: 0, files_touched: 1,
    })
  })

  test('pr-team fixer and closer rows count from their blocks; orchestrator rows carry no counts', async ($, on) => {
    const seen = world(on, p =>
      completed(p.includes('MODE=PLAN') ? '---\nSIGNAL: DONE\nAGENT_ROLE: reviewer\nOUTPUT: plan.json\n---'
        : p.includes('CLOSEOUT') ? fixerBlock('C1,I3', 'M2', 1) : fixerBlock('C1,I3', 'M2', 4)))
    await dispatch($, `MODE=PLAN\nPR_NUMBER=1526\nRUN_ID=${RUN}\nRUNTIME_DIR=${DIR}`, 'pr-team-orchestrator')
    await dispatch($, `AGENT_ID: f1\nAGENT_ROLE: fixer\nRUN_ID: ${RUN}\nOUTPUT_FILE: ${DIR}/outputs/f1.json`, 'pr-fixer')
    await dispatch($, `MODE=CLOSEOUT\nPR_NUMBER=1526\nRUN_ID=${RUN}\nRUNTIME_DIR=${DIR}`, 'pr-team-fixer')
    const [plan, fixer, closer] = usageRows(seen)
    expect(plan).toMatchObject({ skill: 'pr-team', role: 'orchestrator', agent_id: 'orchestrator_plan' })
    expect('issues_fixed' in (plan ?? {})).toBe(false)
    expect(fixer).toMatchObject({
      skill: 'pr-team', role: 'fixer', issues_assigned: null, issues_fixed: 2, issues_bubbled: 1, files_touched: 4,
    })
    expect(closer).toMatchObject({ role: 'closer', issues_fixed: 2, issues_bubbled: 1, files_touched: 1 })
  })

  test('a roast slot is a reviewer row with its subagent type', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    await dispatch($, reviewerPrompt('r9_roast', `OUTPUT_FILE: ${DIR}/outputs/r9_roast.json`), 'harness:roast-my-code')
    expect(usageRows(seen)[0]).toMatchObject({
      skill: 'pr-team', role: 'reviewer', agent_id: 'r9_roast', subagent_type: 'harness:roast-my-code',
    })
  })

  test('background launch: the row is written when the loop turn ends', async ($, on) => {
    const seen = world(on, p => launchedAs(p.includes('AGENT_ID: r1') ? 'loop-1' : 'loop-2'))
    on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '', interrupted: false } }) as never)
    await dispatch($, reviewerPrompt('r1'))
    await dispatch($, reviewerPrompt('r2'))
    expect(seen.files.has(USAGE)).toBe(false)
    await $.tool.call({ tool: 'Bash', command: 'ls', agentId: 'loop-1' } as never)
    await loopEnd($, 'loop-1', {
      input_tokens: 10, output_tokens: 20, cache_read_input_tokens: 30, cache_creation_input_tokens: 40, model: 'claude-sonnet-5-5',
    })
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({ agent_id: 'r1', tokens: 100, tool_uses: 1, duration_s: 4, model_family: 'sonnet' })
    await loopEnd($, 'loop-2')
    expect(usageRows(seen)[1]).toMatchObject({ agent_id: 'r2', tokens: 0 })
    expect(String(usageRows(seen)[1]?.notes)).toMatch(/; usage not measured$/)
  })

  test('a background agent with no usage logs the model the engine launched, not the requested alias', async ($, on) => {
    const seen = world(on, () => launchedAs('loop-1'))
    await dispatch($, reviewerPrompt('r1'))
    await loopEnd($, 'loop-1')
    expect(usageRows(seen)[0]).toMatchObject({ model: 'claude-sonnet-5-5', model_family: 'sonnet', tokens: 0 })
  })

  test('a denied dispatch writes no row; an errored one logs ERROR', async ($, on) => {
    const seen = world(on, p => (p.includes('AGENT_ID: r1') ? { deny: 'no' } : { result: 'boom', isError: true, text: 'boom' }))
    await dispatch($, reviewerPrompt('r1'))
    expect(seen.files.has(USAGE)).toBe(false)
    await dispatch($, reviewerPrompt('r2'))
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({ agent_id: 'r2', signal: 'ERROR', tokens: 0 })
    expect(String(usageRows(seen)[0]?.notes)).toMatch(/; usage not measured; agent errored$/)
  })

  test('a model with no family token logs as unknown', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO), 'claude-fable-5-1'))
    await dispatch($, reviewerPrompt('r1'))
    expect(usageRows(seen)[0]).toMatchObject({ model: 'claude-fable-5-1', model_family: 'unknown' })
  })

  test('parallel fixer returns append one row each', async ($, on) => {
    const seen = world(on, () => completed(fixerBlock('M1', '', 1)))
    await Promise.all([
      dispatch($, fixerPrompt('w1_fix_1'), 'harness:pr-fixer'),
      dispatch($, fixerPrompt('w1_fix_2'), 'harness:pr-fixer'),
      mainTurnEnd($, 't1'),
    ])
    expect(usageRows(seen).map(r => r.agent_id).sort()).toEqual(['w1_fix_1', 'w1_fix_2'])
  })

  test('a retried dispatch is a second row', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    await dispatch($, reviewerPrompt('r1'))
    await dispatch($, reviewerPrompt('r1'))
    expect(usageRows(seen).map(r => r.agent_id)).toEqual(['r1', 'r1'])
  })

  test('rows append after existing rows; an unreadable usage file is untouched and toasted', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    seen.files.set(USAGE, { text: '{"run_id":"old"}\n', mtimeMs: 1 })
    await dispatch($, reviewerPrompt('r1'))
    expect(usageRows(seen).map(r => r.run_id)).toEqual(['old', RUN])
    const before = seen.files.get(USAGE)?.text
    seen.unreadable.add(USAGE)
    await dispatch($, reviewerPrompt('r2'))
    expect(seen.files.get(USAGE)?.text).toBe(before)
    expect(seen.toasts.join('\n')).toContain('usage log unreadable')
  })

  test('agent_usage_path comes from harness.json', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)), { config: JSON.stringify({ agent_usage_path: 'meta/u.jsonl' }) })
    await dispatch($, reviewerPrompt('r1'))
    expect(jsonlRows(seen, `${ROOT}/meta/u.jsonl`)).toHaveLength(1)
    expect(seen.files.has(USAGE)).toBe(false)
  })
})

describe('token figures: tokens summed over requests, context_tokens the last request', () => {
  const launchedAs = (agentId: string) => ({
    result: { status: 'async_launched', agentId, description: 'r', prompt: '', outputFile: 'f', resolvedModel: 'claude-sonnet-5-5' },
    text: 'launched',
  })
  /** A loop turn's end; a null total carries no usage. */
  const loopEnd = ($: Engine, agentId: string, total: number | null) =>
    $.turn.complete({
      answer: 'done', durationMs: 4000, isAborted: false, turnId: `t-${agentId}`, reason: 'answer', agentId,
      ...(total === null ? {} : { usage: usageOf(total) }),
    } as never)

  test('foreground: tokens sum the loop\'s requests, context_tokens is the result\'s totalTokens', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    await steps($, seen, undefined, 5000)
    await steps($, seen, 'loop-x', 300, 400)
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    expect(usageRows(seen)[0]).toMatchObject({ tokens: 700, context_tokens: 1000, requests: 2, notes: 'agent-watcher auto row; other NO_BLOCK' })
  })

  test('foreground with no request heard: tokens 0 and not measured; context_tokens still logged', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    expect(usageRows(seen)[0]).toMatchObject({ tokens: 0, context_tokens: 1000, requests: null })
    expect(String(usageRows(seen)[0]?.notes)).toMatch(/; usage not measured$/)
  })

  test('a loop\'s requests count once: the next dispatch of the same loop id starts from zero', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    await steps($, seen, 'loop-x', 400)
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    expect(usageRows(seen).map(r => r.tokens)).toEqual([400, 0])
  })

  test('background: tokens from the loop turn, context_tokens from its last request', async ($, on) => {
    const seen = world(on, () => launchedAs('loop-1'))
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    await steps($, seen, 'loop-1', 40, 60)
    await loopEnd($, 'loop-1', 100)
    expect(usageRows(seen)[0]).toMatchObject({ tokens: 100, context_tokens: 60, requests: 2 })
  })

  test('a request with no usage counts as a request; the last usage stands', async ($, on) => {
    const seen = world(on, () => launchedAs('loop-3'))
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    await steps($, seen, 'loop-3', 40, null)
    await loopEnd($, 'loop-3', 40)
    expect(usageRows(seen)[0]).toMatchObject({ tokens: 40, context_tokens: 40, requests: 2 })
  })

  test('background with no request heard: context_tokens null', async ($, on) => {
    const seen = world(on, () => launchedAs('loop-2'))
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    await loopEnd($, 'loop-2', 100)
    expect(usageRows(seen)[0]).toMatchObject({ tokens: 100, context_tokens: null, requests: null })
  })

  test('background loop turn with no usage: tokens fall back to the requests heard, measured', async ($, on) => {
    const seen = world(on, () => launchedAs('loop-4'))
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    await steps($, seen, 'loop-4', 40, 60)
    await loopEnd($, 'loop-4', null)
    expect(usageRows(seen)[0]).toMatchObject({ tokens: 100, context_tokens: 60, requests: 2 })
    expect(String(usageRows(seen)[0]?.notes)).not.toMatch(/usage not measured/)
  })

  test('an errored dispatch logs context_tokens null', async ($, on) => {
    const seen = world(on, () => ({ result: 'boom', isError: true, text: 'boom' }))
    await steps($, seen, 'loop-x', 500)
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    expect(usageRows(seen)[0]).toMatchObject({ signal: 'ERROR', tokens: 0, context_tokens: null, requests: null })
  })

  test('an errored result names no loop, so its tally stays until the cap evicts it', async ($, on) => {
    let calls = 0
    const seen = world(on, () => (calls++ === 0 ? { result: 'boom', isError: true, text: 'boom' } : completed('ok')))
    await steps($, seen, 'loop-x', 500)
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    for (let i = 0; i < STEP_TALLY_CAP; i++) await steps($, seen, `loop-evict-${i}`, 1)
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    expect(usageRows(seen)[1]).toMatchObject({ signal: 'NO_BLOCK', tokens: 0, requests: null })
  })

  test('the step hook passes every chunk and the result through unchanged', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    seen.stepUsage.set('p/0', usageOf(10))
    const { chunks, result } = await drain(
      $.turn.step({ turnId: 'p', index: 0, model: 'claude-opus-5-5', messageCount: 1, agentId: 'loop-p' }),
    )
    expect(chunks).toEqual([{ kind: 'text', index: 0, text: 'hi' }])
    expect(result).toEqual({
      turnId: 'p', index: 0, answer: 'hi', toolUses: [], stopReason: 'end_turn', usage: usageOf(10),
    })
  })
})

describe('standalone agent usage rows', () => {
  const launchedAs = (agentId: string) => ({
    result: { status: 'async_launched', agentId, description: 'r', prompt: '', outputFile: 'f', resolvedModel: 'claude-sonnet-5-5' },
    text: 'launched',
  })
  const run = ($: Engine, type: string, prompt = 'write the commit message') => dispatch($, prompt, type)

  test('a defined agent dispatched without a run header logs one standalone row', async ($, on) => {
    const seen = world(on, () => completed('commit written'), { config: '{}' })
    await steps($, seen, 'loop-x', 1000)
    await run($, 'harness:messenger')
    expect(usageRows(seen)).toHaveLength(1)
    expect(String(usageRows(seen)[0]?.run_id)).toMatch(/^standalone_20270115T080000Z_\d+$/)
    expect(usageRows(seen)[0]).toMatchObject({
      pr: null, skill: 'standalone', role: 'other', agent_id: 'messenger',
      subagent_type: 'harness:messenger', model: 'claude-opus-5-5', model_family: 'opus', effort: 'default',
      tokens: 1000, tool_uses: 7, duration_s: 2.5, signal: 'NO_BLOCK',
      notes: 'agent-watcher auto row; other NO_BLOCK',
    })
    expect(Object.keys(usageRows(seen)[0] ?? {})).not.toContain('issues_fixed')
    expect(seen.files.has(MATRIX)).toBe(false)
  })

  test('the row keeps the return block signal when the agent ends in one', async ($, on) => {
    const seen = world(on, () => completed('---\nSIGNAL: DONE\nOUTPUT: o\n---'))
    await run($, 'harness:todo-editor')
    expect(usageRows(seen)[0]).toMatchObject({ agent_id: 'todo-editor', signal: 'DONE' })
  })

  test('every defined agent type is tracked, each as its own run', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    for (const type of DEFINED_AGENTS) await run($, type)
    expect(usageRows(seen).map(r => r.subagent_type)).toEqual([...DEFINED_AGENTS])
    expect(new Set(usageRows(seen).map(r => r.run_id)).size).toBe(DEFINED_AGENTS.length)
  })

  test('parallel dispatches of one agent type get distinct run ids', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    await Promise.all([run($, 'harness:messenger'), run($, 'harness:messenger')])
    const ids = usageRows(seen).map(r => r.run_id)
    expect(ids).toHaveLength(2)
    expect(new Set(ids).size).toBe(2)
  })

  test('agents outside the defined set log a row each too (Decision D5)', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    for (const type of ['Explore', 'general-purpose', 'superpowers:code-reviewer']) await run($, type)
    expect(usageRows(seen).map(r => [r.agent_id, r.subagent_type])).toEqual([
      ['Explore', 'Explore'], ['general-purpose', 'general-purpose'], ['code-reviewer', 'superpowers:code-reviewer'],
    ])
  })

  test('a run header still wins: a defined agent in a pr-review run keeps its run and role', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    await dispatch($, reviewerPrompt('r1', 'PR: 1526'), 'harness:pr-reviewer')
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({ run_id: RUN, skill: 'pr-review', role: 'reviewer', pr: 1526 })
  })

  test('a header no layer claims is a generic row read from that header', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    await dispatch($, `AGENT_ID: a\nAGENT_ROLE: poet\nRUN_ID: ${RUN}`, 'harness:pr-reviewer')
    expect(usageRows(seen)[0]).toMatchObject({ skill: 'standalone', role: 'poet', agent_id: 'a', run_id: RUN })
    expect(seen.files.has(MATRIX)).toBe(false)
  })

  test('background launch: the row is written when the loop turn ends', async ($, on) => {
    const seen = world(on, () => launchedAs('loop-9'))
    on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '', interrupted: false } }) as never)
    await run($, 'harness:todo-editor')
    expect(seen.files.has(USAGE)).toBe(false)
    await $.tool.call({ tool: 'Bash', command: 'ls', agentId: 'loop-9' } as never)
    await $.turn.complete({
      answer: 'done', durationMs: 4000, isAborted: false, turnId: 't-9', reason: 'answer', agentId: 'loop-9',
      usage: { input_tokens: 10, output_tokens: 20, cache_read_input_tokens: 30, cache_creation_input_tokens: 40, model: 'claude-haiku-5-5' },
    } as never)
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({
      skill: 'standalone', agent_id: 'todo-editor', tokens: 100, tool_uses: 1, duration_s: 4, model_family: 'haiku',
    })
  })

  test('a denied dispatch writes no row; an errored one logs ERROR', async ($, on) => {
    const seen = world(on, p => (p.includes('denied') ? { deny: 'no' } : { result: 'boom', isError: true, text: 'boom' }))
    await run($, 'harness:messenger', 'denied')
    expect(seen.files.has(USAGE)).toBe(false)
    await run($, 'harness:messenger', 'errored')
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({ skill: 'standalone', signal: 'ERROR', tokens: 0 })
  })

  test('a finished standalone run leaves no state behind and never becomes the active run', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    const written: { runs: unknown[]; active: unknown[] } = { runs: [], active: [] }
    on('state.set', (_$, e, next) => {
      if (e.plugin === 'agent-watcher' && e.key === 'runs') written.runs.push(e.value)
      if (e.plugin === 'agent-watcher' && e.key === 'active') written.active.push(e.value)
      return next(e)
    })
    await run($, 'harness:messenger')
    expect(usageRows(seen)).toHaveLength(1)
    expect(Object.keys(written.runs.at(-1) as object)).toEqual([])
    expect(written.runs.some(r => Object.keys(r as object).length === 1)).toBe(true)
    expect(written.active).toEqual([])
  })

  test('outside a harness project nothing is logged', async ($, on) => {
    const seen = world(on, () => completed('ok'), { config: null })
    await run($, 'harness:messenger')
    expect(seen.files.has(USAGE)).toBe(false)
  })

  test('standalone dispatches do not disturb a pr-review run in flight', async ($, on) => {
    const seen = world(on, p => completed(p.includes('AGENT_ID') ? doneBlock(ZERO) : 'ok'))
    await dispatch($, reviewerPrompt('r1', 'PR: 1526'), 'harness:pr-reviewer')
    await run($, 'harness:messenger')
    writeReview(seen, { verdict: 'READY TO MERGE', issues: {} })
    await mainTurnEnd($, 't')
    expect(matrixRows(seen).map(r => r.cell)).toEqual(['pr1526_r1'])
    expect(usageRows(seen).map(r => r.skill)).toEqual(['pr-review', 'standalone'])
  })
})

describe('forked skill usage rows', () => {
  /** The agent list the engine answers: one entry per loop id, as `$.agent.list()` gives it. */
  type Listed = { id: string; type: string; description: string }
  /** Answers `agent.list` from `agents`; returns how many times it was asked. */
  const listing = (on: On, agents: Listed[]): { calls: number } => {
    const asked = { calls: 0 }
    on('agent.list', () => {
      asked.calls++
      return { value: agents.map(a => ({ ...a, status: 'running' })) } as never
    })
    return asked
  }
  const fork = (id: string, skill = 'harness:c-msg', type = 'harness:messenger'): Listed =>
    ({ id, type, description: `/${skill}` })
  const loopEnd = ($: Engine, agentId: string, answer = 'drafted') =>
    $.turn.complete({
      answer, durationMs: 4000, isAborted: false, turnId: `t-${agentId}`, reason: 'answer', agentId,
      usage: { input_tokens: 10, output_tokens: 20, cache_read_input_tokens: 30, cache_creation_input_tokens: 40, model: 'claude-sonnet-5-5' },
    } as never)
  const bash = (on: On) =>
    on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '', interrupted: false } }) as never)

  test('a forked skill loop logs one row under the skill it names', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    listing(on, [fork('loop-f')])
    bash(on)
    await steps($, seen, 'loop-f', 300, 500)
    await $.tool.call({ tool: 'Bash', command: 'git status', agentId: 'loop-f' } as never)
    expect(seen.files.has(USAGE)).toBe(false)
    await loopEnd($, 'loop-f')
    expect(usageRows(seen)).toHaveLength(1)
    expect(String(usageRows(seen)[0]?.run_id)).toMatch(/^standalone_\d{8}T\d{6}Z_\d+$/)
    expect(usageRows(seen)[0]).toMatchObject({
      pr: null, skill: 'c-msg', role: 'other', agent_id: 'messenger', subagent_type: 'harness:messenger',
      model: 'claude-sonnet-5-5', model_family: 'sonnet', tokens: 100, context_tokens: 500, requests: 2,
      tool_uses: 1, duration_s: 4, signal: 'NO_BLOCK',
    })
  })

  test('a forked skill that ends in a return block logs its signal', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    listing(on, [fork('loop-f', 'harness:pr-sum')])
    await steps($, seen, 'loop-f', 100)
    await loopEnd($, 'loop-f', 'summary\n---\nSIGNAL: DONE\n---')
    expect(usageRows(seen)[0]).toMatchObject({ skill: 'pr-sum', signal: 'DONE' })
  })

  test('a skill without a plugin prefix keeps its name', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    listing(on, [fork('loop-f', 'retry-policy', 'general-purpose')])
    await steps($, seen, 'loop-f', 100)
    await loopEnd($, 'loop-f')
    expect(usageRows(seen)[0]).toMatchObject({ skill: 'retry-policy', agent_id: 'general-purpose' })
  })

  test('an Agent dispatch loop is not taken for a fork: one row, from the Agent result', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    listing(on, [{ id: 'loop-x', type: 'harness:messenger', description: 'Draft the commit message' }])
    await steps($, seen, 'loop-x', 1000)
    await loopEnd($, 'loop-x')
    await dispatch($, 'SKILL: c-msg', 'harness:messenger')
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({ skill: 'c-msg', tokens: 1000 })
  })

  test('an Agent call described as one /token is not taken for a fork while it runs: one row', async ($, on) => {
    // The loop's requests and turn end land while the call is in flight, as a synchronous dispatch's do.
    const seen: Seen = world(on, async () => {
      await steps($, seen, 'loop-x', 1000)
      await loopEnd($, 'loop-x')
      return completed('ok')
    })
    listing(on, [{ id: 'loop-x', type: 'harness:messenger', description: '/review' }])
    await $.tool.call({ tool: 'Agent', description: '/review', prompt: 'SKILL: c-msg', subagent_type: 'harness:messenger' })
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({ skill: 'c-msg', tokens: 1000 })
  })

  test('a loop that is not a fork resolves no project', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    listing(on, [{ id: 'loop-n', type: 'general-purpose', description: 'Draft the commit message' }])
    await steps($, seen, 'loop-n', 100)
    expect(seen.git.some(argv => argv.includes('--git-common-dir'))).toBe(false)
    await loopEnd($, 'loop-n')
  })

  test('a lookup the agent list refuses is retried on the next request', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    const asked = { calls: 0 }
    on('agent.list', () => {
      asked.calls++
      return (asked.calls === 1 ? { deny: 'busy' } : { value: [{ ...fork('loop-f'), status: 'running' }] }) as never
    })
    await steps($, seen, 'loop-f', 100, 200)
    await loopEnd($, 'loop-f')
    expect(asked.calls).toBe(2)
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({ skill: 'c-msg', requests: 2 })
  })

  test('a loop the agent list does not name, or names off the /<skill> form, logs nothing', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    listing(on, [{ id: 'loop-y', type: 'general-purpose', description: '/two words' }])
    await steps($, seen, 'loop-compact', 100)
    await loopEnd($, 'loop-compact')
    await steps($, seen, 'loop-y', 100)
    await loopEnd($, 'loop-y')
    expect(seen.files.has(USAGE)).toBe(false)
  })

  test('the agent list is asked once per loop, not once per request', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    // A loop that never registers, so only the probe mark keeps steps 2 and 3 from asking again.
    const asked = listing(on, [{ id: 'loop-n', type: 'general-purpose', description: 'Draft the commit message' }])
    await steps($, seen, 'loop-n', 1, 2, 3)
    expect(asked.calls).toBe(1)
    await loopEnd($, 'loop-n')
  })

  test('a background Agent loop listed as a fork logs one row, under its header skill', async ($, on) => {
    const seen = world(on, () => ({
      result: {
        status: 'async_launched', agentId: 'loop-b', description: 'r', prompt: '', outputFile: 'f',
        resolvedModel: 'claude-sonnet-5-5',
      },
      text: 'launched',
    }))
    const asked = listing(on, [fork('loop-b')])
    await dispatch($, 'SKILL: todo-edit', 'harness:messenger')
    await steps($, seen, 'loop-b', 100)
    await loopEnd($, 'loop-b')
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({ skill: 'todo-edit' })
    expect(asked.calls).toBe(0)
  })

  test('a resumed fork logs a second row for its second run of turns', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    listing(on, [fork('loop-f')])
    await steps($, seen, 'loop-f', 100)
    await loopEnd($, 'loop-f')
    await steps($, seen, 'loop-f', 100)
    await loopEnd($, 'loop-f')
    const ids = usageRows(seen).map(r => r.run_id)
    expect(ids).toHaveLength(2)
    expect(new Set(ids).size).toBe(2)
  })

  test('outside a harness project a fork is looked up but not logged', async ($, on) => {
    const seen = world(on, () => completed('ok'), { config: null })
    const asked = listing(on, [fork('loop-f')])
    await steps($, seen, 'loop-f', 100)
    await loopEnd($, 'loop-f')
    expect(asked.calls).toBe(1)
    expect(seen.files.has(USAGE)).toBe(false)
  })
})

describe('the header convention and row fields (issue #193)', () => {
  const launched = () => ({
    result: { status: 'async_launched', agentId: 'loop-1', description: 'r', prompt: '', outputFile: 'f' }, text: 'launched',
  })
  const bandLine = async ($: Engine): Promise<string | undefined> => {
    const props = {
      hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 80, scroll: { offset: 0, bodyRows: 10 }, view: {},
    }
    const ui = await $.ui.mount({ plugin: 'agent-watcher', surface: 'terminal', component: 'AbovePrompt', props })
    const text = (await ui.find({ type: 'Text', text: /^PR #/ }))?.text
    await ui.unmount()
    return text
  }
  /** Every `runs` and `active` value the mod writes. */
  const stateWrites = (on: On): { runs: Record<string, Run>[]; active: unknown[] } => {
    const written: { runs: Record<string, Run>[]; active: unknown[] } = { runs: [], active: [] }
    on('state.set', (_$, e, next) => {
      if (e.plugin === 'agent-watcher' && e.key === 'runs') written.runs.push(e.value as Record<string, Run>)
      if (e.plugin === 'agent-watcher' && e.key === 'active') written.active.push(e.value)
      return next(e)
    })
    return written
  }

  test('a header with the skill key, RUN_ID and extra keys logs skill, run_id and fields', async ($, on) => {
    const seen = world(on, () => completed('---\nSIGNAL: recorded\nRUN: R-1\n---'))
    await dispatch($, 'SKILL: strap-skills\nRUN_ID: strap_R-1\nTARGET: retry-policy\nRUN: R-1\n\nPlay it.', 'x:runner')
    expect(usageRows(seen)[0]).toMatchObject({
      skill: 'strap-skills', run_id: 'strap_R-1', agent_id: 'runner', role: 'other', signal: 'recorded',
      fields: { TARGET: 'retry-policy', RUN: 'R-1' },
    })
  })

  test('a header block that ends before a body SIGNAL: line keeps that line out of fields', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    await dispatch($, 'SKILL: todo-edit\nISSUE: I2\nRead the brief.\nSIGNAL: DONE\nNOTES: body', 'general-purpose')
    expect(usageRows(seen)[0]?.fields).toEqual({ ISSUE: 'I2' })
  })

  test('a pr-review slot dispatch logs exactly as before, with no fields key', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    await steps($, seen, 'loop-x', 1000)
    await dispatch($, reviewerPrompt('r1', 'PR: 1526\nLENS: docs'), 'harness:pr-reviewer')
    expect(usageRows(seen)).toEqual([{
      logged_at: new Date(NOW).toISOString(), run_id: RUN, pr: 1526, skill: 'pr-review', role: 'reviewer',
      agent_id: 'r1', subagent_type: 'harness:pr-reviewer', model: 'claude-opus-5-5', model_family: 'opus',
      effort: 'default', tokens: 1000, context_tokens: 1000, requests: 1, tool_uses: 7, duration_s: 2.5, signal: 'DONE',
      notes: 'agent-watcher auto row; reviewer DONE',
    }])
  })

  test('a field value over 200 characters is cut to 197 and ...', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    await dispatch($, `SKILL: todo-edit\nCONTEXT: ${'c'.repeat(300)}`, 'general-purpose')
    expect(usageRows(seen)[0]?.fields).toEqual({ CONTEXT: `${'c'.repeat(197)}...` })
  })

  test('strap TREE / INIT and bubble-memo FILES lines put no path separator in the row', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    const runner = 'SKILL: strap-skills\nTARGET: retry-policy\nRUN: R-1\nTREE: C:\\w\\tree\nINIT: /w/tree/init.sh'
    await dispatch($, runner, 'harness:strap-scenario-runner')
    await dispatch($, 'SKILL: bubble-memo\nISSUE: I2\nFILES: plugins/a.py, plugins/b.py', 'harness:bubble-memo-investigator')
    const [strap, memo] = usageRows(seen)
    expect(strap?.fields).toEqual({ TARGET: 'retry-policy', RUN: 'R-1' })
    expect(memo?.fields).toEqual({ ISSUE: 'I2' })
    for (const row of usageRows(seen)) expect(JSON.stringify(row.fields)).not.toMatch(/[\\/]/)
  })

  test('a foreign SKILL over a reviewer header is a generic row: no matrix, band or pr-team run', async ($, on) => {
    const seen = world(on, p => (p.startsWith('SKILL:') ? completed(doneBlock(ZERO)) : launched()))
    const written = stateWrites(on)
    await dispatch($, reviewerPrompt('r1', 'PR: 1526'), 'harness:pr-reviewer')
    expect(await bandLine($)).toBe('PR #1526 · reviewers 0/1')
    // Without the SKILL line this header is a pr-team reviewer slot of another run of PR 1526.
    const memoRun = 'pr1526_20261009T130000Z'
    const memo = `SKILL: bubble-memo\nRUN_ID: ${memoRun}\nAGENT_ID: inv_I2\nAGENT_ROLE: reviewer`
    await dispatch($, memo, 'harness:bubble-memo-investigator')
    expect(await bandLine($)).toBe('PR #1526 · reviewers 0/1')
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({
      skill: 'bubble-memo', run_id: memoRun, agent_id: 'inv_I2', role: 'reviewer', pr: null,
    })
    expect(written.runs.some(runs => Object.values(runs).some(r => r.skill === 'pr-team'))).toBe(false)
    writeReview(seen, { verdict: 'READY TO MERGE', issues: {} })
    await mainTurnEnd($, 't1')
    expect(matrixRows(seen).map(r => r.cell)).not.toContain('pr1526_inv_I2')
  })

  test('SKILL: harness:strap-skills logs strap-skills; SKILL: Strap Skills logs standalone', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    await dispatch($, 'SKILL: harness:strap-skills', 'general-purpose')
    await dispatch($, 'SKILL: Strap Skills', 'general-purpose')
    const [prefixed, spaced] = usageRows(seen)
    expect(prefixed).toMatchObject({ skill: 'strap-skills' })
    expect('fields' in (prefixed ?? {})).toBe(false)
    expect(spaced).toMatchObject({ skill: 'standalone', fields: { SKILL: 'Strap Skills' } })
  })

  test('an unclaimed AGENT_ROLE: fixer logs role other and no counts', async ($, on) => {
    const seen = world(on, () => completed('---\nSIGNAL: DONE\nFIXED: C1\nEDITED: 1\n---'))
    await dispatch($, 'SKILL: todo-edit\nAGENT_ID: f1\nAGENT_ROLE: fixer', 'general-purpose')
    expect(usageRows(seen)[0]).toMatchObject({ role: 'other', agent_id: 'f1', fields: { AGENT_ROLE: 'fixer' } })
    expect('issues_fixed' in (usageRows(seen)[0] ?? {})).toBe(false)
  })

  test('AGENT_ID: docs/x and RUN_ID: a/b fall back to the type name and the generated id; PR: 208 fills pr', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    await dispatch($, 'SKILL: bubble-memo\nAGENT_ID: docs/x\nRUN_ID: a/b\nPR: 208', 'harness:bubble-memo-reviewer')
    const row = usageRows(seen)[0]
    expect(row).toMatchObject({ agent_id: 'bubble-memo-reviewer', pr: 208, skill: 'bubble-memo' })
    expect(String(row?.run_id)).toMatch(/^standalone_\d{8}T\d{6}Z_\d+$/)
    expect('fields' in (row ?? {})).toBe(false)
  })

  test('a SKILL: strap-skills dispatch leaves the active run alone and is gone from state after its row', async ($, on) => {
    const seen = world(on, p => (p.startsWith('SKILL:') ? completed('ok') : launched()))
    const written = stateWrites(on)
    await dispatch($, reviewerPrompt('r1', 'PR: 1526'), 'harness:pr-reviewer')
    const activeBefore = [...written.active]
    await dispatch($, `SKILL: strap-skills\nRUN_ID: ${RUN}\nTARGET: retry-policy`, 'harness:strap-scenario-runner')
    expect(written.active).toEqual(activeBefore)
    expect(await bandLine($)).toBe('PR #1526 · reviewers 0/1')
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({ skill: 'strap-skills', run_id: RUN })
    expect(Object.keys(written.runs.at(-1) ?? {})).toEqual([RUN])
    expect(Object.values(written.runs.at(-1) ?? {})[0]?.claimedBy).toBe('pr-review')
  })

  test('two concurrent dispatches under one RUN_ID log two rows', async ($, on) => {
    const seen = world(on, () => completed('ok'))
    const prompt = 'SKILL: strap-skills\nRUN_ID: strap_R-9\nAGENT_ID: runner'
    await Promise.all([
      dispatch($, prompt, 'harness:strap-scenario-runner'),
      dispatch($, prompt, 'harness:strap-scenario-runner'),
    ])
    expect(usageRows(seen).map(r => [r.run_id, r.agent_id])).toEqual([['strap_R-9', 'runner'], ['strap_R-9', 'runner']])
  })
})

describe('recovery of a claimed, unlogged pr-team run', () => {
  /** When RUN (`pr1526_20261009T120000Z`) started. */
  const RUN_START = Date.UTC(2026, 9, 9, 12, 0, 0)
  const TERMINAL = { agent_id: 'r1', agent_role: 'reviewer', signal: 'DONE', counts: { findings: 0, critical: 0, important: 0, minor: 0 } }

  const claimedRun = (seen: Seen): void => {
    seen.files.set(`${ROOT}/${DIR}/.matrix_owner`, { text: 'pending\n', mtimeMs: RUN_START })
    seen.files.set(`${ROOT}/${DIR}/dispatch_plan_review.json`, { text: JSON.stringify({ agents: [{ id: 'r1', model: 'opus' }] }), mtimeMs: RUN_START })
    seen.files.set(`${ROOT}/${DIR}/terminals.jsonl`, { text: `${JSON.stringify(TERMINAL)}\n`, mtimeMs: RUN_START })
  }

  const start = ($: Engine) => $.session.start({ cwd: ROOT, surface: 'terminal', isInteractive: true })

  test('a review JSON from before the run started is not its verdict', async ($, on) => {
    const seen = world(on, () => completed('hi'))
    claimedRun(seen)
    seen.files.set(REVIEW, { text: JSON.stringify({ verdict: 'READY TO MERGE', issues: {} }), mtimeMs: RUN_START - 60_000 })
    await start($)
    expect(seen.files.has(MATRIX)).toBe(false)
  })

  test('a review JSON written after the run started logs its matrix rows and no usage rows', async ($, on) => {
    const seen = world(on, () => completed('hi'))
    claimedRun(seen)
    seen.files.set(REVIEW, { text: JSON.stringify({ verdict: 'READY TO MERGE', issues: {} }), mtimeMs: RUN_START + 60_000 })
    await start($)
    expect(matrixRows(seen).map(r => r.cell)).toEqual(['pr1526_r1'])
    expect(seen.files.has(USAGE)).toBe(false)
  })
})

describe('pr-review run directory', () => {
  const PR_DIR = `${ROOT}/docs/_scratch/pr_review/1526`
  const OTHER = 'pr1526_20261009T130000Z'

  const setRun = (seen: Seen, current: string, plan: Record<string, unknown>): void => {
    seen.files.set(`${PR_DIR}/current`, { text: `${current}\n`, mtimeMs: NOW })
    seen.files.set(`${PR_DIR}/${RUN}/plan.json`, { text: JSON.stringify({ run_id: RUN, pr: 1526, ...plan }), mtimeMs: NOW })
  }
  const setFix = (seen: Seen, fixer: string, bubbled: string[]): void => {
    const body = { fixer, fixed: [], bubbled: bubbled.map(id => ({ id, classification: 'out_of_scope', reason: 'r' })) }
    seen.files.set(`${PR_DIR}/${RUN}/fixes/${fixer}.json`, { text: JSON.stringify(body), mtimeMs: NOW })
  }
  /** The band line: the test kit exposes no plugin state, so the drawn band is what is observed. */
  const bandLine = async ($: Engine): Promise<string | undefined> => {
    const props = {
      hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 80, scroll: { offset: 0, bodyRows: 10 }, view: {},
    }
    const ui = await $.ui.mount({ plugin: 'agent-watcher', surface: 'terminal', component: 'AbovePrompt', props })
    const text = (await ui.find({ type: 'Text', text: /^PR #/ }))?.text
    await ui.unmount()
    return text
  }
  const launched = () => ({
    result: { status: 'async_launched', agentId: 'loop-1', description: 'r', prompt: '', outputFile: 'f' }, text: 'launched',
  })
  const shell = ($: Engine, tool: 'Bash' | 'PowerShell', command: string) =>
    $.tool.call({ tool, command, description: 'd' } as never)

  test('the current run\'s plan.json phase refines the dispatch phase; another current run is ignored', async ($, on) => {
    const seen = world(on, launched)
    setRun(seen, RUN, { phase: 'consolidate' })
    await dispatch($, reviewerPrompt('r1', 'PR: 1526'))
    expect(await bandLine($)).toBe('PR #1526 · consolidating')
    setRun(seen, OTHER, { phase: 'fix' })
    await mainTurnEnd($, 't1')
    expect(await bandLine($)).toBe('PR #1526 · consolidating')
  })

  test('a plan.json without a known phase keeps the dispatch phase', async ($, on) => {
    const seen = world(on, launched)
    setRun(seen, RUN, { phase: 'merging' })
    await dispatch($, reviewerPrompt('r1', 'PR: 1526'))
    expect(await bandLine($)).toBe('PR #1526 · reviewers 0/1')
  })

  test('bubbled: review bubbles plus fixer bubbles no RESOLVED / CLOSED_NO_ACTION closes', async ($, on) => {
    const seen = world(on, launched)
    setRun(seen, RUN, { phase: 'fix' })
    setFix(seen, 'w1_fix_1', ['I9'])
    setFix(seen, 'w1_fix_2', ['C1', 'M12'])
    seen.files.set(`${PR_DIR}/${RUN}/fixes/notes.txt`, { text: 'junk', mtimeMs: NOW })
    await dispatch($, reviewerPrompt('r1', 'PR: 1526'))
    expect(await bandLine($)).toBe('PR #1526 · fixers 0/0 · 3 bubbled')
    writeReview(seen, {
      verdict: 'NOT READY TO MERGE', issues: { critical: [{ id: 'C1' }], important: [{ id: 'I2' }, { id: 'I9' }] },
      bubbles: ['I2'],
      post_review_resolutions: [{ id: 'C1', status: 'RESOLVED' }, { id: 'M12', status: 'CLOSED_NO_ACTION' }],
    })
    await mainTurnEnd($, 't1')
    // I2 from bubbles[], I9 still open; C1 and M12 closed by their resolutions.
    expect(await bandLine($)).toBe('PR #1526 · fixers 0/0 · 2 bubbled')
  })

  test('a shell call running pr_review.py refreshes within the turn; other commands do not', async ($, on) => {
    const seen = world(on, launched)
    const ranShell = () => ({ result: { stdout: '', stderr: '', interrupted: false } }) as never
    on('tool.call', { tool: 'Bash' }, ranShell)
    on('tool.call', { tool: 'PowerShell' }, ranShell)
    await dispatch($, reviewerPrompt('r1', 'PR: 1526'))
    setRun(seen, RUN, { phase: 'fix-plan' })
    await shell($, 'Bash', 'git status')
    expect(await bandLine($)).toBe('PR #1526 · reviewers 0/1')
    await shell($, 'Bash', `${PR_REVIEW_PY} waves 1526`)
    expect(await bandLine($)).toBe('PR #1526 · fix planning')
    setRun(seen, RUN, { phase: 'fix' })
    await shell($, 'PowerShell', '& python C:\\plugins\\harness\\scripts\\pr_review.py closeout 1526')
    expect(await bandLine($)).toBe('PR #1526 · fixers 0/0')
  })
})

describe('review-local runs (a local-<label> key)', () => {
  const KEY = 'local-fix-band'
  const LOCAL_RUN = `${KEY}_20261009T120000Z`
  const KEY_DIR = `${ROOT}/docs/_scratch/pr_review/${KEY}`
  const LOCAL_REVIEW = `${ROOT}/docs/PR_REVIEWS/LOCAL_fix-band_watch.json`
  const localPrompt = (id: string, role = 'reviewer') => `AGENT_ID: ${id}\nAGENT_ROLE: ${role}\nRUN_ID: ${LOCAL_RUN}\nPR: ${KEY}`
  const open = { verdict: 'NOT READY TO MERGE', issues: { important: [{ id: 'I1' }, { id: 'I2' }] } }
  const launched = () => ({
    result: { status: 'async_launched', agentId: 'loop-1', description: 'r', prompt: '', outputFile: 'f' }, text: 'launched',
  })
  const bandLine = async ($: Engine): Promise<string | undefined> => {
    const props = {
      hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 80, scroll: { offset: 0, bodyRows: 10 }, view: {},
    }
    const ui = await $.ui.mount({ plugin: 'agent-watcher', surface: 'terminal', component: 'AbovePrompt', props })
    const text = (await ui.find({ type: 'Text', text: /^(local review|PR #)/ }))?.text
    await ui.unmount()
    return text
  }

  test('the band names the run by its key; the run directory is the key folder', async ($, on) => {
    const seen = world(on, launched)
    await dispatch($, localPrompt('overall'), 'harness:pr-reviewer')
    expect(await bandLine($)).toBe(`local review ${KEY} · reviewers 0/1`)
    seen.files.set(`${KEY_DIR}/current`, { text: `${LOCAL_RUN}\n`, mtimeMs: NOW })
    seen.files.set(`${KEY_DIR}/${LOCAL_RUN}/plan.json`, { text: JSON.stringify({ phase: 'fix' }), mtimeMs: NOW })
    const fix = { fixer: 'w1_fix_1', fixed: [], bubbled: [{ id: 'I9', classification: 'out_of_scope', reason: 'r' }] }
    seen.files.set(`${KEY_DIR}/${LOCAL_RUN}/fixes/w1_fix_1.json`, { text: JSON.stringify(fix), mtimeMs: NOW })
    await mainTurnEnd($, 't1')
    expect(await bandLine($)).toBe(`local review ${KEY} · fixers 0/0 · 1 bubbled`)
  })

  test('the review is LOCAL_<label>_*.json; usage rows log a null pr; matrix rows are never written', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    const r = await dispatch($, localPrompt('overall'), 'harness:pr-reviewer')
    expect(r.context ?? []).not.toContain(OWNER_NOTE)
    seen.files.set(LOCAL_REVIEW, { text: JSON.stringify({ ...open, bubbles: ['I2'] }), mtimeMs: NOW + 1 })
    await mainTurnEnd($, 't1')
    expect(await bandLine($)).toBe(`local review ${KEY} · reviewers 1/1 · 1 bubbled`)
    expect(usageRows(seen)).toHaveLength(1)
    expect(usageRows(seen)[0]).toMatchObject({ run_id: LOCAL_RUN, pr: null, role: 'reviewer' })
    expect(seen.files.has(MATRIX)).toBe(false)
  })

  test('a hot local sentinel names the local review for the Stop keyword check', async ($, on) => {
    const seen = world(on, () => completed('x'))
    on('classic.Stop', () => ({}))
    seen.files.set(`${SENTINELS}/.phase5_pending_${KEY}`, { text: `${KEY}\n${NOW / 1000 - 60}\n`, mtimeMs: NOW })
    seen.files.set(LOCAL_REVIEW, { text: JSON.stringify(open), mtimeMs: NOW })
    const block = (await $.classic.Stop({ stop_hook_active: false, last_assistant_message: 'Bubbles: I1' })).block
    expect(block?.startsWith(`local review ${KEY}: `)).toBe(true)
    expect(await bandLine($)).toBe(`local review ${KEY} · Phase 5 pending`)
  })
})

describe('Stop guard', () => {
  const closerBlock = '---\nSIGNAL: DONE\nAGENT_ROLE: fixer\nFIXED: C1\nBUBBLED: I2,M3\nEDITED: 1\nOUTPUT: o\n---'
  const closeout = ($: Engine) => dispatch($, `MODE=CLOSEOUT\nRUN_ID=${RUN}\nRUNTIME_DIR=${DIR}`, 'pr-team-fixer')

  test('blocks when bubbled ids are not dispositioned; loop-break lets it through', async ($, on) => {
    const seen = world(on, () => completed(closerBlock))
    on('classic.Stop', () => ({}))
    writeReview(seen, {
      verdict: 'NOT READY TO MERGE', issues: { important: [{ id: 'I2' }], minor: [{ id: 'M3' }] },
      post_review_resolutions: [{ id: 'C1' }], bubbles: ['I2'],
    })
    await closeout($)
    expect((await $.classic.Stop({ stop_hook_active: false })).block).toContain('M3')
    expect((await $.classic.Stop({ stop_hook_active: true })).block).toBeUndefined()
  })

  const open = { verdict: 'NOT READY TO MERGE', issues: { important: [{ id: 'I1' }, { id: 'I2' }] } }
  const say = ($: Engine, text: string) => $.classic.Stop({ stop_hook_active: false, last_assistant_message: text })

  test('"bubble" in the last message checks the active pr-review run', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    on('classic.Stop', () => ({}))
    await dispatch($, reviewerPrompt('runtime', 'PR: 1526'))
    writeReview(seen, open)
    expect((await say($, 'I2 should bubble up for a decision.')).block).toContain('bubbles[]')
    expect((await say($, 'Review written.')).block).toBeUndefined()
    writeReview(seen, { ...open, bubbles: ['I2'] })
    expect((await say($, 'I2 is bubbled.')).block).toBeUndefined()
  })

  test('with no tracked run, a hot sentinel names the active review', async ($, on) => {
    const seen = world(on, () => completed('x'))
    on('classic.Stop', () => ({}))
    seen.files.set(`${SENTINELS}/.phase5_pending_1526`, { text: `1526\n${NOW / 1000 - 60}\n`, mtimeMs: NOW })
    writeReview(seen, open)
    expect((await say($, 'Bubbles: I1, I2')).block).toContain('PR #1526')
  })

  test("another session's sentinel names no active review; the arming session's does", async ($, on) => {
    const seen = world(on, () => completed('x'))
    on('classic.Stop', () => ({}))
    const sentinel = `1526\n${NOW / 1000 - 60}\nsess-owner\n`
    seen.files.set(`${SENTINELS}/.phase5_pending_1526`, { text: sentinel, mtimeMs: NOW })
    writeReview(seen, open)
    const stop = (session_id: string) =>
      $.classic.Stop({ stop_hook_active: false, last_assistant_message: 'Bubbles: I1, I2', session_id })
    expect((await stop('sess-other')).block).toBeUndefined()
    expect((await stop('sess-owner')).block).toContain('PR #1526')
  })

  test('with no active review the keyword checks nothing', async ($, on) => {
    const seen = world(on, () => completed('x'))
    on('classic.Stop', () => ({}))
    writeReview(seen, open)
    expect((await say($, 'bubble bubble')).block).toBeUndefined()
  })

  test('allows once every bubbled id is dispositioned; keeps a settings block as is', async ($, on) => {
    const seen = world(on, () => completed(closerBlock))
    let settingsBlock: string | undefined
    on('classic.Stop', () => (settingsBlock === undefined ? {} : { block: settingsBlock }))
    writeReview(seen, {
      verdict: 'NOT READY TO MERGE', issues: { important: [{ id: 'I2' }] }, bubbles: ['I2'],
      bubble_up: [{ id: 'M3', classification: 'out_of_scope', reason: 'r' }],
    })
    await closeout($)
    expect((await $.classic.Stop({ stop_hook_active: false })).block).toBeUndefined()
    settingsBlock = 'Phase 5 sentinel hot'
    expect((await $.classic.Stop({ stop_hook_active: false })).block).toBe('Phase 5 sentinel hot')
  })
})

describe('harness project', () => {
  const open = { verdict: 'NOT READY TO MERGE', issues: { important: [{ id: 'I1' }] } }

  test('without .claude/harness.json the watch stays inactive', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)), { config: null })
    on('classic.Stop', () => ({}))
    const r = await dispatch($, reviewerPrompt('r1', 'PR: 1526'))
    expect(r.context ?? []).not.toContain(OWNER_NOTE)
    expect(seen.agentCalls).toBe(1)
    seen.files.set(`${SENTINELS}/.phase5_pending_1526`, { text: `1526\n${NOW / 1000 - 60}\n`, mtimeMs: NOW })
    writeReview(seen, open)
    await mainTurnEnd($, 't')
    expect(seen.files.has(MATRIX)).toBe(false)
    expect(seen.files.has(USAGE)).toBe(false)
    expect((await $.classic.Stop({ stop_hook_active: false, last_assistant_message: 'bubble' })).block).toBeUndefined()
    expect(seen.git.filter(argv => !argv.includes('--show-toplevel'))).toEqual([])
  })

  test('state_dir, matrix_path, artifacts.reviews and base_branch come from harness.json', async ($, on) => {
    const config = { state_dir: 'st', matrix_path: 'meta/m.jsonl', base_branch: 'trunk', artifacts: { reviews: 'rev' } }
    const seen = world(on, () => completed(doneBlock(ZERO)), { config: JSON.stringify(config) })
    on('classic.Stop', () => ({}))
    await dispatch($, reviewerPrompt('r1'))
    seen.files.set(`${ROOT}/rev/1526_watch.json`, { text: JSON.stringify({ verdict: 'READY TO MERGE', issues: {} }), mtimeMs: NOW + 1 })
    await mainTurnEnd($, 't')
    expect(seen.files.has(MATRIX)).toBe(false)
    const rows = (seen.files.get(`${ROOT}/meta/m.jsonl`)?.text ?? '').split('\n').filter(Boolean)
    expect(rows.map(l => (JSON.parse(l) as { cell: string }).cell)).toEqual(['pr1526_r1'])
    expect(seen.git).toContainEqual(['git', '-C', ROOT, 'merge-base', 'HEAD', 'trunk'])
  })

  test('sentinels sit under <state_dir>/pr-review; reviews under artifacts.reviews', async ($, on) => {
    const config = { state_dir: 'st', artifacts: { reviews: 'rev' } }
    const seen = world(on, () => completed('x'), { config: JSON.stringify(config) })
    on('classic.Stop', () => ({}))
    seen.files.set(`${ROOT}/st/pr-review/.phase5_pending_1600`, { text: `1600\n${NOW / 1000 - 60}\n`, mtimeMs: NOW })
    seen.files.set(`${ROOT}/rev/1600_x.json`, { text: JSON.stringify(open), mtimeMs: NOW })
    expect((await $.classic.Stop({ stop_hook_active: false, last_assistant_message: 'bubble' })).block).toContain('PR #1600')
  })

  test('claimed pr-team runs are recovered from <state_dir>/pr-team/_runtime', async ($, on) => {
    const seen = world(on, () => completed('hi'), { config: JSON.stringify({ state_dir: 'st' }) })
    const dir = `${ROOT}/st/pr-team/_runtime/${RUN}`
    const terminal = { agent_id: 'r1', agent_role: 'reviewer', signal: 'DONE', counts: null }
    seen.files.set(`${dir}/.matrix_owner`, { text: 'pending\n', mtimeMs: 1 })
    seen.files.set(`${dir}/dispatch_plan_review.json`, { text: JSON.stringify({ agents: [{ id: 'r1', model: 'opus' }] }), mtimeMs: 1 })
    seen.files.set(`${dir}/terminals.jsonl`, { text: `${JSON.stringify(terminal)}\n`, mtimeMs: 1 })
    writeReview(seen, { verdict: 'READY TO MERGE', issues: {} })
    await $.session.start({ cwd: ROOT, surface: 'terminal', isInteractive: true })
    expect(matrixRows(seen).map(r => r.cell)).toEqual(['pr1526_r1'])
    expect(seen.files.get(`${dir}/.matrix_owner`)?.text).toMatch(/^logged /)
  })

  test('a pr-team slot without OUTPUT_FILE reads its sidecar under <state_dir>/pr-team/_runtime', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)), { config: JSON.stringify({ state_dir: 'st' }) })
    on('classic.Stop', () => ({}))
    const sidecar = `${ROOT}/st/pr-team/_runtime/${RUN}/bubble_ups.json`
    seen.files.set(sidecar, { text: JSON.stringify({ items: [{ id: 'I7' }] }), mtimeMs: NOW })
    writeReview(seen, { verdict: 'NOT READY TO MERGE', issues: { important: [{ id: 'I7' }] } })
    await dispatch($, reviewerPrompt('r1'))
    expect((await $.classic.Stop({ stop_hook_active: false })).block).toContain('I7')
  })

  test('no base_branch: origin/HEAD names the base, else main', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)), { originHead: 'origin/develop' })
    await dispatch($, reviewerPrompt('r1'))
    writeReview(seen, { verdict: 'READY TO MERGE', issues: {} })
    await mainTurnEnd($, 't')
    expect(seen.git).toContainEqual(['git', '-C', ROOT, 'merge-base', 'HEAD', 'develop'])
  })

  test('with origin/HEAD unset the base is main', async ($, on) => {
    const seen = world(on, () => completed(doneBlock(ZERO)))
    await dispatch($, reviewerPrompt('r1'))
    writeReview(seen, { verdict: 'READY TO MERGE', issues: {} })
    await mainTurnEnd($, 't')
    expect(seen.git).toContainEqual(['git', '-C', ROOT, 'merge-base', 'HEAD', 'main'])
  })
})

// ---------------------------------------------------------------------------
// Two layers: the core's layer-list seams, over an in-memory Io (the engine always loads the plugin under
// test with its own LAYERS, so a second registerCore would stack a second core beneath it).

const PR_RUN = 'pr1526_20261009T120000Z'
const STUB_RUN = 'stub_1'
const SOLO_RUN = 'standalone_1'

type Memory = { runs: Record<string, Run>; active: string | null; missing: string[]; files: Map<string, string> }

/** An Io over plain memory, rooted at ROOT with the harness defaults. */
const memoryIo = (m: Memory): Io => ({
  watch: {
    root: ROOT, harness: {}, sentinelRoot: ROOT,
    cfg: { stateDir: '.claude/state/harness', agentUsagePath: 'docs/_harness/agent_usage.jsonl' },
  },
  readText: async p => m.files.get(p),
  listDir: async () => [],
  exists: async p => m.files.has(p),
  mtimeOf: async () => undefined,
  write: async (p, t) => {
    m.files.set(p, t)
    return true
  },
  gitLine: async () => undefined,
  toast: async () => undefined,
  now: async () => NOW,
  runs: async () => m.runs,
  updateRuns: async change => {
    m.runs = change(m.runs)
  },
  activeRunId: async () => m.active,
  updateFailures: async () => undefined,
  setPhase5: async () => undefined,
  missing: async () => m.missing,
  setMissing: async ids => {
    m.missing = ids
  },
})

/** `layer` with each per-run member logged as `<name>.<member> <runId>` before it runs. */
const logged = (layer: Layer, log: string[]): Layer => ({
  ...layer,
  foldRun: (run, id, c) => {
    log.push(`${layer.name}.foldRun ${run.runId}`)
    return layer.foldRun === undefined ? run : layer.foldRun(run, id, c)
  },
  onComplete: async (io, run, id, c) => {
    log.push(`${layer.name}.onComplete ${run.runId}`)
    await layer.onComplete?.(io, run, id, c)
  },
  rowFields: async (io, run, agent, c) => {
    log.push(`${layer.name}.rowFields ${run.runId}`)
    return layer.rowFields?.(io, run, agent, c)
  },
  resultContext: async (io, run, agent, r) => {
    log.push(`${layer.name}.resultContext ${run.runId}`)
    return (await layer.resultContext?.(io, run, agent, r)) ?? []
  },
})

const boom = async (): Promise<never> => {
  throw new Error('stub layer failed')
}

/** A second layer: claims `STUB=` headers; its usage counts, settle and Stop check all throw. */
const stubLayer: Layer = {
  name: 'stub',
  identify: (_t, h) => (h.STUB === undefined ? undefined : {
    runId: STUB_RUN, skill: 'pr-team', agentId: h.STUB, role: 'fixer', pr: null, runtimeDir: null, phase: 'fix',
  }),
  resultContext: async () => ['stub line'],
  rowFields: boom,
  onSettle: boom,
  stopReason: boom,
}

const claimed = (d: Dispatch, claimedBy: string | undefined): Run =>
  applyCompletion(applyDispatch({}, d, newAgent(d, {}), 1, claimedBy)[d.runId]!, d.agentId, {
    tokens: 5, toolUses: 1, durationMs: 1000, model: 'claude-opus-5-5', isMeasured: true, ending: 'ok',
    block: parseReturnBlock('---\nSIGNAL: DONE\n---'),
  })

const memory = (): Memory => {
  const pr: Dispatch = {
    runId: PR_RUN, skill: 'pr-team', agentId: 'r1', role: 'reviewer', pr: 1526, runtimeDir: null, phase: 'review',
  }
  const stub = stubLayer.identify(undefined, { STUB: 's1' }, undefined)!
  const solo: Dispatch = {
    runId: SOLO_RUN, skill: 'standalone', agentId: 'messenger', role: 'other', pr: null, runtimeDir: null,
    phase: 'done',
  }
  const runs = {
    [PR_RUN]: claimed(pr, 'pr-review'), [STUB_RUN]: claimed(stub, 'stub'), [SOLO_RUN]: claimed(solo, undefined),
  }
  return { runs, active: PR_RUN, missing: [], files: new Map() }
}

const c0 = {
  tokens: 0, toolUses: 0, durationMs: 0, model: null, block: undefined, isMeasured: true, ending: 'ok' as const,
}

describe('two layers', () => {
  const perRun = async (layers: readonly Layer[], m: Memory, runId: string, agentId: string): Promise<void> => {
    const io = memoryIo(m)
    const run = m.runs[runId]!
    foldInto(layers, run, agentId, c0)
    await completeLayer(io, layers, { runId, agentId }, c0)
    await countsFor(io, layers, run, run.agents[agentId]!, c0)
    await contextFor(io, layers, { ...run, agentId, role: run.agents[agentId]!.role }, {})
  }

  test('each run reaches only the per-run members of the layer that claimed it', async () => {
    const log: string[] = []
    const layers = [logged(prReviewLayer, log), logged(stubLayer, log)]
    const m = memory()
    const members = ['foldRun', 'onComplete', 'rowFields', 'resultContext']
    await perRun(layers, m, PR_RUN, 'r1')
    expect(log).toEqual(members.map(k => `pr-review.${k} ${PR_RUN}`))
    log.length = 0
    await perRun(layers, m, STUB_RUN, 's1')
    expect(log).toEqual(members.map(k => `stub.${k} ${STUB_RUN}`))
    log.length = 0
    await perRun(layers, m, SOLO_RUN, 'messenger')
    expect(log).toEqual([])
  })

  test('the claimer alone adds result context', async () => {
    const m = memory()
    const io = memoryIo(m)
    const layers = [prReviewLayer, stubLayer]
    const stubClaim = stubLayer.identify(undefined, { STUB: 's1' }, undefined)!
    expect(await contextFor(io, layers, stubClaim, {})).toEqual(['stub line'])
    const prRun = m.runs[PR_RUN]!
    expect(await contextFor(io, layers, { ...prRun, agentId: 'r1', role: 'reviewer' }, {})).toEqual([])
  })

  test('a throwing stub rowFields still lets its usage row append, with no counts', async () => {
    const m = memory()
    await logUsage(memoryIo(m), [stubLayer, prReviewLayer], { runId: STUB_RUN, agentId: 's1' }, c0)
    const rows = (m.files.get(USAGE) ?? '').split('\n').filter(Boolean).map(l => JSON.parse(l))
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      run_id: STUB_RUN, agent_id: 's1', role: 'fixer', issues_assigned: null, issues_fixed: null,
    })
  })

  test('a throwing stub settle and Stop check still let pr-review settle and block', async () => {
    const m = memory()
    m.runs[PR_RUN] = { ...m.runs[PR_RUN]!, bubbled: ['I2'], bubbledFrom: 'closer' }
    m.missing = ['stale']
    const io = memoryIo(m)
    const layers = [stubLayer, prReviewLayer]
    await settleLayers(io, layers)
    expect(m.missing).toEqual([])
    m.missing = ['I2']
    const reason = await stopReasonOf(io, layers, { stop_hook_active: false })
    expect(reason).toContain('does not disposition bubbled I2')
  })
})
