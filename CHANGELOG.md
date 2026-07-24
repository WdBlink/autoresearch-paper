# Changelog

All notable changes to **autoresearch-paper** are documented here.
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
within the Harness contract:

- **Major** (1.0+) — breaking changes to the orchestrator contract or
  state-schema.
- **Minor** (0.x.0) — new feature (tier, gate, watchdog layer, etc.).
- **Patch** (0.0.x) — bug fixes, refactors, doc updates.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Conventional Commits](https://www.conventionalcommits.org/).

## [0.14.0] - 2026-07-24

### Added

- A host-neutral scientific figure artifact schema binding source inputs,
  transformations, render commands, renderer identity, outputs, hashes, and
  human review bound to every current output.
- An offline, standard-library figure validator with path-confinement,
  symlink-escape, inventory, hash, provenance, format, preview, output-bound
  human-review, and authority checks.
- A post-research-decision figure-build stage and pre-writing/package gates
  across arxiv, conference, and journal plans.
- Focused Scientific Visualization integration at the audited upstream
  revision, with Scientific Schematics retained as optional proposal-only
  assistance.

### Security

- AI-generated schematics and AI quality scores cannot approve scientific
  accuracy or figure promotion.
- Unsafe paths, undeclared or mismatched artifacts, and unreviewed proposals
  fail closed without weakening the writing gate.
- CP-04 and writing authority are bound to an immutable non-empty figure gate;
  stale PDFs, empty inventories, alias capability names, and placeholder
  review receipts fail closed.
- CP-01 freezes the exact expected figure IDs (minimum 1 arxiv, 4 conference,
  6 journal-q1); omitted or unexpected inventory entries cannot pass.

## [0.13.0] - 2026-07-23

### Added

- Frozen acceptance profiles covering the exact seven T008 fault scenarios,
  planned soak duration, required session restarts, and allowed claim kinds.
- Evidence-bound fault and session completion receipts that reject duplicate
  transitions, lost accepted evidence, excess overlap, unauthorized recovery,
  insufficient restarts, or insufficient measured duration.
- Claim validation that caps duration at the measured interval and enforces
  minimum evidence for 24h and 7×24 labels.
- A production-path acceptance regression executing all seven faults and a
  real multi-process/session bounded soak.

### Limitations

- The committed evidence validates bounded fault and restart behavior, not
  24-hour, 7×24, or full-cutover stability. Those labels remain mechanically
  rejected by the shipped profile and claim gate.

## [0.12.0] - 2026-07-23

### Added

- Two-stage episode-to-audited-memory and memory-to-proposal promotion with
  identical replay, held-out/regression validation, and independent audits at
  both boundaries.
- Skill-defect versus execution-lapse diagnosis, persistent rejected receipts,
  and a registry preventing rejected identical proposal bytes from returning
  as unreviewed novelty.
- Proposal-bound `authorize_evaluator_change` human actions.

### Security

- Learning receipts are proposal-only and explicitly carry no application
  authority. No command automatically edits skills, policy, specs, or
  evaluators.
- Learning gate evidence and auditor identity are excluded from worker-owned
  namespaces; evaluator proposals require an applied authenticated human
  receipt bound to the exact bytes.

## [0.11.0] - 2026-07-23

### Added

- Immutable controller-owned evaluator, evidence, and metric-contract
  snapshots that remove production admission from worker-owned namespaces.
- Replayed scientific-acceptance receipts binding canonical execution,
  candidate, evidence, frozen comparison, derived verdict, and current
  unattended evaluator admission.
- Deterministic `goal_drift` and `evaluator_integrity` detection, exact-once
  counters, and isolated pause/rebaseline or revoke/re-admit routes.

### Changed

- Candidate evaluation transparently rebinds hash-matching CP-02 inputs to the
  canonical controller snapshot.
- Normal writing authorization consumes a scientific-acceptance receipt rather
  than trusting a stored PASS field alone.

## [0.10.0] - 2026-07-23

### Added

- Capsule-bound MiniMax production dispatch with exact task-contract,
  purpose-bearing input-manifest, state-revision, promotion, and durable
  evidence correlation.
- Durable Codex checkpoint request derivation from the canonical capsule and
  exact checkpoint evidence-role profile.
- Exact-once controller commits that admit only immutable worker promotion or
  frontier dependent-transition receipts into the durable work-unit loop.
- Closed production transport regressions for both worker and frontier paths.

### Changed

- The production procedure no longer reconstructs worker or frontier context
  from conversation history. Generic frontier request creation remains for
  non-durable gates such as initial CP-01 approval.
- Codex advice remains read-only and cannot directly complete a durable task;
  only the deterministic controller's applied transition receipt is evidence.

## [0.9.0] - 2026-07-23

### Added

- A launchd-backed, session-independent production trigger with durable
  registration/unregistration receipts, generation-bound tick leases,
  duplicate suppression, missed-tick reconciliation, and crash recovery.
- Immutable canonical plan revisions, append-only transition/evidence chains,
  rebuildable objective/phase/evidence/blocker/approval/next-action
  projections, general dependency-driven work selection, and fresh hash-bound
  context capsules.
- Metadata-only Guardian observations with closed schemas, deterministic
  controller recovery policies, and validation of pre-authorized lifecycle
  receipts.
- Executable evaluator admission for unattended conference/journal plans,
  binding evaluator class and authority, immutable inputs, validation
  identity, identical replay, passing regression, allowed search space,
  complexity policy, and exact durable-plan evaluator identity.

### Changed

- A file-backed schedule no longer counts as a production trigger; external
  scheduler acceptance is required before a registration receipt is written.
- Unattended conference/journal registration, tick execution, graph advance,
  and work-unit result application now fail closed without current evaluator
  admission and revalidate the complete admission chain on every boundary.
- The closed M1 conformance workflow remains unchanged and distinct from the
  production state-driven loop. Fault injection and multi-session soak remain
  cutover acceptance work.

### Fixed

- External scheduler bootstrap and applied-tick crash windows now recover
  without duplicate registration, state transition, or tick effect.
- Derived state deletion rebuilds from canonical revisions and chained events;
  evaluator, goal, task, input, state-revision, or admission drift blocks
  result application.

## [0.8.0] - 2026-07-18

### Added

- A Claude Code target-runtime adapter with immutable per-plan MiniMax M3 and
  Codex model policy, bounded structured worker dispatch, and read-only tools.
- A durable `frontier-advisor-v1` bridge for CP-01 through CP-04 with hashed
  context manifests, atomic budget reservation, Codex CLI transport, response
  schema validation, durable state, and idempotent advisory consumption.
- MAVIS-free conformance coverage using fake Claude/Codex executables.
- HMAC-signed, expiring, replay-protected lifecycle, waiver, worker-cancel,
  and cleanup actions with durable audit receipts.
- Frozen evaluator contracts, hash-bound machine verdicts, authenticated
  writing waivers, and CP-04 final-evidence enforcement.
- Typed runtime/scientific failure counters, distinct scientific pivot
  eligibility, worker inspect/wait/message/cancel, file-backed patrol, and
  exact-path owned-resource cleanup.
- Plan/checkpoint/request/context-bound frontier responses, exact-once
  dependent transitions, deadline expiration, restart assertion, and changed
  artifact rejection.

### Changed

- Model-authored rescue verdicts are advisory records only. Forbidden accept,
  override, waiver, or cancellation output is converted to human escalation
  and never sent to a lifecycle command.
- MAVIS is an explicit `--legacy-mavis` compatibility dependency; Claude Code
  is the canonical Harness entry point.
- The shipped `claude-research-conformance-v1` fixture replaces arbitrary
  conformance command lists and resumes PREPARED subprocesses through stable
  runtime operation IDs; it is not the production research trigger.
- CP-02 freezes the audited metric contract; scientific direction identity no
  longer includes candidate bytes; repeated CP-03 decisions have per-request
  receipts; promotion and cleanup have recovery journals.

### Fixed

- PREPARED operation recovery now reaches command-owned pivot, human-action,
  promotion, and cleanup journals; operation-bound retries converge without
  weakening replay or changed-generation rejection.
- Writing-gate consumers revalidate the complete authority chain and exact
  candidate input; declarative evaluator metrics can no longer come from a
  candidate-independent evidence file.
- Stop-only terminal authorization now supports plans with zero eligible
  removable resources while enforcing exact cleanup coverage otherwise.
- Setup messages no longer execute Markdown backticks as shell substitutions.
- Cleanup dry-runs report intended ephemeral resource actions even when the
  corresponding legacy MAVIS file is absent on the test host.

## [0.7.0] - 2026-07-16

### Changed (breaking)

- **CLI → tool migration.** The legacy `mavis` CLI subcommands
  `mavis agent {new,delete,archive,...}`,
  `mavis cron {create,delete,trigger,list,...}`,
  `mavis session {list,compress,archive,...}`,
  `mavis hook {create,delete,list,...}` are removed by the runtime.
  The skill is rewired to:
  - Use the **native `mavis` tool** (`mavis({ command: "agent create", args: {...} })`)
    for agent / cron / session operations. The tool is the only
    supported call form in v0.7.0+.
  - **Direct file writes** for hooks
    (`~/.mavis/hooks/<name>.json.md`), crons
    (`~/.mavis/agents/<agent>/crons/<name>.md`), and watchdog agents
    (`~/.mavis/agents/<name>/agent.md`). The Mavis daemon picks these
    up on its next scan.
  - **Direct file removal** during cleanup. Cron / hook files are
    `rm -f`'d; session and agent directories are moved to
    `~/.mavis/{sessions,agents}/.archived/<name>-<ts>/` for recovery.
- **`mavis team plan abort` → `mavis team plan cancel`.** v0.7.0
  renames the abort verb to `cancel` for consistency with the cancel
  flow used elsewhere. All watchdog and rescue docs are updated.
- **`mavis communication send` deprecated.** v0.7.0 has no direct
  replacement; the watchdog should write a `findings/<ts>.md` summary
  and (for `critical` severity) an `control/escalate_to_human.json`
  signal so the L0 rescue daemon flags it on its next patrol.

### Added

- **Built-in agent safety check** in `cleanup-plan-resources.sh`.
  Agents with a `scripts/` subdir and no `agent.md` (e.g. the `mavis`
  built-in) are refused even when marked `ephemeral=true`. The
  script moves the directory to `~/.mavis/agents/.archived/` instead
  of `rm -rf`'ing it, so a misconfigured manifest can be recovered.
- **Hook filename dual-fallback.** `cleanup-plan-resources.sh` and
  `plan-l0-guard.py` try both `<name>.json.md` (current convention)
  and `<name>` (legacy) when removing or checking hooks. This avoids
  re-introducing the v0.6.0 archive-subcommand bug class for hooks.

### Fixed

- **Test prompt #3** (`tests/test-prompts.json`) — updated expected
  stderr to the new `mavis CLI not found in PATH (needed for
  `mavis team plan ...`)` message, with a v0.7.0+ annotation that the
  script no longer needs the CLI for any other subcommand.
- **FM-1 in `tests/e2e-uav-coverage.md`** — same message update.
- **Cleanup section in `tests/e2e-uav-coverage.md`** — replaces the
  `mavis cron delete` / `mavis hook delete` calls with direct file
  removals; documents the v0.7.0+ contract.
- **Plan-l0-guard health check** — the cron/hook health check no
  longer requires the removed `mavis cron list` / `mavis hook list`
  CLIs. It reads files directly under `~/.mavis/agents/<a>/crons/`
  and `~/.mavis/hooks/`, which is the v0.7.0+ contract.

### Migration recipe for downstream consumers

- Replace `mavis agent new <name> ...` with
  `mavis({ command: "agent create", args: { name: "<name>", system_prompt: "...", display_name: "...", description: "...", persona: "..." } })`.
- Replace `mavis cron create <agent> <name> ...` with a file write to
  `~/.mavis/agents/<agent>/crons/<name>.md` (markdown with
  frontmatter: `name`, `schedule`, `timezone`, `agent`, `session_mode`,
  `keep_sessions`, body=prompt).
- Replace `mavis hook create <name>.json -e <event> ...` with a file
  write to `~/.mavis/hooks/<name>.json.md` (markdown with
  frontmatter: `hookEvent`, `type`, `priority`, `matcher`, `timeout`,
  body=script).
- Replace `mavis cron trigger <agent> <name>` with
  `mavis({ command: "cron trigger", args: { cron_id: "<agent>/<name>" } })`.
- Keep `mavis team plan {status,cancel,resume,decision,run}` — those
  remain a CLI in v0.7.0+.

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
