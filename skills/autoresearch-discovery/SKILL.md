---
name: autoresearch-discovery
description: Use when turning an early research idea and constraints into a falsifiable Research Brief before designing an experiment or adapting a repository.
---

# Auto-Research Discovery

## Core contract

Turn the supplied idea into exactly one stage artifact: `research-brief.md`.
It defines a researchable question and the evidence needed to evaluate it; it does
not claim novelty, superiority, or feasibility without support.

## Inputs

Collect the idea or problem, stated constraints, target audience if supplied, and
available literature sources. Ask only for material context that prevents framing a
testable question. Treat demands for novelty or state-of-the-art results as claims
to investigate, not requirements to promise.

## Procedure

1. State the problem, affected setting, practical constraints, and target audience.
2. Locate relevant prior art from credible, traceable sources. Record citation
   details sufficient to verify each source, verify that the source supports the
   stated comparison, and distinguish direct evidence from uncertain leads.
3. Identify a specific gap that the evidence supports. Never infer novelty merely
   because a quick search found no match; say when coverage, terminology, or source
   access leaves the gap uncertain.
4. Frame one falsifiable hypothesis and its falsifier: an observation that would
   undermine it. List plausible baselines and the minimum evaluation evidence needed
   to make the comparison meaningful.
5. If the evidence or constraints do not support a testable question, finish with
   `no-testable-opportunity` and explain why rather than fabricating a hypothesis.

## Research Brief

Write `research-brief.md` with exactly these headings, in this order:

1. Problem
2. Prior art
3. Gap
4. Hypothesis
5. Falsifier
6. Plausible baselines
7. Evaluation requirements
8. Risks
9. Recommended next step

In **Prior art**, include verified citations and any uncertainty about their scope.
In **Evaluation requirements**, describe only the evidence a later stage must
obtain, without selecting tools, repositories, metrics, thresholds, or protocols.

## Stop

Stop after writing the Research Brief. A terminal brief can recommend gathering
better literature, narrowing the setting, or ending the line of inquiry when it is
`no-testable-opportunity`.

## Boundaries

This stage owns why and what to research, not how to implement it. Do not adapt a
repository, inspect implementation details beyond evaluation feasibility, classify
an actual evaluator, build an evaluator, select an implementation approach,
optimize a candidate, freeze experimental thresholds, validate final claims, write
a paper, or create downstream experiment or implementation artifacts.
