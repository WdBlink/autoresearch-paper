---
name: autoresearch-evaluator-engineering
description: Use when Adapter supplied a compact evaluator plan for a partial or missing evaluator that must be built and validated before Adapter can reconsider readiness.
---

# Auto-Research Evaluator Engineering

## Entry condition

Enter only after Adapter classified the evaluator `partial` or `missing` and
issued its evaluator plan. This capability builds measurement only. Success must
return to Adapter (`karpathy-autoresearch-adapter`) for reclassification and a
possible final Experiment Contract.

## Inputs

Use `autoresearch/evaluator_plan.md` as the sole prior-stage handoff. Read only
that compact plan and the necessary project files it links: evaluator assets,
fixtures/data, runtime dependencies, repository constraints, and measurement
risks. Do not request or load a Research Brief or any Experiment Contract, and
do not load the Adapter conversation.

## Build and validate

Define and implement the smallest credible evaluator without changing a
candidate:

1. Specify metric semantics, direction, aggregation, comparison baseline, and
   pass/fail or KEEP/DISCARD interpretation.
2. Fix versioned data, splits, seeds, environment, and the evaluator command.
3. Add fixtures with known outcomes; check meaningful better/worse or
   valid/invalid cases for discrimination, not mere executability.
4. Run enough repeatability trials for the planned budget and characterize cost,
   runtime, variance, leakage, and limitations.
5. Demonstrate candidate-edit isolation: evaluator assets may change here, but
   candidate edits cannot alter evaluation behavior.

Never optimize the candidate or launch an Experiment.

## Evaluator Package

On validation, produce `autoresearch/evaluator-package/` with the compact
`autoresearch/evaluator-package/manifest.json`. The manifest links the evaluator
command/version, metric contract, fixed data/split and environment, known-outcome
fixtures, discrimination evidence, repeatability evidence, candidate-edit
isolation evidence, cost/runtime report, validation summary, and known
limitations. It states what the evaluator can and cannot conclude.

Then return to Adapter with only that compact manifest as the prior-stage handoff;
Adapter opens linked evidence as needed and owns readiness reclassification.
Never create or execute an Experiment Contract here.

## Stop

Emit `evaluator-not-validatable` and stop with no route if credible semantics,
fixed inputs/splits, a runnable command, known-outcome and discrimination checks,
adequate repeatability, candidate-edit isolation, or meaningful limitations
cannot be established. Preserve partial work without claiming readiness.

## Boundaries

Do not perform discovery, alter research framing, set stage-wide human policy,
adapt beyond evaluator assets, optimize a candidate, launch an Experiment, or
validate research claims. Construct evaluator evidence, return control to
Adapter, and stop.
