/**
 * One memo still holding an `Open` index row. `memo` and `review` are absolute paths (forward slashes); `review`
 * is the newest `<NNNN>_*.json` for the memo's PR, null while none exists. `mtimeMs` is the review JSON's mtime
 * as last read; 0 before the first read.
 */
export type ActiveMemo = {
  memo: string
  review: string | null
  mtimeMs: number
}

declare module 'claude-code' {
  interface PluginState {
    'bubble-stamp': {
      /** Active memos by file name (`PR_<N>_Bubbles.md`). */
      memos: Record<string, ActiveMemo>
    }
  }
}
