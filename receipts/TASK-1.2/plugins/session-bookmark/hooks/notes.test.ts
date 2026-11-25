import { describe, expect, test } from 'claude-code/testing'

import {
  DEFAULT_STATE_DIR,
  MAX_NOTE_CHARS,
  MAX_NOTES,
  markingBranch,
  NOTE_BRANCH_KEY,
  NOTES_PATH,
  NOTES_SCHEMA_VERSION,
  noteLine,
  notesFileOf,
  OTHER_BRANCH_MARK,
  parseNotes,
  parseNotesOrNull,
  stateDirOf,
} from './notes'

const file = (notes: unknown, version: unknown = NOTES_SCHEMA_VERSION): string => JSON.stringify({ version, notes })
const entry = (text: unknown): { added: string; text: unknown } => ({ added: '2026-10-22T00:00:00Z', text })
const onBranch = (text: string, branch: unknown) => ({ ...entry(text), [NOTE_BRANCH_KEY]: branch })
const standing = (text: string) => ({ text, branch: null })

describe('stateDirOf', () => {
  test('the configured state_dir, cleaned', async () => {
    expect(stateDirOf('{"state_dir": "var\\\\state/"}')).toBe('var/state')
  })

  test('absent, malformed, blank or wrong-typed text gives the default', async () => {
    for (const text of [undefined, '', '{not json', '[]', '{}', '{"state_dir": "  "}', '{"state_dir": 3}']) {
      expect(stateDirOf(text)).toBe(DEFAULT_STATE_DIR)
    }
  })
})

describe('notesFileOf', () => {
  test('joins root, state dir and the notes path', async () => {
    expect(notesFileOf('/repo', '.claude/state/harness')).toBe(`/repo/.claude/state/harness/${NOTES_PATH}`)
    expect(notesFileOf('C:\\repo\\', 'var')).toBe(`C:/repo/var/${NOTES_PATH}`)
  })

  test('an absolute state dir is kept as it is', async () => {
    expect(notesFileOf('/repo', '/data/state')).toBe(`/data/state/${NOTES_PATH}`)
    expect(notesFileOf('/repo', 'D:/state')).toBe(`D:/state/${NOTES_PATH}`)
  })
})

describe('parseNotes', () => {
  test('the texts, oldest first, trimmed', async () => {
    expect(parseNotes(file([entry('  first '), entry('second')]))).toEqual([standing('first'), standing('second')])
  })

  test('malformed JSON, another version or no notes array hold none', async () => {
    for (const text of ['{not json', '[]', file([entry('x')], 2), '{"version":1}', file('x')]) {
      expect(parseNotes(text)).toEqual([])
    }
  })

  test('blank and non-text entries are dropped', async () => {
    const notes = [entry('keep'), entry('   '), entry(5), 'bare', null, { added: 'x' }]
    expect(parseNotes(file(notes))).toEqual([standing('keep')])
  })

  test('a note past MAX_NOTE_CHARS is cut', async () => {
    expect(parseNotes(file([entry('z'.repeat(MAX_NOTE_CHARS + 5))]))).toEqual([standing('z'.repeat(MAX_NOTE_CHARS))])
  })

  test('more than MAX_NOTES keeps the newest', async () => {
    const texts = Array.from({ length: MAX_NOTES + 3 }, (_, i) => `n${i}`)
    expect(parseNotes(file(texts.map(entry)))).toEqual(texts.slice(3).map(standing))
  })

  test('the branch is read, trimmed', async () => {
    expect(parseNotes(file([onBranch('a', ' dev ')]))).toEqual([{ text: 'a', branch: 'dev' }])
  })

  test('parseNotesOrNull tells a refused file (null) from an empty one ([])', async () => {
    for (const text of ['{not json', '[]', file([entry('x')], 2), '{"version":1}', file('x')]) {
      expect(parseNotesOrNull(text)).toBeNull()
    }
    expect(parseNotesOrNull(file([]))).toEqual([])
    expect(parseNotesOrNull(file([entry('keep')]))).toEqual([standing('keep')])
  })

  test('an absent, non-text or blank branch reads as a standing note', async () => {
    const notes = [entry('absent'), onBranch('number', 7), onBranch('null', null), onBranch('blank', '  ')]
    expect(parseNotes(file(notes))).toEqual(['absent', 'number', 'null', 'blank'].map(standing))
  })
})

describe('markingBranch', () => {
  test('a detached HEAD marks against no branch; any other name is kept', async () => {
    expect(markingBranch('HEAD')).toBeNull()
    expect(markingBranch('dev')).toBe('dev')
    expect(markingBranch(null)).toBeNull()
  })
})

describe('noteLine', () => {
  test('a standing note prints its text alone', async () => {
    expect(noteLine(1, standing('keep it'), 'dev')).toBe('1. keep it')
    expect(noteLine(2, standing('keep it'), null)).toBe('2. keep it')
  })

  test('a note on the current branch prints the branch', async () => {
    expect(noteLine(3, { text: 'keep it', branch: 'dev' }, 'dev')).toBe('3. [dev] keep it')
  })

  test('an unknown current branch prints the branch with no mark', async () => {
    expect(noteLine(1, { text: 'keep it', branch: 'dev' }, null)).toBe('1. [dev] keep it')
  })

  test('a note from another branch is marked with the current one', async () => {
    expect(noteLine(4, { text: 'keep it', branch: 'dev' }, 'main')).toBe(`4. [dev; ${OTHER_BRANCH_MARK} main] keep it`)
    expect(OTHER_BRANCH_MARK).toBe('now on')
  })
})
