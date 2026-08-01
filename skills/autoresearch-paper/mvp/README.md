# MVP-0 P1 — Research Compiler

This directory is the new Thin Loop implementation path. P1 compiles an open
research idea into one immutable, executable, and falsifiable Research IR. It
does not import or call the Legacy v0.20 Harness.

## Boundary

Research IR contains scientific semantics only:

- problem and central claim;
- falsification predicates and provisional related-work gap;
- honest baseline/evaluator readiness, metrics, and guardrails;
- allowed code search space and initial experiment DAG;
- experiment budget and STOP/RECOMPILE rules.

It deliberately excludes model routing, Claude/MiniMax sessions, Codex call
budgets, watchdogs, cron, dashboard state, paper templates, and lifecycle
slots. Those concerns cannot change what constitutes scientific success.

## Workflow

```text
proposal IR
   │ schema + semantic validation
   ▼
content-addressed proposal
   │ independent critique
   ▼
content-addressed critique
   │ explicit JSON Pointer revision + required-finding closure
   ▼
content-addressed revision and revised IR
   │ independent approval
   ▼
content-addressed freeze receipt
```

Every object is canonical UTF-8 JSON at
`<store>/objects/sha256/<digest>.json`. Freeze receipts live at
`<store>/receipts/sha256/<digest>.json`. Publishing is immutable and
collision-checked. `verify-freeze` reconstructs the complete lineage from the
digests rather than trusting filenames or producer claims.

`ENGINEERING_ACCEPTANCE` proves the compiler workflow only. `OWNER_REVIEWED`
records that a human owner reviewed the scientific contract, but P1 does not
authenticate lifecycle authority and neither scope authorizes Worker dispatch.

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
identical recorded author/reviewer/approver identity, but P1 does not
authenticate who controls those identity strings.

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
