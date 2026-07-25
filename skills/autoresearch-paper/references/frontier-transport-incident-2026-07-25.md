# Frontier Transport Incident: CP-01 Budget Deadlock

Date: 2026-07-25
Affected release: v0.14.0
Fixed release: v0.14.1

## Impact

A Claude Code run exhausted its four-call frontier budget before CP-01 could
produce accepted advice. The controller correctly blocked
`approve_execution`, but the plan could not make further progress.

## Failure chain

The four reservations did not represent four equivalent network timeouts:

1. Codex rejected a controller-owned non-Git plan directory because the runtime
   omitted `--skip-git-repo-check`.
2. The frozen frontier model was `MiniMax-M3`, which the authenticated ChatGPT
   Codex provider does not support.
3. The frontier response schema used `{"const": 1}` without an explicit
   integer type and was rejected by strict structured output validation.
4. A corrected frontier request was terminated by the outer Claude Code Bash
   timeout while Codex was still retrying WebSocket transport. The durable
   request remained `WAITING`; reconciliation found no raw response and
   conservatively changed it to `PAUSED/transport_outcome_uncertain`.

The v0.14.0 ledger is cumulative. It intentionally had no refund operation and
no redelivery path for PAUSED requests, so all four reservations remained
counted.

## Root causes

- Environment and schema checks happened after budget reservation.
- The policy did not freeze a verified provider/transport route.
- Codex CLI's default WebSocket retries could exceed the outer host timeout
  even though the HTTPS fallback was healthy.
- Transport output was copied only after subprocess completion, leaving little
  evidence when the host terminated the controller.
- Runbook language did not clearly distinguish a cumulative budget from
  reusable concurrency slots.
- The runbook budgeted request bytes, but Codex transport usage also includes
  base instructions, available skills/tools, and repeated cached prefixes.

## Corrective controls

v0.14.1:

- performs executable, login, strict-schema, and known model/transport
  preflight before reservation;
- defaults to an authenticated HTTPS-only ChatGPT provider overlay;
- passes `--skip-git-repo-check` while keeping Codex read-only;
- streams JSON events and stderr directly to durable files;
- disables optional Codex plugins/apps/search/multi-agent surfaces and uses a
  measured 150k-per-call conservative input reservation for the current local
  CLI, while acknowledging that user skills remain discoverable on 0.144.6;
- preserves the charge for any send whose backend outcome is uncertain; and
- reconciles crashes around the ledger/status boundary with immutable release
  intents and receipts when transport is provably unstarted; and
- documents that uncertain-send retries need a new immutable request and
  reservation.

There is deliberately no retroactive ledger rewrite. Existing exhausted plans
must be restarted with a new frozen policy after upgrading.

## Operator diagnosis

Inspect, in order:

1. `state/frontier/requests/<request-id>/preflight.json` or
   `preflight-failure.json`;
2. `status.json` and `state/frontier/events.jsonl`;
3. `transport.events.jsonl` and `transport.stderr`;
4. `budget-releases/*.intent.json`, its matching receipt, and
   `state/frontier/budget.json`; and
5. the exact outer-host exit code and timeout.

Do not summarize all failures as “network timeout” when durable transport or
preflight evidence identifies a deterministic rejection.
