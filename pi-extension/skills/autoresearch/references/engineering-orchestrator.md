## Orchestrator

Use explicitly for an engineering subtask with a mechanical completion predicate. The research workflow remains the main entry. Classifies the goal into a **Goal archetype** — see `references/orchestrator-routing.md` for the archetype table and router decision table.

Resolve every `scripts/...` path below relative to this installed skill directory, never relative to the caller's working directory.

For performance, latency, throughput, runtime, CPU, memory, allocations, binary
size, power, energy, bandwidth, or compute-cost goals, read
`references/behavior-preserving-optimization.md`. The working metric ranks
candidates; independent behavior evidence decides whether a candidate survives.

**Two modes based on archetype:**
- **Orchestration loop** — predicate-bearing archetypes (ship-ready, optimize-metric, fix-broken, harden, build-feature, explore). Goal has a mechanical Success predicate; the loop runs until that predicate is met.
- **Single-pass dispatch** — subjective/terminal archetypes (document, what-to-build, decide-design). Routes once to the fitting subcommand (learn / improve / reason), lets it self-terminate, then reports. No loop, no Plateau, no ship gate.

### Orchestration Loop Steps

Backed by `scripts/orchestrate.sh` (deterministic seam — all routing logic lives there). Subcommands exposed: `classify`, `next-hop`, `units`, `plateau`, `screen-cmd`, `verdict`, `validate-state`, `screen-state-predicate`.

1. **Classify** — `scripts/orchestrate.sh classify "<goal>"` → archetype label + mode.
2. **Derive predicate** — reuse `plan` logic to produce a concrete Success predicate: exact shell command + expected output. For `optimize-metric`, run the full plan/wizard derivation internally.
3. **Confirm** — ONE `ctx.ui` showing: archetype, mode, concrete predicate (command + expected output), terminal choice (stop-at-verified vs proceed-to-ship). Misclassifications are caught here, not mid-run.
4. **Round-0 dry-run** — prove the predicate command runs and returns a value; safety-screen every derived command via `screen-cmd`; print projected cycle budget. Stop here if `--dry-run`.
5. **Loop** until predicate satisfied:
   a. Assess state via cheap signals (last `handoff.json`, regression verdict, error count) + affected-test verify.
   b. `scripts/orchestrate.sh next-hop orchestrator-state.json` → next subcommand.
   c. Run subcommand via Subcommand routing (its own bounded inner loop).
   d. Record per-hop outcome ∈ {progressed, no-op, failed, blocked}.
   e. Fold hop's `handoff.json` into `orchestrator-state.json`.
   f. `scripts/orchestrate.sh units` → recompute **Units remaining** and append the number or `unknown` to the state's `units_remaining` array.
6. **Stop conditions** (checked after each hop):
   - Predicate met → ship gate (only if ship is in the pipeline) else `CONVERGED`.
   - Cycles > ceiling (default 50, override `--max-cycles N`) → stop + report `CEILING`. Checked first: a reached ceiling is never extended by fork rounds.
   - `scripts/orchestrate.sh plateau orchestrator-state.json` → exit 0 (flat): unless `--no-fork` or `fork_rounds_since_progress` is already 2, run one fork-and-flush round from the incumbent (`references/fork-and-flush.md`), add 1 to `fork_rounds_since_progress`, and continue; otherwise stop + report `PLATEAU`. Exit 1: continue. Exit 3: stop + report `BLOCKED`.
   - Hop outcome `blocked`/`failed` with no alternative route → checkpoint + stop + report `BLOCKED`.

### Orchestrator State

`orchestrator-state.json` — orchestrator-owned, additive. Tracks: goal, archetype, predicate, terminal-choice, `units_remaining` history, cycle count, per-hop pipeline log with outcomes, current incumbent, `fork_rounds_since_progress` (reset to 0 whenever units improve). Each hop's `handoff.json` is unchanged (single-hop bridge); the orchestrator reads it and folds it in. Two clearly-owned state objects, no overlap.

### Orchestrator Safety Invariants

- **Never auto-approve ship/deploy/push.** The orchestrator never passes `--auto` to `ship`; deploy always requires explicit user approval.
- **Data-migration behind anchored DB-URL allowlist.** Reuses regression's allowlist — host must be `localhost`/`127.0.0.1`/container hostname, or database name carries `_test`/`_ci` suffix. Bare substring match does not qualify. Anything else refused.
- **screen-cmd on every derived command** — run before the loop starts AND on every command read from a persisted state file on resume. Persisted commands are never trusted; resume re-screens the pinned predicate via `screen-state-predicate` and refuses on `refuse`.
- **No un-screened commands mid-loop.** The autonomous loop cannot introduce new shell commands that bypass `screen-cmd`.
- **Predicate pinned, not re-derived.** Round-0 writes the derived Success predicate verbatim into `orchestrator-state.json`; every cycle and every resume reuses that exact string so "done" is reproducible across runs.
- **Validate the ledger before routing.** `validate-state` gates `orchestrator-state.json` (required fields + coarse types); a malformed ledger is not trusted to route from.
- **Independent verify before convergence.** High-impact changes accepted on the working signal set `pending_verify`; `next-hop` routes to a `verify` hop (held-out / adversarial check) before `DONE` or ship. The verify hop never auto-approves ship.
- **Unknown-units cycles excluded from Plateau counter.** A cycle where `units` returns `unknown` (e.g. runner crash) is not counted as zero-progress; repeated `unknown` routes to `BLOCKED`.
