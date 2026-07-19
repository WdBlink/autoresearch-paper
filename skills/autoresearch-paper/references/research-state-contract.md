---
name: research-state-contract
description: Hash-bound evaluator, typed failures, and final writing gate.
---

# Research State Contract

Research and runtime health are separate state machines. Heartbeat or worker
failure cannot become scientific evidence, request a structural pivot, or
enable CP-03.

## Frozen evaluator

`run-evaluator` is a controller-owned execution that persists immutable
evaluator/evidence/candidate hashes and the observed metric/value.
`freeze-evaluator` consumes a calibration execution receipt and persists the
evaluator and evidence hashes, metric, comparison operator, threshold, and
contract hash. CP-02 `freeze_evaluator` must already be APPLIED.

`record-evaluator-verdict` consumes a candidate execution receipt; callers
cannot submit value or PASS/FAIL. The controller derives the verdict from the
frozen comparison.
Validated immutable verdicts live in `state/evaluator_verdicts/` and are named
in the fsynced evaluator audit.

Bare text such as `research_acceptance.md: PASS`, `WAIVED_BY_HUMAN`, or
`WAIVED_NEGATIVE_RESULT` is compatibility evidence only and never authority.
The executable gate requires `--verdict`, or an immutable applied
`waive_acceptance` receipt bound to tier, candidate, evaluator contract, and
scope. Pending records are not authority. Negative-result waiver is
arxiv-only. Every tier requires APPLIED CP-04 subtype
`prewriting_final_evidence` and produces a durable gate audit.

```bash
python3 references/scripts/research-state-guard.py check-writing-gate \
  --plan-dir PLAN --tier conference --verdict state/evaluator_verdicts/CANDIDATE.json
```

## Typed failures

`state/failure_state.json` has independent counters for:

- `runtime_stall`
- `implementation_failure`
- `scientific_no_improvement`
- `duplicate_direction`
- `verifier_rejection`

Non-scientific failures use unique `(class,fingerprint)` keys. Scientific
failures require a complete normalized direction descriptor and canonical
FAIL verdict bound to a live candidate; free-text fingerprints are rejected.
The state additionally stores the direction registry and frozen
`scientific_pivot_threshold` (default 2). There is no `stale_count` transition
authority.

Only distinct validated direction hashes count toward pivot eligibility. Once
eligible, `research-state-guard.py validate-pivot` consumes the applied CP-03
receipt and rejects a direction already present in the failed registry.
Runtime stalls remain runtime stalls regardless of count.

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
after process restart.
