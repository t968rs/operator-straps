/**
 * The project-root rule: the watch is active only in a project holding `.claude/harness.json`. Candidates
 * are the session cwd and each folder above it (nearest first: a subfolder or a linked worktree finds its
 * checkout's file), then CLAUDE_PROJECT_DIR; the first that holds the file is the root. No process is
 * spawned to find it. Pure: the `$` probe lives in watch.ts.
 */

export const HARNESS_CONFIG_REL = '.claude/harness.json'

/** Folders above the cwd that are looked in, at most. */
export const MAX_DEPTH = 32

const keyOf = (p: string): string => p.toLowerCase()

/** Forward slashes, no trailing slash (`/` stays `/`); undefined when blank. */
export const normalDir = (v: string | undefined): string | undefined => {
  const t = (v ?? '').trim().replace(/\\/g, '/')
  if (t === '') return undefined
  const s = t.replace(/\/+$/, '')
  return s === '' ? '/' : s
}
const nonBlank = normalDir

/** The folder above `dir`, or undefined at a filesystem root (`/`, `C:`, `//host/share`). */
export const parentOf = (dir: string): string | undefined => {
  const cut = dir.lastIndexOf('/')
  if (cut < 0 || dir === '/' || /^\/\/[^/]+\/[^/]+$/.test(dir)) return undefined
  return cut === 0 ? '/' : dir.slice(0, cut)
}

/** `dir` and the folders above it, nearest first, at most MAX_DEPTH + 1. */
export const ancestorsOf = (dir: string): string[] => {
  const out: string[] = []
  for (let cur: string | undefined = dir; cur !== undefined && out.length <= MAX_DEPTH; cur = parentOf(cur)) {
    out.push(cur)
  }
  return out
}

/** Candidate roots in probe order: the cwd and its ancestors, then CLAUDE_PROJECT_DIR; repeats dropped. */
export const rootCandidates = (rawEnv: string | undefined, rawCwd: string | undefined): string[] => {
  const cwd = nonBlank(rawCwd)
  const out: string[] = []
  for (const c of [...(cwd === undefined ? [] : ancestorsOf(cwd)), nonBlank(rawEnv)]) {
    if (c !== undefined && !out.some(o => keyOf(o) === keyOf(c))) out.push(c)
  }
  return out
}

/** `<dir>/.claude/harness.json`, without a doubled slash at `/`. */
export const configPathOf = (dir: string): string =>
  `${dir.endsWith('/') ? dir : `${dir}/`}${HARNESS_CONFIG_REL}`
