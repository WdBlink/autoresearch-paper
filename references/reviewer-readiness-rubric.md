# Reviewer Readiness Rubric

Six-dimension self-check used by T11-readiness. Each dimension scored
0–10, with explicit descriptors for 0/2/5/7/9/10. The skill uses the
per-dimension tier thresholds in the plan templates.

## How to use this rubric

The verifier agent (T11-readiness) reads the rubric, then walks through
each dimension of the paper. For each dimension:

1. Cite the specific section(s) that justify the score.
2. Quote 1–2 representative passages.
3. State the score with the matching descriptor below.

The output `reviewer-readiness.md` must be honest. Inflated scores
defeat the rubric's purpose; the user trusts the score because it is
strict.

---

## Dimension 1 — Novelty

How original is the contribution relative to lit-review.md?

| Score | Descriptor |
|---|---|
| 0 | The paper re-states existing work in different words. |
| 2 | Minor incremental improvement; the gap addressed is small or already partially closed. |
| 5 | One clearly defended gap statement with a working method. |
| 7 | Multiple gap statements, at least one with a non-trivial methodological contribution. |
| 9 | A new framing or sub-area that the field will likely cite. |
| 10 | A new problem definition that re-shapes how others think about the topic. |

Tier thresholds: arxiv ≥ 5, conference ≥ 7, journal-q1 ≥ 8.

## Dimension 2 — Evidence Quality

How strong is the experimental support for the claims?

| Score | Descriptor |
|---|---|
| 0 | No experiments, or results are missing cells. |
| 2 | Single experiment, single seed. |
| 5 | Multiple baselines, multiple seeds, but no significance testing. |
| 7 | ≥ 3 baselines, ≥ 3 seeds, p-values or CIs reported, ablations present. |
| 9 | Includes out-of-distribution or robustness tests, failure analysis, and a held-out split. |
| 10 | Multi-site replication or external-lab validation. |

Tier thresholds: arxiv ≥ 5, conference ≥ 7, journal-q1 ≥ 8.

## Dimension 3 — Reproducibility

Can a reviewer re-run the experiments from the paper?

| Score | Descriptor |
|---|---|
| 0 | No code, no data references. |
| 2 | Code in a private repo, no install instructions. |
| 5 | Public repo with README; runs end-to-end on the original hardware. |
| 7 | Public repo + container + exact seed list + environment.yml + expected wall-clock + sanity-check output. |
| 9 | Public repo + container + signed results-raw/ with hashes. |
| 10 | Public repo + container + a CI pipeline that re-runs the headline experiment on push. |

Tier thresholds: arxiv ≥ 5, conference ≥ 6, journal-q1 ≥ 8.

## Dimension 4 — Writing Clarity

Is the prose readable, the structure logical, the claims well-stated?

| Score | Descriptor |
|---|---|
| 0 | Incoherent or unreadable. |
| 2 | Grammatical but disorganized; sections do not flow. |
| 5 | Logical structure, claims stated clearly, but verbose or repetitive. |
| 7 | Tight prose, every paragraph earns its place, claims are falsifiable. |
| 9 | Reads like a well-edited journal paper; uses scholarly story-telling (per `academic-writing-storytelling` skill). |
| 10 | Multiple reviewers comment "well-written". |

Tier thresholds: arxiv ≥ 5, conference ≥ 6, journal-q1 ≥ 7.

## Dimension 5 — Figure Quality

Do the figures carry their weight?

| Score | Descriptor |
|---|---|
| 0 | No figures, or figures are unreadable. |
| 2 | Figures present but decorative; do not support claims. |
| 5 | Figures present, readable, and tied to claims in text. |
| 7 | Each figure has a 1-paragraph caption that states the take-home; color-blind safe palette. |
| 9 | Figures follow a coherent visual language (one style across all). |
| 10 | Figures are the talk of the conference. |

Tier thresholds: arxiv ≥ 5, conference ≥ 6, journal-q1 ≥ 7.

## Dimension 6 — Ethical Framing

Are limitations, ethical concerns, and broader impacts addressed honestly?

| Score | Descriptor |
|---|---|
| 0 | No discussion of limitations or ethics. |
| 2 | Limitations mentioned in passing. |
| 5 | Dedicated limitations section; brief ethical note. |
| 7 | Limitations + broader impact + ethical considerations, each as separate sections, each ≥ 1 paragraph. |
| 9 | Honest failure-mode catalog + mitigations + future work that the field actually needs. |
| 10 | Becomes a reference for how to discuss ethics in the sub-area. |

Tier thresholds: arxiv ≥ 5, conference (n/a — not required), journal-q1 ≥ 6.

## How the verifier uses this

```yaml
reviewer_readiness:
  novelty: 7          # + evidence quote
  evidence: 8         # + evidence quote
  reproducibility: 7  # + evidence quote
  clarity: 8          # + evidence quote
  figures: 7          # + evidence quote
  ethics: 6           # + evidence quote
  overall_pass: true  # all dimensions ≥ tier threshold
  weakest_dimension: ethics
  recommended_fixes:
    - ethics: add a paragraph on dataset bias in the failure cases
```

If `overall_pass: false`, the verifier lists each under-threshold
dimension in `next-steps.md` with a 1-paragraph "what to fix" suggestion
and the matching section in `paper.tex`.