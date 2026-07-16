---
name: autoresearch-paper
description: Turn a paragraph-level research brief into a research-first autonomous paper pipeline. Use when the user wants "帮我把这个课题写成论文", "autoresearch 写 paper", "先把算法做出来再写论文", or a multi-hour/multi-day Mavis plan with evaluator freeze, implementation/experiment loop, research acceptance gate, L0/L1/L2 heartbeat, pause/resume/stop, and manifest cleanup. Targets Mavis / MiniMax Code environments where the runtime exposes the native `mavis` tool (agent / cron / session / team plan) and direct hook files under `~/.mavis/hooks/` — the legacy `mavis agent|cron|session|hook` CLI subcommands are removed.
license: MIT
metadata:
  short-description: Research-first brief-to-paper pipeline with heartbeat and cleanup
  version: "0.7.0"
---

# Autoresearch Paper

Run a research-first paper pipeline from a short brief. The skill creates
an evidence-anchored plan, freezes the evaluator before method work,
blocks writing until research evidence passes or is explicitly waived,
and manages watchdog, resume, stop, and cleanup resources through
file-backed state.

## Safety Rules

- Never spawn Mavis agents, cron jobs, hooks, or launchd jobs before the
  user confirms both tier and plan preview.
- Never auto-abort. Watchdog and L0 findings are advisory until the user
  confirms a destructive action.
- Never start writing for `conference` or `journal-q1` until
  `state/research_acceptance.md` contains `PASS` or `WAIVED_BY_HUMAN`.
- Never create one permanent team member per retry, direction, section, or
  iteration. Stable roles are enough; temporary workers must be marked
  `ephemeral=true` in `resource_manifest.json`.
- Never end stop/abort/complete without running
  `cleanup-plan-resources.sh` or reporting exact residual resources.

## Execution Procedure

```
run_autoresearch_paper(user_request) -> delivered_or_running_plan

run scripts/setup.sh
brief = collect_brief(user_request)
tier = decide_tier(brief.target_venue, references/goal-keywords.md, references/tier-decision-tree.md)
show tier, task count, estimated agents, wall-clock -> require explicit confirmation
plan_dir = create_plan_dir_and_state(brief, tier)
task_graph = generate_plan_yaml(
    references/plan-template-<tier>.md,
    references/task-prompt-snippets.md,
    assets/task-prompt-snippets.md,
    references/research-state-contract.md,
    references/lifecycle-contract.md
)
show human-readable plan preview + watchdog config -> require explicit "go"
write watchdog-system-prompt.md from references/watchdog-prompt-template.md
run references/bootstrap-watchdog.sh <topic-slug> <tier> <plan-dir> [--rescue if accepted]
run mavis team plan run --plan <plan-dir>/plan.yaml
register plan id with references/scripts/register-plan-id.py
while plan is running:
    observe mavis team plan status + last_seen.jsonl + state/progress.json + l0/watchdog health
    honor status, pause, resume, stop, cleanup, rescue-status commands
    surface watchdog/L0 findings without destructive action
on finish or user stop:
    run cleanup-plan-resources.sh
    deliver paper paths, reviewer-readiness, watchdog summary, cleanup report
```

## When To Use

Use this skill when the user wants a long-running research-and-writing
pipeline that can pause, resume, inspect, and clean up after itself.
The pipeline assumes a measurable evaluator, simulator, public benchmark,
or other evidence source. If the topic has no measurable evaluator, warn
the user and downgrade to `arxiv` unless they provide an evaluator.

Do not use this skill for a short one-off draft, one-paper reading task,
slide deck, blog post, or camera-ready submission service. The output is a
structured draft and next-step list; the user owns scientific authorship,
submission, and final claims.

## Inputs

Ask for or parse these three fields:

```
topic: what to study
target_venue: arxiv | conference/venue | SCI Q1/journal
materials: paths, PDFs, notes, repos, datasets, or empty
```

If the user gives one paragraph, parse it internally. If the target venue
is ambiguous, use the Channel B fallback in `references/tier-decision-tree.md`.

## Tier Contract

| Tier | Use For | Shape |
|---|---|---|
| `arxiv` | preprint, negative result, working paper | shorter graph, negative-result waiver allowed |
| `conference` | IROS/ICRA/CVPR/NeurIPS/ACL-style targets | T0 evaluator, method, implementation, experiment, independent gate, writing |
| `journal-q1` | SCI Q1, Nature sub-journal, T-PAMI/T-RO/IJRR-style targets | conference graph plus deeper experiments and ablations |

Tier keywords live in `references/goal-keywords.md`. The fallback dialogue
lives in `references/tier-decision-tree.md`.

## Plan Generation Contract

Generated plans must initialize:

- `state/progress.json`
- `state/directions_tried.json`
- `state/candidate_registry.jsonl`
- `state/scoreboard.tsv`
- `state/research_acceptance.md`
- `control/`
- `resource_manifest.json`
- `last_seen.jsonl`
- `watchdog-log.md`

For `conference` and `journal-q1`, the task graph must include:

- `T0 evaluator-freeze`
- literature review and gap analysis
- method design
- implementation
- experiment
- `T6.1 evaluate-candidate`
- `T6.2 research-decision`
- `T6.3 pivot-or-retry`
- writing and package tasks only after the research gate

For `arxiv`, a clean negative-result paper may proceed only with
`WAIVED_NEGATIVE_RESULT`.

Read these modules when generating a plan:

- `references/plan-template-arxiv.md`
- `references/plan-template-conference.md`
- `references/plan-template-journal-q1.md`
- `references/task-prompt-snippets.md`
- `assets/task-prompt-snippets.md`
- `references/research-state-contract.md`
- `references/lifecycle-contract.md`

## Research Gate

`state/research_acceptance.md` is the only writing gate.

Accepted values:

- `PASS`
- `WAIVED_BY_HUMAN`
- `WAIVED_NEGATIVE_RESULT` (`arxiv` only)
- `FAIL`

Before T7 writing, run:

```bash
python3 references/scripts/research-state-guard.py \
  check-writing-gate --plan-dir <plan-dir> --tier <tier>
```

When `stale_count >= 2`, a retry must be structural. Validate pivots with:

```bash
python3 references/scripts/research-state-guard.py \
  validate-pivot --plan-dir <plan-dir> --proposal <pivot-brief.md>
```

## Watchdog And Lifecycle

Bootstrap command:

```bash
references/bootstrap-watchdog.sh <topic-slug> <tier> <plan-dir> [--rescue]
```

The bootstrap script creates or verifies:

- one stable watchdog agent via the native `mavis` tool (`mavis({ command: "agent create", args: { name: "<topic>-wd", system_prompt: "..." } })`)
- one hourly Mavis cron for L1 patrol (written to `~/.mavis/agents/<agent>/crons/<name>.md`)
- one PostToolUse hook from `assets/first-action-last-seen-hook.md` for L2 heartbeats (written directly to `~/.mavis/hooks/<name>.json.md`; no daemon CLI call)
- `resource_manifest.json`
- initial research state and control directories
- optional launchd-managed L0 rescue daemon

Heartbeat layers:

| Layer | Mechanism | Purpose |
|---|---|---|
| L0 | `plan-l0-guard.py` via launchd/manual patrol | session-independent stale detection, repair, cleanup requests |
| L1 | watchdog Mavis agent + hourly cron | emits findings and recommendations |
| L2 | `last_seen.jsonl` hook | per-task activity heartbeat |

The UI remains useful for status and control, but it is not the L0
heartbeat. L0 must be session-independent so a stale session is not
responsible for noticing its own stall.

## User Commands

Expose these commands by resolving `<plan-id>` to `<plan-dir>` with
`references/scripts/resolve-plan-dir.py`:

| Command | Action |
|---|---|
| `/autoresearch-paper status` | show plan status, research gate, stale count, resource health, recent findings |
| `/autoresearch-paper pause` | run `pause-plan.sh <plan-id>` and write `control/pause_requested.json` |
| `/autoresearch-paper resume` | run `resume-plan.sh <plan-id>`; L0 verifies and repairs resources |
| `/autoresearch-paper stop` | run `stop-plan.sh <plan-id>`; cancel when possible and clean resources |
| `/autoresearch-paper cleanup` | run `cleanup-plan-resources.sh <plan-id>` without deleting outputs |
| `/autoresearch-paper rescue-status` | show `state/l0_status.json`, `state/watchdog_health.json`, and rescue history |

## Long-Running Compute

Any worker action expected to exceed the runtime's foreground session cap
must use a background daemon pattern with checkpoint files. The producer
session should launch work, write a partial deliverable, and exit quickly.

Required checkpoint files:

- `run.pid`
- `run.log`
- `exit.code`
- `checkpoint.json`
- a lock file that prevents duplicate daemon launches

On Linux, workers may use `nohup setsid ... &`. On macOS, `setsid` is not
available by default; use `nohup ... &` plus `disown`, or a Python launcher
that calls `os.setsid()`.

Verifier sessions must independently inspect artifacts. Producer self-claims
do not count as evidence.

## Anti-Patterns

| ID | Forbidden behavior |
|---|---|
| ❌-1 | Spawn the agent team before explicit user confirmation |
| ❌-2 | Auto-abort a plan because watchdog recommends abort |
| ❌-3 | Overwrite an existing agent, cron, hook, manifest, or state file silently |
| ❌-4 | Let watchdog edit `last_seen.jsonl`, `out/*`, or research artifacts |
| ❌-5 | Invent a tier outside `arxiv`, `conference`, `journal-q1` |
| ❌-6 | Guess tier when Channel A misses instead of using Channel B |
| ❌-7 | Show raw YAML instead of a readable plan preview for confirmation |
| ❌-8 | Run destructive abort/cancel without the abort gate |
| ❌-9 | Promise camera-ready PDF, venue submission, or human-authorship replacement |
| ❌-10 | Run conference/journal mode without a measurable evaluator |
| ❌-11 | Let T7 writing start after T6 experiment without `research_acceptance.md` PASS or waiver |
| ❌-12 | Create permanent team members for every retry, direction, or section |
| ❌-13 | Stop a plan without `cleanup-plan-resources.sh` or a residual-resource report |

## Failure Modes

| ID | Trigger | First-line fix | Fallback |
|---|---|---|---|
| FM-1 | `mavis` missing (CLI for `team plan ...`) | run `scripts/setup.sh` and install/activate Mavis | abort before Step 5 |
| FM-3a | malformed YAML | retry stricter YAML generation up to 3 total attempts | fill the tier template mechanically |
| FM-3b | model refuses YAML | classify refusal; do not retry blindly | bypass model and fill template mechanically |
| FM-4 | agent/cron/hook already exists | treat as idempotent; skip existing resource | ask user for a new slug suffix |
| FM-7 | local rescue judge fails | fall back to `nudge` and log `judge_failed` | disable local LLM after repeated failures |
| FM-10 | long foreground SSH/compute hits session cap | relaunch via daemon + checkpoint files | salvage partial checkpoint on retry |
| FM-11 | rendered PDF has `[?]` or `??` | run pdflatex/bibtex/pdflatex/pdflatex and `pdftotext` checks | repair missing `.bib`/cross-refs manually |
| FM-12 | page-budget fold regresses readiness | compute dimension regression before deleting a section | request waiver, short-paper track, or restructure |
| FM-13 | result files hide ERROR/TypeError records | scan all raw files, not one sample | targeted rerun or patch helper |
| FM-14 | verifier reuses producer context | use a fresh session or artifact-only `codex exec` | defer to human if fresh verification is impossible |
| FM-16 | producer burns cap on repeated dry-runs | run one small dry-run then launch full daemon | read prior checkpoint and do not re-dry-run |
| FM-17 | model reloads per cell | preload model once at daemon startup | reload per batch if memory is limited |
| FM-18 | skip-if-exists breaks on pretty JSON | use full-file `json.load` | diagnose slow reruns from progress files |
| FM-19 | wrapper paper overclaims B5 beats B0 when equal | separate "preserves SOTA" from stress-path gains | add honest scope clarification |
| FM-20 | T6 completes but `research_acceptance.md` is missing or FAIL | run T6.1/T6.2 against frozen evaluator | require explicit waiver for writing |
| FM-21 | `stale_count >= 2` repeats same direction | force T6.3 structural pivot using `directions_tried.json` | escalate at `stale_count >= 4` |
| FM-22 | stop/abort leaves runtime resources behind | run `cleanup-plan-resources.sh <plan-id>` | report exact residual manual commands |
| FM-23 | team members grow unbounded | keep stable roles and mark temporary members `ephemeral=true` | cleanup archives/deletes temporary members |

## Deliverables

On completion, report:

- tier and why it was selected
- plan id and plan directory
- wall-clock vs estimate
- research gate verdict and evidence path
- paper paths: `paper.tex`, figures, bibliography
- `reviewer-readiness.md`
- `next-steps.md`
- `cleanup_report.md`

## References

- `references/goal-keywords.md` — tier keyword table
- `references/tier-decision-tree.md` — tier fallback logic
- `references/plan-template-arxiv.md` — arxiv plan shape
- `references/plan-template-conference.md` — conference plan shape
- `references/plan-template-journal-q1.md` — journal plan shape
- `references/task-prompt-snippets.md` — prompt asset index
- `assets/task-prompt-snippets.md` — full worker prompt fragments
- `references/research-state-contract.md` — state schema and research gate
- `references/lifecycle-contract.md` — manifest, resume, cleanup contract
- `references/watchdog-prompt-template.md` — watchdog system prompt template
- `references/first-action-last-seen.md` — hook registration contract
- `assets/first-action-last-seen-hook.md` — hook body registered by bootstrap
- `references/reviewer-readiness-rubric.md` — reviewer-readiness scoring
- `references/scripts/` — L0, rescue, cleanup, pause/resume/stop helpers

## Versioning

Per-release changelog. Versions follow semver-ish semantics within the
Mavis skill family (major = breaking orchestrator contract, minor = new
feature, patch = fixes). The full per-commit history is in the git log of
this file.

- **v0.7.0 (2026-07-16)** — CLI → tool migration. The legacy
  `mavis agent|cron|session|hook|archive` CLI subcommands are removed by
  the runtime; the skill is rewired to use the native `mavis` tool for
  agent/cron/session, direct file writes for hooks (`~/.mavis/hooks/...`),
  and direct cron/agent file removal during cleanup. `mavis team plan ...`
  remains a CLI (with the v0.7 flag rename `abort` → `cancel`).
  `mavis communication send` is marked deprecated (no replacement
  contract yet — surface as a finding instead of auto-sending).
- **v0.6.0 (2026-06-26)** — Agent Skills monorepo layout. The skill bundle
  moves to `skills/autoresearch-paper/` so `npx skills add` resolves it.
  Cleanup-script subcommand fix (`mavis agent archive` → `delete`,
  `mavis session archive` → `compress`).
- **v0.4.0 (2026-06-26)** — Platform-portable daemon pattern: drop Linux
  `setsid` dependency, add producer-discipline pre-flight checklist, and
  add the harness-paper honest-framing pattern to the reviewer rubric.
- **v0.3.1-r5 (2026-06-25)** — Wide-table 2-column span recipe
  (Step 7.5.a + FM-15) for camera-ready LaTeX output.
- **v0.3.1 (2026-06-25)** — V6 evidence: engine-ceiling handling, verifier
  spot-check recipe, and the "0% framing" honesty pattern for negative
  results.
- **v0.3.0 (2026-06-24)** — Rescue Layer: L0 filesystem-corruption guard,
  hourly watchdog cron, plan-rescue daemon, and three failure-mode FMs.
  Also adds the abort-gate and workspace-isolation checkpoint contracts.
- **v0.2.0 and earlier** — Three-tier plan templates
  (`arxiv` / `conference` / `journal-q1`), heartbeat contract, and the
  original brief-to-paper pipeline.

## License

MIT.
