# P6 Supervisory Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a complete L0/L1/L2 Watchdog and supervisory controller that
advances one verified MVP-0 P1–P5 transition per L1 heartbeat, survives loss of
the foreground Host, and automatically approves only evidence-bound engineering
IR revisions.

**Architecture:** A new deterministic `supervisory_controller.py` owns one
canonical run state and append-only tick ledger while continuing to treat P1–P5
stores as their domain authorities. An independent zero-model launchd L0 checks
and repairs the exact scheduler binding; a Codex `kind = "heartbeat"` L1 targets
one exact thread and invokes the MVP0 skill; controller-owned L2 receipts prove
the fixed Claude/MiniMax Worker is alive. One immutable activation receipt binds
all three layers and their functional probes. Model judgment is supplied as
closed JSON to deterministic P6 publication commands, never hidden inside the
controller. Delegated engineering review has a new live approval scope and
receipt that P2/P5 must replay before accepting a child freeze.

**Tech Stack:** Python 3 standard library, JSON Schema Draft 2020-12, TOML
generation/validation with `tomllib`, plist generation/validation with
`plistlib`, macOS launchd, existing MVP-0 Python modules, `unittest`, Git, Codex
scheduled-task TOML.

## Global Constraints

- Keep the Legacy v0.20 Harness isolated; P6 imports only the MVP-0 P1–P5 modules.
- Bind one controller to exactly one `target_thread_id`, one absolute research run, and one immutable initial P1 lineage.
- Use `kind = "heartbeat"` and `target_thread_id` for L1. Register launchd only
  for the plan-bound, metadata-only L0 health supervisor; never use system cron
  or launchd to execute model-bearing research transitions.
- Require loaded, distinct L0/L1 identities, an L2 heartbeat contract, frozen
  intervals/thresholds, and successful L0/L1/L2 probes before unattended Worker
  dispatch.
- L0 may inspect only scheduler/controller/lease/Worker/heartbeat/resource
  metadata and must record `model_dispatches = 0` on every observation.
- Stop must converge exactly once, disable L0 before L1, target only
  identity-matching Workers, preserve research artifacts, and report residuals.
- Perform at most one durable state transition per scheduled heartbeat.
- Never retry the exact failed Worker contract, reset its worktree, accept rejected files, rotate its session UUID, or fall back from MiniMax-M3.
- Automatically approve only `/budget`, `/experiment_plan`, and evidence-only evaluator status/path/SHA bindings; preserve all scientific semantics byte-for-byte.
- Use `DELEGATED_ENGINEERING_REVIEW`; never use test-only `ENGINEERING_ACCEPTANCE` or fabricate `owner/*` identities.
- Require a fresh non-MiniMax Codex reviewer and deterministic policy validator before delegated freeze.
- Pause the automation on scientific changes, STOP, completion, inconsistent state, or three identical deterministic blockers.
- Default recurrence is `RRULE:FREQ=MINUTELY;INTERVAL=10`.
- The live acceptance target is thread `019fc053-ab31-7333-b5da-85b03372ec24` and run `/Users/wdblink/Research/runs/fwvg-mvp0-evaluator-20260802`.
- Do not claim 24-hour or 7-by-24 stability from P6 implementation or one field heartbeat.

---

## File map

- Create `skills/autoresearch-paper/mvp/supervisory_controller.py`: manifest/state/tick store, lease, phase derivation, one-tick transitions, automation rendering, CLI.
- Create `skills/autoresearch-paper/mvp/delegated_review.py`: engineering-root comparison, review publication/replay, delegated freeze evidence.
- Create `skills/autoresearch-paper/mvp/automation_registration.py`: deterministic thread-heartbeat TOML generation and validation.
- Create `skills/autoresearch-paper/mvp/runtime_assurance.py`: L0/L1/L2
  activation, functional probes, heartbeat replay, read-only inspection, and
  restart-safe shutdown.
- Create `skills/autoresearch-paper/mvp/l0_watchdog.py`: metadata-only L0 tick
  and narrow exact-L1 restoration.
- Create `skills/autoresearch-paper/mvp/launchd_registration.py`: deterministic
  plan-bound plist rendering, load-state discovery, registration, and removal.
- Create `skills/autoresearch-paper/mvp/prompts/codex-supervisor-heartbeat.md`: durable same-thread heartbeat procedure.
- Create four schemas under `skills/autoresearch-paper/mvp/schemas/`: supervisor manifest, supervisor state, supervisor tick, delegated engineering review.
- Create closed schemas for activation receipts, L0 observations, L2
  heartbeats, runtime snapshots, resource manifests, and shutdown journals.
- Create `skills/autoresearch-paper/tests/test_mvp_supervisory_controller.py`: state, transition, idempotence, blocker, automation, and cross-lineage tests.
- Create `skills/autoresearch-paper/tests/test_mvp_delegated_review.py`: root policy and approval-evidence tests.
- Create `skills/autoresearch-paper/tests/test_mvp_runtime_assurance.py`: L0/L1/L2
  activation, recovery, stale detection, inspection, stop, and crash-replay
  tests using a fake launchctl backend.
- Modify `skills/autoresearch-paper/mvp/research_compiler.py`: receipt v2 and delegated approval scope.
- Modify `skills/autoresearch-paper/mvp/recompile_loop.py`: replay delegated child freeze evidence.
- Modify `skills/autoresearch-paper/mvp/worker_adapter.py`: accept delegated freeze only through P6 review replay and add predecessor-bound session resume.
- Modify `skills/autoresearch-paper/mvp/README.md`, root `README.md`, setup/contract validators, and installed preview resources.

---

### Task 1: Thread automation registration and immutable supervisor foundation

**Files:**
- Create: `skills/autoresearch-paper/mvp/automation_registration.py`
- Create: `skills/autoresearch-paper/mvp/supervisory_controller.py`
- Create: `skills/autoresearch-paper/mvp/schemas/supervisor-manifest.schema.json`
- Create: `skills/autoresearch-paper/mvp/schemas/supervisor-state.schema.json`
- Create: `skills/autoresearch-paper/mvp/schemas/supervisor-tick.schema.json`
- Test: `skills/autoresearch-paper/tests/test_mvp_supervisory_controller.py`

**Interfaces:**
- Produces: `register.render_thread_automation(...) -> str`
- Produces: `register.validate_thread_automation(path: Path, *, expected_thread_id: str, expected_controller_id: str) -> dict[str, Any]`
- Produces: `supervisor.init_supervisor(...) -> dict[str, Any]`
- Produces: `supervisor.verify_supervisor(store_dir: Path) -> dict[str, Any]`
- Produces: CLI commands `init`, `verify`, `inspect`, and `render-automation`.

- [ ] **Step 1: Write failing binding and initialization tests**

Add tests that call the desired public functions before they exist:

```python
def test_thread_automation_binds_exact_target_and_is_app_parseable(self):
    rendered = registration.render_thread_automation(
        controller_id="mvp0-supervisor-0123456789abcdef",
        name="AutoResearch MVP0 · fwvg",
        prompt="Use $autoresearch-paper-mvp0 and run one exact tick.",
        target_thread_id="019fc053-ab31-7333-b5da-85b03372ec24",
        created_at_ms=1785632400000,
    )
    parsed = tomllib.loads(rendered)
    self.assertEqual(parsed["kind"], "heartbeat")
    self.assertEqual(parsed["status"], "ACTIVE")
    self.assertEqual(parsed["rrule"], "RRULE:FREQ=MINUTELY;INTERVAL=10")
    self.assertEqual(parsed["target_thread_id"], "019fc053-ab31-7333-b5da-85b03372ec24")

def test_supervisor_init_rejects_thread_or_run_mismatch(self):
    initialized = supervisor.init_supervisor(...literal fixture paths...)
    manifest = Path(initialized["manifest_path"])
    with self.assertRaisesRegex(supervisor.SupervisorError, "target thread"):
        supervisor.inspect_supervisor(
            store_dir=self.store,
            target_thread_id="019f0000-0000-0000-0000-000000000000",
            run_root=self.other_run,
        )
```

The production mutation caught is accepting a heartbeat delivered to the wrong Codex task or run.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
python3 -m unittest skills.autoresearch-paper.tests.test_mvp_supervisory_controller -v
```

Expected: import failure for missing `automation_registration` or `supervisory_controller`.

- [ ] **Step 3: Implement closed schemas and deterministic automation rendering**

Implement exact TOML quoting without external dependencies and require these keys:

```python
AUTOMATION_KEYS = {
    "version", "id", "kind", "name", "prompt", "status", "rrule",
    "target_thread_id", "created_at", "updated_at",
}

def render_thread_automation(*, controller_id: str, name: str, prompt: str,
                             target_thread_id: str, created_at_ms: int,
                             updated_at_ms: int | None = None,
                             status: str = "ACTIVE",
                             rrule: str = "RRULE:FREQ=MINUTELY;INTERVAL=10") -> str:
    ...
```

Reject non-UUID-shaped thread ids, non-`heartbeat` files, unknown fields, wrong controller ids, relative automation paths, and recurrence rules outside minute intervals 5–60.

- [ ] **Step 4: Implement supervisor initialization and replay**

Use immutable `supervisor-manifest.json`, canonical `supervisor-state.json`, append-only `ticks.jsonl`, and content-addressed tick objects. The initial state is `READY`, transition sequence `0`, and binds the verified P1 freeze plus current P2–P5 store paths. Use atomic replace for mutable state and mode `0444` for immutable objects.

- [ ] **Step 5: Verify GREEN and replay failures**

Run the Task 1 suite. Add and pass literal tamper cases for manifest bytes, automation target mismatch, unknown state keys, and orphan tick objects.

- [ ] **Step 6: Commit Task 1**

```bash
git add skills/autoresearch-paper/mvp/automation_registration.py \
  skills/autoresearch-paper/mvp/supervisory_controller.py \
  skills/autoresearch-paper/mvp/schemas/supervisor-*.schema.json \
  skills/autoresearch-paper/tests/test_mvp_supervisory_controller.py
git commit -m "feat: add P6 supervisor foundation"
```

---

### Task 2: Idempotent one-tick state machine and blocker fuse

**Files:**
- Modify: `skills/autoresearch-paper/mvp/supervisory_controller.py`
- Modify: `skills/autoresearch-paper/tests/test_mvp_supervisory_controller.py`

**Interfaces:**
- Produces: `derive_phase(manifest: Mapping[str, Any], state: Mapping[str, Any]) -> str`
- Produces: `tick(store_dir: Path, *, target_thread_id: str, run_root: Path, action_input: Path | None = None) -> dict[str, Any]`
- Produces: CLI command `tick`.

- [ ] **Step 1: Write failing transition, idempotence, and overlap tests**

Cover the literal progression `NEEDS_P3 -> NEEDS_P4 -> NEEDS_P5`, asserting one sequence increment per call. Call the same tick twice over the same already-applied input and assert the second response is `already_applied: true` with no JSONL append. Hold the lease in one process and assert a second mutation fails with `tick lease is already held`.

Add a blocker test using the same literal blocker digest three times:

```python
self.assertEqual(first["phase"], "READY")
self.assertEqual(second["phase"], "READY")
self.assertEqual(third["phase"], "BLOCKED")
self.assertTrue(third["automation_pause_required"])
```

The production mutations caught are applying two state changes in one heartbeat, duplicate append, and infinite deterministic retry.

- [ ] **Step 2: Run selected tests and verify RED**

Expected: missing `tick`/lease behavior, not fixture setup failure.

- [ ] **Step 3: Implement one-tick publication**

Use `fcntl.flock(LOCK_EX | LOCK_NB)`. A tick verifies the prior store, calculates exactly one transition, publishes one immutable receipt, appends one index row, and atomically replaces state. Keep transition handlers in a closed dictionary keyed by the current phase; do not loop handlers.

- [ ] **Step 4: Implement blocker counting and automatic pause intent**

Store only the latest blocker digest and consecutive count. A different digest resets the count to one. Count three sets `BLOCKED`; terminal/human/blocked results expose `automation_pause_required = true` without directly editing unrelated automations.

- [ ] **Step 5: Run Task 2 and Task 1 suites**

Expected: all P6 tests pass, no warning output.

- [ ] **Step 6: Commit Task 2**

```bash
git add skills/autoresearch-paper/mvp/supervisory_controller.py \
  skills/autoresearch-paper/tests/test_mvp_supervisory_controller.py
git commit -m "feat: add idempotent P6 ticks"
```

---

### Task 3: Delegated engineering review and freeze scope

**Files:**
- Create: `skills/autoresearch-paper/mvp/delegated_review.py`
- Create: `skills/autoresearch-paper/mvp/schemas/delegated-engineering-review.schema.json`
- Create: `skills/autoresearch-paper/tests/test_mvp_delegated_review.py`
- Modify: `skills/autoresearch-paper/mvp/research_compiler.py`
- Modify: `skills/autoresearch-paper/tests/test_mvp_research_compiler.py`

**Interfaces:**
- Produces: `review.validate_engineering_delta(parent, candidate, evidence) -> tuple[str, ...]`
- Produces: `review.publish_review(...) -> dict[str, str]`
- Produces: `review.verify_review(receipt_path: Path, store_dir: Path) -> dict[str, Any]`
- Extends: `compiler.freeze(..., approval_scope="DELEGATED_ENGINEERING_REVIEW", delegated_review_receipt=Path(...))`.

- [ ] **Step 1: Write failing allowlist and forbidden-root tests**

Use literal parent/candidate IR fixtures. Prove `/budget` and `/experiment_plan` pass. Prove changing `/central_claim`, metric threshold, baseline id, evaluator argv, falsification, forbidden changes, or safety content fails. Prove evaluator `status`, `implementation_artifact`, and `implementation_sha256` pass only when the review evidence binds a verified P3 artifact hash and all evaluator semantics remain equal.

Add a freeze test requiring distinct `codex/compiler`, `codex/frontier-reviewer`, `codex/revision`, and `codex/frontier-approver` identities. A bare scope string without the review receipt must fail.

- [ ] **Step 2: Run delegated/compiler tests and verify RED**

Expected: missing module and unsupported approval scope.

- [ ] **Step 3: Implement closed review publication and replay**

The receipt binds parent/child IR digests, P4 decision, P5 request/proposal, actual changed roots, retained-root hashes, evidence artifacts, deterministic policy result, reviewer verdict, and four identities. Use a content-addressed object plus one immutable proposal mapping. Reject replacement or orphan objects.

- [ ] **Step 4: Add Research Compiler freeze receipt v2**

Retain v1 replay for `OWNER_REVIEWED` and test-only fixtures. Emit v2 for delegated scope with `delegated_review_receipt_sha256`. Verify the delegated receipt before freezing and again in `verify_freeze`. Do not allow `--engineering-test` to bypass delegated review.

- [ ] **Step 5: Verify RED-GREEN mutation cases**

Run both suites; then temporarily change the allowlist comparison to accept `/central_claim`, confirm the forbidden-root test fails, restore production code, and rerun green.

- [ ] **Step 6: Commit Task 3**

```bash
git add skills/autoresearch-paper/mvp/delegated_review.py \
  skills/autoresearch-paper/mvp/schemas/delegated-engineering-review.schema.json \
  skills/autoresearch-paper/mvp/research_compiler.py \
  skills/autoresearch-paper/tests/test_mvp_delegated_review.py \
  skills/autoresearch-paper/tests/test_mvp_research_compiler.py
git commit -m "feat: add delegated engineering review"
```

---

### Task 4: P5/P2 delegated replay and fixed-session successor Adapter

**Files:**
- Modify: `skills/autoresearch-paper/mvp/recompile_loop.py`
- Modify: `skills/autoresearch-paper/mvp/worker_adapter.py`
- Modify: `skills/autoresearch-paper/tests/test_mvp_recompile_loop.py`
- Modify: `skills/autoresearch-paper/tests/test_mvp_worker_adapter.py`

**Interfaces:**
- Extends: `recompile.bind_freeze(..., delegated_review_store: Path | None = None)`.
- Extends: `worker.init_adapter(..., predecessor_turn_receipt: Path | None = None, delegated_review_store: Path | None = None)`.
- Adds manifest v2 fields: `predecessor_adapter_id`, `predecessor_turn_receipt_path`, `predecessor_turn_receipt_sha256`, `session_start_mode`.

- [ ] **Step 1: Write failing delegated replay tests**

Prove P5 and P2 accept a delegated freeze only when the exact P6 review store replays. Wrong review store, proposal digest, child IR, or retained-root hash must fail. Existing `OWNER_REVIEWED` behavior remains unchanged.

- [ ] **Step 2: Write failing successor session tests**

Create a failed predecessor turn with `session_state = PAUSED`, a successor P5 request, and a clean new worktree from the accepted source commit. Initialize the child Adapter with the predecessor receipt. Assert:

```python
self.assertEqual(manifest["session_id"], predecessor["session_id"])
self.assertEqual(manifest["session_start_mode"], "RESUME_PREDECESSOR")
self.assertEqual(first_transport_argv[session_flag_index:session_flag_index + 2],
                 ["--resume", predecessor["session_id"]])
```

Reject a different model, session, source commit, nonterminal predecessor, reused worktree, or same task contract SHA-256.

- [ ] **Step 3: Run selected P2/P5 tests and verify RED**

Expected: unsupported delegated scope and missing predecessor parameters.

- [ ] **Step 4: Implement delegated evidence replay**

P5 freeze binding stores the delegated review digest. P2 independently replays P1 freeze, P5 freeze binding, and delegated receipt; it never accepts the scope based on a string alone.

- [ ] **Step 5: Implement Adapter manifest v2 and resume transport**

Child Adapter initialization reads the immutable predecessor terminal receipt and prior manifest, verifies exact MiniMax-M3/session/source lineage, creates a new clean worktree, and binds the predecessor. The first dispatch uses exact `--resume`; normal first-generation adapters continue using `--session-id`.

- [ ] **Step 6: Run P1–P5 focused suites**

Run compiler, Worker, ledger, Gate, Recompile, and delegated review tests. Expected: zero failures.

- [ ] **Step 7: Commit Task 4**

```bash
git add skills/autoresearch-paper/mvp/recompile_loop.py \
  skills/autoresearch-paper/mvp/worker_adapter.py \
  skills/autoresearch-paper/tests/test_mvp_recompile_loop.py \
  skills/autoresearch-paper/tests/test_mvp_worker_adapter.py
git commit -m "feat: resume delegated P6 lineages"
```

---

### Task 5: Wire P2–P5 actions into the supervisor heartbeat

**Files:**
- Modify: `skills/autoresearch-paper/mvp/supervisory_controller.py`
- Create: `skills/autoresearch-paper/mvp/prompts/codex-supervisor-heartbeat.md`
- Modify: `skills/autoresearch-paper/tests/test_mvp_supervisory_controller.py`

**Interfaces:**
- Produces: action envelopes `RECORD_P3`, `DECIDE_P4`, `PREPARE_P5`, `REVIEW_ENGINEERING_IR`, `CREATE_CHILD_P2`, `WAIT_FOR_WORKER`, `PAUSE`.
- Extends: `tick(..., action_input: Path | None)` to consume exact closed Codex analysis/review files.

- [ ] **Step 1: Write failing end-to-end fake-lineage tests**

Use the real P1–P5 modules and fake Claude transport to prove separate ticks perform:

```text
terminal P2 -> P3 -> P4 PIVOT -> P5 proposal
-> delegated review -> child freeze -> successor P2 dispatch
```

Assert each call advances exactly one tick sequence and the next action is literal. Add a scientific-root candidate test that produces `WAITING_HUMAN` and `automation_pause_required = true` without creating a critique/freeze.

- [ ] **Step 2: Run the end-to-end P6 tests and verify RED**

Expected: unsupported transition actions, not test-fixture errors.

- [ ] **Step 3: Implement deterministic P3/P4 transitions**

Call existing module functions with exact paths from the manifest. Verify each output before publishing the P6 tick. Never loop from P3 into P4 in one call.

- [ ] **Step 4: Implement P5 and delegated-review action envelopes**

When Codex judgment is required, `inspect` returns a closed action envelope containing exact prompt path, schema path, input digests, output path, and authorized author/reviewer identity. The heartbeat Host produces one JSON artifact with a fresh non-MiniMax Codex reviewer and passes it back to `tick`; the controller validates and publishes it.

- [ ] **Step 5: Implement child P2 transition**

Create one successor Adapter/worktree, use the delegated freeze and predecessor-bound session, compile one new task whose SHA differs from the failed contract, dispatch once, and stop the heartbeat turn.

- [ ] **Step 6: Write and pressure-test the durable heartbeat prompt**

The prompt must read the MVP0 skill and manifest, verify exact task/run binding, run `inspect`, execute at most the returned action, and finish after one committed tick. It must pause on `WAITING_HUMAN`, `BLOCKED`, `STOPPED`, or `COMPLETED`; it must not say "continue everything" without checking state.

- [ ] **Step 7: Run Task 5 and all focused P1–P6 suites**

Expected: all focused tests pass with fake transports only.

- [ ] **Step 8: Commit Task 5**

```bash
git add skills/autoresearch-paper/mvp/supervisory_controller.py \
  skills/autoresearch-paper/mvp/prompts/codex-supervisor-heartbeat.md \
  skills/autoresearch-paper/tests/test_mvp_supervisory_controller.py
git commit -m "feat: orchestrate one P6 heartbeat tick"
```

---

### Task 6: Complete L0/L1/L2 runtime-assurance closure

**Files:**
- Create: `skills/autoresearch-paper/mvp/runtime_assurance.py`
- Create: `skills/autoresearch-paper/mvp/l0_watchdog.py`
- Create: `skills/autoresearch-paper/mvp/launchd_registration.py`
- Create: `skills/autoresearch-paper/mvp/schemas/runtime-activation.schema.json`
- Create: `skills/autoresearch-paper/mvp/schemas/l0-observation.schema.json`
- Create: `skills/autoresearch-paper/mvp/schemas/l2-heartbeat.schema.json`
- Create: `skills/autoresearch-paper/mvp/schemas/runtime-snapshot.schema.json`
- Create: `skills/autoresearch-paper/mvp/schemas/resource-manifest.schema.json`
- Create: `skills/autoresearch-paper/mvp/schemas/shutdown-journal.schema.json`
- Create: `skills/autoresearch-paper/tests/test_mvp_runtime_assurance.py`

**Interfaces:**
- Produces: `bootstrap_assurance(...) -> dict[str, Any]`.
- Produces: `run_l0_health_tick(...) -> dict[str, Any]`.
- Produces: `record_worker_heartbeat(...) -> dict[str, Any]`.
- Produces: `verify_activation(...) -> dict[str, Any]`.
- Produces: `inspect_runtime(...) -> dict[str, Any]` without mutation.
- Produces: `shutdown_runtime(...) -> dict[str, Any]` with restart-safe replay.

- [ ] **Step 1: Write failing L0/L1/L2 activation tests**

Use a fake launchctl backend with an explicit loaded-service set. Prove
activation rejects a schedule file without a loaded service, shared L0/L1
labels or command digests, invalid interval relationships, missing log paths,
and a missing L2 contract. Prove a successful bootstrap runs a non-due L1 probe,
removes and restores exact L1 through L0 with `model_dispatches = 0`, accepts one
test L2 heartbeat, and freezes one activation receipt only after all three pass.

- [ ] **Step 2: Run the runtime-assurance suite and verify RED**

Expected: missing modules/interfaces, not fixture or platform failures.

- [ ] **Step 3: Port the proven contracts without importing Legacy Harness**

Extract the contract shapes and deterministic algorithms from the existing
`harness-runtime.py` tests into small MVP0 modules. Do not import that script,
read `progress.json`, create legacy plan state, or expose research content to L0.
Render plan-bound plists with absolute argv/stdout/stderr, distinct labels, and
an exact command digest. Use dependency injection for launchctl so unit tests do
not mutate the host.

- [ ] **Step 4: Implement sequenced L2 heartbeat replay**

Bind controller, Adapter, turn, session UUID, model, task-contract digest,
process identity, sequence, observed time, and predecessor digest. Exact
duplicate bytes are idempotent; out-of-order, conflicting duplicate,
wrong-session, wrong-process, wrong-contract, and post-terminal receipts fail
closed. Heartbeats never alter scientific state.

- [ ] **Step 5: Implement L0 metadata-only observation and exact L1 repair**

Allow L0 to read only an explicit metadata projection. It writes one immutable
observation plus a deduplicated JSONL index. When active authority permits and
the exact L1 is missing or disabled, restore only its frozen configuration. On
unknown drift, pause/stop, or command mismatch, record a typed proposal without
repair. Assert every path reports zero model calls.

- [ ] **Step 6: Verify GREEN and mutation coverage**

Temporarily permit L0 to inspect a Research IR path, accept a wrong-session
heartbeat, and treat a plist as loaded. Confirm the respective tests fail;
restore production code and rerun green.

- [ ] **Step 7: Commit Task 6**

```bash
git add skills/autoresearch-paper/mvp/runtime_assurance.py \
  skills/autoresearch-paper/mvp/l0_watchdog.py \
  skills/autoresearch-paper/mvp/launchd_registration.py \
  skills/autoresearch-paper/mvp/schemas/runtime-*.schema.json \
  skills/autoresearch-paper/mvp/schemas/l0-observation.schema.json \
  skills/autoresearch-paper/mvp/schemas/l2-heartbeat.schema.json \
  skills/autoresearch-paper/mvp/schemas/resource-manifest.schema.json \
  skills/autoresearch-paper/mvp/schemas/shutdown-journal.schema.json \
  skills/autoresearch-paper/tests/test_mvp_runtime_assurance.py
git commit -m "feat: restore complete P6 runtime assurance"
```

---

### Task 7: Lifecycle reconciliation, inspection, and exact-once stop

**Files:**
- Modify: `skills/autoresearch-paper/mvp/runtime_assurance.py`
- Modify: `skills/autoresearch-paper/mvp/supervisory_controller.py`
- Modify: `skills/autoresearch-paper/mvp/worker_adapter.py`
- Modify: `skills/autoresearch-paper/tests/test_mvp_runtime_assurance.py`
- Modify: `skills/autoresearch-paper/tests/test_mvp_supervisory_controller.py`

**Interfaces:**
- Extends P2 dispatch with an activation gate and L2 heartbeat callback.
- Produces a read-only snapshot for Dashboard projection.
- Produces restart-safe `pause`, `resume`, and `stop` lifecycle commands.

- [ ] **Step 1: Write failing activation-gate and stale-worker tests**

Prove unattended P2 dispatch is rejected when any activation artifact is
missing, stale, altered, unloaded, mismatched, or legacy-only. Prove a fresh L2
receipt allows liveness inspection while a stale receipt creates a runtime
fault without changing a P4/P5 scientific decision.

- [ ] **Step 2: Write failing read-only inspection tests**

Hash every file and snapshot fake launchctl state before and after repeated
inspection. Require byte-identical state while exposing loaded-vs-recorded
disagreements, freshness, bounded logs, process identity, shutdown state, and
declared residuals. Missing facts remain explicitly missing.

- [ ] **Step 3: Write failing crash-replay and stop-order tests**

Inject crashes after `BLOCK_NEW_WORK`, `L0_DISABLED`, `L1_DISABLED`, and Worker
TERM. Repeated stop must converge to one receipt, disable L0 before L1, disable
the exact retry trigger, TERM then bounded KILL only matching process groups,
preserve every research artifact, and list survivors as residuals.

- [ ] **Step 4: Implement lifecycle integration**

Make the P6 controller verify current activation before dispatch and reconcile
L0/L1/L2 before deriving `WORKER_RUNNING`. Pass the least-authority heartbeat
writer to the Worker Adapter. Implement pause as a reversible block on new work,
resume as full activation revalidation/repair, and stop as an irreversible
lifecycle state for that activation generation.

- [ ] **Step 5: Run P2/P6/runtime suites and full regression**

Require all focused cases and `./skills/autoresearch-paper/scripts/setup.sh test`
to pass before proceeding to installation.

- [ ] **Step 6: Commit Task 7**

```bash
git add skills/autoresearch-paper/mvp/runtime_assurance.py \
  skills/autoresearch-paper/mvp/supervisory_controller.py \
  skills/autoresearch-paper/mvp/worker_adapter.py \
  skills/autoresearch-paper/tests/test_mvp_runtime_assurance.py \
  skills/autoresearch-paper/tests/test_mvp_supervisory_controller.py
git commit -m "feat: reconcile and stop P6 watchdog resources"
```

---

### Task 8: Skill, validation, installation, and real thread registration

**Files:**
- Modify: `README.md`
- Modify: `skills/autoresearch-paper/mvp/README.md`
- Modify: `skills/autoresearch-paper/scripts/setup.sh`
- Modify: `skills/autoresearch-paper/tests/validate_contracts.py`
- Modify: installed `/Users/wdblink/.agents/skills/autoresearch-paper-mvp0/SKILL.md`
- Sync: installed MVP0 P6 modules, schemas, prompt, and README.
- Create local App state: `/Users/wdblink/.codex/automations/<controller-id>/automation.toml`
- Create local L0 state: one plan-bound plist plus immutable registration and
  activation receipts under the research run.

**Interfaces:**
- The installed skill describes P1–P6 and names the P6 resources directly.
- The L1 automation is visible-compatible, exact-thread-bound, and initially
  `ACTIVE` only after the complete activation closure verifies.
- The L0 service is loaded, distinct from L1, metadata-only, and recoverable
  through exact receipts; L2 is bound to the fixed Worker identity.

- [ ] **Step 1: Write failing setup and contract validation tests**

Add required P6 resources to `setup.sh` and executable schema parsing to
`validate_contracts.py`. Add behavior tests that render/parse the L1 automation
and L0 plist, verify distinct identities and zero-model L0 argv, and validate
the L2/activation schemas; do not grep for source strings as the primary test.

- [ ] **Step 2: Run setup contract checks and verify RED**

Expected: missing P6 installation/docs/resource coverage.

- [ ] **Step 3: Update documentation and installed skill**

Document P6 as a complete runtime-assurance controller, not proof of 24-hour or
7-by-24 stability. Explain which layer is managed in Codex App, which is the
independent L0, how L2 is emitted, and how operators inspect/pause/resume/stop.
Keep `SKILL.md` below 500 lines by moving commands and review-policy detail into
the MVP README. Regenerate `agents/openai.yaml` only if its description/default
prompt no longer accurately covers P6.

- [ ] **Step 4: Sync installed resources and validate the Skill**

Use `apply_patch` for files and deterministic comparison for repository/installed copies. Run the Skill Creator `quick_validate.py` and require matching hashes for all P6 resources.

- [ ] **Step 5: Run the fresh full regression gate**

Run:

```bash
./skills/autoresearch-paper/scripts/setup.sh test
```

Require exit `0` and record the exact test count. Also run `git diff --check`, JSON schema parsing, Python compilation, and secret scanning.

- [ ] **Step 6: Initialize the live supervisor in dry-run mode**

Bind:

```text
thread = 019fc053-ab31-7333-b5da-85b03372ec24
run = /Users/wdblink/Research/runs/fwvg-mvp0-evaluator-20260802
```

Verify the current P1–P5 lineage and derive the next action without dispatching a Worker.

- [ ] **Step 7: Bootstrap and verify the real L0/L1/L2 closure**

Use the current-session scheduled-task update capability if exposed. Otherwise render the exact automation TOML, write only its unique directory, then run:

```bash
python3 /Users/wdblink/.codex/skills/codex-automation-registration/scripts/normalize_automation.py \
  /Users/wdblink/.codex/automations/<controller-id>/automation.toml
python3 /Users/wdblink/.codex/skills/codex-automation-registration/scripts/normalize_automation.py \
  --check /Users/wdblink/.codex/automations/<controller-id>/automation.toml
```

Confirm exact `target_thread_id`, timestamps, ACTIVE status, and ten-minute
RRULE. Register the exact L0 service, freeze L2, run all three probes, and verify
one activation receipt through read-only runtime inspection. Do not modify
unrelated automations or launchd services.

- [ ] **Step 8: Perform bounded live recovery and heartbeat acceptance**

On a disposable clone of the registration, remove L1 and prove L0 restores it
without a model call; then stop the clone and prove exact cleanup. Manually
trigger or wait for one real App-scheduled L1 run. Confirm it returns to the
exact target chat, reads the supervisor store, advances at most one authorized
transition, records current L2 evidence when a Worker is running, does not retry
the failed `$2` contract, and writes a replayable tick. If App triggering is
unavailable, leave L1 PAUSED and report that live scheduled delivery remains
unproven; do not substitute a local script call for App evidence.

- [ ] **Step 9: Commit repository Task 8 changes**

```bash
git add README.md skills/autoresearch-paper/mvp/README.md \
  skills/autoresearch-paper/scripts/setup.sh \
  skills/autoresearch-paper/tests/validate_contracts.py
git commit -m "docs: install the P6 watchdog workflow"
```

Do not commit `~/.agents`, `~/.codex/automations`, live research runs, or credentials.

---

### Task 9: Whole-branch review and publication

**Files:**
- Review all P6 commits and changed files.
- Update Draft PR #12 body and validation counts.

**Interfaces:**
- Produces a reviewed, pushed `codex/mvp0-thin-loop` branch and updated Draft PR.

- [ ] **Step 1: Generate a whole-branch review package**

Use the merge base with `main`, full commit list, stat, and contextual diff. Include deferred findings from the SDD ledger.

- [ ] **Step 2: Run an independent most-capable code review**

Review for exact spec compliance, thread/run binding, concurrency, authority boundaries, state replay, automation safety, backward compatibility, and test quality.

- [ ] **Step 3: Apply one bounded fix wave if required**

Use one implementer for the complete finding list, rerun covering tests, and perform one scoped re-review. Stop on residual load-bearing findings.

- [ ] **Step 4: Run final verification before completion**

Freshly run the full regression, Skill validation, installed hash comparison, automation normalization check, supervisor replay, `git diff --check`, and `git status`.

- [ ] **Step 5: Push and update Draft PR #12**

Push `codex/mvp0-thin-loop`, update the PR description with P6 scope and exact evidence, and report any Scheduled/App acceptance limitation separately from deterministic test success.
