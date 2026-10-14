/** The Phase 5 sentinel rule of the harness plugin's `hooks/check_phase5_sentinel.py`. Pure: no `$`. */

/** Mirrors `MAX_AGE_SECONDS` in check_phase5_sentinel.py. */
export const MAX_AGE_SECONDS = 86400
export const SENTINEL_PREFIX = '.phase5_pending_'

export type SentinelText = { pr: string | null; writtenAt: number | null; sessionId: string | null }

const orNull = (s: string): string | null => (s === '' ? null : s)

/**
 * Line 1 the PR id, line 2 an optional unix-int write time, line 3 the optional id of the session
 * that armed it (CRLF tolerated).
 */
export const parseSentinel = (text: string): SentinelText => {
  const lines = text.split(/\r?\n/)
  const stamp = (lines[1] ?? '').trim()
  return {
    pr: orNull((lines[0] ?? '').trim()),
    writtenAt: /^\d+$/.test(stamp) ? Number(stamp) : null,
    sessionId: orNull((lines[2] ?? '').trim()),
  }
}

export const isHot = (basisSeconds: number, nowSeconds: number): boolean =>
  nowSeconds - basisSeconds < MAX_AGE_SECONDS

/**
 * Mirrors `blocks_session`: a hot sentinel spares a session only when both ids are known and differ.
 * A blank session id (after trimming, as the Python hook strips it) counts as unknown.
 */
export const blocksSession = (owner: string | null, sessionId: string | null | undefined): boolean => {
  const id = sessionId?.trim() ?? ''
  return owner === null || id === '' || owner === id
}

export const isSentinelName = (name: string): boolean =>
  name.startsWith(SENTINEL_PREFIX) && name.length > SENTINEL_PREFIX.length
