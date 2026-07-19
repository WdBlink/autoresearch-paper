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
`content_field`, `max_bytes`), and
`completion_check: {"type":"output_schema","assertion":"valid"}`.
Workers return content/hash proposals only; the controller revalidates and
atomically materializes them with `promote-worker-artifacts`.
Allowed tools are limited to `Read`, `Glob`, `Grep`, `WebSearch`, and
`WebFetch`. Timeout is 1..86400 seconds.

```bash
python3 references/scripts/harness-runtime.py dispatch-worker \
  --plan-dir PLAN --task-contract task.json
python3 references/scripts/harness-runtime.py promote-worker-artifacts \
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

## Authenticated Human Actions

Allowed actions are `pause`, `resume`, `stop`, `cancel_worker`,
`waive_acceptance`, `override_acceptance`, and `cleanup_resource`.

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
different bytes. Downstream gates consume immutable applied receipts present
in the audit, never pending signed records.

`cancel-worker` is an authenticated alias requiring the same run ID in the
record and command. Waiver and cleanup actions produce immutable receipts.
Compatibility wrappers `pause-plan.sh`, `resume-plan.sh`, and `stop-plan.sh`
require `--record` and `--key-file`.

## Evaluator and Writing Gate

```bash
python3 references/scripts/harness-runtime.py freeze-evaluator \
  --plan-dir PLAN --execution-receipt CALIBRATION_RECEIPT \
  --operator gte --threshold 0.8
python3 references/scripts/harness-runtime.py run-evaluator \
  --plan-dir PLAN --evaluator evaluator.py --evidence evidence.json \
  --candidate candidate.md --purpose candidate
python3 references/scripts/harness-runtime.py record-evaluator-verdict \
  --plan-dir PLAN --execution-receipt CANDIDATE_RECEIPT \
  --candidate-id candidate-1
python3 references/scripts/harness-runtime.py check-writing-gate \
  --plan-dir PLAN --tier conference --verdict STORED_VERDICT
```

The controller executes the evaluator and derives metric, measured value, and
PASS/FAIL from immutable execution receipts. The frozen contract binds the
calibration execution, evaluator, evidence, metric, operator, and threshold.
Changed evaluator, evidence,
candidate, threshold, or contract blocks writing. Bare
`state/research_acceptance.md` strings have no authority. An authenticated
applied `waive_acceptance` receipt is accepted only when it binds the tier,
candidate, evaluator contract, and scope; pending records are rejected.
Negative-result waivers are arxiv-only. Every tier requires the applied CP-04
`prewriting_final_evidence` transition and writes a gate audit.

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
```

Failure classes are `runtime_stall`, `implementation_failure`,
`scientific_no_improvement`, `duplicate_direction`, and
`verifier_rejection`. Duplicate `(class,fingerprint)` pairs are idempotent.
The controller normalizes scientific direction descriptors, computes their
hashes, and binds them to live candidates and canonical FAIL verdicts. Only
distinct validated direction hashes enable CP-03. Patrol is
file-backed and deterministic; stale workers increment only `runtime_stall`.

## Sparse Codex Checkpoints

The registry and dependent transitions are fixed:

| Checkpoint | Subtype | Allowed recommendation | Transition |
|---|---|---|---|
| CP-01 | — | `accept` | `approve_execution` |
| CP-02 | — | `accept` | `freeze_evaluator` |
| CP-03 | — | `pivot` or `repair` | `authorize_structural_pivot` |
| CP-04 | `acceptance_dispute` | `accept` | `resolve_acceptance_dispute` |
| CP-04 | `prewriting_final_evidence` | `accept` | `start_writing` |

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
context, and every current artifact hash after restart.

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
authorized by an applied `cleanup_resource` record. Directories, shared files,
path escapes, token mismatch, and absent authorization fail closed. The token
is SHA-256 of `plan_id + NUL + normalized_path + NUL + ownership_nonce`.

Plan-level stop never grants manifest-wide deletion. Every removal needs its
own applied `cleanup_resource` receipt; aggregate destruction is legacy-only.

## Canonical Top-Level Entry

```bash
python3 references/scripts/run-claude-harness.py \
  --plan-dir PLAN --workflow canonical-flow.json
```

The workflow is closed and journaled, supports `${step_id.field}` references,
resumes completed steps without replay, and records expected consumer-first
blocks as negative conformance evidence.

## Errors and Recovery

- Contract, authentication, transport, budget, runtime, or correlation errors:
  exit 2 with one actionable JSON error.
- Writing gate blocked: exit 20.
- Structural pivot validation blocked through the compatibility guard: exit 21.
- Frontier files under `state/frontier/` and worker files under
  `state/worker_runs/` reconstruct status after process or Claude session loss.
- Tests use temporary directories and local executable fakes; they make no
  network or paid model calls.
