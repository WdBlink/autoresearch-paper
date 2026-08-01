# MVP-0 P1–P2 — Research Compiler and Minimal Worker Adapter

This directory is the new Thin Loop implementation path. P1 compiles an open
research idea into one immutable, executable, and falsifiable Research IR. P2
binds an owner-reviewed IR to one detached research worktree and one exact
Claude Code/MiniMax session, then accepts only closed JSON Worker results. The
implementation does not import or call the Legacy v0.20 Harness.

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
the scientific contract.

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
  boundary in `allowed_paths`.

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

Each successful or failed launched turn stores:

```text
adapter-dir/
├── adapter-manifest.json          immutable identity binding
├── session.json                   minimal mutable session pointer
├── contracts/sha256/*.json        immutable task contracts
├── runs/000001-task-id/
│   ├── instruction.json
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
workflow, autonomous loop, recovery controller, or production/24h/7×24 claim
is part of P2.
