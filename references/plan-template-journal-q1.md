# Plan Template — `journal-q1` Tier

Same 8-task skeleton as `conference`, but with deeper experiments, longer
wall-clock, and stricter gates. Targets SCI Q1 / Nature 子刊 / T-PAMI / T-RO.

## Plan shape

Identical to `conference`:

```
T1 lit ─▶ T2 gap ─▶ T3 method ─▶ T4 impl ─▶ T5 plan ─▶ T6 expt
                                                       │
                                                       ▼
                              T7 write-1 ◀───────────────┤
                                  │
                                  ▼
                              T8 write-2 ◀──── T9 ablation (required)
                                  │
                                  ▼
                              T10 pkg
                                  │
                                  ▼
                              T11 readiness
```

Total wall-clock target: 3–7 days.

## Differences from `conference` tier

### Stricter experiment gates

| Aspect | conference | journal-q1 |
|---|---|---|
| Number of seeds per result | ≥ 3 | ≥ 5 |
| Statistical reporting | p-values encouraged | confidence intervals required |
| Baseline count | ≥ 3 | ≥ 5, including a recent SOTA |
| Dataset count | ≥ 1 | ≥ 2, ideally from different domains |
| Wall-clock budget per expt | hours | days |

### T9 ablation is required (not optional)

- ≥ 6 ablations (vs 4 in conference tier).
- Each ablation must include a 1-paragraph interpretation of *why* the
  metric moved, not just the number.

### Additional rigor tasks injected

These are inserted between T6 and T7:

```
T6 expt ─▶ T6.5 robustness ─▶ T6.6 failure-analysis ─▶ T7 write-iter1
```

- **T6.5 robustness**: stress-test the method on out-of-distribution
  inputs, perturbed inputs, or held-out splits. Output
  `<plan-dir>/out/robustness.md`.
- **T6.6 failure-analysis**: catalog ≥ 5 failure cases from the
  experiment. Output `<plan-dir>/out/failure-cases.md` with each case
  tagged with a hypothesized cause and a 1-paragraph discussion.

Both are required for journal reviewers, who routinely ask
"what about distribution shift" and "show me where it fails".

### T7 write-iter1 has a longer format

Journal papers typically allow 12–14 pages + references vs 8 pages for
conferences. T7 must produce:

- ≥ 6 figures (vs 4 in conference).
- ≥ 3 tables (vs 2).
- An extended related-work section (≥ 1.5 pages) since journal review
  takes months and reviewers expect comprehensive positioning.

### T8 write-iter2 includes a "discussion" section

Conferences often skip a discussion section; journals always have one.
T8 must produce:

- `<plan-dir>/out/discussion.md` — limitations, future work, broader
  impact, ethical considerations. This is then folded into the final
  paper.tex.

### T11 readiness rubric thresholds

| Dimension | conference | journal-q1 |
|---|---|---|
| Novelty | ≥ 7 | ≥ 8 |
| Evidence quality | ≥ 7 | ≥ 8 |
| Reproducibility | ≥ 6 | ≥ 8 |
| Writing clarity | ≥ 6 | ≥ 7 |
| Figure quality | ≥ 6 | ≥ 7 |
| Ethical framing | n/a | ≥ 6 (required) |

Anything below threshold surfaces in `next-steps.md` and blocks T12
(there is no T12 in journal tier — submissions don't go through rebuttal,
they go through major/minor revision).

## When to downgrade

If after T1+T2 the user realizes the work does not yet have journal-grade
depth, surface this and ask: "Detected conference-tier depth, not
journal-grade. Downgrade to `conference` plan?" Do not silently continue
the heavier plan — burning 7 days on something that needed 10 would be
worse than restarting at the lighter tier.