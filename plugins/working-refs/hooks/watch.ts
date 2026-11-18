import type { EngineInterface, On } from 'claude-code'
import { atom, read, update } from 'claude-code'

import type { WorkingLine } from '../types'
import { lineFileOf, overridesFileOf, plansFolderOf, readConfig, type WorkingRefsConfig } from './config'
import { buildLine, statusText } from './line'
import { PIP_HTML_SUFFIX, PLAN_SUFFIX } from './mirror'
import { parseOverrides } from './overrides'
import { archivedIdsOf, type MergeBaseOf, pageOf, parsePlan, type PlanInfo, qualifies } from './plans'

/**
 * Engine glue for working-refs: finds the project, scans its plans folder, runs git for the archive tags, HEAD
 * and the merge bases (plan 2025 D9), and stores the branch's working line in the `line` atom and the
 * ccstatusline form in `<state_dir>/working-refs/line.txt` (D6). Scans run at `session.start`, when
 * git-status's snapshot names another branch, when HEAD or the archive tags moved at a prompt, and when the
 * plans folder's signature or the override file's mtime moved after a file or shell tool call or at a prompt.
 * Every host failure degrades to an empty line; no hook throws into a tool call, a prompt or a session start.
 * Functions taking `$` are function declarations: the engine follows `$` past an import only into one.
 */

type Dollar = EngineInterface

/** Longest one git call may take, in milliseconds. */
export const GIT_TIMEOUT_MS = 10_000
/** Tools whose calls may write a plan, its page or the override file. */
export const WATCH_TOOLS = /^(Bash|PowerShell|Edit|MultiEdit|Write)$/
/** `<root>/.claude/harness.json`. */
export const HARNESS_CONFIG_REL = '.claude/harness.json'
/** Folders above the cwd that are looked in for the project, at most. */
export const MAX_DEPTH = 32

const ARCHIVE_REFS = 'refs/tags/archive/plan/'

const noop = (): undefined => undefined

const gitAtom = atom({ plugin: 'git-status', key: 'git' } as const, null)
const lineAtom = atom({ plugin: 'working-refs', key: 'line' } as const, null)

// ---------------------------------------------------------------------------
// Pure: the project root rule (todo-watch root.ts) and the folder signature

/** The project the scans serve: its root (forward slashes) and its configuration. */
export type Watch = { root: string; cfg: WorkingRefsConfig }

/** Forward slashes, no trailing slash (`/` stays `/`); undefined when blank. */
export const normalDir = (v: string | undefined): string | undefined => {
  const t = (v ?? '').trim().replace(/\\/g, '/')
  if (t === '') return undefined
  const s = t.replace(/\/+$/, '')
  return s === '' ? '/' : s
}

/** The folder above `dir`, or undefined at a filesystem root (`/`, `C:`, `//host/share`). */
export const parentOf = (dir: string): string | undefined => {
  const cut = dir.lastIndexOf('/')
  if (cut < 0 || dir === '/' || /^\/\/[^/]+\/[^/]+$/.test(dir)) return undefined
  return cut === 0 ? '/' : dir.slice(0, cut)
}

/** Candidate roots in probe order: the cwd and the folders above it, then CLAUDE_PROJECT_DIR; repeats dropped. */
export const rootCandidates = (rawEnv: string | undefined, rawCwd: string | undefined): string[] => {
  const out: string[] = []
  const add = (c: string | undefined): void => {
    if (c !== undefined && !out.some(o => o.toLowerCase() === c.toLowerCase())) out.push(c)
  }
  let cur = normalDir(rawCwd)
  for (let depth = 0; cur !== undefined && depth <= MAX_DEPTH; depth += 1, cur = parentOf(cur)) add(cur)
  add(normalDir(rawEnv))
  return out
}

/** `<dir>/.claude/harness.json`, without a doubled slash at `/`. */
export const configPathOf = (dir: string): string => `${dir.endsWith('/') ? dir : `${dir}/`}${HARNESS_CONFIG_REL}`

/** What a folder listing gives of one entry. */
export type Listed = { name: string; kind: string; size: number; mtimeMs: number }

const isPlanFile = (name: string): boolean => name.endsWith(PLAN_SUFFIX)
const isWatchedName = (name: string): boolean => isPlanFile(name) || name.endsWith(PIP_HTML_SUFFIX)

/**
 * The plans folder's signature: the name, size and mtime of each `*_ActionPlan.json` and `*_PIP.html`, sorted.
 * A plan rewritten in place changes it, which the folder's own mtime does not.
 */
export const signatureOf = (entries: readonly Listed[]): string =>
  entries
    .filter(e => e.kind === 'file' && isWatchedName(e.name))
    .map(e => `${e.name}\t${e.size}\t${e.mtimeMs}`)
    .sort()
    .join('\n')

/** The plan files of a listing that have their sibling page beside them. */
export const pairedPlans = (entries: readonly Listed[]): string[] => {
  const files = new Set(entries.filter(e => e.kind === 'file').map(e => e.name))
  return entries
    .filter(e => e.kind === 'file' && isPlanFile(e.name))
    .map(e => e.name)
    .filter(name => files.has(pageOf(name) ?? ''))
    .sort()
}

// ---------------------------------------------------------------------------
// Session memory (a reload starts afresh; its `session.start` fires again)

/** What the last scan saw, which the probes compare with. */
const memo = {
  /** Whether a scan has run since the session started; the probes compare with nothing before one. */
  isScanned: false,
  /** The branch the last scan used; null for no git-status snapshot. */
  branch: null as string | null,
  head: undefined as string | undefined,
  archived: undefined as string | undefined,
  signature: undefined as string | undefined,
  overridesMtime: undefined as number | undefined,
  /** Whether the last scan read any plan, so a prompt runs git only when a plan could move. */
  hasPlans: false,
}

/** One scan at a time: a request while one runs is owed one more after it. */
const pacing = { isBusy: false, isOwed: false }

const resetMemo = (): void => {
  memo.isScanned = false
  memo.branch = null
  memo.head = undefined
  memo.archived = undefined
  memo.signature = undefined
  memo.overridesMtime = undefined
  memo.hasPlans = false
}

// ---------------------------------------------------------------------------
// Host access

async function readText($: Dollar, path: string): Promise<string | undefined> {
  const raw = await $.fs.read(path).catch(noop)
  return typeof raw === 'string' ? raw : undefined
}

async function mtimeOf($: Dollar, path: string): Promise<number | undefined> {
  const st = await $.fs.stat(path).catch(noop)
  return st === undefined ? undefined : st.mtimeMs
}

async function listOf($: Dollar, dir: string): Promise<Listed[]> {
  return $.fs.list(dir).catch(() => [] as Listed[])
}

/** Runs `fn` after the current dispatch, so no tool result, prompt or start waits on it. */
function later($: Dollar, fn: () => Promise<unknown>): void {
  try {
    $.clock.after(0, () => {
      void fn().catch(noop)
    })
  } catch {
    // no timer: this pass is skipped
  }
}

/** The first candidate whose harness.json reads, with its text; else the cwd (or the env) with no file. */
async function resolveWatch($: Dollar): Promise<Watch | undefined> {
  const env = await $.env.get('CLAUDE_PROJECT_DIR').catch(noop)
  const cwd = await $.session.cwd().catch(noop)
  const candidates = rootCandidates(env, cwd)
  for (const root of candidates) {
    const text = await readText($, configPathOf(root))
    if (text !== undefined) return { root, cfg: readConfig(text) }
  }
  const root = candidates[0]
  return root === undefined ? undefined : { root, cfg: readConfig(undefined) }
}

/** One git call in the project: its exit code and stdout, or undefined when it could not run or timed out. */
async function git($: Dollar, root: string, args: string[]): Promise<{ exitCode: number; stdout: string } | undefined> {
  const ran = await $.process.run(['git', '-C', root, ...args], { timeoutMs: GIT_TIMEOUT_MS }).catch(noop)
  return ran === undefined ? undefined : { exitCode: ran.exitCode, stdout: ran.stdout }
}

/** `git rev-parse HEAD`; undefined on any failure. */
async function headOf($: Dollar, root: string): Promise<string | undefined> {
  const ran = await git($, root, ['rev-parse', 'HEAD'])
  return ran === undefined || ran.exitCode !== 0 ? undefined : ran.stdout.trim()
}

/** The archive tag names, one per line; undefined on any failure. */
async function archiveTagsOf($: Dollar, root: string): Promise<string | undefined> {
  const ran = await git($, root, ['for-each-ref', '--format=%(refname:short)', ARCHIVE_REFS])
  return ran === undefined || ran.exitCode !== 0 ? undefined : ran.stdout
}

/**
 * The base tip `plan.py new` recorded `base_commit` against (D9, `branch_capture.resolve_merge_base` without the
 * fetch): `origin/<base>` when it exists and local `<base>` does not contain it, else `<base>`; null when a
 * call could not run.
 */
async function baseTipOf($: Dollar, root: string, base: string): Promise<string | null> {
  const remote = `origin/${base}`
  const has = await git($, root, ['rev-parse', '--verify', '--quiet', `${remote}^{commit}`])
  if (has === undefined) return null
  if (has.exitCode !== 0) return base
  const contains = await git($, root, ['merge-base', '--is-ancestor', remote, base])
  if (contains === undefined) return null
  return contains.exitCode === 0 ? base : remote
}

/** `git merge-base <tip> HEAD` for one base branch; null when any call failed. */
async function mergeBaseFor($: Dollar, root: string, base: string): Promise<string | null> {
  const tip = await baseTipOf($, root, base)
  if (tip === null) return null
  const ran = await git($, root, ['merge-base', tip, 'HEAD'])
  return ran === undefined || ran.exitCode !== 0 ? null : ran.stdout.trim()
}

// ---------------------------------------------------------------------------
// The scan

/** The git facts a prompt probe already holds, handed to the scan it starts. */
type GitFacts = { head: string | undefined; tags: string | undefined }

/** HEAD and the archive tag names, each undefined when its call failed. */
async function gitFactsOf($: Dollar, root: string): Promise<GitFacts> {
  return { head: await headOf($, root), tags: await archiveTagsOf($, root) }
}

/** The branch from git-status's snapshot; null while it has none. */
async function branchNow($: Dollar): Promise<string | null> {
  const snap = await read($, gitAtom).catch(() => null)
  return snap === null || snap === undefined ? null : snap.branch
}

/** The plans in the folder that read and have their page. */
async function readPlans($: Dollar, folder: string, entries: readonly Listed[]): Promise<PlanInfo[]> {
  const plans: PlanInfo[] = []
  for (const name of pairedPlans(entries)) {
    const path = `${folder}/${name}`
    const text = await readText($, path)
    const plan = text === undefined ? null : parsePlan(path, text)
    if (plan !== null) plans.push(plan)
  }
  return plans
}

/** The merge base of every distinct base branch some plan needs for rule 2, one resolution each. */
async function mergeBases($: Dollar, root: string, need: readonly PlanInfo[]): Promise<MergeBaseOf> {
  const found = new Map<string, string | null>()
  for (const plan of need) {
    const base = plan.baseBranch
    if (base === null || plan.baseCommit === '' || found.has(base)) continue
    found.set(base, await mergeBaseFor($, root, base))
  }
  return base => found.get(base) ?? null
}

/** The qualifying plans of `branch` (null: no snapshot, rule 1 never holds), git run only as they need. */
async function qualifyingPlans(
  $: Dollar, root: string, plans: readonly PlanInfo[], branch: string | null, archived: ReadonlySet<string>,
): Promise<PlanInfo[]> {
  const key = branch ?? ''
  const never: MergeBaseOf = () => null
  const byBranch = plans.filter(p => qualifies(p, key, never, archived))
  const rest = plans.filter(p => !byBranch.includes(p) && !archived.has(p.id))
  const mergeBaseOf = await mergeBases($, root, rest)
  return [...byBranch, ...rest.filter(p => qualifies(p, key, mergeBaseOf, archived))]
}

/** Writes the line to the atom when it changed. */
async function storeLine($: Dollar, line: WorkingLine | null): Promise<void> {
  const held = await read($, lineAtom).catch(() => null)
  if (JSON.stringify(held ?? null) === JSON.stringify(line)) return
  await update($, lineAtom, () => line)
}

/**
 * Writes the ccstatusline form to line.txt when it differs from the file's contents (absent reads as empty),
 * so a line another branch or an earlier session left is emptied by the first scan.
 */
async function writeLineFile($: Dollar, path: string, text: string): Promise<void> {
  const onDisk = (await readText($, path)) ?? ''
  if (onDisk !== text) await $.fs.write(path, text)
}

/** One full scan: plans, git, overrides, then the atom and the line file. */
async function runScan($: Dollar, facts?: GitFacts): Promise<void> {
  const w = await resolveWatch($)
  if (w === undefined) return
  const branch = await branchNow($)
  const folder = plansFolderOf(w.root, w.cfg)
  const entries = await listOf($, folder)
  const plans = await readPlans($, folder, entries)
  const overridesPath = overridesFileOf(w.root, w.cfg)
  const overridesMtime = await mtimeOf($, overridesPath)
  const hasPlans = plans.length > 0
  const { head, tags } = hasPlans ? (facts ?? (await gitFactsOf($, w.root))) : { head: undefined, tags: undefined }
  const archived = archivedIdsOf(tags ?? '')
  const qualifying = hasPlans ? await qualifyingPlans($, w.root, plans, branch, archived) : []
  const text = overridesMtime === undefined ? undefined : await readText($, overridesPath)
  const overrides = branch === null ? new Map() : parseOverrides(text)
  const line = buildLine(branch ?? '', qualifying, overrides)
  Object.assign(memo, {
    isScanned: true, branch, head, archived: tags, signature: signatureOf(entries), overridesMtime, hasPlans,
  })
  await storeLine($, line).catch(noop)
  await writeLineFile($, lineFileOf(w.root, w.cfg), statusText(line)).catch(noop)
}

/** Asks for a scan and returns at once; one asked while a scan runs is owed after it. */
function requestScan($: Dollar, facts?: GitFacts): void {
  if (pacing.isBusy) {
    pacing.isOwed = true
    return
  }
  pacing.isBusy = true
  void runScan($, facts)
    .catch(noop)
    .finally(() => finishScan($))
}

function finishScan($: Dollar): void {
  pacing.isBusy = false
  if (!pacing.isOwed) return
  pacing.isOwed = false
  requestScan($)
}

// ---------------------------------------------------------------------------
// Probes

/** Whether the plans folder's signature or the override file's mtime moved since the last scan. */
async function filesMoved($: Dollar, w: Watch): Promise<boolean> {
  const signature = signatureOf(await listOf($, plansFolderOf(w.root, w.cfg)))
  const overridesMtime = await mtimeOf($, overridesFileOf(w.root, w.cfg))
  return signature !== memo.signature || overridesMtime !== memo.overridesMtime
}

/** After a file or shell tool call: a scan when the plans folder or the override file moved. */
async function afterToolCall($: Dollar): Promise<void> {
  if (!memo.isScanned) return requestScan($)
  const w = await resolveWatch($)
  if (w !== undefined && (await filesMoved($, w))) requestScan($)
}

/**
 * At a prompt: the snapshot's branch (a write the `state.set` hook missed), HEAD and the archive tags (only
 * while a plan was read), then the files; a scan when any moved, handed the git facts already read. A failed
 * git call counts as no move.
 */
async function onPrompt($: Dollar): Promise<void> {
  if (!memo.isScanned || (await branchNow($)) !== memo.branch) return requestScan($)
  const w = await resolveWatch($)
  if (w === undefined) return
  if (memo.hasPlans) {
    const { head, tags } = await gitFactsOf($, w.root)
    const isGitMoved = (head !== undefined && head !== memo.head) || (tags !== undefined && tags !== memo.archived)
    if (isGitMoved) return requestScan($, { head: head ?? memo.head, tags: tags ?? memo.archived })
  }
  if (await filesMoved($, w)) requestScan($)
}

/** git-status wrote a snapshot: a scan when its branch is not the one the last scan used. */
function onSnapshot($: Dollar, branch: string | null): void {
  if (memo.isScanned && branch === memo.branch) return
  later($, async () => requestScan($))
}

// ---------------------------------------------------------------------------
// Registration

/** `session.start` work (wired in ./register): forget the last session and scan. Never throws. */
export async function startScan($: Dollar): Promise<void> {
  resetMemo()
  later($, async () => requestScan($))
}

export const registerWatch = (on: On): void => {
  on('state.set', { plugin: 'git-status', key: 'git' }, async ($, e, next) => {
    const result = await next(e)
    const snap = e.value as { branch?: unknown } | null | undefined
    const branch = snap !== null && snap !== undefined && typeof snap.branch === 'string' ? snap.branch : null
    onSnapshot($, branch)
    return result
  }).catch((_$, e, next) => next(e))

  on('tool.call', { tool: WATCH_TOOLS }, async ($, e, next) => {
    const result = await next(e)
    later($, () => afterToolCall($))
    return result
  }).catch((_$, e, next) => next(e))

  on('prompt.submit', async ($, e, next) => {
    const result = await next(e)
    later($, () => onPrompt($))
    return result
  }).catch((_$, e, next) => next(e))
}
