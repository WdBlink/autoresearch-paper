---
name: lifecycle-contract
description: Authenticated lifecycle and owned-resource cleanup contract.
---

# Lifecycle Contract

The deterministic Claude target controller owns lifecycle state. A model can
propose an action but cannot authenticate it. Pause, resume, stop, worker
cancellation, waiver, and destructive cleanup require an expiring signed human
record as documented in `claude-code-runtime.md`.

## Human authority

The user-owned key is at least 32 bytes and mode `0600`. Records bind plan ID,
action, nonce, issue/expiry timestamps, actor, key ID, and details. Successful
application persists a hash-bound PREPARED journal, reserves replay state,
performs the mutation, writes the immutable receipt/audit, and commits the
journal. Restart rolls an exact PREPARED action forward. Forged,
expired, wrong-action, and cross-plan records produce no mutation. An exact
retry bound to the same durable operation ID returns its existing receipt; an
unbound replay is rejected and no retry can apply a second mutation.
The originating operation ID is stored in the command-owned PREPARED journal
for both human actions and resource cleanup, and PREPARED/COMMITTED recovery
requires exact equality with that ID.

Compatibility wrappers require explicit authority:

```bash
pause-plan.sh PLAN --record RECORD --key-file KEY
resume-plan.sh PLAN --record RECORD --key-file KEY
stop-plan.sh PLAN --record RECORD --key-file KEY
```

The canonical waiting journal binds the exact authorization proposal path,
SHA-256, and prepared operation ID. Every resume validates all three before
changing state or applying an action. A replacement, redirect, or reconstructed
proposal cannot be rebound by newly created action records.

Only `resume-plan.sh --legacy-mavis` and cleanup with `--legacy-mavis` may touch
legacy resources. The ordinary path never invokes MAVIS.

## Resource ownership

`resource_manifest.json` binds every target-owned removable item:

```json
{
  "schema_version": 1,
  "plan_id": "plan_xxx",
  "resources": [
    {
      "resource_id": "temporary-result",
      "path": "out/temporary-result.json",
      "ephemeral": true,
      "run_scoped": true,
      "ownership_generation": "random-plan-owned-value"
    }
  ]
}
```

`remove-resource` accepts only a regular non-symlink file inside the normalized
plan directory, an exact ownership token, and an applied `cleanup_resource`
receipt for that resource. It refuses directories, symlinks, shared items,
path escapes, token mismatch, changed content/identity, and authorization replay.
A PREPARED/COMMITTED recovery journal rolls forward an unlink interrupted before
its receipt commit; a recreated file needs a new generation and authorization.

`cleanup-plan-resources.sh` validates an applied stop receipt but grants no
manifest-wide deletion. Aggregate cleanup is rejected; each resource requires
its own applied `cleanup_resource` receipt through `remove-resource`. The
script preserves outputs, state, audit history, and reports; legacy agents,
sessions, hooks, and crons remain untouched unless `--legacy-mavis` is explicit.
The terminal human boundary requires an exact one-to-one cleanup action set for
all eligible manifest resources. An empty set is valid only when the manifest
contains no eligible removable resource; a missing declared resource without a
cleanup journal fails closed.

## State

- `state/controller.json`: current deterministic lifecycle state.
- `control/pause_requested.json`, `resume_signal.json`,
  `stop_requested.json`: canonical applied receipts.
- `state/human_action_replay.json`: used record/nonce pairs.
- `state/human_action_audit.jsonl`: fsynced action audit.
- `state/cleanup_authorizations/`: immutable cleanup receipts.
- `state/cleanup_receipts.jsonl`: removed owned-resource audit.
- `state/terminal_snapshots/<sha256>`: controller-owned, read-only terminal
  bytes. Manifests cite these snapshots; producer paths are provenance only.

Authenticated stop changes controller state only. Cleanup truth comes from
individual removal receipts; residual items are named in `cleanup_report.md`.
