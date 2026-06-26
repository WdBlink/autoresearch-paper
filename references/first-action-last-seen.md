---
name: first-action-last-seen
description: Usage contract for the first-action last_seen hook asset registered by bootstrap-watchdog.sh.
---

# First-Action Last-Seen

This reference describes the heartbeat hook used by the L2 watchdog. The
runtime hook body lives in `assets/first-action-last-seen-hook.md`.

## Execution Procedure

```
register_last_seen_hook(plan_dir, topic_slug) -> hook_name

read assets/first-action-last-seen-hook.md
call mavis hook create <hook_name>.json with event PostToolUse
set PLAN_DIR for worker sessions before the hook runs
assert <plan-dir>/last_seen.jsonl exists
return hook_name
```

## Contract

- The hook appends one JSONL heartbeat to `<plan-dir>/last_seen.jsonl`
  after worker tool use.
- The hook is liveness-only; it must not edit research outputs.
- Bootstrap owns hook registration and records the hook in
  `resource_manifest.json` with `ephemeral=true`.
- Cleanup removes the hook only when it is marked ephemeral.
