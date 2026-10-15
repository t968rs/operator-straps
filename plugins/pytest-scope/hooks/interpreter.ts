import type { EngineInterface, Register, ToolCallResult } from 'claude-code'
import { atom, update } from 'claude-code'

/**
 * Rewrites bare pytest invocations at Bash command positions to the interpreter named by the plugin's
 * `python` option. A bare name resolves to whatever Python is first on PATH, often a base env without the
 * project's test dependencies. Every failure path passes the command through.
 *
 * The rewrite runs before the permission rules and the PreToolUse hooks read the command, so it produces
 * one form only: `"<python>" -m pytest ...` opening a simple command. The project allows that form in its
 * own permission rules. `python -c`, scripts, other modules and assignment- or keyword-led calls keep
 * their bare spelling and the rules written for it.
 */

type On = Parameters<Register>[0]
type BashResult = ToolCallResult<'Bash'>

/** Program words that are pytest itself: rewritten to `"<python>" -m pytest`. */
const PYTEST_WORDS: ReadonlySet<string> = new Set(['pytest', 'py.test', 'pytest.exe'])
/** Interpreter words rewritten only when followed by `-m pytest`. */
const PYTHON_WORDS: ReadonlySet<string> = new Set(['python', 'python3', 'python.exe', 'python3.exe', 'py'])

/** Cheap pre-filter: skip env/fs work for commands that cannot hold a candidate word. */
const CANDIDATE = /(^|[^\w./\\-])(python3?(?:\.exe)?|pytest(?:\.exe)?|py\.test|py)(?![\w.\\/-])/i
/** Characters ending an unquoted word. */
const WORD_END = new Set([' ', '\t', '\r', '\n', ';', '&', '|', '<', '>', '(', ')'])
/** Characters an interpreter path may not hold and still be double-quoted verbatim. */
const UNQUOTABLE = /["$`\n\r]/
const NOTE_LIMIT = 200

const rewrites = atom({ plugin: 'pytest-scope', key: 'rewrites' } as const, 0)

type Word = { kind: 'word'; start: number; end: number }
type Token = Word | { kind: 'sep' } | { kind: 'redir' }
type Heredoc = { delim: string; strip: boolean }
type Cursor = { s: string; i: number; tokens: Token[]; pending: Heredoc[] }

/** Raised when the scanner cannot be sure of the command's structure. */
class Unsure extends Error {}

const unsure = (): never => {
  throw new Unsure()
}

/** Index just past the closing quote of a single-quoted span opened at `i`. */
const skipSingle = (s: string, i: number): number => {
  const close = s.indexOf("'", i + 1)
  return close < 0 ? unsure() : close + 1
}

/** Index just past an ANSI-C `$'...'` span whose `$` sits at `i`. */
const skipAnsi = (s: string, i: number): number => {
  let j = i + 2
  while (j < s.length && s[j] !== "'") j += s[j] === '\\' ? 2 : 1
  return j < s.length ? j + 1 : unsure()
}

/** Index just past a double-quoted span opened at `i`; bails on command substitution. */
const skipDouble = (s: string, i: number): number => {
  let j = i + 1
  while (j < s.length && s[j] !== '"') {
    if (s[j] === '`' || (s[j] === '$' && s[j + 1] === '(')) unsure()
    j += s[j] === '\\' ? 2 : 1
  }
  return j < s.length ? j + 1 : unsure()
}

/** Index just past a `${...}` expansion whose `$` sits at `i`. */
const skipBrace = (s: string, i: number): number => {
  const close = s.indexOf('}', i + 2)
  return close < 0 ? unsure() : close + 1
}

/** Index just past the quoted or escaped unit at `i`, or `i + 1` for a plain character. */
const skipUnit = (s: string, i: number): number => {
  const ch = s[i]
  const after = s[i + 1]
  if (ch === "'") return skipSingle(s, i)
  if (ch === '"') return skipDouble(s, i)
  if (ch === '`') return unsure()
  if (ch === '\\') return i + 1 < s.length ? i + 2 : unsure()
  if (ch === '$' && after === '(') return unsure()
  if (ch === '$' && after === "'") return skipAnsi(s, i)
  if (ch === '$' && after === '{') return skipBrace(s, i)
  return i + 1
}

/** Reads one word at the cursor and records it. */
const readWord = (c: Cursor): Word => {
  const start = c.i
  while (c.i < c.s.length && !WORD_END.has(c.s[c.i] ?? '')) c.i = skipUnit(c.s, c.i)
  const word: Word = { kind: 'word', start, end: c.i }
  c.tokens.push(word)
  return word
}

/** Reads a heredoc operator's delimiter and queues its body. */
const readHeredoc = (c: Cursor): void => {
  const strip = c.s[c.i] === '-'
  if (strip) c.i += 1
  while (c.s[c.i] === ' ' || c.s[c.i] === '\t') c.i += 1
  const word = readWord(c)
  const delim = c.s.slice(word.start, word.end).replace(/['"\\]/g, '')
  if (delim === '') unsure()
  c.pending.push({ delim, strip })
}

/** Reads a redirection operator (and a heredoc's delimiter) at the cursor. */
const readRedirect = (c: Cursor): void => {
  const { s } = c
  c.tokens.push({ kind: 'redir' })
  if (s.startsWith('<<<', c.i)) {
    c.i += 3
    return
  }
  if (s.startsWith('<<', c.i)) {
    c.i += 2
    readHeredoc(c)
    return
  }
  c.i += 1
  if ('>&|<'.includes(s[c.i] ?? ' ')) c.i += 1
}

/** Skips every queued heredoc body that starts at the cursor (just after a newline). */
const readHeredocBodies = (c: Cursor): void => {
  for (const doc of c.pending) {
    let found = false
    while (!found && c.i < c.s.length) {
      const nl = c.s.indexOf('\n', c.i)
      const end = nl < 0 ? c.s.length : nl
      let line = c.s.slice(c.i, end).replace(/\r$/, '')
      if (doc.strip) line = line.replace(/^\t+/, '')
      found = line === doc.delim
      c.i = end + 1
    }
    if (!found) unsure()
  }
  c.pending = []
}

/** Reads a control operator (`;`, `&`, `&&`, `|`, `||`, `|&`) or `&>` redirection. */
const readControl = (c: Cursor): void => {
  const ch = c.s[c.i]
  const after = c.s[c.i + 1]
  if (ch === '&' && after === '>') {
    c.i += 1
    readRedirect(c)
    return
  }
  const isDouble = (ch === '&' && after === '&') || (ch === '|' && (after === '|' || after === '&'))
  c.i += isDouble ? 2 : 1
  c.tokens.push({ kind: 'sep' })
}

/** Advances past a `#` comment, leaving the newline in place. */
const skipComment = (c: Cursor): void => {
  const nl = c.s.indexOf('\n', c.i)
  c.i = nl < 0 ? c.s.length : nl
}

/** Handles one step of the scan at the cursor. */
const step = (c: Cursor): void => {
  const ch = c.s[c.i] ?? ''
  if (ch === '\n') {
    c.i += 1
    c.tokens.push({ kind: 'sep' })
    readHeredocBodies(c)
  } else if (ch === ' ' || ch === '\t' || ch === '\r') c.i += 1
  else if (ch === '\\' && /^\\\r?\n/.test(c.s.slice(c.i, c.i + 3))) c.i += c.s[c.i + 1] === '\r' ? 3 : 2
  else if (ch === '#') skipComment(c)
  else if (ch === ';' || ch === '&' || ch === '|') readControl(c)
  else if (ch === '<' || ch === '>') readRedirect(c)
  else if (ch === '(' || ch === ')') unsure()
  else readWord(c)
}

/** Tokenizes a Bash command; null when its structure is uncertain. */
export const scan = (s: string): Token[] | null => {
  const c: Cursor = { s, i: 0, tokens: [], pending: [] }
  try {
    while (c.i < s.length) step(c)
    return c.pending.length > 0 ? null : c.tokens
  } catch (err) {
    if (err instanceof Unsure) return null
    throw err
  }
}

/** A program word that opens its simple command, with the index of its token. */
type Head = { word: Word; index: number }

/**
 * The program word of each simple command that starts it outright: a command led by an assignment, a
 * reserved word or a redirection yields none, since its permission rule names that prefix.
 */
export const commandHeads = (tokens: readonly Token[]): Head[] => {
  const out: Head[] = []
  let isAtStart = true
  tokens.forEach((t, index) => {
    if (t.kind === 'sep') isAtStart = true
    else {
      if (isAtStart && t.kind === 'word') out.push({ word: t, index })
      isAtStart = false
    }
  })
  return out
}

/** The raw text of token `i` when it is a word; undefined otherwise. */
const wordText = (s: string, tokens: readonly Token[], i: number): string | undefined => {
  const t = tokens[i]
  return t?.kind === 'word' ? s.slice(t.start, t.end) : undefined
}

/** What replaces a head word, or undefined when the head is not a pytest invocation. */
const replacementFor = (s: string, tokens: readonly Token[], head: Head, quoted: string): string | undefined => {
  const raw = s.slice(head.word.start, head.word.end)
  const name = raw.toLowerCase()
  if (PYTEST_WORDS.has(name)) return `${quoted} -m pytest`
  const isModule = wordText(s, tokens, head.index + 1) === '-m' && wordText(s, tokens, head.index + 2) === 'pytest'
  return PYTHON_WORDS.has(name) && isModule ? quoted : undefined
}

/** The command with each bare pytest invocation routed through `python`; null when nothing changed. */
export const rewriteCommand = (command: string, python: string): string | null => {
  const tokens = scan(command)
  if (tokens === null) return null
  const edits = commandHeads(tokens).flatMap(head => {
    const text = replacementFor(command, tokens, head, `"${python}"`)
    return text === undefined ? [] : [{ ...head.word, text }]
  })
  if (edits.length === 0) return null
  let out = command
  for (const edit of [...edits].reverse()) out = `${out.slice(0, edit.start)}${edit.text}${out.slice(edit.end)}`
  return out
}

/** Per-path existence results, kept for the module's lifetime. */
const existence = new Map<string, boolean>()

/** True when the path names a file; a missing path is cached, other failures are not. */
const isFile = async ($: EngineInterface, path: string): Promise<boolean> => {
  const known = existence.get(path)
  if (known !== undefined) return known
  try {
    const stat = await $.fs.stat(path)
    existence.set(path, stat.kind === 'file')
    return stat.kind === 'file'
  } catch (err) {
    if (/ENOENT|ENOTDIR|not found|no such/i.test(String(err))) existence.set(path, false)
    return false
  }
}

/**
 * The configured interpreter in the spelling the rewrite writes: trimmed, forward slashes. Undefined when
 * unset, relative (the engine would resolve it against the plugin folder), or not quotable verbatim.
 */
export const interpreterPath = (raw: string | undefined): string | undefined => {
  const path = (raw ?? '').trim().replace(/\\/g, '/')
  if (path === '' || UNQUOTABLE.test(path)) return undefined
  return /^(?:[a-zA-Z]:)?\//.test(path) ? path : undefined
}

/** The interpreter when the command may need it and the file exists; else undefined. */
const usableInterpreter = async (
  $: EngineInterface,
  command: string,
  python: string,
): Promise<string | undefined> => {
  if (!CANDIDATE.test(command)) return undefined
  return (await isFile($, python)) ? python : undefined
}

/** The one-line note the model reads beside a rewritten call's result. */
export const rewriteNote = (rewritten: string): string => {
  const shown = rewritten.length > NOTE_LIMIT ? `${rewritten.slice(0, NOTE_LIMIT)}...` : rewritten
  return `[pytest-scope] bare pytest rewritten to the configured interpreter: ${shown}`
}

/** Adds the rewrite note to an answered or errored result; a deny stays as it came. */
const withNote = (ran: BashResult, rewritten: string): BashResult => {
  if (ran.deny !== undefined) return ran
  return { ...ran, context: [rewriteNote(rewritten), ...(ran.context ?? [])] }
}

/** Bumps the session's rewrite counter; a state failure never costs the call. */
const countRewrite = async ($: EngineInterface): Promise<void> => {
  try {
    await update($, rewrites, n => n + 1)
  } catch {
    // the counter is advisory
  }
}

/**
 * Registers the Bash interpreter rewrite for the configured `python`; registers nothing when it is unset
 * or unusable. The `.catch` handler never denies: `next` is replay-safe, so once called `next(e)` settles
 * to that call's result without running the tool twice, and before it was called `next(e)` runs the
 * original command.
 */
export const registerInterpreter = (on: On, configured: string | undefined): void => {
  const python = interpreterPath(configured)
  if (python === undefined) return
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const usable = await usableInterpreter($, e.command, python)
    const rewritten = usable === undefined ? null : rewriteCommand(e.command, usable)
    if (rewritten === null) return next(e)
    const ran = await next({ ...e, command: rewritten })
    if (ran.deny === undefined) await countRewrite($)
    return withNote(ran, rewritten)
  }).catch(($, e, next) => next(e))
}
