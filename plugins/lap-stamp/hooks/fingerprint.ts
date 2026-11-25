/**
 * Text fingerprint shared by the writer (a turn's answer at `turn.complete`) and the reader (a drawn reply block at
 * render). Both sides normalize the same way, so a block the terminal draws without its `<context>` span still
 * matches the row written from the full answer.
 */

export type Fingerprint = {
  /** FNV-1a 64 of the normalized text, 16 lower-case hex chars. */
  hash: string
  /** Length of the normalized text in UTF-16 code units. */
  len: number
}

const CONTEXT_SPAN = /<context(?:\s[^>]*)?>[\s\S]*?<\/context>/g

const FNV_OFFSET = BigInt('0xcbf29ce484222325')
const FNV_PRIME = BigInt('0x100000001b3')
const MASK_64 = BigInt('0xffffffffffffffff')

/** Drops `<context>...</context>` spans, unifies line endings to LF and trims both ends. */
export function normalizeAnswer(text: string): string {
  return text.replace(CONTEXT_SPAN, '').replace(/\r\n?/g, '\n').trim()
}

/** FNV-1a 64 over the UTF-8 bytes of the text, as 16 lower-case hex chars. */
export function fnv1a64Hex(text: string): string {
  let hash = FNV_OFFSET
  for (const byte of new TextEncoder().encode(text)) {
    hash = ((hash ^ BigInt(byte)) * FNV_PRIME) & MASK_64
  }
  return hash.toString(16).padStart(16, '0')
}

/** Hash and normalized length of the text; null when the normalized text is empty. */
export function fingerprintOf(text: string): Fingerprint | null {
  const normalized = normalizeAnswer(text)
  if (normalized === '') return null
  return { hash: fnv1a64Hex(normalized), len: normalized.length }
}
