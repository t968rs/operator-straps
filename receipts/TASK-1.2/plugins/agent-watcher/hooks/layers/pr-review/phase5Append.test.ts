import type { FsEntry, On, ProcessRunResult } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

/**
 * The `PHASE5_PENDING=` line's `session.append` fallback: a main-loop compaction row re-forces the line
 * when no `session.compact` dispatch reached the layer; a subagent's row or another door does not.
 */

const ROOT = '/repo'
const NOW_MS = 1_800_000_000_000
const NOW_S = NOW_MS / 1000
const DIR = `${ROOT}/.claude/state/harness/pr-review`
const HOT: Record<string, string> = { '.phase5_pending_1526': `1526\n${NOW_S - 60}\n` }

const slash = (p: string): string => p.replace(/\\/g, '/').replace(/^[A-Za-z]:/, '')
const entry = (name: string): FsEntry => ({ name, kind: 'file', size: 10, mtimeMs: 0, isLink: false })
const gitFailed: ProcessRunResult = {
  exitCode: 128, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
}

/** Env, cwd, a failing git, one hot sentinel under ROOT, an empty harness.json and core's prompt echo. */
const world = (on: On): void => {
  mock.env(on, { CLAUDE_PROJECT_DIR: ROOT })
  mock.clock(on, { now: NOW_MS })
  on('session.cwd', () => ({ value: ROOT }))
  on('process.run', () => ({ value: gitFailed }))
  on('prompt.submit', (_$, e) => ({ text: e.text, context: e.context }))
  on('fs.list', (_$, e) =>
    slash(e.path) === DIR ? { value: Object.keys(HOT).map(entry) } : { deny: `ENOENT ${e.path}` },
  )
  on('fs.read', (_$, e) => {
    const path = slash(e.path)
    if (path === `${ROOT}/.claude/harness.json`) return { value: '{}' }
    const text = HOT[path.slice(path.lastIndexOf('/') + 1)]
    return text === undefined ? { deny: `ENOENT ${e.path}` } : { value: text }
  })
  on('fs.stat', (_$, e) => ({ deny: `ENOENT ${e.path}` }))
}

const submit = { text: 'hello', wait: false, origin: { kind: 'composer' } } as const

/** A row reaching `session.append`: the main loop's unless `agentId`, by the compaction door unless `door`. */
const row = (agentId?: string, door: 'compaction' | 'note' = 'compaction') => ({
  message: { type: 'user' as const, role: 'user' as const, content: [{ type: 'text' as const, text: 'summary' }] },
  door,
  origin: { kind: 'engine' as const },
  uuid: `u-${agentId ?? 'main'}-${door}`,
  ...(agentId === undefined ? {} : { agentId }),
})

describe('the context line after a compaction row', () => {
  test('a compaction row with no session.compact dispatch re-forces the line; a subagent row does not', async ($, on) => {
    world(on)
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1526'])
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
    await $.session.append(row('sub-1'))
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
    await $.session.append(row(undefined, 'note'))
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
    await $.session.append(row())
    expect((await $.prompt.submit(submit)).context).toEqual(['PHASE5_PENDING=1526'])
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
  })
})
