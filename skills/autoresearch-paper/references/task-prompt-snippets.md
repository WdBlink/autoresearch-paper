---
name: task-prompt-snippets
description: Index and usage contract for the task prompt snippets asset used by plan generation.
---

# Task Prompt Snippets

This reference tells the plan generator when and how to load the full
snippet asset. The long prompt bodies live in
`assets/task-prompt-snippets.md` so `references/` stays procedural and
auditable.

## Execution Procedure

```
load_task_snippets(tier, task_graph) -> snippet_map

read assets/task-prompt-snippets.md
for each task in task_graph:
    resolve the matching snippet heading
    concatenate snippet + plan context + deliverable contract
return snippet_map
```

## Usage Rules

- Do not edit snippet text while generating a plan.
- Fill only bracketed placeholders such as `{TOPIC}`, `{TIER}`,
  `{PLAN_DIR}`, `{OUT_DIR}`, and `{MATERIALS}`.
- Keep tier-specific gates in the plan templates; keep reusable worker
  prompts in the asset.
- Generated v0.17 plans use one executable stage at a time. Worker prompts may
  propose next questions but cannot create executable downstream stages,
  apply Gate decisions, or widen their role-visible evidence.
- `state/staged_research/v1/` is the sole runtime truth. Never place
  `state/progress.json` or `state/research-dossier.md` in a prompt as authority;
  they are rebuildable, non-authoritative projections. If an operator view is
  missing or suspect, use `rebuild-staged-projections` from canonical state.
- `capacity v2` keeps per-stage Worker quota, global Worker capacity,
  `STAGE-REVIEW`, and CP-01/CP-02/CP-04 (optionally CP-03) separate. Prompt text
  cannot transfer those classes, and a frontier top-up cannot add Worker
  allowance.
- Prepare bootstrap JSON under `control/staged-inputs/` and review materials
  under `control/review-materials/`. Never create or write
  `state/staged_research/v1/` directly; only `init-staged-research` may publish
  the initial canonical state.
- Legacy capacity v1 is existing-plan lifecycle/replay compatibility and must
  not be copied into a new v0.17 plan or used for automatic stage crossing.
- A Worker may propose Stage 2 material, but only
  `advance-staged-research` may use an initial signed pre-authorization for one
  named next stage. It requires the prior terminal decision, MiniMax report,
  and fresh strongest-policy review before deriving a bound receipt and
  starting exactly one next-stage Worker; `silence_is_approval=false`.
- If a task references a missing snippet heading, stop plan generation and
  repair the template or asset before showing the preview.

## Snippet Index

Full text: `assets/task-prompt-snippets.md`.

| Task | Asset heading |
|---|---|
| T0 evaluator freeze | `T0-evaluator-freeze` |
| T1 literature review | `T1` |
| T2 arxiv method and experiment | `T2` |
| T2 conference gap analysis | `T2-gap` |
| T3 method design | `T3-method` |
| T4 implementation | `T4-impl` |
| T5 experiment plan | `T5-expt-plan` |
| T6 experiment | `T6-expt` |
| T6.1 independent evaluation | `T6.1-evaluate-candidate` |
| T6.2 research decision | `T6.2-research-decision` |
| T6.3 pivot or retry | `T6.3-pivot-or-retry` |
| T6.4 figure build | `T6.4-figure-build` |
| T7 write iter1 | `T7-write-iter1` |
| T8 write iter2 | `T8-write-iter2` |
| T9 ablation | `T9-ablation` |
| T10 package | `T10-pkg` |
| T11 reviewer readiness | `T11-readiness` |
| T12 rebuttal preview | `T12-rebuttal` |

The asset must continue to mention `directions_tried.json` and
`research-state-guard.py` in the research-loop snippets so generated
plans inherit direction de-duplication and the executable writing gate.
