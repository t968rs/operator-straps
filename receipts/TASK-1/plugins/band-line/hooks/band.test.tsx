import type { On } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import type { Engine } from 'claude-code/testing'

import type { GitSnapshot, SessionFigures } from '../types'
import { ctxLabel, formatBanner, modelLabel, needsAttention, NO_FIGURES, TICK_MS } from './banner'

const ROOT = '/repo'
const NOW_MS = 1_800_000_000_000

const snapshot = (over: Partial<GitSnapshot> = {}): GitSnapshot => ({
  branch: 'dev', upstream: 'origin/dev', ahead: 0, behind: 0,
  staged: 0, unstaged: 0, untracked: 0, ...over,
})

const figures = (over: Partial<SessionFigures> = {}): SessionFigures => ({
  model: 'claude-sonnet-5-5', ctxTokens: 110_000, ctxPercent: 11, ...over,
})

// ---------------------------------------------------------------------------
// The world beneath the plugin

type World = {
  /** git-status's snapshot as its state holds it; null before its first run. Unset is a clean `dev`. */
  git?: GitSnapshot | null
  /** `$.session.model()` and `$.session.usage()` refuse. */
  isSessionBroken?: boolean
  /** `$.session.model()`'s answer; unset is Sonnet 5.5. */
  model?: string
  /** `$.session.usage().context`; unset is 110000 tokens of a 1M window (11%); null is a fresh session. */
  context?: { tokens?: number; percent?: number; window: number } | null
}

/** Answers git-status's snapshot, the session figures, core's band and the session events from memory. */
const world = (on: On, w: World = {}): void => {
  on('state.get', (_$, e, next) =>
    e.plugin === 'git-status' && e.key === 'git'
      ? { value: { value: w.git === undefined ? snapshot() : w.git, version: 1 } }
      : next(e),
  )
  on('ui.render', ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  on('session.model', () => (w.isSessionBroken ? { deny: 'no session' } : { value: w.model ?? 'claude-sonnet-5-5' }))
  on('session.usage', () => {
    if (w.isSessionBroken) return { deny: 'no session' }
    const context = w.context === undefined ? { tokens: 110_000, percent: 11, window: 1_000_000 }
      : w.context ?? { window: 1_000_000 }
    return { value: { startedAt: 0, context, rateLimits: [] } }
  })
  on('prompt.submit', (_$, e) => ({ text: e.text, context: e.context }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
}

const submit = { text: 'hello', wait: false, origin: { kind: 'composer' } } as const
const BAND = {
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 120, scroll: { offset: 0, bodyRows: 10 }, view: {} },
} as const

/** The banner text the band draws now, or undefined when it draws none. */
const banner = async ($: Engine, columns = 120): Promise<string | undefined> => {
  const ui = await $.ui.mount({ plugin: 'band-line', surface: 'terminal', ...BAND, props: { ...BAND.props, bodyColumns: columns } })
  const text = (await ui.find({ type: 'Text', text: /oStraps:/ }))?.text
  await ui.unmount()
  return text
}

const turnEnd = ($: Engine, turnId: string) =>
  $.turn.complete({ answer: 'ok', durationMs: 5, isAborted: false, turnId, reason: 'answer' })

// ---------------------------------------------------------------------------
// Pure: the banner text

describe('formatBanner', () => {
  test('the full line: label, branch, tree, commit counts, model and context', async () => {
    const g = snapshot({ ahead: 1, staged: 2, unstaged: 3, untracked: 1 })
    expect(formatBanner(g, figures())).toBe(
      'oStraps: ⎇ dev ↑1 ↓0 · +2 ~3 ?1 · (R,L):0,1 | [Sonnet 5.5] · ctx:110k 11%',
    )
  })

  test('clean and in sync omits zero segments but keeps the commit counts', async () => {
    expect(formatBanner(snapshot(), NO_FIGURES)).toBe('oStraps: ⎇ dev · clean · (R,L):0,0')
  })

  test('no upstream carries the warning glyph', async () => {
    const g = snapshot({ upstream: null, branch: '9998-banner-sunset' })
    expect(formatBanner(g, figures())).toBe(
      '⚠ oStraps: ⎇ 9998-banner-sunset no upstream · clean · (R,L):0,0 | [Sonnet 5.5] · ctx:110k 11%',
    )
  })

  test('detached head shows as such, with the glyph', async () => {
    const text = formatBanner(snapshot({ branch: '(detached)', upstream: null }), NO_FIGURES)
    expect(text).toBe('⚠ oStraps: ⎇ (detached) no upstream · clean · (R,L):0,0')
  })

  test('remote-only commits are R (behind), local-only commits are L (ahead)', async () => {
    expect(formatBanner(snapshot({ ahead: 3, behind: 7 }), NO_FIGURES)).toBe(
      'oStraps: ⎇ dev ↑3 ↓7 · clean · (R,L):7,3',
    )
  })

  test('only an upstream-less or detached branch needs attention', async () => {
    expect(needsAttention(snapshot())).toBe(false)
    expect(needsAttention(snapshot({ unstaged: 9, ahead: 4, behind: 4 }))).toBe(false)
    expect(needsAttention(snapshot({ upstream: null }))).toBe(true)
  })

  test('segments with no figure are left out, never zeroed', async () => {
    const g = snapshot()
    expect(formatBanner(g, figures({ ctxTokens: null, ctxPercent: null }))).toBe(
      'oStraps: ⎇ dev · clean · (R,L):0,0 | [Sonnet 5.5]',
    )
    expect(formatBanner(g, figures({ model: null }))).toBe('oStraps: ⎇ dev · clean · (R,L):0,0 | ctx:110k 11%')
  })

  test('a narrow band clips the branch and tree, never the counts, model or context', async () => {
    const g = snapshot({
      branch: `feature/${'x'.repeat(90)}`, ahead: 12, behind: 345, staged: 99, unstaged: 99, untracked: 99,
    })
    const text = formatBanner(g, figures(), 100)
    expect(text.length).toBeLessThanOrEqual(100)
    expect(text.startsWith(`oStraps: ⎇ feature/${'x'.repeat(23)}…`)).toBe(true)
    expect(text.endsWith(' · (R,L):345,12 | [Sonnet 5.5] · ctx:110k 11%')).toBe(true)
  })

  test('a band too narrow for the tail still keeps the tail whole', async () => {
    const g = snapshot({ branch: 'x'.repeat(40), ahead: 123456, behind: 654321 })
    const text = formatBanner(g, figures(), 20)
    expect(text.endsWith(' · (R,L):654321,123456 | [Sonnet 5.5] · ctx:110k 11%')).toBe(true)
    expect(text.startsWith('oStraps:')).toBe(true)
  })
})

describe('modelLabel', () => {
  test('a family id reads as its name and version', async () => {
    expect(modelLabel('claude-sonnet-5-5')).toBe('Sonnet 5.5')
    expect(modelLabel('claude-opus-5-5')).toBe('Opus 5.5')
    expect(modelLabel('claude-fable-5-1')).toBe('Fable 5.1')
    expect(modelLabel('claude-haiku-5')).toBe('Haiku 5')
  })

  test('a date stamp or a context-window suffix is dropped', async () => {
    expect(modelLabel('claude-sonnet-5-5-20261001')).toBe('Sonnet 5.5')
    expect(modelLabel('claude-opus-5-5[1m]')).toBe('Opus 5.5')
  })

  test('an alias is capitalized; any other id is kept, clipped', async () => {
    expect(modelLabel('opus')).toBe('Opus')
    expect(modelLabel('my-gateway/model-x')).toBe('my-gateway/model-x')
    expect(modelLabel(`gw/${'m'.repeat(60)}`).length).toBe(24)
  })
})

describe('ctxLabel', () => {
  test('tokens in thousands, then the percentage', async () => {
    expect(ctxLabel(110_000, 11)).toBe('ctx:110k 11%')
    expect(ctxLabel(110_499, 11)).toBe('ctx:110k 11%')
    expect(ctxLabel(850, 0)).toBe('ctx:850 0%')
  })

  test('millions get one decimal; a missing percentage is left out', async () => {
    expect(ctxLabel(1_250_000, 63)).toBe('ctx:1.3M 63%')
    expect(ctxLabel(40_000, null)).toBe('ctx:40k')
  })

  test('no token count, no segment', async () => {
    expect(ctxLabel(null, 11)).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// The band

const SONNET_LINE = 'oStraps: ⎇ dev · clean · (R,L):0,0 | [Sonnet 5.5] · ctx:110k 11%'

describe('the oStraps band', () => {
  test('the first prompt draws the full banner from git-status\'s snapshot', async ($, on) => {
    world(on)
    await $.prompt.submit(submit)
    expect(await banner($)).toBe(SONNET_LINE)
  })

  test('no snapshot from git-status yet: no banner', async ($, on) => {
    world(on, { git: null })
    await $.prompt.submit(submit)
    expect(await banner($)).toBeUndefined()
  })

  test('the context figures follow each turn', async ($, on) => {
    const w: World = {}
    world(on, w)
    await $.prompt.submit(submit)
    w.context = { tokens: 250_000, percent: 25, window: 1_000_000 }
    await turnEnd($, 't1')
    expect(await banner($)).toBe(SONNET_LINE.replace('ctx:110k 11%', 'ctx:250k 25%'))
  })

  test('a model switch shows at the next prompt', async ($, on) => {
    const w: World = {}
    world(on, w)
    await $.prompt.submit(submit)
    w.model = 'claude-opus-5-5'
    await $.prompt.submit(submit)
    expect(await banner($)).toBe(SONNET_LINE.replace('Sonnet', 'Opus'))
  })

  test('a fresh session shows the model but no context until its first response', async ($, on) => {
    world(on, { context: null })
    await $.prompt.submit(submit)
    expect(await banner($)).toBe('oStraps: ⎇ dev · clean · (R,L):0,0 | [Sonnet 5.5]')
  })

  test('a session that refuses its figures still shows the git part', async ($, on) => {
    world(on, { isSessionBroken: true })
    await $.prompt.submit(submit)
    expect(await banner($)).toBe('oStraps: ⎇ dev · clean · (R,L):0,0')
  })

  test('session.start reads the session, then every 60 s', async ($, on) => {
    const clock = mock.clock(on, { now: NOW_MS })
    const w: World = {}
    world(on, w)
    await $.session.start({ cwd: ROOT, surface: null, isInteractive: false })
    await clock.settle()
    expect(await banner($)).toBe(SONNET_LINE)
    w.context = { tokens: 300_000, percent: 30, window: 1_000_000 }
    await clock.advance(TICK_MS)
    expect(await banner($)).toBe(SONNET_LINE.replace('ctx:110k 11%', 'ctx:300k 30%'))
  })

  test('no upstream: the band warns', async ($, on) => {
    world(on, { git: snapshot({ branch: 'topic', upstream: null }) })
    await $.prompt.submit(submit)
    expect(await banner($)).toBe('⚠ oStraps: ⎇ topic no upstream · clean · (R,L):0,0 | [Sonnet 5.5] · ctx:110k 11%')
  })

  test('another band is kept: the banner wraps what the hooks beneath drew', async ($, on) => {
    // registered ahead of core's stand-in band, which answers for whatever is beneath it
    on('ui.render', { component: 'AbovePrompt' }, ($$, e) => {
      const { Box, Text } = $$.ui.resolve(e)
      return <Box><Text>PR #1526 · reviewers 0/1</Text></Box>
    })
    world(on)
    await $.prompt.submit(submit)
    const ui = await $.ui.mount({ plugin: 'band-line', surface: 'terminal', ...BAND })
    expect((await ui.findAll({ type: 'Text' })).map(t => t.text)).toEqual([SONNET_LINE, 'PR #1526 · reviewers 0/1'])
    await ui.unmount()
  })

  test('no banner draws while a survey holds the band', async ($, on) => {
    world(on)
    await $.prompt.submit(submit)
    const ui = await $.ui.mount({ plugin: 'band-line', surface: 'terminal', ...BAND, props: { ...BAND.props, hasSurvey: true } })
    expect(await ui.find({ type: 'Text', text: /oStraps:/ })).toBeUndefined()
    await ui.unmount()
  })
})
