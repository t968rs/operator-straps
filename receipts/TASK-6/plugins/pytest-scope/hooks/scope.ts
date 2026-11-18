import type { EngineInterface, Register, ToolCallResult } from 'claude-code'
import { atom, read, update } from 'claude-code'

/**
 * Denies pytest runs that name no test file: no path at all, or a directory path. A file or a node-id is
 * the unit. Bash and PowerShell commands are both judged, after the interpreter rewrite. `--collect-only`
 * and other information-only runs pass. `/pytest-broad-ok` lets the next broad run through once.
 * Every failure path (no root, a failed stat, an unreadable state store) lets the call through.
 */

type On = Parameters<Register>[0]
type Dollar = EngineInterface

const broadOk = atom({ plugin: 'pytest-scope', key: 'broadOk' } as const, false)

const RULE = 'A directory path is never the unit; a file or a node-id is'
const OVERRIDE = 'pytest-broad-ok'
const MAX_DENY_FILES = 15
const GIT_TIMEOUT_MS = 5000
/** Test module names pytest collects by default. */
const TEST_FILE = /(?:^|\/)(?:test_[^/]*|[^/]*_test)\.py$/i

// ---------------------------------------------------------------------------
// Paths

/** Forward slashes, no surrounding quotes, no `./` lead, no duplicate or trailing slash. */
export const cleanPath = (raw: string): string => {
  let p = raw.trim().replace(/^["']|["']$/g, '').replace(/\\/g, '/')
  p = p.replace(/(?<!^)\/{2,}/g, '/')
  while (p.startsWith('./')) p = p.slice(2)
  return p.length > 1 ? p.replace(/\/+$/, '') : p
}

/** Git Bash `/c/x` spelled as `c:/x`, so it compares with a drive-letter root. */
export const driveForm = (p: string): string => p.replace(/^\/([a-zA-Z])(?=\/|$)/, '$1:')

/** True for `/x`, `C:/x` and `//share` spellings. */
export const isAbsolute = (p: string): boolean => /^(?:[a-zA-Z]:)?\//.test(p)

/** Root-relative form of `raw` when it lies under `root`; otherwise the cleaned path. */
export const toRepoRelative = (raw: string, root: string | undefined): string => {
  const p = cleanPath(raw)
  if (root === undefined || !isAbsolute(p)) return p
  const r = cleanPath(root)
  const [pl, rl] = [driveForm(p).toLowerCase(), driveForm(r).toLowerCase()]
  if (pl === rl) return '.'
  return pl.startsWith(`${rl}/`) ? driveForm(p).slice(rl.length + 1) : p
}

/** Where to ask git for the top level, in order: the session cwd, then CLAUDE_PROJECT_DIR (no repeats). */
export const rootStarts = (rawEnv: string | undefined, rawCwd: string | undefined): string[] => {
  const out: string[] = []
  for (const raw of [rawCwd, rawEnv]) {
    const c = raw === undefined || raw.trim() === '' ? undefined : cleanPath(raw)
    if (c !== undefined && !out.some(o => o.toLowerCase() === c.toLowerCase())) out.push(c)
  }
  return out
}

// ---------------------------------------------------------------------------
// Host access (kept in this file: the engine follows `$` past an import only into function declarations)

/** `git rev-parse --show-toplevel` from `start`; undefined on any failure. */
const toplevelOf = async ($: Dollar, start: string): Promise<string | undefined> => {
  const argv = ['git', '-C', start, 'rev-parse', '--show-toplevel']
  const ran = await $.process.run(argv, { timeoutMs: GIT_TIMEOUT_MS }).catch(() => undefined)
  const top = ran === undefined || ran.exitCode !== 0 ? '' : ran.stdout.trim()
  return top === '' ? undefined : cleanPath(top)
}

/**
 * The root relative paths resolve against: the git top level of the session cwd, else of
 * CLAUDE_PROJECT_DIR, else the first of those that is set. Undefined when neither is. Never throws.
 */
const resolveRoot = async ($: Dollar, cwd: string | undefined): Promise<string | undefined> => {
  const env = await $.env.get('CLAUDE_PROJECT_DIR').catch(() => undefined)
  const starts = rootStarts(env, cwd)
  for (const start of starts) {
    const top = await toplevelOf($, start)
    if (top !== undefined) return top
  }
  return starts[0]
}

/** The session cwd (it follows a Bash `cd`); undefined when the host does not answer. */
const sessionCwd = async ($: Dollar): Promise<string | undefined> => {
  const cwd = await $.session.cwd().catch(() => undefined)
  return cwd === undefined || cwd.trim() === '' ? undefined : cleanPath(cwd)
}

/** Test files git knows under `dir` (root-relative; '.' for all), tracked or untracked; [] on failure. */
const testFilesUnder = async ($: Dollar, root: string, dir: string): Promise<string[]> => {
  const argv = ['git', '-C', root, 'ls-files', '--cached', '--others', '--exclude-standard', '--', dir]
  const ran = await $.process.run(argv, { timeoutMs: GIT_TIMEOUT_MS }).catch(() => undefined)
  if (ran === undefined || ran.exitCode !== 0) return []
  return ran.stdout.split(/\r?\n/).map(cleanPath).filter(f => f !== '' && TEST_FILE.test(f))
}

// ---------------------------------------------------------------------------
// Shell tokenizing

/** A shell word, or a control operator between commands. */
export type Token = { kind: 'word'; text: string } | { kind: 'op'; text: string }

const OPS = ['&&', '||', ';;', '|&', ';', '|', '&', '\n'] as const

/** Reads a quoted run starting at `i` (on the quote); returns its text and the index after it. */
const readQuoted = (s: string, i: number): [string, number] => {
  const q = s[i]
  let out = ''
  let j = i + 1
  while (j < s.length && s[j] !== q) {
    if (q === '"' && s[j] === '\\' && /["\\$`]/.test(s[j + 1] ?? '')) j++
    out += s[j]
    j++
  }
  return [out, j + 1]
}

/** Reads a redirection operator at `i` (`>`, `>>`, `<`, `>&1`, `<&-`); returns it and the index after. */
const readRedirect = (s: string, i: number): [string, number] => {
  const m = /^(?:[<>]{1,2}|&>>?)(?:&[0-9-]*)?/.exec(s.slice(i))
  const text = m?.[0] ?? s[i] ?? ''
  return [text, i + text.length]
}

/** Index of the next newline at or after `i` (the end of a `#` comment), or the end of `s`. */
const commentEnd = (s: string, i: number): number => {
  const nl = s.indexOf('\n', i)
  return nl < 0 ? s.length : nl
}

/**
 * Splits a command line into words and operators, honouring quotes; backslashes stay literal.
 * A `#` starting a word opens a comment to the end of the line. A `(` starting a word and a `)`
 * that closes no `(` of its own word are operators (subshell / group), so `$(pwd)/x` stays one word.
 */
export const tokenize = (s: string): Token[] => {
  const tokens: Token[] = []
  let word: string | undefined
  let depth = 0
  const flush = (): void => {
    if (word !== undefined) tokens.push({ kind: 'word', text: word })
    word = undefined
    depth = 0
  }
  const op = (text: string): void => {
    flush()
    tokens.push({ kind: 'op', text })
  }
  let i = 0
  while (i < s.length) {
    const c = s[i] ?? ''
    if (c === '\\' && s[i + 1] === '\n') {
      i += 2
      continue
    }
    if (c === '#' && word === undefined) {
      i = commentEnd(s, i)
      continue
    }
    if (c === "'" || c === '"') {
      const [text, next] = readQuoted(s, i)
      word = (word ?? '') + text
      i = next
      continue
    }
    if (c === '<' || c === '>' || (c === '&' && s[i + 1] === '>')) {
      const [text, next] = readRedirect(s, i)
      word = (word ?? '') + text
      i = next
      continue
    }
    if (c === '(' && word === undefined) {
      op('(')
      i++
      continue
    }
    if (c === '(' || (c === ')' && depth > 0)) {
      depth += c === '(' ? 1 : -1
      word = (word ?? '') + c
      i++
      continue
    }
    if (c === ')') {
      op(')')
      i++
      continue
    }
    const found = OPS.find(o => s.startsWith(o, i))
    if (found !== undefined) {
      op(found)
      i += found.length
      continue
    }
    if (c === ' ' || c === '\t' || c === '\r') flush()
    else word = (word ?? '') + c
    i++
  }
  flush()
  return tokens
}

/** A queued heredoc: its delimiter, and whether `<<-` strips leading tabs from body lines. */
type Heredoc = { delim: string; strip: boolean }

/** Characters that end an unquoted heredoc delimiter word. */
const DELIM_END = /[\s;&|<>()]/

/**
 * Reads the delimiter word after a `<<` that ends just before `i`: quotes and backslashes removed
 * (`'EOF'`, `"EOF"`, `\EOF` all give EOF). Returns the heredoc and the index after the word.
 */
const readDelimiter = (s: string, i: number): [Heredoc, number] => {
  const strip = s[i] === '-'
  let j = strip ? i + 1 : i
  while (s[j] === ' ' || s[j] === '\t') j++
  let delim = ''
  while (j < s.length && !DELIM_END.test(s[j] ?? '')) {
    const c = s[j] ?? ''
    if (c === "'" || c === '"') {
      const close = s.indexOf(c, j + 1)
      const stop = close < 0 ? s.length : close
      delim += s.slice(j + 1, stop)
      j = stop + 1
    } else if (c === '\\') {
      delim += s[j + 1] ?? ''
      j += 2
    } else {
      delim += c
      j++
    }
  }
  return [{ delim, strip }, j]
}

/** Index after the bodies of `docs`, which start at `i`; an unterminated body runs to the end. */
const skipBodies = (s: string, i: number, docs: readonly Heredoc[]): number => {
  let at = i
  for (const doc of docs) {
    let found = false
    while (!found && at < s.length) {
      const nl = s.indexOf('\n', at)
      const stop = nl < 0 ? s.length : nl
      let line = s.slice(at, stop).replace(/\r$/, '')
      if (doc.strip) line = line.replace(/^\t+/, '')
      found = line === doc.delim
      at = stop + 1
    }
  }
  return Math.min(at, s.length)
}

/** Whether `s[i]` starts a word (so a `#` there opens a comment). */
const atWordStart = (s: string, i: number): boolean => i === 0 || /[\s;&|()<>]/.test(s[i - 1] ?? '')

/** Scanner state for stripHeredocs. */
type HeredocScan = { s: string; i: number; out: string; quote: string | undefined; pending: Heredoc[] }

/** Copies `n` characters at the cursor to the output. */
const copy = (c: HeredocScan, n: number): void => {
  c.out += c.s.slice(c.i, c.i + n)
  c.i += n
}

/** One step inside a quoted span: a backslash in double quotes escapes the next character. */
const stepQuoted = (c: HeredocScan): void => {
  const ch = c.s[c.i]
  if (ch === '\\' && c.quote === '"') return copy(c, 2)
  if (ch === c.quote) c.quote = undefined
  copy(c, 1)
}

/** A `<<` operator at the cursor (not `<<<`): copies it and its delimiter, and queues the body. */
const stepHeredoc = (c: HeredocScan): void => {
  const [doc, next] = readDelimiter(c.s, c.i + 2)
  copy(c, next - c.i)
  if (/^[A-Za-z_]/.test(doc.delim)) c.pending.push(doc)
}

/** One step outside quotes. */
const stepPlain = (c: HeredocScan): void => {
  const { s, i } = c
  const ch = s[i] ?? ''
  if (ch === '\\') copy(c, 2)
  else if (ch === "'" || ch === '"') {
    c.quote = ch
    copy(c, 1)
  } else if (ch === '#' && atWordStart(s, i)) copy(c, commentEnd(s, i) - i)
  else if (s.startsWith('<<<', i)) copy(c, 3)
  else if (s.startsWith('<<', i)) stepHeredoc(c)
  else if (ch === '\n' && c.pending.length > 0) {
    copy(c, 1)
    c.i = skipBodies(s, c.i, c.pending)
    c.pending = []
  } else copy(c, 1)
}

/**
 * Drops heredoc bodies (their lines are data, not commands); an unterminated body runs to the end.
 * A `<<` inside quotes or a comment, and a `<<<` here-string, open no heredoc.
 */
export const stripHeredocs = (s: string): string => {
  const c: HeredocScan = { s, i: 0, out: '', quote: undefined, pending: [] }
  while (c.i < s.length) {
    if (c.quote === undefined) stepPlain(c)
    else stepQuoted(c)
  }
  return c.out
}

/** One simple command of a line: its words, and the operator that follows it ('' at the end). */
export type Segment = { words: string[]; after: string }

/** Groups tokens into simple commands. */
export const segments = (tokens: readonly Token[]): Segment[] => {
  const out: Segment[] = []
  let words: string[] = []
  for (const t of tokens) {
    if (t.kind === 'word') words.push(t.text)
    else {
      if (words.length > 0) out.push({ words, after: t.text })
      words = []
    }
  }
  if (words.length > 0) out.push({ words, after: '' })
  const last = out[out.length - 1]
  // a trailing `;` or newline ends the line: the last command's status is the line's
  if (words.length === 0 && last !== undefined && (last.after === ';' || last.after === '\n')) last.after = ''
  return out
}

// ---------------------------------------------------------------------------
// pytest argument parsing

/** A parsed pytest invocation. */
export type PytestRun = {
  positionals: string[]
  /** `--collect-only`, `--version`, `-h` and kin: nothing runs. */
  isInfoOnly: boolean
  /** `-k`, `-m`, `--deselect`, `--lf` or `--sw` given: a positional file may not run whole. */
  isNarrowed: boolean
}

/**
 * Options that take the next word. `--cov` takes an optional value through argparse `nargs='?'`, which
 * consumes the next word whenever it does not start with `-`: `pytest --cov tests/test_x.py` names no
 * test path and runs the whole suite, so the word is consumed here too.
 */
const SHORT_WITH_VALUE = new Set(['-k', '-m', '-p', '-c', '-o', '-n', '-W', '-r'])
const LONG_WITH_VALUE = new Set([
  '--rootdir', '--deselect', '--ignore', '--ignore-glob', '--confcutdir', '--basetemp', '--tb',
  '--maxfail', '--durations', '--junitxml', '--junit-xml', '--log-level', '--log-file',
  '--log-cli-level', '--log-file-level', '--override-ini', '--import-mode', '--capture',
  '--color', '--timeout', '--durations-min', '--cov', '--cov-report', '--dist',
])
const INFO_ONLY = new Set(['--collect-only', '--co', '--version', '-V', '-h', '--help', '--fixtures', '--markers'])
/** Selections that may leave part of a named file unrun. */
const NARROWING = new Set([
  '-k', '-m', '--deselect', '--lf', '--last-failed', '--sw', '--stepwise', '--sw-skip', '--stepwise-skip',
])

/** The option name of `tok`: `--x=v` -> `--x`, `-kexpr` -> `-k`, else `tok`. */
const optionName = (tok: string): string => {
  if (tok.startsWith('--')) return tok.split('=')[0] ?? tok
  const short = tok.slice(0, 2)
  return SHORT_WITH_VALUE.has(short) ? short : tok
}

/** Whether `tok` is an option that takes the next word as its value. */
const takesNext = (tok: string): boolean =>
  tok.startsWith('--') ? !tok.includes('=') && LONG_WITH_VALUE.has(tok) : SHORT_WITH_VALUE.has(tok)

/** Parses pytest's own arguments (everything after `pytest`). */
export const parsePytestArgs = (args: readonly string[]): PytestRun => {
  const run: PytestRun = { positionals: [], isInfoOnly: false, isNarrowed: false }
  let onlyPositionals = false
  for (let i = 0; i < args.length; i++) {
    const tok = args[i] ?? ''
    if (onlyPositionals || !tok.startsWith('-') || tok === '-') {
      if (!/^\d*[<>&]/.test(tok)) run.positionals.push(tok)
      else if (/^\d*[<>]{1,2}$|^&>>?$/.test(tok)) i++
      continue
    }
    if (tok === '--') {
      onlyPositionals = true
      continue
    }
    const name = optionName(tok)
    if (INFO_ONLY.has(name)) run.isInfoOnly = true
    if (NARROWING.has(name)) run.isNarrowed = true
    if (takesNext(tok)) i++
  }
  return run
}

const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/
const PYTEST_NAMES = new Set(['pytest', 'py.test'])
/** Interpreter options that take the next word (`python -X utf8 -m pytest`). */
const PY_OPTS_WITH_VALUE = new Set(['-X', '-W'])

/** The final path component, case-folded, without `.exe`. */
const baseName = (word: string): string =>
  (word.replace(/\\/g, '/').split('/').pop() ?? '').toLowerCase().replace(/\.exe$/, '')

/** Shell keywords and `!` that may precede a command word. */
const KEYWORDS = new Set(['!', 'if', 'then', 'else', 'elif', 'do', 'while', 'until', '{', 'exec', 'nohup'])

/** Wrapper programs that run the rest of the line, with their options that take a value. */
const WRAPPERS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ['time', new Set<string>()],
  ['env', new Set(['-u', '--unset', '-C', '--chdir', '-S', '--split-string'])],
  ['nice', new Set(['-n', '--adjustment'])],
  ['timeout', new Set(['-s', '--signal', '-k', '--kill-after'])],
])

/** `<x> run` runners, with their `run` options that take a value. */
const RUNNERS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ['conda', new Set(['-n', '--name', '-p', '--prefix', '--cwd'])],
  ['mamba', new Set(['-n', '--name', '-p', '--prefix', '--cwd'])],
  ['micromamba', new Set(['-n', '--name', '-p', '--prefix', '--cwd'])],
  ['uv', new Set(['--with', '--python', '-p', '--project', '--directory', '--env-file', '--extra', '--group',
    '--package', '--with-requirements', '--index'])],
  ['poetry', new Set<string>()],
  ['pipenv', new Set<string>()],
])

/** Index after the options at `i` (each in `withValue` also takes the next word). */
const skipOptions = (words: readonly string[], i: number, withValue: ReadonlySet<string>): number => {
  let j = i
  while (j < words.length && (words[j] ?? '').startsWith('-')) {
    const w = words[j] ?? ''
    j += withValue.has(w) ? 2 : 1
    if (w === '--') break
  }
  return j
}

/** Index of the word after a wrapper or runner prefix at `i`; `i` when none starts there. */
const skipWrapper = (words: readonly string[], i: number): number => {
  const name = baseName(words[i] ?? '').replace(/\.(?:bat|cmd)$/, '')
  const wrapper = WRAPPERS.get(name)
  if (wrapper !== undefined) {
    const j = skipOptions(words, i + 1, wrapper)
    return name === 'timeout' ? j + 1 : j
  }
  const runner = RUNNERS.get(name)
  if (runner !== undefined && words[i + 1] === 'run') return skipOptions(words, i + 2, runner)
  return i
}

/** Index of the command word: past assignments, keywords, wrappers and runners. */
export const commandStart = (words: readonly string[]): number => {
  let i = 0
  while (i < words.length) {
    const w = words[i] ?? ''
    if (ASSIGNMENT.test(w) || KEYWORDS.has(w)) {
      i++
      continue
    }
    const next = skipWrapper(words, i)
    if (next === i) return i
    i = next
  }
  return i
}

/** pytest's argument words when `words` invokes pytest; undefined otherwise. */
export const pytestArgsOf = (words: readonly string[]): string[] | undefined => {
  const i = commandStart(words)
  const head = words[i]
  if (head === undefined) return undefined
  if (PYTEST_NAMES.has(baseName(head))) return words.slice(i + 1)
  for (let j = i + 1; j < words.length; j++) {
    const w = words[j] ?? ''
    if (w === '-m' && PYTEST_NAMES.has(words[j + 1] ?? '')) return words.slice(j + 2)
    if (w.startsWith('-m') && PYTEST_NAMES.has(w.slice(2))) return words.slice(j + 1)
    if (!w.startsWith('-')) return undefined
    if (PY_OPTS_WITH_VALUE.has(w)) j++
  }
  return undefined
}

/** A pytest call found in a command line, and whether its exit status decides the line's. */
export type PytestCall = PytestRun & { decidesExit: boolean }

/** Every pytest call in a Bash command line (raw or interpreter-rewritten). */
export const findPytestCalls = (command: string): PytestCall[] => {
  const segs = segments(tokenize(stripHeredocs(command)))
  return segs.flatMap((seg, idx) => {
    const args = pytestArgsOf(seg.words)
    if (args === undefined) return []
    const decidesExit = segs.slice(idx).every(s => s.after === '&&' || s.after === '')
    return [{ ...parsePytestArgs(args), decidesExit }]
  })
}

// ---------------------------------------------------------------------------
// Broad pytest deny

/** Strips a `::node` suffix (a drive letter's colon is kept). */
export const stripNode = (p: string): string => {
  const at = p.indexOf('::')
  return at < 0 ? p : p.slice(0, at)
}

/** Joins a relative path onto `base`, folding `.` and `..` segments. */
export const joinPath = (base: string, rel: string): string => {
  const parts = cleanPath(base).split('/')
  for (const seg of cleanPath(rel).split('/')) {
    if (seg === '..' && parts.length > 1) parts.pop()
    else if (seg !== '' && seg !== '.' && seg !== '..') parts.push(seg)
  }
  return parts.join('/') || '/'
}

/**
 * Absolute spellings of a positional: as given when absolute, else under the session cwd (the Bash
 * tool keeps its cwd between calls) and under the root.
 */
const absoluteSpellings = (p: string, root: string, cwd: string | undefined): string[] => {
  if (isAbsolute(p)) return [p]
  const bases = cwd === undefined ? [root] : [cwd, root]
  return [...new Set(bases.map(b => joinPath(b, p)))]
}

/** Spellings of an absolute path to stat: under the root's own spelling, else as given and as `c:/x`. */
const statCandidates = (p: string, root: string): string[] => {
  const rel = toRepoRelative(p, root)
  if (!isAbsolute(rel)) return [rel === '.' ? root : `${root}/${rel}`]
  return [...new Set([p, driveForm(p)])]
}

/** Whether an absolute path is an existing directory; a failed stat counts as no. */
const isDirectory = async ($: Dollar, p: string, root: string): Promise<boolean> => {
  for (const candidate of statCandidates(p, root)) {
    const stat = await $.fs.stat(candidate).catch(() => undefined)
    if (stat !== undefined) return stat.kind === 'dir'
  }
  return false
}

/** The root-relative spelling of the first of `spellings` that is a directory, if any. */
const firstDirectory = async (
  $: Dollar,
  spellings: readonly string[],
  root: string,
): Promise<string | undefined> => {
  for (const abs of spellings) {
    if (await isDirectory($, abs, root)) return toRepoRelative(abs, root)
  }
  return undefined
}

/** The broad targets of a run: '.' when nothing is named, else each positional that is a directory. */
const broadTargets = async (
  $: Dollar,
  root: string,
  cwd: string | undefined,
  run: PytestRun,
): Promise<string[]> => {
  if (run.isInfoOnly) return []
  if (run.positionals.length === 0) return ['.']
  const found: string[] = []
  for (const raw of run.positionals) {
    const dir = await firstDirectory($, absoluteSpellings(cleanPath(stripNode(raw)), root, cwd), root)
    if (dir !== undefined) found.push(dir)
  }
  return found
}

/** The listing lines for up to MAX_DENY_FILES test files, naming how many were left out. */
export const fileListing = (files: readonly string[]): string[] => {
  if (files.length === 0) return []
  const shown = files.slice(0, MAX_DENY_FILES).map(f => `  ${f}`)
  const more = files.length > MAX_DENY_FILES ? [`  ... ${files.length - MAX_DENY_FILES} more`] : []
  return [`Test files under it (${files.length}):`, ...shown, ...more]
}

/** The deny text naming the broad targets and up to MAX_DENY_FILES test files under them. */
const denyMessage = async ($: Dollar, root: string, targets: string[]): Promise<string> => {
  const what = targets.map(t => (t === '.' ? 'no test path (the whole suite)' : `directory ${t}`))
  const found = await Promise.all(targets.map(t => testFilesUnder($, root, t)))
  return [
    `pytest-scope: broad pytest run blocked (${what.join(', ')}).`,
    `${RULE}: name the test files that prove the change, or node-ids (file.py::test_name).`,
    ...fileListing([...new Set(found.flat())]),
    `The developer can arm a one-shot override with /${OVERRIDE}.`,
  ].join('\n')
}

/** The deny text when any call is broad and no override is armed; consumes an armed override. */
const judgeBroad = async ($: Dollar, calls: readonly PytestCall[]): Promise<string | undefined> => {
  if (calls.length === 0) return undefined
  const cwd = await sessionCwd($)
  const root = await resolveRoot($, cwd)
  if (root === undefined) return undefined
  const targets = (await Promise.all(calls.map(c => broadTargets($, root, cwd, c)))).flat()
  if (targets.length === 0) return undefined
  if (await read($, broadOk)) {
    await update($, broadOk, () => false)
    return undefined
  }
  return denyMessage($, root, [...new Set(targets)])
}

// ---------------------------------------------------------------------------
// Hooks

type ShellResult = ToolCallResult<'Bash'> | ToolCallResult<'PowerShell'>

/** Denies a broad pytest run, else runs the command. */
const guardShell = async <R extends ShellResult>(
  $: Dollar,
  command: string,
  run: () => Promise<R>,
): Promise<R | { deny: string }> => {
  const deny = await judgeBroad($, findPytestCalls(command))
  return deny === undefined ? run() : { deny }
}

/** Bash and PowerShell: deny broad pytest runs. */
const onShell = (on: On): void => {
  on('tool.call', { tool: 'Bash' }, ($, e, next) => guardShell($, e.command, () => next(e)))
    .catch(($, e, next) => next(e))
  on('tool.call', { tool: 'PowerShell' }, ($, e, next) => guardShell($, e.command, () => next(e)))
    .catch(($, e, next) => next(e))
}

/** session.start: register the one-shot override command. */
const onSessionStart = (on: On): void => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: OVERRIDE,
      description: 'Allow the next broad (directory / no-path) pytest call once',
    }).catch(() => undefined)
    return next(e)
  }).catch(($, e, next) => next(e))
}

/** The override command's answer. */
const onOverride = (on: On): void => {
  on('command.run', { command: OVERRIDE }, async $ => {
    await update($, broadOk, () => true)
    return { text: 'Next broad pytest call is allowed once.' }
  }).catch(() => ({ text: 'pytest-scope: could not arm the override.' }))
}

/** Registers the broad-run deny and its override when `enabled`; registers nothing otherwise. */
export const registerScope = (on: On, enabled: boolean): void => {
  if (!enabled) return
  onShell(on)
  onSessionStart(on)
  onOverride(on)
}
