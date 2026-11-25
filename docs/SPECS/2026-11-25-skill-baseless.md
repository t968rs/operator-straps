# Skill: baseless

Date: 2026-11-25

## Request

Bundle a harness skill named baseless that carries the verification-before-completion discipline, adapted from
the outside plugin's skill of that name, so no harness skill or rule depends on that plugin for it. Every
pointer that names the outside verification skill moves to harness:baseless, post-forcepush's verification
step included. This is the skill only: the rewrite of post-forcepush's verification step into inline checks is
separate work, and the outside plugin stays installed.

## Goals

- harness:baseless appears in the skill list and loads through the Skill tool.
- The skill's description triggers on its own, without waiting on another plugin being absent.
- The skill states the gate: name the command that proves a claim, run it, read its output, then claim.
- The skill maps each kind of claim to the evidence it needs.
- The skill lists the hedge words that stop a completion claim.
- The skill treats a subagent's success report as unverified until checked.
- post-forcepush's verification step invokes harness:baseless.
- post-forcepush's final report and common-mistakes table name harness:baseless.
- The session rules' claim-making rule names harness:baseless.
- The parallel2 README's evidence-before-claiming row names harness:baseless.
- A search of the live plugin skills, rules and READMEs finds no pointer to the outside verification skill.
- The skill's source and license are recorded the same way earlier ported skills record theirs.

## Avoid

- The outside plugin is not uninstalled or disabled.
- Pointers to the outside plugin's other skills do not change.
- post-forcepush's verification step is not replaced by inline checks.
- The skill's description and body do not name the plugin it came from.
- The session rules file does not pass its size cap.
- Review records, plans, research notes and cut release notes are not rewritten.
