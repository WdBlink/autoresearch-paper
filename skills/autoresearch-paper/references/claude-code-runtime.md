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
- For staged research, `state/staged_research/v1/` is the sole runtime truth.
  `state/progress.json` and `state/research-dossier.md` are rebuildable,
  non-authoritative projections and are never controller inputs.
- Mutable snapshots use atomic replacement. Successful audit appends are
  flushed and fsynced.

Rebuild the operator views after repair or suspected hand editing without
changing canonical staged state:

```bash
python3 references/scripts/harness-runtime.py rebuild-staged-projections \
  --plan-dir PLAN
```

## Controller permission mode

Claude Code's interactive `auto` classifier is not an unattended execution
contract. It can deny a safe controller command before the Runtime launches a
Worker or frontier request, especially when an old session contains credential
text. Such a denial is an outer-Harness event and consumes no CP, stage-review,
retry, Gate, or Worker capacity.

For an unattended run, the operator must pre-authorize the top-level Claude
controller before starting the loop. Prefer exact Claude Code allow rules for
the Runtime command surface. For a bounded field acceptance in an isolated
research worktree, an explicitly authorized `--dangerously-skip-permissions`
controller session is also valid; it does not relax optimization-contract,
hash, budget, Gate, or signed-action enforcement inside the Runtime. Never
switch permission mode in response to model output alone, and never interpret
silence or a classifier denial as lifecycle authorization.

The isolated Codex reviewer is reduced with explicit feature disables and a
single-reviewer developer instruction. Do not emit `agents.enabled=false`:
current Codex parses `agents` as a role table and rejects that boolean child as
an invalid `AgentRoleToml`. Multi-agent and collaboration escape attempts remain
blocked by feature flags plus transport-event validation.

## Freeze Policy

```bash
python3 references/scripts/harness-runtime.py init-policy \
  --plan-dir PLAN --worker-model MiniMax-M3 \
  --worker-max-budget-usd 1.00 --frontier-model FRONTIER_MODEL \
  --frontier-reasoning-effort xhigh --frontier-transport chatgpt-https \
  --plan-audit-model gpt-5.6-sol \
  --plan-audit-reasoning-effort ultra \
  --max-frontier-calls 4 \
  --max-frontier-input-tokens 1400000 --max-frontier-output-tokens 60000 \
  --scientific-pivot-threshold 2
```

The immutable `state/model_policy.json` pins the Claude runtime, low-cost
worker family, per-worker USD cap, frontier model and transport, four-call
default budget, token budgets, scientific pivot threshold, and a distinct
mandatory top-level-plan reviewer. Every new plan pins CP-01 to Codex
`gpt-5.6-sol` at `ultra`; the general `frontier_model` remains available for
CP-02 through CP-04. A changed policy hash pauses a frontier request.
`chatgpt-https` is the verified default: the
runtime creates a request-local provider overlay with WebSockets disabled and
reuses the authenticated ChatGPT session. `codex-default` is available only
when the local Codex transport has been independently verified.

The input budget is observed transport usage, not only the request and artifact
bytes. Codex may inject its base instructions, available skill descriptions,
and tool context, then count the prefix again across tool turns. On the local
v0.14.1 acceptance environment a small CP-01 audit used 79k–130k input tokens.
Reserve at least 150k input tokens per ChatGPT frontier request. The runtime
rejects a plan-wide budget smaller than the per-request floor multiplied by
the declared call count. The final plan013 CP-01 acceptance was charged
294,915 input and 11,457 output tokens after transport-overrun reconciliation.
The operational field default is therefore 350k/15k per request and 1.4m/60k
for the default four-call plan; the 150k/5k values remain admission floors,
not recommended reservations.
New v0.16.1 policies freeze this measured envelope as
`chatgpt-frontier-v1`: each ChatGPT request must reserve at least 150k input
and 5k output tokens. The 150k floor covers the measured 79k–130k range with
bounded headroom; it is not inferred from the latest request's artifact bytes.
The send path rejects a smaller reservation before login preflight, budget
reservation, or transport launch. If the controller-observed terminal event is
exactly `0/0`, the request is charged its full reservation and records
`conservative_reservation_fallback`; zero is never treated as free usage.
The runtime disables optional plugins, apps, web search, multi-agent, and goals,
but Codex CLI 0.144.6 still discovers user skills. Cached-token discounts do
not change the controller's conservative token accounting.

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
proposal-only `authorize_evaluator_change`. Staged plans also support
`authorize_frontier_capacity`, a positive future-only capacity grant. The
initial `authorize_contract` may also carry bounded continuation authority for
exactly one explicitly named next stage.

```bash
python3 references/scripts/harness-runtime.py create-human-action \
  --plan-dir PLAN --plan-id PLAN_ID --action pause \
  --key-file KEY --expires-in 300
python3 references/scripts/harness-runtime.py apply-human-action \
  --plan-dir PLAN --record RECORD --key-file KEY --expected-action pause

python3 references/scripts/harness-runtime.py create-human-action \
  --plan-dir PLAN --plan-id PLAN_ID --action authorize_frontier_capacity \
  --key-file KEY --expires-in 300 \
  --add-frontier-calls 1 --add-frontier-input-tokens 350000 \
  --add-frontier-output-tokens 15000
python3 references/scripts/harness-runtime.py apply-human-action \
  --plan-dir PLAN --record RECORD --key-file KEY \
  --expected-action authorize_frontier_capacity --operation-id op_64_HEX

python3 references/scripts/harness-runtime.py create-human-action \
  --plan-dir PLAN --plan-id PLAN_ID --action authorize_contract \
  --key-file KEY --expires-in 300 --record-id RECORD_ID \
  --contract-version CONTRACT_VERSION --contract-sha256 CONTRACT_SHA256 \
  --stage-id STAGE_1 --stage-envelope-sha256 STAGE_1_SHA256 \
  --continuation-stage-id STAGE_2 --continuation-stage-limit 1
python3 references/scripts/harness-runtime.py apply-human-action \
  --plan-dir PLAN --record RECORD_PATH_FROM_CREATE_OUTPUT --key-file KEY \
  --expected-action authorize_contract --operation-id op_64_HEX
```

Pass the key pathname only through `--key-file`. An Agent must never read the
key bytes, implement HMAC itself, write a synthetic authorization JSON, or feed
the pending record directly to `init-staged-research`. The initializer accepts
only the `receipt.receipt_path` returned by `apply-human-action`. For capacity
v2, the first envelope must also declare
`stage_budget_and_stop.worker_dispatches >= 1`; the plan-global
`worker_dispatch_capacity` does not substitute for that per-stage quota.
There is no placeholder-replacement step: choose `RECORD_ID` first, write that
exact value into `optimization_contract.authorization_receipt_id`, freeze and
hash the contract, and pass the same value to
`create-human-action --record-id RECORD_ID`. Editing the contract after action
creation invalidates the signed hash; allowing the CLI to generate a random ID
creates an unresolvable binding unless that ID was already in the contract.

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

The bounded continuation object is valid only on the initial signed
`authorize_contract`. It fixes one `allowed_stage_ids` entry,
`max_automatic_crossings=1`, and `silence_is_approval=false`; omission means
there is no automatic continuation authority. A later chat message, lack of a
reply, timeout, or operator silence never grants approval.

Capacity grants bind the immutable model policy, current active stage and
envelope, and the exact global budget, staged capacity, and active-stage usage
ledger hashes. A PREPARED/COMMITTED journal rolls all three projections
forward exactly once. The grant only raises future capacity: it cannot name,
refund, validate, or rewrite a launched request, cannot move CP-01/CP-02/CP-04
slots, and cannot violate `remaining_calls >= mandatory_future_calls` for a
legacy capacity-v1 plan. Under capacity v2, the same frontier top-up changes no
per-stage or global Worker allowance, `STAGE-REVIEW` capacity, or CP slot.

## Worker input and recovery boundary

`dispatch-worker` verifies every input path and SHA-256 before any staged
Worker budget mutation. Claude Code receives only the declared read-only tools;
for verified inputs outside the plan cwd, the controller appends their distinct
parent directories through `--add-dir`. The content evaluator is not a hidden
test: `artifact_content_contracts` discloses the exact JSON fields, record
order, cardinality, line-grounding rule, and size bounds in the Worker prompt.
`--add-dir` is directory-granular read authority, not exact-file isolation.
Do not place undeclared secrets beside an authorized source; use an isolated
source directory when siblings are outside Worker authority. Only frozen
manifest paths and hashes may contribute accepted observations. Exact-copy
input sandboxes remain a separate hardening profile, not a v0.16.2 claim.

The scientific stage clock is reset when CP-01 authorizes Development, rather
than charging time spent waiting for frontier review. Recovery is deliberately
narrow. `reconcile-orphan-worker-budget` applies only when no run directory,
dispatch marker, or dispatch journal exists. A denied-input recovery requires
every frozen `Read` to be present in Claude's permission-denial evidence and
zero scientific records. Actual model usage remains in the immutable recovery
journal. Content errors after the complete contract is visible are genuine
Worker failures and are not refundable.

The shipped `source_inventory_v1` evaluator is versioned independently and
runs one positive plus five adversarial conformance cases. CP-01 binds the
exact evaluator implementation and conformance result. A one-time deterministic
alias normalizer is available only for a failed pre-disclosure proposal whose
controller-fault reconciliation is already committed; the original Worker run
remains `FAILED`, and the normalization receipt states the mixed provenance.

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
python3 references/scripts/harness-runtime.py check-figure-gate \
  --plan-dir PLAN --inventory out/figures/required-figures.json \
  --requirements state/figure-requirements.json
python3 references/scripts/harness-runtime.py check-writing-gate \
  --plan-dir PLAN --tier conference --verdict STORED_VERDICT \
  --figure-gate-receipt state/figure_gates/DECISION.json
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
`prewriting_final_evidence` transition and writes a gate audit. The CP-04
request must bind the current figure-gate receipt; the writing gate revalidates
its non-empty inventory, manifests, human output-bound reviews, and current
artifact hashes.

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

CP-01 is not a self-review. New staged plans bind an immutable human-owned
optimization contract, exactly one executable first-stage envelope, its
deterministic preflight, and named checkpoint capacity. These artifacts are
independently reviewed by the strongest Codex profile allowed by the frozen
policy (`gpt-5.6-sol`/`ultra` in this release). The review is advisory; only
the deterministic controller applies `approve_execution`. Legacy v0.15 plans
retain their normalized-brief, execution-plan, risk-budget, and
figure-requirements evidence profile.

The author-family field is declared provenance, not cryptographic model
attestation. The enforceable guarantee is that the exact frozen plan bytes are
reviewed by the independent Codex profile before execution.

For a checkpoint that is itself a durable work unit, derive the request from
the current capsule. Do not reconstruct its context from chat history:

```bash
python3 references/scripts/harness-runtime.py create-durable-frontier-request \
  --plan-dir PLAN --context-capsule CAPSULE --checkpoint CP-04 \
  --checkpoint-subtype acceptance_dispute --attempt 1 \
  --objective "resolve bounded evidence dispute" \
  --decision-required resolve_acceptance_dispute \
  --max-input-tokens 350000 --max-output-tokens 15000
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

For a new v0.17 staged plan, use capacity v2 and initialize only the first
executable stage:

Before this command, write caller-authored contract, envelope, evaluation,
capacity, and raw-preflight inputs under `PLAN/control/staged-inputs/`; place
their immutable review materials under `PLAN/control/review-materials/STAGE/`.
Do not create `PLAN/state/staged_research/v1/` yourself, even for an empty
directory or a proposed contract snapshot. `init-staged-research` is the only
publisher of that canonical namespace. If any manual write has already landed
there, abandon that initialization attempt and restart from a clean plan
identity rather than treating the bytes as controller authority.
Create and apply the `authorize_contract` action using the exact sequence in
Authenticated Human Actions above, then pass only the applied receipt path to
the initializer. Never manufacture that receipt in a helper script.

```bash
python3 references/scripts/harness-runtime.py init-staged-research \
  --plan-dir PLAN --plan-id PLAN_ID \
  --contract optimization-contract.json \
  --stage-envelope first-stage.json \
  --evaluation-profile evaluation-profile.json \
  --checkpoint-capacity checkpoint-capacity.json \
  --authorization-receipt state/human_actions/applied/OWNER_AUTH.json \
  --incumbent-sha256 INCUMBENT_SHA256
python3 references/scripts/harness-runtime.py preflight-staged-research \
  --plan-dir PLAN --preflight-inputs raw-preflight-evidence.json
python3 references/scripts/harness-runtime.py create-frontier-request \
  --plan-dir PLAN --plan-id PLAN_ID --checkpoint CP-01 \
  --objective "audit contract and first stage" \
  --decision-required approve_execution \
  --artifact state/staged_research/v1/contracts/CONTRACT.json::optimization_contract \
  --artifact state/staged_research/v1/stages/STAGE/envelope.json::first_stage_envelope \
  --artifact state/staged_research/v1/stages/STAGE/preflight.json::current_stage_preflight \
  --artifact state/staged_research/v1/checkpoint-capacity.json::checkpoint_capacity \
  --max-input-tokens 350000 --max-output-tokens 15000
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

The owner receipt must be a canonical applied `authorize_contract` action
binding the contract version/hash and first-stage ID/envelope hash. It may also
bind exactly one future stage ID using the continuation flags shown above; that
does not make the future envelope executable or bypass its later evidence,
compile, preflight, and authorization checks.
Every newly initialized or compiled stage must also carry a closed
`review_material_manifest`. Each entry is
`{id,path,sha256,purpose}`; `path` is canonical and relative to the plan,
cannot traverse a symlink, and must name a mode-0444 controller material.
Purposes exactly bind stage objective, allowed intervention, entry/exit
criteria, stage budget, required report schema, and stop policy (plus figure
requirements for a figure-production stage). Legacy v0.16 envelopes without
the manifest remain readable and idempotently replayable, but cannot be used
to create a new stage.
For the initial stage, the manifest additionally requires readable
`execution_plan`, `acceptance_evaluator`, `risk_and_stop_rules`, and
`figure_strategy` materials. CP-01 expands every bound material into its own
frozen `context_manifest` entry. Hash commitments alone are not substantive
review evidence.
`raw-preflight-evidence.json` contains only the truth table, statistical
design, train/evaluation matrix, conditional state machine, and current-stage
critical path. It cannot contain caller-authored pass/fail/not-applicable
labels; versioned Controller calculators derive and hash every verdict.

Responses bind plan ID, checkpoint, subtype, request hash, canonical context
manifest hash, model, and observed transport usage. Apply is exact-once and
writes a transition receipt. `assert-transition` rechecks request, response,
context, and every current artifact hash after restart. The generic
`create-frontier-request` form remains available for non-durable gates such as
the initial CP-01 approval. Its evidence profile is selected by versioned
staged state, so legacy v0.15 receipts remain readable.

After a candidate is frozen, the controller creates one logical Gate query.
Transport retries append attempt IDs under the same idempotency binding and
consume the independent retry ledger. `accept` promotes, `reject` retains the
incumbent, and `escalate` blocks. Every terminal decision appends evidence. A
terminal MiniMax-M3 report and fresh strongest-policy non-M3 review must exist
before `compile-next-stage` authorizes at most one next envelope.

Capacity v2 keeps five concerns non-fungible:

- each envelope's `stage_budget_and_stop.worker_dispatches` is the per-stage
  Worker quota;
- `worker_dispatch_capacity` is the plan-global Worker allowance;
- `stage_review_capacity` is reserved only for terminal `STAGE-REVIEW` calls;
- CP-01, CP-02, and CP-04 each have their own named slot, with CP-03 optional;
- Gate transport retry capacity remains independent.

A Worker dispatch must pass both the active stage quota and the global Worker
allowance. Spending or topping up one class cannot mint, refund, or transfer
another class. Legacy capacity v1 keeps existing-plan lifecycle and idempotent
replay compatibility; it is not valid as a v0.17 capacity template or as
automatic-crossing authority.

After Stage 1 has a canonical terminal Gate decision, persisted MiniMax report,
and fresh strongest-policy non-M3 `STAGE-REVIEW`, cross the single initially
authorized boundary with:

```bash
python3 references/scripts/harness-runtime.py advance-staged-research \
  --plan-dir PLAN \
  --stage-envelope stage-2.json \
  --preflight-inputs stage-2-preflight.json \
  --task-contract stage-2-first-worker.json \
  --authorized-evidence EVIDENCE_ID
```

The command derives a continuation receipt bound to the initial applied
authorization, source decision, MiniMax report, fresh strong review, and exact
next envelope. Its recoverable journal then performs compile → preflight →
authorize → start exactly one Stage 2 Worker. Replay returns the same run; it
does not start a second Worker. The bounded outcome stops at Worker start—it
does not establish Stage 2 completion or scientific success. Without that
initial explicit pre-authorization, use the existing signed
`reauthorize_stage` plus `compile-next-stage` path.

Each checkpoint enforces its exact evidence-role profile. Responses require
`status=completed` and evidence citations bound to the frozen manifest.
`block`/`revise` advice may retain blockers and critical findings as valid
advisory evidence; `accept` with either is a semantic inconsistency and cannot
unlock a transition. Observed over-budget usage and malformed responses have
separate PAUSED classifications. A per-request send claim permits one transport;
`SENT`/`WAITING` reconcile from durable raw response and event files without
redelivery. Malformed raw output becomes `INVALID` then `PAUSED`. `PAUSED` and
`EXPIRED` requests are never redelivered. A retry uses a new request ID,
incremented attempt, deadline, and reservation. Expire an overdue request with:

Before any reservation, the runtime verifies the Codex executable, `codex login
status`, the strict frontier response schema, and known model/transport
incompatibilities. It also passes `--skip-git-repo-check` because plan
directories are controller-owned evidence roots, not necessarily Git
worktrees. These deterministic failures write `preflight-failure.json` and do
not consume budget. If the controller crashes between the ledger reservation
and transport launch, retry or operator expiry reconciles that reservation
through immutable `budget-releases/*.intent.json` and matching receipt files.
Only a state that proves transport never started may be released; a
`SENT`/`WAITING` reservation remains charged. Once `SENT` is recorded,
stdout/stderr are streamed to durable files. A timeout, process interruption,
or missing raw response is outcome-uncertain: the reservation remains charged,
the request becomes `PAUSED`, and a retry requires a new request ID. Never edit
`budget.json` by hand. The transport timeout must be 1..86400 seconds and is
capped by the request's remaining frozen deadline. Upgrade-exhausted v0.14.0
plans must restart from a newly frozen plan.

There are two intentionally separate persistence paths. A frontier request
created from a durable context capsule may use
`commit-durable-frontier-result` after its registered controller transition.
A terminal `STAGE-REVIEW` is not a durable work-unit commit: it must bind the
canonical active contract, envelope, and immutable terminal stage report, then
persist through `record-strong-stage-review`. Creating `STAGE-REVIEW` while a
stage is still `CONTRACTED` fails before reservation and directs the operator
to CP-01 `approve_execution`. No command synthesizes or attaches a context
capsule after request creation.

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

## Fault, Soak, and Claim Acceptance

Read `fault-soak-acceptance-contract.md` for T008. The controller freezes the
seven-scenario profile, validates fault and multi-session evidence, and issues
only duration-bounded claim receipts through `start-acceptance-profile`,
`complete-acceptance-profile`, and `validate-acceptance-claim`. Short bounded
acceptance never implies 24h, 7×24, or full-cutover evidence.

The v0.17 release claim is only a bounded stage-crossing capability and
acceptance target: one first-stage terminal lineage through the start of one
second-stage Worker. It does not claim Stage 2 completion, scientific success,
24h or 7x24 stability, production readiness, or full cutover.

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
