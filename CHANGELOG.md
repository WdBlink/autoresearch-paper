# Changelog

All notable changes to **autoresearch-paper** are documented here.
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
within the Mavis skill family:

- **Major** (1.0+) — breaking changes to the orchestrator contract or
  state-schema.
- **Minor** (0.x.0) — new feature (tier, gate, watchdog layer, etc.).
- **Patch** (0.0.x) — bug fixes, refactors, doc updates.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Conventional Commits](https://www.conventionalcommits.org/).

## [0.6.0] - 2026-06-26

### Added

- **Agent Skills monorepo layout.** The skill bundle moves to
  `skills/autoresearch-paper/` so `npx skills add WdBlink/autoresearch-paper`
  resolves it. Root `README.md` and `docs/` stay at the repo root.
- **Full test bundle under `tests/`.** Contract tests for research gate,
  L0 dry-run, plan-dir resolution, stop/cleanup JSON escaping, and
  manifest-based resource cleanup.
- **`CHANGELOG.md`** at repo root, this file.
- **`docs/ROADMAP.md`** with three-tier planning board (on-deck / candidates
  / wishlist).

### Fixed

- **Cleanup script subcommand fix.** `mavis agent archive` and
  `mavis session archive` in `references/scripts/cleanup-plan-resources.sh`
  replaced with the correct subcommands (`delete` and `compress`
  respectively). The original bug let residual agents and sessions leak
  across plans because the helper CLI exited 0 while printing an error.

### Changed

- README: adds Status, Table of Contents, Architecture, FAQ, Changelog,
  and Citation sections.
- `SKILL.md`: adds `## Versioning` section so the changelog is reachable
  from a stable anchor.

## [0.4.0] - 2026-06-26

### Added

- **Platform-portable daemon pattern.** Replaces the Linux-only `setsid`
  step in `nohup` invocations with a portable `(command &) disown` form,
  so the same bootstrap works on macOS and Linux.
- **Producer discipline pre-flight checklist.** Hardens the producer
  against the "ran a quick smoke test and exited before launching the
  full sweep" failure mode. The checklist enforces corruption-guard
  sanity, lockfile, progress.json, aggregator slot, and cron readiness
  before the worker exits.
- **In-process model preload.** For NN inference backends (VGGT-Ω,
  DUSt3R, PyTorch baselines), the model is loaded once at task start
  and passed to every cell, instead of reloaded per cell.

### Added (reviewer rubric)

- **Harness-paper honest-framing pattern.** When the harness is dormant
  on a SOTA-tuned baseline (B5 == B0 on the primary metric), the
  reviewer rubric now expects an explicit "no regression on SOTA" plus
  a separate "preventive gain on stress" claim, instead of a wrapped
  paper that hides the no-op finding.

## [0.3.1-r5] - 2026-06-25

### Added

- **Step 7.5.a + FM-15**: wide-table 2-column `multicolumn` span
  recipe for camera-ready LaTeX output. Fixes the cell-overflow issue
  in `\begin{tabular}{lcc}` when the metric column has 12+ entries.

## [0.3.1] - 2026-06-25

### Added

- **V6 evidence-driven optimization round.** Six rounds of Darwin-style
  rubric evaluation (dim1–dim9) over the 5-day window. The
  V6 evaluation surface includes engine-ceiling handling, verifier
  spot-check recipe, and the 0% framing honesty pattern for negative
  results.
- **Reviewer-readiness rubric (6 dimensions).** Structure, Effectiveness,
  Resource Integration, Checkpoints, Safety, and Reproducibility.
  The 9-dim SkillLens rubric is consulted for inspiration but the
  authoritative score uses the 6-dim version tuned for paper skills.

## [0.3.0] - 2026-06-24

### Added

- **Rescue Layer.** L0 filesystem-corruption guard, hourly watchdog
  cron, plan-rescue daemon (`references/scripts/plan-rescue-daemon.py`),
  and three failure-mode FMs (manual_retry, soft_pause, hard_abort).
- **Abort gate.** A `🔴 STOP · ABORT GATE` marker that the L0 guard
  writes when filesystem state is corrupted; the user must explicitly
  acknowledge before any cleanup.
- **Workspace isolation.** A `🔴 STOP · WORKSPACE ISOLATION` marker
  that pins the plan dir on plan start; any cross-plan write attempt
  triggers an alert and rollback.
- **`resource_manifest.json` contract.** Every ephemeral resource
  (agent, cron, hook, lock, background process) is recorded and
  walked by `cleanup-plan-resources.sh` on stop / complete / abort.

## [0.2.0] - 2026-06-23

### Added

- **Three-tier plan templates.** `references/plan-template-arxiv.md`,
  `conference.md`, `journal-q1.md`. Tier selection is driven by
  `goal-keywords.md` and `tier-decision-tree.md`.
- **Heartbeat contract.** L0 (filesystem), L1 (hourly cron), L2
  (per-task `last_seen.jsonl`). Each layer has its own recovery path.

## [0.1.0] - 2026-06-22

### Added

- Initial brief-to-paper pipeline. Receives a paragraph-level research
  brief, generates a `plan.yaml`, freezes the evaluator at T0, runs
  method/experiment loop T1–T6, gates writing at T6.1/T6.2, and
  delivers `paper.tex` + bibliography + figures + readiness report
  at T7.

[0.6.0]: https://github.com/WdBlink/autoresearch-paper/releases/tag/v0.6.0
[0.4.0]: https://github.com/WdBlink/autoresearch-paper/releases/tag/v0.4.0
[0.3.1-r5]: https://github.com/WdBlink/autoresearch-paper/compare/v0.3.1...v0.3.1-r5
[0.3.1]: https://github.com/WdBlink/autoresearch-paper/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/WdBlink/autoresearch-paper/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/WdBlink/autoresearch-paper/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/WdBlink/autoresearch-paper/releases/tag/v0.1.0
