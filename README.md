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

## What It Does

```
brief -> tier -> T0 evaluator -> method/experiment loop -> research gate -> paper
                         |
                         v
              L0/L1/L2 heartbeat + manifest cleanup
```

The skill is for multi-hour or multi-day research runs, not single-pass
drafting. For `conference` and `journal-q1` tiers, writing is blocked until
`state/research_acceptance.md` records `PASS` or `WAIVED_BY_HUMAN`.

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
├── SKILL.md
├── README.md
├── scripts/
│   └── setup.sh
├── assets/
│   ├── task-prompt-snippets.md
│   └── first-action-last-seen-hook.md
├── references/
│   ├── goal-keywords.md
│   ├── tier-decision-tree.md
│   ├── plan-template-arxiv.md
│   ├── plan-template-conference.md
│   ├── plan-template-journal-q1.md
│   ├── task-prompt-snippets.md
│   ├── research-state-contract.md
│   ├── lifecycle-contract.md
│   ├── watchdog-prompt-template.md
│   ├── first-action-last-seen.md
│   ├── reviewer-readiness-rubric.md
│   ├── bootstrap-watchdog.sh
│   ├── launchd/
│   └── scripts/
└── tests/
```

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
scripts/setup.sh test
```

The test path runs contract validation and unit tests for research gates,
L0 dry-run behavior, plan-dir resolution, stop/cleanup JSON escaping, and
manifest-based resource cleanup.

## License

MIT

Forged with [Skill Forge](https://github.com/motiful/skill-forge) · Crafted with [Readme Craft](https://github.com/motiful/readme-craft)

[license-shield]: https://img.shields.io/github/license/WdBlink/autoresearch-paper.svg
[license-url]: https://github.com/WdBlink/autoresearch-paper/blob/main/LICENSE
[version-shield]: https://img.shields.io/badge/version-0.6.0-CC785C
[repo-url]: https://github.com/WdBlink/autoresearch-paper
[skills-shield]: https://img.shields.io/badge/Agent%20Skills-compatible-2f6f8f
[skills-url]: https://skills.sh/
