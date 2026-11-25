import type { On, ProcessRunResult } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

/**
 * The GIT_STATE line's `session.append` fallback: a main-loop compaction row re-forces the line when no
 * `session.compact` dispatch reached the mod; a subagent's row or another door does not.
 */

const ROOT = '/repo'

const CLEAN = [
  '# branch.oid 0123456789abcdef0123456789abcdef01234567',
  '# branch.head dev',
  '# branch.upstream origin/dev',
  '# branch.ab +0 -0',
].join('\n')

const CLEAN_CONTEXT =
  'GIT_STATE BRANCH=dev UPSTREAM=origin/dev AHEAD=0 BEHIND=0 STAGED=0 UNSTAGED=0 UNTRACKED=0 DIRTY=false'

const ran = (stdout: string): ProcessRunResult => ({
  exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})

/** Env, session cwd, a clean repo at ROOT, the status line and core's prompt echo. */
const world = (on: On): void => {
  mock.env(on, { CLAUDE_PROJECT_DIR: ROOT })
  on('session.cwd', () => ({ value: '' }))
  on('ui.status', () => ({ value: undefined }))
  on('prompt.submit', (_$, e) => ({ text: e.text, context: e.context }))
  on('settings.read', () => ({ value: {} }))
  on('fs.exists', () => ({ value: false }))
  on('process.run', (_$, e) => ({ value: e.argv[3] === 'rev-parse' ? ran(`${e.argv[2] ?? ''}\n`) : ran(CLEAN) }))
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
    expect((await $.prompt.submit(submit)).context).toEqual([CLEAN_CONTEXT])
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
    await $.session.append(row('sub-1'))
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
    await $.session.append(row(undefined, 'note'))
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
    await $.session.append(row())
    expect((await $.prompt.submit(submit)).context).toEqual([CLEAN_CONTEXT])
    expect((await $.prompt.submit(submit)).context ?? []).toEqual([])
  })
})
