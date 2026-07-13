# Roadmap

**autoresearch-paper** planning board. This is a living document, not a
commitment; items move between sections as reality permits. Versions are
not pre-assigned — when a roadmap item ships, the version is decided by
the [CHANGELOG.md](../CHANGELOG.md) entry.

## On-deck

Items with an active design and a likely first release. Expect them in
the next minor version.

### Portable runtime adapter (TBD)

The orchestrator currently hard-codes the Mavis plan-engine abstractions
(`mavis team plan`, `mavis cron`, `mavis hook`). A portable adapter would
let the same brief → plan → T0 → T6.2 path run under Codex CLI or
Claude Code, with the Mavis path as the fully-featured default.

- **Scope (intended)**: brief intake, plan generation, T0 evaluator
  freeze, T6 research-gate verdict. Not the autonomous run loop
  (watchdog, cron, hooks) — those are Mavis-specific by design.
- **Entry points**: `references/plan-engine-adapter.md` (sketch only),
  the `PlanEngine` interface in `references/scripts/`.
- **Risks**: divergent behavior between adapters. Mitigation: pin the
  behavior contract to a shared test fixture, not the implementation.
- **Design notes**: see [`design-review-2026-06-26.md`](design-review-2026-06-26.md)
  for the SOTA-abandonment root-cause analysis that motivates this.

### Multi-language paper output

The current `paper.tex` template is English-centric. Researchers writing
for non-English venues (CCF-A 中文 / CJK journals, French-speaking labs)
have asked for a localized template path.

- **Scope (intended)**: parallel `paper-zh.tex` / `paper-fr.tex` templates
  driven by the brief's `language` field. Bibliography style also
  localizes (GB/T 7714 vs. APA vs. IEEE).
- **Open questions**: how reviewer-readiness scoring applies to
  non-English text. The current rubric is English-tuned.

## Candidates

Items with a design sketch but no active branch. Pull requests welcome.

### Multi-author plan mode

Two or more humans share one plan; the gate verdicts and cleanup hooks
track a `authors` list. Useful for advisor / student co-writing.

### Camera-ready submission automation

The Boundaries section explicitly says "does not submit to venues". A
follow-up skill (or feature) could wrap the camera-ready steps
(anonymization, line-number toggle, response letter template) without
making the boundary claim dishonest.

### Test-time compute (T7.5.b)

If the venue allows it, re-run a small evaluation sweep at submission
time and report the fresh numbers in the readiness summary. Currently
we use the cached numbers from T6.1.

## Wishlist

Ideas that exist on the wall but have no design yet. Do not start
without an issue thread.

- **Multi-modal figure extraction.** Auto-pull figures from PDF
  references instead of asking the user to point at a folder.
- **Reviewer-simulator loop.** After T7, run a separate agent against
  the paper that mimics a venue's reviewer pool and surfaces likely
  rejection causes.
- **Cross-plan knowledge graph.** Plans today are isolated. A
  meta-plan that ingests successful `references/research-state.md`
  files from prior plans and surfaces "you already explored direction X
  on plan Y".
- **Continuous-arxiv mode.** Skip the brief step entirely; subscribe
  to an arxiv category and auto-generate a plan per paper in the feed.

## Anti-roadmap

Things we have explicitly decided **not** to build, and why. This is
the more important section.

- **Direct venue submission.** The skill is honest about producing a
  paper draft; submission is the human author's responsibility.
- **Bypass the research gate via `WAIVED_NEGATIVE_RESULT`.** The gate
  exists to make the explore-for-hours-then-write-a-zero-contribution
  failure mode visible. Silently bypassing it would defeat the skill.
- **Replace human authorship of novel claims.** The skill produces a
  paper that compiles, cites correctly, and presents the evidence the
  user has collected. It does not invent claims.
- **Generic "AI paper writer" mode.** The skill is a paper pipeline,
  not a content generator. If you want generic writing, use a writing
  skill; this one is opinionated about research-first workflows.

## How to propose a roadmap item

Open an issue with the `roadmap` label and a 2-paragraph sketch: the
user pain, the proposed shape, and the riskiest assumption. The author
of this file will move it to "Candidates" or "Wishlist" and add a
comment.
