---
name: karpathy-autoresearch-adapter
description: Use when mapping a repository and frozen Research Brief into a plan-first, repository-specific Experiment Contract or evaluator plan.
---

# Karpathy Autoresearch Adapter

## Sole handoff modes

Accept exactly one compact input per invocation:

| Mode | Sole input artifact |
| --- | --- |
| Research brief | `research-brief.md` |
| Evaluator package return | `autoresearch/evaluator-package/manifest.json` |
| Evaluator-invalid return | `autoresearch/evaluator-invalid-return.md` |

## Core contract

Act as the sole evaluator-readiness classifier. Map the repository, constraints,
and frozen `research-brief.md` into execution design without redefining the gap,
contribution, hypothesis, or claims. This stage owns implementation/run/
measurement design, not evaluator construction, experiments, or science claims.

The only ready-state lifecycle product is
`autoresearch/experiment-contract.md`. `autoresearch/adaptation-plan.md` is an
approved design record; `autoresearch/evaluator_plan.md` is the compact handoff
for an evaluator detour. Adapter never emits a partial Experiment Contract.

## Plan first

Default to read-only repository inspection. Examine documentation, manifests,
CI, entry points, tests, benchmarks, data/fixtures, evaluator commands, and
existing artifacts. Cite the frozen Research Brief and repository evidence.
If `autoresearch/evaluator-package/manifest.json` returns from Evaluator
Engineering, read that manifest first and open only linked evidence needed for
reclassification. It must bind the originating evaluator plan and the frozen
Research Brief requirements carried by that plan.

Return a plan in chat and stop unless the user gives **explicit apply
authorization**. The plan names the future product, mutable/forbidden surfaces,
baseline, candidate isolation, invocation, scoring and KEEP/DISCARD rule,
resource bounds, output paths, Git discipline, and a fresh-agent check.

## Evaluator classification

Classify repository evidence using exactly one status:

- `ready`: evidence establishes a runnable deterministic comparison and score or
  gate, fixed inputs and splits, candidate-edit isolation, discrimination and
  known-outcome checks, and repeatability adequate for the declared budget.
- `partial`: some credible measurement exists, but any required ready evidence
  is absent, weak, unstable, or not yet bound.
- `missing`: no credible evaluator exists.

A deterministic command alone is insufficient. Missing readiness evidence means
`partial`, not `ready`. Readiness authorizes bounded development measurement; it
is not external scientific validity. Do not fabricate a judge or infer readiness
from documentation promises.

## Evaluator-invalid operational return

For `autoresearch/evaluator-invalid-return.md`, verify the bound Experiment
Contract identity/hash, evaluator identity and failure evidence, candidate and
ledger state, and provenance. First mark the bound contract ineligible for reuse;
never resume from it or edit it in place. Then reclassify readiness from the
return evidence and linked files, return the replacement plan in chat, and stop.
Require **explicit apply authorization** before persisting a replacement
Experiment Contract or evaluator plan.

After authorization, persist a replacement contract only if `ready`. If
`partial` or `missing`, persist `autoresearch/evaluator_plan.md` and follow the
normal `autoresearch-evaluator-engineering` detour. Preserve candidate/ledger
state and state whether a future replacement contract may resume it.

## Apply only after authorization

After explicit apply authorization, persist the approved design as
`autoresearch/adaptation-plan.md`.

For `ready`, create `autoresearch/experiment-contract.md` as the sole compact
prior-stage handoff to Experiment (`autoresearch-experiment`). It must link the
frozen `research-brief.md` and frozen evaluator evidence, bind the evaluator
identity, command, inputs/splits/seeds, scoring, gates and readiness evidence,
and define target, baseline, mutable/forbidden files, candidate isolation,
KEEP/DISCARD rule, budget, rollback, stop/reauthorization conditions, and
runtime outputs. A fresh agent must be able to execute it without loading the
Adapter conversation or another prior package.

For `partial` or `missing`, create at most
`autoresearch/evaluator_plan.md` plus the approved adaptation plan, then stop.
The evaluator plan is the sole compact prior-stage handoff to
`autoresearch-evaluator-engineering`. It carries the frozen Research Brief
identity/hash/reference, its frozen evaluation requirements, permitted design
latitude that cannot redefine them, necessary project files, risks, and missing
readiness evidence. Do not create an Experiment Contract. After an Evaluator
Package returns, reclassify it here and create a final contract only if all
`ready` evidence exists.

## Stop and boundaries

Emit terminal `repository-not-runnable` when repository setup or required
invocation cannot run under the stated constraints. Emit terminal
`baseline-failed` when the declared baseline cannot be reproduced reliably
enough to freeze. Use `research-brief.md` as the compact terminal input for both
and route nowhere. Report operational evidence; do not redefine the research
question, evaluation requirement, or scientific claim to escape either outcome.
Preserve an already-authorized `autoresearch/adaptation-plan.md` and its failure
evidence as internal records when they exist, but never advertise an automatic
resume artifact.

Never redefine the gap, conduct discovery, implement an evaluator, run the
research loop or an experiment, validate final claims, gather evidence, or write
the paper. Do not mutate in plan-only mode. Do not route to
`autoresearch-experiment` until an Adapter-issued `ready` contract is frozen;
otherwise the single next owner is `autoresearch-evaluator-engineering` or none.
