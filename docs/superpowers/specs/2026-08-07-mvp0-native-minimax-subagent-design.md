# MVP-0 Native MiniMax M3 Subagent Design

**Date:** 2026-08-07

**Branch:** `codex/mvp0-thin-loop`

**Quality tier:** functional

## Summary

MVP-0 will replace its external Claude Code transport with one active
Codex-native `minimax_m3` subagent node per research run. Codex remains the Host
and sole lifecycle authority. The existing deterministic P1-P6 stores remain
the source of scientific and execution truth.

The native Worker node is bound to the run and reused through Codex follow-up
dispatches while it remains available. Reusing one node preserves
conversational context and is expected to improve prompt-cache locality and
reduce repeated context tokens. Cache behavior is an optimization only: no
correctness, identity, cost, or completion decision may depend on an assumed
cache hit. If Codex confirms that the node is gone, the Host may cleanly create
a replacement generation from durable, hash-bound state.

## Scope

This release changes only the active MVP-0 path on `codex/mvp0-thin-loop`:

- `mvp/worker_adapter.py` and its P2 contracts;
- P6 supervisor and runtime-assurance integration with the Worker lifecycle;
- MVP-0 schemas, prompts, tests, examples, installation checks, and docs;
- the `autoresearch-paper-mvp0` skill instructions and agent metadata.

The full production/legacy Harness, including its Claude Code compatibility
runtime, is outside this release. Shared files may change only when MVP-0 owns
the affected contract and the legacy runtime remains behaviorally unchanged.

## Decision

Use a split-phase native adapter:

1. deterministic Python code prepares a closed dispatch;
2. the Codex Host creates or follows up the one bound `minimax_m3` subagent;
3. the subagent performs the bounded task in the detached worktree;
4. deterministic Python code validates and finalizes the delivery.

This keeps model orchestration visible in Codex while preserving the existing
hash, path, evidence, and authority boundaries.

### Rejected alternatives

**Skill-only dispatch.** Merely instructing Codex to spawn MiniMax would be a
small diff, but it would remove mechanical preparation, delivery validation,
immutable receipts, and replayable failure evidence.

**Local Codex process bridge.** Launching `codex exec` or an internal Codex API
from Python would preserve a single command-shaped adapter but recreate an
external process boundary, weaken in-app observability, and couple MVP-0 to an
unsupported transport surface.

**One fresh subagent per task.** Fresh nodes simplify recovery but discard
context and prompt-cache locality. MVP-0 therefore keeps one active node and
replaces it only after confirmed node loss, never as routine task scheduling.

## Authority and invariants

The following rules are unchanged:

- Codex owns planning, dispatch, lifecycle actions, validation, gates, and
  final decisions.
- MiniMax is a bounded artifact producer. It is never a reviewer, approver,
  scientific gate, or final authority.
- The frozen Research IR and closed Worker task contract define all permitted
  work.
- The Worker may write only the declared worktree paths plus its unique result
  delivery file.
- The Host independently derives the Git delta and hashes every delivered
  artifact; Worker-declared hashes are never authoritative.
- A failed task contract is not repeated. Successors retain exact P5 lineage
  and use the current bound native Worker generation.
- No external Claude Code, MiniMax CLI, `codex exec`, or fallback model process
  may be launched by the MVP-0 native path.

The migration adds these invariants:

- At most one native `minimax_m3` subagent node is active for each research run.
- The current node is created through Codex's native Agent lifecycle and reused
  through native follow-up operations while available.
- The configured agent profile, canonical task name, and opaque native agent ID
  are Host observations. The Worker cannot establish its own identity.
- A confirmed missing or unavailable node may be replaced by a new
  `minimax_m3` generation after the old generation is proven inactive and has
  no uncertain delivery. Every replacement is recorded in immutable lineage.
- A mismatched node, uncertain delivery, or inability to prove the old node
  inactive pauses the run. MVP-0 never permits two nodes to own the same turn.
- Model/profile identity is proven by the Host dispatch route, not by text or
  metadata self-reported in the Worker result.
- Cache hits and token attribution are reported only when the Codex Host exposes
  evidence for them. Missing telemetry is recorded as unknown.

## Architecture

### Components

#### Native Worker Adapter

`mvp/worker_adapter.py` remains the deterministic P2 boundary, but transport
execution is split into preparation and finalization.

It no longer discovers a Claude executable, translates JSON Schema for Claude,
parses Claude stream events, manages Claude session UUIDs, passes Claude tool
permissions, or classifies Claude CLI failures.

#### Codex Host orchestration

The `autoresearch-paper-mvp0` skill performs the only model-bearing operations:

- create the run's Worker with the native `minimax_m3` agent profile;
- bind the returned native identity and generation to the prepared run;
- send the first closed work order to that node;
- send later work orders through native follow-up to the same node;
- wait for native lifecycle completion or attention;
- persist Host-observed lifecycle evidence before finalization.

#### Deterministic stores

The adapter store, experiment ledger, evidence gate, P5 store, and supervisor
store retain their current separation. Native identity and dispatch artifacts
are additive inputs to replay; they do not become a second research truth.

### Data flow

```text
Frozen IR + task contract
          |
          v
prepare-dispatch (deterministic)
  - validate IR/task/input hashes
  - archive inputs
  - capture before-inventory
  - reserve one turn
  - publish closed work order
          |
          v
Codex native Agent lifecycle
  - first generation: spawn minimax_m3
  - later turns: follow up the current node
  - confirmed loss: seal transition, then spawn next generation
  - wait and record Host-observed identity/status
          |
          v
MiniMax writes bounded worktree changes + result.json
          |
          v
finalize-dispatch (deterministic)
  - verify prepared-turn and bound identity
  - validate result schema
  - derive Git delta and hashes
  - enforce path/operation/command boundaries
  - publish immutable terminal receipt
          |
          v
P3 experiment ledger -> P4 gate -> P5 successor -> current Worker generation
```

## Adapter state and commands

### Initialization

`worker_adapter.py init` will bind:

- `control_plane: "codex-native"`;
- `agent_profile: "minimax_m3"`;
- the frozen IR, detached worktree, schemas, and per-turn limits;
- a Host-owned native binding location.

It will remove `--claude-bin`, Claude executable digests, Claude permission
mode, transport-schema digests, and the Claude session UUID. The adapter ID
remains the durable P2 identity.

### `prepare-dispatch`

Inputs:

- adapter directory;
- exact Worker task contract;
- optional runtime-assurance store for unattended work.

Outputs:

- immutable `native-work-order.json`;
- immutable input archive and before-inventory;
- unique result-delivery path;
- turn index, dispatch ID, worktree root, timeout, expected profile, and prompt
  path for the Codex Host;
- adapter state `PREPARED`.

Preparation acquires the adapter delivery lease. A second preparation is
rejected until the prepared turn is finalized or deterministically reconciled.

### `bind-native-agent`

The Codex Host records the first successful native creation result in a
Host-owned binding artifact containing:

- schema version;
- adapter ID and research-run binding;
- expected profile `minimax_m3`;
- native generation number;
- native agent ID;
- canonical task name;
- creation timestamp;
- first dispatch ID.

Each generation binding is immutable. Later turns must name the current native
agent ID and canonical task name. A replacement creates the next generation
record with the prior binding digest, confirmed-loss observation, and exact
durable resume capsule. The Worker result file is outside the authority path
for these bindings.

### Native dispatch

The first turn uses Codex native subagent creation with:

- agent type `minimax_m3`;
- a stable logical task-name prefix derived from the adapter ID plus the native
  generation number;
- the detached worktree as the working directory;
- the immutable work-order path as the single requirements source;
- explicit allowed and forbidden paths;
- the unique result-delivery path;
- stop conditions and deterministic validator commands.

Every later turn uses native follow-up for the exact current agent. A new spawn
is forbidden while that node is available or while its last delivery is
uncertain. A confirmed unavailable node may be replaced only through the
generation-transition procedure.

### `record-native-observation`

Before finalization, the Codex Host records an observation of the native tool
result: dispatch ID, bound agent identity, lifecycle state, completion or
attention status, and any host-exposed usage/cache fields. This artifact is
Host-owned and immutable.

Unknown telemetry uses JSON `null`; it is never estimated from prompt size or
Worker claims.

### `finalize-dispatch`

Finalization requires:

- the exact prepared turn;
- an existing immutable native binding;
- a Host observation for the same dispatch and agent identity;
- the unique Worker result file when lifecycle completion was reported.

It then reuses the current result, command, observation, Git-delta, hash, and
symlink validations. A valid delivery becomes `COMPLETED` or `BLOCKED`. Invalid
or incomplete delivery becomes a typed `FAILED` receipt with a rejected-change
manifest.

Finalization is idempotent for the same dispatch. Replaying it with different
bytes or identity is rejected.

### Reconciliation

`inspect` exposes `READY`, `PREPARED`, `RUNNING`, `COMPLETED`, `BLOCKED`,
`FAILED`, or `PAUSED` plus the bound native identity and prepared dispatch.

If Codex restarts after preparation:

- a matching live/idle bound node may receive the outstanding work order once;
- a matching completed node may be finalized from its existing result and Host
  observation;
- a confirmed missing node with no in-flight or uncertain delivery may advance
  to a new native generation using the latest durable resume capsule;
- an uncertain delivery or identity mismatch pauses the run;
- the Host never resends an uncertain work order or activates two generations.

### Generation transition

Clean recreation is a recovery path, not normal dispatch. Before creating a
replacement, the Codex Host must record that the current native agent is
unavailable and prove that no prepared dispatch can still mutate the worktree
or deliver a result. Deterministic code then seals a transition artifact with:

- prior generation binding and terminal Host-observation digests;
- the reason and time of confirmed loss;
- latest terminal P2 receipt and P3/P4/P5 lineage digests;
- current worktree HEAD and clean/accepted inventory identity;
- the complete durable resume capsule for the next node;
- next generation number and required profile `minimax_m3`.

Codex creates one replacement node from that capsule and records the new
binding. If node inactivity or the delivery boundary cannot be proven, the
transition is rejected and the run remains paused. Cache locality restarts with
the new generation; no cache or hidden conversation state is treated as
required recovery data.

## Work order and result contracts

The existing Worker task and result schemas remain scientifically compatible.
Their descriptions become Host-neutral and refer to a Codex-native MiniMax
Worker.

A new closed native work-order schema binds:

- adapter, run, dispatch, turn, and task identities;
- expected native agent profile;
- immutable IR/task/input hashes;
- worktree and unique result-delivery paths;
- allowed paths and operations;
- exact experiment and acceptance commands;
- positive, negative, and boundary cases;
- timeout and stop conditions;
- result schema path and digest.

The Worker result schema does not contain authoritative agent identity, model
identity, token use, cache use, lifecycle state, or scientific verdicts.

## P6 and Watchdog changes

The current L2 process/session heartbeat cannot survive the removal of the
external Claude process. It becomes a native lifecycle observation:

- L0 remains a zero-model launchd health supervisor.
- L1 remains the scheduled Codex Host heartbeat bound to the exact task.
- L2 records Host-observed state for the one native MiniMax node and its active
  dispatch.

L0 may detect stale or missing L2 observations and pause/flag the run, but it
cannot inspect, signal, or kill a Codex-native subagent. Codex's control plane
must confirm node loss before the Host records a generation transition and
creates a replacement. Documentation and tests must stop claiming
OS-process-level L2 supervision for the native path.

One L1 heartbeat still commits at most one supervisor transition. A P2 native
dispatch is one transition: prepare, invoke/follow up, wait, record, and finalize
one bounded work order. If the native call requires user attention or cannot
finish within its bound, the tick commits a typed paused/failed outcome rather
than advancing scientific state.

## Failure model

New typed failures include:

- `native_agent_unbound`;
- `native_agent_unavailable`;
- `native_agent_identity_mismatch`;
- `native_agent_profile_mismatch`;
- `native_dispatch_uncertain`;
- `native_observation_missing`;
- `native_result_missing`;
- `native_result_invalid`;
- `native_usage_unknown` as non-fatal telemetry state.

Existing failures for contract drift, input drift, unauthorized changes,
symlink traversal, command escape, timeout, result-schema failure, rejected
changes, and lineage mismatch remain fail-closed.

There is no fallback to Claude Code, a MiniMax CLI, `codex exec`, or a different
Codex profile. Clean replacement with the same `minimax_m3` profile is allowed
only after confirmed node loss, a clear delivery boundary, and an immutable
generation-transition record.

## Security and least authority

- The native Worker receives the closed work-order path, not the controller's
  conversation or full supervisor store.
- Its mutable surface is the detached worktree's allowed paths and one unique
  result file.
- Adapter bindings, Host observations, task archives, inventories, and receipts
  are outside Worker-writable paths.
- The Host validates current filesystem bytes and Git state after every native
  dispatch.
- The Worker cannot approve its output or write P3-P6 authority artifacts.
- Reviewer identities remain fresh, non-MiniMax Codex roles with artifact-only
  inputs.

## Documentation and compatibility

The MVP-0 skill, README, prompt templates, examples, and agent metadata will
describe a Codex-native MiniMax Worker and the single-node reuse invariant.

The installed MVP-0 package must not require a Claude installation. MVP-0
commands and help text must not expose `--claude-bin`, Claude session IDs,
`--resume`, or Claude-specific permissions. Historical design documents and
the full legacy runtime are not rewritten.

Version notes must state that cache locality is an expected benefit of native
single-node reuse, not a guaranteed token-saving measurement.

## Testing strategy

Implementation follows test-driven development.

### Adapter contract tests

- initialization succeeds without a Claude executable and records the exact
  native profile;
- preparation emits a closed, hash-bound work order and no model process;
- the first Host binding accepts exactly `minimax_m3`;
- later dispatches require the same agent ID and canonical task name;
- a second node, unknown node, profile drift, or self-reported identity is
  rejected;
- finalization accepts a valid result and exact allowed Git delta;
- missing/invalid results and out-of-bound changes produce immutable failed
  receipts;
- finalization and reconciliation are idempotent.

### Supervisor and assurance tests

- P6 selects native create only when no binding exists or a valid generation
  transition authorizes replacement;
- P6 selects native follow-up for every later P2 task;
- confirmed node loss with no uncertain delivery creates exactly one new
  generation from the durable resume capsule;
- identity drift and uncertain dispatch pause without replacement;
- recovery never leaves two active nodes or replays an uncertain work order;
- native L2 observations replay and stale observations are detected;
- L0 does not claim process control over the native node;
- one heartbeat still commits at most one transition.

### Integration and packaging tests

- fake Host lifecycle fixtures exercise prepare, bind, observe, and finalize;
- a successor stage reuses the current native node binding when available and
  cleanly resumes on the next generation after confirmed loss;
- no MVP-0 runtime path invokes Claude, MiniMax CLI, or `codex exec`;
- installation and contract validators pass without Claude Code;
- the complete MVP-0 test suite passes;
- the repository's unrelated legacy-runtime tests retain their prior behavior.

## Acceptance criteria

The migration is complete when all of the following are demonstrated:

1. An MVP-0 research run initializes and prepares P2 without discovering or
   executing Claude Code.
2. Codex keeps exactly one active `minimax_m3` subagent node for the run and
   uses native follow-up while it is available; confirmed loss produces one
   hash-linked replacement generation without duplicate ownership.
3. Every dispatch is bounded by an immutable work order and every delivery is
   independently validated into an immutable terminal receipt.
4. Profile drift, uncertain delivery, duplicate ownership, and invalid Worker
   output fail closed; confirmed node loss is recoverable only through the
   recorded generation-transition protocol.
5. Frozen IR authority, allowed paths/commands, Git-byte hashing, P3/P4/P5
   separation, and fresh non-MiniMax review remain enforced.
6. P6 and L0/L1/L2 replay honestly represent native lifecycle observations and
   make no external-process supervision claim.
7. Targeted native-adapter and supervisor tests plus the complete MVP-0 suite
   pass with fresh evidence.
8. MVP-0 documentation and installed metadata describe the native single-node
   architecture and contain no active Claude-worker instructions.

## Non-goals

- Migrating the full production/legacy Claude compatibility runtime.
- Guaranteeing or estimating a cache-hit rate, token saving, or per-agent cost.
- Adding concurrent MiniMax Workers, routine per-task replacement, or model
  fallback.
- Allowing MiniMax to review, approve, gate, or change the Research IR.
- Claiming 24-hour operation, 7x24 reliability, production readiness, SOTA, or
  paper completion.
