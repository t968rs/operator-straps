import type { Engine } from 'claude-code/testing'
import type { FsStat, On, ProcessRunResult } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'

import {
  fileListing,
  findPytestCalls,
  joinPath,
  parsePytestArgs,
  pytestArgsOf,
  rootStarts,
  tokenize,
  toRepoRelative,
} from './scope'

const ROOT = '/repo'
const PY = 'C:/py/envs/proj/python.exe'
const ON = { options: { require_test_file: true } }
const RULE = 'A directory path is never the unit; a file or a node-id is'
const GEO_FILES = ['tests/geo/test_a.py', 'tests/geo/helpers.py', 'tests/geo/b_test.py', 'tests/geo/conftest.py']

type World = {
  /** CLAUDE_PROJECT_DIR; unset when null. */
  root?: string | null
  /** The session cwd ($.session.cwd()); denied when unset. */
  cwd?: string
  /** Root-relative directories that exist; files ending .py exist anywhere under a known base. */
  dirs?: string[]
  /** `git rev-parse --show-toplevel` answer per start folder; null means not a repository. */
  toplevels?: Record<string, string | null>
  /** `git ls-files` output lines per root-relative directory. */
  files?: Record<string, string[]>
  /** git cannot be spawned. */
  isGitMissing?: boolean
  /** A source whose answer fails. */
  broken?: 'state.get' | 'fs.stat'
}

type Seen = { shell: string[]; commands: string[]; broadOk: () => boolean }

const slash = (path: string): string => path.replace(/\\/g, '/')

const stat = (kind: FsStat['kind']): { value: FsStat } => ({ value: { kind, size: 1, mtimeMs: 7, isLink: false } })

const ran = (stdout: string, exitCode = 0): ProcessRunResult => ({
  exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
})

/** The base-relative tail of `path` under one of `bases`, or undefined. */
const relOf = (path: string, bases: readonly string[]): string | undefined => {
  const p = slash(path)
  for (const base of bases) {
    const b = `${slash(base).toLowerCase()}/`
    // on Linux the engine resolves a drive-letter spelling against the plugin folder: find the base inside;
    // on Windows it resolves a drive-less base (`/repo`) onto the current drive (`E:/repo`)
    const at = p.toLowerCase().indexOf(b)
    if (at === 0 || (at > 0 && (/^[a-z]:/.test(b) || /^[a-z]:$/i.test(p.slice(0, at))))) return p.slice(at + b.length)
    if (p.toLowerCase() === b.slice(0, -1)) return '.'
  }
  return undefined
}

/** git's answer to one argv: rev-parse per start folder, ls-files per directory. */
const gitAnswer = (w: World, argv: readonly string[]): ProcessRunResult => {
  const start = argv[2] ?? ''
  if (argv[3] === 'rev-parse') {
    const top = w.toplevels?.[start]
    return top === null ? ran('', 128) : ran(`${top ?? ROOT}\n`)
  }
  const dir = argv[argv.length - 1] ?? '.'
  const listed = Object.entries(w.files ?? {}).filter(([d]) => dir === '.' || d === dir || d.startsWith(`${dir}/`))
  return ran(listed.flatMap(([, f]) => f).join('\n'))
}

/** Mocks env, cwd, fs.stat, git, the shell tools and command registration beneath the plugin. */
const world = (on: On, w: World = {}): Seen => {
  const state = new Map<string, unknown>()
  const seen: Seen = { shell: [], commands: [], broadOk: () => state.get('broadOk') === true }
  on('state.set', (_$, e, next) => {
    if (e.plugin === 'pytest-scope') state.set(e.key, e.value)
    return next(e)
  })
  const root = w.root === undefined ? ROOT : w.root
  mock.env(on, root === null ? {} : { CLAUDE_PROJECT_DIR: root })
  on('session.cwd', () => (w.cwd === undefined ? { deny: 'no cwd in this test' } : { value: w.cwd }))
  if (w.broken === 'state.get') on('state.get', () => ({ deny: 'EIO: state store unavailable' }))
  const dirs = w.dirs ?? ['tests', 'tests/geo', 'tests/big']
  const bases = [root, w.cwd].filter((b): b is string => b !== undefined && b !== null)
  on('fs.stat', (_$, e) => {
    if (w.broken === 'fs.stat') return { deny: `EACCES: ${e.path}` }
    const rel = relOf(e.path, bases)
    if (rel === undefined) return { deny: `ENOENT: ${e.path}` }
    if (rel === '.' || dirs.includes(rel)) return stat('dir')
    return rel.endsWith('.py') ? stat('file') : { deny: `ENOENT: ${e.path}` }
  })
  on('process.run', (_$, e) => (w.isGitMissing === true ? { deny: 'spawn git ENOENT' } : { value: gitAnswer(w, e.argv) }))
  for (const tool of ['Bash', 'PowerShell'] as const) {
    on('tool.call', { tool }, (_$, e) => {
      seen.shell.push(e.command)
      return { result: { stdout: 'ok', stderr: '', interrupted: false } } as never
    })
  }
  on('command.register', (_$, e) => {
    seen.commands.push(e.name)
    return { value: { command: e.name } }
  })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  return seen
}

/** The refusal text of a tool call result, whichever way the engine reports it. */
const refusal = (r: { deny?: string; isError?: true; text?: string }): string | undefined =>
  r.deny ?? (r.isError === true ? r.text : undefined)

const bash = ($: Engine, command: string) => $.tool.call({ tool: 'Bash', command })

const override = async ($: Engine): Promise<string> => {
  const r = await $.command.run({
    command: 'pytest-broad-ok',
    args: '',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 100 },
  })
  return r.text ?? ''
}

describe('pytest detection (pure)', () => {
  test('raw, interpreter and rewritten spellings are found', async () => {
    expect(pytestArgsOf(['pytest', 'a.py'])).toEqual(['a.py'])
    expect(pytestArgsOf(['py.test'])).toEqual([])
    expect(pytestArgsOf(['X=1', 'Y=2', 'python', '-X', 'utf8', '-m', 'pytest', '-q'])).toEqual(['-q'])
    expect(pytestArgsOf([PY, '-m', 'pytest', 'a.py'])).toEqual(['a.py'])
    expect(pytestArgsOf(['$PY', '-mpytest'])).toEqual([])
    expect(pytestArgsOf(['C:\\envs\\PYTHON.EXE', '-m', 'pytest'])).toEqual([])
    expect(pytestArgsOf(['python', 'tools/run_tests.py', '-m', 'pytest'])).toBeUndefined()
    expect(pytestArgsOf(['ruff', 'check', 'x.py'])).toBeUndefined()
  })

  test('a quoted interpreter path and the PYTHONPATH prefix tokenize as one word each', async () => {
    const calls = findPytestCalls(`PYTHONPATH="a;b" "${PY}" -m pytest "tests\\geo" -q 2>&1 | tail -5`)
    expect(calls).toHaveLength(1)
    expect(calls[0]?.positionals).toEqual(['tests\\geo'])
  })

  test('options and their values are skipped; positionals kept', async () => {
    const run = parsePytestArgs([
      '-k', 'foo', '-p', 'no:cacheprovider', '--tb=short', '--rootdir', 'x', '-n4', '-rA', 'a.py', '-W', 'error',
      '--deselect', 'b.py::t', 'c.py::T::m', '-q',
    ])
    expect(run.positionals).toEqual(['a.py', 'c.py::T::m'])
    expect(parsePytestArgs(['--co', 'dir']).isInfoOnly).toBe(true)
    expect(parsePytestArgs(['a.py', '>', 'log.txt']).positionals).toEqual(['a.py'])
  })

  test('--cov consumes the next word, as argparse nargs=? does: no test path is named', async () => {
    expect(parsePytestArgs(['--cov', 'tests/test_x.py']).positionals).toEqual([])
    expect(parsePytestArgs(['--cov=src', 'tests/test_x.py']).positionals).toEqual(['tests/test_x.py'])
    expect(parsePytestArgs(['tests/test_x.py', '--cov']).positionals).toEqual(['tests/test_x.py'])
  })

  test('a trailing comment is not pytest arguments; a comment cannot swallow the next line', async () => {
    const narrow = findPytestCalls('"$PY" -m pytest tests/geo/test_a.py -q  # covers tests/geo')
    expect(narrow[0]?.positionals).toEqual(['tests/geo/test_a.py'])
    const broad = findPytestCalls("# don't run everything\npytest tests")
    expect(broad[0]?.positionals).toEqual(['tests'])
    expect(tokenize('echo a#b')).toEqual([{ kind: 'word', text: 'echo' }, { kind: 'word', text: 'a#b' }])
    expect(findPytestCalls('pytest "a #b.py"')[0]?.positionals).toEqual(['a #b.py'])
  })

  test('wrappers, keywords and subshells do not hide pytest', async () => {
    const lines = [
      'timeout 900 "$PY" -m pytest tests',
      'time pytest tests',
      'if pytest tests; then echo ok; fi',
      'for x in 1; do pytest tests; done',
      '( pytest tests )',
      '(pytest tests)',
      '! pytest tests',
      '{ pytest tests; }',
      'conda run -n env python -m pytest tests',
      'uv run --with x pytest tests',
      'env -u HOME X=1 nice -n 5 timeout -s KILL 10m pytest tests',
    ]
    for (const line of lines) expect(findPytestCalls(line)[0]?.positionals).toEqual(['tests'])
    expect(findPytestCalls('command -v pytest')).toHaveLength(0)
    expect(findPytestCalls('pytest $(pwd)/a.py')[0]?.positionals).toEqual(['$(pwd)/a.py'])
  })

  test('heredoc bodies are data, not commands', async () => {
    expect(findPytestCalls("cat > notes.md <<'EOF'\npytest tests\nEOF\necho done")).toHaveLength(0)
    expect(findPytestCalls('cat <<-EOF > x\n\tpytest dir\n\tEOF\npytest a.py')).toHaveLength(1)
    expect(findPytestCalls('cat <<\\EOF > run.sh\npytest tests/\nEOF')).toHaveLength(0)
    expect(findPytestCalls('cat <<EOF\n\tEOF\npytest tests/')).toHaveLength(0)
    const two = 'cat <<A <<B\npytest x/\nA\npytest y/\nB\npytest a.py'
    expect(findPytestCalls(two).map(c => c.positionals)).toEqual([['a.py']])
  })

  test('a here-string, a quoted << and a commented << open no heredoc', async () => {
    const lines = [
      'cat <<< hello\npytest tests/',
      'echo "a <<EOF b"\npytest tests/',
      "echo 'x <<EOF'\npytest tests/",
      'echo hi # <<EOF\npytest tests/',
      'echo $((1<<2))\npytest tests/',
    ]
    for (const line of lines) expect(findPytestCalls(line).map(c => c.positionals)).toEqual([['tests/']])
  })
})

describe('paths (pure)', () => {
  test('joinPath folds . and ..', async () => {
    expect(joinPath('/repo/src', '../x')).toBe('/repo/x')
    expect(joinPath('C:/Repo', './a/./b/')).toBe('C:/Repo/a/b')
    expect(joinPath('/repo', '../..')).toBe('/')
  })

  test('toRepoRelative maps Git Bash and drive spellings under the root', async () => {
    expect(toRepoRelative('/c/Repo/tests/geo', 'C:/Repo')).toBe('tests/geo')
    expect(toRepoRelative('C:\\Repo\\tests', 'c:/repo')).toBe('tests')
    expect(toRepoRelative('/elsewhere/x', '/repo')).toBe('/elsewhere/x')
  })

  test('rootStarts asks the cwd first, then CLAUDE_PROJECT_DIR, without repeats', async () => {
    expect(rootStarts('/repo', '/repo/src')).toEqual(['/repo/src', '/repo'])
    expect(rootStarts('C:/Repo', 'c:\\repo\\')).toEqual(['c:/repo'])
    expect(rootStarts(undefined, ' ')).toEqual([])
  })

  test('fileListing caps at 15 and names how many more', async () => {
    const files = Array.from({ length: 20 }, (_, i) => `tests/big/test_m${i}.py`)
    const lines = fileListing(files)
    expect(lines[0]).toBe('Test files under it (20):')
    expect(lines).toContain('  tests/big/test_m14.py')
    expect(lines).not.toContain('  tests/big/test_m15.py')
    expect(lines[lines.length - 1]).toBe('  ... 5 more')
    expect(fileListing([])).toEqual([])
  })
})

describe('broad pytest deny', () => {
  test('a directory positional is denied with the rule, its test files and the way out', ON, async ($, on) => {
    const seen = world(on, { files: { 'tests/geo': GEO_FILES } })
    const text = refusal(await bash($, 'pytest tests/geo -q')) ?? ''
    expect(text).toContain(RULE)
    expect(text).toContain('directory tests/geo')
    expect(text).toContain('Test files under it (2):')
    expect(text).toContain('  tests/geo/test_a.py')
    expect(text).toContain('  tests/geo/b_test.py')
    expect(text).not.toContain('helpers.py')
    expect(text).toContain('/pytest-broad-ok')
    expect(seen.shell).toHaveLength(0)
  })

  test('no positional at all is denied', ON, async ($, on) => {
    const seen = world(on)
    expect(refusal(await bash($, '"$PY" -m pytest -q'))).toContain('no test path')
    expect(seen.shell).toHaveLength(0)
  })

  test('a file and a node-id run', ON, async ($, on) => {
    const seen = world(on)
    expect(refusal(await bash($, 'pytest tests/geo/test_a.py -q'))).toBeUndefined()
    expect(refusal(await bash($, 'python -m pytest "tests/geo/test_a.py::TestX::test_y"'))).toBeUndefined()
    expect(seen.shell).toHaveLength(2)
  })

  test('--collect-only and a runner script are never denied', ON, async ($, on) => {
    const seen = world(on)
    expect(refusal(await bash($, 'pytest tests --collect-only -q'))).toBeUndefined()
    expect(refusal(await bash($, 'python tools/run_tests.py --all'))).toBeUndefined()
    expect(seen.shell).toHaveLength(2)
  })

  test('/pytest-broad-ok allows exactly one broad call', ON, async ($, on) => {
    const seen = world(on)
    expect(await override($)).toBe('Next broad pytest call is allowed once.')
    expect(seen.broadOk()).toBe(true)
    expect(refusal(await bash($, 'pytest tests'))).toBeUndefined()
    expect(seen.broadOk()).toBe(false)
    expect(refusal(await bash($, 'pytest tests'))).toContain(RULE)
    expect(seen.shell).toHaveLength(1)
  })

  test('session start registers the override command', ON, async ($, on) => {
    const seen = world(on)
    await $.session.start({ cwd: ROOT, source: 'startup' } as never)
    expect(seen.commands).toEqual(['pytest-broad-ok'])
  })

  test('a rewritten interpreter command is still judged', ON, async ($, on) => {
    const seen = world(on)
    expect(refusal(await bash($, `"${PY}" -m pytest tests\\geo`))).toContain(RULE)
    expect(refusal(await bash($, `"${PY}" -m pytest tests/geo/test_a.py`))).toBeUndefined()
    expect(seen.shell).toHaveLength(1)
  })

  test('wrapped, keyword-led and prefixed broad runs are denied end to end', ON, async ($, on) => {
    const seen = world(on)
    expect(refusal(await bash($, 'timeout 900 "$PY" -m pytest tests'))).toContain(RULE)
    expect(refusal(await bash($, 'if pytest tests; then echo ok; fi'))).toContain(RULE)
    expect(refusal(await bash($, 'PYTHONPATH=src py.test tests/geo'))).toContain(RULE)
    expect(refusal(await bash($, "# don't run everything\npytest tests"))).toContain(RULE)
    expect(refusal(await bash($, 'cat <<\\EOF > run.sh\npytest tests/\nEOF'))).toBeUndefined()
    expect(seen.shell).toHaveLength(1)
  })

  test('a narrow run with a trailing comment naming a directory runs', ON, async ($, on) => {
    const seen = world(on)
    expect(refusal(await bash($, 'pytest tests/geo/test_a.py -q  # covers tests/geo'))).toBeUndefined()
    expect(seen.shell).toHaveLength(1)
  })

  test('PowerShell pytest runs are judged like Bash', ON, async ($, on) => {
    const seen = world(on)
    const ps = (command: string) => $.tool.call({ tool: 'PowerShell', command })
    expect(refusal(await ps('python -m pytest tests\\geo'))).toContain(RULE)
    expect(refusal(await ps('python -m pytest tests\\geo\\test_a.py'))).toBeUndefined()
    expect(seen.shell).toHaveLength(1)
  })

  test('a Git Bash /c/ spelling of a directory is denied like the drive-letter spelling', ON, async ($, on) => {
    const seen = world(on, { root: 'C:/Repo', toplevels: { 'C:/Repo': 'C:/Repo' } })
    expect(refusal(await bash($, 'pytest C:/Repo/tests/geo'))).toContain(RULE)
    expect(refusal(await bash($, 'pytest /c/Repo/tests/geo'))).toContain(RULE)
    expect(refusal(await bash($, 'pytest /c/Repo/tests/geo/test_a.py'))).toBeUndefined()
    expect(seen.shell).toHaveLength(1)
  })

  test('a directory named relative to a cd-ed cwd is denied', ON, async ($, on) => {
    const seen = world(on, { cwd: '/repo/tests', toplevels: { '/repo/tests': ROOT } })
    expect(refusal(await bash($, 'pytest geo/'))).toContain('directory tests/geo')
    expect(refusal(await bash($, 'pytest geo/test_a.py'))).toBeUndefined()
    expect(refusal(await bash($, 'pytest .'))).toContain('directory tests')
    expect(seen.shell).toHaveLength(1)
  })

  test('the 20 files under a directory list 15 and how many more', ON, async ($, on) => {
    const big = Array.from({ length: 20 }, (_, i) => `tests/big/test_m${i}.py`)
    world(on, { files: { 'tests/big': big } })
    const text = refusal(await bash($, 'pytest tests/big')) ?? ''
    expect(text).toContain('Test files under it (20):')
    expect(text).toContain('... 5 more')
  })
})

describe('roots and failures', () => {
  test('outside a repository the root falls back to the cwd and broad runs are still denied', ON, async ($, on) => {
    const seen = world(on, { root: null, cwd: '/scratch', dirs: ['tests'], toplevels: { '/scratch': null } })
    expect(refusal(await bash($, 'pytest tests'))).toContain('directory tests')
    expect(refusal(await bash($, 'pytest tests/test_a.py'))).toBeUndefined()
    expect(seen.shell).toHaveLength(1)
  })

  test('git missing: the deny still applies, without a file listing', ON, async ($, on) => {
    const seen = world(on, { isGitMissing: true })
    const text = refusal(await bash($, 'pytest tests/geo')) ?? ''
    expect(text).toContain(RULE)
    expect(text).not.toContain('Test files under it')
    expect(seen.shell).toHaveLength(0)
  })

  test('with neither a cwd nor CLAUDE_PROJECT_DIR every call runs', ON, async ($, on) => {
    const seen = world(on, { root: null })
    expect(refusal(await bash($, 'pytest'))).toBeUndefined()
    expect(refusal(await bash($, 'pytest tests'))).toBeUndefined()
    expect(seen.shell).toHaveLength(2)
  })

  test('a failing state read lets narrow and broad calls through', ON, async ($, on) => {
    const seen = world(on, { broken: 'state.get' })
    expect(refusal(await bash($, 'pytest tests/geo/test_a.py'))).toBeUndefined()
    expect(refusal(await bash($, 'pytest tests/geo'))).toBeUndefined()
    expect(seen.shell).toHaveLength(2)
  })

  test('a failing fs.stat lets directory calls through', ON, async ($, on) => {
    const seen = world(on, { broken: 'fs.stat' })
    expect(refusal(await bash($, 'pytest tests/geo/test_a.py'))).toBeUndefined()
    expect(refusal(await bash($, 'pytest tests/geo'))).toBeUndefined()
    expect(seen.shell).toHaveLength(2)
  })
})

describe('the require_test_file option', () => {
  test('off (the default): broad runs pass and no command is registered', async ($, on) => {
    const seen = world(on)
    await $.session.start({ cwd: ROOT, source: 'startup' } as never)
    expect(refusal(await bash($, 'pytest tests'))).toBeUndefined()
    expect(refusal(await bash($, 'pytest'))).toBeUndefined()
    expect(seen.shell).toHaveLength(2)
    expect(seen.commands).toEqual([])
  })
})
