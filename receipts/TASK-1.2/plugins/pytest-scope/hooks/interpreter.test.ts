import type { FsStat, On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

import { interpreterPath, rewriteCommand, rewriteNote } from './interpreter'

const FPM = 'C:/py/envs/proj/python.exe'
const Q = `"${FPM}"`
const NOTE_PREFIX = '[pytest-scope] bare pytest rewritten to the configured interpreter: '
const FILE: FsStat = { kind: 'file', size: 1, mtimeMs: 0, isLink: false }

type World = { files?: readonly string[] }

/** Records every value the plugin writes to its `rewrites` state key. */
const rewriteWrites = (on: On): unknown[] => {
  const values: unknown[] = []
  on('state.set', (_$, e, next) => {
    if (e.plugin === 'pytest-scope' && e.key === 'rewrites') values.push(e.value)
    return next(e)
  })
  return values
}

/** Mocks fs.stat and the Bash tool beneath the plugin; returns the commands the tool received. */
const world = (on: On, { files = [] }: World): string[] => {
  const seen: string[] = []
  // the engine resolves a non-absolute spelling (C:/... on Linux) against the plugin folder;
  // on Windows it hands the hook backslashes
  on('fs.stat', (_$, e) => {
    const path = e.path.replace(/\\/g, '/')
    return files.some(f => path === f || path.endsWith(`/${f}`))
      ? { value: FILE }
      : { deny: `ENOENT: no such file ${e.path}` }
  })
  on('tool.call', { tool: 'Bash' }, (_$, e) => {
    seen.push(e.command)
    return { result: { stdout: 'ok', stderr: '', interrupted: false } }
  })
  return seen
}

describe('rewriteCommand: pytest invocations', () => {
  test('pytest and py.test become -m pytest', async () => {
    expect(rewriteCommand('pytest tests/test_a.py -q', FPM)).toBe(
      `${Q} -m pytest tests/test_a.py -q`,
    )
    expect(rewriteCommand('py.test -q', FPM)).toBe(`${Q} -m pytest -q`)
  })
  test('python / python3 -m pytest keep their -m pytest', async () => {
    expect(rewriteCommand('python -m pytest a.py', FPM)).toBe(`${Q} -m pytest a.py`)
    expect(rewriteCommand('python3 -m pytest a.py -q', FPM)).toBe(`${Q} -m pytest a.py -q`)
  })
  test('Windows .exe spellings and the py launcher resolve to base too and are rewritten', async () => {
    expect(rewriteCommand('python.exe -m pytest tests/test_x.py -v', FPM)).toBe(
      `${Q} -m pytest tests/test_x.py -v`,
    )
    expect(rewriteCommand('python3.exe -m pytest a.py', FPM)).toBe(`${Q} -m pytest a.py`)
    expect(rewriteCommand('pytest.exe a.py', FPM)).toBe(`${Q} -m pytest a.py`)
    expect(rewriteCommand('Python.EXE -m pytest a.py', FPM)).toBe(`${Q} -m pytest a.py`)
    expect(rewriteCommand('py -m pytest a.py', FPM)).toBe(`${Q} -m pytest a.py`)
  })
})

describe('rewriteCommand: only forms the allow list still covers', () => {
  test('python -c, scripts and other modules keep the allow-listed bare spelling', async () => {
    expect(rewriteCommand('python -c "print(1)"', FPM)).toBeNull()
    expect(rewriteCommand('python3 -c "import x\n# c\nprint(1)"', FPM)).toBeNull()
    expect(rewriteCommand('python x.py', FPM)).toBeNull()
    expect(rewriteCommand('python -m ruff check a.py', FPM)).toBeNull()
    expect(rewriteCommand('python.exe x.py', FPM)).toBeNull()
    expect(rewriteCommand('py -3 x.py', FPM)).toBeNull()
  })
  test('ruff and pylint are left alone', async () => {
    expect(rewriteCommand('ruff check src/a.py | head', FPM)).toBeNull()
    expect(rewriteCommand('pylint src/x.py --disable=all', FPM)).toBeNull()
    expect(rewriteCommand('ruff.exe check a.py', FPM)).toBeNull()
  })
  test('assignment-, keyword- and redirection-led commands are left alone', async () => {
    expect(rewriteCommand('PYTHONPATH="C:/r;C:/r/scripts" python -m pytest x.py', FPM)).toBeNull()
    expect(rewriteCommand('PYTHONPATH=scripts pytest f.py', FPM)).toBeNull()
    expect(rewriteCommand('if pytest a.py; then echo ok; fi', FPM)).toBeNull()
    expect(rewriteCommand('2>err.txt pytest a.py', FPM)).toBeNull()
  })
})

describe('rewriteCommand: command positions', () => {
  test('a pipe rewrites only the pytest', async () => {
    expect(rewriteCommand('pytest a.py | head', FPM)).toBe(`${Q} -m pytest a.py | head`)
    expect(rewriteCommand('echo hi | python -m pytest a.py', FPM)).toBe(`echo hi | ${Q} -m pytest a.py`)
  })
  test('every separator opens a command position', async () => {
    expect(rewriteCommand('ruff check a && pytest b', FPM)).toBe(`ruff check a && ${Q} -m pytest b`)
    expect(rewriteCommand('pytest a || python3 -m pytest b; pylint c', FPM)).toBe(
      `${Q} -m pytest a || ${Q} -m pytest b; pylint c`,
    )
    expect(rewriteCommand('cd x\npytest y', FPM)).toBe(`cd x\n${Q} -m pytest y`)
    expect(rewriteCommand('pytest a 2>&1 | tail -5', FPM)).toBe(`${Q} -m pytest a 2>&1 | tail -5`)
  })
})

describe('rewriteCommand: left alone', () => {
  test('words inside quotes', async () => {
    expect(rewriteCommand('echo "python -m pytest x.py; pytest"', FPM)).toBeNull()
    expect(rewriteCommand("bash -c 'pytest a'", FPM)).toBeNull()
    expect(rewriteCommand('"pytest" x.py', FPM)).toBeNull()
  })
  test('words not at a command position', async () => {
    expect(rewriteCommand('echo pytest', FPM)).toBeNull()
    expect(rewriteCommand('git log --grep pytest', FPM)).toBeNull()
    expect(rewriteCommand('which pytest', FPM)).toBeNull()
  })
  test('qualified, versioned or already-routed interpreters', async () => {
    expect(rewriteCommand('/usr/bin/python -m pytest x.py', FPM)).toBeNull()
    expect(rewriteCommand('python3.11 -m pytest x.py', FPM)).toBeNull()
    expect(rewriteCommand('"$PY" -m pytest a.py', FPM)).toBeNull()
    expect(rewriteCommand('$PY -m pytest a.py', FPM)).toBeNull()
  })
  test('Object.prototype keys are not program words', async () => {
    expect(rewriteCommand('toString x; echo pytest', FPM)).toBeNull()
    expect(rewriteCommand('constructor; echo pytest', FPM)).toBeNull()
    expect(rewriteCommand('hasOwnProperty a && pytest a.py', FPM)).toBe(`hasOwnProperty a && ${Q} -m pytest a.py`)
  })
  test('heredoc bodies', async () => {
    const cmd = 'cat <<EOF > notes.txt\npython -m pytest x.py\npytest\nEOF\necho done'
    expect(rewriteCommand(cmd, FPM)).toBeNull()
    const after = "cat <<'END'\npytest a\nEND\npytest b"
    expect(rewriteCommand(after, FPM)).toBe(`cat <<'END'\npytest a\nEND\n${Q} -m pytest b`)
  })
  test('uncertain structure: unbalanced quotes, backticks, subshells', async () => {
    expect(rewriteCommand('pytest "x.py', FPM)).toBeNull()
    expect(rewriteCommand('pytest `which x`', FPM)).toBeNull()
    expect(rewriteCommand('pytest $(echo x.py)', FPM)).toBeNull()
    expect(rewriteCommand('(cd a && pytest)', FPM)).toBeNull()
    expect(rewriteCommand('cat <<EOF\npytest', FPM)).toBeNull()
  })
})

describe('rewriteNote', () => {
  test('truncates the command to 200 characters', async () => {
    const long = `${Q} ${'x'.repeat(400)}`
    const note = rewriteNote(long)
    expect(note.startsWith(NOTE_PREFIX)).toBe(true)
    expect(note.length).toBe(NOTE_PREFIX.length + 200 + 3)
  })
})

describe('interpreterPath', () => {
  test('an absolute path is kept, backslashes become forward slashes', async () => {
    expect(interpreterPath(FPM)).toBe(FPM)
    expect(interpreterPath('  C:\\py\\envs\\proj\\python.exe ')).toBe(FPM)
    expect(interpreterPath('/opt/venv/bin/python')).toBe('/opt/venv/bin/python')
  })
  test('unset, blank, relative or unquotable paths are refused', async () => {
    expect(interpreterPath(undefined)).toBeUndefined()
    expect(interpreterPath('   ')).toBeUndefined()
    expect(interpreterPath('venv/bin/python')).toBeUndefined()
    expect(interpreterPath('python.exe')).toBeUndefined()
    expect(interpreterPath('C:/py/"x"/python.exe')).toBeUndefined()
    expect(interpreterPath('/opt/$HOME/python')).toBeUndefined()
  })
})

const WITH_PY = { options: { python: FPM } }

describe('tool.call hook', () => {
  test('rewrites, notes the result and counts the rewrite', WITH_PY, async ($, on) => {
    const seen = world(on, { files: [FPM] })
    const counted = rewriteWrites(on)
    const ran = await $.tool.call({ tool: 'Bash', command: 'pytest t.py | head' })
    const expected = `${Q} -m pytest t.py | head`
    expect(seen).toEqual([expected])
    expect(ran.context).toEqual([`${NOTE_PREFIX}${expected}`])
    expect(counted).toEqual([1])
  })

  test('a backslash option value is written with forward slashes', {
    options: { python: 'C:\\py\\envs\\proj\\python.exe' },
  }, async ($, on) => {
    const seen = world(on, { files: [FPM] })
    await $.tool.call({ tool: 'Bash', command: 'pytest a.py' })
    expect(seen).toEqual([`${Q} -m pytest a.py`])
  })

  test('a non-rewritten call reaches the tool unchanged with no note', WITH_PY, async ($, on) => {
    const seen = world(on, { files: [FPM] })
    const ran = await $.tool.call({ tool: 'Bash', command: 'git log --grep pytest' })
    expect(seen).toEqual(['git log --grep pytest'])
    expect(ran.context).toBeUndefined()
  })

  test('python unset passes through', async ($, on) => {
    const seen = world(on, { files: [FPM] })
    const ran = await $.tool.call({ tool: 'Bash', command: 'pytest x.py' })
    expect(seen).toEqual(['pytest x.py'])
    expect(ran.context).toBeUndefined()
  })

  test('python blank passes through', { options: { python: '' } }, async ($, on) => {
    const seen = world(on, { files: [FPM] })
    await $.tool.call({ tool: 'Bash', command: 'pytest a.py' })
    expect(seen).toEqual(['pytest a.py'])
  })

  test('a relative python passes through', { options: { python: 'venv/python.exe' } }, async ($, on) => {
    const seen = world(on, { files: ['venv/python.exe'] })
    await $.tool.call({ tool: 'Bash', command: 'pytest a.py' })
    expect(seen).toEqual(['pytest a.py'])
  })

  test('a missing interpreter file passes through', {
    options: { python: 'C:/nobody/envs/gone/python.exe' },
  }, async ($, on) => {
    const seen = world(on, {})
    const first = await $.tool.call({ tool: 'Bash', command: 'pytest a.py' })
    await $.tool.call({ tool: 'Bash', command: 'python -m pytest b.py' })
    expect(seen).toEqual(['pytest a.py', 'python -m pytest b.py'])
    expect(first.context).toBeUndefined()
  })

  test('a failing fs.stat passes the original command through', WITH_PY, async ($, on) => {
    const seen: string[] = []
    on('fs.stat', () => {
      throw new Error('boom')
    })
    on('tool.call', { tool: 'Bash' }, (_$, e) => {
      seen.push(e.command)
      return { result: { stdout: 'ok', stderr: '', interrupted: false } }
    })
    const ran = await $.tool.call({ tool: 'Bash', command: 'pytest x.py' })
    expect(seen).toEqual(['pytest x.py'])
    expect(ran.deny).toBeUndefined()
    expect(ran.context).toBeUndefined()
  })

  test('a failed counter write keeps the rewrite and its note', WITH_PY, async ($, on) => {
    const seen = world(on, { files: [FPM] })
    on('state.set', () => {
      throw new Error('state store down')
    })
    const ran = await $.tool.call({ tool: 'Bash', command: 'pytest a.py' })
    expect(seen).toEqual([`${Q} -m pytest a.py`])
    expect(ran.context).toEqual([`${NOTE_PREFIX}${Q} -m pytest a.py`])
  })

  test('a denied call keeps its deny and gains no note', WITH_PY, async ($, on) => {
    on('fs.stat', () => ({ value: FILE }))
    on('tool.call', { tool: 'Bash' }, () => ({ deny: 'blocked beneath' }))
    const ran = await $.tool.call({ tool: 'Bash', command: 'pytest x.py' })
    expect(ran.context).toBeUndefined()
  })

  test('the interpreter existence check is cached per path', {
    options: { python: 'C:/cache/envs/probe/python.exe' },
  }, async ($, on) => {
    const stats: string[] = []
    on('fs.stat', (_$, e) => {
      stats.push(e.path)
      return { value: FILE }
    })
    on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: '', stderr: '', interrupted: false } }))
    await $.tool.call({ tool: 'Bash', command: 'python -m pytest a.py' })
    await $.tool.call({ tool: 'Bash', command: 'pytest b.py' })
    expect(stats.length).toBe(1)
  })

  test('the PowerShell tool is never rewritten', WITH_PY, async ($, on) => {
    on('fs.stat', () => ({ value: FILE }))
    const seen: string[] = []
    on('tool.call', { tool: 'PowerShell' }, (_$, e) => {
      seen.push(e.command)
      return { result: { output: 'ok' } as never }
    })
    const ran = await $.tool.call({ tool: 'PowerShell', command: 'python -m pytest x.py' })
    expect(seen).toEqual(['python -m pytest x.py'])
    expect(ran.context).toBeUndefined()
  })

  test('a failure after next was called settles to that call without a second run', WITH_PY, async ($, on) => {
    on('fs.stat', () => ({ value: FILE }))
    const seen: string[] = []
    on('tool.call', { tool: 'Bash' }, (_$, e) => {
      seen.push(e.command)
      throw new Error('tool blew up')
    })
    const failed = await $.tool.call({ tool: 'Bash', command: 'pytest x.py' }).then(
      () => false,
      () => true,
    )
    // pins the no-second-run outcome; the engine settles it the same way with or without .catch
    expect(seen).toEqual([`${Q} -m pytest x.py`])
    expect(failed).toBe(true)
  })

  test('bare forms with their own rules reach the tool unchanged', WITH_PY, async ($, on) => {
    const seen = world(on, { files: [FPM] })
    const counted = rewriteWrites(on)
    const kept = [
      'python -c "print(1)"',
      'ruff check src/a.py | head',
      'pylint src/a.py',
      'PYTHONPATH="C:/r;C:/r/src" python -m pytest x.py',
    ]
    for (const command of kept) {
      const ran = await $.tool.call({ tool: 'Bash', command })
      expect(ran.context).toBeUndefined()
    }
    expect(seen).toEqual(kept)
    expect(counted).toEqual([])
  })

  test('a Windows python.exe -m pytest call is rewritten end to end', WITH_PY, async ($, on) => {
    const seen = world(on, { files: [FPM] })
    await $.tool.call({ tool: 'Bash', command: 'python.exe -m pytest tests/test_x.py -v' })
    expect(seen).toEqual([`${Q} -m pytest tests/test_x.py -v`])
  })
})
