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

- **Current version:** v0.7.0 (Mavis-native, macOS / Linux; CLI → tool migration)
- **Stability:** Production for personal use, early for shared plans
- **Tier coverage:** `arxiv` (open) · `conference` (gated) · `journal-q1` (gated)
- **Direction:** the orchestrator currently depends on the Mavis plan
  engine; portable-runtime support (Codex / Claude Code adapter) is
  on the planning board but not scheduled. See the design notes in
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
- Runs L0/L1/L2 heartbeat checks across launchd, Mavis cron, and per-task
  `last_seen.jsonl`.
- Keeps pause, resume, stop, and cleanup state in the plan directory.
- Cleans ephemeral agents, crons, hooks, locks, and background processes from
  a `resource_manifest.json`.
- Verifies paper packages with artifact-only reviewer checks, not producer
  self-claims.

## Quick Start

```text
/autoresearch-paper — turn a research brief into a gated paper pipeline.
/autoresearch-paper status — inspect a running plan and its watchdog state.
/autoresearch-paper stop — cancel when possible and clean runtime resources.
```

## Architecture

The skill is a thin orchestrator on top of a Mavis plan engine. Five
components collaborate end-to-end:

```
┌──────────────────────────────────────────────────────────────────┐
│  Brief  →  Tier  →  Plan  →  Bootstrap  →  Run  →  Deliver      │
│  LLM     arxiv/   YAML     watchdog     team     paper.tex        │
│          conf/    gen      agent        plan     + bib + figs    │
│          j-q1     (T0)     + cron       (T1-T8)  + readiness     │
│                   evaluator + hook                                │
└──────────────────────────────────────────────────────────────────┘
                                    │
                ┌───────────────────┼───────────────────┐
                ▼                   ▼                   ▼
         L0 guard (fs)      L1 hourly (cron)    L2 per-task (JSONL)
         filesystem         watchdog agent      last_seen.jsonl
         corruption         stall detection     producer liveness
         check
```

**Research gate (T6.1/T6.2):** A `KEEP / DISCARD / PIVOT / WAIVE` verdict is
written to `state/research_acceptance.md`. For `conference` and `journal-q1`
tiers, the writing stage (T7) refuses to start unless the verdict is `KEEP`
or `WAIVED_BY_HUMAN`. This is the lever that prevents the "explore for hours,
write a near-zero paper" failure mode.

**Resource manifest:** Every ephemeral resource (agent, cron, hook, lock,
background process) is recorded in `state/resource_manifest.json`. On stop,
complete, or abort, `cleanup-plan-resources.sh` walks this manifest so
nothing leaks across plans.

**Pause / resume:** Pause writes a sentinel file; the next L1 tick stops
issuing new subagent tasks but keeps the plan state and watchdog alive.
Resume re-runs the bootstrap self-check to repair any drift.

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

Then verify local runtime dependencies from the installed skill directory:

```bash
scripts/setup.sh
```

For a project-level install, omit `-g`:

```bash
npx skills add WdBlink/autoresearch-paper
```

### Mavis Runtime Registration

This skill can be invoked from Agent Skills-compatible runtimes after `npx`
install. Full autonomous execution also requires the Mavis runtime because
the plan engine, watchdog agent, cron, and hook APIs are Mavis-specific.

If your Mavis build does not scan Agent Skills directories, register the
installed source directory into your Mavis skill root as a symlink or copy.
Keep one source of truth; avoid maintaining a stale manual copy.

## Dependencies

`scripts/setup.sh` checks the runtime surface and blocks with repair
instructions if anything required is missing.

| Dependency | Why it is needed |
|---|---|
| Mavis CLI | team plans, agents, cron, hooks |
| Python 3 | bundled guards, cleanup, tests |
| Codex CLI | optional local-LLM rescue judge |
| Node.js / npx | GitHub skill installation |
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
preview, and only starts the Mavis team after an explicit "go".

During a run:

| Command | Action |
|---|---|
| `/autoresearch-paper status` | show plan progress, research gate, stale count, and resource health |
| `/autoresearch-paper pause` | soft-pause through `control/pause_requested.json` |
| `/autoresearch-paper resume` | resume and verify/repair watchdog resources |
| `/autoresearch-paper stop` | cancel when possible and run manifest cleanup |
| `/autoresearch-paper cleanup` | clean runtime resources without deleting outputs |
| `/autoresearch-paper rescue-status` | show L0/watchdog health and rescue history |

## Workflow

| Stage | What happens |
|---|---|
| Brief | parse topic, target venue, and materials |
| Tier | choose `arxiv`, `conference`, or `journal-q1` with fallback confirmation |
| Plan | generate `plan.yaml` from tier templates and prompt assets |
| Bootstrap | create watchdog agent, cron, hook, state, and `resource_manifest.json` |
| Run | start `mavis team plan run` and register the plan id |
| Patrol | L0 guard, hourly watchdog, and `last_seen.jsonl` detect stalls |
| Research Gate | T6.1/T6.2 decide KEEP, DISCARD, PIVOT, or waiver |
| Deliver | produce `paper.tex`, bibliography, figures, readiness report, next steps |
| Cleanup | stop/complete/abort runs `cleanup-plan-resources.sh` |

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
│       │   ├── watchdog-prompt-template.md
│       │   ├── first-action-last-seen.md
│       │   ├── reviewer-readiness-rubric.md
│       │   ├── bootstrap-watchdog.sh
│       │   ├── launchd/
│       │   └── scripts/
│       └── tests/
└── docs/
```

## FAQ

**Q: Can I run it on Codex CLI or Claude Code without Mavis?**
A: Partially. The skill installs cleanly on any Agent Skills-compatible
runtime, and the brief → plan → T0 evaluator path works. The autonomous
run loop (T1–T8 with watchdog cron, hooks, and pause/resume) requires the
Mavis plan engine. A portable-runtime abstraction is on the wishlist
(see [Status](#status) for design notes) but not scheduled.

**Q: The research gate rejected my run. Can I waive it?**
A: Yes. `journal-q1` and `conference` tiers block writing without a `KEEP`
or `WAIVED_BY_HUMAN` verdict in `state/research_acceptance.md`. Set the
verdict explicitly; do not bypass silently. The skill logs the waiver
author, reason, and timestamp so reviewers can audit it.

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
A: `stop` cancels the plan and runs cleanup together. `cleanup` runs the
manifest-driven resource teardown without cancelling — useful when a
plan is in an unrecoverable state but you want to free the runtime
resources before restarting.

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

The test path runs contract validation and unit tests for research gates,
L0 dry-run behavior, plan-dir resolution, stop/cleanup JSON escaping, and
manifest-based resource cleanup.

## Changelog

Per-version notes live in
[`skills/autoresearch-paper/SKILL.md#versioning`](skills/autoresearch-paper/SKILL.md#versioning).
Quick highlights:

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
  version = {0.7.0}
}
```

## License

MIT

Forged with [Skill Forge](https://github.com/motiful/skill-forge) · Crafted with [Readme Craft](https://github.com/motiful/readme-craft)

[license-shield]: https://img.shields.io/github/license/WdBlink/autoresearch-paper.svg
[license-url]: https://github.com/WdBlink/autoresearch-paper/blob/main/LICENSE
[version-shield]: https://img.shields.io/badge/version-0.7.0-CC785C
[repo-url]: https://github.com/WdBlink/autoresearch-paper
[skills-shield]: https://img.shields.io/badge/Agent%20Skills-compatible-2f6f8f
[skills-url]: https://skills.sh/
