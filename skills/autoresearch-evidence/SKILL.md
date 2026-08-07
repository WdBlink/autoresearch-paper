---
name: autoresearch-evidence
description: Use when an accepted frozen Candidate Package needs independent claim validation and a bounded Validated Research Package.
---

# Auto-Research Evidence

## Core contract

Validate an accepted frozen candidate without changing it. Produce exactly one
`validated-research-package/` only when every Claim Boundary row can use the
closed enum `supported|qualified|unsupported`. A claim-blocking gap produces an
`insufficient-evidence` upstream request instead of a validated package.

## Sole handoff modes

| Mode | Sole input artifact |
| --- | --- |
| Candidate package | `autoresearch/candidate-package/manifest.json` |

## Inputs

Use `autoresearch/candidate-package/manifest.json` as the sole prior-stage
handoff. Read that compact manifest first. It must link an accepted candidate,
the frozen Experiment Contract and evaluator, outcome summary, experiment
ledger, and evidence/log index. Open only linked files needed to evaluate the
intended claim wording and scope; do not load the entire Candidate Package or
prior-stage context by default.

If the manifest has no accepted candidate, is inconsistent, or cannot reproduce,
do not infer missing context or begin claim validation. Emit terminal
`no-accepted-candidate` for an explicit absence and do not create a Validated
Research Package. Treat inconsistency or failed reproduction as a claim-blocking
gap under the `insufficient-evidence` Stop rule below.

## Freeze

Freeze the selected candidate method, source/configuration, Experiment Contract,
evaluator identity/version, data/split, metrics, baseline set, and intended claim
before validation. Preserve immutable references or hashes.

Never change the candidate method, tune its parameters, select a replacement,
or make implementation changes in response to validation. Never silently
redefine the evaluator, metric, comparison population, baseline, or claim scope
to obtain a favorable result. Other reauthorization follows the frozen
contract's declared rule and stops; Evidence adds no direct scientific route.

## Validate

Run only claim-evaluating work against frozen inputs. Repeated runs, new
validation seeds, predefined ablations, baseline comparisons, uncertainty
estimates, and error analysis are allowed when they test the stated claim.
Record commands, versions, seed assignments, raw outputs or stable references,
and deviations.

Compare every relevant baseline in scope. Distinguish replicated effects from
noise, clear negative/regression results, missing coverage, and unresolved
conflicts. A screening gain or one favorable dataset cannot support a broader
claim than the evaluated scope.

## Claim Boundary

Write `validated-research-package/claim-boundary.md` with one row per intended
or evaluated claim:

| Claim | Supporting evidence | Applicable scope | Uncertainty / limitation | Status |
|---|---|---|---|---|
| Method A reduces median latency versus B0 | runs A-01 through A-05 and table 2 | dataset A on frozen evaluator v1 | 95% CI excludes zero; no evidence on dataset C | qualified |

Use exactly these Claim Boundary row statuses:

- `supported` — evidence directly supports the claim throughout its stated scope.
- `qualified` — evidence supports a narrower stated scope or has a material limitation.
- `unsupported` — clear negative or regression evidence answers the claim.

A resolved negative result is `unsupported`. Missing, invalid, unreproducible,
incomplete, or internally inconsistent/contradictory required evidence blocks
the package; it is never a fourth Claim Boundary status. Every valid row states
supporting evidence, applicable scope, and uncertainty/limitations.

## Validated Research Package

For a complete three-status boundary, create
`validated-research-package/manifest.json` as Paper's sole compact prior-stage
handoff. It links `claim-boundary.md`, the frozen candidate, Experiment Contract,
evaluator, evidence index, validation summary, commands/environment, provenance,
and immutable identifiers. It records only the three valid claim statuses and is
the input for `autoresearch-paper`.

## Stop

For any claim-blocking validation gap, do not create or freeze
`validated-research-package/`. Emit the typed package-validation outcome
`insufficient-evidence` in `autoresearch/evidence-request.md`. This compact
resume manifest immutably binds the exact Adapter-issued frozen Experiment
Contract identity and hash, Candidate Package manifest, evaluator identity,
requested missing evidence, permitted scope, and provenance. Request the bound
work from only `autoresearch-experiment`. This outcome cannot appear in a Claim
Boundary or Validated Research Package manifest. Do not route to Discovery or
Paper.

After a valid package is frozen, hand off only its manifest and stop.

## Boundaries

Evidence decides which claims frozen evidence can carry and never tunes the
method. Do not optimize candidates, repair/redesign an evaluator, reauthorize an
Experiment Contract, promote claims beyond the Claim Boundary, or write a paper.
