# Review and packaging

Treat Peer Review as an executable release gate, not a request for general
approval. Record each finding, severity, evidence, owner stage, resolution, and
verification result.

## Review dimensions

- **Scientific consistency:** method, setup, evaluator, metrics, baselines, and
  conclusions agree across abstract, body, displays, supplement, and metadata.
- **Claim boundary:** every claim stays within its frozen status, scope,
  uncertainty, and limitation; unsupported implications are removed.
- **Citation:** cited sources exist, metadata and attribution are correct, and
  each citation supports the sentence where it appears.
- **Numerical:** manuscript values match traceable frozen results or disclosed
  computations over existing data; rounding, aggregates, intervals, labels,
  and units are consistent.
- **Format:** the package follows venue structure, anonymity, length, file,
  bibliography, ethics, disclosure, and supplemental requirements.
- **Visual:** figures and tables are legible, accurate, consistently styled,
  captioned, accessible, and faithful to their source values.

Route every failed check to Literature, Structure, grounded Writing,
Figures/Tables, or Compilation. Re-run the changed check and all dependent
checks. Release only when no blocking or material finding remains. A disclosed
limitation already frozen in the valid Claim Boundary is not blocking when all
of its referenced evidence is present.

If review finds a required manifest-linked artifact absent or invalid, first
attempt only its linked already-frozen deterministic recovery task exactly as
recorded, when one exists. Verify the restored artifact against the frozen
identity/hash and rerun dependent checks. Recovery cannot introduce a new seed,
ablation, experiment, analysis, or Claim Boundary change.

## Package inventory

Create exactly one `manuscript-package/` with:

- editable source and the compiled submission artifact;
- bibliography and verified citation record;
- final figures, tables, captions, and source/transformation records;
- supplements and venue-required declarations or checklists;
- claim-to-evidence traceability ledger and review log; and
- a manifest listing every file, provenance, build command, and disclosed
  limitations already frozen in the valid Claim Boundary.

Do not copy unnecessary private artifacts into the submission package. Verify
that the packaged source builds from its recorded command and that the compiled
artifact matches the reviewed output.

If no authorized recovery exists, recovery fails, or an asset required for an
included claim or required venue deliverable remains absent/invalid, emit
`missing-frozen-evidence`, create no Manuscript Package, and stop. That terminal
outcome and `manuscript-package-complete` never coexist.
Emit completion only after the complete package passes every release gate.
