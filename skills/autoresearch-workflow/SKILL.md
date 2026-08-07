---
name: autoresearch-workflow
description: Use when routing an Auto-Research project from an explicit entry request or compact artifact handoff to exactly one next modular skill, stage, resume point, or return loop without performing domain work.
---

# Core contract

Act only as a thin router. Select exactly one `next_skill` from the observable project state and emit the compact handoff. Accept at most one compact handoff. Do not inspect repository internals, load or execute the selected domain skill, create domain artifacts, or perform research work.

# Input

Accept either an explicit entry request or one compact handoff containing status and artifact references. For direct entry, infer state only from the artifacts and statuses stated in the request; treat unstated artifacts as unavailable. Read [artifact handoffs](references/artifact-handoffs.md) only to identify product names and handoff fields.

# Routing

Use the first applicable row.

| Observable state | Route |
| --- | --- |
| No Research Brief | `autoresearch-discovery` |
| Research Brief, no Experiment Contract | `karpathy-autoresearch-adapter` |
| Evaluator `partial` or `missing` | `autoresearch-evaluator-engineering`, then Adapter reclassification |
| Frozen Experiment Contract, no Candidate Package | `autoresearch-experiment` |
| Candidate Package, no Validated Research Package | `autoresearch-evidence` |
| Validated Research Package with Claim Boundary | `autoresearch-paper` |
| Evidence says `insufficient-evidence` | `autoresearch-experiment` |
| Paper says `research-frame-invalid` | wait for human confirmation, then Evidence or Experiment |

For the final row, do not emit a domain route until human confirmation identifies Evidence or Experiment.

# Handoff

Emit only this four-field YAML shape, replacing values with the selected route and relevant artifact references:

```yaml
next_skill: karpathy-autoresearch-adapter
reason: Research Brief exists and no Experiment Contract exists.
input_artifact: research-brief.md
resume_artifact: autoresearch/experiment-contract.md
```

# Stop

Always stop after routing. Return no explanation, plan, or execution output beyond the compact YAML handoff.

# Boundaries

Do not perform discovery, evaluator engineering, adaptation, experimentation, evidence review, or paper writing. The router selects and stops; the selected skill owns all domain procedure.
