---
name: autoresearch-paper
description: Use when a frozen Validated Research Package and Claim Boundary must become a submission-ready scientific manuscript without reopening research.
---

# Auto-Research Paper

## Core contract

Turn one frozen `validated-research-package/` into exactly one
`manuscript-package/`. Work fully autonomous inside the package's Claim
Boundary. Treat its methods, evaluator, evidence, and claim statuses as fixed;
paper production may explain and present them but cannot create new research.

Use only these delivery mechanisms: Literature, Structure, grounded Writing,
Figures/Tables, Compilation, and Peer Review. Do not import a legacy
supervisory runtime or compatibility workflow.

## Inputs

Require:

- the complete `validated-research-package/`, including its manifest, Claim
  Boundary, frozen code/config/result references, and provenance;
- project assets and citation sources referenced by that package; and
- the target venue, format, length, anonymity, and submission constraints.

Read [asset intake](references/paper/asset-intake.md) at entry. Validate the
manifest and classify an unusable input as either `missing-frozen-evidence` or
`research-frame-invalid`; never silently fill a research gap.

## Asset gate

Build a traceability map from every manuscript claim, number, figure, table,
and citation to the frozen package or a verified literature source. Preserve
the Claim Boundary's supported, qualified, unsupported, and
insufficient-evidence distinctions. Narrow or omit unsupported prose; do not
promote it through rhetoric.

Proceed without routine outline, draft, figure, or format approval when the
research frame remains valid. Missing frozen artifacts do not authorize new
research: record `missing-frozen-evidence`, state the affected deliverable,
and continue only with claims and artifacts the frozen package supports.

## Autonomous production loop

Read [the production loop](references/paper/production-loop.md) before drafting.
Iterate autonomously through:

1. **Literature** — verify citations and position the frozen contribution
   without reopening an open-ended novelty hunt.
2. **Structure** — map the Claim Boundary and venue requirements into a complete
   outline and evidence-backed argument.
3. **Grounded Writing** — draft each claim, limitation, method statement, and
   result from the traceability map.
4. **Figures/Tables** — derive presentation artifacts only from frozen
   deterministic tasks or existing data.
5. **Compilation** — build the target format, resolve references, and inspect
   the rendered manuscript.
6. **Peer Review** — audit scientific and submission quality, then route every
   finding back to the responsible internal step until clean.

Keep working through this loop without asking for routine approval.

## Allowed completion work

Rerun frozen deterministic tasks exactly as recorded to recover or verify an
artifact. Compute statistics, plots, or tables from existing data when the
transformation is reproducible, disclosed, and cannot change the research
decision or Claim Boundary. Verify citation metadata and add literature needed
to explain or position already-frozen claims.

Refuse a new seed, new ablation, or new experiment whose result could change a
claim. Do not change the method, evaluator, metric, data/split, comparison set,
or acceptance decision. Do not satisfy survey quotas or expand an unresolved
literature search. Do not hide new research inside writing, analysis, figure
polish, or reviewer response.

## Release gate

Read [review and packaging](references/paper/review-and-packaging.md) before
release. Require clean scientific-consistency, claim-boundary, citation,
numerical, format, and visual reviews. Route a failed check back to Literature,
Structure, grounded Writing, Figures/Tables, or Compilation and repeat review.

Release one `manuscript-package/` containing the editable manuscript source,
compiled submission artifact, bibliography, figures/tables, traceability and
review records, venue-required supporting files, and a package manifest. Mark
any unresolved frozen-evidence limitation explicitly; never disguise it as a
completed result.

## Stop

Use `research-frame-invalid` only when the supplied Claim Boundary, method,
evaluator, or evidence relationships are internally incompatible such that
honest manuscript production would require reframing the research. Pause only
for this outcome and obtain human confirmation before routing upstream to
Evidence or Experiment. Do not start that upstream work from this skill.

For `missing-frozen-evidence`, report the exact absent or invalid reference and
its manuscript impact. Do not request routine approval and do not manufacture,
rerun, or broaden research to repair it.

## Boundaries

Own paper production only. Do not discover or optimize a method, alter an
evaluator, run claim-changing research, revalidate scientific claims, or widen
the Claim Boundary. The frozen package is the scientific authority; the
manuscript-package is this skill's sole product.
