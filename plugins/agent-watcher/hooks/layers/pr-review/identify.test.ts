import { describe, expect, test } from 'claude-code/testing'

import { identify } from './identify'

const RUN = 'pr1526_20261009T120000Z'
const BASE = '.claude/state/harness/pr-team/_runtime'
const slot = (extra: string): string => `${extra}AGENT_ID: r1\nAGENT_ROLE: reviewer\nRUN_ID: ${RUN}`

describe('identify: a foreign SKILL header is never claimed (Decision D9)', () => {
  test('a reviewer slot under another skill is refused, pr-team or pr-review alike', async () => {
    expect(identify('harness:pr-reviewer', slot('SKILL: bubble-memo\n'), BASE)).toBeUndefined()
    expect(identify('harness:pr-reviewer', slot('SKILL: bubble-memo\nPR: 1526\n'), BASE)).toBeUndefined()
    expect(identify('pr-team-fixer', `SKILL: strap-skills\nMODE=CLOSEOUT\nRUN_ID=${RUN}`, BASE)).toBeUndefined()
  })

  test('a header naming pr-review or pr-team, or no skill, is claimed as before', async () => {
    expect(identify('harness:pr-reviewer', slot(''), BASE)?.skill).toBe('pr-team')
    expect(identify('harness:pr-reviewer', slot('SKILL: pr-team\n'), BASE)?.skill).toBe('pr-team')
    expect(identify('harness:pr-reviewer', slot('SKILL: pr-review\nPR: 1526\n'), BASE)).toMatchObject({
      skill: 'pr-review', pr: 1526, agentId: 'r1', role: 'reviewer',
    })
  })
})
