# Artifact handoffs

## Primary products

The six stage products are:

1. Research Brief — `research-brief.md`
2. Experiment Contract — `experiment-contract.md`
3. Evaluator Package — `evaluator-package/`
4. Candidate Package — `candidate-package/`
5. Validated Research Package — `validated-research-package/`
6. Manuscript Package — `manuscript-package/`

## Compact handoff

A compact handoff contains exactly `next_skill`, `reason`, `input_artifact`, and `resume_artifact`. Encode the observable status as the machine-readable prefix of `reason`; never add a fifth `status` field:

```yaml
reason: status=<canonical-token>; <brief human-readable rationale>
```

Use one canonical lowercase kebab-case token: `no-research-brief`, `research-brief-no-experiment-contract`, `evaluator-partial`, `evaluator-missing`, `experiment-contract-frozen`, `candidate-package-ready`, `validated-research-package-claim-bounded`, `insufficient-evidence`, or `research-frame-invalid`. The two artifact fields reference the available input product and the expected resume product.

## Direct entry

For an explicit entry request, route from only the stated status and artifact references. Do not inspect a repository or create, validate, or infer domain artifacts.

## Conditional capability detour

Evaluator `partial` or `missing` routes to `autoresearch-evaluator-engineering`, then Adapter reclassification. This is a conditional capability detour, not a scientific return loop.

## Scientific return loops

There are two scientific return loops:

- Evidence `insufficient-evidence` routes to `autoresearch-experiment`.
- Paper `research-frame-invalid` waits for human confirmation, then routes to Evidence or Experiment.
