---
name: autoresearch
description: "Research to paper: develop a research question, compare venues, study matched accepted papers, plan and run experiments, then write and independently review an evidence-bound manuscript."
metadata:
  version: "3.0.0"
  research-workflow: "3"
---

# Autoresearch Paper

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
Venue selection and the concrete plan budget are user-answer checkpoints.
Prepare the sourced candidates or budget proposal with `ask-user`; use
question or the host's supported user-input interface (Codex can use
`request_user_input_async` when available), wait for an actual
answer, then apply its source-bound response. Show the budget default of no
implicit task cap and the optional calls, tokens, cost and total-time limits.
An increase requires another concrete question. Existing explicit answers may
be reused when they match the current question; execution delegation and a
preselected option do not supply an answer. See `paper/references/user-input.md`.

The stages are intake → venue selection/calibration → plan → literature →
experiment/evidence synthesis → figures → write → independent review → delivery.
Use the same state owner for rounds, snapshots, effects, bindings and recovery.
A code keep, a completed tool or an overall score cannot satisfy a missing claim.

The only public resource-limit configuration is the Brief's `budget`.
Usage is receipt-backed in the same controller and survives host-session changes.
Thirty minutes prompts a checkpoint and continuation, not task termination.
Continue authorized internal repair; wait only on the affected external
dependencies. A stopped checkpoint requires an actual user stop or a verified
task-budget reason. Full completion still belongs to the original finalizer.
Read `paper/references/budget.md` for resource admission and recovery.

An `active` checkpoint preserves a continuation point. Keep working on the next
executable part of the original research request. Replies about venue, budget or
browser availability steer that same request; completing that intermediate step
does not finish it. Before ending a host turn, apply the continuation and handoff
conditions in the main command. Required user choices must actually be asked
through the host's user-input interface before they can justify waiting.

Use the stage's `production_steps` and `paper/references/production.md` for
provided acquisition, recording, render/export, source variants and review
assembly. The main CLI owns path resolution, round-request persistence and
export verification. Keep dataset/method choices in the research adapter;
do not copy a previous study's counts, filenames or reviewer roles into a run.


Before promising an empirical run, preflight the actual condition matrix against
the recording/statistics adapter. The supplied numerical adapter admits named
conditions with preregistered paired contrasts, averaging seeds within independent
cases. Preserve the full case × seed × condition denominator, including failed
and unstarted slots; operational failures block statistics. This descriptive
protocol supplies no universal statistical inference or scientific completion.
A two-arm development diagnostic does not satisfy a larger planned comparison.
For the separately bounded fixed-template vector profile, use
`paper/references/local-response-protocol.md`. Preserve its nested states,
source/receipt closure and two prospective freezes; its engineering tolerances
do not establish full-state identification or global stability.

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

## Run bounded engineering work

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
