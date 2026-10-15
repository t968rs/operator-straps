/** A `/pytest-broad-ok` override: armed until the next broad pytest call consumes it. */
export type BroadOverride = boolean

declare module 'claude-code' {
  interface PluginState {
    'pytest-scope': {
      /** Interpreter rewrites of calls that were not denied, this session. */
      rewrites: number
      /** One-shot override armed by /pytest-broad-ok. */
      broadOk: BroadOverride
    }
  }
}
