---
name: autoresearch
description: "Research to paper: develop a research question, compare venues, study matched accepted papers, plan and run experiments, then write and independently review an evidence-bound manuscript."
metadata:
  version: "2.3.0"
  research-workflow: "2"
---

# Autoresearch — Research to Paper

The whole Skill carries a research project from materials and open questions to
verified evidence and a paper. Writing is the late `write` stage, after literature,
experimental or review evidence, and figure planning. Do not start with prose or
fabricate results to complete an outline.

## Main entry

For `/autoresearch`, a research question, existing project or paper request, read
`../../commands/autoresearch.md` and follow the research workflow. The controller
reveals only the current stage's knowledge and executable handoff. No separate
paper subcommand is required.

Start with the current question, scope, angle, audience and available evidence.
If a venue is unknown, compare actual candidates before freezing a target. The
normal calibration sample is 8–15 accepted papers in the same direction, drawn
from the recent two editions or journal years; exceptions are explicit. Inspect
each measured figure/table and panel, not just caption counts. Venue knowledge
and the final obligation contract are ready before manuscript drafting.
When a consequential research choice is still missing, use question or
the host's supported input interface. Reuse the user's existing choices and
approval; a routine implementation detail does not require another question.

The stages are intake → venue selection/calibration → plan → literature →
experiment/evidence synthesis → figures → write → independent review → delivery.
Use the same state owner for rounds, snapshots, effects, bindings and recovery.
A code keep, a completed tool or an overall score cannot satisfy a missing claim.

Use the stage's `production_steps` and `paper/references/production.md` for
provided acquisition, recording, render/export, source variants and review
assembly. The main CLI owns path resolution, round-request persistence and
export verification. Keep dataset/method choices in the research adapter;
do not copy a previous study's counts, filenames or reviewer roles into a run.

## Auxiliary protocols

These are tools for a bounded research subtask, not competing product entries.
Read `../../commands/autoresearch_<name>.md` when the corresponding task arises.

| Command | Purpose |
| --- | --- |
| `/autoresearch_iterate` | Original classic metric loop, including `--classic`, keep/discard and rollback |
| `/autoresearch_plan` | Derive scope, metric and Verify for a bounded experimental/code subtask |
| `/autoresearch_debug`, `/autoresearch_fix` | Reproduce and fix implementation failures |
| `/autoresearch_probe`, `/autoresearch_reason`, `/autoresearch_predict` | Challenge assumptions and compare approaches |
| `/autoresearch_scenario`, `/autoresearch_improve` | Examine alternatives and edge cases |
| `/autoresearch_learn`, `/autoresearch_evals`, `/autoresearch_regression` | Record evidence, analyze progress and check regression |
| `/autoresearch_security`, `/autoresearch_ship` | Explicitly requested engineering audit or release; external actions retain their authorization boundary |

For a predicate-bearing engineering orchestration task, read
`references/engineering-orchestrator.md`. `--classic` explicitly selects iterate;
`--auto` selects this auxiliary orchestration protocol. A bare natural-language
research goal always enters the research workflow.

## Keep the upstream research mechanisms

The classic loop and orchestrator retain their existing limits, command screening,
hooks and rollback. `references/fork-and-flush.md` supplies fresh-context rounds
from the best commit: scheduled 33%/66%, a single 50% round below 12 iterations,
every 20 unbounded iterations, or five no-keep iterations replacing the next
scheduled round. Orchestrator plateaus permit two rounds without progress.
Use the files-only context and distinct Advisor assignments. Keep the authoritative
research ledger and evaluator outside the editable/rollback scope. Scientific
acceptance still requires the frozen contract and independent evidence review.

No push, publication, deployment, paid call or expanded compute follows merely
from loading the Skill. Actual approved research resources and scope control work.
