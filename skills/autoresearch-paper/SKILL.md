---
name: autoresearch-paper
description: Turn a paragraph-level research brief into a research-first autonomous paper pipeline. Use for a multi-hour or multi-day Claude Code Harness with low-cost MiniMax M3 workers, four sparse Codex audits, hash-bound evaluator evidence, authenticated lifecycle actions, typed failures, pause/resume/stop, patrol, and owned cleanup. MAVIS is compatibility-only.
license: MIT
metadata:
  short-description: Research-first brief-to-paper pipeline with heartbeat and cleanup
  version: "0.17.0"
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
- Never convert MiniMax M3 or Codex output directly into acceptance, waiver,
  cancellation, resume, or destructive cleanup. Persist advice for controller
  validation or authenticated human review.
- Never start writing from a bare PASS string. Require a validated evaluator
  verdict or applied candidate/evaluator/tier-bound waiver receipt; every tier
  also requires APPLIED CP-04 `prewriting_final_evidence`.
- Never dispatch a MiniMax worker from its own plan. For a v0.16 staged plan,
  CP-01 binds the immutable human-owned optimization contract, exactly one
  first-stage envelope, its deterministic preflight, and named checkpoint
  capacity to an independent strongest-policy Codex review. The review is
  advisory; only the deterministic controller may authorize the stage.
- Never use `state/progress.json` or `state/research-dossier.md` to authorize a
  staged transition. `state/staged_research/v1/` is the sole runtime truth;
  those two files are rebuildable, non-authoritative projections.
- Never infer continuation authority from silence. The initial signed
  `authorize_contract` may pre-authorize exactly one explicitly named next
  stage, with `max_automatic_crossings=1` and `silence_is_approval=false`.
- Never transfer capacity between a stage's Worker quota, the global Worker
  capacity, `STAGE-REVIEW`, or CP-01/CP-02/CP-04 (and optional CP-03). A signed
  frontier top-up does not increase any Worker allowance.
- Never create a new staged envelope without the exact plan-relative,
  content-addressed `review_material_manifest` for objective, intervention,
  entry/exit, budget, report schema, and stop policy. Legacy v0.16 envelopes
  without it are read/replay-only.
- Never submit an initial staged CP-01 with wrapper artifacts alone. Bind a
  readable first-stage execution plan, acceptance evaluator, risk/stop rules,
  and figure strategy in `review_material_manifest`; the controller expands
  them into the bounded Codex evidence manifest.
- Never hide a closed artifact validator from the Worker. Compile the exact
  top-level and record fields, order, cardinality, and grounding rules into the
  Worker-visible prompt. External frozen inputs may be exposed with
  `--add-dir` only after controller hash verification and only with read-only
  tools. Claude grants that read authority at directory granularity: the input
  parent must contain no sibling secret that the Worker is not authorized to
  read. Accepted evidence still cites only the frozen manifest.
- Never treat `usage: {0,0}` as free or refund a launched frontier call.
  Preserve valid negative advice; reject `accept` with blockers/critical
  findings. Extra capacity requires a signed future-only
  `authorize_frontier_capacity` receipt.
- Never promote a paper figure from appearance, an AI review score, or an
  unbound image file. Require the repository-owned non-empty figure inventory,
  manifest hash and path validation, and a human review receipt bound to every
  current output.
- Never register or advance unattended conference/journal execution without a
  current controller-applied evaluator admission whose replay, regression,
  authority, inputs, search space, and complexity policy all revalidate.
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
    references/lifecycle-contract.md,
    references/scientific-figure-pipeline.md
)
show human-readable plan preview + watchdog config -> require explicit "go"
freeze Claude/MiniMax/Codex policy with references/scripts/harness-runtime.py init-policy
freeze the human-owned contract and exactly one first stage with init-staged-research
prepare caller-authored bootstrap inputs only under control/staged-inputs/ and
  review materials only under control/review-materials/; never pre-create or
  write state/staged_research/v1/ because init-staged-research is its sole publisher
create and apply authorize_contract only with harness-runtime.py
  create-human-action then apply-human-action; never read the human-action key
  or hand-build/HMAC-sign an authorization record
choose one stable RECORD_ID before hashing the contract, store the same value in
  contract.authorization_receipt_id, and pass it as create-human-action --record-id
run preflight-staged-research; bind contract + stage + preflight + named capacity to CP-01
run the strongest reviewer allowed by the frozen policy; retain controller authority
require validated CP-01 accept -> apply + assert approve_execution
route routine bounded tasks through harness-runtime.py dispatch-worker
at CP-01/02/03/04, create -> send -> validate -> apply -> assert the dependent transition
write watchdog-system-prompt.md from references/watchdog-prompt-template.md
schedule and run deterministic file-backed patrol through harness-runtime.py
initialize the canonical durable task graph and register its external trigger
advance one canonical work unit and dispatch only from its fresh context capsule
for MiniMax: dispatch-worker --context-capsule -> promote-worker-artifacts -> commit-durable-worker-result
for capsule-bound Codex: create-durable-frontier-request -> send -> validate -> apply -> commit-durable-frontier-result
for an observation-only first stage (research + evaluation_calls=0):
    preflight binds path + sha256 + symbol + line_start for every source;
    the frozen validator exposes an executable candidate/preflight adapter
    freeze-stage-candidate -> complete-observation-stage; the Controller runs
    the exact frozen source-inventory validator and records a typed non-Gate
    decision without creating Gate-accepted or reusable evidence
after a recorded stage decision: persist MiniMax report; create terminal STAGE-REVIEW -> send -> validate -> apply -> record-strong-stage-review
if the initial signed contract explicitly pre-authorized the named next stage:
    advance-staged-research -> derive bound receipt -> compile -> preflight -> authorize -> start exactly one next-stage Worker
else: require a fresh signed reauthorize_stage receipt before compile-next-stage
rebuild progress.json and research-dossier.md from canonical staged state with rebuild-staged-projections when needed
at the first authorized figure-production stage, freeze the exact inventory
after KEEP/waiver and before writing: build figures -> validate every figure manifest
use legacy adapters only when the user explicitly selects --legacy-mavis
while plan is running:
    observe canonical staged state + last_seen.jsonl + generated projections + l0/watchdog health
    honor status, pause, resume, stop, cleanup, rescue-status commands
    surface watchdog/L0 findings without destructive action
on finish or user stop:
    run cleanup-plan-resources.sh
    deliver paper paths, reviewer-readiness, watchdog summary, cleanup report
```

## Target Runtime: Claude Code

Read `references/claude-code-runtime.md` before dispatch. The current target
adapter provides:

- frozen per-plan MiniMax M3 and Codex model/budget policy;
- sole-authority `state/staged_research/v1/` state plus deterministic
  `rebuild-staged-projections` output for legacy progress and the human dossier;
- capacity v2 separation of per-stage Worker dispatches, global Worker
  dispatches, `STAGE-REVIEW`, and named CP slots, with no Worker capacity from
  frontier top-ups;
- exactly one initial-contract-pre-authorized crossing, gated on a terminal
  decision, MiniMax report, and fresh strongest-policy review, ending at one
  next-stage Worker start;
- a mandatory independent CP-01 top-level-plan audit pinned to
  `gpt-5.6-sol` at `ultra`, with reviewer identity and policy hash carried into
  the durable `approve_execution` receipt;
- non-interactive, schema-bounded MiniMax M3 worker dispatch through Claude Code;
- immutable, hash-bound requests for CP-01 through CP-04;
- fail-closed frontier preflight before budget reservation, including Codex
  executable/auth, strict response-schema, model, and transport checks;
- authenticated, expiring, replay-protected human actions;
- hash-bound evaluator verdict and final-writing gates;
- executable evaluator admission and drift-triggered autonomy revocation for
  unattended conference/journal plans;
- typed runtime/scientific failure counters and CP-03 eligibility;
- controller-replayed scientific-acceptance receipts plus isolated goal-drift
  and evaluator-integrity detection/routes;
- two-stage episode→audited-memory→proposal learning gates with replay,
  held-out/regression evidence, independent audits, and human-only evaluator
  proposal authorization;
- seven-scenario fault evidence, real multi-session soak accounting, and
  measured-duration claim gates that reject unsupported 24h/7×24/full-cutover
  language;
- complete worker inspect/wait/message/cancel, file-backed patrol, and owned cleanup;
- launchd-backed external registration, generation-bound tick leases,
  canonical state/event/evidence revisions, rebuildable projections, and fresh
  task context capsules;
- metadata-only Guardian observations and controller validation of
  pre-authorized lifecycle actions;
- HTTPS-only durable Codex transport with streamed evidence, response
  validation, exact-once dependent transitions, timeout, and restart
  inspection. Outcome-uncertain sends remain charged and are never blindly
  redelivered.
- capsule-bound production dispatch for both MiniMax and Codex, with exact
  task/manifest/revision correlation and controller-only durable commits.
- the packaged `references/canonical-conformance-workflow.json`
  `claude-research-conformance-v1` fixture, which rejects incomplete M1
  conformance runs and verifies terminal artifacts. It is not the production
  topic-to-paper trigger; production state advancement is handled by the
  durable loop, while fault/soak cutover remains an M5 gate.

MAVIS bootstrap/watchdog scripts are compatibility fixtures. They never define
target Harness semantics and run only through explicit legacy entry points.

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

- canonical `state/staged_research/v1/` governance for new v0.17 plans, using
  capacity v2, exclusively through `init-staged-research`; preparatory contract,
  envelope, profile, capacity, preflight, and review-material inputs belong
  under `control/staged-inputs/` or `control/review-materials/`, never under the
  canonical namespace
- generated `state/progress.json` and `state/research-dossier.md` projections;
  neither is transition authority
- `state/directions_tried.json`
- `state/candidate_registry.jsonl`
- `state/scoreboard.tsv`
- `state/research_acceptance.md`
- a closed `metric_contract` input for CP-02; do not pre-create
  `state/evaluator_contract.json` (the controller freezes it after CP-02)
- `state/failure_state.json`
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
- `T6.4 figure-build` after a validated KEEP decision; its authorized stage
  freezes the exact figure inventory
- writing and package tasks only after the research gate

For `arxiv`, a clean negative-result paper may proceed only with an applied,
hash-bound negative-result waiver receipt.

Read these modules when generating a plan:

- `references/plan-template-arxiv.md`
- `references/plan-template-conference.md`
- `references/plan-template-journal-q1.md`
- `references/task-prompt-snippets.md`
- `assets/task-prompt-snippets.md`
- `references/research-state-contract.md`
- `references/lifecycle-contract.md`
- `references/scientific-figure-pipeline.md`

## Research Gate

`state/evaluator_contract.json` is frozen from a controller-executed calibration
receipt and the exact CP-02-audited `metric_contract` containing metric,
operator, and threshold. Candidate value and PASS/FAIL are also derived from controller-owned
execution receipts. Bare `research_acceptance.md` values are never authority.
Human waivers must be applied receipts bound to tier, candidate, evaluator
contract, and scope; pending signed records are not authority. Negative-result
waivers remain arxiv-only. Every writing tier requires CP-04 final-evidence
approval and emits a writing-gate audit.

Unattended `conference` and `journal-q1` execution additionally requires
`admit-evaluator` followed by `check-autonomy-eligibility`. A finite metric
alone is insufficient: admission binds independent authority, immutable
inputs, validation identity, identical replay, passing regression, allowed
search space, and complexity policy. Admission drift blocks trigger, advance,
and result application.

Before T7 writing, run:

```bash
python3 references/scripts/harness-runtime.py \
  check-figure-gate --plan-dir <plan-dir> \
  --inventory <plan-dir>/out/figures/required-figures.json \
  --requirements <plan-dir>/state/figure-requirements.json

python3 references/scripts/research-state-guard.py \
  check-writing-gate --plan-dir <plan-dir> --tier <tier> \
  --verdict <state/evaluator_verdicts/candidate.json> \
  --figure-gate-receipt <state/figure_gates/decision.json>
```

When distinct controller-normalized scientific directions bound to canonical
FAIL verdicts reach the frozen threshold, a retry must be structural. Runtime
stalls never count. Validate:

```bash
python3 references/scripts/research-state-guard.py \
  validate-pivot --plan-dir <plan-dir> --proposal <pivot-brief.md>
```

## Scientific Figure Gate

Read `references/scientific-figure-pipeline.md` before T6.4, T7, T10, or T11.
The repository-owned figure contract is host neutral:

- `scientific-visualization` is the curated default capability for truthful,
  accessible, publication-oriented local plots;
- `scientific-schematics` is optional and proposal-only for method or
  architecture drafts;
- an AI-generated image or AI quality score has no scientific-accuracy,
  artifact-promotion, evaluator, or writing authority;
- every promoted figure binds its source inputs, transformations, render
  command, renderer identity, source revision, outputs, and hashes;
- exact figure requirements are frozen at the first controller-authorized
  figure-production stage, not at initial CP-01;
- result figures are built only after a validated KEEP decision, or after the
  applicable authenticated arxiv waiver;
- T7 is blocked until a non-empty required-figure inventory, every bound
  manifest, and every human output-bound review receipt pass the deterministic
  validator.

Validate the plan inventory from the installed skill directory:

```bash
python3 references/scripts/validate-figure-artifacts.py \
  --plan-dir <plan-dir> \
  --inventory <plan-dir>/out/figures/required-figures.json \
  --requirements <plan-dir>/state/figure-requirements.json
```

The validator proves the declared path, hash, provenance, and artifact-format
contract. It does not certify scientific truth, accessibility, visual
legibility, or venue compliance; those remain independent review duties.

## Patrol And Lifecycle

Target commands:

```bash
python3 references/scripts/harness-runtime.py init-durable-plan --plan-dir PLAN --graph PLAN/durable-plan.json
python3 references/scripts/harness-runtime.py register-durable-trigger \
  --plan-dir PLAN --interval-seconds 300 --jitter-seconds 30 \
  --session-budget-seconds 1800 --human-escalation-after-seconds 900
python3 references/scripts/harness-runtime.py run-durable-tick --plan-dir PLAN
python3 references/scripts/harness-runtime.py run-patrol --plan-dir PLAN --stale-seconds 7200
```

The production wake-up is externally registered and survives the initiating
Claude Code session. Tick state, leases, canonical revisions, and context
capsules are file-backed; a file-only schedule is not treated as a trigger.
Patrol records only typed runtime failures. `bootstrap-watchdog.sh` remains an
explicit legacy fixture.

Heartbeat layers:

| Layer | Mechanism | Purpose |
|---|---|---|
| L0 | `plan-l0-guard.py` via launchd/manual patrol | session-independent stale detection, repair, cleanup requests |
| L1 | launchd-backed durable trigger and lease | wakes and reconciles the deterministic controller |
| L2 | `last_seen.jsonl` hook | per-task activity heartbeat |

The UI remains useful for status and control, but it is not the L0
heartbeat. L0 must be session-independent so a stale session is not
responsible for noticing its own stall.

## User Commands

Expose these commands by resolving `<plan-id>` to `<plan-dir>` with
`references/scripts/resolve-plan-dir.py`:

| Command | Action |
|---|---|
| `/autoresearch-paper status` | inspect controller, workers, typed failures, gates, and patrol state |
| `/autoresearch-paper pause` | create and apply a signed `pause` record |
| `/autoresearch-paper resume` | create and apply a signed `resume` record |
| `/autoresearch-paper stop` | create/apply signed `stop`, then pass its receipt to cleanup |
| `/autoresearch-paper cleanup` | create/apply scoped `cleanup_resource` records and remove owned files |
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
| ❌-11 | Let T7 start from a bare PASS string or without the required CP-04 receipt |
| ❌-12 | Create permanent team members for every retry, direction, or section |
| ❌-13 | Stop a plan without `cleanup-plan-resources.sh` or a residual-resource report |
| ❌-14 | Let model advice directly accept, waive, cancel, resume, or clean lifecycle resources |
| ❌-15 | Call Codex outside CP-01 through CP-04 or before reserving the frozen frontier budget |
| ❌-16 | Accept a figure from an AI score, an unbound file, or a manifest that escapes the plan root |
| ❌-17 | Let MiniMax M3 approve or execute its own top-level plan without the frozen strongest-model CP-01 receipt |

## Failure Modes

| ID | Trigger | First-line fix | Fallback |
|---|---|---|---|
| FM-1 | `claude` missing | run `scripts/setup.sh` and install/activate Claude Code | stop before any worker dispatch |
| FM-1L | `mavis` missing on a legacy compatibility path | migrate that operation to the Claude adapter or install Mavis temporarily | do not make MAVIS canonical again |
| FM-3a | malformed YAML | retry stricter YAML generation up to 3 total attempts | fill the tier template mechanically |
| FM-3b | model refuses YAML | classify refusal; do not retry blindly | bypass model and fill template mechanically |
| FM-4 | agent/cron/hook already exists | treat as idempotent; skip existing resource | ask user for a new slug suffix |
| FM-7 | local rescue judge fails | fall back to `nudge` and log `judge_failed` | disable local LLM after repeated failures |
| FM-10 | long foreground SSH/compute hits session cap | relaunch via daemon + checkpoint files | salvage partial checkpoint on retry |
| FM-11 | rendered PDF has `[?]` or `??` | run pdflatex/bibtex/pdflatex/pdflatex and `pdftotext` checks | repair missing `.bib`/cross-refs manually |
| FM-12 | page-budget fold regresses readiness | compute dimension regression before deleting a section | request waiver, short-paper track, or restructure |
| FM-13 | result files hide ERROR/TypeError records | scan all raw files, not one sample | targeted rerun or patch helper |
| FM-14 | verifier reuses producer context | use a fresh session or artifact-only `codex exec` | defer to human if fresh verification is impossible |
| FM-17 | model reloads per cell | preload model once at daemon startup | reload per batch if memory is limited |
| FM-18 | skip-if-exists breaks on pretty JSON | use full-file `json.load` | diagnose slow reruns from progress files |
| FM-19 | wrapper paper overclaims B5 beats B0 when equal | separate "preserves SOTA" from stress-path gains | add honest scope clarification |
| FM-20 | verdict/evidence/candidate hash drifts | rerun evaluation against the frozen contract | require authenticated waiver |
| FM-21 | scientific threshold repeats the same direction | deduplicate controller-normalized, FAIL-bound directions and force T6.3 structural pivot | request CP-03 advice |
| FM-22 | stop/abort leaves runtime resources behind | run `cleanup-plan-resources.sh <plan-id>` | report exact residual manual commands |
| FM-23 | team members grow unbounded | keep stable roles and mark temporary members `ephemeral=true` | cleanup archives/deletes temporary members |
| FM-24 | `scientific-visualization` capability is unavailable | install the pinned focused skill and retain the figure specification | block only the affected figure build; do not weaken the gate |
| FM-25 | optional AI schematic capability or credential is unavailable | keep the textual/vector specification and deterministic renderer path | skip AI generation without blocking unrelated result figures |
| FM-26 | figure inventory, manifest, path, hash, or human output-bound review fails | preserve the proposal and rerun the repository validator | prohibit T7/T10 promotion until corrected |

## Deliverables

On completion, report:

- tier and why it was selected
- plan id and plan directory
- wall-clock vs estimate
- research gate verdict and evidence path
- paper paths: `paper.tex`, figures, bibliography
- validated non-empty figure inventory, manifests, and human output-bound
  review receipts
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
- `references/claude-code-runtime.md` — target runtime commands and migration boundary
- `references/learning-promotion-contract.md` — two-stage audited memory and proposal gates
- `references/fault-soak-acceptance-contract.md` — seven faults, soak evidence, and bounded claims
- `references/scientific-figure-pipeline.md` — deterministic plots, optional schematics, manifests, and promotion gate
- `references/figure-artifact.schema.json` — machine-readable figure artifact contract
- `references/figure-requirements.schema.json` — expected figure identities;
  legacy v0.15 plans freeze them at CP-01, while v0.16 freezes them at the
  figure stage
- `references/staged-research.schema.json` — aggregate staged-governance v1
  contract, stage, Gate, report, review, and evidence definitions, including
  capacity v2; legacy capacity v1 retains existing-plan lifecycle/replay
  compatibility but cannot use automatic stage crossing
- `references/role-visible-state.schema.json` — exact per-role rendered state
  and ordered context transformations, distinct from audit history
- `references/frontier-response.schema.json` — Codex advisory response schema
- `references/frontier-transport-incident-2026-07-25.md` — v0.14.0 CP-01
  failure chain, v0.14.1 controls, and operator diagnosis order
- `references/watchdog-prompt-template.md` — watchdog system prompt template
- `references/first-action-last-seen.md` — hook registration contract
- `assets/first-action-last-seen-hook.md` — hook body registered by bootstrap
- `references/reviewer-readiness-rubric.md` — reviewer-readiness scoring
- `references/scripts/` — L0, rescue, cleanup, pause/resume/stop helpers

## Versioning

Per-release changelog. Versions follow semver-ish semantics within the
Harness contract (major = breaking orchestrator contract, minor = new
feature, patch = fixes). The full per-commit history is in the git log of
this file.

- **v0.17.0 (2026-07-27)** — Canonical staged state is the sole runtime
  authority; progress and dossier files are rebuildable non-authoritative
  projections. Capacity v2 isolates per-stage and global Worker limits,
  terminal `STAGE-REVIEW`, and named CP capacity. An initial signed contract
  may explicitly pre-authorize one next stage; only a terminal decision,
  MiniMax report, and fresh strongest-policy review allow the controller to
  derive the bound receipt and idempotently start one next-stage Worker.
  Current Codex custom-agent schemas are supported by disabling multi-agent
  features without emitting the obsolete `agents.enabled=false` override.
  Observation-only bootstrap stages now terminate through deterministic
  `complete-observation-stage`: the Controller validates the frozen promoted
  source inventory, records an explicit non-Gate decision, and produces no
  reusable Gate evidence before the mandatory terminal strong review.
  Their preflight source manifest binds each selected symbol and one-based
  source line in addition to path and digest; Runtime rejects an ambiguous or
  drifting selection before model dispatch. The shipped validator also offers
  a CLI adapter that emits a hash-bound development receipt.
  A MiniMax terminal report contains the scientific fields but cannot know its
  post-call role-visible hash. After the completed call is recorded, the
  Controller may add only that provenance field to the canonical report; it
  must not author or rewrite the report's scientific content.
  An unattended top-level Claude controller must run under explicit operator
  pre-authorization; `auto` classifier denial is a pre-launch Harness event,
  not permission to consume or reassign research capacity.
  Legacy capacity v1 retains existing-plan lifecycle/replay compatibility but
  cannot use automatic stage crossing. This release claims a
  bounded stage-crossing capability and acceptance target only—not second-stage
  completion, scientific success, 24h or 7x24 stability, production readiness,
  or full cutover.
- **v0.16.2 (2026-07-26)** — Field-loop recovery: staged CP-01 now expands
  readable plan/evaluator/risk/figure materials into the Codex audit boundary,
  plan-wide ChatGPT budgets must fund every declared call, frontier review is
  forced into an isolated single-reviewer surface, and hash-verified external
  Worker inputs plus closed evaluator schemas are made visible before spend.
  Claude executable/UTF-8 checks and combined dispatch/scientific-capacity
  prechecks now occur before mutation, and every normalized artifact obeys its
  declared byte cap.
  Release acceptance used the original Claude session to pass CP-01, enter
  `DEVELOPING`, execute MiniMax-M3 research, and produce a strictly grounded
  first-stage inventory rather than stopping at a schema fixture.
- **v0.16.1 (2026-07-26)** — Field-recovery patch: typed negative frontier
  advice, conservative unknown-usage charging, ChatGPT reservation floors,
  signed prospective capacity top-ups, content-addressed stage review
  material, and fail-fast CP-01/STAGE-REVIEW routing. Launched charges,
  immutable provenance, and bounded acceptance claims remain unchanged.
- **v0.16.0 (2026-07-25)** — Versioned rolling-stage governance: one
  human-owned optimization contract, one CP-01 first-stage envelope,
  deterministic preflight and non-fungible CP capacity, one logical Gate per
  candidate with independently budgeted retries, evidence/role-visible
  ledgers, terminal MiniMax reports, fresh non-M3 strong review, and
  controller compilation of at most one next stage. Exact figure inventory
  now freezes at the authorized figure-production stage; legacy v0.15
  receipts remain readable.
- **v0.15.0 (2026-07-25)** — Mandatory strongest-model top-level plan review:
  the controller may declare MiniMax M3 as the initial-plan author, but CP-01 is pinned to Codex
  `gpt-5.6-sol` at `ultra`; the reviewer profile and frozen policy hash are
  revalidated before `approve_execution` and every worker dispatch.
- **v0.14.1 (2026-07-25)** — Frontier transport hardening: strict-schema,
  executable/auth, and model/transport preflight before budget reservation;
  Git-safe HTTPS-only ChatGPT routing; durable streamed transport evidence;
  exact crash recovery for reservations proven not to have launched transport;
  and fail-closed accounting for uncertain sends.
- **v0.14.0 (2026-07-24)** — Curated scientific-figure pipeline:
  source-bound figure manifests, deterministic path/hash/provenance validation,
  a post-KEEP pre-writing gate, Scientific Visualization as the focused
  default capability, and Scientific Schematics as optional proposal-only
  assistance.
- **v0.13.0 (2026-07-23)** — Bounded T008 acceptance: all seven production
  fault classes, multi-session restart soak accounting, evidence manifests,
  duplicate/loss/overlap/authority checks, and measured-duration claim gates.
  This release does not claim 24h or 7×24 stability.
- **v0.12.0 (2026-07-23)** — Deterministic autonomy and gated learning:
  closes the existing bounded-worker/deterministic-recovery slice and adds
  two-stage audited memory/proposal promotion, rejection memory, novelty
  protection, and proposal-bound human evaluator authorization.
- **v0.11.0 (2026-07-23)** — Scientific-truth and failure-routing closure:
  controller-owned evaluator material snapshots, replayed scientific
  acceptance with current admission, and isolated deterministic goal-drift /
  evaluator-integrity detection and routing.
- **v0.10.0 (2026-07-23)** — Production transport cutover: canonical context
  capsules now bind MiniMax task contracts and inputs, derive Codex checkpoint
  manifests, and admit only controller promotion/transition receipts into the
  durable evidence loop with exact-once commit recovery.
- **v0.9.0 (2026-07-23)** — Durable production loop and evaluator admission:
  launchd registration, generation-bound tick claims, canonical revisions and
  projections, fresh context capsules, metadata-only Guardian recovery, and
  replay/regression/authority-bound eligibility for unattended
  conference/journal plans.
- **v0.8.0 (2026-07-18)** — Claude Code target cutover: authenticated human
  actions, evidence-bearing evaluator/writing gates, typed failures, complete
  target runtime operations, hash-bound CP-01–CP-04 transitions, and a
  no-MAVIS fake-transport integration test.
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
