# First-Action Last-Seen Hook

`PostToolUse` hook that records every tool invocation by a worker
agent into `<plan-dir>/last_seen.jsonl`. The watchdog reads this on
each hourly patrol to detect liveness and staleness.

This file is consumed by `bootstrap-watchdog.sh`. The script reads
its contents and writes them to `~/.mavis/hooks/<name>.json.md` (a
plain markdown file with frontmatter). The legacy `mavis hook create -b`
CLI is removed in v0.7.0; the daemon picks the file up on its next scan.

## Why PostToolUse and not SessionStart

`SessionStart` fires only once per session; we want a heartbeat on
every meaningful action. PostToolUse with a matcher on the most
common tools (`Read|Write|Edit|Bash`) gives us a heartbeat that
approximates "the agent is still working" without firing on
trivial internal events.

## Hook body (markdown with code block — what `~/.mavis/hooks/<name>.json.md` expects)

````markdown
# First-Action Last-Seen — append a heartbeat line to the plan's last_seen.jsonl

This hook fires on every `PostToolUse` event matching `^(Read|Write|Edit|Bash)$`.

It appends a single JSONL line to `${PLAN_DIR}/last_seen.jsonl`:

```bash
#!/usr/bin/env bash
# ${PLAN_DIR}/last_seen.jsonl path is injected by the skill via env var.
PLAN_DIR="${PLAN_DIR:?PLAN_DIR must be set by the skill before invoking the hook}"
mkdir -p "${PLAN_DIR}"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
AGENT="${MAVIS_AGENT_NAME:-unknown}"
SESSION="${MAVIS_SESSION_ID:-unknown}"
TOOL="${MAVIS_TOOL_NAME:-unknown}"
printf '{"ts":"%s","agent":"%s","session":"%s","tool":"%s"}\n' \
  "${TS}" "${AGENT}" "${SESSION}" "${TOOL}" \
  >> "${PLAN_DIR}/last_seen.jsonl"
```

## Required environment

The skill must export these before the worker session starts:

- `PLAN_DIR` — absolute path to the plan output directory.

The hook runtime provides:

- `MAVIS_AGENT_NAME` — name of the worker agent (e.g. `literature-agent`).
- `MAVIS_SESSION_ID` — id of the current session.
- `MAVIS_TOOL_NAME` — name of the tool that just ran (e.g. `Read`).

If any of these are missing, the hook logs to stderr and exits 0
(fail-open — never block the worker).

## What the watchdog does with this file

On each patrol tick, the watchdog:

1. Reads the last 1000 lines (or all, whichever is fewer).
2. Groups by `agent` (or `session`, if agent is `unknown`).
3. For each group, finds the most recent `ts`.
4. Compares each `ts` against that task's expected wall-clock from
   plan.yaml. If older than 2× expected, emit `stale-task` finding.
5. If a task has no entry at all in last_seen.jsonl but is in
   `running` state per `mavis team plan status` (the only `mavis`
   subcommand still exposed as a CLI in v0.7.0+), emit
   `no-heartbeat` finding (severity `critical`).
````