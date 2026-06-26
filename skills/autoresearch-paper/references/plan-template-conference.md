---
name: plan-template-conference
description: Full 8-task plan.yaml template for the conference tier — literature → gap → method → impl → experiment → write-iter1 → write-iter2 → package. Optional rebuttal-preview task for IROS/ICRA/CVPR/NeurIPS-grade submissions.
---

# Plan Template — `conference` Tier

Research-first plan, plus an optional rebuttal-preview task. Used for
IROS/ICRA/CVPR/NeurIPS-grade submissions. T7 writing is blocked by
`state/research_acceptance.md`; completing T6 experiments is not enough.

## Execution Procedure

```
render_conference_plan(brief, materials, plan_dir) -> plan_yaml

create T0 evaluator-freeze before method work
create literature, gap, method, implementation, experiment, evaluation, decision, pivot, writing, package tasks
load prompt bodies from ../assets/task-prompt-snippets.md
route FAIL through T6.3 until PASS, WAIVED_BY_HUMAN, or human stop
```

## Plan shape

```
T0 evaluator-freeze ─▶ T1 lit-review ─▶ T2 gap-analysis ─▶ T3 method-design
        │                                                          │
        └──────────────────────────────▶ T5 experiment-plan ◀──────┤
                                                                   ▼
                                                            T4 implement
                                                                   │
                                                                   ▼
                                                            T6 experiment
                                                                   │
                                                                   ▼
                                                     T6.1 evaluate-candidate
                                                                   │
                                                                   ▼
                                                     T6.2 research-decision
                                               PASS / WAIVED       │ FAIL
                                                    │              ▼
                                                    │       T6.3 pivot-or-retry
                                                    │              │
                                                    ▼              └──▶ T3/T4/T5/T6
                                           T7 write-iter1
                                                    │
                                                    ▼
                                           T8 write-iter2 ◀──── T9 ablation (optional)
                                                    │
                                                    ▼
                                           T10 package
                                                    │
                                                    ▼
                                           T11 reviewer-readiness
                                                    │
                                                    ▼
                                           T12 rebuttal-preview (optional)
```

Total wall-clock target: 1–2 weeks.

## Task definitions

### T0 — evaluator-freeze

- **depends_on**: []
- **agent**: evaluator-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T0-evaluator-freeze`
- **outputs**:
  - `<plan-dir>/state/task_spec.md`
  - `<plan-dir>/state/evaluator.yaml`
  - `<plan-dir>/state/success_criteria.md`
  - `<plan-dir>/state/baseline_contract.md`
  - `<plan-dir>/state/allowed_search_space.md`
  - initialized `progress.json`, `directions_tried.json`,
    `candidate_registry.jsonl`, `scoreboard.tsv`, and
    `research_acceptance.md` with status `FAIL`.
- **gate**: the primary metric, baseline set, and acceptance threshold
  are frozen before T3 can propose a method. Later changes require a
  human override in `control/override_requested.json`.

### T1 — literature-review

Same as `arxiv` tier, but stricter:

- **depends_on**: [T0]
- ≥ 25 papers enumerated.
- Each paper tagged with venue + year + a 1-paragraph summary.
- `lit-taxonomy.md` must include a 3-axis taxonomy (method × application
  × data domain) so gap-finding is mechanical.

### T2 — gap-analysis

- **depends_on**: [T1]
- **agent**: gap-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T2-gap`
- **inputs**: T1 outputs, paragraph ①
- **outputs**:
  - `<plan-dir>/out/gap-statements.md` — 3–7 explicit gap statements,
    each with: what is missing, why it matters, and a 1-sentence claim
    we will defend in the paper.
- **gate**: ≥ 3 gap statements. Hard fail otherwise — without a gap
  there is no paper.

### T3 — method-design

- **depends_on**: [T2]
- **agent**: method-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T3-method`
- **inputs**: T1, T2, paragraph ①
- **outputs**:
  - `<plan-dir>/out/method-spec.md` — full method specification:
    inputs, outputs, components, training/inference pipeline, hyperparameters.
  - `<plan-dir>/out/method-figure-spec.md` — figure 1 sketch (the
    "architecture" or "pipeline" figure every paper needs).
  - append/update `<plan-dir>/state/directions_tried.json` with the
    proposed direction id before implementation begins.
  - append one `PROPOSED` entry to
    `<plan-dir>/state/candidate_registry.jsonl`.
- **gate**: direction must not duplicate an exhausted/discarded entry in
  `directions_tried.json`.

### T4 — implement

- **depends_on**: [T3]
- **agent**: implement-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T4-impl`
- **inputs**: T3 spec
- **outputs**:
  - `<plan-dir>/out/code/` — implementation, runnable end-to-end.
  - `<plan-dir>/out/code/README.md` — how to run, expected runtime.
  - `<plan-dir>/out/code/sanity-check.md` — output of a 5-minute
    sanity run that confirms the pipeline does not crash.

### T5 — experiment-plan

- **depends_on**: [T0, T3, T4]
- **agent**: expt-plan-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T5-expt-plan`
- **inputs**: T3, T4
- **outputs**:
  - `<plan-dir>/out/expt-design.md` — exact table layout, baselines,
    metrics, datasets, seeds, hardware budget. Reviewer-2 must be able
    to read this and reproduce.

### T6 — experiment

- **depends_on**: [T5]
- **agent**: expt-run-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T6-expt`
- **inputs**: T5
- **outputs**:
  - `<plan-dir>/out/results.md` — full result tables.
  - `<plan-dir>/out/results-raw/` — raw logs, JSON, or CSV.
- `<plan-dir>/out/significance.md` — p-values or confidence intervals
    where applicable; flagged when not.

### T6.1 — evaluate-candidate

- **depends_on**: [T6]
- **agent**: verifier-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T6.1-evaluate-candidate`
- **inputs**: T0 evaluator files, T6 outputs, raw logs
- **outputs**:
  - `<plan-dir>/out/candidate-evaluation.md` — independent metric
    comparison against the frozen baseline contract.
  - appended `<plan-dir>/state/scoreboard.tsv` row.
  - appended `<plan-dir>/state/candidate_registry.jsonl` row with
    `KEEP`, `DISCARD`, `PIVOT`, or `ESCALATE`.
- **gate**: evaluator must cite exact result files. Producer self-claims
  are insufficient.

### T6.2 — research-decision

- **depends_on**: [T6.1]
- **agent**: orchestrator-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T6.2-research-decision`
- **outputs**:
  - `<plan-dir>/state/research_acceptance.md`
  - updated `<plan-dir>/state/progress.json`
  - optional `<plan-dir>/control/pivot_requested.json`
- **gate**:
  - `PASS` only if T6.1 meets the frozen success criteria.
  - `FAIL` increments `stale_count`.
  - `stale_count >= 2` requires structural pivot via T6.3.
  - `stale_count >= 4` requires escalation to human.

### T6.3 — pivot-or-retry

- **depends_on**: [T6.2 when research_acceptance.md is FAIL]
- **agent**: method-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T6.3-pivot-or-retry`
- **outputs**:
  - updated `<plan-dir>/state/directions_tried.json`
  - updated `<plan-dir>/state/progress.json`
  - a new method-design brief that routes back to T3/T4/T5/T6
- **gate**: if `stale_count >= 2`, the change must be structural
  (algorithm family, data representation, objective, evaluator, or
  baseline framing), not a hyperparameter tweak.

### T7 — write-iter1

- **depends_on**: [T6.2]
- **agent**: writer-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T7-write-iter1`
- **inputs**: all prior outputs
- **outputs**:
  - `<plan-dir>/out/paper-iter1.tex` — first complete draft.
  - `<plan-dir>/out/figures/` — all figures.
  - `<plan-dir>/out/bibliography.bib`.
- **gate**: each section (intro / related / method / expt / conclusion)
  has at least one paragraph. No `[TODO]` placeholders in the body.
  Hard fail unless `state/research_acceptance.md` contains `PASS` or
  `WAIVED_BY_HUMAN`.

### T8 — write-iter2

- **depends_on**: [T7]
- **agent**: writer-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T8-write-iter2`
- **inputs**: T7 outputs, reviewer-readiness-rubric scoring
- **outputs**:
  - `<plan-dir>/out/paper-iter2.tex` — refined draft.
  - `<plan-dir>/out/change-log.md` — what iter2 changed vs iter1,
    section by section.
- **gate**: ≥ 80% of iter1's `reviewer-readiness-rubric.md` low scores
  (≤ 5) are lifted to ≥ 6. Hard fail otherwise — surface to user.

### T9 — ablation (optional)

- **depends_on**: [T6.2, T7]
- **agent**: ablation-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T9-ablation`
- **inputs**: T6 results, T3 spec
- **outputs**:
  - `<plan-dir>/out/ablation.md` — ablation table, one row per removed
    component, with the headline metric delta.
- **gate**: ≥ 4 ablations. Hard fail otherwise — reviewer-3 will
  ask "what if you remove X" within 5 minutes.

### T10 — package

- **depends_on**: [T8, T9 if present]
- **agent**: pkg-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T10-pkg`
- **inputs**: all prior outputs
- **outputs**:
  - `<plan-dir>/out/paper.tex` — final version (rename from iter2).
  - `<plan-dir>/out/figures/` — final.
  - `<plan-dir>/out/bibliography.bib` — final.
  - `<plan-dir>/out/venue-specific.tex` — venue LaTeX class wrapper
    (CVPR / ICRA / IROS each have different `\documentclass` options).
  - `<plan-dir>/out/submission-checklist.md` — venue-specific
    submission requirements (page limits, anonymization, supplementary
    rules, deadline).

### T11 — reviewer-readiness

- **depends_on**: [T10]
- **agent**: verifier-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T11-readiness`
- **inputs**: T10
- **outputs**:
  - `<plan-dir>/out/reviewer-readiness.md` — 6-dimension scoring using
    `reviewer-readiness-rubric.md`. Tier `conference` requires ≥ 7
    per dimension on the headline claims (novelty, evidence, clarity)
    and ≥ 6 on the rest. Anything below is flagged in
    `next-steps.md`.

### T12 — rebuttal-preview (optional, opt-in)

- **depends_on**: [T11]
- **agent**: rebuttal-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T12-rebuttal`
- **inputs**: T10, T11
- **outputs**:
  - `<plan-dir>/out/anticipated-reviews.md` — 3 simulated reviewer
    reviews (Reviewer-1 / Reviewer-2 / Reviewer-3 archetypes).
  - `<plan-dir>/out/rebuttal-draft.md` — pre-written rebuttal for each
    anticipated weakness.
- **opt-in**: ask the user before launching this task. It is valuable
  but not part of the standard submission path.
