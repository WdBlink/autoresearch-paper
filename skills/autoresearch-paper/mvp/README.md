# MVP-0 P1–P5 — Research Compiler, Worker, Evidence, Gate, and Recompile

This directory is the new Thin Loop implementation path. P1 compiles an open
research idea into one immutable, executable, and falsifiable Research IR. P2
binds an owner-reviewed IR to one detached research worktree and one exact
Claude Code/MiniMax session, then accepts only closed JSON Worker results. P3
turns each terminal P2 delivery into an ordered, content-addressed Experiment
Receipt with archived input/output evidence. The implementation does not import
or call the Legacy v0.20 Harness. P4 validates the frozen evaluator's closed
report and emits one deterministic Gate decision for each P3 receipt.
P5 turns an eligible Gate result into one evidence-bound continuation or
versioned recompile request and routes IR N+1 back through P1 human review.

## Boundary

Research IR contains scientific semantics only:

- problem and central claim;
- falsification predicates and provisional related-work gap;
- honest baseline/evaluator readiness, metrics, and guardrails;
- allowed code search space and initial experiment DAG;
- experiment budget and STOP/RECOMPILE rules.

It deliberately excludes model routing, Claude/MiniMax sessions, Codex call
budgets, watchdogs, cron, dashboard state, paper templates, and lifecycle
slots. Those concerns cannot change what constitutes scientific success. P2
adds the Worker transport beside the IR; it does not add transport fields to
the scientific contract. P3 adds provenance beside both. P4 decides only
whether current evidence supports KEEP, PIVOT, STOP, or RECOMPILE; it does not
perform the recompile.
P5 can compile a new proposal, but it cannot approve that proposal or dispatch
its next Worker.

## Workflow

```text
proposal IR
   │ schema + semantic validation
   ▼
content-addressed proposal
   │ render review card, then STOP for Human Critique
   ▼
owner-bound content-addressed critique
   │ explicit JSON Pointer revision + required-finding closure
   ▼
content-addressed revision and revised IR
   │ render semantic diff, then STOP for Human Approval
   ▼
owner-reviewed content-addressed freeze receipt
```

Every object is canonical UTF-8 JSON at
`<store>/objects/sha256/<digest>.json`. Freeze receipts live at
`<store>/receipts/sha256/<digest>.json`. Publishing is immutable and
collision-checked. `verify-freeze` reconstructs the complete lineage from the
digests rather than trusting filenames or producer claims.

Interactive use must pause twice: after proposal publication in
`AWAITING_HUMAN_CRITIQUE`, and after revision in
`AWAITING_HUMAN_APPROVAL`. `OWNER_REVIEWED` requires recorded
`owner/<identity>` critique and approval identities. P1 does not authenticate
those identity strings, and the receipt does not authorize Worker dispatch.

`ENGINEERING_ACCEPTANCE` proves the compiler workflow only. It is allowed only
for fixtures or CI with the explicit `--engineering-test` switch; it cannot
complete an interactive research request.

## Commands

```bash
python3 mvp/research_compiler.py validate \
  --ir /absolute/path/research-ir.json \
  --check-paths

python3 mvp/research_compiler.py propose \
  --ir /absolute/path/research-ir.json \
  --store /absolute/path/compiler-store \
  --author codex/research-compiler

python3 mvp/research_compiler.py critique \
  --proposal /absolute/path/proposal-object.json \
  --critique /absolute/path/critique.json \
  --store /absolute/path/compiler-store \
  --reviewer owner/research-critic

python3 mvp/research_compiler.py revise \
  --proposal /absolute/path/proposal-object.json \
  --critique-record /absolute/path/critique-object.json \
  --revision /absolute/path/revision.json \
  --store /absolute/path/compiler-store \
  --author codex/research-compiler-revision

python3 mvp/research_compiler.py freeze \
  --revision /absolute/path/revision-object.json \
  --store /absolute/path/compiler-store \
  --approved-by owner/research-approval \
  --approval-scope OWNER_REVIEWED \
  --approval-note "Approved after reviewing the final IR and critique closure."

python3 mvp/research_compiler.py verify-freeze \
  --receipt /absolute/path/freeze-receipt.json \
  --store /absolute/path/compiler-store \
  --check-paths
```

Use [`prompts/codex-research-compiler.md`](prompts/codex-research-compiler.md)
with the strongest Codex model to draft the proposal. The deterministic
validator and approval boundary remain authoritative. The workflow rejects an
AI author or reviser acting as an owner. The same human owner may critique the
proposal and later approve the revised IR. P1 records but does not authenticate
who controls an `owner/<identity>` string.

For a fixture or CI-only lineage, use distinct non-owner roles and add
`--approval-scope ENGINEERING_ACCEPTANCE --engineering-test`. Never use that
path for a live research request.

## Honest planned baselines and evaluators

P1 supports `baseline_contract.status = "PLANNED"` and
`evaluator_spec.status = "PLANNED"` because many real briefs have neither a
fair baseline nor evaluator. Existing source anchors remain separately
hash-bound and do not make a proposed baseline `READY`.

For a planned evaluator:

- `implementation_sha256` must be null;
- exactly one dependency-free `EVALUATOR_BUILD` experiment is required;
- every baseline or method experiment must depend on it transitively;
- the command, input/output contracts, and metric JSON bindings are frozen now;
- the IR cannot pretend that evaluator bytes or baseline results already exist.

Once implementation bytes exist, changing status to `READY` and binding their
SHA-256 requires a new approved IR version, not a Worker-side edit.

## P2 minimal Worker Adapter

P2 is deliberately one narrow execution edge:

```text
OWNER_REVIEWED Research IR
        │
        ▼
detached Git worktree ── fixed task contract
        │
        ▼
Claude Code --session-id UUID ── MiniMax-M3
        │ later turns use only --resume UUID
        ▼
closed worker-result/v1 JSON
        │ Host rehashes every changed/evidence file
        ▼
immutable identity/usage receipt
```

The Worker is an artifact producer. It cannot change the Research IR,
evaluator contract, research goal, acceptance decision, or paper direction.
P2 does not run an independent verifier and does not promote the worktree
changes into the source branch. A `COMPLETED` result is therefore delivery,
not scientific acceptance.

### Initialize one Adapter

The frozen IR must be `OWNER_REVIEWED`, its `source.code_root` must be the root
of a clean Git repository, and both output paths must be new and outside that
repository. `ENGINEERING_ACCEPTANCE` is accepted only with the explicit
`--engineering-test` flag.

```bash
python3 mvp/worker_adapter.py init \
  --freeze-receipt /absolute/compiler-store/receipts/sha256/FREEZE.json \
  --compiler-store /absolute/compiler-store \
  --source-repo /absolute/research-repo \
  --adapter-dir /absolute/run/mvp0-worker \
  --worktree /absolute/run/research-worktree \
  --claude-bin claude \
  --worker-model MiniMax-M3 \
  --max-budget-usd-per-turn 2
```

`adapter-manifest.json` immutably binds the compiler store and freeze receipt,
source commit, worktree, Research IR, Claude executable bytes, MiniMax model
argument, result/task schemas, tool list, and session UUID. `session.json`
stores only the current fixed-session turn count and `READY/BUSY/PAUSED` state.

The repository's Draft 2020-12 Worker Result schema remains the authoritative
Host validator. Claude Code 2.1.205 cannot resolve that metaschema through
`--json-schema`, so the Adapter deterministically removes `$schema`/`$id`, maps
`$defs` to `definitions`, rewrites local references, and sends only that
Draft-07-compatible projection at the transport edge. The manifest binds both
authoritative and projected schema hashes.

### Write and validate one task contract

Use [`schemas/worker-task-contract.schema.json`](schemas/worker-task-contract.schema.json).
The Adapter additionally requires:

- `research_ir_sha256` equals the bound frozen IR;
- `experiment_id`, `search_space_ids`, paths, and operations are authorized by
  that IR;
- every `allowed_paths` value is an exact frozen search-space or expected-artifact
  pattern, rather than a broader newly invented glob;
- `command_argv` exactly equals the frozen experiment command;
- every input is a repository-relative regular worktree file with the declared
  digest. Inputs are read evidence and need not be inside the narrower write
  boundary in `allowed_paths`;
- `experiment_context` freezes the configuration, explicit seed list, data
  versions, and environment artifact versions before dispatch. Every data or
  environment artifact must be an exact declared input artifact.

```bash
python3 mvp/worker_adapter.py validate-task \
  --adapter-dir /absolute/run/mvp0-worker \
  --task-contract /absolute/task-contract.json
```

### Dispatch and inspect

```bash
python3 mvp/worker_adapter.py dispatch \
  --adapter-dir /absolute/run/mvp0-worker \
  --task-contract /absolute/task-contract.json

python3 mvp/worker_adapter.py inspect \
  --adapter-dir /absolute/run/mvp0-worker
```

The first dispatch uses controller-created `--session-id UUID`; every later
dispatch uses exact `--resume UUID`. It never uses `--continue`, fuzzy session
selection, Remote Control, a native Codex MiniMax subagent, or automatic model
fallback. Concurrent delivery is rejected by one non-blocking local lease.
Claude receives `Read/Glob/Grep/Write/Edit`, while Bash is pre-approved only
for the exact shell rendering of `command_argv` and each declared acceptance
check; `dontAsk` denies undeclared command prompts.

The Worker must return [`schemas/worker-result.schema.json`](schemas/worker-result.schema.json).
The Host compares a pre/post Git-visible file inventory and requires the JSON
artifact list to exactly match this turn's regular-file changes. Deletion,
commits, path escape, wrong hashes, wrong session identity, wrong model identity,
malformed output, timeout, or transport failure creates an immutable failed
receipt and pauses the session. P2 intentionally has no automatic recovery or
retry path.

Before launch, P2 also archives every verified task input under the immutable
turn run directory. This prevents P3 from reconstructing a pre-execution input
using bytes that a completed experiment may already have modified.

Each successful or failed launched turn stores:

```text
adapter-dir/
├── adapter-manifest.json          immutable identity binding
├── session.json                   minimal mutable session pointer
├── contracts/sha256/*.json        immutable task contracts
├── runs/000001-task-id/
│   ├── instruction.json
│   ├── input-archive.json
│   ├── input-blobs/sha256/*
│   ├── before-inventory.json
│   ├── after-inventory.json       successful response only
│   ├── change-manifest.json       or rejected-change-manifest.json
│   ├── transport.jsonl
│   ├── transport.stderr
│   └── result.json                valid worker-result/v1 only
└── turns/000001-task-id.json      identity + usage + result lineage
```

Usage fields are observations, never authority. Valid zero counts remain `0`;
missing fields remain `null`; `usage_complete` reports whether all four token
fields were present. Cache-read counts do not prove future cache hits or cost
savings.

### Isolation claim

P2's worktree boundary is enforced at the accepted change layer: the Host
inventories all Git-visible files plus ignored files that match the task's
explicit `allowed_paths`, then rejects undeclared Git-visible writes, symlinks,
special files, deletions, and HEAD changes. It is not an operating-system
sandbox and cannot prove that a malicious external process did not attempt an
out-of-scope access or an ignored write outside every declared path. Run it
only on a trusted machine and treat a paused worktree as evidence to inspect,
not something to auto-reset.

No watchdog, checkpoint protocol, Dashboard, cron, launchd, paper-writing
workflow, autonomous scheduler, or production/24h/7×24 claim is part of
P2–P5.

## P3 Experiment Receipt ledger

P3 records what happened; it does not judge whether the result is scientifically
good. Initialize one new ledger outside the source repository, research
worktree, and Adapter directory:

```bash
python3 mvp/experiment_ledger.py init \
  --adapter-dir /absolute/run/mvp0-worker \
  --ledger-dir /absolute/run/mvp0-experiment-ledger
```

After every terminal P2 dispatch, record that exact turn before dispatching the
next task:

```bash
python3 mvp/experiment_ledger.py record \
  --ledger-dir /absolute/run/mvp0-experiment-ledger \
  --turn-receipt /absolute/run/mvp0-worker/turns/000001-task-id.json

python3 mvp/experiment_ledger.py verify \
  --ledger-dir /absolute/run/mvp0-experiment-ledger
```

The ledger requires P2 turns in exact sequence and makes exact duplicate
recording idempotent. A `COMPLETED` experiment must report the frozen
`command_argv` with exit code zero; creating files without reporting successful
execution is a Worker delivery, not an Experiment Receipt. `BLOCKED` and
`FAILED` turns are still recorded without upgrading their identity or outcome.
Public `verify` also requires the JSONL ledger to cover every terminal P2 turn
and rejects any receipt object not named by the index, so a deleted log suffix
cannot be mistaken for complete history. If a process stops after publishing
the immutable receipt object but before appending its JSONL entry, retrying the
same turn reuses that exact object and completes the append; unrelated orphan
objects remain fail-closed.

Each record binds:

- frozen Research IR, experiment hypothesis, stage, and expected observation;
- task contract, exact command, configuration, seeds, data versions, and
  environment versions;
- Adapter, fixed Claude session, MiniMax identity result, source commit,
  worktree HEAD observation, change manifest, and raw P2 turn/result hashes;
- immutable pre-execution input blobs plus result and observation-evidence
  blobs;
- exact Worker outcome and nullable/zero-preserving usage observations.

`recorded_at` is the bound P2 terminal timestamp rather than a new wall-clock
sample. That makes the content-addressed receipt deterministic across recovery
from an interrupted index append.

`experiment-receipts.jsonl` appends the complete closed receipt and its digest.
The same receipt is stored immutably at
`objects/sha256/<receipt-sha256>.json`; evidence bytes live at
`blobs/sha256/<artifact-sha256>`. Every receipt names the previous digest, and
`verify` replays the JSONL/object equality, chain, P2 lineage, frozen task/IR,
and all blobs.

P3 deliberately has no evaluator and emits no KEEP, PIVOT, STOP, RECOMPILE,
claim acceptance, SOTA, or paper-readiness decision. Those are P4 Evidence Gate
concerns.

## P4 deterministic Evidence Gate

P4 consumes the complete P3 ledger and, for a `READY` evaluator, one closed
[`evaluator-report/v1`](schemas/evaluator-report.schema.json). The report must
bind the exact Research IR and Experiment Receipt, frozen evaluator executable
hash and argv, baseline, task seeds, every primary/guardrail metric, every
frozen stop rule, and source blobs already archived by P3. The evaluator report
contains measurements, never a decision.

Initialize a separate Gate store, then decide exactly once for a receipt:

```bash
python3 mvp/evidence_gate.py init \
  --ledger-dir /absolute/run/mvp0-experiment-ledger \
  --store-dir /absolute/run/mvp0-evidence-gate

python3 mvp/evidence_gate.py decide \
  --store-dir /absolute/run/mvp0-evidence-gate \
  --experiment-receipt-sha256 RECEIPT_SHA256 \
  --evaluator-report /absolute/run/evaluator-report.json

python3 mvp/evidence_gate.py verify \
  --store-dir /absolute/run/mvp0-evidence-gate
```

Process receipts in P3 sequence. Gate records must remain a contiguous prefix
of the P3 ledger, so a later receipt cannot be decided while an earlier one is
still undecided. P4 validates and archives the closed evaluator report; it does
not launch the domain evaluator process itself.

For `BLOCKED` or `FAILED` receipts, omit `--evaluator-report`; the result is
PIVOT unless a frozen budget is exhausted, in which case it is STOP. A
completed receipt under a `PLANNED` evaluator yields RECOMPILE so P5 can
propose a new IR that binds the evaluator implementation. P4 never treats a
Worker-authored statement as evaluator output.

For a completed receipt with a `READY` evaluator, the deterministic priority is:

1. frozen falsification, triggered STOP rule, or exhausted budget → `STOP`;
2. triggered RECOMPILE rule → `RECOMPILE`;
3. all seed, primary threshold, primary baseline non-inferiority, and guardrail
   checks pass → `KEEP`;
4. otherwise → `PIVOT`.

Falsification requires the metric's frozen minimum seed count. Baseline
comparison uses the primary metric's frozen aggregation and direction; P4
requires non-inferiority but invents no unfrozen superiority margin. Reaching a
hard budget can produce STOP while preserving `candidate_accepted=true`, so the
evidence assessment is not erased by the execution cap.

The Gate canonicalizes and archives the evaluator report and evaluator
implementation, publishes a content-addressed
[`evidence-gate-decision/v1`](schemas/evidence-gate-decision.schema.json), and
creates one immutable record keyed by Experiment Receipt SHA-256. A second
report for the same receipt is rejected, limiting adaptive Gate queries. Full
verification rebuilds every decision from the frozen IR, complete P3 lineage,
archived evaluator, report, metric truth table, stop rules, and historical
budget prefix. Exact publication interruption is recoverable; unrelated orphan
objects fail closed.

P4 does not judge novelty, paper quality, SOTA, or publication readiness. It
does not generate failure analysis, `recompile_request.json`, a revised IR, or
the next Worker task. Those are P5 Recompile Loop responsibilities.

## P5 evidence-bound Recompile Loop

P5 starts only from the latest `PIVOT` or `RECOMPILE` decision in a verified
P4 prefix. `KEEP` and `STOP` are terminal for this path. Initialize a separate
store; its frozen prefix remains replayable even if the same P4 store later
appends decisions while continuing the current IR:

```bash
python3 mvp/recompile_loop.py init \
  --gate-store /absolute/run/mvp0-evidence-gate \
  --store-dir /absolute/run/mvp0-recompile
```

Use the strongest Codex model with
[`prompts/codex-recompile-analyst.md`](prompts/codex-recompile-analyst.md).
Publish exactly one [`failure-analysis/v1`](schemas/failure-analysis.schema.json)
for the frozen decision. It must cover the exact ordered P3 prefix and may cite
only content-addressed P3 evidence:

```bash
python3 mvp/recompile_loop.py analyze \
  --store-dir /absolute/run/mvp0-recompile \
  --analysis /absolute/run/failure-analysis.json

python3 mvp/recompile_loop.py request \
  --store-dir /absolute/run/mvp0-recompile \
  --request /absolute/run/recompile-request.json
```

The closed [`recompile-request/v1`](schemas/recompile-request.schema.json)
chooses one path:

- `CONTINUE_CURRENT_IR` is available only after `PIVOT`. It names one
  unattempted experiment already frozen in the current IR whose complete
  transitive dependency set has succeeded. It requests no IR changes and does
  not itself dispatch that experiment.
- `RECOMPILE_IR` is available after `PIVOT` or `RECOMPILE`. It names every
  top-level scientific contract section that may change and every constraint
  that must remain byte-identical. A Gate `RECOMPILE` cannot fall back to the
  continuation path.

For a recompile request, draft Research IR N+1, preserving `ir_id`, setting
`version = N + 1`, and binding `parent_ir_sha256` to the frozen parent. P5
requires the candidate's actual changed top-level roots to equal the request:

```bash
python3 mvp/recompile_loop.py compile \
  --store-dir /absolute/run/mvp0-recompile \
  --request-sha256 REQUEST_SHA256 \
  --candidate-ir /absolute/run/research-ir-v2.json \
  --author codex/recompile-compiler
```

`compile` publishes a normal P1 `research-ir-proposal/v1` and stops at
`AWAITING_HUMAN_CRITIQUE`. Run the existing P1 critique, revision, and Human
Approval transitions. Human-requested revision may change bytes inside the
already requested roots, but cannot expand the root set or alter retained
constraints. After P1 freezes the final IR, bind it back to P5:

```bash
python3 mvp/recompile_loop.py bind-freeze \
  --store-dir /absolute/run/mvp0-recompile \
  --proposal-sha256 P5_PROPOSAL_SHA256 \
  --freeze-receipt /absolute/compiler-store/receipts/sha256/CHILD_FREEZE.json

python3 mvp/recompile_loop.py verify \
  --store-dir /absolute/run/mvp0-recompile
```

P5 permits one linear analysis/request/proposal/freeze lineage per store,
limits post-hoc reinterpretation to one analysis and request, and replays exact
object inventories. It does not invoke Claude Code, create a P2 Adapter for the
child IR, select paper claims, or execute an autonomous loop. A new approved IR
starts a new bounded P2–P5 lineage only under separate execution authority.
