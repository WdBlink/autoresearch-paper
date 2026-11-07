# Autoresearch Paper

<picture>
  <source media="(prefers-color-scheme: dark)" srcset=".github/logo-dark.svg">
  <img alt="Autoresearch Paper" src=".github/logo-light.svg" width="440">
</picture>

![version](https://img.shields.io/badge/version-3.0.0-blue)

Autoresearch Paper is an independent skill for conducting research and producing
a manuscript with verified evidence. Start with `$autoresearch <research question>`
in Codex or `/autoresearch <research question>` in Claude Code. The same workflow
carries the project through experiments, writing, independent review, and delivery.

## Workflow

Materials and scope/angle/audience → candidate venue comparison → chosen target
and 8–15 matched accepted-paper samples → per-figure/table/panel analysis →
concrete research and deliverable plan → literature and citation verification →
experiments or review evidence → figures → writing → independent quality/R6/item
review → verified PDF, editable source and evidence archive.

An unknown venue starts a draft research Brief. Read-only preparation can
compare sourced candidates and measure templates before the final obligations
are frozen. The actual concrete Brief is approved before experiments. Existing
exact choices and authorizations are reused. Every changed obligation remains
explicit; no research result, simulated score or operator silence grants approval.

The host performs source reading, scientific reasoning, actual experiments and
independent review. Deterministic scripts reveal the current stage and verify
inputs, records, hashes, budgets and handoffs. They do not infer scientific truth.

Venue choice, the concrete plan budget and every budget increase are actual
user-answer steps. The host shows sourced candidates or the plan/resources,
asks through its user-input interface and waits for the reply. The single
optional `budget` defaults to `{}` with no hidden task total cap and grants no
new paid-resource permission. Calls, tokens, cost and total wall time can be
capped explicitly; usage persists across sessions. Thirty minutes is a checkpoint
prompt followed by continued available work. See the
[question/answer contract](foundation/references/user-input.md) and
[budget/exit contract](foundation/references/budget.md).

## Install and run

```sh
git clone https://github.com/WdBlink/autoresearch-paper.git
cd autoresearch-paper
bash scripts/install.sh --codex --global
```

Start a new Codex session and invoke `$autoresearch` with your research question
and materials. The installed controller is `skills/autoresearch/paper/scripts/research.py`.
See the [installation guide](guide/getting-started.md) for other hosts and local installs.

Use `context` for the actual stage knowledge and task contract. Scriptable steps
include `tool --name venue-compare`, `venue-design-template`, `venue-calibrate`,
`plan-snapshot`, `plan-audit`, and `citation-check`. Round snapshots, citation
batches, per-item delivery, section ownership, compilation and recovery use the
same controller store. Full fields are in
[packets](foundation/references/packets.md),
[venue packets](foundation/references/venue-packets.md), and
[science packets](foundation/references/science-packets.md).

## Auxiliary engineering commands

Use `$autoresearch iterate` for the classic metric loop.
Plan/debug/fix/probe/reason/predict/scenario/improve/learn/evals/regression and
security/ship support specific engineering tasks. Use `$autoresearch --auto` for
predicate orchestration. The frozen evaluator and research ledger stay outside the
scope of Git rollback. See the [command guides](guide/README.md).

## Evidence and ownership

[Deli parity audit](docs/DELI_PARITY_AUDIT.md) distinguishes actual migrated
checks, host judgment and intentionally inapplicable historical heuristics.
[Source provenance](foundation/provenance.json) records the Deli, PaperFlow, and
Wiki materials used to develop the workflow. The [MIT license](LICENSE) includes
the applicable copyright notices.

Offline fixtures exercise real PDF measurements, eight generated venue sample
PDFs, statistics, TeX builds, citation/claim bindings, itemized review interfaces,
recovery and export. They are software tests, not real papers or actual model
reviews. The statistical tools support paired independent cases and a bounded
local response protocol. See the [science packets](foundation/references/science-packets.md)
for their assumptions and the [runtime contract](foundation/references/runtime-contract.md)
for run versioning.
