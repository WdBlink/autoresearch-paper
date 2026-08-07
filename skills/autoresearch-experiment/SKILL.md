---
name: autoresearch-experiment
description: Use when a frozen Experiment Contract and a ready, isolated evaluator authorize bounded candidate search and a reproducible Candidate Package is needed.
---

# Auto-Research Experiment

Run the complete bounded XYZ loop—**Research → Development → Review →
Record**—inside one Experiment Contract. This skill owns candidate optimization,
not evaluator construction, final scientific validation, or paper production.

## Entry gate

Proceed only when all of these are supplied and internally consistent:

- a frozen `autoresearch/experiment-contract.md` that names the target,
  mutable and forbidden surfaces, evaluator command and inputs, baseline,
  KEEP/DISCARD rule, resource budget, authority, and stopping conditions;
- a `ready`, isolated evaluator or evaluator package whose command, data/split,
  scoring, and adoption gate are fixed; and
- writable candidate workspace plus a destination for
  `autoresearch/candidate-package/`.

If any item is absent, mutable, inconsistent, or needs changing, do not start an
iteration. Record `contract-reauthorization-needed` when a contract change is
requested; return evaluator gaps to Evaluator Engineering and contract changes
to Adapter.

## Frozen contract

Treat the contract as the complete authority for this run. Freeze its target and
scope, file permissions, evaluator identity/command/data/split/seed/scoring,
baseline, budget, KEEP/DISCARD rule, authority, and stop or re-authorization
conditions before the first candidate.

**Never modify the frozen evaluator**—including its threshold, data, split,
baseline, command, scoring, or adoption gate—to make a candidate pass. A
screening metric may rank or make one candidate eligible for expensive Review;
screening cannot authorize adoption. Only the declared frozen evaluator and
KEEP rule can do that.

Read [the bounded loop reference](references/bounded-experiment-loop.md) only
when starting a run or recovering a recorded run.

## One transition

Operate one bounded candidate at a time. Do not batch changes, carry an
unreviewed candidate forward, or use a failed change as the baseline.

1. **Research** — Read the frozen contract, current baseline, and prior ledger
   rows. Propose exactly one falsifiable, in-scope intervention and record its
   hypothesis, expected effect, allowed files, rollback point, and estimated
   cost. Stop rather than guessing beyond the contract.
2. **Development** — Implement only that intervention within the editable
   scope. Capture a reproducible diff/configuration, command, environment and
   input provenance. Do not edit forbidden surfaces or the evaluator.
3. **Review** — First run any declared cheap screening. If it qualifies, run
   the frozen evaluator against the frozen baseline and apply the declared
   KEEP/DISCARD rule exactly. A proxy gain alone is a null result for adoption.
   On DISCARD, restore the candidate workspace to its recorded rollback point.
4. **Record** — Append an immutable result row to
   `experiment-ledger.jsonl`, for every accepted and rejected attempt, before
   proposing another candidate. Update the best reproducible candidate only
   after a KEEP decision.

## Candidate Package

Produce exactly one `autoresearch/candidate-package/` for the run. It contains:

- the accepted best Candidate (or an explicit absence of an accepted Candidate),
  reproducible source/configuration, provenance, baseline comparison, and
  reproduction command;
- `experiment-ledger.jsonl` with complete accepted and rejected attempts;
- raw evaluator and screening logs or stable references to them; and
- an honest outcome: `accepted`, `no-improvement`, `budget-exhausted`, or
  `contract-reauthorization-needed`, plus the stop reason and remaining budget.

Do not replace rejected evidence with a summary or delete discarded artifacts
needed to reproduce the decision. Candidate Package is this skill's unique
product; do not create a Validated Research Package, Claim Boundary, or paper.

## Stop

Stop immediately and record the current state when the contract's success
threshold or stopping rule is met, the budget is exhausted, no permissible next
candidate remains, evaluator execution is invalid, or re-authorization is
needed. `no-improvement` and `budget-exhausted` are successful honest outcomes,
not invitations to relax the evaluator or invent a new metric.

Before handoff, ensure the selected best candidate (if any) still reproduces
with the frozen evaluator and that every attempted transition has a ledger row.
Route the frozen Candidate Package to Evidence for external validation; do not
claim external transfer, SOTA, or scientific proof from private development
results.

## Boundaries

Do not alter the Research Brief, invent or repair an evaluator, redefine
contract authority, edit evaluator assets, approve an out-of-scope candidate,
conduct final evidence review, or write/optimize a paper. Do not import or run
legacy MVP, Watchdog, repository-wide controller, or other supervisory runtime
as a requirement for this loop. The four states above are the complete
Experiment lifecycle.
