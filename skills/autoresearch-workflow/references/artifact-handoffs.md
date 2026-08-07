# Artifact handoffs

## Primary products

The seven primary products are:

1. Research Brief — `research-brief.md`
2. Experiment Contract — `autoresearch/experiment-contract.md`
3. Evaluator Report — `autoresearch/evaluator-report.md`
4. Candidate Package — `autoresearch/candidate-package.md`
5. Validated Research Package — `autoresearch/validated-research-package.md`
6. Claim Boundary — `autoresearch/claim-boundary.md`
7. Paper — `autoresearch/paper.md`

## Compact handoff

A compact handoff contains one observable `status` and references to the available product artifacts. The router returns only `next_skill`, `reason`, `input_artifact`, and `resume_artifact`.

## Direct entry

For an explicit entry request, route from only the stated status and artifact references. Do not inspect a repository or create, validate, or infer domain artifacts.

## Scientific return loops

There are two scientific return loops:

- Evaluator `partial` or `missing` routes to `autoresearch-evaluator-engineering`, then Adapter reclassification.
- Evidence `insufficient-evidence` routes to `autoresearch-experiment`.

`research-frame-invalid` waits for human confirmation before selecting Evidence or Experiment.
