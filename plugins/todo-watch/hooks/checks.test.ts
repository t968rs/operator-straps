import type { SessionMessage } from 'claude-code'
import type { Engine } from 'claude-code/testing'
import { describe, expect, test } from 'claude-code/testing'

import type { Watch } from './watch'
import { MAX_TOAST_SECONDS, readConfig } from './config'
import {
  CHECK_TIMEOUT_MS, isWatchedPath, normalPath, parseReport, parseRunner, pathOfCall, reportTimeMs, startGateMs,
  LONG_TOAST_MS,
} from './checks'
import {
  BANNER_CONFIG, CATALOG_LINE, CATALOG_REL, checkRuns, CONFIG, NOW, prompt, PYTHON, RESEARCH_CATALOG_REL,
  reportText, runTodo, SCRIPT, SNAPSHOTS_REL, start, SYNC_REL, TODO_DIR, turnEnd, world, type World,
} from './testWorld'

const HOUR = 3_600_000

// ---------------------------------------------------------------------------
// Pure: runner pointer and report

describe('parseRunner', () => {
  test('a pointer as the harness hook writes it', async () => {
    const text = JSON.stringify({
      schema_version: 1, python: 'C:/py/python.exe', script: 'C:/p/todo_sync.py', project: 'C:/repo',
      report: 'C:/repo/.claude/state/harness/todo-sync/report.json', written_at: '2026-10-19T10:00:00Z',
    })
    expect(parseRunner(text)).toEqual({
      python: 'C:/py/python.exe', script: 'C:/p/todo_sync.py', project: 'C:/repo',
      report: 'C:/repo/.claude/state/harness/todo-sync/report.json',
    })
  })

  test('another version, a blank field or bad JSON is no pointer; a missing report is allowed', async () => {
    const base = { schema_version: 1, python: 'p', script: 's', project: '/repo' }
    expect(parseRunner(JSON.stringify({ ...base, schema_version: 2 }))).toBeUndefined()
    expect(parseRunner(JSON.stringify({ ...base, script: ' ' }))).toBeUndefined()
    expect(parseRunner('{')).toBeUndefined()
    expect(parseRunner(JSON.stringify(base))?.report).toBeUndefined()
  })
})

describe('parseReport', () => {
  test('the keys the mod reads', async () => {
    const r = parseReport(reportText(NOW, 2, { P1: 1, T2: 1 }), 9)
    expect(r?.drift).toBe(2)
    expect(r?.byRule).toEqual({ P1: 1, T2: 1 })
    expect([r?.errors, r?.warns, r?.ghFetchedAt, r?.mtimeMs]).toEqual([2, 0, null, 9])
    expect(r?.findings[0]).toEqual({
      rule: 'P1', severity: 'error', counted: true, file: 'docs/PLANS/a_PIP.md', line: 3, subject: 'X-1',
      message: 'P1 broke', fix: null,
    })
    expect(reportTimeMs(r!)).toBe(NOW)
  })

  test('a missing key, another version or a wrong type is malformed', async () => {
    const good = JSON.parse(reportText(NOW, 1, { P1: 1 })) as Record<string, unknown>
    const bad = (over: Record<string, unknown>) => parseReport(JSON.stringify({ ...good, ...over }), 1)
    const { findings: _f, ...noFindings } = good
    expect(parseReport(JSON.stringify(noFindings), 1)).toBeUndefined()
    expect(bad({ schema_version: 2 })).toBeUndefined()
    expect(bad({ drift: -1 })).toBeUndefined()
    expect(bad({ by_rule: [] })).toBeUndefined()
    expect(parseReport('not json', 1)).toBeUndefined()
  })

  test('malformed findings are skipped; optional finding keys default to null', async () => {
    const good = JSON.parse(reportText(NOW, 1, {})) as Record<string, unknown>
    const findings = [
      { rule: 'T6', severity: 'warn', counted: false, file: null, message: 'm' },
      { rule: 'T6', severity: 'fatal', counted: false, file: null, message: 'm' },
      { rule: 'T6', severity: 'warn', counted: false, message: 'no file key' },
    ]
    const r = parseReport(JSON.stringify({ ...good, findings }), 1)
    expect(r?.findings).toEqual([
      { rule: 'T6', severity: 'warn', counted: false, file: null, line: null, subject: null, message: 'm', fix: null },
    ])
  })

  test('a check --rules report covers a subset of the rules and is ignored', async () => {
    const good = JSON.parse(reportText(NOW, 0, {})) as Record<string, unknown>
    const skipped = (reason: string) => JSON.stringify({ ...good, rules_skipped: [{ rule: 'T2', reason }] })
    expect(parseReport(skipped('not selected'), 1)).toBeUndefined()
    expect(parseReport(skipped('disabled'), 1)?.drift).toBe(0)
  })

  test('an unparsable generated_at falls back to the mtime', async () => {
    const r = parseReport(JSON.stringify({ ...JSON.parse(reportText(NOW, 0, {})), generated_at: 'soon' }), 42)
    expect(reportTimeMs(r!)).toBe(42)
  })
})

// ---------------------------------------------------------------------------
// Pure: watched paths

const watchAt = (root: string): Watch => ({ root, cfg: readConfig(JSON.stringify(CONFIG)) })

describe('isWatchedPath', () => {
  test('watched files and anything under a watched folder', async () => {
    const w = watchAt('/repo')
    expect(isWatchedPath(w, `/repo/${CATALOG_REL}`)).toBe(true)
    expect(isWatchedPath(w, '/repo/docs/RESEARCH/FBS/_IMPL_TODO.md')).toBe(true)
    expect(isWatchedPath(w, '/repo/docs/PLANS/1_ActionPlan.json')).toBe(true)
    expect(isWatchedPath(w, '/repo/src/a.py')).toBe(false)
    expect(isWatchedPath(w, '/repo/docs/RESEARCH')).toBe(false)
    expect(isWatchedPath(w, '/repo/docs/RESEARCHER/x.md')).toBe(false)
    expect(isWatchedPath(w, '')).toBe(false)
  })

  test('relative paths are project-relative; dot segments fold', async () => {
    const w = watchAt('/repo')
    expect(isWatchedPath(w, 'docs/PLANS/x.md')).toBe(true)
    expect(isWatchedPath(w, `./${CATALOG_REL}`)).toBe(true)
    expect(isWatchedPath(w, '/repo/src/../docs/PLANS/x.md')).toBe(true)
    expect(isWatchedPath(w, 'src/x.md')).toBe(false)
  })

  test('POSIX roots compare case-sensitively', async () => {
    expect(isWatchedPath(watchAt('/repo'), '/repo/docs/plans/x.md')).toBe(false)
  })

  test('Windows-style roots: backslashes and any case', async () => {
    const w = watchAt('C:/repo')
    expect(isWatchedPath(w, 'C:\\repo\\docs\\RESEARCH\\todo.json')).toBe(true)
    expect(isWatchedPath(w, 'c:/REPO/docs/plans/x.md')).toBe(true)
    expect(isWatchedPath(w, 'docs\\PLANS\\x.md')).toBe(true)
    expect(isWatchedPath(w, 'C:\\repo\\src\\x.md')).toBe(false)
  })

  test('normalPath keeps the head', async () => {
    expect(normalPath('C:\\a\\.\\b\\..\\c\\')).toBe('C:/a/c')
    expect(normalPath('//host/share/x')).toBe('//host/share/x')
    expect(normalPath('/a//b')).toBe('/a/b')
  })

  test('pathOfCall: file_path, notebook_path for NotebookEdit, none for a shell', async () => {
    expect(pathOfCall({ tool: 'Write', file_path: '/a' })).toBe('/a')
    expect(pathOfCall({ tool: 'NotebookEdit', notebook_path: '/n.ipynb', file_path: '/x' })).toBe('/n.ipynb')
    expect(pathOfCall({ tool: 'Bash' })).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// Hooks

const catalogPath = (w: World): string => `${w.root}/${CATALOG_REL}`

/** A Write through the tool chain, then the work it scheduled. */
async function write($: Engine, w: World, path: string): Promise<void> {
  await $.tool.call({ tool: 'Write', file_path: path, content: '{}' })
  await w.clock.settle()
}

async function bash($: Engine, w: World): Promise<void> {
  await $.tool.call({ tool: 'Bash', command: 'python gen.py' })
  await w.clock.settle()
}

describe('M1: the session start toast', () => {
  test('catalog-only; a report older than the session start shows no drift', async ($, on) => {
    const w = world(on, { hasRunner: false })
    w.setFile(`${w.root}/${SYNC_REL}/report.json`, reportText(NOW - HOUR, 3, { P1: 3 }), NOW - HOUR)
    await start($, w)
    expect(w.notices).toEqual([CATALOG_LINE])
    const text = await runTodo($)
    expect(text.split('\n\n')[0]).toBe(CATALOG_LINE)
    expect(text).toContain('no report yet')
    expect(text).not.toContain('sync checks unavailable')
  })

  test('by default a toast that stays the longest the engine allows', async ($, on) => {
    const w = world(on, { hasRunner: false })
    await start($, w)
    expect([w.toasts, w.toastTimeouts, w.band]).toEqual([[CATALOG_LINE], [MAX_TOAST_SECONDS * 1000], []])
  })

  test('todo.notice.toast_seconds sets how long the toast stays', async ($, on) => {
    const w = world(on, { config: { todo: { folder: TODO_DIR, notice: { toast_seconds: 15 } } }, hasRunner: false })
    await start($, w)
    expect([w.toasts, w.toastTimeouts]).toEqual([[CATALOG_LINE], [15_000]])
  })

  test('todo.notice.style banner posts to the band, no toast', async ($, on) => {
    const w = world(on, { config: BANNER_CONFIG, hasRunner: false })
    await start($, w)
    expect([w.band, w.toasts]).toEqual([[CATALOG_LINE], []])
  })

  test('the drift part appears once a report newer than the start lands', async ($, on) => {
    const w = world(on)
    w.engine.drift = 2
    w.engine.byRule = { P1: 2 }
    await $.session.start({ cwd: w.root, surface: null, isInteractive: false })
    expect(w.notices).toEqual([CATALOG_LINE])
    expect((await runTodo($)).split('\n\n')[0]).toBe(CATALOG_LINE)
    await w.clock.settle()
    expect(checkRuns(w)).toEqual([[PYTHON, SCRIPT, 'check', '--project', '/repo']])
    expect((await runTodo($)).split('\n\n')[0]).toBe(`${CATALOG_LINE} · 2 out of sync`)
  })

  test('a report stamped in whole seconds within the start second is fresh', async ($, on) => {
    expect(startGateMs(NOW + 999)).toBe(NOW)
    const w = world(on)
    w.engine.mode = 'fail'
    await w.clock.advance(500)
    await start($, w)
    w.setFile(`${w.root}/${SYNC_REL}/report.json`, reportText(NOW, 2, { P1: 2 }), NOW + 501)
    await prompt($, w)
    expect((await runTodo($)).split('\n\n')[0]).toBe(`${CATALOG_LINE} · 2 out of sync`)
  })

  test('a malformed or missing catalog toasts nothing at start', async ($, on) => {
    const w = world(on, { catalog: '{"counts": 1}', hasRunner: false })
    await start($, w)
    expect(w.notices).toEqual([])
    expect(await runTodo($)).toContain('TODO catalog unreadable')
  })
})

describe('M4: drift toasts', () => {
  test('only on a rise above the last toasted drift, and once at zero', async ($, on) => {
    const w = world(on)
    const drifts: Array<[number, Record<string, number>]> = [
      [1, { P1: 1 }], [3, { P1: 2, S5: 1 }], [2, { S5: 2 }], [3, { S5: 3 }], [0, {}], [0, {}], [1, { T2: 1 }],
    ]
    w.engine.drift = 2
    w.engine.byRule = { P1: 1, S5: 1 }
    await start($, w)
    for (const [drift, byRule] of drifts) {
      w.engine.drift = drift
      w.engine.byRule = byRule
      await write($, w, catalogPath(w))
    }
    expect(w.notices).toEqual([
      CATALOG_LINE,
      'TODO sync drift 2 (+2): P1=1 S5=1',
      'TODO sync drift 3 (+1): P1=2 S5=1',
      'TODO sync clean',
      'TODO sync drift 1 (+1): T2=1',
    ])
    expect(checkRuns(w).length).toBe(8)
  })

  for (const [config, surface] of [[CONFIG, 'toasts'], [BANNER_CONFIG, 'band']] as const) {
    test(`drift notices follow todo.notice.style: ${surface}`, async ($, on) => {
      const w = world(on, { config })
      await start($, w)
      w.engine.drift = 1
      w.engine.byRule = { P1: 1 }
      await write($, w, catalogPath(w))
      expect(w[surface]).toEqual([CATALOG_LINE, 'TODO sync drift 1 (+1): P1=1'])
    })
  }

  test('a first report with no drift toasts nothing', async ($, on) => {
    const w = world(on)
    await start($, w)
    expect(w.notices).toEqual([CATALOG_LINE])
    expect(await runTodo($)).toContain('sync clean')
  })
})

describe('M2: the TODO_SYNC context line', () => {
  test('none before a fresh report; then on change only; again after /clear, resume, compaction', async ($, on) => {
    const w = world(on)
    w.engine.drift = 2
    w.engine.byRule = { T2: 1, P1: 1 }
    await $.session.start({ cwd: w.root, surface: null, isInteractive: false })
    expect(await prompt($, w)).toEqual([])
    expect(await prompt($, w)).toEqual(['TODO_SYNC drift=2 P1=1 T2=1'])
    expect(await prompt($, w)).toEqual([])
    w.engine.drift = 1
    w.engine.byRule = { P1: 1 }
    await write($, w, catalogPath(w))
    expect(await prompt($, w)).toEqual(['TODO_SYNC drift=1 P1=1'])
    expect(await prompt($, w)).toEqual([])
    await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })
    expect(await prompt($, w)).toEqual(['TODO_SYNC drift=1 P1=1'])
    await $.session.end({ reason: 'resume', sessionId: 's1', resume: { id: 's1' } })
    expect(await prompt($, w)).toEqual(['TODO_SYNC drift=1 P1=1'])
    const history: SessionMessage[] = [{ role: 'user', text: 'hi', toolUses: [] }]
    await $.session.compact({ trigger: 'manual', messages: history })
    expect(await prompt($, w)).toEqual(['TODO_SYNC drift=1 P1=1'])
    await $.session.compact({ trigger: 'precompute', messages: history })
    expect(await prompt($, w)).toEqual([])
  })

  test('todo.inject_context false attaches nothing', async ($, on) => {
    const w = world(on, { config: { todo: { ...CONFIG.todo, inject_context: false } } })
    w.engine.drift = 1
    w.engine.byRule = { P1: 1 }
    await start($, w)
    expect(await prompt($, w)).toEqual([])
    expect(w.notices).toContain('TODO sync drift 1 (+1): P1=1')
  })
})

describe('M3: tool calls', () => {
  test('a Write outside watched paths spawns no process; one on a watched path checks', async ($, on) => {
    const w = world(on)
    await start($, w)
    const before = w.runs.length
    expect(before).toBe(1)
    await write($, w, `${w.root}/src/a.py`)
    await write($, w, `${w.root}/docs/notes.md`)
    expect(w.runs.length).toBe(before)
    await write($, w, `${w.root}/docs/PLANS/b_PIP.md`)
    expect(w.runs.length).toBe(before + 1)
  })

  test('with no runner, no Write ever reaches process.run', async ($, on) => {
    const w = world(on, { hasRunner: false })
    await start($, w)
    await write($, w, `${w.root}/src/a.py`)
    await write($, w, catalogPath(w))
    expect(w.runs).toEqual([])
  })

  test('a Bash that leaves watched mtimes alone spawns nothing; one that moves one checks', async ($, on) => {
    const w = world(on)
    await start($, w)
    await bash($, w)
    await bash($, w)
    expect(w.runs.length).toBe(1)
    await w.clock.advance(1000)
    w.onBash = () => w.touch(catalogPath(w))
    await bash($, w)
    expect(checkRuns(w).length).toBe(2)
    w.onBash = () => undefined
    await bash($, w)
    expect(checkRuns(w).length).toBe(2)
  })

  test('a new file in a watched folder trips the Bash probe', async ($, on) => {
    const w = world(on)
    await start($, w)
    await w.clock.advance(1000)
    w.onBash = () => w.setFile(`${w.root}/docs/PLANS/new_PIP.md`, '- [ ] x')
    await bash($, w)
    expect(checkRuns(w).length).toBe(2)
  })

  test('PowerShell probes like Bash; Edit and NotebookEdit gate on their path', async ($, on) => {
    const w = world(on)
    await start($, w)
    await w.clock.advance(1000)
    w.onBash = () => w.touch(catalogPath(w))
    await $.tool.call({ tool: 'PowerShell', command: 'python gen.py' })
    await w.clock.settle()
    expect(checkRuns(w).length).toBe(2)
    await $.tool.call({ tool: 'Edit', file_path: `${w.root}/src/x.py`, old_string: 'a', new_string: 'b' })
    await $.tool.call({ tool: 'NotebookEdit', notebook_path: `${w.root}/nb/x.ipynb`, new_source: 'x' })
    await w.clock.settle()
    expect(checkRuns(w).length).toBe(2)
    await $.tool.call({ tool: 'Edit', file_path: `${w.root}/docs/PLANS/a.md`, old_string: 'a', new_string: 'b' })
    await w.clock.settle()
    expect(checkRuns(w).length).toBe(3)
  })

  test('a burst coalesces: one run in flight, one owed', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.engine.isHeld = true
    await write($, w, catalogPath(w))
    await write($, w, catalogPath(w))
    await write($, w, catalogPath(w))
    expect(checkRuns(w).length).toBe(2)
    w.engine.isHeld = false
    w.held.shift()?.()
    await w.clock.settle()
    expect(checkRuns(w).length).toBe(3)
    await w.clock.settle()
    expect(checkRuns(w).length).toBe(3)
  })

  test('the check run is capped', async ($, on) => {
    expect(CHECK_TIMEOUT_MS).toBe(20_000)
    const w = world(on)
    await start($, w)
    expect(checkRuns(w).length).toBe(1)
    const index = w.runs.findIndex(argv => argv[2] === 'check')
    expect(w.inits[index]?.timeoutMs).toBe(CHECK_TIMEOUT_MS)
  })
})

describe('M3b: edits made outside the session', () => {
  test('an IDE-side mtime change trips the probe on prompt.submit', async ($, on) => {
    const w = world(on)
    await start($, w)
    await prompt($, w)
    expect(checkRuns(w).length).toBe(1)
    await w.clock.advance(1000)
    w.touch(`${w.root}/${RESEARCH_CATALOG_REL}`)
    await prompt($, w)
    expect(checkRuns(w).length).toBe(2)
    await prompt($, w)
    expect(checkRuns(w).length).toBe(2)
  })

  test('and on turn.complete', async ($, on) => {
    const w = world(on)
    await start($, w)
    await w.clock.advance(1000)
    w.touch(`${w.root}/${SNAPSHOTS_REL}/TODO_Snapshot_2026_1017.md`)
    await turnEnd($, w)
    expect(checkRuns(w).length).toBe(2)
  })

  test('an in-place stub edit one level under the research folder trips the probe', async ($, on) => {
    const w = world(on)
    const stub = `${w.root}/docs/RESEARCH/HYDRO/_IMPL_TODO.md`
    w.setFile(stub, 'status: OPEN', NOW - HOUR)
    await start($, w)
    expect(checkRuns(w).length).toBe(1)
    await w.clock.advance(1000)
    w.touch(stub)
    await prompt($, w)
    expect(checkRuns(w).length).toBe(2)
  })
})

describe('fail open', () => {
  test('a process timeout shows nothing and throws nothing', async ($, on) => {
    const w = world(on)
    w.engine.mode = 'timeout'
    await start($, w)
    expect(checkRuns(w).length).toBe(1)
    expect(w.notices).toEqual([CATALOG_LINE])
    expect(await prompt($, w)).toEqual([])
    expect(await runTodo($)).toContain('no report yet')
    await write($, w, catalogPath(w))
    expect(checkRuns(w).length).toBe(2)
  })

  test('a non-zero exit shows nothing', async ($, on) => {
    const w = world(on)
    w.engine.mode = 'fail'
    w.setFile(`${w.root}/${SYNC_REL}/report.json`, '{"broken": true}', NOW + 1)
    await start($, w)
    expect(await prompt($, w)).toEqual([])
    expect(w.notices).toEqual([CATALOG_LINE])
  })

  test('a malformed report changes nothing shown', async ($, on) => {
    const w = world(on)
    await start($, w)
    w.setFile(`${w.root}/${SYNC_REL}/report.json`, '{"schema_version": 1}', NOW + 10)
    w.engine.mode = 'fail'
    expect(await prompt($, w)).toEqual(['TODO_SYNC drift=0'])
  })
})

describe('the runner pointer', () => {
  test('one that appears after session.start is picked up on the first prompt, and the check runs', async ($, on) => {
    const w = world(on, { hasRunner: false })
    w.engine.drift = 1
    w.engine.byRule = { S5: 1 }
    await start($, w)
    expect(w.runs).toEqual([])
    w.addRunner()
    expect(await prompt($, w)).toEqual([])
    expect(checkRuns(w).length).toBe(1)
    expect(await prompt($, w)).toEqual(['TODO_SYNC drift=1 S5=1'])
  })

  test('or on the first turn.complete', async ($, on) => {
    const w = world(on, { hasRunner: false })
    await start($, w)
    w.addRunner()
    await turnEnd($, w)
    expect(checkRuns(w).length).toBe(1)
  })

  test('none after the retry: sync checks unavailable, once on the context line, no toast', async ($, on) => {
    const w = world(on, { hasRunner: false })
    await start($, w)
    expect(await runTodo($)).toContain('no report yet')
    expect(await prompt($, w)).toEqual(['TODO_SYNC unavailable'])
    expect(await prompt($, w)).toEqual([])
    expect(await runTodo($)).toContain('sync checks unavailable')
    expect(w.notices).toEqual([CATALOG_LINE])
    w.addRunner()
    await prompt($, w)
    expect(w.runs).toEqual([])
  })

  test('a pointer whose script is gone is no pointer', async ($, on) => {
    const w = world(on)
    w.files.delete(SCRIPT)
    await start($, w)
    expect(await prompt($, w)).toEqual(['TODO_SYNC unavailable'])
    expect(w.runs).toEqual([])
  })
})

describe('inactive', () => {
  for (const [label, config] of [
    ['todo.folder null', { todo: { folder: null } }],
    ['no harness.json', null],
  ] as const) {
    test(`${label}: no command, no toast, no process, no context`, async ($, on) => {
      const w = world(on, { config })
      on('command.run', () => ({ text: 'beneath' }))
      await start($, w)
      expect(await prompt($, w)).toEqual([])
      await write($, w, catalogPath(w))
      await bash($, w)
      await turnEnd($, w)
      expect([w.commands, w.notices, w.runs]).toEqual([[], [], []])
      expect(await runTodo($)).toBe('beneath')
    })
  }
})

describe('project roots', () => {
  for (const root of ['C:/repo', '/repo']) {
    test(`${root}: start toast, watched writes in either slash style, the project argument`, async ($, on) => {
      const w = world(on, { root })
      await start($, w)
      expect(w.notices).toEqual([CATALOG_LINE])
      await write($, w, `${root}/docs/PLANS/a.md`.replace(/\//g, '\\'))
      await write($, w, CATALOG_REL)
      await write($, w, `${root}/src/a.py`)
      expect(checkRuns(w).map(argv => argv[4])).toEqual([root, root, root])
    })
  }
})
