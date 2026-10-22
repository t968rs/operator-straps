import { describe, expect, test } from 'claude-code/testing'

import {
  DEFAULT_STATE_DIR,
  MAX_NOTE_CHARS,
  MAX_NOTES,
  NOTES_PATH,
  NOTES_SCHEMA_VERSION,
  notesFileOf,
  parseNotes,
  stateDirOf,
} from './notes'

const file = (notes: unknown, version: unknown = NOTES_SCHEMA_VERSION): string => JSON.stringify({ version, notes })
const entry = (text: unknown): { added: string; text: unknown } => ({ added: '2026-10-22T00:00:00Z', text })

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
    expect(parseNotes(file([entry('  first '), entry('second')]))).toEqual(['first', 'second'])
  })

  test('malformed JSON, another version or no notes array hold none', async () => {
    for (const text of ['{not json', '[]', file([entry('x')], 2), '{"version":1}', file('x')]) {
      expect(parseNotes(text)).toEqual([])
    }
  })

  test('blank and non-text entries are dropped', async () => {
    expect(parseNotes(file([entry('keep'), entry('   '), entry(5), 'bare', null, { added: 'x' }]))).toEqual(['keep'])
  })

  test('a note past MAX_NOTE_CHARS is cut', async () => {
    expect(parseNotes(file([entry('z'.repeat(MAX_NOTE_CHARS + 5))]))).toEqual(['z'.repeat(MAX_NOTE_CHARS)])
  })

  test('more than MAX_NOTES keeps the newest', async () => {
    const texts = Array.from({ length: MAX_NOTES + 3 }, (_, i) => `n${i}`)
    expect(parseNotes(file(texts.map(entry)))).toEqual(texts.slice(3))
  })
})
