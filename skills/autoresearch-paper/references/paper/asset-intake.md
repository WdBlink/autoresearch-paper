# Paper asset intake

Use this gate once at entry and again whenever a referenced asset fails to
resolve. Do not begin manuscript production from assumptions.

## Verify the frozen package

1. Locate `manifest.json` and the Claim Boundary inside the
   `validated-research-package/`.
2. Verify the manifest's hashes or immutable references for code, configuration,
   evaluator identity, data/split, results, logs, statistics, and prior figures
   or tables. Record both present and absent assets.
3. Confirm that every Claim Boundary row identifies supporting evidence,
   applicable scope, uncertainty or limitation, and status.
4. Resolve project assets: terminology, method descriptions, result files,
   reproduction commands, author-supplied diagrams, and supplemental material.
5. Resolve venue assets: template, style/bibliography files, anonymity rules,
   length limits, section requirements, and submission checklist.
6. Resolve citation sources to stable primary records where possible. Record
   enough metadata to verify author, title, venue, year, and identifier.

Create an intake record mapping each source asset to its immutable reference,
intended manuscript use, and verification result. Never overwrite the frozen
package.

## Typed outcomes

Use `missing-frozen-evidence` when the research frame and Claim Boundary remain
coherent but a manifest-listed artifact is absent, unreadable, hash-mismatched,
or insufficient to render a particular statement or display. Identify the exact
reference, affected claim or artifact, and safe action: omit, narrow, mark as a
limitation, or leave the deliverable incomplete. Do not regenerate it through a
new seed, ablation, experiment, or changed analysis.

Use `research-frame-invalid` only when the package cannot support an honest
paper at all without changing the research frame—for example, the Claim
Boundary contradicts the manifest, results bind to a different method or
evaluator, or the claimed comparison cannot be mapped to its evidence. Preserve
the conflict record and pause for human confirmation before any upstream route
to Evidence or Experiment.

Do not treat a missing template, bibliography style, citation PDF, or other
publication asset as a research-frame failure. Acquire or reconstruct ordinary
publication assets when doing so does not invent scientific evidence.
