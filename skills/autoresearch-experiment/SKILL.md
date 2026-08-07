---
name: autoresearch-experiment
description: Use when an Adapter-issued frozen Experiment Contract authorizes a new bounded candidate run or a bound Evidence request resumes that contract.
---

# Auto-Research Experiment

Run the complete bounded **Research → Development → Review → Record** loop
inside one Experiment Contract. Own candidate optimization, not evaluator
construction, final scientific validation, or paper production.

## Sole handoff modes

Accept exactly one of these compact inputs per invocation; receiving both is
invalid:

| Mode | Sole input artifact |
| --- | --- |
| New run | `autoresearch/experiment-contract.md` |
| Evidence resume | `autoresearch/evidence-request.md` |

## Entry gate

For new-run mode, accept one Adapter-issued frozen
`autoresearch/experiment-contract.md` as that invocation's sole compact
handoff. Proceed only when that contract:

- identifies its Adapter provenance and frozen `research-brief.md`;
- identifies and binds a `ready` evaluator, including command, fixed inputs and
  splits, seed policy, scoring, KEEP/DISCARD gate, readiness evidence, and
  candidate-edit isolation;
- freezes target, baseline, mutable/forbidden surfaces, budget, authority,
  rollback, stop, and reauthorization conditions; and
- links every necessary project file rather than requiring another prior package.

If evaluator identity, integrity, isolation, readiness evidence, or execution is
absent, mutable, inconsistent, or invalid, do not iterate. Emit
`experiment-evaluator-invalid` and return only to Adapter
(`karpathy-autoresearch-adapter`). Never classify readiness or route directly to
evaluator construction. For a non-evaluator contract change, record
`contract-reauthorization-needed` and stop under the contract with no route.

## Evidence resume

Accept `autoresearch/evidence-request.md` only as a compact resume manifest. It
must immutably bind the exact Adapter-issued frozen Experiment Contract identity
and hash, Candidate Package manifest, evaluator identity, requested missing
evidence, permitted scope, and provenance. Verify those bindings, then open the
linked frozen contract and only the linked state needed to resume.

The request adds no authority. If requested work, files, evaluator use, budget,
or evidence collection falls outside the bound contract, emit terminal
`contract-reauthorization-needed`, perform no iteration, and never silently
broaden scope. An in-contract resume follows the same evaluator, KEEP/DISCARD,
ledger, and stop rules as a new run.

## Evaluator-invalid return

On any evaluator integrity, isolation, readiness, or execution failure, stop
before another iteration and emit
`autoresearch/evaluator-invalid-return.md`. This compact operational-return
manifest binds the stale Experiment Contract identity and hash, evaluator
identity, failure evidence, candidate and ledger state, and provenance. Route it
only to Adapter; it is not an Experiment resume input and authorizes no repair.

## Frozen contract

Treat the contract as the complete authority. **Never modify the frozen
evaluator**—including threshold, source, data, split, seed, baseline, command,
scoring, or adoption gate—to make a candidate pass. A screening metric may rank
or qualify one candidate for expensive Review; screening cannot authorize
adoption. Only the bound evaluator and KEEP rule can.

Read [the bounded loop reference](references/bounded-experiment-loop.md) only
when starting a run or recovering a recorded run.

## One transition

Operate one bounded candidate at a time:

1. **Research** — Read the contract and prior ledger rows. Record one
   falsifiable in-scope intervention, expected effect, allowed files, rollback
   point, and estimated cost.
2. **Development** — Implement only that intervention. Capture reproducible
   diff/configuration, command, environment, and input provenance.
3. **Review** — Run declared screening if any, then the frozen evaluator. Apply
   KEEP/DISCARD exactly. Restore the rollback point after DISCARD.
4. **Record** — Append an immutable `experiment-ledger.jsonl` row for every
   accepted, rejected, invalid, or stopped attempt before another candidate.

Never batch changes, carry an unreviewed candidate, or use a failed change as
the baseline.

## Candidate Package

Produce one `autoresearch/candidate-package/`. Its compact
`autoresearch/candidate-package/manifest.json` links the frozen Experiment
Contract, evaluator identity/readiness evidence, accepted candidate (or its
explicit absence), reproducible source/configuration, outcome summary,
experiment ledger, and evidence/log index. Keep raw evaluator/screening outputs
or stable references and all accepted/rejected ledger rows.

Record one honest outcome: `accepted`, `no-improvement`, `budget-exhausted`, or
`contract-reauthorization-needed`, with stop reason and remaining budget. Only a
manifest with an `accepted` candidate is the sole compact handoff to Evidence
(`autoresearch-evidence`). A no-candidate outcome is terminal; artifact presence
alone never advances it.

Do not create a Validated Research Package, Claim Boundary, or paper.

## Stop

Stop when success or another contract rule is met, budget is exhausted, no
permissible candidate remains, reauthorization is needed, or evaluator execution
becomes invalid. `no-improvement` and `budget-exhausted` are honest terminal
outcomes, not permission to weaken measurement. Any evaluator integrity or
readiness failure must preserve the record in the evaluator-invalid return and
return to Adapter; do not repair or reclassify it here.

Before an accepted handoff, reproduce the best candidate with the frozen
evaluator and ensure every transition has a ledger row. Experiment results are
private development evidence, not external transfer or scientific proof.

## Boundaries

Do not alter the Research Brief, invent/repair/classify an evaluator, redefine
contract authority, edit evaluator assets, approve an out-of-scope candidate,
conduct final evidence review, or write a paper. The four states above are the
complete Experiment lifecycle.
