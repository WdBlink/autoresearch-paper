# P6 Supervisory Controller and Codex Thread Watchdog

Status: approved design, amended after full-Watchdog review

Date: 2026-08-02

## Objective

Add a bounded P6 control layer above the implemented MVP-0 P1–P5 transactions.
P6 must keep one research run moving without requiring a person to send
"continue" after every terminal Codex turn. It must restore the accepted
three-layer runtime-assurance closure: an independent zero-model L0 health
supervisor, a Codex scheduled L1 task inside the existing research chat, and
controller-owned L2 heartbeats from the fixed Claude/MiniMax Worker. L1 must
appear in the Codex App Scheduled view and bind exactly one automation to one
Codex thread and one research run.

The first live acceptance target is:

- Codex thread: `019fc053-ab31-7333-b5da-85b03372ec24`
- research run: `/Users/wdblink/Research/runs/fwvg-mvp0-evaluator-20260802`

P6 does not claim 24-hour or 7-by-24 stability. It establishes the recoverable
controller and one real thread-bound watchdog needed before those profiles are
meaningful.

## Product boundary

P6 adds:

- a single canonical supervisor state for a run;
- one-idempotent-tick transition logic over P2–P5 durable artifacts;
- an independently registered L0 launchd health supervisor with zero model
  calls;
- a Codex thread-heartbeat L1 automation registration;
- a controller-owned L2 Worker-heartbeat contract and receipt stream;
- one immutable activation receipt binding exact L0/L1/L2 identities,
  intervals, thresholds, logs, and functional probes;
- automatic recovery from a completed or interrupted Host turn;
- deterministic L0 repair of a missing or stopped L1 registration;
- automatic delegated review for execution-only Research IR revisions;
- automatic creation of the next authorized P2 lineage;
- exact-once pause/stop with owned-resource and residual reporting;
- a read-only runtime snapshot suitable for the existing Dashboard projection;
- explicit pause, terminal, and human-review states.

P6 does not add:

- a second research truth outside the P1–P5 stores;
- a generic machine-wide process daemon or system `cron` entry unrelated to
  one exact research run;
- a new Dashboard implementation or paper-writing loop; P6 supplies the
  canonical runtime snapshot consumed by the existing Dashboard;
- automatic modification of scientific claims, metrics, baselines, fairness,
  falsification, or safety boundaries;
- silent retry of the same failed Worker contract;
- promotion of rejected Worker changes into accepted source state.

The Legacy v0.20 Harness remains isolated. P6 may port its already-tested
runtime-assurance contracts and deterministic algorithms into independent MVP0
modules, but it must not import the legacy Harness runtime or restore legacy
research state as a second source of truth.

## Chosen architecture

Use a three-layer hybrid watchdog backed by a deterministic P6 controller.

```text
L0 launchd health supervisor (session-independent, metadata-only, zero model)
  -> verifies and, under frozen recovery authority, restores exact L1

L1 Codex App Scheduled heartbeat (exact target_thread_id)
  -> durable prompt (exact controller path and identity)
  -> supervisor tick (one transition only)
  -> P2 / P3 / P4 / P5 / delegated review / child P2
  -> immutable tick receipt and updated canonical state

L2 fixed Claude/MiniMax Worker
  -> sequenced identity-bound heartbeat receipts
  -> supervisor liveness and stale-worker decisions

read-only runtime inspection
  -> existing loopback Dashboard projection
```

Rejected alternatives:

1. A standalone scheduled task that later relays to the research chat adds a
   second chat, loses the original context, and needs an extra thread-messaging
   bridge.
2. Codex-only scheduling cannot detect or repair the loss of its own
   registration and cannot satisfy the accepted requirement that runtime
   assurance remain meaningful when the Codex foreground task is absent.
3. A launchd-only research scheduler loses the required same-thread Codex Host
   continuity and App management surface. Launchd is therefore restricted to
   L0 health supervision; it is not the model-bearing research scheduler.

The Codex manual explicitly distinguishes standalone scheduled tasks from
scheduled tasks inside a chat. P6 uses the latter for L1 because continuity
with the existing research context is required. L0 remains deliberately
outside that failure domain and never invokes Codex, Claude, or MiniMax.

## Canonical supervisor store

Create one store outside the source repository:

```text
<run>/supervisor/
├── supervisor-manifest.json       # immutable, mode 0444
├── supervisor-state.json          # canonical mutable state
├── ticks.jsonl                    # append-only ordered tick index
├── objects/sha256/<digest>.json   # immutable tick and review objects
├── assurance/
│   ├── activation-receipt.json   # immutable L0/L1/L2 closure
│   ├── l0-registration.json     # immutable scheduler binding
│   ├── l1-registration.json     # immutable Codex automation binding
│   ├── l2-heartbeat-contract.json
│   ├── l0-observations.jsonl
│   └── l2-heartbeats.jsonl
├── runtime/resource-manifest.json # owned external resources only
├── runtime/shutdown-journal.json  # restart-safe exact-once stop
├── leases/tick.lock               # local overlap exclusion
└── reports/latest.md              # derived human-readable status
```

`supervisor-manifest.json` binds:

- `controller_id` and schema version;
- exact Codex `target_thread_id`;
- absolute research run and source repository paths;
- current compiler, Adapter, P3, P4, and P5 store paths;
- initial Research IR and freeze receipt digests;
- expected automation id and automation file path;
- exact L0 service identity and command digest;
- L1 automation cadence, L0 health cadence, L2 heartbeat cadence, and all stale
  thresholds;
- bound stdout/stderr paths and owned-resource manifest;
- engineering delegation policy;
- hashes of the P6 code, schemas, prompt, and policy used at initialization.

`supervisor-state.json` is the only P6 runtime truth. It contains the current
phase, latest committed tick, active lineage paths and digests, retry/stall
counters, and terminal or human-review reason. P1–P5 remain authoritative for
their own artifacts; P6 only indexes their verified digests and never copies or
rewrites their conclusions.

Every mutation takes an exclusive local lease, verifies the complete prior
lineage, writes an immutable content-addressed tick object, appends its digest
to `ticks.jsonl`, and atomically replaces the canonical state. A repeated tick
over the same verified state is a no-op with no duplicate transition.

## L1 Codex automation binding

Register a local Codex automation at:

```text
~/.codex/automations/<controller-id>/automation.toml
```

Required shape:

```toml
version = 1
id = "<controller-id>"
kind = "heartbeat"
name = "AutoResearch MVP0 · <short-run-name>"
prompt = "<durable P6 heartbeat prompt>"
status = "ACTIVE"
rrule = "RRULE:FREQ=MINUTELY;INTERVAL=10"
target_thread_id = "<exact Codex thread id>"
created_at = <unix milliseconds>
updated_at = <unix milliseconds>
```

Use the Codex scheduled-task update capability when it is callable. When it is
not exposed, write the exact app-compatible TOML, normalize it with
`codex-automation-registration`, and require a Codex App refresh only if it is
not visible. Do not register a system crontab entry. This file is L1, not the
entire Watchdog.

The prompt includes the exact controller id, supervisor manifest path, expected
thread id, and run path. On every run it invokes `$autoresearch-paper-mvp0`,
rebuilds state from durable artifacts, and executes at most one `tick`. The
App-owned `target_thread_id` is the delivery binding; the prompt, automation
file, and supervisor manifest provide three-way accidental-mismatch protection.
This is a binding and replay guarantee, not cryptographic user authentication.

The default cadence is ten minutes. Users can pause, resume, change cadence, or
inspect run history from the Codex App Scheduled view. P6 automatically pauses
the automation on terminal or human-review states and reactivates it only after
the corresponding state has been explicitly resolved.

## L0 independent health supervisor

Register one plan-bound macOS launchd service with a scheduler label and
controller-command digest distinct from L1. Its command may read only the
supervisor manifest, activation receipt, scheduler metadata, controller lease,
Worker status, heartbeat metadata, and owned-resource manifest. It must not read
Research IR content, experiment results, prompts, or model responses and must
never invoke a model.

Each L0 tick writes one typed, deduplicated observation. It may perform only
frozen deterministic recovery, initially limited to restoring the exact L1
automation file when it is missing, disabled, or byte-mismatched and no stop or
pause authority is active. It must not execute a research transition itself.
Unknown drift, stale controller state, or mismatched identity produces a
recovery proposal and a fail-closed runtime status rather than a guessed repair.

The health interval must be no greater than both 3600 seconds and one half of
the shortest frozen stale threshold. Registration binds absolute stdout and
stderr paths. A schedule file on disk is not proof that L0 is loaded.

## L2 Worker heartbeat

Every running P2 Worker emits sequenced immutable heartbeat receipts through a
least-authority controller callback. Each receipt binds controller id, Adapter
id, turn id, session UUID, model, process identity, task-contract digest,
sequence, observation time, and predecessor heartbeat digest. Heartbeats carry
no hidden reasoning and do not imply scientific progress or success.

The controller accepts a heartbeat only for the currently bound running Worker
and rejects stale, duplicate-with-different-bytes, out-of-order, wrong-session,
wrong-process, or wrong-contract receipts. A stale L2 heartbeat is a runtime
fault. It may trigger bounded process inspection and P5 recovery, but it cannot
force a scientific decision.

## Activation closure

Unattended Worker dispatch is forbidden until one immutable activation receipt
replays successfully against:

- loaded and distinct L0 and L1 identities;
- exact L0 and L1 command/configuration digests;
- the L2 heartbeat contract;
- frozen intervals and stale thresholds;
- one non-due L1 functional probe with zero model calls;
- one L0 drill that removes L1 and proves exact restoration with zero model
  calls;
- one L2 conformance heartbeat bound to the same controller and authority;
- bound logs and the owned-resource manifest.

Activation is invalidated by an unloaded, stale, altered, mismatched, or
legacy-only layer. Bootstrap is restart-safe and commits `READY` only after all
three probes pass.

## Controller states

P6 uses a closed state set:

- `READY`: verified run with no transition currently executing;
- `WORKER_RUNNING`: a P2 dispatch has no terminal receipt yet;
- `NEEDS_P3`: a terminal P2 turn is not in the P3 ledger;
- `NEEDS_P4`: the next P3 receipt has no P4 decision;
- `NEEDS_P5`: the latest eligible P4 decision is `PIVOT` or `RECOMPILE`;
- `NEEDS_ENGINEERING_REVIEW`: an execution-only child IR proposal exists;
- `NEEDS_CHILD_P2`: a delegated or owner-reviewed child freeze is bound;
- `WAITING_HUMAN`: a scientific change or owner-only decision is required;
- `BLOCKED`: a bounded recovery policy is exhausted or state is inconsistent;
- `STOPPED`: a verified STOP rule, explicit owner stop, or terminal budget rule
  has fired;
- `COMPLETED`: the bounded research objective has reached its declared terminal
  acceptance condition.

The controller derives the next state from verified P1–P5 artifacts. A mutable
state label cannot override their durable truth.

## One-tick transition table

Each scheduled run performs at most one row:

| Observed durable state | Tick action | Result |
|---|---|---|
| active P2 without terminal receipt | inspect liveness and timeout only | `WORKER_RUNNING`, `BLOCKED`, or no-op |
| terminal P2 absent from P3 | record and verify exact turn | `NEEDS_P4` |
| next P3 receipt absent from P4 | decide and verify Gate | `NEEDS_P5`, `STOPPED`, or `READY` |
| eligible P4 `PIVOT/RECOMPILE` | publish P5 analysis/request/proposal | `NEEDS_ENGINEERING_REVIEW` or `WAITING_HUMAN` |
| execution-only P5 proposal | run independent review and deterministic policy validation | `NEEDS_CHILD_P2` or `BLOCKED` |
| bound child freeze | create successor P2 lineage and dispatch one authorized task | `WORKER_RUNNING` |
| human/scientific boundary | write report and pause automation | `WAITING_HUMAN` |
| verified terminal condition | write report and pause automation | `STOPPED` or `COMPLETED` |

`KEEP` selects the next ready experiment through a separately authorized child
P2 lineage. It does not reuse or mutate the old Adapter manifest. `STOP` is
terminal. `PIVOT` and `RECOMPILE` enter P5.

## Worker failure and successor lineage

A failed Worker turn remains failed and immutable. P6 never retries the exact
same task contract and never resets its worktree.

For a recoverable budget, timeout, or task-size failure, P5 may compile IR N+1
whose changed roots are limited to execution policy. The successor may:

- raise or lower the per-turn Worker budget within the run's bounded spending
  policy;
- reduce one experiment objective or split later experiment-plan entries;
- change execution dependencies without changing scientific acceptance;
- bind rejected-file hashes as failure evidence, but not as accepted artifacts.

The current evaluator-build failure will first use a higher bounded per-turn
budget and a narrower completion objective. It will not pretend the rejected
drafts were accepted source state.

Create a new child Adapter and worktree from the last accepted source commit.
Preserve the fixed Claude/MiniMax session where safe by adding an explicit
predecessor-bound resume mode: the child Adapter binds the predecessor turn,
session UUID, model, and P5 request, and its first transport call uses exact
`--resume`. If identity or predecessor checks fail, pause instead of rotating
the session or falling back to another model.

## Delegated engineering review

Add the live approval scope `DELEGATED_ENGINEERING_REVIEW`. Do not reuse the
test-only `ENGINEERING_ACCEPTANCE` scope and do not fabricate an `owner/*`
identity.

Automatic review is permitted only when all actual changed JSON roots are in
the closed engineering allowlist:

- `/budget`;
- `/experiment_plan`;
- evidence-only evaluator bindings: status, implementation artifact path, and
  implementation SHA-256 when those values are derived from verified receipts.

The following remain byte-identical under delegated review:

- problem and central claim;
- novelty and related-work boundary;
- baseline identity and fairness contract;
- primary metric, guardrails, thresholds, aggregations, seed requirements, and
  confidence rules;
- falsification and STOP semantics;
- source project identity;
- forbidden changes and safety constraints;
- evaluator argv, metric bindings, and measurement semantics.

The compiler author, fresh non-MiniMax Codex reviewer, revision author, and
Codex approver must use distinct identities where required by the P1 lineage.
The reviewer verdict binds the exact parent IR, P4 decision, P5 request,
proposal, actual changed roots, retained-root hashes, and deterministic policy
validator output. Any ambiguity, broader root, missing evidence, or reviewer
rejection produces `WAITING_HUMAN` or `BLOCKED`; it never weakens the policy.

P2 and P5 are extended to accept `DELEGATED_ENGINEERING_REVIEW` only when the
complete P6 review receipt replays successfully. A bare freeze receipt carrying
that string is insufficient.

## Watchdog and recovery semantics

The Watchdog is the combined L0/L1/L2 closure, not the Codex heartbeat alone.
L0 supervises scheduler health, L1 resumes and advances the Codex Host, and L2
proves liveness of the active Claude/MiniMax Worker. The deterministic P6
controller reconciles their evidence without turning runtime health into a
scientific verdict.

The watchdog may:

- resume the exact target chat after a Host turn completes;
- detect and restore the exact missing L1 registration without a model call;
- advance a committed state to its next authorized transition;
- detect a missing terminal receipt, dead Worker process, timeout, or paused
  Adapter;
- invoke P5 recovery instead of repeating a failed contract;
- re-run an interrupted publication step when the immutable object already
  matches exactly;
- pause itself after terminal, human, inconsistent, or bounded-blocked states.

It may not:

- convert silence into success;
- auto-approve a scientific change;
- accept uncommitted or rejected Worker files;
- rotate the Claude session or model to hide an identity failure;
- perform more than one state transition per scheduled run;
- run concurrently with another tick for the same controller.

Applying a valid stop first blocks new controller work, then disables L0 before
L1, disables any bound retry trigger, terminates only identity-matching Worker
process groups with bounded TERM/KILL, and reports every residual. It deletes no
research artifact and grants no broader cleanup authority. Repeated stop calls
converge on the same receipt after a crash.

Transient Codex transport errors leave the last committed state intact and are
eligible for the next heartbeat. Three consecutive identical deterministic
blockers create `BLOCKED`, write a report, and pause the automation to avoid
unbounded token burn. A later explicit recovery may reactivate the same
controller without deleting its history.

## App visibility and operator controls

The L1 automation must be visible in Codex App Scheduled with a unique name that
includes the research run. Operators can:

- inspect recent heartbeat runs in the original research chat;
- pause or resume the watchdog;
- edit the cadence;
- manually trigger a run;
- follow the latest derived supervisor report.

P6 also exposes read-only `inspect-runtime` and `verify` commands plus explicit
`pause`, `resume`, and `stop` commands. `inspect-runtime` correlates canonical
state with discovered L0/L1/L2, process, log, and residual state without any
mutation and feeds the existing loopback Dashboard. `resume` verifies the
automation, target thread, full lineage, and current activation closure before
changing status to active.

## Interfaces

Implement `mvp/supervisory_controller.py` with commands:

```text
init
inspect
tick
verify
render-automation
bootstrap-assurance
l0-health-tick
record-worker-heartbeat
inspect-runtime
pause
resume
stop
```

Add closed JSON schemas for the supervisor manifest/state, tick receipt,
delegated engineering review, activation receipt, L0 observation, L2 heartbeat,
runtime snapshot, shutdown journal, and resource manifest. Add one durable
heartbeat prompt under `mvp/prompts/`. Keep L0/L1 registration and validation in
small deterministic helpers rather than embedding scheduler logic in
`SKILL.md`.

Update the installed MVP0 skill to describe P6, its automation boundary, its
human/scientific pause rule, and the exact one-tick semantics. Keep the skill
under 500 lines by moving detailed P6 commands and policy into the MVP README or
a direct reference.

## Error handling and security

Fail closed on:

- target thread, controller, automation, or run mismatch;
- altered manifests, schemas, prompts, or prior content-addressed objects;
- non-contiguous P3/P4/P5 lineage;
- changed scientific roots under delegated review;
- overlapping tick leases;
- stale or unknown Claude session/model identity;
- source HEAD or worktree provenance drift;
- an automation file that is missing required App-visible fields;
- any missing, unloaded, stale, mismatched, or legacy-only L0/L1/L2 layer;
- a shared L0/L1 scheduler identity or controller-command digest;
- L0 attempting to read research content or dispatch a model;
- heartbeat identity, order, contract, or process drift;
- pause/resume/stop without matching authority and restart-safe journal state.

Scheduled runs use unattended permissions. The prompt and controller use the
narrowest workspace and exact commands needed for the run. P6 does not grant a
generic shell allowlist to the Worker. The machine and user launchd domain must
remain available for L0. Codex App availability is required for L1 research
advancement but not for L0 health observation; the runtime snapshot reports
these dependencies separately rather than inferring health from either UI.

## Test strategy

Use strict red-green-refactor development. Tests use temporary repositories,
fake clocks, fake Claude transport, and temporary automation roots; they never
send real model requests except the final explicitly bounded field acceptance.

Required deterministic cases:

1. exact thread/run/controller binding succeeds;
2. any binding mismatch fails without mutation;
3. duplicate or overlapping heartbeat ticks are idempotent;
4. terminal P2 advances through P3 and P4 one tick at a time;
5. `PIVOT/RECOMPILE` advances into P5;
6. execution-only IR N+1 passes independent delegated review;
7. changed scientific roots force `WAITING_HUMAN` and pause automation;
8. delegated scope without the P6 review lineage is rejected by P2 and P5;
9. budget failure creates a successor rather than retrying the failed contract;
10. successor Adapter preserves predecessor and fixed-session identity;
11. interrupted object publication recovers only the exact object;
12. three identical deterministic blockers pause as `BLOCKED`;
13. STOP and completed outcomes pause the automation;
14. automation TOML parses, normalizes, and contains the exact
    `target_thread_id`;
15. P1–P5 regression suites remain green;
16. the installed Skill and bundled P6 resources match repository content.
17. activation fails until loaded, distinct L0/L1 plus L2 contract and all
    three functional probes agree;
18. removing L1 causes one deduplicated zero-model L0 restoration;
19. stale, wrong-session, wrong-process, or out-of-order L2 heartbeats fail
    closed and never alter scientific state;
20. read-only runtime inspection exposes missing/stale/mismatched layers without
    mutating repository, scheduler, or controller state;
21. crash-interrupted stop resumes exactly once, disables L0 before L1, targets
    only bound Workers, preserves research artifacts, and reports residuals;
22. L0 remains useful when Codex App and Claude foreground processes are absent.

## Field acceptance

After deterministic tests pass:

1. install the P6 preview into the shared `~/.agents` skill so Codex and Claude
   Code symlinked installations see the same version;
2. initialize a P6 supervisor for the existing Fixed-Wing Visual Guidance run;
3. register one ten-minute L1 thread heartbeat bound to
   `019fc053-ab31-7333-b5da-85b03372ec24`;
4. register one independent L0 launchd health service and freeze the L2
   heartbeat contract;
5. execute the non-due L1 probe, destructive-but-restored L0-to-L1 recovery
   drill, and L2 conformance heartbeat, then commit one activation receipt;
6. verify App-visible L1 plus loaded/distinct L0 and current L2 evidence through
   read-only runtime inspection;
7. run one bounded manual heartbeat tick;
8. observe one App-scheduled heartbeat returning to the same chat;
9. prove it advances from the current durable state without replaying the
   failed `$2` contract;
10. stop one disposable acceptance registration and prove ordered exact-once
    cleanup with no undeclared residuals;
11. leave the real automation active only if the next state is authorized and healthy;
   otherwise leave it paused with an exact report.

Success means the real target chat is correctly bound, the independent
L0/L1/L2 closure is active and observable, deterministic recovery and stop
drills pass, and the Host can resume one authorized transition from durable
state. It does not yet prove 24-hour or 7-by-24 stability.
