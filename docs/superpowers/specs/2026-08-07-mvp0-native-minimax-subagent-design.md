# MVP-0 Native MiniMax M3 Subagent Orchestration Design

**Date:** 2026-08-07

**Branch:** `codex/mvp0-thin-loop`

**Quality tier:** functional

## Summary

MVP-0 will replace its external Claude Code transport with Codex-native
`minimax_m3` subagents. Codex remains the Host, top-level orchestrator, and sole
decision authority. MiniMax subagents perform the configured execution,
analysis, testing, and peer-review roles. The existing deterministic P1-P6
stores remain the source of scientific and execution truth.

Subagent count and topology are derived from the skill's active flow and role
configuration. MVP-0 imposes no numeric ceiling and never removes a required
role merely to reduce fan-out. Nodes may be retained and reused through native
follow-ups when continued context is useful; otherwise they may be released.
Reuse can improve prompt-cache locality, but cache behavior is an optimization
only: no correctness, identity, cost, or completion decision may depend on an
assumed cache hit. A lost node may be cleanly recreated from durable,
hash-bound state.

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
2. the Codex Host derives the required subagent roles from skill configuration;
3. Codex creates or follows up the required `minimax_m3` nodes, in parallel or
   sequence according to their dependencies and isolation boundaries;
4. the subagents perform their bounded execution or peer-review work;
5. deterministic Python code validates and finalizes every delivery;
6. Codex resolves escalations, synthesizes evidence, and makes the top-level
   decision.

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

**Fixed single Worker.** A single persistent node improves cache locality for a
linear workload but cannot satisfy configured parallel roles, independent
cross-review, or non-overlapping specialist work. MVP-0 therefore reuses nodes
when useful without treating one node as a global limit.

**Unbounded ceremony.** Removing a numeric ceiling does not mean spawning
duplicate roles for consensus theater. Every node must correspond to a role,
dependency, independence requirement, or isolated unit declared by the active
skill configuration.

## Authority and invariants

The following rules are unchanged:

- Codex owns planning, dispatch, lifecycle actions, validation, gates, and
  final decisions.
- MiniMax is a bounded execution and advisory-review layer. A MiniMax subagent
  may review another subagent's artifact when the active skill requires an
  independent cross-review, but it is never its own reviewer, an approver, a
  scientific gate, or final authority.
- The frozen Research IR and closed Worker task contract define all permitted
  work.
- The Worker may write only the declared worktree paths plus its unique result
  delivery file.
- The Host independently derives the Git delta and hashes every delivered
  artifact; Worker-declared hashes are never authoritative.
- A failed task contract is not repeated. Successors retain exact P5 lineage
  and dispatch the roles required by the current skill configuration.
- No external Claude Code, MiniMax CLI, `codex exec`, or fallback model process
  may be launched by the MVP-0 native path.

The migration adds these invariants:

- Native `minimax_m3` subagent count is configuration-driven and has no MVP-0
  hard cap. Mandatory and independent roles remain distinct dispatches.
- Each node is created through Codex's native Agent lifecycle and may be reused
  through native follow-up operations while its role still needs context.
- The configured role, agent profile, canonical task name, and opaque native
  agent ID are Host observations. A subagent cannot establish its own identity
  or role.
- A confirmed missing or unavailable node may be replaced for the same logical
  role after the old generation is proven inactive and has no uncertain
  delivery. Every replacement is recorded in immutable lineage.
- A mismatched node, uncertain delivery, or inability to prove the old node
  inactive pauses only the affected work. MVP-0 never permits two nodes to own
  the same mutating dispatch.
- The subagent that produces an artifact never evaluates that artifact. Review
  nodes receive artifact-only context and a distinct role/identity.
- Subagent uncertainty becomes a structured Host-decision request. Codex alone
  resolves it and either follows up the same node or changes orchestration.
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

#### Role plan and node registry

At each configured flow node, Codex compiles the skill requirements into a
closed `native-role-plan.json`. The plan records the flow node, every role
instance, role kind, dependencies, mutability, isolation assignment, input and
output contract digests, independence constraints, and retention hint. It has
no `max_agents`, `max_nodes`, or equivalent truncation field. Repeated role
instances are valid when the skill explicitly requires multiple personas,
independent samples, or cross-reviews.

Deterministic validation rejects omitted mandatory roles, undeclared roles,
dependency cycles, producer self-review, and overlapping mutation without
isolation. It does not reject a valid plan because of its role count. The
Host-owned node registry maps each logical role instance to its native identity,
generation, current dispatch, retained/idle state, and immutable lineage.

#### Codex Host orchestration

The `autoresearch-paper-mvp0` skill performs the only model-bearing operations:

- resolve the active flow, roles, dependencies, and isolation requirements;
- create the required nodes with the native `minimax_m3` agent profile;
- bind each returned native identity, logical role, and generation to the run;
- dispatch independent roles in parallel and dependent roles in sequence;
- reuse a node through native follow-up when its role benefits from retained
  context;
- route structured uncertainties back to Codex for a decision;
- wait for native lifecycle completion or attention;
- persist Host-observed lifecycle evidence before finalization;
- synthesize validated outputs without allowing a producer to review itself.

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
  - resolve configured execution/review roles
  - spawn or follow up the required minimax_m3 nodes
  - run independent roles in parallel; serialize dependencies
  - return uncertainty to Codex for a Host decision
  - on confirmed loss, seal transition and recreate that logical role
  - wait and record Host-observed identity/role/status
          |
          v
MiniMax execution nodes write bounded changes/results
MiniMax review nodes write artifact-only advisory evaluations
          |
          v
finalize-dispatch / finalize-review (deterministic)
  - verify work order, role, and bound identity
  - validate role-specific output schema
  - derive Git delta and hashes for mutating roles
  - enforce path/operation/command/review independence
  - publish immutable per-node receipts
          |
          v
Codex synthesis/decision -> P3 ledger -> P4 gate -> P5 successor
```

## Adapter state and commands

### Initialization

`worker_adapter.py init` will bind:

- `control_plane: "codex-native"`;
- `agent_profile: "minimax_m3"`;
- the frozen IR, worktree/isolation roots, schemas, and per-dispatch limits;
- a Host-owned native node registry and binding location;
- the resolved role/topology configuration digest for the run.

It will remove `--claude-bin`, Claude executable digests, Claude permission
mode, transport-schema digests, and the Claude session UUID. The adapter ID
remains the durable P2 identity.

### `prepare-dispatch`

Inputs:

- adapter directory;
- exact Worker task contract;
- logical role, node kind, dependencies, and output-contract digest;
- mutability and isolation assignment for that role;
- optional runtime-assurance store for unattended work.

Outputs:

- immutable `native-work-order.json`;
- immutable input archive and before-inventory;
- unique result-delivery path;
- turn index, dispatch ID, logical role, dependencies, isolation root, timeout,
  expected profile, and prompt path for the Codex Host;
- adapter state `PREPARED`.

Preparation acquires a dispatch-scoped delivery lease. The Host may prepare all
roles required by the configured node. Concurrent mutating preparations require
disjoint declared paths or isolated worktrees; overlapping mutations are
rejected. Read-only review roles consume immutable artifact snapshots and do
not acquire write ownership of the producer's worktree.

### `bind-native-agent`

The Codex Host records each successful native creation result in a Host-owned
binding artifact containing:

- schema version;
- adapter ID and research-run binding;
- logical node ID, configured role, and node kind;
- expected profile `minimax_m3`;
- native generation number;
- native agent ID;
- canonical task name;
- creation timestamp;
- first dispatch ID.

Each logical node's generation binding is immutable. Follow-up work must name
that logical node's current native agent ID and canonical task name. A
replacement creates its next generation record with the prior binding digest,
confirmed-loss observation, and exact durable resume capsule. Worker result and
review files are outside the authority path for these bindings.

### Native dispatch

Each configured role uses Codex native subagent creation when it has no retained
compatible node. The dispatch includes:

- agent type `minimax_m3`;
- a stable logical task-name prefix derived from the adapter ID and role plus
  the native generation number;
- its assigned isolated worktree or read-only artifact package;
- the immutable work-order path as the single requirements source;
- explicit allowed and forbidden paths;
- the unique result-delivery path;
- stop conditions and deterministic validator commands.

A retained node receives later compatible work through native follow-up. The
Host may create additional nodes whenever the configuration declares another
role, independent review, or isolated unit; there is no numeric skill-level
ceiling. Duplicate nodes with the same role and scope are forbidden unless the
configuration explicitly requests independent samples. A confirmed unavailable
node may be replaced only through the generation-transition procedure.

Independent roles run in parallel when their work orders have no dependency or
write conflict. Dependent roles run serially with artifact paths and digests,
not producer conversation transcripts, passed between them. If the Codex host
has fewer simultaneous slots than the role plan, it schedules complete waves;
capacity may delay a role but never delete, merge, or downgrade it.

### `record-native-observation`

Before finalization, the Codex Host records an observation of each native tool
result: dispatch ID, logical role, bound agent identity, lifecycle state,
completion or attention status, and any host-exposed usage/cache fields. This
artifact is Host-owned and immutable.

Unknown telemetry uses JSON `null`; it is never estimated from prompt size or
Worker claims.

### `finalize-dispatch`

Finalization requires:

- the exact prepared turn;
- an existing immutable native binding for the declared role;
- a Host observation for the same dispatch, role, and agent identity;
- the unique role-specific result file when lifecycle completion was reported.

Mutating execution results reuse the current command, observation, Git-delta,
hash, and symlink validations. Read-only reviews validate the artifact package,
independence lineage, finding schema, and absence of mutations. A valid
delivery becomes `COMPLETED`, `BLOCKED`, or `NEEDS_HOST_DECISION`. Invalid or
incomplete delivery becomes a typed `FAILED` receipt with appropriate rejected
evidence.

Finalization is idempotent for the same dispatch. Replaying it with different
bytes or identity is rejected.

### Reconciliation

`inspect` exposes all configured logical nodes and outstanding dispatches with
`READY`, `PREPARED`, `RUNNING`, `COMPLETED`, `BLOCKED`,
`NEEDS_HOST_DECISION`, `FAILED`, or `PAUSED`, plus their bindings and
dependencies.

If Codex restarts after preparation:

- a matching live/idle bound node may receive its outstanding work order once;
- a matching completed node may be finalized from its existing result and Host
  observation;
- a confirmed missing logical node with no in-flight or uncertain delivery may
  advance to a new native generation using its latest durable resume capsule;
- an uncertain delivery or identity mismatch pauses the affected dependency
  branch;
- the Host never resends an uncertain work order or activates two generations
  for the same logical node.

### Generation transition

Clean recreation is a per-logical-node recovery path, not normal fan-out.
Before creating a replacement, the Codex Host must record that the bound native
agent is unavailable and prove that none of its prepared dispatches can still
mutate an assigned worktree or deliver a result. Deterministic code then seals
a transition artifact with:

- prior generation binding and terminal Host-observation digests;
- the reason and time of confirmed loss;
- latest terminal P2 receipt and P3/P4/P5 lineage digests;
- current worktree HEAD and clean/accepted inventory identity;
- the complete durable resume capsule for the next node;
- logical role, next generation number, and required profile `minimax_m3`.

Codex creates one replacement for that logical node from the capsule and
records the new binding. Other independent nodes may remain active. If node
inactivity or the delivery boundary cannot be proven, the transition is
rejected and its dependency branch remains paused. Cache locality restarts for
the replacement; no cache or hidden conversation state is required recovery
data.

## Work order and result contracts

The existing Worker task and execution-result schemas remain scientifically
compatible. Their descriptions become Host-neutral and refer to a Codex-native
MiniMax execution role. Closed schemas are added for advisory review results
and Host-decision requests.

A new closed native work-order schema binds:

- adapter, run, dispatch, turn, and task identities;
- logical node ID, role, node kind, dependencies, and expected native profile;
- immutable IR/task/input hashes;
- isolation root or read-only artifact package and unique result-delivery path;
- allowed paths and operations;
- producer/reviewer independence constraints;
- exact experiment and acceptance commands;
- positive, negative, and boundary cases;
- timeout and stop conditions;
- retention hint (`follow_up` or `release_when_idle`);
- role-specific result schema path and digest.

Execution results record bounded artifacts and commands. Advisory review
results record findings, severity, file/evidence references, and fix
suggestions, plus an advisory verdict when the role contract requests one;
they cannot authoritatively approve work or cause a gate transition. A
`NEEDS_HOST_DECISION` result contains a closed question, the exact ambiguity,
bounded options, recommendation when available, affected invariants, and
evidence paths. Codex records the decision and sends a new follow-up work order;
the subagent never assumes an answer.

No subagent-authored result contains authoritative agent identity, model
identity, token use, cache use, lifecycle state, or scientific verdicts.

## P6 and Watchdog changes

The current L2 process/session heartbeat cannot survive the removal of the
external Claude process. It becomes a native lifecycle observation:

- L0 remains a zero-model launchd health supervisor.
- L1 remains the scheduled Codex Host heartbeat bound to the exact task.
- L2 records Host-observed state for every retained or active native MiniMax
  node and dispatch in the resolved topology.

L0 may detect stale or missing L2 observations and pause/flag the run, but it
cannot inspect, signal, or kill a Codex-native subagent. Codex's control plane
must confirm node loss before the Host records a generation transition and
creates a replacement. Documentation and tests must stop claiming
OS-process-level L2 supervision for the native path.

One L1 heartbeat still commits at most one supervisor transition. That
transition may execute all configured subagent roles for the current flow node,
including parallel independent roles and serial cross-review. Codex prepares,
invokes/follows up, waits, records, and finalizes every required work order
before synthesis. If a subagent requires confirmation, the tick commits
`NEEDS_HOST_DECISION` and returns the closed question to Codex rather than
advancing scientific state.

## Failure model

New typed failures include:

- `native_agent_unbound`;
- `native_agent_unavailable`;
- `native_agent_identity_mismatch`;
- `native_agent_profile_mismatch`;
- `native_role_mismatch`;
- `native_required_role_missing`;
- `native_self_review_forbidden`;
- `native_isolation_conflict`;
- `native_duplicate_mutating_owner`;
- `native_dispatch_uncertain`;
- `native_observation_missing`;
- `native_result_missing`;
- `native_result_invalid`;
- `native_host_decision_required` as a non-fatal control state;
- `native_usage_unknown` as non-fatal telemetry state.

Existing failures for contract drift, input drift, unauthorized changes,
symlink traversal, command escape, timeout, result-schema failure, rejected
changes, and lineage mismatch remain fail-closed.

There is no fallback to Claude Code, a MiniMax CLI, `codex exec`, or a different
Codex profile. Clean replacement with the same `minimax_m3` profile is allowed
only after confirmed node loss, a clear delivery boundary, and an immutable
generation-transition record.

## Security and least authority

- Each native subagent receives its closed role-specific work-order path, not
  the controller's conversation or full supervisor store.
- A mutating node's surface is its assigned worktree paths and unique result
  file. A review node receives immutable artifacts and a unique advisory-review
  file with no producer-worktree writes.
- Adapter bindings, Host observations, task archives, inventories, and receipts
  are outside Worker-writable paths.
- The Host validates current filesystem bytes and Git state after every native
  dispatch.
- No subagent can authoritatively approve its own or another node's output,
  write P3-P6 authority artifacts, or decide a gate. Reviewers may return the
  advisory verdict required by their closed role contract.
- Cross-review nodes are distinct MiniMax identities when configured. Existing
  mandatory strongest-policy Codex review remains a Host-level gate wherever
  the MVP-0 governance configuration requires it.

## Documentation and compatibility

The MVP-0 skill, README, prompt templates, examples, and agent metadata will
describe Codex-native MiniMax role dispatch with configuration-driven fan-out,
independent cross-review, optional node retention, and Host escalation.

The installed MVP-0 package must not require a Claude installation. MVP-0
commands and help text must not expose `--claude-bin`, Claude session IDs,
`--resume`, or Claude-specific permissions. Historical design documents and
the full legacy runtime are not rewritten.

Version notes must state that retaining useful nodes can improve cache locality
but is not a guaranteed token-saving measurement or a reason to suppress
configured roles.

## Testing strategy

Implementation follows test-driven development.

### Adapter contract tests

- initialization succeeds without a Claude executable and records the exact
  native profile and role-configuration digest;
- preparation emits closed, hash-bound work orders for every configured role
  and starts no model process;
- Host bindings accept exactly `minimax_m3` and bind distinct logical roles;
- no numeric adapter limit rejects required role fan-out;
- retained nodes require the same role, agent ID, and canonical task name;
- additional configured roles are accepted while duplicate mutating ownership,
  unknown roles, profile drift, and self-reported identity are rejected;
- execution finalization accepts a valid result and exact allowed Git delta;
- review finalization accepts an independent artifact-only evaluation and
  rejects producer self-review or mutations;
- `NEEDS_HOST_DECISION` preserves a closed uncertainty for Codex follow-up;
- missing/invalid results and out-of-bound changes produce immutable failed
  receipts;
- finalization and reconciliation are idempotent.

### Supervisor and assurance tests

- P6 creates every configured role without an arbitrary fan-out ceiling;
- P6 dispatches independent roles concurrently and dependencies serially;
- P6 selects native follow-up for retained compatible nodes;
- confirmed node loss with no uncertain delivery creates exactly one new
  generation for the affected logical role from its durable resume capsule;
- identity drift and uncertain dispatch pause without replacement;
- recovery never leaves duplicate ownership of one mutating dispatch or replays
  an uncertain work order;
- subagent uncertainty returns to Codex without an assumed decision;
- native L2 observations replay and stale observations are detected;
- L0 does not claim process control over the native node;
- one heartbeat still commits at most one transition.

### Integration and packaging tests

- fake Host lifecycle fixtures exercise prepare, bind, observe, and finalize;
- configured cross-review uses a distinct MiniMax node from the producer;
- successor work reuses compatible retained bindings when useful and cleanly
  resumes a logical role on its next generation after confirmed loss;
- a high-fan-out fixture proves that all configured roles dispatch without a
  skill-imposed maximum;
- no MVP-0 runtime path invokes Claude, MiniMax CLI, or `codex exec`;
- installation and contract validators pass without Claude Code;
- the complete MVP-0 test suite passes;
- the repository's unrelated legacy-runtime tests retain their prior behavior.

## Acceptance criteria

The migration is complete when all of the following are demonstrated:

1. An MVP-0 research run initializes and prepares P2 without discovering or
   executing Claude Code.
2. Codex dispatches every MiniMax execution and peer-review role required by
   the active skill configuration, with no MVP-0 numeric cap, and preserves
   declared parallelism, dependencies, and isolation.
3. Every dispatch is bounded by an immutable work order and every delivery is
   independently validated into an immutable terminal receipt.
4. No producer reviews its own work; MiniMax cross-review is advisory, and
   Codex retains synthesis, escalation resolution, gates, and final authority.
5. Profile/role drift, uncertain delivery, conflicting mutations, and invalid
   output fail closed; confirmed node loss is recoverable through the recorded
   per-role generation-transition protocol.
6. P6 and L0/L1/L2 replay honestly represent native lifecycle observations and
   make no external-process supervision claim.
7. Targeted native-adapter and supervisor tests plus the complete MVP-0 suite
   pass with fresh evidence.
8. Frozen IR authority, allowed paths/commands, Git-byte hashing, P3/P4/P5
   separation, and mandatory Host-level reviews remain enforced.
9. MVP-0 documentation and installed metadata describe configuration-driven
   native role dispatch and contain no active Claude-worker instructions.

## Non-goals

- Migrating the full production/legacy Claude compatibility runtime.
- Guaranteeing or estimating a cache-hit rate, token saving, or per-agent cost.
- Inventing duplicate roles outside skill configuration, routine per-task
  replacement, or model fallback.
- Allowing MiniMax to approve, gate, resolve Host uncertainties, or change the
  Research IR.
- Claiming 24-hour operation, 7x24 reliability, production readiness, SOTA, or
  paper completion.
