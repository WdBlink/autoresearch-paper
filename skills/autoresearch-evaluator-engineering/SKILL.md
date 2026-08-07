---
name: autoresearch-evaluator-engineering
description: Use when the Adapter classified a repository evaluator as partial or missing and a reproducible evaluator must be built and validated before an Experiment Contract can exist.
---

# Auto-Research Evaluator Engineering

## Entry condition

Enter only after Adapter has classified the evaluator as `partial` or `missing`
and supplied its evaluator plan. Do not enter for `ready`. This capability builds
measurement only; a successful handoff must **return to Adapter** for readiness
reclassification and final Experiment Contract creation.

## Inputs

Read the frozen Research Brief, partial Experiment Contract if present, evaluator
plan, repository evidence, available fixtures/data, and known measurement risks.
Preserve the Research Brief's evaluation requirements; identify any absent ground
truth, baseline, data access, or decision rule instead of inventing them.

## Build and validate

Define and implement the smallest credible evaluator without changing a candidate:

1. Specify metric semantics, direction, aggregation, comparison baseline, and
   pass/fail or KEEP/DISCARD interpretation.
2. Fix versioned data, splits, seeds, environment, and evaluator command so runs
   are repeatable. Record all inputs and runtime dependencies.
3. Add fixtures with known outcomes and check the evaluator produces those
   outcomes. Test that meaningful better/worse or valid/invalid cases are
   discriminative rather than merely executable.
4. Run repeatability checks and characterize cost and runtime. Investigate unstable
   output, leakage, missing provenance, or unbounded cost before proceeding.
5. Keep validation isolated from candidate edits: evaluator assets and validation
   may change, but the candidate, its parameters, and its implementation must not.
   Never optimize the candidate or launch an Experiment.

## Evaluator Package

On validation, produce one `autoresearch/evaluator-package/` containing the
evaluator command, metric contract, fixed data/split and environment record,
fixtures and known outcomes, discrimination and repeatability results, cost/runtime
characterization, a validation report, and known limitations. State exactly what
the evaluator can and cannot conclude. Return to Adapter with the package path and
evidence needed to reclassify the evaluator; do not create or execute an Experiment
Contract here.

## Stop

Emit `evaluator-not-validatable` and stop if credible metric semantics, fixed data
or splits, a runnable evaluator command, known-outcome fixtures, discriminative
behavior, repeatable results, isolated candidate edits, or meaningful limitations
cannot be established. Explain the evidence gap and preserve partial work without
claiming readiness.

## Boundaries

Do not perform discovery, alter the Research Brief, set stage-wide human policy,
adapt the repository beyond evaluator assets, optimize or edit a candidate, launch
an Experiment, or validate research claims. This capability only constructs and
validates evaluator engineering evidence, then returns control to Adapter.
