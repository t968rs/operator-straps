# Canonical per-agent prompt template

This is the single source-of-truth for the per-agent prompt body that the shim
splices into every parallel `Agent()` dispatch (Step 2 reviewers, Step 5 fixer
subagents). SKILL.md, `dispatch_plan.schema.json`, and the orchestrator/fixer
agent definitions reference this file by path — they MUST NOT inline a competing
template body.

The six slots — `{id}`, `{agent_role}`, `{prompt_file_path}`, `{output_file_path}`,
`{return_contract_path}`, `{run_id}` — are filled from the dispatch plan's per-agent entry, the
phase-derived role and the skill's own location. All other dispatch metadata (subagent_type,
model, description) is spliced into the `Agent()` envelope kwargs separately and is NOT part of
the prompt body.

## Template body (verbatim)

```
Read your task spec from {prompt_file_path}; follow its instructions; on completion
write detailed output to {output_file_path}; emit the strict return-contract block
per {return_contract_path} as the last thing in your
return text. Your return block MUST include `AGENT_ROLE: {agent_role}` as a
required field for terminals.jsonl schema validation.

AGENT_ID: {id}
AGENT_ROLE: {agent_role}
PROMPT_FILE: {prompt_file_path}
OUTPUT_FILE: {output_file_path}
RETURN_CONTRACT: {return_contract_path}
RUN_ID: {run_id}
```

## Slot binding

| Slot                 | Source                                                                                             |
|----------------------|----------------------------------------------------------------------------------------------------|
| `{id}`               | `dispatch_plan.agents[i].id`                                                                       |
| `{agent_role}`       | `"reviewer"` for Step 2 dispatches; `"fixer"` for Step 5 dispatches (derived from phase, NOT plan) |
| `{prompt_file_path}` | `dispatch_plan.agents[i].prompt_file_path`                                                         |
| `{output_file_path}` | `dispatch_plan.agents[i].output_file_path`                                                         |
| `{return_contract_path}` | absolute path of this skill's `return_contract.md` (`${CLAUDE_SKILL_DIR}/return_contract.md`) |
| `{run_id}`           | `dispatch_plan.run_id` (echoed unchanged from Step 1)                                              |

## Invariant

If the byte sequence of the template body above changes, every downstream
reference (SKILL.md Step 2 prose, `dispatch_plan.schema.json` $comment, agent
definition prose) must be updated in the same commit. The plugin's guard test
`tests/skills/test_canonical_prompt_template_referenced.py` asserts that SKILL.md
no longer inlines the template body — only references it by path.
