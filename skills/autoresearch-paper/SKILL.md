---
name: autoresearch-paper
description: Use when a valid frozen Validated Research Package manifest and venue constraints must become a submission-ready scientific manuscript without reopening research.
---

# Auto-Research Paper

## Core contract

Turn one valid frozen `validated-research-package/` into exactly one
`manuscript-package/`. Work fully autonomous inside its exact Claim Boundary.
Methods, evaluator, evidence, and claim statuses are fixed; paper production may
explain and present them but cannot create research.

Use only Literature, Structure, grounded Writing, Figures/Tables, Compilation,
and Peer Review. Do not import a supervisory or compatibility workflow.

## Sole handoff modes

| Mode | Sole input artifact |
| --- | --- |
| Validated package | `validated-research-package/manifest.json` |

## Inputs

Accept `validated-research-package/manifest.json` as the sole prior-stage
handoff, plus target venue, format, length, anonymity, and submission constraints.
Read the compact manifest first, then open only linked Claim Boundary, assets,
provenance, code/config/result references, and citation sources needed for the
current manuscript task. Do not load the entire prior package by default.

Read [asset intake](references/paper/asset-intake.md) at entry. Never silently
fill a research gap.

## Asset gate

Verify that the manifest and every Claim Boundary row use exactly
`supported|qualified|unsupported`. Refuse any package whose manifest or Claim
Boundary contains `insufficient-evidence`: emit `invalid-validated-package`, do
not begin manuscript production, do not create `manuscript-package/`, and do not
consume the invalid package as research authority.

For a valid package, build traceability from every manuscript claim, number,
figure, table, and citation to a manifest-linked frozen artifact or verified
literature source. Preserve status, scope, and uncertainty. Narrow or omit
unsupported prose; never promote it rhetorically.

Proceed without routine outline, draft, figure, or format approval while the
research frame remains valid. A limitation already frozen in a valid Claim
Boundary is a disclosed limitation and does not emit `missing-frozen-evidence`
when all referenced assets are present.

Emit terminal `missing-frozen-evidence` only when a manifest-linked asset needed
to substantiate an included claim or complete a required venue deliverable is
absent or invalid. Stop, create no Manuscript Package, and never run research to
repair it. An optional unused asset does not trigger this outcome.

## Autonomous production loop

Read [the production loop](references/paper/production-loop.md) before drafting,
then iterate autonomously:

1. **Literature** — verify citations and position only frozen contributions.
2. **Structure** — map the Claim Boundary and venue rules into the argument.
3. **Grounded Writing** — trace every claim, limitation, method, and result.
4. **Figures/Tables** — derive presentation only from frozen deterministic tasks
   or existing data.
5. **Compilation** — build, resolve references, and inspect the rendered output.
6. **Peer Review** — route findings to the responsible internal step and repeat.

## Allowed completion work

Rerun a frozen deterministic task exactly as recorded to recover/verify an
artifact. Compute reproducible disclosed statistics, plots, or tables from
existing data only when they cannot change the research decision or Claim
Boundary. Verify citation metadata and add literature that explains frozen
claims.

Refuse a new seed, new ablation, or new experiment whose result could change a
claim. Do not change method, evaluator, metric, data/split, comparisons, or the
acceptance decision. Do not hide new research inside writing, analysis, figures,
or reviewer response.

## Release gate

Read [review and packaging](references/paper/review-and-packaging.md). Require
clean claim-boundary, scientific-consistency, citation, numerical, format, and
visual reviews. Route a failed check to an internal production step and repeat.

Only after every release gate is clean, release `manuscript-package/` with
editable source, compiled submission,
bibliography, figures/tables, traceability and review records, venue files, and
a compact manifest, then emit `manuscript-package-complete`. Never disguise a
frozen-evidence limitation.

## Stop

Emit `research-frame-invalid-confirmation-pending` only when valid-package
relationships are internally incompatible and honest production would require
reframing. Pause for human confirmation before routing upstream to
`autoresearch-evidence` or `autoresearch-experiment`; never start that work here.
Without confirmation, there is no route. After confirmation, emit the matching
`research-frame-invalid-confirmed-evidence` or
`research-frame-invalid-confirmed-experiment` status. This human-confirmed route
is one of the two scientific loops.
The confirmation request must preserve the candidate manifest and Experiment
Contract references already linked by the validated manifest so the confirmed
target receives its normal compact entry artifact.

For `missing-frozen-evidence` or `invalid-validated-package`, report the exact
failure and impact without manufacturing or broadening research.

## Outcome exclusivity

| Condition | Outcome | Manuscript Package |
| --- | --- | --- |
| Required frozen asset absent or invalid | `missing-frozen-evidence` | `forbidden` |
| Invalid validated package | `invalid-validated-package` | `forbidden` |
| Research frame invalid, confirmation pending | `research-frame-invalid-confirmation-pending` | `forbidden` |
| All release gates clean | `manuscript-package-complete` | `required` |

These outcomes are mutually exclusive. A blocking terminal outcome cannot
coexist with `manuscript-package-complete`.

## Boundaries

Own paper production only. Do not discover/optimize a method, alter an evaluator,
run claim-changing research, revalidate claims, or widen the Claim Boundary.
