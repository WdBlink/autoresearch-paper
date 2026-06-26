---
name: lifecycle-contract
description: Resource lifecycle and cleanup contract for autoresearch-paper runs.
---

# Lifecycle Contract

Every long-running `autoresearch-paper` run must be resumable and must
clean up its runtime resources on stop, abort, or completion. Outputs and
logs are preserved; runtime resources are not.

## Execution Procedure

```
manage_lifecycle(plan_dir, action) -> lifecycle_report

read resource_manifest.json
if action == resume -> verify and repair resources, then write watchdog_health.json
if action in {stop, abort, complete} -> run cleanup in fixed order
preserve outputs and state history
write cleanup_report.md and update manifest status
```

## Resource Manifest

Each plan directory owns a `resource_manifest.json` file:

```json
{
  "schema_version": 1,
  "plan_id": "plan_xxx",
  "plan_dir": "/abs/path/to/plan",
  "topic_slug": "uav-coverage",
  "tier": "conference",
  "status": "running",
  "created_at": "2026-06-26T00:00:00Z",
  "updated_at": "2026-06-26T00:00:00Z",
  "bootstrap_script": "/abs/path/references/bootstrap-watchdog.sh",
  "agents": [
    {"name": "uav-coverage-wd", "role": "watchdog", "ephemeral": true}
  ],
  "sessions": [],
  "crons": [
    {"agent": "uav-coverage-wd", "name": "uav-coverage-wd-liveness", "ephemeral": true}
  ],
  "hooks": [
    {"name": "first-action-last-seen-uav-coverage.json", "ephemeral": true}
  ],
  "launchd": [
    {
      "label": "com.mavis.plan-rescue-daemon",
      "plist": "$HOME/Library/LaunchAgents/com.mavis.plan-rescue-daemon.plist",
      "run_scoped": false
    }
  ],
  "local_processes": [],
  "remote_processes": [],
  "locks": []
}
```

Only `ephemeral=true` resources are deleted automatically. Shared global
resources, such as the default rescue launchd daemon, are verified but not
removed unless `run_scoped=true`.

## Agent Policy

Do not create one permanent Mavis team member per iteration, retry,
direction, or paper section.

Allowed long-lived roles:

- orchestrator
- implementer
- experimenter
- verifier
- watchdog

Workers should usually be fresh sessions, not permanent agent members.
Any temporary member must be registered in `resource_manifest.json` with:

```json
{"name":"tmp-method-v3","ephemeral":true,"ttl":"24h","plan_id":"plan_xxx"}
```

Cleanup must archive or delete temporary members.

## Resume Semantics

`resume-plan.sh` and L0 guard must:

1. Read `resource_manifest.json`.
2. Verify cron, hook, launchd, and process health where the runtime
   exposes list/status commands.
3. Reuse resources that are alive.
4. Recreate missing watchdog resources by calling the recorded
   `bootstrap_script` with `topic_slug`, `tier`, and `plan_dir` when the
   prompt file still exists.
5. Write `state/watchdog_health.json` with `healthy`, `missing`, and
   `repaired` fields.

If repair is impossible, resume must still mark the missing resource and
surface `rebootstrap_required`; it must not pretend the plan is healthy.

## Cleanup Semantics

Cleanup order is fixed:

1. Prevent new work: write `control/stop_requested.json` or completion
   marker.
2. Ask the plan engine to stop/cancel when a `plan_id` is known.
3. Stop/wait local and remote background processes.
4. Delete producer polling crons.
5. Delete watchdog cron and hook.
6. Unload run-scoped launchd jobs.
7. Archive/delete temporary agents and sessions.
8. Delete lockfiles and pidfiles owned by the plan.
9. Write `cleanup_report.md` and append `state/cleanup_history.jsonl`.
10. Update `resource_manifest.json.status`.

Cleanup is best-effort per resource but mandatory as a workflow step.
Failures must be reported as residual items in `cleanup_report.md`.

## Completion

On normal completion:

- Preserve `out/`, `state/`, `watchdog-log.md`, `cleanup_report.md`, and
  the manifest.
- Clean runtime resources: cron, hook, temporary agents, temporary
  sessions, locks, and background processes.
- Set `resource_manifest.json.status = "completed_cleaned"` when no
  residual runtime resources remain; otherwise set
  `completed_with_residuals`.

## Stop / Abort

On explicit user stop or abort:

- Write the stop reason to `control/stop_requested.json`.
- Cancel the Mavis plan when possible.
- Run `cleanup-plan-resources.sh`.
- Set `resource_manifest.json.status = "stopped_cleaned"` when cleanup
  succeeds; otherwise set `stopped_with_residuals`.

The skill must not end by telling the user to manually hunt for old
crons, hooks, or background processes. Manual cleanup is a fallback only
after the automated cleanup report names the exact residual item.
