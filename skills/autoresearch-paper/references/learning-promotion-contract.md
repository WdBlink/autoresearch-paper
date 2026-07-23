---
name: learning-promotion-contract
description: Two-stage audited episode-memory and proposal promotion.
---

# Gated Learning Promotion

Learning never edits a skill, policy, spec, or evaluator directly. The
deterministic controller issues immutable evidence receipts through two
separate gates.

## Episode to audited memory

```bash
python3 references/scripts/harness-runtime.py promote-episode-memory \
  --plan-dir PLAN --episode-manifest EPISODE.json \
  --diagnosis DIAGNOSIS.json --replay REPLAY.json \
  --validation HELDOUT_OR_REGRESSION.json --audit AUDIT.json \
  --auditor-identity READ_ONLY_AUDITOR.json
```

The episode manifest binds plan identity and a purpose-bearing evidence
manifest. Diagnosis is exactly `skill_defect` or `execution_lapse` and binds
the normalized evidence-manifest hash. Replay must reproduce identical result
identities. Validation is a passing held-out or regression result with zero
failed cases. The audit is independently authored outside worker-owned
namespaces, binds the episode and diagnosis hashes, and has no findings.

Both accepted and rejected memory receipts are immutable and append-audited.
An execution-lapse memory may be retained as `AUDITED`, but it is not eligible
to justify a skill/policy/spec/evaluator proposal.

## Audited memory to proposal

```bash
python3 references/scripts/harness-runtime.py promote-learning-proposal \
  --plan-dir PLAN --memory-receipt MEMORY.json \
  --proposal CHANGE.patch --target-kind skill \
  --replay REPLAY.json --validation REGRESSION.json \
  --audit FRESH_AUDIT.json --auditor-identity READ_ONLY_AUDITOR.json
```

Proposal promotion revalidates the complete memory source chain and requires a
second replay, held-out/regression result, and a fresh subject-bound audit.
The result is only an `APPROVED` or `REJECTED` proposal receipt with
`application_authority:false`. It never applies proposal bytes.

Identical proposal bytes have one registry identity. A rejected proposal
cannot re-enter later under different review files as unreviewed novelty.

## Evaluator changes

Evaluator proposals additionally require a dedicated, hash-bound human action:

```bash
python3 references/scripts/harness-runtime.py create-human-action \
  --plan-dir PLAN --plan-id PLAN_ID \
  --action authorize_evaluator_change --key-file KEY --expires-in 300 \
  --reason "proposal-only review" --learning-proposal CHANGE.json
python3 references/scripts/harness-runtime.py apply-human-action \
  --plan-dir PLAN --record RECORD --key-file KEY \
  --expected-action authorize_evaluator_change
```

The applied receipt authorizes only promotion of the exact proposal bytes for
human review. It still does not apply or activate a new evaluator.
