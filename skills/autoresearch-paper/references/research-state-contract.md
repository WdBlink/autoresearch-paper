---
name: research-state-contract
description: Hash-bound evaluator, typed failures, and final writing gate.
---

# Research State Contract

Research and runtime health are separate state machines. Heartbeat or worker
failure cannot become scientific evidence, request a structural pivot, or
enable CP-03.

## Canonical staged authority

For staged research, `state/staged_research/v1/` is the sole runtime truth.
It is controller-owned from first publication: caller-authored bootstrap files
must remain under `control/staged-inputs/` or `control/review-materials/`, and
must never be written directly into the canonical namespace;
`init-staged-research` is its only initial publisher.
Authorization has the same controller boundary: Agents may pass a protected
key pathname to `create-human-action` and `apply-human-action`, but must never
read the key, compute an HMAC, or construct an authorization receipt. Only the
applied receipt returned by the controller may initialize staged state.
The controller derives `state/progress.json` and
`state/research-dossier.md` from that namespace. Both are rebuildable,
non-authoritative projections: editing, deleting, or forging either one cannot
authorize a transition. Run `rebuild-staged-projections --plan-dir PLAN` to
regenerate them after canonical validation.

Legacy fallback is permitted only when the canonical staged namespace is
absent. If it exists but its state is unreadable, malformed, or unknown,
monitoring fails closed as `staged_invalid`; it must not consult or mutate the
legacy projection.

New v0.17 plans use capacity v2. The active envelope's
`stage_budget_and_stop.worker_dispatches` limits Workers in that stage, while
the capacity ledger's `worker_dispatch_capacity` limits Workers across the
plan. `stage_review_capacity` is separate and non-transferable. CP-01, CP-02,
and CP-04 have distinct non-fungible slots; CP-03 may have its own optional
slot. A dispatch must have capacity in its own class, and Worker dispatch must
also satisfy both the per-stage and global Worker limits. A signed frontier top-up
(`authorize_frontier_capacity`) does not increase, refund, or transfer
Worker, `STAGE-REVIEW`, or checkpoint capacity. Legacy capacity v1 keeps
existing-plan lifecycle and idempotent replay compatibility, but it cannot
authorize `advance-staged-research`.

The initial signed and applied `authorize_contract` may pre-authorize exactly
one explicit next-stage ID and one automatic crossing. Absence of that field is
not permission: `silence_is_approval` is always false. Once the source stage has
a canonical terminal decision, persisted MiniMax report, and fresh strongest-policy
non-M3 review, `advance-staged-research` derives a continuation
receipt bound to those artifacts, the initial authorization, and the exact next
envelope. It then journals compile → preflight → authorize → the start of
exactly one next-stage Worker. The command is replay-safe and stops at Worker
start; it does not assert second-stage completion or scientific success.

## Frozen evaluator

`run-evaluator` is a controller-owned execution that persists immutable
evaluator/evidence/candidate hashes and the observed metric/value. The closed
declarative evaluator must read that value from the candidate artifact;
candidate-independent evidence values cannot become candidate verdicts.
`freeze-evaluator` consumes a calibration execution receipt and the exact
closed `metric_contract` audited by CP-02. It persists that artifact's hash,
metric, comparison operator, threshold, and the evaluator/evidence hashes.
There are no independent threshold CLI arguments. CP-02 `freeze_evaluator`
must already be APPLIED.

`record-evaluator-verdict` consumes a candidate execution receipt; callers
cannot submit value or PASS/FAIL. The controller derives the verdict from the
frozen comparison.
Validated immutable verdicts live in `state/evaluator_verdicts/` and are named
in the fsynced evaluator audit.

`freeze-evaluator` snapshots evaluator, evidence, and metric-contract bytes
into the controller-owned, read-only `state/evaluator_materials/` namespace.
Candidate runs are rebound to those canonical bytes. A production acceptance
decision then replays the full authority chain:

```bash
python3 references/scripts/harness-runtime.py check-scientific-acceptance \
  --plan-dir PLAN --verdict state/evaluator_verdicts/CANDIDATE.json
```

The immutable receipt binds the evaluator execution, frozen contract,
candidate, evidence, metric, operator, threshold, and derived PASS/FAIL. For
unattended conference/journal plans it also requires the current evaluator
admission. A normal writing gate consumes this receipt; a stored PASS field
alone is not sufficient.

Bare text such as `research_acceptance.md: PASS`, `WAIVED_BY_HUMAN`, or
`WAIVED_NEGATIVE_RESULT` is compatibility evidence only and never authority.
The executable gate requires `--verdict`, or an immutable applied
`waive_acceptance` receipt bound to tier, candidate, evaluator contract, and
scope. Pending records are not authority. Negative-result waiver is
arxiv-only. Every tier requires APPLIED CP-04 subtype
`prewriting_final_evidence` and produces a durable gate audit. That exact gate
grants only `paper-deliverable` at `artifacts/paper/paper.md`; before it,
workers can produce only `research-intermediate` artifacts inside their own
normalized task namespace. Names and prose never imply writing authority.
CP-04 and the writing gate also bind an immutable figure-gate receipt produced
from a non-empty plan inventory. The controller revalidates the inventory,
every manifest, every review receipt, and every current output hash before
granting writing authority.

```bash
python3 references/scripts/harness-runtime.py check-figure-gate \
  --plan-dir PLAN --inventory out/figures/required-figures.json \
  --requirements state/figure-requirements.json
python3 references/scripts/research-state-guard.py check-writing-gate \
  --plan-dir PLAN --tier conference \
  --verdict state/evaluator_verdicts/CANDIDATE.json \
  --figure-gate-receipt state/figure_gates/DECISION.json
```

## Typed failures

`state/failure_state.json` has independent counters for:

- `runtime_stall`
- `implementation_failure`
- `scientific_no_improvement`
- `duplicate_direction`
- `verifier_rejection`
- `goal_drift`
- `evaluator_integrity`

Non-scientific failures use unique `(class,fingerprint)` keys. Scientific
failures require a complete normalized direction descriptor and canonical
FAIL verdict bound to a live candidate; free-text fingerprints are rejected.
Distinct direction identity hashes the normalized scientific descriptor plus
the frozen evaluator identity, never candidate bytes. Each outcome still binds
its specific candidate and FAIL receipt.
The state additionally stores the direction registry and frozen
`scientific_pivot_threshold` (default 2). There is no `stale_count` transition
authority.

Only distinct validated direction hashes count toward pivot eligibility. Once
eligible, `research-state-guard.py validate-pivot` consumes the applied CP-03
receipt and rejects a direction already present in the failed registry.
Runtime stalls remain runtime stalls regardless of count.

The last two classes are controller-detected only. Run
`check-research-integrity` to compare the canonical durable goal, constraints,
evaluator, frozen contract, and required admission against current bytes.
Goal drift routes to pause/rebaseline; evaluator-integrity drift routes to
autonomy revocation and re-admission. Neither increments runtime-stall or
scientific-non-improvement, and workers cannot inject these labels through
`record-failure`.

## Sparse frontier gates

- CP-01 audits the initial plan and gates execution approval.
- CP-02 audits the evaluator and gates evaluator freeze.
- CP-03 is creatable only after typed scientific pivot eligibility and gates a
  structural pivot.
- CP-04 resolves an acceptance dispute or performs the final prewriting
  evidence audit. The latter gates conference/journal writing.

All four gates require checkpoint-specific complete evidence profiles and bind
current hashes. Actual consumers enforce CP-01 dispatch/promotion, CP-02
evaluator execution/freeze, CP-03 pivot application, and both CP-04 dispute and
writing paths. Changed evidence invalidates the dependent transition even
after process restart. Structural-pivot consumption is the one deliberate
exception during receipt reconstruction: the controller verifies the frozen
request/response, proposal, applied transition, and `last_applied_pivot`
identity while accepting the expected post-consumption failure-state hash.
The applied pivot also stores the frozen pre-state hash and a canonical hash of
the exact post-pivot state projection (excluding only the embedded receipt);
receipt reconstruction fails if any unrelated counter, event, registry, or
metadata field drifts after the atomic state commit.
