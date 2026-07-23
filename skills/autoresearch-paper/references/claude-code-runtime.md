---
name: claude-code-runtime
description: Claude Code target Harness, MiniMax M3 workers, and sparse Codex gates.
---

# Claude Code Runtime

Claude Code is the canonical Harness entry point. The deterministic controller
is `scripts/harness-runtime.py`; it dispatches bounded MiniMax M3 work through
`claude -p` and requests Codex advice through `codex exec` only at CP-01 through
CP-04. The primary path has no `mavis` executable, daemon, instruction-set, or
fallback dependency. MAVIS appears only behind explicit `--legacy-mavis`
compatibility flags.

## Authority

- Model output is evidence, never lifecycle, waiver, evaluator, or cleanup
  authority.
- Human authority is an expiring HMAC-SHA256 record signed with a user-owned
  key file of at least 32 bytes and POSIX mode `0600`.
- The controller owns state transitions, hash checks, budget reservation,
  replay protection, and append-only audit records.
- Mutable snapshots use atomic replacement. Successful audit appends are
  flushed and fsynced.

## Freeze Policy

```bash
python3 references/scripts/harness-runtime.py init-policy \
  --plan-dir PLAN --worker-model MiniMax-M3 \
  --worker-max-budget-usd 1.00 --frontier-model FRONTIER_MODEL \
  --frontier-reasoning-effort xhigh --max-frontier-calls 4 \
  --max-frontier-input-tokens 80000 --max-frontier-output-tokens 20000 \
  --scientific-pivot-threshold 2
```

The immutable `state/model_policy.json` pins the Claude runtime, low-cost
worker family, per-worker USD cap, frontier model, four-call default budget,
token budgets, and scientific pivot threshold. A changed policy hash pauses a
frontier request.

## Bounded Worker Contract

Task contracts must contain a closed output schema, `allowed_write_paths: []`,
closed `artifact_outputs` declarations (`artifact_id`, normalized `path`,
`content_field`, `max_bytes`, and `capability: {"class": ...}`), and
`completion_check: {"type":"output_schema","assertion":"valid"}`.
Workers return content/hash proposals only; the controller revalidates and
atomically materializes them with `promote-worker-artifacts`.
Without a writing gate, the only capability class is `research-intermediate`
and the exact destination root is
`artifacts/intermediate/<normalized-task-id>/`. With the exact frozen gate,
the sole declaration is `paper_deliverable`, class `paper-deliverable`, at
`artifacts/paper/paper.md`. Promotion revalidates the frozen contract/status,
the gate's full verdict/waiver, audit, transition, and artifact chain, the exact
authorized candidate as one writer input, class, and namespace; aliases,
unrelated inputs, and class/path drift have no authority.
Allowed tools are limited to `Read`, `Glob`, `Grep`, `WebSearch`, and
`WebFetch`. Timeout is 1..86400 seconds.

```bash
python3 references/scripts/harness-runtime.py dispatch-worker \
  --plan-dir PLAN --task-contract task.json --context-capsule CAPSULE
python3 references/scripts/harness-runtime.py promote-worker-artifacts \
  --plan-dir PLAN --worker-run-id RUN
python3 references/scripts/harness-runtime.py commit-durable-worker-result \
  --plan-dir PLAN --worker-run-id RUN
python3 references/scripts/harness-runtime.py inspect-worker \
  --plan-dir PLAN --worker-run-id RUN
python3 references/scripts/harness-runtime.py wait-worker \
  --plan-dir PLAN --worker-run-id RUN --deadline-seconds 60
python3 references/scripts/harness-runtime.py send-worker-message \
  --plan-dir PLAN --worker-run-id RUN --message "advisory text"
```

Runs persist under `state/worker_runs/<run-id>/`. Dispatch and promotion require
CP-01 `approve_execution`. Messages are durable, advisory, and queued for the
next controller observation; they are not a live channel to an executing
process. `wait-worker` polls every 100ms and
returns non-zero for `FAILED`, `PAUSED`, `CANCELLED`, or deadline expiry.

On the production durable path, `--context-capsule` is required by the
controller procedure. The runtime revalidates that the capsule is the current
claimed work unit and that its task contract and complete purpose-bearing input
manifest exactly match the worker contract. Promotion repeats that validation.
Only the immutable controller promotion receipt becomes durable work-unit
evidence; worker output never advances the task graph directly.

## Authenticated Human Actions

Allowed actions are `pause`, `resume`, `stop`, `cancel_worker`,
`waive_acceptance`, `override_acceptance`, `cleanup_resource`, and
proposal-only `authorize_evaluator_change`.

```bash
python3 references/scripts/harness-runtime.py create-human-action \
  --plan-dir PLAN --plan-id PLAN_ID --action pause \
  --key-file KEY --expires-in 300
python3 references/scripts/harness-runtime.py apply-human-action \
  --plan-dir PLAN --record RECORD --key-file KEY --expected-action pause
```

The signed payload contains only schema version, record ID, plan ID, action,
32-byte URL-safe nonce, issue/expiry times, actor, key ID, and details. The
signature is lowercase HMAC-SHA256 over canonical compact JSON. Application
checks signature, key, plan, action arguments, UTC expiry, and unused
`(record_id, nonce)` before mutation. Application uses a PREPARED/COMMITTED
journal, so restart rolls forward the exact bound record without accepting
different bytes. An exact retry carrying the same durable operation ID after
the committed mutation returns the same receipt idempotently; an unbound replay
or a fresh operation ID is rejected. The same inner-journal binding applies to
owned cleanup. Downstream gates consume immutable applied receipts
present in the audit, never pending signed records.

## Gated Learning

Read `learning-promotion-contract.md` before promoting persistent learning.
`promote-episode-memory` separates skill defects from execution lapses and
requires replay, held-out/regression validation, and independent audit.
`promote-learning-proposal` revalidates that memory and requires a second
replay/validation plus a fresh audit. Results are proposal-only receipts and
never mutate source files. Evaluator proposals additionally consume an applied
`authorize_evaluator_change` human receipt bound to the exact proposal hash.

`cancel-worker` is an authenticated alias requiring the same run ID in the
record and command. Waiver and cleanup actions produce immutable receipts.
Compatibility wrappers `pause-plan.sh`, `resume-plan.sh`, and `stop-plan.sh`
require `--record` and `--key-file`.

## Evaluator and Writing Gate

```bash
python3 references/scripts/harness-runtime.py freeze-evaluator \
  --plan-dir PLAN --execution-receipt CALIBRATION_RECEIPT
python3 references/scripts/harness-runtime.py run-evaluator \
  --plan-dir PLAN --evaluator evaluator.py --evidence evidence.json \
  --candidate candidate.md --purpose candidate
python3 references/scripts/harness-runtime.py record-evaluator-verdict \
  --plan-dir PLAN --execution-receipt CANDIDATE_RECEIPT \
  --candidate-id candidate-1
python3 references/scripts/harness-runtime.py check-scientific-acceptance \
  --plan-dir PLAN --verdict STORED_VERDICT
python3 references/scripts/harness-runtime.py check-writing-gate \
  --plan-dir PLAN --tier conference --verdict STORED_VERDICT
```

The declarative evaluator reads a finite metric only from the candidate
artifact. Plan-global evidence remains frozen context and cannot substitute a
candidate-independent value into a candidate verdict.

The controller snapshots evaluator materials outside worker-owned namespaces,
executes the evaluator, and derives metric, measured value, and PASS/FAIL from
immutable execution receipts. Scientific acceptance replays that chain and
requires current unattended admission before writing. The frozen contract binds the
calibration execution and the exact CP-02-audited, closed `metric_contract`;
callers cannot independently supply metric, operator, or threshold.
Changed evaluator, evidence,
candidate, threshold, or contract blocks writing. Bare
`state/research_acceptance.md` strings have no authority. An authenticated
applied `waive_acceptance` receipt is accepted only when it binds the tier,
candidate, evaluator contract, and scope; pending records are rejected.
Negative-result waivers are arxiv-only. Every tier requires the applied CP-04
`prewriting_final_evidence` transition and writes a gate audit.

### Evaluator admission for unattended autonomy

Conference and journal-q1 plans with `execution_mode: unattended` remain
blocked until the deterministic controller writes a current evaluator
admission receipt:

```bash
python3 references/scripts/harness-runtime.py admit-evaluator \
  --plan-dir PLAN --contract evaluator-admission.json \
  --evaluator EVALUATOR --authority-identity AUTHORITY \
  --input-manifest INPUTS --validation-identity VALIDATION \
  --replay-identity REPLAY --regression-suite REGRESSION \
  --allowed-search-space SEARCH_SPACE
python3 references/scripts/harness-runtime.py check-autonomy-eligibility \
  --plan-dir PLAN
```

The contract follows `evaluator-admission.schema.json`. Admission verifies the
evaluator class, authority identity, immutable input manifest, validation or
held-out identity, identical replay verdicts, a passing regression suite,
allowed search space, and an applicable complexity identity or explicit
not-applicable rationale. A human-review class cannot admit unattended
autonomy. `external_readonly` authority requires both the evaluator and
authority artifact to be filesystem read-only; `controller_owned` authority
must bind the canonical frozen evaluator contract.

The durable trigger, task-graph advance, work-unit application, and tick runner
all revalidate the current admission. Any evaluator, authority, input,
validation, replay, regression, search-space, complexity, graph, or receipt
drift appends an invalidation audit and blocks before another result is
applied. A finite candidate value or LLM review by itself creates no admission.

## Typed Failures and Patrol

```bash
python3 references/scripts/harness-runtime.py record-failure \
  --plan-dir PLAN --class scientific_no_improvement \
  --direction DIRECTION.json --verdict STORED_FAIL_VERDICT --source evaluator
python3 references/scripts/harness-runtime.py pivot-eligibility --plan-dir PLAN
python3 references/scripts/harness-runtime.py schedule-patrol \
  --plan-dir PLAN --interval-seconds 300
python3 references/scripts/harness-runtime.py run-patrol \
  --plan-dir PLAN --stale-seconds 7200
python3 references/scripts/harness-runtime.py check-research-integrity \
  --plan-dir PLAN
```

Failure classes are `runtime_stall`, `implementation_failure`,
`scientific_no_improvement`, `duplicate_direction`, and
`verifier_rejection`, plus controller-detected `goal_drift` and
`evaluator_integrity`. Duplicate `(class,fingerprint)` pairs are idempotent.
The controller normalizes scientific direction descriptors, computes their
hashes, and binds them to live candidates and canonical FAIL verdicts. Only
distinct validated direction hashes enable CP-03. Patrol is
file-backed and deterministic; stale workers increment only `runtime_stall`.
Production advance/application boundaries automatically record detected
goal/evaluator integrity drift with isolated routes and counters.

## Durable Production Loop

The M2 durable loop is separate from the closed M1 conformance fixture. It
registers a launchd-backed external wake-up, claims each tick under a durable
generation/lease, advances an immutable-revision task graph, and journals one
fresh context capsule before a worker result can be applied.

```bash
python3 references/scripts/harness-runtime.py init-durable-plan \
  --plan-dir PLAN --graph PLAN/durable-plan.json
python3 references/scripts/harness-runtime.py register-durable-trigger \
  --plan-dir PLAN --schedule-id research_loop --interval-seconds 300 \
  --jitter-seconds 30 --session-budget-seconds 1800 \
  --human-escalation-after-seconds 900 --lease-seconds 300
python3 references/scripts/harness-runtime.py run-durable-tick \
  --plan-dir PLAN --schedule-id research_loop
python3 references/scripts/harness-runtime.py advance-durable-plan \
  --plan-dir PLAN
python3 references/scripts/harness-runtime.py apply-work-unit-result \
  --plan-dir PLAN --capsule CAPSULE --result CONTROLLER_RESULT
python3 references/scripts/harness-runtime.py rebuild-durable-projection \
  --plan-dir PLAN
```

`durable-plan.json` freezes plan identity, target tier, attended/unattended
mode, objective, constraints, evaluator, task contracts, dependencies, and
input hashes. Canonical state lives as immutable numbered revisions with an
append-only event/evidence chain.
`projection.json` is disposable and rebuildable; it exposes objective, phase,
evidence, blockers, approvals, and next action but never becomes authority.

The scheduler adapter writes a hash-bound launchd plist and registration
receipt under `state/durable_loop/schedules/`. A schedule file alone is not a
registration. Registration succeeds only after the external scheduler accepts
the service; removal requires an applied authenticated `stop` receipt.
Concurrent deliveries of one tick produce one current claim. An expired claim
advances to one new generation; an active claim remains pending.

Each capsule binds one task and canonical state revision to the live objective,
constraints, evaluator, task contract, inputs, prior directions, and evidence.
Goal, evaluator, task, input, or revision drift blocks application. Worker
output remains evidence and is applied only through the controller-owned
`apply-work-unit-result` command.

Guardian observations use `guardian-observation.schema.json`, which contains
only schedule, worker, and controller liveness metadata. Extra
research-content fields fail closed. Guardian lifecycle requests are valid
only when `guardian-validate-lifecycle` revalidates an already-applied
authenticated pause/resume/stop receipt; Guardian never receives lifecycle
authority. Liveness proposals have no effect until
`apply-guardian-proposal` revalidates live metadata and applies one registered
`guardian-recovery-v1` deterministic controller policy.

Tests use a local fake `launchctl`; they do not register a live service. Actual
fault injection and multi-session soak remain T008 acceptance work.

## Sparse Codex Checkpoints

The registry and dependent transitions are fixed:

| Checkpoint | Subtype | Allowed recommendation | Transition |
|---|---|---|---|
| CP-01 | — | `accept` | `approve_execution` |
| CP-02 | — | `accept` | `freeze_evaluator` |
| CP-03 | — | `pivot` or `repair` | `authorize_structural_pivot` |
| CP-04 | `acceptance_dispute` | `accept` | `resolve_acceptance_dispute` |
| CP-04 | `prewriting_final_evidence` | `accept` | `start_writing` |

For a checkpoint that is itself a durable work unit, derive the request from
the current capsule. Do not reconstruct its context from chat history:

```bash
python3 references/scripts/harness-runtime.py create-durable-frontier-request \
  --plan-dir PLAN --context-capsule CAPSULE --checkpoint CP-04 \
  --checkpoint-subtype acceptance_dispute --attempt 1 \
  --objective "resolve bounded evidence dispute" \
  --decision-required resolve_acceptance_dispute \
  --max-input-tokens 20000 --max-output-tokens 5000
python3 references/scripts/harness-runtime.py send-frontier-request \
  --plan-dir PLAN --request-id FAR_ID
python3 references/scripts/harness-runtime.py validate-frontier-response \
  --plan-dir PLAN --request-id FAR_ID
python3 references/scripts/harness-runtime.py apply-frontier-response \
  --plan-dir PLAN --request-id FAR_ID \
  --dependent-transition resolve_acceptance_dispute \
  --controller-note "bounded evidence accepted"
python3 references/scripts/harness-runtime.py commit-durable-frontier-result \
  --plan-dir PLAN --request-id FAR_ID
```

The capsule must expose exactly the registered checkpoint evidence roles.
Create, send, validate, and apply recheck the immutable request/capsule
correlation. Codex remains read-only and advisory: durable completion consumes
the controller-issued dependent-transition receipt, never the response itself.
The commit journal recovers an applied work-unit result without duplication.

```bash
python3 references/scripts/harness-runtime.py create-frontier-request \
  --plan-dir PLAN --plan-id PLAN_ID --checkpoint CP-01 \
  --objective "audit plan" --decision-required approve_execution \
  --artifact brief.md::normalized_brief \
  --artifact execution.json::execution_plan \
  --artifact risk.json::risk_budget \
  --max-input-tokens 20000 --max-output-tokens 5000
python3 references/scripts/harness-runtime.py send-frontier-request \
  --plan-dir PLAN --request-id FAR_ID
python3 references/scripts/harness-runtime.py reconcile-frontier-request \
  --plan-dir PLAN --request-id FAR_ID
python3 references/scripts/harness-runtime.py validate-frontier-response \
  --plan-dir PLAN --request-id FAR_ID
python3 references/scripts/harness-runtime.py apply-frontier-response \
  --plan-dir PLAN --request-id FAR_ID \
  --dependent-transition approve_execution --controller-note "accepted"
python3 references/scripts/harness-runtime.py assert-transition \
  --plan-dir PLAN --plan-id PLAN_ID --transition approve_execution
```

Responses bind plan ID, checkpoint, subtype, request hash, canonical context
manifest hash, model, and observed transport usage. Apply is exact-once and
writes a transition receipt. `assert-transition` rechecks request, response,
context, and every current artifact hash after restart. The generic
`create-frontier-request` form remains available for non-durable gates such as
the initial CP-01 approval.

Each checkpoint enforces its exact evidence-role profile. Responses require
`status=completed`, no blockers or critical findings, and evidence citations
bound to the frozen manifest. A per-request send claim permits one transport;
`SENT`/`WAITING` reconcile from durable raw response and event files without
redelivery. Malformed raw output becomes `INVALID` then `PAUSED`. `PAUSED` and
`EXPIRED` requests are never redelivered. A retry uses a new request ID,
incremented attempt, deadline, and reservation. Expire an overdue request with:

```bash
python3 references/scripts/harness-runtime.py expire-frontier-request \
  --plan-dir PLAN --request-id FAR_ID --now 2026-07-18T00:00:00Z
```

## Owned Cleanup

```bash
python3 references/scripts/harness-runtime.py remove-resource \
  --plan-dir PLAN --resource-id ID --ownership-token TOKEN \
  --authorization APPLIED_CLEANUP_RECEIPT
```

Only an existing regular non-symlink file inside the plan can be removed. Its
manifest entry must be `ephemeral:true`, run-scoped, exact-path bound, and
authorized by an applied `cleanup_resource` record. The record binds the
ownership generation, content hash, and filesystem identity observed at
authorization time. Directories, shared files, path escapes, token mismatch,
recreation, replay, and absent authorization fail closed. The token is SHA-256
of `plan_id + NUL + normalized_path + NUL + ownership_generation`.

Plan-level stop never grants manifest-wide deletion. It reports residuals.
Every removal needs its own applied `cleanup_resource` receipt bound to the
current resource generation and consumed once; aggregate destruction is
legacy-only.

## M1 Closed Conformance Entry

```bash
python3 references/scripts/run-claude-harness.py \
  --plan-dir PLAN \
  --workflow references/canonical-conformance-workflow.json \
  --inputs PLAN/control/canonical-conformance-inputs.json
```

The runner accepts only the closed `claude-research-conformance-v1` fixture.
Its packaged 40-step sequence exercises CP-01, worker promotion, CP-02/freeze,
prebuilt scientific-failure and dispute branches, CP-03, final evidence,
writing, patrol, stop, and per-resource cleanup. This is M1 conformance
evidence, not a general topic-to-paper trigger; the state-driven research loop
remains part of integrated cutover. The runner writes PREPARED before every
subprocess and supplies a stable operation ID. External delivery commands use
dedicated ambiguity reconciliation; local commands re-enter only with the
identical request and converge through idempotency or their command-owned
recovery journal if the runner dies before recording COMMITTED.
Arbitrary or incomplete conformance lists and missing terminal artifact
classes are rejected. The durable production loop above does not reinterpret
this fixture or its M1 authority evidence.

## Errors and Recovery

- Contract, authentication, transport, budget, runtime, or correlation errors:
  exit 2 with one actionable JSON error.
- Writing gate blocked: exit 20.
- Structural pivot validation blocked through the compatibility guard: exit 21.
- Frontier files under `state/frontier/` and worker files under
  `state/worker_runs/` reconstruct status after process or Claude session loss.
- Tests use temporary directories and local executable fakes; they make no
  network or paid model calls.
