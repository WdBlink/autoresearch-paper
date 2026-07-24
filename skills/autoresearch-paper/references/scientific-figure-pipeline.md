# Scientific figure pipeline

This pipeline is host neutral. Codex, Claude Code, or another host may invoke
the capabilities, but the repository manifest and validator are the acceptance
authority. A skill, renderer, image model, reviewer model, visual score, or
attractive output cannot promote a figure by itself.

## Focused capability policy

Use only the reviewed, pinned subset of
`K-Dense-AI/scientific-agent-skills` needed for the task:

- `scientific-visualization` is the preferred capability for deterministic
  result and statistical plots.
- `scientific-schematics` is optional for method-diagram proposals only.
- A missing AI capability or credential does not block deterministic plots.
- Do not install the full upstream collection for this pipeline. Record the
  selected skill's release or commit and review its `SKILL.md` before use.

Upstream skills supply rendering guidance; they do not own research decisions,
artifact promotion, filesystem boundaries, or the final figure gate.

## Authority and timing

Build result/statistical figures only after the candidate has a validated KEEP
receipt. An arxiv negative result may instead use its authenticated applied
waiver. A deterministic method diagram binds the frozen method specification.
Before execution, CP-01 must approve a controller-owned
`state/figure-requirements.json` containing the exact expected figure IDs.
The minimum set is 1 for arxiv, 4 for conference, and 6 for journal-q1.

Run T6.4 after that authority exists and before T7. T7 and T10 must rerun the
validator for every required manifest. T11 remains a semantic and visual
readiness review; it cannot repair a failed deterministic gate.

```text
validated KEEP / waiver / method spec
  -> source data + render source
  -> deterministic local render
  -> vector manuscript output + raster preview
  -> hash-bound manifest
  -> output-bound human review receipt
  -> repository inventory validator
  -> T7/T10 eligibility
```

## Plan-owned artifacts

Keep every referenced file beneath the same plan root. A typical package is:

```text
<plan-dir>/
  out/results-raw/scores.csv
  out/figures/render-primary.py
  out/figures/fig-primary.pdf
  out/figures/fig-primary.png
  out/figures/fig-primary.review.json
  out/figures/fig-primary.manifest.json
  out/figures/required-figures.json
  state/figure-requirements.json
  state/keep-receipt.json
```

Paths in the manifest are relative POSIX paths. Absolute paths, `..`, empty
segments, Windows paths, missing files, and symlinks resolving outside the plan
root fail closed. SHA-256 is computed from current bytes for every input,
output, authority receipt, and review receipt.

The manifest follows `figure-artifact.schema.json` and records:

- figure identity, kind, generation mode, and capability;
- source inputs and the exact render script or specification;
- an ordered transformation list (use `[]` when there are none);
- renderer identity, version, source revision, exact argv, and random seed;
- at least one manuscript PDF or SVG and one PNG or JPEG preview;
- plan, timestamp, claim identifiers, and research-authority provenance;
- an output-bound human review receipt, reviewer identity, independence, and
  decision.

For result/statistical figures, include at least one claim identifier and use a
KEEP or arxiv negative-result-waiver authority. `random_seed` is mandatory even
for a renderer with no stochastic behavior; use `0` and keep the implementation
free of uncontrolled randomness.

## AI schematic boundary

An output from `scientific-schematics` or another image model is a proposal.
Store it separately, mark `generation.mode` as `ai_schematic_proposal`, and do
not place it directly in the manuscript. An AI review score may be recorded,
but it has no acceptance authority.

To promote the idea, reconstruct it with a deterministic local renderer such
as TikZ or SVG, bind the proposal as an input if useful, and create a new
manifest whose generation mode is `deterministic`. A fresh human must review
the deterministic result. The renderer cannot review itself, and an AI agent
or model cannot provide the promotion receipt.

## Executable gate

Run from any host; the validator uses only the Python standard library and does
not execute the recorded render command or access the network:

```bash
python3 references/scripts/validate-figure-artifacts.py \
  --plan-dir <plan-dir> \
  --inventory <plan-dir>/out/figures/required-figures.json \
  --requirements <plan-dir>/state/figure-requirements.json
```

The inventory must exactly match the CP-01-approved expected figure ID set and
bind each manifest by SHA-256. Exit `0` returns a JSON `PASS` result with the
requirements, inventory, manifest, and verified artifact hashes. The
controller then stores an immutable figure-gate receipt bound to the CP-01
approval. Exit `2` returns a typed JSON failure on stderr. Any failure blocks
figure promotion and therefore T7/T10. Fix the source, rerender, update the
hashes from the new bytes, and obtain a fresh human review whose
`reviewed_outputs` exactly bind every current output; never weaken the
contract to make an output pass.

## Evidence boundary

A validator PASS proves contract structure, plan-root confinement, current
hashes, declared provenance, required formats, and the presence of a human,
independent, output-bound PASS record. It does not prove scientific truth, visual
clarity, accessibility, statistical correctness, or reviewer authenticity.
Those remain separate evaluator, independent-review, and readiness obligations.
