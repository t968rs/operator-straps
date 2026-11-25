/**
 * The project-root rule: the mod is active only in a project holding `.claude/harness.json`. Candidates
 * follow harness_lib.project.project_root: the git top level of the session cwd (a linked worktree, or a
 * subfolder of one), then CLAUDE_PROJECT_DIR, then the cwd itself; the first that holds the file is the
 * root. Pure: the `$` probe lives in watch.ts.
 */

export const HARNESS_CONFIG_REL = '.claude/harness.json'

const clean = (p: string): string => p.trim().replace(/\\/g, '/').replace(/\/+$/, '')
const keyOf = (p: string): string => clean(p).toLowerCase()
const nonBlank = (v: string | undefined): string | undefined =>
  v !== undefined && v.trim() !== '' ? clean(v) : undefined

/**
 * Candidate roots in probe order: `rawTop` (git's top level of the cwd), CLAUDE_PROJECT_DIR, the cwd;
 * blanks and case-insensitive repeats dropped.
 */
export const rootCandidates = (
  rawEnv: string | undefined,
  rawCwd: string | undefined,
  rawTop?: string,
): string[] => {
  const out: string[] = []
  for (const c of [nonBlank(rawTop), nonBlank(rawEnv), nonBlank(rawCwd)]) {
    if (c !== undefined && !out.some(o => keyOf(o) === keyOf(c))) out.push(c)
  }
  return out
}
