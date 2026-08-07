---
name: autoresearch-evidence
description: Use when a frozen Candidate Package and Experiment Contract need independent validation evidence and a bounded final claim record.
---

# Auto-Research Evidence

## Core contract

Validate a frozen candidate without changing it, then produce exactly one
`validated-research-package/` containing `manifest.json` and
`claim-boundary.md`. This package records what the evidence supports, its
applicable scope, uncertainty, and claim status; it is not a paper or a new
candidate.

## Inputs

Require all of the following before evaluating claims:

- the frozen Candidate Package and its reproducible candidate, provenance,
  experiment ledger, and outcome;
- the frozen Experiment Contract, including evaluator, data/split, metrics,
  baseline, and KEEP/DISCARD rule;
- the evaluator and relevant baselines named by that contract; and
- the intended claim wording and scope.

If an input is missing, inconsistent, or cannot reproduce, do not fill the gap
with assumption. Record `insufficient-evidence` and return the work to
Experiment with the specific evidence needed.

## Freeze

Freeze the selected candidate method, its source/configuration, the Experiment
Contract, evaluator identity and version, data/split, metrics, baseline set,
and intended claim before validation. Preserve immutable references or hashes
in `manifest.json`.

Never change the candidate method, tune its parameters, select a replacement,
or make implementation changes in response to validation results. Never
silently redefine the evaluator, metrics, comparison population, baseline, or
claim wording/scope to produce a favorable result. A requested change requires
an explicit return to the appropriate earlier stage and a new frozen input.

## Validate

Run only claim-evaluating work against the frozen inputs. Repeated runs, new
validation seeds, predefined ablations, baseline comparisons, uncertainty
estimates, and error analysis are allowed when they test the stated claim.
Record commands, versions, seed assignments, raw outputs or stable references,
and deviations in the manifest so the result can be checked independently.

Compare each result with every relevant baseline in the stated scope. Distinguish
replicated effects from noise, failures, clear regressions that answer the claim,
missing coverage, and unresolved conflicts among required results. Do not use a
screening gain or one favorable dataset to support a broader claim than the
evaluated scope.

## Claim Boundary

Write `claim-boundary.md` with a semantic claim-boundary table. Include one row
per intended or evaluated claim, rather than a generic pass/fail conclusion:

| Claim | Supporting evidence | Applicable scope | Uncertainty / limitation | Status |
|---|---|---|---|---|
| Method A reduces median latency versus B0 | runs A-01 through A-05 and table 2 | dataset A on frozen evaluator v1 | 95% CI excludes zero; no evidence on dataset C | qualified |

Use only these statuses:

- `supported` — evidence directly supports the claim throughout its stated scope.
- `qualified` — evidence supports a narrower, explicitly stated scope or has a
  material limitation.
- `unsupported` — clear negative or regression evidence that answers the claim.
- `insufficient-evidence` — required evidence is absent, invalid, unreproducible,
  too incomplete, or internally inconsistent/contradictory and unresolved.

A resolved negative result is `unsupported`, even when it contradicts the
desired claim. A conflict among required evidence is `insufficient-evidence`
until further validation resolves it.

The table must state supporting evidence, applicable scope, and uncertainty for
every status, including negative results. Keep the original claim separate from
the narrower wording that the evidence can support; do not turn a universal
claim into a universal conclusion when results vary by dataset or baseline.

`manifest.json` must identify the frozen inputs, evidence inventory, validation
commands and environment, each claim status, package outcome, and the exact
next-stage routing decision.

## Stop

Stop after producing the validated-research-package and its complete evidence
record. For absent required evidence, or unresolved or internally
inconsistent/contradictory required evidence, use `insufficient-evidence`,
identify the gap or conflict, and return to Experiment. Do not automatically
route to Discovery and do not draft the manuscript.

## Boundaries

Evidence decides which claims the frozen evidence can carry. It may validate
with additional seeds, predefined ablations, comparisons, uncertainty analysis,
and error analysis, but it never tunes the method. Do not optimize candidates,
repair or redesign the evaluator, re-authorize the Experiment Contract, promote
claims beyond the Claim Boundary, or write a paper.
