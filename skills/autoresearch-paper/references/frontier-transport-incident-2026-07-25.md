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

## v0.16 field follow-up

The Fixed-Win Visual Guidance field run later exposed three different classes
that must not be collapsed into this transport incident:

- a structurally valid negative audit is usable advisory evidence, even when
  it contains critical findings; only an `accept` with unresolved blockers or
  critical findings is semantically inconsistent;
- model-authored `usage: {0,0}` inside the response is never authoritative,
  while an observed terminal transport event of `0/0` is conservatively
  charged at the complete frozen reservation; and
- an initial staged plan must use CP-01 `approve_execution`. `STAGE-REVIEW` is
  terminal-only and persists through `record-strong-stage-review`, not through
  a newly synthesized durable context capsule.

The field report claimed 12 calls, 10 blocks, two accepts, and two transport
faults. Artifact-level re-audit corrected that ledger to 14 reservations,
eight final canonical blocks, one final canonical accept, and five transport
faults, with one `response_invalid` that overlaps the canonical accept. The
purported second accept was only an early `agent_message` from a transport
whose final durable response was `block`; it is not a second accepted result.
These are incident counts, not a controlled acceptance profile.

In the final reported round, the response object's model-authored usage was
`0/0`, but the canonical Codex transport event recorded `74370` input and
`2740` output tokens. That input exceeded the request's frozen `18000`
reservation, so the controller was
correct to refuse application and keep the launched charge. The defect was the
generic `response_invalid` classification and an unrealistic preflight
reservation—not a refundable zero-cost response. The same run also attempted
`STAGE-REVIEW` while the stage was still initial/contracted; that route must be
CP-01 first, regardless of the content of the supplied evidence bundle.

v0.16.1 also adds signed positive capacity for future request IDs. This is not
a refund mechanism: the grant binds current policy, stage/envelope, and all
three ledgers, then rolls them forward through an exact-once journal. Existing
launched charges and historical field ledgers are not rewritten.
