# P6 Supervisory Controller and Codex Thread Watchdog

Status: approved design

Date: 2026-08-02

## Objective

Add a bounded P6 control layer above the implemented MVP-0 P1–P5 transactions.
P6 must keep one research run moving without requiring a person to send
"continue" after every terminal Codex turn. It must use a Codex scheduled task
inside the existing research chat, appear in the Codex App Scheduled view, and
bind exactly one automation to one Codex thread and one research run.

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
- Codex thread-heartbeat automation registration;
- automatic recovery from a completed or interrupted Host turn;
- automatic delegated review for execution-only Research IR revisions;
- automatic creation of the next authorized P2 lineage;
- explicit pause, terminal, and human-review states.

P6 does not add:

- a second research truth outside the P1–P5 stores;
- a generic process daemon or system `cron`/`launchd` supervisor;
- a Dashboard or paper-writing loop;
- automatic modification of scientific claims, metrics, baselines, fairness,
  falsification, or safety boundaries;
- silent retry of the same failed Worker contract;
- promotion of rejected Worker changes into accepted source state.

The Legacy v0.20 Harness remains isolated. P6 uses only the MVP-0 P1–P5
contracts and Codex scheduled tasks.

## Chosen architecture

Use a Codex scheduled task inside the existing chat, backed by a deterministic
P6 controller.

```text
Codex App Scheduled
  -> thread heartbeat (exact target_thread_id)
  -> durable prompt (exact controller path and identity)
  -> supervisor tick (one transition only)
  -> P2 / P3 / P4 / P5 / delegated review / child P2
  -> immutable tick receipt and updated canonical state
```

Rejected alternatives:

1. A standalone scheduled task that later relays to the research chat adds a
   second chat, loses the original context, and needs an extra thread-messaging
   bridge.
2. A system cron or launchd job cannot be managed from the Codex App and does
   not satisfy the requested product surface.

The Codex manual explicitly distinguishes standalone scheduled tasks from
scheduled tasks inside a chat. P6 uses the latter because continuity with the
existing research context is required.

## Canonical supervisor store

Create one store outside the source repository:

```text
<run>/supervisor/
├── supervisor-manifest.json       # immutable, mode 0444
├── supervisor-state.json          # canonical mutable state
├── ticks.jsonl                    # append-only ordered tick index
├── objects/sha256/<digest>.json   # immutable tick and review objects
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
- automation cadence and engineering delegation policy;
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

## Codex automation binding

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
not visible. Do not register a system crontab entry.

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

The outer watchdog is the Codex thread heartbeat. The inner watchdog is the P6
tick's deterministic inspection of the current Worker and durable stores.

The watchdog may:

- resume the exact target chat after a Host turn completes;
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

Transient Codex transport errors leave the last committed state intact and are
eligible for the next heartbeat. Three consecutive identical deterministic
blockers create `BLOCKED`, write a report, and pause the automation to avoid
unbounded token burn. A later explicit recovery may reactivate the same
controller without deleting its history.

## App visibility and operator controls

The automation must be visible in Codex App Scheduled with a unique name that
includes the research run. Operators can:

- inspect recent heartbeat runs in the original research chat;
- pause or resume the watchdog;
- edit the cadence;
- manually trigger a run;
- follow the latest derived supervisor report.

P6 also exposes read-only `inspect` and `verify` commands plus explicit `pause`
and `resume` commands. `resume` verifies the automation, target thread, and full
lineage before changing status to active.

## Interfaces

Implement `mvp/supervisory_controller.py` with commands:

```text
init
inspect
tick
verify
render-automation
pause
resume
```

Add closed JSON schemas for the supervisor manifest/state, tick receipt, and
delegated engineering review. Add one durable heartbeat prompt under
`mvp/prompts/`. Keep registration normalization in a small deterministic helper
rather than embedding TOML generation in `SKILL.md`.

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
- an automation file that is missing required App-visible fields.

Scheduled runs use unattended permissions. The prompt and controller use the
narrowest workspace and exact commands needed for the run. P6 does not grant a
generic shell allowlist to the Worker. The Codex App must be running and the
machine available for local scheduled tasks; P6 reports this operational
dependency rather than claiming an external always-on service.

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

## Field acceptance

After deterministic tests pass:

1. install the P6 preview into the shared `~/.agents` skill so Codex and Claude
   Code symlinked installations see the same version;
2. initialize a P6 supervisor for the existing Fixed-Wing Visual Guidance run;
3. register one ten-minute thread heartbeat bound to
   `019fc053-ab31-7333-b5da-85b03372ec24`;
4. verify the automation TOML and visibility-compatible schema;
5. run one bounded manual heartbeat tick;
6. observe one App-scheduled heartbeat returning to the same chat;
7. prove it advances from the current durable state without replaying the
   failed `$2` contract;
8. leave the automation active only if the next state is authorized and healthy;
   otherwise leave it paused with an exact report.

Success means the real target chat is correctly bound and can resume one
authorized transition from durable state. It does not yet prove 24-hour or
7-by-24 stability.
