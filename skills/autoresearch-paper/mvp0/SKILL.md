---
name: autoresearch-paper-mvp0
description: Run the Codex-hosted AutoResearch MVP-0 P1–P6 loop: compile and freeze a falsifiable Research IR, dispatch a fixed Claude Code/MiniMax Worker, record evidence, decide the Gate, recompile bounded successors, and supervise the run with a three-layer L0/L1/L2 Watchdog. Use for MVP-0 research-loop tests and bounded unattended execution. This does not claim 24h, 7x24, production readiness, SOTA, or paper-writing completion.
---

# AutoResearch Paper MVP0

Use Codex as the Host and one physically separate Claude Code session with the
frozen MiniMax model as the bounded Worker. P1–P5 remain the only scientific
and experiment truth. P6 observes and advances those stores one transition per
Codex heartbeat; it never creates a second research truth.

## Required reading

Read these resources completely before acting:

- `mvp/README.md`;
- `mvp/prompts/codex-research-compiler.md` and
  `mvp/schemas/research-ir.schema.json` for P1;
- the Worker task/result schemas and `mvp/worker_adapter.py` for P2;
- the Experiment Receipt schema and `mvp/experiment_ledger.py` for P3;
- the evaluator/decision schemas and `mvp/evidence_gate.py` for P4;
- `mvp/prompts/codex-recompile-analyst.md`, the P5 schemas, and
  `mvp/recompile_loop.py` for P5;
- `mvp/prompts/codex-supervisor-heartbeat.md`, the supervisor/runtime schemas,
  `mvp/supervisory_controller.py`, and `mvp/runtime_assurance.py` for P6.

Use `examples/mvp0/fixed-wing-visual-guidance/` only as a shape example. Never
copy its claims, paths, evidence, or approval.

## Non-negotiable boundaries

- P1 must discuss the research contract with the owner before freezing the
  initial IR. Publish a proposal, stop for Human Critique, revise, stop for
  Human Approval, then freeze `OWNER_REVIEWED` and replay it.
- `ENGINEERING_ACCEPTANCE` is test-only. Never use it for live work.
- P6 may use `DELEGATED_ENGINEERING_REVIEW` only for a version N+1 delta that
  passes the deterministic execution-only policy and a fresh non-MiniMax Codex
  review. Problem, claim, baseline, metrics, thresholds, falsification, safety,
  evaluator semantics, and scientific hypothesis fields remain immutable.
- The compiler, reviewer, revision author, and approver must be distinct
  `codex/<role>` identities for delegated review. MiniMax is never a reviewer,
  approver, or final authority.
- Never treat Worker `COMPLETED`, P3 recording, or a Watchdog heartbeat as
  scientific success. Only the frozen P4 truth table can decide KEEP, PIVOT,
  STOP, or RECOMPILE.
- Never repeat a failed task contract, reset its rejected worktree, rotate the
  Worker model/session, or accept rejected files. A successor uses a clean new
  worktree, an exact P5 freeze, the predecessor terminal receipt, the same
  session UUID, and exact `--resume`.
- Unattended dispatch is forbidden until the full L0/L1/L2 activation receipt
  replays. A Codex automation file alone is not a complete Watchdog.
- One heartbeat performs at most one state transition. Stop after the committed
  tick and let the next heartbeat derive the next action.
- Pause on scientific/ambiguous changes, identity mismatch, unknown scheduler
  drift, exhausted deterministic recovery, or inconsistent lineage.
- Do not claim 24h, 7x24, production cutover, SOTA, or paper readiness from P6.

## P1–P5 flow

1. Ground the brief in real local evidence and hash every cited local file.
2. Draft and validate one Research IR with a fair baseline/evaluator,
   falsification conditions, allowed search space, finite budget, and STOP plus
   RECOMPILE rules.
3. Publish the proposal and render a review card. End at
   `AWAITING_HUMAN_CRITIQUE`.
4. Translate owner feedback into a structured critique, publish explicit JSON
   Pointer changes, render the semantic diff, and end at
   `AWAITING_HUMAN_APPROVAL`.
5. After later explicit approval, freeze `OWNER_REVIEWED` and run
   `verify-freeze --check-paths`.
6. Only on execution authority, initialize P2 in a clean detached worktree,
   compile one task from one frozen experiment, and dispatch once.
7. Record every terminal P2 receipt into P3 before another Worker turn.
8. Run P4 once for the next P3 receipt. Preserve negative and failed evidence.
9. On PIVOT/RECOMPILE, publish a P5 failure analysis, request, and IR N+1
   proposal. Do not silently broaden the scientific contract.

Exact commands and receipt semantics are in `mvp/README.md`.

## P6 supervisor initialization

Initialize one plan-bound store under the research run:

```bash
python3 mvp/supervisory_controller.py init \
  --run-dir /absolute/research-run \
  --target-thread-id <exact-codex-task-id> \
  --adapter-dir /absolute/research-run/adapter \
  --ledger-dir /absolute/research-run/ledger \
  --gate-store /absolute/research-run/gate \
  --p5-store /absolute/research-run/p5-recompile
```

Run `inspect` first. Its action envelope binds the controller, exact Codex task,
run, sequence, and one permitted action. If it returns
`NEEDS_ENGINEERING_REVIEW`, inspect the full parent/child semantic diff and P4/P5
evidence, then supply the closed engineering-review input to one `tick`.

Render the L1 automation using `render-automation`. Register it through the
Codex App scheduled-task capability when available. Otherwise write only its
exact returned path, normalize it with `codex-automation-registration`, and
verify it appears in Scheduled before claiming App registration.

Bootstrap the complete runtime closure only after L1 exists:

```bash
python3 mvp/supervisory_controller.py bootstrap-assurance \
  --store-dir /absolute/research-run/supervisor \
  --launch-agents-dir "$HOME/Library/LaunchAgents" \
  --python-executable /absolute/python3 \
  --now 2026-08-02T00:00:00Z
```

This proves:

- L0: independent launchd health supervisor, zero model calls, exact L1 repair;
- L1: Codex App `kind=heartbeat`, exact `target_thread_id`, ten-minute cadence;
- L2: sequenced process/session/task-bound Worker heartbeats;
- activation: immutable receipt binding identities, intervals, logs, probes,
  and owned resources.

L0 never reads research content or invokes a model. It can restore only the
exact frozen L1 file. L1 is the model-bearing Host tick. L2 proves Worker
liveness, not scientific progress.

## Heartbeat operation

For every L1 run:

1. verify the exact task/run/controller binding and publish one `heartbeat`;
2. run `inspect`;
3. create at most the one closed input requested by the action;
4. run one `tick`;
5. run `verify`;
6. report the committed phase and end the Codex turn.

Typical sequence:

```text
terminal P2 → NEEDS_P3 → NEEDS_P4 → NEEDS_P5
→ NEEDS_ENGINEERING_REVIEW → NEEDS_CHILD_P2
→ successor Worker starts → terminal P2
```

P6 may publish deterministic P3/P4 transitions and bounded P5 artifacts. It
may automatically freeze only execution-only IR changes. A scientific delta
must become `WAITING_HUMAN`; do not weaken the policy to keep the loop moving.

## Observe and control

- `inspect`: read-only next controller action.
- `verify`: replay supervisor ticks and P1–P5 lineage.
- `inspect-runtime`: read-only L0/L1/L2/process/log/residual snapshot for the
  Dashboard projection.
- `l0-health-tick`: zero-model health observation and exact permitted repair.
- `pause`: block new work and pause the exact L1 registration; require an
  explicit `--authority-id`.
- `resume`: replay supervisor and full activation before reactivation.
- `stop`: exact-once ordered shutdown—block work, disable L0, disable L1,
  terminate only identity-matching Worker processes, and report residuals.

L0 must detect both a stale L1 execution heartbeat and a stale/missing active
L2 Worker heartbeat. It may repair only an exactly missing frozen L1 file;
drift, scheduler absence, and stale execution produce typed recovery evidence
instead of an unsafe resend or an invented success state.

Codex App owns the automation `updated_at` value and may normalize terminal
prompt whitespace when it persists a heartbeat. Treat only those
representation changes as equivalent. Compare the normalized complete prompt
and all stable controller, task, recurrence, name, creation, and lifecycle
fields; any semantic difference is `L1_DRIFT`.

The Codex App Scheduled view is the operator surface for L1. L0 remains outside
the App failure domain. Dashboard data is a read-only projection; it never
authorizes a transition.

## Completion language

Report concrete evidence separately:

- deterministic P1–P6 tests passed;
- installed resources match the repository;
- L0 is loaded and activation replays;
- L1 is visible and bound to the exact task;
- a real scheduled heartbeat returned to that task;
- a real L2 heartbeat and terminal receipt were recorded;
- the next research stage actually started.

If any item is absent, name it as an unclosed gate. Never collapse these into a
claim of 24h, 7x24, production readiness, SOTA, or full paper completion.
