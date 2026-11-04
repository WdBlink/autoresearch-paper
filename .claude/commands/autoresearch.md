---
name: autoresearch
description: Research brief to evidence-bound experiments, figures and an internally reviewed paper
---

# Research to paper

This is the main research workflow. It uses the complete
Autoresearch base; its classic and orchestrator protocols, helpers, hooks,
keep/discard and fresh-context exploration remain available.

Resolve `paper/` relative to the installed autoresearch skill. Run commands with
Python 3.10+ through `paper/scripts/research.py`; the repository shortcut is
`scripts/research.py`. Read `paper/references/runtime-contract.md` once. Do not
launch the historical autoresearch-paper Harness or a second research scheduler.

## Start and work

1. Read the current question, complete materials and resource authorization.
   Build the Brief JSON described by `paper/references/packets.md`, including
   every required figure, table and section in `deliverable_plan`. Venue choice
   belongs to the user's research scope; compare candidates using official
   instructions and representative accepted papers before choosing. A generic
   citation or page quota does not replace the venue calibration.
2. Choose the preparation branch before approval. A concrete research Brief with an already chosen venue and complete obligations can use `init`, display that exact Brief and relay its actual approval. If venue/obligations are undecided, use `contract_status: draft`, `venue: undecided`, and an empty `deliverable_plan`; do not ask for final approval yet.
3. For a draft, commit read-only intake, prepare sourced venue candidates, relay the actual selected candidate with `confirm-venue`, calibrate the chosen target, and commit venue. Use `set-contract` to produce the concrete post-calibration Brief, show it, and relay its actual final approval. No experimental dispatch can use a draft or a merely completed selection audit.
   If the current user has already delegated topic/venue selection and the whole
   bounded research run, use the evidence-bound `--authorization` record described
   in `packets.md`. Record the host's delegated decision, never a fictitious exact
   human approval or an extra confirmation for an already authorized action.
4. Run `context`. It returns the current stage knowledge, upstream protocol,
   frozen input hashes, itemized obligations and typed action contracts.
   Actually read this returned context. Perform that stage's task with the
   authorized host tools and return its versioned packet and artifacts.
5. Submit `commit --packet /absolute/packet.json --operation-id ID`. Technical
   validation records the stage; it does not judge research novelty. Fix a
   refused packet using the actual diagnostics. `context` then reveals only the
   next stage's specialized knowledge. Stages are intake, venue, plan,
   literature, experiment, figures, write and independent review.
6. The frozen plan covers every requirement with a WorkOrder and typed actions.
   `execute --work-id ID --operation-id ID` performs registered local rendering,
   compilation or validation. The host performs actual research/experiments;
   its raw outcomes still go through the same experiment and figure checks.
   No generated program or arbitrary shell action is executed by this command.
7. After writing, submit one `bind --packet ... --operation-id ...` per required
   item. A binding names the WorkOrder, exact assets, evidence, manuscript and
   insertion location. An independent reviewer then reads `context`, the
   artifact bundle, R6's original plan, current plan and compiled PDF. It returns
   G1–G5, R6 and a `requirement_checks` entry for every binding. A high overall
   score cannot waive a missing item. Preserve negative and inconclusive results.
8. Commit review, close its round checkpoint, then `finalize --operation-id ID`. The deterministic finalizer
   rechecks evidence and produces a manifest, actual PDF and editable TeX with
   all declared assets and receipts. `verify-export --manifest ...` verifies the
   exported bytes. Internal review does not assert external academic acceptance
   and does not authorize submission.

Before each work round, call `begin-round` to capture the actual original plan
and document baseline. After work, `prepare-round --evidence ...` issues the
current state/rules/evidence-bound judgment request. Return the real host
judgment using `apply-round`; unchanged reads are not research progress.
Store both the returned request JSON and decision JSON outside the run or in
`control/round-decisions/`. Keep CLI transport/response logs outside the run as
well; writing them into ordinary research documents after preparation changes
the captured digest and invalidates `apply-round`. A plan
change needs an actual R6 report bound to the round and both plan versions.
Use the Brief's approved limits; defaults are 15 rounds / 30 minutes per host
session, at most five empirical experiment rounds, and at most five changed
large documents per round. Explain justified workload deviations. A limit
ends continuation; it does not grant completion.

Use `tool --name venue-compare`, `venue-design-template`, `venue-calibrate`,
`plan-snapshot`, `plan-audit` and `citation-check` for mechanical work. Exact
fields and invocations are in `paper/references/packets.md`. Compare 8–15
matched accepted samples by default, normally the recent two editions (or the
declared journal window); read every measured visual and panel. Machine counts
and templates do not constitute visual understanding. For approved
non-empirical reviews/surveys, retain a reasoned experiment/G2 inapplicability
and use verified source claims and evidence diagrams without invented data.
To share a preliminary PDF, use `draft-preview`; it marks DRAFT and reports
the current incomplete requirements and blockers, without completing the run.

## Iterate, recover and escape a plateau

During method work use the upstream classic loop with the frozen metric,
verification command and allowed code scope. Keep the run's `.paper/` state and
frozen evaluator outside Git rollback. Never optimize held-out test data or
turn a working-metric keep into scientific acceptance. For open-ended planning,
use the upstream orchestrator or reason/probe protocols; subjective judgments
are not fabricated mechanical metrics. The paper controller remains the sole
paper-state owner.

Fork-and-flush follows `references/fork-and-flush.md`: scheduled rounds at 33%
and 66% (one at 50% below 12 iterations), every 20 unbounded iterations, plus
five iterations without a keep replacing the next scheduled round. The
orchestrator instead allows two plateau rounds without progress. Each branch
starts at the best commit with empty conversation and only task/files/results;
the stateless Advisor gives distinct experiments to the guided fraction.
`paper/lib/exploration.py` supplies deterministic trigger/request, real isolated
Git worktrees, evidence-bound selection and fast-forward promotion. It never
merges paper-state files. The host launches/resumes the actual agents and
retains every failed branch result. It must report if the host lacks fresh
context or resumable leadership. No agent round was demonstrated by a fixture.

A missing terminal effect receipt is uncertain. Use `reconcile` with evidence
before replay; completed audit is not GO. Known failed work and scientific
negative results have different semantics. `rewind --stage ... --reason ...`
retains old receipts and invalidates later bindings and review. Reuse operation
IDs only with identical arguments. Changed approved obligations require a newly
approved Brief, never a quietly edited plan.
