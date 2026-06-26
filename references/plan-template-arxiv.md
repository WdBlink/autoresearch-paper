---
name: plan-template-arxiv
description: Minimal 4-task plan.yaml template for the arxiv tier — literature → gap → method → write. Used when SKILL.md Step 3 generates a preprint/tech-report plan.
---

# Plan Template — `arxiv` Tier

Minimal 4-task plan. Used when the user wants a working paper, a tech
report, a preprint, or explicitly opts out of a venue gate. Unlike
conference/journal tiers, arxiv may proceed with a clean negative result,
but the waiver must be explicit in `state/research_acceptance.md`.

## Execution Procedure

```
render_arxiv_plan(brief, materials, plan_dir) -> plan_yaml

create literature, method+experiment, research-decision, writing/package tasks
load prompt bodies from ../assets/task-prompt-snippets.md
initialize research_acceptance.md as FAIL
allow writing only after PASS or WAIVED_NEGATIVE_RESULT
```

## Plan shape

```
[literature] ──▶ [method+expt fused] ──▶ [research-decision] ──▶ [write-iter1+pkg fused]
                       │
                       └─▶ (optional) ablation
```

Total wall-clock target: 1–2 days.

## Task definitions

### T1 — literature-review

- **depends_on**: []
- **agent**: literature-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T1`
- **inputs**: paragraph ① (topic), paragraph ③ (materials)
- **outputs**:
  - `<plan-dir>/out/lit-review.md` — 10–25 papers, each with 1-paragraph
    summary, key claim, and how it relates to the topic.
  - `<plan-dir>/out/lit-taxonomy.md` — 2-axis taxonomy (e.g. method ×
    application).
- **gate**: must enumerate at least 10 distinct papers. Hard fail if
  fewer than 6 — `paper-deconstruction` skill is for individual papers,
  this task is the breadth pass.

### T2 — method-and-experiment

- **depends_on**: [T1]
- **agent**: method-expt-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T2`
- **inputs**: T1 outputs, paragraph ①
- **outputs**:
  - `<plan-dir>/out/method.md` — proposed method, 1–2 pages, with at
    least one figure-equivalent sketch (text + ASCII or vector spec).
  - `<plan-dir>/out/experiment-design.md` — what will be run, on what
    data or simulator, with what baseline comparison.
  - `<plan-dir>/out/results.md` — actual numbers from the run, in a
    table. Even if the result is "baseline wins, our method loses",
    that is a publishable negative result for a preprint.
- **gate**: results table must be non-empty. The skill does not enforce
  statistical significance here — that is for the conference tier.

### T2.5 — research-decision

- **depends_on**: [T2]
- **agent**: verifier-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T6.2-research-decision`
- **outputs**:
  - `<plan-dir>/state/research_acceptance.md`
  - `<plan-dir>/state/progress.json`
  - `<plan-dir>/state/scoreboard.tsv`
- **gate**: write one of:
  - `PASS` if the result supports a clear positive claim.
  - `WAIVED_NEGATIVE_RESULT` if the plan is intentionally writing an
    honest negative-result or reproducibility preprint.
  - `FAIL` if there is no interpretable result table.

### T3 — write-and-package

- **depends_on**: [T2.5]
- **agent**: writer-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T7-write-iter1`
  and `../assets/task-prompt-snippets.md#T10-pkg`
- **inputs**: all T1 + T2 outputs
- **outputs**:
  - `<plan-dir>/out/paper.tex` — single-column or two-column LaTeX.
  - `<plan-dir>/out/figures/` — standalone PDFs.
  - `<plan-dir>/out/bibliography.bib` — BibTeX.
  - `<plan-dir>/out/reviewer-readiness.md` — `reviewer-readiness-rubric.md`
    scoring, 6 dimensions, each 0–10. Tier `arxiv` accepts ≥ 5 per
    dimension; nothing lower.
- **gate**: `state/research_acceptance.md` must contain `PASS` or
  `WAIVED_NEGATIVE_RESULT`.

### T4 — readiness-self-check

- **depends_on**: [T3]
- **agent**: verifier-agent
- **prompt_snippet**: see `../assets/task-prompt-snippets.md#T11-readiness`
- **inputs**: T3 outputs
- **outputs**:
  - `<plan-dir>/out/next-steps.md` — what a human should still do
    before posting to arxiv. For arxiv tier, the typical list is:
    - verify author list and affiliations
    - compile to PDF and visually check
    - decide on license (CC-BY vs CC-BY-NC vs arXiv non-exclusive)
    - write the arxiv abstract (1500 char limit)
- **wall-clock**: ≤ 30 min.

## What the arxiv tier skips

- write-iter2 (no second writing pass)
- rebuttal-preview (no venue reviews to anticipate)
- statistical-significance enforcement
- cross-venue formatting (each venue has different LaTeX class)

These are added back at `conference` and `journal-q1` tiers.

## When to escalate up

If during T2 the agent realizes the topic actually warrants deeper
experiments (e.g. baseline-comparison surprises reveal a deeper story),
pause the plan, surface this to the user, and ask: "Detected potential
for conference-tier depth. Upgrade to `conference` plan and restart?"
