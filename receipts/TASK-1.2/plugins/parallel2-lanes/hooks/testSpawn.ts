/**
 * The `agent.spawn` input the hook tests share (never imported by ./register): one copy, so a change to
 * `AgentSpawnInput` edits one builder.
 */

import type { AgentSpawnInput } from 'claude-code'

/**
 * A full `agent.spawn` input for one plain Agent call. A variant sets only the flag a test needs (`resume`,
 * or the fork, teammate and workflow flags), not the other values the engine raises with it.
 */
export const spawnInput = (prompt: string, description: string, over: Partial<AgentSpawnInput> = {}): AgentSpawnInput => ({
  tool_use_id: 'toolu_1', prompt, description, subagentType: 'general-purpose',
  provider: { plugin: 'engine', tier: 'core' }, parentModel: 'opus', background: false, fork: false, ...over,
})
