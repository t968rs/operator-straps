import type { On } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

const RUN = 'pr1526_20261009T120000Z'
const NOW = 1_800_000_000_000
const BAND = {
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 80, scroll: { offset: 0, bodyRows: 10 }, view: {} },
} as const

const slash = (p: string): string => p.replace(/\\/g, '/').replace(/^[A-Za-z]:/, '')
const baseName = (p: string): string => slash(p).slice(slash(p).lastIndexOf('/') + 1)
const asFile = (name: string) => ({ name, kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false })

/**
 * The sentinel folder (by file name), other files by `/repo/...` path (listed one folder deep) and an
 * Agent tool that launches in the background.
 */
const world = (on: On, sentinels: Record<string, string> = {}, extra: Record<string, string> = {}): void => {
  const files: Record<string, string> = { '/repo/.claude/harness.json': '{}', ...extra }
  mock.env(on, { CLAUDE_PROJECT_DIR: '/repo' })
  mock.clock(on, { now: NOW })
  on('session.cwd', () => ({ value: '/repo' }))
  on('fs.list', (_$, e) => {
    const dir = slash(e.path)
    if (dir.endsWith('/.claude/state/harness/pr-review')) return { value: Object.keys(sentinels).map(asFile) }
    const inDir = Object.keys(files).filter(p => p.startsWith(`${dir}/`) && !p.slice(dir.length + 1).includes('/'))
    return { value: inDir.map(p => asFile(baseName(p))) }
  })
  on('fs.read', (_$, e) => {
    const text = files[slash(e.path)] ?? sentinels[baseName(e.path)]
    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  on('fs.stat', () => ({ deny: 'ENOENT' }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  // Core's own band: an empty box, drawn whenever the plugin passes.
  on('ui.render', ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  on('tool.call', { tool: 'Agent' }, () => ({
    result: { status: 'async_launched', agentId: 'l1', description: '', prompt: '', outputFile: '' },
    text: '',
  }) as never)
}

describe('band', () => {
  test('quiet with no run and no sentinel', async ($, on) => {
    world(on)
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ plugin: 'pr-review-watch', surface, ...BAND })
      expect(await ui.find({ type: 'Text', text: /^PR #/ })).toBeUndefined()
      await ui.unmount()
    }
  })

  test('an active run and another PR with a hot sentinel', async ($, on) => {
    world(on, { '.phase5_pending_1400': `1400\n${NOW / 1000 - 60}\n` })
    await $.tool.call({
      tool: 'Agent', description: 'r', subagent_type: 'x', prompt: `AGENT_ID: r1\nAGENT_ROLE: reviewer\nRUN_ID: ${RUN}`,
    })
    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ plugin: 'pr-review-watch', surface, ...BAND })
      const band = await ui.find({ type: 'Text', text: /^PR #/ })
      expect(band?.text).toBe('PR #1526 · reviewers 0/1 | PR #1400 · Phase 5 pending')
      await ui.unmount()
    }
  })

  test('pr-review fixing under a hot sentinel: phase, then the marker, then fixer bubbles', async ($, on) => {
    const dir = `/repo/docs/_scratch/pr_review/1526/${RUN}`
    const fix = { fixer: 'w1_fix_1', fixed: [], bubbled: [{ id: 'I9', classification: 'out_of_scope', reason: 'r' }] }
    world(on, { '.phase5_pending_1526': `1526\n${NOW / 1000 - 60}\n` }, {
      '/repo/docs/_scratch/pr_review/1526/current': `${RUN}\n`,
      [`${dir}/plan.json`]: JSON.stringify({ run_id: RUN, pr: 1526, phase: 'fix' }),
      [`${dir}/fixes/w1_fix_1.json`]: JSON.stringify(fix),
    })
    for (const id of ['w1_fix_1', 'w1_fix_2']) {
      const prompt = `AGENT_ID: ${id}\nAGENT_ROLE: fixer\nRUN_ID: ${RUN}\nPR: 1526`
      await $.tool.call({ tool: 'Agent', description: 'f', subagent_type: 'pr-fixer', prompt })
    }
    const ui = await $.ui.mount({ plugin: 'pr-review-watch', surface: 'terminal', ...BAND })
    const band = await ui.find({ type: 'Text', text: /^PR #/ })
    expect(band?.text).toBe('PR #1526 · fixers 0/2 · Phase 5 pending · 1 bubbled')
    await ui.unmount()
  })

  test('pr-review consolidating: the plan.json phase replaces the reviewer count', async ($, on) => {
    const dir = `/repo/docs/_scratch/pr_review/1526/${RUN}`
    world(on, {}, {
      '/repo/docs/_scratch/pr_review/1526/current': `${RUN}\n`,
      [`${dir}/plan.json`]: JSON.stringify({ run_id: RUN, pr: 1526, phase: 'consolidate' }),
    })
    const prompt = `AGENT_ID: r1\nAGENT_ROLE: reviewer\nRUN_ID: ${RUN}\nPR: 1526`
    await $.tool.call({ tool: 'Agent', description: 'r', subagent_type: 'pr-reviewer', prompt })
    const ui = await $.ui.mount({ plugin: 'pr-review-watch', surface: 'terminal', ...BAND })
    expect((await ui.find({ type: 'Text', text: /^PR #/ }))?.text).toBe('PR #1526 · consolidating')
    await ui.unmount()
  })
})
