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

describe('identify: adversarial refuters are pr-review slots', () => {
  const ADV = 'harness:adversarial-reviewer'
  const refuter = (id: string, role: string, pr = 'PR: 1526\n'): string =>
    `AGENT_ID: ${id}\nAGENT_ROLE: ${role}\nRUN_ID: ${RUN}\n${pr}`

  test('a findings refuter and a code refuter are claimed in the review phase', async () => {
    expect(identify(ADV, refuter('adv_refute_runtime', 'refuter'), BASE)).toEqual({
      runId: RUN, skill: 'pr-review', agentId: 'adv_refute_runtime', role: 'refuter', pr: 1526, runtimeDir: null,
      phase: 'review',
    })
    expect(identify(ADV, refuter('adv_code', 'code_refuter'), BASE)).toMatchObject({
      skill: 'pr-review', agentId: 'adv_code', role: 'code_refuter', phase: 'review',
    })
  })

  test('a local run key is kept', async () => {
    const local = refuter('adv_code_tests', 'code_refuter', 'PR: local-fix-band\n')
    expect(identify(ADV, local.replace(RUN, 'local-fix-band_20261009T120000Z'), BASE)).toMatchObject({
      pr: 'local-fix-band', role: 'code_refuter',
    })
  })

  test('a refuter role without a PR line, a spaced role or another skill is not claimed', async () => {
    expect(identify(ADV, refuter('adv_code', 'code_refuter', ''), BASE)).toBeUndefined()
    expect(identify(ADV, refuter('adv_code', 'code refuter'), BASE)).toBeUndefined()
    expect(identify(ADV, `SKILL: bubble-memo\n${refuter('adv_code', 'code_refuter')}`, BASE)).toBeUndefined()
  })
})
