export const meta = {
  name: 'adversarial-review',
  description: 'pr-review Phase 2 under -a: reviewers and code refuters, each followed by its findings refuter',
  whenToUse: 'Only from a pr-review or review-local run with -a, with the args capture printed',
  phases: [
    { title: 'Review', detail: 'each reviewer slot, then the findings refuter of its report' },
    { title: 'Attack', detail: 'each code refuter, then the findings refuter of its attacks' },
  ],
}

// Every agent type, model and prompt arrives in args (capture's workflow_args); the script holds none.
// Agents record through the typed API their briefs name, so the script carries no findings and returns
// only which entries returned. A null stage result skips the item's later stages, so a findings refuter
// never runs after its reviewer or code refuter failed or replied with a problem line.

if (!args || typeof args !== 'object') {
  log('no args object: pass the args capture -a printed')
  return []
}

const reviewers = args.reviewers || []
const code = args.code || []
const refute = args.refute || []
const guidance = typeof args.guidance === 'string' ? args.guidance.replace(/\s+/g, ' ').trim() : ''

const REVIEW = { phase: 'Review' }
const ATTACK = { phase: 'Attack' }

const returned = {}

const withGuidance = prompt => (guidance ? prompt + '\nDeveloper guidance: ' + guidance : prompt)

const isProblem = result => typeof result === 'string' && result.trimStart().startsWith('problem:')

const dispatch = (entry, group) =>
  agent(withGuidance(entry.prompt), { ...group, label: entry.id, agentType: entry.agentType, model: entry.model })
    .then(result => {
      const ok = result !== null && result !== undefined && !isProblem(result)
      returned[entry.id] = ok
      return ok ? result : null
    })

const refuterOf = target => refute.find(entry => entry.target === target) || null

const thenRefute = group => (_, entry) => {
  const refuter = refuterOf(entry.id)
  return refuter ? dispatch(refuter, group) : null
}

const targets = new Set([...reviewers, ...code].map(entry => entry.id))
const orphans = new Set(refute.filter(entry => !targets.has(entry.target)).map(entry => entry.id))
if (orphans.size) log('findings refuters without a target in args, not run: ' + [...orphans].join(', '))
// refuterOf dispatches only the first entry per target; later entries for the same target never run.
const firstFor = new Map()
refute.forEach((entry, index) => { if (!firstFor.has(entry.target)) firstFor.set(entry.target, index) })
const repeats = new Set(refute.filter((entry, index) => firstFor.get(entry.target) !== index).map(entry => entry.id))
if (repeats.size) log('findings refuters repeating a target, not run: ' + [...repeats].join(', '))

await parallel([
  () => pipeline(reviewers, entry => dispatch(entry, REVIEW), thenRefute(REVIEW)),
  () => pipeline(code, entry => dispatch(entry, ATTACK), thenRefute(ATTACK)),
])

const row = entry => {
  const base = { id: entry.id, returned: returned[entry.id] === true }
  if (orphans.has(entry.id)) return { ...base, orphan: true }
  return repeats.has(entry.id) ? { ...base, repeat: true } : base
}
const results = [...reviewers, ...code, ...refute].map(row)
const failed = results.filter(r => !r.returned && !r.orphan && !r.repeat).map(r => r.id)
log('returned ' + results.filter(r => r.returned).length + '/' + results.length)
if (failed.length) log('not returned (recover with a plain Agent dispatch, reviewer first): ' + failed.join(', '))
return results
