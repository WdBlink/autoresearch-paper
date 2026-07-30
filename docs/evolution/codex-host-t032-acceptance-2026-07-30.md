# Codex Host T032 field acceptance — 2026-07-30

## Outcome

The bounded Codex Host migration gate passed on a fresh installed Codex task
using autoresearch-paper v0.19.4. v0.20.0 therefore changes the product Host
wording to **Codex Host switched** (`Codex Host 已切换`).

The accepted lineage was `fwvg-conf-2026-039`, plan identity
`plan_1c7840feace5ce9a39f81682`. Its immutable field report has SHA-256
`5c12600201f70d11d2aa841c81eac42f5853cf60a6ea88ee9a6f236655e9096a`.
The post-freeze verifier checked all 70 cited evidence objects and found zero
path or digest mismatches.

## What passed

1. The installed closed brief was validated and atomically prepared.
2. Authenticated activation, evaluator admission, and Codex Host bootstrap
   reached canonical `ACTIVATED`, `ADMITTED`, and `READY` receipts.
3. A real `gpt-5.6-sol`/`ultra` CP-01 review returned `accept`; the controller
   validated and applied the advisory response before Stage 1 dispatch.
4. The MiniMax M3 Worker completed Stage 1 in a newly bound persistent Claude
   Code session with two real L2 heartbeats. The observation validator passed,
   the decision was `accept`, and the compile journal recorded source state
   `RECORDED`.
5. Only after Stage 1 termination, the controller froze the Stage 2 envelope,
   raw preflight inputs, and first Worker contract. A fresh real
   `gpt-5.6-sol`/`ultra` strong review accepted those exact bytes.
6. `advance-staged-research` compiled the one authorized continuation and
   resumed the exact Stage 1 Claude session as turn 2. The terminal receipt
   records `invocation_mode: resumed`, two real L2 heartbeats, and a completed
   transport turn.
7. The read-only Dashboard returned a plan039 canonical snapshot; L0 and L1
   schedulers were loaded and active, and the health-only assurance tick used
   zero model dispatches with no stale Worker.

## Evidence boundary

This acceptance proves the installed, bounded control lineage:

`closed brief → Codex CP-01 → Host READY → Stage 1 RECORDED → strongest review
→ automatic Stage 2 compilation → same-session Stage 2 Worker turn`

It does **not** prove Stage 2 scientific completion, method improvement, SOTA,
safety, paper completion, 24h or 7x24 stability, production readiness, or full
production cutover. Each future plan must still produce its own plan-bound
authorization, evaluator, frontier, Worker, heartbeat, report, and review
receipts. The absence of a transport-reported model/provider field is recorded
as unavailable; the Worker route is established by the frozen policy and
adapter identity, not by invented transport metadata.

## Preserved negative evidence

Plans 035 through 038 remain immutable and must not be rewritten:

- plan035 exposed Codex turn-start prompt overflow;
- plan036 exposed the reserved candidate artifact identity requirement;
- plan037 exposed canonical enriched-preflight report binding;
- plan038 exposed the response deadline/timestamp boundary.

Those failures drove the v0.19.x fixes and remain part of the audit history.
