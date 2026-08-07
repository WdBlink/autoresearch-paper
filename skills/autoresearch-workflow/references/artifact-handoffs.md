# Artifact handoffs

## Primary products

The six stage products are:

1. Research Brief — `research-brief.md`
2. Experiment Contract — `autoresearch/experiment-contract.md`
3. Evaluator Package — `autoresearch/evaluator-package/`
4. Candidate Package — `autoresearch/candidate-package/`
5. Validated Research Package — `validated-research-package/`
6. Manuscript Package — `manuscript-package/`

## Compact handoff

A compact handoff contains exactly `next_skill`, `reason`, `input_artifact`, and
`resume_artifact`. Encode status at the start of `reason` as
`status=<canonical-token>;`; never add a fifth status field. Use literal `none`
when there is no route or artifact. The artifact fields point to compact
manifests or products, not entire loaded packages.

## Route matrix

Evaluate top to bottom and select the first matching row. This ordering prevents
a negative outcome from falling through merely because an artifact directory
exists.

| Status token | Observable state | next_skill | input_artifact | resume_artifact |
| --- | --- | --- | --- | --- |
| `required-input-missing` | `Referenced required input is absent` | `none` | `none` | `none` |
| `no-testable-opportunity` | `Discovery found no testable opportunity` | `none` | `research-brief.md` | `none` |
| `repository-not-runnable` | `Repository setup or required invocation cannot run within constraints` | `none` | `research-brief.md` | `none` |
| `baseline-failed` | `Declared baseline cannot be reproduced reliably enough to freeze` | `none` | `research-brief.md` | `none` |
| `evaluator-not-validatable` | `Evaluator cannot be validated from the Adapter plan` | `none` | `autoresearch/evaluator_plan.md` | `none` |
| `no-improvement` | `Experiment ended without an accepted candidate` | `none` | `autoresearch/candidate-package/manifest.json` | `none` |
| `budget-exhausted` | `Experiment exhausted its budget without an accepted candidate` | `none` | `autoresearch/candidate-package/manifest.json` | `none` |
| `contract-reauthorization-needed` | `Frozen contract requires changed authority` | `none` | `autoresearch/experiment-contract.md` | `none` |
| `no-accepted-candidate` | `Candidate Package contains no accepted candidate` | `none` | `autoresearch/candidate-package/manifest.json` | `none` |
| `missing-frozen-evidence` | `Paper cannot resolve a manifest-linked frozen asset` | `none` | `validated-research-package/manifest.json` | `none` |
| `invalid-validated-package` | `Validated package contains insufficient-evidence` | `none` | `validated-research-package/manifest.json` | `none` |
| `research-frame-invalid-confirmation-pending` | `Paper frame invalid and confirmation absent` | `none` | `validated-research-package/manifest.json` | `none` |
| `research-frame-invalid-confirmed-evidence` | `Human confirmed Evidence as correction target` | `autoresearch-evidence` | `autoresearch/candidate-package/manifest.json` | `validated-research-package/manifest.json` |
| `research-frame-invalid-confirmed-experiment` | `Human confirmed Experiment as correction target` | `autoresearch-experiment` | `autoresearch/experiment-contract.md` | `autoresearch/candidate-package/manifest.json` |
| `insufficient-evidence` | `Evidence issued a claim-blocking request` | `autoresearch-experiment` | `autoresearch/evidence-request.md` | `autoresearch/candidate-package/manifest.json` |
| `experiment-evaluator-invalid` | `Experiment emitted a bound evaluator-invalid return` | `karpathy-autoresearch-adapter` | `autoresearch/evaluator-invalid-return.md` | `autoresearch/experiment-contract.md` |
| `evaluator-package-ready-for-adapter` | `Evaluator Engineering produced a package` | `karpathy-autoresearch-adapter` | `autoresearch/evaluator-package/manifest.json` | `autoresearch/experiment-contract.md` |
| `evaluator-partial` | `Adapter classified evaluator partial` | `autoresearch-evaluator-engineering` | `autoresearch/evaluator_plan.md` | `autoresearch/evaluator-package/manifest.json` |
| `evaluator-missing` | `Adapter classified evaluator missing` | `autoresearch-evaluator-engineering` | `autoresearch/evaluator_plan.md` | `autoresearch/evaluator-package/manifest.json` |
| `manuscript-package-complete` | `Paper completed the manuscript package` | `none` | `manuscript-package/` | `none` |
| `no-research-brief` | `Project has no Research Brief` | `autoresearch-discovery` | `none` | `research-brief.md` |
| `research-brief-no-experiment-contract` | `Research Brief exists and no Experiment Contract exists` | `karpathy-autoresearch-adapter` | `research-brief.md` | `autoresearch/experiment-contract.md` |
| `experiment-contract-frozen` | `Adapter-issued frozen ready contract exists and no Candidate Package exists` | `autoresearch-experiment` | `autoresearch/experiment-contract.md` | `autoresearch/candidate-package/manifest.json` |
| `accepted-candidate-package` | `Candidate Package has an accepted candidate and no Validated Research Package exists` | `autoresearch-evidence` | `autoresearch/candidate-package/manifest.json` | `validated-research-package/manifest.json` |
| `validated-research-package-claim-bounded` | `Valid frozen package has an exact three-status Claim Boundary` | `autoresearch-paper` | `validated-research-package/manifest.json` | `manuscript-package/` |

## Direct entry

Route from only the stated status and artifact references. Do not inspect a
repository, infer an unstated accepted candidate, or create/validate an artifact.
Direct Paper entry refuses a package whose manifest or Claim Boundary contains
`insufficient-evidence` by selecting `invalid-validated-package` and no route.
When Paper requests confirmation, its handoff must carry the candidate manifest
and Experiment Contract references from the validated manifest. After a human
selects a target, use only the receiving skill's compact entry artifact shown in
the matrix.

## Conditional operational detour

Adapter `partial|missing` routes to Evaluator Engineering. Its compact Evaluator
Package manifest returns to Adapter for the sole readiness reclassification.
Experiment-discovered evaluator integrity/readiness failures also return to
Adapter through `autoresearch/evaluator-invalid-return.md`, which binds the stale
contract, evaluator identity and failure evidence, candidate/ledger, and
provenance. Adapter invalidates that contract before reclassification and
requires explicit apply authorization before persisting a replacement. This
detour is operational and is not a scientific return loop.

The terminal Adapter outcomes `repository-not-runnable` and `baseline-failed`
are evaluated before artifact-presence fallthrough. Both retain
`research-brief.md`, use literal `next_skill: none`, and grant no new authority.

## Scientific return loops

- Evidence `insufficient-evidence` routes to `autoresearch-experiment`.
  It uses `autoresearch/evidence-request.md`. That compact resume manifest binds
  the exact Adapter-issued contract identity/hash, candidate manifest and
  evaluator, missing evidence, permitted scope, and provenance. It never
  enlarges the linked contract.
- Human-confirmed Paper `research-frame-invalid` routes to `autoresearch-evidence` or `autoresearch-experiment`.
