---
name: karpathy-autoresearch-adapter
description: Use when mapping a repository and frozen Research Brief into a plan-first, repository-specific Experiment Contract.
---

# Karpathy Autoresearch Adapter

## Core contract

Map the supplied repository, constraints, known evaluator command (if any), and
frozen `research-brief.md` into the repository-specific execution boundary. The
Research Brief is research truth: reference it; never copy or redefine the gap,
contribution, or hypothesis. This stage owns implementation/run/measurement
design, not discovery or research claims.

The only ready-state lifecycle handoff is
`autoresearch/experiment-contract.md`. An `adaptation-plan.md` is an interim
preview, never a lifecycle handoff.

## Plan first

Default to read-only inspection. Scan repository evidence: documentation,
manifests, CI, entry points, tests, benchmarks, data/fixtures, evaluator
commands, and existing artifacts. State the repository path and cite the frozen
Research Brief without researching or reframing it.

Return this plan in chat and stop unless the user provides **explicit apply
authorization**. The plan must name the future Experiment Contract and include:

- Research Brief reference, repository objective, constraints, and evidence;
- evaluator status and deterministic-command evidence;
- immutable judge, baseline, mutable surface, allowed/forbidden files;
- invocation, score and KEEP/DISCARD rules, runtime artifact and Git discipline;
- planned output paths and a fresh-agent continuation check.

## Evaluator classification

Classify from repository evidence using exactly one status:

- `ready`: a deterministic command/test/benchmark compares baseline and
  candidate outputs with a score or keep/discard result.
- `partial`: useful checks or metrics exist, but a baseline, data split, score,
  or acceptance gate is incomplete.
- `missing`: no credible evaluator exists.

Do not fabricate a judge or claim evaluator readiness from README promises.

## Apply only after authorization

With explicit apply authorization, persist the approved plan as
`autoresearch/adaptation-plan.md`.

For `ready`, then create exactly one lifecycle handoff:
`autoresearch/experiment-contract.md`. It must tell a fresh-agent which files
to read, how to run the immutable baseline and evaluator, how to propose one
candidate within the mutable surface, the fixed KEEP/DISCARD rule, how to
restore discards, stop conditions, and runtime outputs that must stay ignored.
Freeze the Research Brief reference, evaluator command/data/split/scoring/gates,
and forbidden files; do not create a generic program or runtime implementation.

For `partial` or `missing`, after authorization create at most
`autoresearch/evaluator_plan.md` (as well as the approved adaptation plan), then
stop. Do not create an Experiment Contract. Route to Evaluator Engineering;
after it succeeds, **return to Adapter** to reclassify evaluator readiness and
freeze the final contract.

## Stop and boundaries

Never redefine the gap, conduct discovery, implement an evaluator, run the research loop,
run an experiment, validate final claims, gather evidence, or write the paper. Do not mutate
files in plan-only mode. Do not advance to
Experiment until a `ready` contract exists and the router hands it off.

Summarize evaluator status, evidence, plan/apply status, files created, and the
single next owner; then stop.
