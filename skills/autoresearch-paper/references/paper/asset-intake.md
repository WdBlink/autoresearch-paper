# Paper asset intake

Use this gate once at entry and again whenever a referenced asset fails to
resolve. Do not begin manuscript production from assumptions.

## Verify the frozen package

1. Start from the sole prior-stage handoff,
   `validated-research-package/manifest.json`; do not preload the package.
   Verify that it links `claim-boundary.md` and the needed frozen assets.
2. Verify the manifest's hashes or immutable references for code, configuration,
   evaluator identity, data/split, results, logs, statistics, and prior figures
   or tables. Record both present and absent assets.
3. Confirm that every Claim Boundary row identifies supporting evidence,
   applicable scope, uncertainty or limitation, and exactly one of
   `supported|qualified|unsupported`. If the manifest or a row contains
   `insufficient-evidence`, emit `invalid-validated-package` and refuse Paper.
4. Resolve project assets: terminology, method descriptions, result files,
   reproduction commands, author-supplied diagrams, and supplemental material.
5. Resolve venue assets: template, style/bibliography files, anonymity rules,
   length limits, section requirements, and submission checklist.
6. Resolve citation sources to stable primary records where possible. Record
   enough metadata to verify author, title, venue, year, and identifier.

Create an intake record mapping each source asset to its immutable reference,
intended manuscript use, and verification result. Never overwrite the frozen
package. Open only manifest-linked assets needed for the current manuscript task.

## Required-asset recovery

When a required manifest-linked artifact is absent or invalid, first look for an
already-frozen deterministic recovery task linked by the valid package. If it
exists, run only that task exactly as recorded with its frozen command, inputs,
configuration, environment, and expected identity/hash. If recovery succeeds,
verify the restored artifact and continue intake.

This recovery cannot add a new seed, ablation, experiment, analysis, or Claim
Boundary change. If no authorized recovery exists, recovery fails, or the asset
remains absent or invalid, emit `missing-frozen-evidence`, create no Manuscript
Package, and stop.

## Typed outcomes

Use `missing-frozen-evidence` only after the recovery gate above, when an asset
required for an included claim or required venue deliverable remains absent,
unreadable, hash-mismatched, or invalid.
Identify the exact reference and affected claim or deliverable, create no
Manuscript Package, emit the terminal status, and stop. Do not regenerate the
asset through a new seed, ablation, experiment, or changed analysis.

A limitation already disclosed in the frozen Claim Boundary is not missing
evidence when all assets required to state that qualified or unsupported result
honestly are present. Likewise, an absent optional asset that is not used by an
included claim or required deliverable does not trigger
`missing-frozen-evidence`.

Use `research-frame-invalid-confirmation-pending` only when the package cannot
support an honest paper at all without changing the research frame—for example, the Claim
Boundary contradicts the manifest, results bind to a different method or
evaluator, or the claimed comparison cannot be mapped to its evidence. Preserve
the conflict record and pause for human confirmation before any upstream route
to Evidence or Experiment. After confirmation, emit the target-specific
`research-frame-invalid-confirmed-evidence` or
`research-frame-invalid-confirmed-experiment` status.

Do not treat a missing template, bibliography style, citation PDF, or other
publication asset as a research-frame failure. Acquire or reconstruct ordinary
publication assets when doing so does not invent scientific evidence.
