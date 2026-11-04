# Autoresearch Paper

![version](https://img.shields.io/badge/version-2.3.0-blue)

A research-to-paper Skill developed on the complete
[uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch) v2.3.0 source.
The main invocation is `$autoresearch <research question>` in Codex or
`/autoresearch <research question>` in Claude Code. The whole Skill performs the
research workflow. Manuscript writing is its late `write` stage.

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

## Run and inspect

```sh
bash scripts/transform.sh
bash scripts/install.sh --codex --global --config-dir /absolute/test-config --force
python3 scripts/research.py --run /absolute/private-run --help
bash scripts/test-paper.sh
```

The installer example uses an explicit test configuration. No model or remote
compute starts during install. The installed main controller is
`skills/autoresearch/paper/scripts/research.py`; `paper/` is a bundled implementation
folder, not a second Skill or a paper-only product entry.

Use `context` for the actual stage knowledge and task contract. Scriptable steps
include `tool --name venue-compare`, `venue-design-template`, `venue-calibrate`,
`plan-snapshot`, `plan-audit`, and `citation-check`. Round snapshots, citation
batches, per-item delivery, section ownership, compilation and recovery use the
same controller store. Full fields are in
[packets](foundation/references/packets.md),
[venue packets](foundation/references/venue-packets.md), and
[science packets](foundation/references/science-packets.md).

## Upstream tools retained

Use `$autoresearch iterate` explicitly for the original metric loop.
Plan/debug/fix/probe/reason/predict/scenario/improve/learn/evals/regression and
security/ship remain bounded auxiliary protocols. Predicate orchestration,
hooks, rollback and fork-and-flush retain their upstream mechanisms. Contexts
fork from the best commit, while the frozen evaluator and research ledger remain
outside the editable scope. [Original upstream guide](guide/upstream-readme.md).

## Evidence and ownership

[Deli parity audit](docs/DELI_PARITY_AUDIT.md) distinguishes actual migrated
checks, host judgment and intentionally inapplicable historical heuristics.
[Source provenance](foundation/provenance.json) pins user-local Deli additions,
PaperFlow changes and Wiki methods. Unlicensed third-party Deli originals are
not republished or relicensed. The complete upstream MIT license is retained.

Offline fixtures exercise real PDF measurements, eight generated venue sample
PDFs, statistics, TeX builds, citation/claim bindings, itemized review interfaces,
recovery and export. They are software tests, not real papers or actual model
reviews. The numerical adapter currently supports paired independent cases and
mean/SD/SE/exploratory normal CI; unsupported protocols fail explicitly. Existing
runs stay pinned to their implementation; an upgrade does not hot-migrate them.
