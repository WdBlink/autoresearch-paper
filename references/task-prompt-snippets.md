# Task Prompt Snippets

Per-task prompt fragments used when the plan generator assembles
`plan.yaml`. The plan generator fills in the bracketed placeholders at
generation time. The full per-task prompt that an agent sees is
`task-snippet + topic-specific instructions + tier-specific gates`.

## How this is used

When the plan generator writes `<plan-dir>/plan.yaml`, each task's
`prompt` field is built by concatenating:

```
1. <task-snippet from this file>
2. <plan-level system context — topic, tier, evaluator>
3. <task-specific deliverables — paths, gates>
4. <output contract — exact files and their formats>
```

The generator **must** not edit the snippets — they are versioned with
the skill. Tier-specific gates live in the plan templates, not here.

---

## T1 — literature-review

```
You are running the literature-review task for a research paper.

Topic: {TOPIC}
Tier: {TIER}
Reference materials (may be empty): {MATERIALS}

Your job: enumerate the most relevant existing work, then group them
into a taxonomy that exposes where the field is dense and where it is
sparse.

Outputs (write to {OUT_DIR}):
- lit-review.md — {MIN_PAPERS} or more papers, each with:
    - title, authors, venue, year, link (DOI or arxiv id)
    - 1-paragraph summary of the contribution
    - 1-sentence "how it relates to {TOPIC}"
- lit-taxonomy.md — at least {TAXONOMY_AXES} orthogonal axes, with
  every paper from lit-review.md placed on each axis.

Gate: lit-review.md must list at least {MIN_PAPERS} distinct papers.
Hard fail otherwise.

Anti-patterns to avoid:
- Do NOT cite papers you have not actually read. If you cannot access
  a paper, say so explicitly and use the abstract as the basis for
  the summary, tagged with [abstract-only].
- Do NOT pad with unrelated tangentially-related work. Quality over
  quantity on the related axis.
- Do NOT invent DOIs or arxiv ids.

You may use the `paper-deconstruction` skill for any single paper you
want a deeper read on; that is the per-paper deep-read companion.
```

## T2-gap — gap-analysis (conference+ only)

```
You are running the gap-analysis task for a research paper.

Topic: {TOPIC}
Tier: {TIER}
Inputs: lit-review.md and lit-taxonomy.md from T1.

Your job: turn the sparse regions of the taxonomy into explicit
defensible gap statements. A gap statement is a claim that "the field
has not yet done X" with evidence.

Outputs (write to {OUT_DIR}):
- gap-statements.md — {MIN_GAPS} or more gap statements, each with:
    - the missing thing (1 sentence)
    - why it matters (1 sentence)
    - the claim this paper will defend (1 sentence)
    - which papers in lit-review.md show the gap is real
    - confidence level: high / medium / low

Gate: at least {MIN_GAPS} gap statements.
Hard fail otherwise — without a gap there is no paper.

Anti-patterns to avoid:
- Do NOT state a gap that is already addressed in lit-review.md.
  Re-read carefully before writing each statement.
- Do NOT state gaps that are merely "more compute" or "more data"
  without a methodological change. Those are engineering gaps, not
  research gaps.
- Do NOT propose a gap that requires inventing a new field. The gap
  should be defensible to a reviewer who has read the same literature.
```

## T2 — method-and-experiment (arxiv only)

```
You are running the method-and-experiment task for a research paper.

Topic: {TOPIC}
Tier: arxiv
Inputs: lit-review.md from T1.

Your job: propose a method, design a minimal experiment, and run it.
For arxiv tier, "run it" means producing numbers, not necessarily
beating every baseline. A clean negative result is acceptable.

Outputs (write to {OUT_DIR}):
- method.md — proposed method, 1–2 pages. Include a textual
  description, the algorithm in pseudocode, and a sketch of the
  architecture or pipeline.
- experiment-design.md — what data, what baseline, what metric.
- results.md — table of results, even if baseline wins.

Gate: results.md must contain a non-empty result table.
```

## T3-method — method-design (conference+ only)

```
You are running the method-design task for a research paper.

Topic: {TOPIC}
Tier: {TIER}
Inputs: lit-review.md, lit-taxonomy.md, gap-statements.md.
Selected gap to address: {SELECTED_GAP}

Your job: turn the gap into a concrete method specification.

Outputs (write to {OUT_DIR}):
- method-spec.md — full specification:
    - inputs and outputs (with shapes / types)
    - components (named, with responsibility per component)
    - training or inference pipeline
    - hyperparameters with default values
    - complexity analysis (FLOPs or wall-clock per inference)
- method-figure-spec.md — figure 1 sketch: the architecture /
  pipeline diagram. Write it as a textual specification that an
  illustrator or a tikz-generating agent can render.

Gate: method-spec.md must be detailed enough that an implementer
agent (T4) can build the system without asking you questions.
```

## T4-impl — implement (conference+ only)

```
You are running the implementation task for a research paper.

Topic: {TOPIC}
Tier: {TIER}
Inputs: method-spec.md, method-figure-spec.md.

Your job: build a runnable implementation of the method.

Outputs (write to {OUT_DIR}/code/):
- the implementation, organized as a small repo with README.md
- README.md — how to install, how to run, expected runtime on the
  target hardware
- sanity-check.md — output of a 5-minute sanity run that confirms
  the pipeline does not crash and produces a reasonable output

Gate: `python main.py` (or equivalent) must complete without error.
Hard fail otherwise.

Anti-patterns to avoid:
- Do NOT use placeholder data. If real data is unavailable, generate
  a synthetic dataset whose properties are documented in
  sanity-check.md.
- Do NOT skip the README. A future reviewer must be able to run this.
```

## T5-expt-plan — experiment-plan (conference+ only)

```
You are running the experiment-plan task for a research paper.

Topic: {TOPIC}
Tier: {TIER}
Inputs: method-spec.md, code/ from T4.

Your job: lay out the exact experiment that will answer the question
the paper is asking.

Outputs (write to {OUT_DIR}):
- expt-design.md — exact table layout (column headers, which rows),
  baseline list, metric definitions, dataset list, seed list,
  hardware budget (GPU hours), expected wall-clock.

Gate: expt-design.md must be specific enough that T6 can run it
without further clarification. If T6 has to ask a question, T5 has
failed.
```

## T6-expt — experiment (all tiers, but stricter for journal-q1)

```
You are running the experiment task for a research paper.

Topic: {TOPIC}
Tier: {TIER}
Inputs: expt-design.md, code/ from T4.

Your job: execute the experiment as designed.

Outputs (write to {OUT_DIR}):
- results.md — final result tables, exactly as laid out in
  expt-design.md
- results-raw/ — raw logs, JSON, CSV. Each row timestamped.
- significance.md — {for conference+} p-values or confidence
  intervals. {for arxiv} optional.

Gate: every cell in every result table must be filled. Empty cells
require a "why not" note in significance.md or results.md.

Anti-patterns to avoid:
- Do NOT cherry-pick seeds. Run all of them, report all of them.
- Do NOT silently drop outliers. If you drop them, log why in
  results-raw/ and report the un-dropped count in results.md.
- **0% / negative-result honest framing recipe** (V6 lesson). If your
  experiments produce M_success=0 uniformly (e.g., on a real physics
  simulator where heuristic policies can't reach waypoints in step
  budget), DO NOT report this as "failure". Distinguish:
    (a) **Heuristic-policy ceiling** — bound on what the policy can do,
        not what the architecture can do. Report as such.
    (b) **Architecture failure** — the proposed method genuinely doesn't
        work. Only claim this with quantitative evidence.
  The three legitimate contribution types when (a) is the case:
    1. **Structural verification** — the architecture's L1-L5 wiring is
       correct (e.g., L5 marker discriminates ablations via McNemar
       p < 0.0001).
    2. **Overhead measurement** — the architecture's per-layer cost is
       measurable (e.g., Wilcoxon M_time p < 0.001 across ablations).
    3. **Fault-ladder discrimination** — the fault-injection ladder
       cleanly differentiates ablations on at least one scenario.
  §5 Discussion MUST explicitly reframe-as-contribution using one of
  these three framings. NEVER claim "policy succeeds" when M_success=0.
```

## T7-write-iter1 — first writing pass

```
You are writing the first complete draft of the paper.

Topic: {TOPIC}
Tier: {TIER}
Venue: {VENUE}
Inputs: all prior outputs in {OUT_DIR}/.

Style guide:
- For conferences: follow {VENUE} author kit (LaTeX class, page
  limit). Use the `academic-writing-storytelling` skill for
  narrative shape and `paper-deconstruction` for any single-paper
  deep read you need to reference.
- For journals: longer related work, add a "discussion" placeholder
  section that T8 will fill.

Outputs (write to {OUT_DIR}):
- paper-iter1.tex — full LaTeX source.
- figures/ — each figure as a standalone PDF (vector preferred).
- bibliography.bib — full BibTeX.

Gate: every section has at least one paragraph. No [TODO]
placeholders in the body.
```

## T8-write-iter2 — second writing pass

```
You are running the second writing pass of the paper.

Inputs: paper-iter1.tex, reviewer-readiness.md (from a dry-run scoring
using reviewer-readiness-rubric.md).

Your job: lift every dimension that scored ≤ 5 to ≥ 6. Document
each change in change-log.md so the user can review what shifted.

Outputs (write to {OUT_DIR}):
- paper-iter2.tex — refined draft.
- change-log.md — per-section, what was changed and why.

Gate: ≥ 80% of low dimensions are lifted. Hard fail otherwise —
surface to user.

Page-budget fold regression guard (V6 lesson): If you are tempted to
fold a dedicated section (§6 Limitations/Ethics, §3 Method sub-section,
§5 multi-voice, etc.) into another section to hit a venue page limit,
STOP and run the Step 7.5 pre-flight check from SKILL.md first. Folding
§6 Limitations/Ethics typically regresses Dim 6 Ethics by 2 points (6 → 4
in V6); the fold is invisible until the next reviewer-readiness scoring
pass. Prefer waiver request, short-paper track, or restructuring over
silent fold.
```

## T9-ablation — ablation study (required for journal-q1, optional for conference)

```
You are running the ablation study for the paper.

Topic: {TOPIC}
Tier: {TIER}
Inputs: method-spec.md, results.md.

Your job: remove one component at a time, re-run, report the metric
delta. Interpret *why* the metric moved, not just that it did.

Outputs (write to {OUT_DIR}):
- ablation.md — table with one row per removed component, with the
  headline metric delta and a 1-paragraph interpretation.

Gate: ≥ {MIN_ABLATIONS} ablations.
```

## T10-pkg — package

```
You are producing the final submission package.

Topic: {TOPIC}
Tier: {TIER}
Venue: {VENUE}
Inputs: paper-iter2.tex (or paper-iter1.tex for arxiv tier),
figures/, bibliography.bib, change-log.md.

Your job: assemble the final paper.tex and venue-specific wrapper,
and produce a submission checklist the user can follow.

Outputs (write to {OUT_DIR}):
- paper.tex — final LaTeX source (rename from iter file).
- figures/ — final.
- bibliography.bib — final.
- venue-specific.tex — venue LaTeX class wrapper.
- submission-checklist.md — venue-specific requirements:
    - page limits
    - anonymization rules
    - supplementary rules
    - deadline and submission portal URL
    - co-author order and affiliations to verify

Negative-result framing reminder (V6 lesson): If the paper has
M_success=0 across all configs on real physics (heuristic-policy
ceiling), the §6 Limitations MUST explicitly distinguish this from
architecture failure and reframe as one of: structural verification,
overhead measurement, or fault-ladder discrimination. See T6 anti-patterns
section for the full recipe.
```

## T11-readiness — reviewer-readiness self-check

```
You are scoring the paper against reviewer-readiness-rubric.md.

Inputs: paper.tex, all of {OUT_DIR}/.

Your job: produce a 6-dimension score (0–10 each) and a per-dimension
justification. The 6 dimensions are listed in
reviewer-readiness-rubric.md.

Outputs (write to {OUT_DIR}):
- reviewer-readiness.md — scores + justifications.

Gate (tier-specific):
- arxiv: ≥ 5 per dimension
- conference: ≥ 7 on novelty / evidence / clarity; ≥ 6 elsewhere
- journal-q1: ≥ 8 on novelty / evidence / reproducibility; ≥ 7 on
  clarity / figures; ≥ 6 on ethics
```

## T12-rebuttal — rebuttal preview (optional, conference tier only)

```
You are simulating reviewer reviews and pre-writing a rebuttal.

Inputs: paper.tex, reviewer-readiness.md.

Your job: write 3 simulated reviews (Reviewer-1 / Reviewer-2 /
Reviewer-3 archetypes: thorough-but-friendly / hostile-but-fair /
lazy-but-sharp), then write a rebuttal for each anticipated
weakness.

Outputs (write to {OUT_DIR}):
- anticipated-reviews.md — 3 simulated reviews.
- rebuttal-draft.md — pre-written rebuttal for each weakness.

Anti-patterns to avoid:
- Do NOT write reviews that only praise the paper. The point of the
  exercise is to find weaknesses before the real reviewers do.
- Do NOT write rebuttals that just say "we will fix this". Cite the
  exact section / experiment you would point to.
```