import type { Engine } from 'claude-code/testing'
import type { On, ProcessRunResult } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import { OWNER_NOTE } from './tracker'

/**
 * Engine-level behavior of the tracker: what reaches the matrix JSONL, the ownership marker and the
 * Stop decision. Files, git, env and the Agent tool sit beneath the plugin, answered from memory.
 */

const ROOT = '/repo'
const RUN = 'pr1526_20261009T120000Z'
/** The harness defaults: state_dir `.claude/state/harness`, matrix_path under `docs/_harness`. */
const DIR = `.claude/state/harness/pr-team/_runtime/${RUN}`
const SENTINELS = `${ROOT}/.claude/state/harness/pr-review`
const MATRIX = `${ROOT}/docs/_harness/pr_review_invocation_test_matrix.jsonl`
const REVIEW = `${ROOT}/docs/PR_REVIEWS/1526_watch.json`
const HARNESS = `${ROOT}/.claude/harness.json`
const PR_REVIEW_PY = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/hpy" "${CLAUDE_PLUGIN_ROOT}/scripts/pr_review.py"'
const SHA = '0123456789abcdef0123456789abcdef01234567'
const NOW = 1_800_000_000_000
const ZERO = 'findings=0 critical=0 important=0 minor=0'

type Files = Map<string, { text: string; mtimeMs: number }>
/** `unreadable`: paths that exist but whose read is refused (a lock, an OS refusal, over 4 MiB). */
type Seen = { files: Files; unreadable: Set<string>; toasts: string[]; agentCalls: number; git: string[][] }
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
  const seen: Seen = { files: new Map(), unreadable: new Set(), toasts: [], agentCalls: 0, git: [] }
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
  on('tool.call', { tool: 'Agent' }, (_$, e) => {
    seen.agentCalls++
    return agentAnswer(e.prompt) as never
  })
  return seen
}

const dispatch = ($: Engine, prompt: string, subagentType = 'superpowers:code-reviewer') =>
  $.tool.call({ tool: 'Agent', description: 'r', prompt, subagent_type: subagentType, model: 'opus' })

const mainTurnEnd = ($: Engine, turnId: string) =>
  $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId, reason: 'answer' })

const writeReview = (seen: Seen, body: Record<string, unknown>): void => {
  seen.files.set(REVIEW, { text: JSON.stringify(body), mtimeMs: NOW + 1 })
}

const matrixRows = (seen: Seen): Record<string, unknown>[] =>
  (seen.files.get(MATRIX)?.text ?? '').split('\n').filter(Boolean).map(l => JSON.parse(l) as Record<string, unknown>)

describe('Agent hook', () => {
  test('untracked dispatches pass through untouched', async ($, on) => {
    const seen = world(on, () => completed('hi'))
    const r = await dispatch($, 'find files', 'Explore')
    expect(r.context ?? []).toEqual([])
    expect(seen.agentCalls).toBe(1)
    expect(seen.files.has(MATRIX)).toBe(false)
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
      e.plugin === 'pr-review-watch' && e.key === 'runs' ? { deny: 'state store full' } : next(e),
    )
    const r = await dispatch($, reviewerPrompt('runtime', 'PR: 1526'))
    expect(r.context ?? []).not.toContain(OWNER_NOTE)
  })
})

describe('matrix rows', () => {
  test('one measured row per reviewer once the review has a verdict; attempted once', async ($, on) => {
    const seen = world(on, p => completed(doneBlock(p.includes('r1') ? 'findings=2 critical=1 important=1 minor=0' : ZERO)))
    await dispatch($, reviewerPrompt('r1'))
    await dispatch($, reviewerPrompt('r2'))
    expect(seen.files.has(MATRIX)).toBe(false)
    writeReview(seen, { verdict: 'NOT READY TO MERGE: 1 critical', issues: { critical: [{ id: 'C1' }] } })
    await mainTurnEnd($, 't1')
    const rows = matrixRows(seen)
    expect(rows.map(r => r.cell)).toEqual(['pr1526_r1', 'pr1526_r2'])
    expect(rows[0]).toMatchObject({
      tokens: 1000, tool_uses: 7, duration_s: 2.5, model_family: 'opus', C_count: 1, verdict_prefix: 'NOT READY TO MERGE',
    })
    expect(rows[0]?.dev_commit).toBe(`${SHA} -- dev (pr-review-watch auto)`)
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

  test('a review JSON written after the run started logs its rows', async ($, on) => {
    const seen = world(on, () => completed('hi'))
    claimedRun(seen)
    seen.files.set(REVIEW, { text: JSON.stringify({ verdict: 'READY TO MERGE', issues: {} }), mtimeMs: RUN_START + 60_000 })
    await start($)
    expect(matrixRows(seen).map(r => r.cell)).toEqual(['pr1526_r1'])
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
    const ui = await $.ui.mount({ plugin: 'pr-review-watch', surface: 'terminal', component: 'AbovePrompt', props })
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
