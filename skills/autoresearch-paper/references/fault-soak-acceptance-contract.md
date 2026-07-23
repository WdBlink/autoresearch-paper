---
name: fault-soak-acceptance-contract
description: Seven-fault, multi-session soak, and bounded claim evidence.
---

# Fault and Soak Acceptance

T008 is an acceptance layer, not runtime authority. It freezes what will be
measured, binds observed fault/session evidence, and prevents release claims
from exceeding that evidence.

## Start a frozen profile

The profile names exactly seven scenarios—`process_death`, `missed_tick`,
`duplicate_trigger`, `state_corruption`, `budget_exhaustion`,
`evaluator_drift`, and `multi_session_restart`—plus planned duration, required
session restarts, and allowed claim kinds.

```bash
python3 references/scripts/harness-runtime.py start-acceptance-profile \
  --plan-dir PLAN --profile PROFILE.json
```

## Complete fault and soak evidence

Each fault record must report PASS for authority, idempotency, recovery, and
evidence, with a live immutable-hash manifest. Session observations bind
start/completion, newly applied transition IDs, cumulative accepted evidence,
maximum controller overlap, and unauthorized recovery count.

```bash
python3 references/scripts/harness-runtime.py complete-acceptance-profile \
  --plan-dir PLAN --profile-id PROFILE_ID \
  --fault-evidence FAULT.json \
  --session-observation SESSION.json
```

Repeat the two evidence arguments as required. Completion rejects missing or
duplicate fault scenarios, duplicate transitions, non-monotonic accepted
evidence, insufficient restarts/duration, overlap above one, and any
unauthorized recovery action.

## Bound release claims

```bash
python3 references/scripts/harness-runtime.py validate-acceptance-claim \
  --plan-dir PLAN --profile-id PROFILE_ID \
  --claim-kind bounded_fault_acceptance \
  --claimed-duration-seconds SECONDS
```

The claim kind must have been frozen in the profile and claimed duration cannot
exceed measured duration. `long_stability` additionally requires at least
86400 measured seconds; `seven_by_twenty_four` requires at least 604800.
`full_cutover` must be explicitly allowed by the profile. A short T008 run may
validate the mechanism and bounded fault/restart acceptance, but it is not
evidence for 24h or 7×24 stability.
