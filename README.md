<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/logo-light.svg">
    <img alt="Autoresearch Paper" src=".github/logo-light.svg" width="440">
  </picture>
</div>

<div align="center">

[![License: MIT][license-shield]][license-url]
[![Version][version-shield]][repo-url]
[![Agent Skills][skills-shield]][skills-url]

</div>

Autoresearch Paper helps AI researchers keep long-running paper projects
honest: it makes agents prove the algorithm or experiment works before they
start writing.

## Status

- **Current version:** v0.17.2
- **Stability:** Experimental; bounded stage-crossing acceptance target
- **Tier coverage:** `arxiv` (open) · `conference` (gated) · `journal-q1` (gated)
- **Direction:** Claude Code is the canonical Harness entry point. MiniMax M3
  workers, authenticated lifecycle authority, evidence gates, typed patrol,
  owned cleanup, the launchd-backed durable state loop, evaluator admission,
  capsule-bound MiniMax/Codex production transport, replayed scientific
  acceptance, deterministic integrity-failure routing, and two-stage gated
  learning promotion, and bounded seven-fault/multi-session acceptance are
  implemented.
  The packaged `claude-research-conformance-v1` workflow is a closed M1
  conformance fixture: it journals operation IDs and verifies terminal
  evidence, but does not claim to be the production topic-to-paper trigger.
  The production loop now has external registration, tick leases, canonical
  revisions, fresh context capsules, and evaluator-eligibility blocking;
  bounded fault/restart evidence is complete. The scientific-figure path now
  binds source data, transformations, renderer identity, commands, outputs,
  hashes, a figure-stage-frozen expected set, an exact inventory, and
  output-bound human review before writing.
  New staged plans freeze a human-owned optimization contract and exactly one
  first-stage envelope. CP-01 uses the strongest allowed Codex reviewer, while
  the deterministic controller remains authoritative. Each candidate gets one
  logical isolated Gate decision; terminal MiniMax reports receive fresh
  non-M3 review before at most one next stage is compiled.
  v0.17 makes `state/staged_research/v1/` the sole runtime truth;
  `state/progress.json` and `state/research-dossier.md` are rebuildable,
  non-authoritative views. Capacity v2 separates per-stage and global Worker
  limits from STAGE-REVIEW and named checkpoint capacity. An initial signed
  contract may pre-authorize exactly one named next stage, and the controller
  may cross only after the prior stage has a terminal decision, MiniMax report,
  and fresh strongest-policy review. Silence is never approval.
  Observation-only bootstrap stages have an explicit non-Gate terminal path:
  preflight freezes path/hash/symbol/line bindings, the shipped executable
  validator checks the promoted inventory, and the controller records no
  Gate-accepted or reusable evidence before the mandatory strong review.
  Terminal scientific report content remains MiniMax-authored; after the call,
  the controller adds only the otherwise unknowable role-visible provenance
  hash to the canonical report.
  v0.16.2 expands content-addressed review material into the actual CP-01
  audit context, rejects underfunded multi-call policies, and uses a real
  Claude-to-first-work-unit run as field acceptance. It rejects unavailable
  Claude executables and non-UTF-8 sources before budget mutation and reserves
  dispatch/scientific capacity under one controller lock. v0.16.1 added typed negative frontier
  advice, conservative unknown-usage charging, fail-fast stage-review routing,
  and signed prospective capacity grants without refunding launched calls.
  v0.17 claims only a bounded stage-crossing capability and acceptance target:
  one first-stage-terminal to second-stage-Worker-start crossing. It does not
  claim second-stage completion, scientific success, 24h or 7×24 stability,
  production readiness, or full cutover.
  MAVIS is available only as explicit legacy compatibility. See
  [`skills/autoresearch-paper/references/claude-code-runtime.md`](skills/autoresearch-paper/references/claude-code-runtime.md), the design notes in
  [`docs/evolution/design-review-2026-06-26.md`](docs/evolution/design-review-2026-06-26.md)
  and forward-looking plans in [`docs/ROADMAP.md`](docs/ROADMAP.md).
- **Maintenance:** issues and PRs welcome; major refactors land in
  feature branches first.

## Table of Contents

1. [Why](#why)
2. [Features](#features)
3. [Quick Start](#quick-start)
4. [Architecture](#architecture)
5. [When To Use](#when-to-use)
6. [Install](#install)
7. [Dependencies](#dependencies)
8. [Usage](#usage)
9. [Workflow](#workflow)
10. [Repository Layout](#repository-layout)
11. [FAQ](#faq)
12. [Boundaries](#boundaries)
13. [Contributing](#contributing)
14. [Tests](#tests)
15. [Changelog](#changelog)
16. [Citation](#citation)
17. [License](#license)

## Why

Long-running AI research runs often fail in the same way: agents explore for
hours, lose the thread, retry the same weak direction, then write an honest
paper about a near-zero contribution. Autoresearch Paper makes that failure
visible and recoverable with evaluator freeze, research acceptance gates,
heartbeat watchdogs, and manifest-driven cleanup.

## Features

- Blocks writing until the research gate passes or the human owner waives it.
- Tracks failed directions so agents pivot structurally instead of repeating
  the same dead end.
- Separates runtime stalls from scientific no-improvement using typed failures.
- Requires a plan-bound, independently registered L0/L1/L2 assurance closure
  before any unattended durable Worker can start.
- Requires signed, expiring, replay-protected pause, resume, stop, waiver,
  worker cancellation, and cleanup actions.
- Removes only exact-path, token-bound, plan-owned ephemeral resources.
- Verifies paper packages with artifact-only reviewer checks, not producer
  self-claims.
- Dispatches schema-bounded MiniMax M3 workers through Claude Code and reserves
  a frozen budget before sparse Codex checkpoint audits.
- Registers a session-independent launchd trigger with exactly-one tick claims,
  rebuildable canonical state, and fresh hash-bound task capsules.
- Treats `state/staged_research/v1/` as the only staged runtime authority and
  uses `rebuild-staged-projections` to rebuild `state/progress.json` plus
  `state/research-dossier.md` as disposable operator projections.
- Blocks unattended conference/journal autonomy until evaluator authority,
  replay, regression, immutable inputs, search space, and complexity policy
  pass executable admission; any identity drift revokes eligibility.

## Quick Start

```text
/autoresearch-paper — turn a research brief into a gated paper pipeline.
/autoresearch-paper status — inspect a running plan and its watchdog state.
/autoresearch-paper stop — stop the controller and report exact residual resources.
```

## Architecture

The target control plane is Claude Code, with a deterministic file-backed
controller between model output and formal plan state. Legacy MAVIS resources
are compatibility-only. The research flow is:

```
Claude Code control plane
        │
        ▼
deterministic controller ── canonical staged/durable state ── evidence ledger
        │
        ├── L0 launchd health supervisor (health-only, zero model calls)
        ├── L1 launchd durable work trigger (leases + state advance)
        └── L2 controller Worker heartbeat receipts
                │
                ├── MiniMax/Claude Worker proposals
                └── sparse Codex checkpoints + independent retry lineage
```

L0, L1, and L2 are bound by one immutable activation receipt but keep distinct
scheduler/command identities. Legacy Mavis cron, `plan-l0-guard.py`, and
`last_seen.jsonl` remain compatibility artifacts rather than activation proof.

**Research gate (T6.1/T6.2):** The controller binds evaluator, evidence,
threshold, candidate, and measured verdict hashes. Bare PASS text is rejected.
Conference and journal writing additionally require an applied CP-04 final
evidence audit; waivers are signed human records.

**Unattended autonomy gate:** Conference and journal-q1 durable triggers cannot
register or advance without a current evaluator-admission receipt. The
controller revalidates authority, replay, regression, inputs, search space,
complexity policy, and exact evaluator identity on every autonomy boundary.

**Resource manifest:** Every target-owned removable resource is recorded in
`resource_manifest.json` with an exact path, ownership nonce, and scope.
Cleanup requires an authenticated receipt and refuses shared or escaping paths.

**Pause / resume:** Both actions require a signed, expiring, replay-protected
human record. The deterministic controller writes canonical receipts and keeps
the durable plan state available across Claude sessions.

**Bounded staged continuation:** Capacity v2 keeps the active stage's Worker
quota, the plan-global Worker allowance, terminal `STAGE-REVIEW`, and
CP-01/CP-02/CP-04 (optionally CP-03) in separate non-transferable classes. A
frontier top-up never increases Worker capacity. If the initial signed
`authorize_contract` names exactly one next stage, `advance-staged-research`
may derive one bound continuation receipt after terminal decision/report/review
evidence and start exactly one Worker for that next stage. No response or
operator silence counts as approval.

For the deeper plan structure, see
[`skills/autoresearch-paper/SKILL.md`](skills/autoresearch-paper/SKILL.md).

## When To Use

Use this when you have a research idea, a target venue, and enough material
or infrastructure to define an evaluator. Do not use it for one-off drafts,
blog posts, slide decks, or camera-ready submission automation.

## Install

Primary install path:

```bash
npx skills add WdBlink/autoresearch-paper -g
```

Upgrade copied installations to v0.17.2 with a full bundle refresh so the
runtime and response schema move together:

```bash
npx skills add WdBlink/autoresearch-paper -g --copy
```

Then verify local runtime dependencies from the installed skill directory:

```bash
scripts/setup.sh
```

Install the focused scientific figure capability at the audited upstream
revision. Do not install the complete collection merely for this workflow:

```bash
gh skill install K-Dense-AI/scientific-agent-skills \
  scientific-visualization \
  --pin 70a0d595e54b8d92ca54f216d4315e0ab8c7d967 \
  --agent claude-code --scope user

# Repeat only when Codex does not share the Claude/user skill directory.
gh skill install K-Dense-AI/scientific-agent-skills \
  scientific-visualization \
  --pin 70a0d595e54b8d92ca54f216d4315e0ab8c7d967 \
  --agent codex --scope user
```

`scientific-schematics` is optional and proposal-only. If installed, it may
draft method or architecture diagrams, but neither its generated image nor an
AI quality score passes the repository-owned figure gate.

For a project-level install, omit `-g`:

```bash
npx skills add WdBlink/autoresearch-paper
```

### Legacy Mavis Runtime Registration

This skill can be invoked from Agent Skills-compatible runtimes after `npx`
install. The target worker and frontier-advisor path does not require MAVIS.
Old watchdog agent, cron, hook, and cleanup fixtures require it only when the
caller explicitly selects the legacy compatibility path.

If your Mavis build does not scan Agent Skills directories, register the
installed source directory into your Mavis skill root as a symlink or copy.
Keep one source of truth; avoid maintaining a stale manual copy.

## Dependencies

`scripts/setup.sh` checks the runtime surface and blocks with repair
instructions if anything required is missing.

| Dependency | Why it is needed |
|---|---|
| Claude Code | primary Harness host and MiniMax M3 dispatch |
| Mavis CLI | optional legacy team-plan/watchdog compatibility |
| Python 3 | bundled guards, cleanup, tests |
| Codex CLI | registered sparse frontier-advisor checkpoints |
| Node.js / npx | GitHub skill installation |
| Scientific Visualization skill | focused deterministic publication-figure guidance and helpers |
| Scientific Schematics skill | optional proposal-only method-diagram generation; never acceptance authority |
| jq | JSON validation during checks |
| launchctl | macOS launchd L0 rescue mode |
| pdflatex + bibtex | LaTeX package verification |
| pdftotext | rendered PDF marker checks |

## Usage

```text
/autoresearch-paper

Topic: energy-aware UAV swarm coverage under wind disturbance.
Target: ICRA 2027.
Materials: PDFs and simulator notes in a local folder.
```

The skill asks for missing fields, confirms the tier, shows a readable plan
preview, and only starts the controller after an explicit "go".

During a run:

| Command | Action |
|---|---|
| `/autoresearch-paper status` | show plan progress, research gate, stale count, and resource health |
| `/autoresearch-paper pause` | soft-pause through `control/pause_requested.json` |
| `/autoresearch-paper resume` | resume and verify/repair watchdog resources |
| `/autoresearch-paper stop` | stop the controller and report residual resources |
| `/autoresearch-paper cleanup` | apply one approved receipt per owned resource |
| `/autoresearch-paper rescue-status` | show L0/watchdog health and rescue history |

## Workflow

| Stage | What happens |
|---|---|
| Brief | parse topic, target venue, and materials |
| Tier | choose `arxiv`, `conference`, or `journal-q1` with fallback confirmation |
| Plan | generate `plan.yaml` from tier templates and prompt assets |
| Bootstrap | freeze model policy and create controller, evaluator, failure, and ownership state |
| Run | dispatch bounded MiniMax M3 tasks through the Claude Code controller |
| Frontier audit | reserve budget, send a registered checkpoint to Codex, validate, then record controller consumption |
| Patrol | file-backed target patrol and `last_seen.jsonl` detect runtime stalls |
| Research Gate | T6.1/T6.2 record hash-bound PASS/FAIL evidence or authenticated waiver |
| Figure Gate | v0.16 freezes expected IDs only when the controller authorizes the figure-production stage; T6.4 binds exact manifests, outputs, and human reviews (legacy v0.15 CP-01 receipts retain their historical timing) |
| Deliver | produce `paper.tex`, bibliography, figures, readiness report, next steps |
| Cleanup | stop reports residuals; each deletion consumes a scoped receipt |

## Repository Layout

```
autoresearch-paper/
├── README.md
├── skills/
│   └── autoresearch-paper/
│       ├── SKILL.md
│       ├── scripts/
│       │   └── setup.sh
│       ├── assets/
│       │   ├── task-prompt-snippets.md
│       │   └── first-action-last-seen-hook.md
│       ├── references/
│       │   ├── goal-keywords.md
│       │   ├── tier-decision-tree.md
│       │   ├── plan-template-arxiv.md
│       │   ├── plan-template-conference.md
│       │   ├── plan-template-journal-q1.md
│       │   ├── task-prompt-snippets.md
│       │   ├── research-state-contract.md
│       │   ├── lifecycle-contract.md
│       │   ├── claude-code-runtime.md
│       │   ├── frontier-response.schema.json
│       │   ├── figure-artifact.schema.json
│       │   ├── figure-requirements.schema.json
│       │   ├── scientific-figure-pipeline.md
│       │   ├── watchdog-prompt-template.md
│       │   ├── first-action-last-seen.md
│       │   ├── reviewer-readiness-rubric.md
│       │   ├── bootstrap-watchdog.sh
│       │   ├── launchd/
│       │   └── scripts/
│       │       └── harness-runtime.py
│       └── tests/
└── docs/
```

## FAQ

**Q: Can I run it on Codex CLI or Claude Code without Mavis?**
A: Yes. Policy, bounded MiniMax M3 workers, CP-01–CP-04 Codex gates,
authenticated lifecycle actions, the durable trigger/state loop, evaluator
admission/verdicts, patrol, and owned cleanup all run without MAVIS. Pass
`--legacy-mavis` only for an old compatibility fixture.

**Q: The research gate rejected my run. Can I waive it?**
A: Yes, with an expiring HMAC-signed `waive_acceptance` record. A Markdown
string cannot waive the gate. Negative-result waiver is arxiv-only.

**Q: What if the watchdog keeps reporting stalls?**
A: Check `last_seen.jsonl` and the L0 corruption guard output. Common
causes: a worker task exceeded the 30-minute ceiling, the plan dir
moved, or the JSONL is being written outside the plan dir. The rescue
daemon (`references/scripts/plan-rescue-daemon.py`) is the entry point
for diagnosis.

**Q: Does the skill write the final paper?**
A: It produces a structured paper draft and evidence bundle. It does not
submit to venues, does not promise a camera-ready PDF, and does not
replace human authorship of novel claims. See [Boundaries](#boundaries).

**Q: How is cleanup different from stop?**
A: `stop` changes controller status and reports residuals; it does not grant
aggregate deletion authority. `cleanup` removes only individually approved,
owned resource generations. Neither deletes paper outputs.

## Boundaries

The skill produces a structured paper draft and evidence bundle. It does
not submit to venues, does not promise a camera-ready PDF, and does not
replace human authorship of novel claims. If the topic has no measurable
evaluator, the skill downgrades to `arxiv` or stops for clarification.

## Contributing

Run `scripts/setup.sh test` before opening a pull request. Changes that touch
watchdog, L0, cleanup, or research gate behavior should add or update runtime
contract tests under `tests/`.

## Tests

```bash
cd skills/autoresearch-paper
scripts/setup.sh test
```

The test path runs contract validation, exhaustive runtime unit/negative tests,
and a complete no-MAVIS fake-Claude/fake-Codex integration flow.

## Changelog

Per-version notes live in
[`skills/autoresearch-paper/SKILL.md#versioning`](skills/autoresearch-paper/SKILL.md#versioning).
Quick highlights:

- **Unreleased** — adds typed provider-quota recovery and exact-once logical
  retry lineages for named checkpoints. Adds the Claude-native runtime
  assurance closure: independent launchd L0 and L1 services, controller-owned
  L2 Worker heartbeats, interval validation, activation/test receipts, and
  health-only L1 recovery with zero model calls. A separate least-authority
  trigger can resume a due initial CP-01 quota retry before L1 admission.
- **v0.17.2** — closes the remaining real Plan021 CP-01 findings: validator
  schema versions require JSON integers rather than booleans, and a Worker
  cannot pre-author Controller-owned role-visible provenance. Frozen source
  inventory and stage-report conformance suites now contain twelve and ten
  cases respectively; the former proves the actual CLI receipt path. Plan021
  and Plan022 remain immutable negative evidence; the field
  gate requires a fresh plan and fresh real review. A pre-authorization
  `prepare-staged-research` pass now closes the Plan024 hash/receipt loop before
  any owner signature is created. Observation preflight also records exact
  Runtime path/hash, byte identity, and the ten-case conformance result for the
  terminal report validator, closing Plan025's sole CP-01 finding. The Worker
  output contract also preserves exact source `symbol`/`line_start` bindings
  separately from the generic input manifest, closing the Plan026 field defect
  where a valid inventory was rejected before content validation.
- **v0.17.1** — explicitly inactive observation-only evaluation profiles and
  a CP-01-frozen, conformance-tested terminal-report validator close the
  execution-contract gaps found by real GPT-5.6 CP-01 field review. The
  six-role terminal review sees candidate, decision, and validation evidence;
  only an exact strongest-model `accept` may start the authorized next Worker.
  Older three-role terminal-review packets fail closed and require a fresh
  versioned stage/review path.
- **v0.17.0** — sole-authority staged state with rebuildable projections,
  capacity v2 class isolation, and one idempotent, explicitly pre-authorized
  stage crossing through the start of one next-stage Worker. The isolated
  Codex surface now disables multi-agent features without the obsolete
  `agents.enabled=false` override, and an unattended Claude controller must be
  explicitly pre-authorized rather than relying on `auto` permission prompts.
  Observation-only Stage 1 now has a deterministic non-Gate terminal route,
  exact source symbol/line selection, an executable receipt-producing
  validator, and independent plan-local/Runtime byte-identity evidence.
  Canonical stage reports also remove a real-call circular dependency by
  allowing the controller to inject only the completed Worker's role-visible
  hash into otherwise unchanged MiniMax-authored content.
  Legacy capacity v1 retains existing-plan lifecycle/replay compatibility but
  cannot use automatic stage crossing. No second-stage completion, scientific
  success, long-soak, production-readiness, or full-cutover claim is made.
- **v0.16.2** — field-loop recovery for substantive CP-01 evidence closure,
  aggregate frontier-budget admission, isolated single-reviewer Codex
  transport, external read-only Worker inputs, disclosed closed evaluators,
  and a real first-work-unit acceptance artifact.
- **v0.16.1** — field recovery for frontier response/usage classification,
  a measured ChatGPT reservation floor, signed append-only capacity top-ups,
  content-addressed stage material, and deterministic CP-01/STAGE-REVIEW
  routing. No launched-call refund or apply-time capsule synthesis is added.
- **v0.16.0** — bounded rolling stages, exact role-visible-state records,
  non-fungible CP-01/02/04 capacity, separately budgeted Gate transport
  retries, accept/reject/escalate evidence, fresh terminal strong review, and
  figure-inventory freeze at the authorized figure-production stage.
- **v0.15.0** — MiniMax M3 may draft the top-level research plan, but Codex
  `gpt-5.6-sol` at `ultra` must independently accept the exact CP-01 evidence
  bundle before any worker dispatch; reviewer identity and policy hash remain
  revalidated by downstream consumers.
  The author family is controller-declared provenance, not cryptographic model
  attestation.
- **v0.14.1** — frontier preflight before budget reservation, strict response
  schema compatibility, Git-safe HTTPS-only Codex routing, durable transport
  event streaming, and conservative accounting for uncertain sends. See the
  [CP-01 incident report](skills/autoresearch-paper/references/frontier-transport-incident-2026-07-25.md).
- **v0.14.0** — source-bound scientific figure manifests, offline path/hash
  validation, post-KEEP pre-writing gates, focused Scientific Visualization
  integration, and optional proposal-only Scientific Schematics.
- **v0.13.0** — seven production fault scenarios, multi-session soak evidence,
  and claim gates bounded to the measured interval; no 24h/7×24 claim.
- **v0.12.0** — audited episode memory, defect-versus-lapse diagnosis,
  replay/regression-gated proposal receipts, and human-only evaluator proposals.
- **v0.11.0** — controller-owned evaluator snapshots, replayed scientific
  acceptance, and isolated goal/evaluator integrity failure routing.
- **v0.10.0** — capsule-bound MiniMax dispatch and Codex request derivation,
  with controller-only exact-once durable result commits.
- **v0.9.0** — launchd-backed durable trigger, generation-bound tick leases,
  canonical plan revisions, fresh context capsules, metadata-only Guardian,
  and executable evaluator admission for unattended conference/journal plans.
- **v0.8.0** — Claude Code target cutover with authenticated human actions,
  hash-bound evaluator and CP-01–CP-04 gates, typed failures, target patrol and
  owned cleanup, plus no-MAVIS end-to-end conformance.
- **v0.7.0** — CLI → tool migration. The legacy
  `mavis agent|cron|session|hook|archive` CLI subcommands are removed by
  the runtime; the skill is rewired to use the native `mavis` tool
  (agent/cron/session) and direct file writes for hooks
  (`~/.mavis/hooks/...`). Only `mavis team plan ...` remains a CLI
  (with the v0.7 rename `abort` → `cancel`). `mavis communication send`
  is marked deprecated.
- **v0.6.0** — Agent Skills monorepo layout (`npx skills add` support),
  cleanup-script subcommand fix, full test bundle under `tests/`.
- **v0.4.0** — Platform-portable daemon pattern (no Linux `setsid`
  dependency), producer discipline, model preload for in-process NN
  pipelines.
- **v0.3.1** — V6 evidence-driven optimization rounds (verifier
  spot-check, 0% framing recipe, wide-table camera-ready fix).
- **v0.3.0** — Rescue Layer (L0 guard, watchdog daemon, abort gate,
  workspace isolation) and three failure-mode FMs.
- **v0.2.0** — Three-tier plan templates and heartbeat contract.

For the complete history, see the git log of
`skills/autoresearch-paper/SKILL.md`.

## Citation

If this skill contributed to a paper or research artifact, you can cite the
release as:

```bibtex
@software{autoresearch_paper,
  title  = {Autoresearch Paper: A Research-First Brief-to-Paper Pipeline
            with Evaluator Freeze and Heartbeat Watchdog},
  author = {WdBlink},
  year   = {2026},
  url    = {https://github.com/WdBlink/autoresearch-paper},
  version = {0.17.2}
}
```

## License

MIT

Forged with [Skill Forge](https://github.com/motiful/skill-forge) · Crafted with [Readme Craft](https://github.com/motiful/readme-craft)

[license-shield]: https://img.shields.io/github/license/WdBlink/autoresearch-paper.svg
[license-url]: https://github.com/WdBlink/autoresearch-paper/blob/main/LICENSE
[version-shield]: https://img.shields.io/badge/version-0.17.2-CC785C
[repo-url]: https://github.com/WdBlink/autoresearch-paper
[skills-shield]: https://img.shields.io/badge/Agent%20Skills-compatible-2f6f8f
[skills-url]: https://skills.sh/
