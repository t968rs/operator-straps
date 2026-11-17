import type { EngineInterface, Register } from 'claude-code'
import { atom, update } from 'claude-code'

import type { GitSnapshot, SessionFigures } from '../types'

/**
 * The oStraps banner: its text, and the session figures it shows beside git-status's snapshot.
 *
 * git-status owns the snapshot (its `git` state); this mod reads it and keeps the main loop's model and
 * context window in its own `session` state. While this mod is loaded, git-status's own status line is
 * cleared, so the banner is the one place the git state shows.
 */

type Dollar = EngineInterface

/** No reading of the session yet. */
export const NO_FIGURES: SessionFigures = { model: null, ctxTokens: null, ctxPercent: null }
const sessionState = atom({ plugin: 'band-line', key: 'session' } as const, NO_FIGURES)

/** Background refresh period of the session figures, in milliseconds. */
export const TICK_MS = 60_000
/** The plugin whose status line the banner replaces. */
export const GIT_STATUS_PLUGIN = 'git-status'

const MAX_BRANCH = 32
/** The banner's label; the engine draws a plugin's own status line under the plugin's name instead. */
const LABEL = 'oStraps:'
const WARNING = '⚠ '
/** Fewest characters the clipped head keeps, so a very narrow band still shows its label. */
const MIN_HEAD = 12
const MAX_MODEL = 24

// ---------------------------------------------------------------------------
// Pure formatting

/** Whole-string truncation with an ellipsis. */
const clip = (text: string, max: number): string => (text.length <= max ? text : `${text.slice(0, max - 1)}…`)

/** The branch segment: name, then ahead/behind or "no upstream". */
const branchSegment = (g: GitSnapshot): string => {
  const head = `⎇ ${clip(g.branch || '?', MAX_BRANCH)}`
  if (g.upstream === null) return `${head} no upstream`
  return g.ahead > 0 || g.behind > 0 ? `${head} ↑${g.ahead} ↓${g.behind}` : head
}

/** The working-tree segment: non-zero counts, or "clean". */
const treeSegment = (g: GitSnapshot): string => {
  const parts: string[] = []
  if (g.staged > 0) parts.push(`+${g.staged}`)
  if (g.unstaged > 0) parts.push(`~${g.unstaged}`)
  if (g.untracked > 0) parts.push(`?${g.untracked}`)
  return parts.length === 0 ? 'clean' : parts.join(' ')
}

/** The commit-count segment: commits only the remote has (behind), then commits only the local branch has (ahead). */
const commitsSegment = (g: GitSnapshot): string => ` · (R,L):${g.behind},${g.ahead}`

/** A branch that tracks nothing, or a detached head: the states worth a glance. */
export const needsAttention = (g: GitSnapshot): boolean => g.upstream === null

const cap = (word: string): string => word.charAt(0).toUpperCase() + word.slice(1)

/**
 * A model id as a short name: `claude-sonnet-5-5` is `Sonnet 5.5`; a date stamp or a `[1m]` suffix is dropped,
 * an alias is capitalized and any other id is kept, clipped.
 */
export const modelLabel = (id: string): string => {
  const bare = id.replace(/\[[^\]]*\]$/, '')
  const m = bare.match(/^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$/)
  if (m !== null) return `${cap(m[1] ?? '')} ${m[2]}${m[3] === undefined ? '' : `.${m[3]}`}`
  return /^[a-z]+$/.test(bare) ? cap(bare) : clip(bare, MAX_MODEL)
}

/** `850`, `110k`, `1.3M`. */
const tokenSize = (tokens: number): string => {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`
  return tokens >= 1000 ? `${Math.round(tokens / 1000)}k` : `${tokens}`
}

/** The context segment, `ctx:110k 11%`; undefined without a token count (a fresh or just compacted session). */
export const ctxLabel = (tokens: number | null, percent: number | null): string | undefined => {
  if (tokens === null) return undefined
  const size = tokenSize(tokens)
  return percent === null ? `ctx:${size}` : `ctx:${size} ${percent}%`
}

/** The session segment, ` | [Sonnet 5.5] · ctx:110k 11%`, each part left out while unknown; empty when both are. */
const sessionSegment = (s: SessionFigures): string => {
  const parts = [s.model === null ? undefined : `[${modelLabel(s.model)}]`, ctxLabel(s.ctxTokens, s.ctxPercent)]
  const shown = parts.filter((p): p is string => p !== undefined)
  return shown.length === 0 ? '' : ` | ${shown.join(' · ')}`
}

/**
 * The banner: label, branch, tree, commit counts, then the session figures. When it runs over `columns`
 * the branch and tree are clipped; the commit counts and the session figures are kept whole.
 */
export const formatBanner = (g: GitSnapshot, s: SessionFigures, columns = 120): string => {
  const tail = `${commitsSegment(g)}${sessionSegment(s)}`
  const head = `${needsAttention(g) ? WARNING : ''}${LABEL} ${branchSegment(g)} · ${treeSegment(g)}`
  return clip(head, Math.max(columns - tail.length, MIN_HEAD)) + tail
}

// ---------------------------------------------------------------------------
// Session figures

/** The main loop's model and context window as the engine reports them; a refusal leaves a figure null. */
const readFigures = async ($: Dollar): Promise<SessionFigures> => {
  const model = await $.session.model().catch(() => undefined)
  const usage = await $.session.usage().catch(() => undefined)
  return {
    model: model === undefined || model === '' ? null : model,
    ctxTokens: usage?.context.tokens ?? null,
    ctxPercent: usage?.context.percent ?? null,
  }
}

const sameFigures = (a: SessionFigures, b: SessionFigures): boolean =>
  a.model === b.model && a.ctxTokens === b.ctxTokens && a.ctxPercent === b.ctxPercent

/** Stores the session figures when they moved, so an unchanged reading never redraws; never throws. */
const refreshSession = async ($: Dollar): Promise<void> => {
  const next = await readFigures($).catch(() => NO_FIGURES)
  await update($, sessionState, prev => (sameFigures(prev, next) ? prev : next)).catch(() => undefined)
}

/** The periodic refresh of the session figures (a reload starts afresh). */
const ticking = { tick: undefined as { cancel: () => void } | undefined }

/** (Re)starts the periodic refresh; a timer costs no model tokens. */
const startTicking = ($: Dollar): void => {
  try {
    ticking.tick?.cancel()
    ticking.tick = $.clock.every(TICK_MS, () => void refreshSession($))
  } catch {
    ticking.tick = undefined
  }
}

// ---------------------------------------------------------------------------
// Registration

/** Registers the session-figure refresh triggers and clears git-status's own status line. */
export const registerBanner = (on: Parameters<Register>[0]): void => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    startTicking($)
    await refreshSession($)
    return started
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    await refreshSession($)
    return result
  })

  on('prompt.submit', async ($, e, next) => {
    await refreshSession($)
    return next(e)
  }).catch((_$, e, next) => next(e))

  on('ui.status', async (_$, e, next) => (next.origin.plugin === GIT_STATUS_PLUGIN ? next({ ...e, text: undefined }) : next(e)))
    .catch((_$, e, next) => next(e))
}
