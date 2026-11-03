# /autoresearch:reason — Adversarial Refinement

Separate isolated agents generate, attack, synthesize, and judge competing versions of any artifact until the best version emerges through adversarial pressure. Default: 8 iterations (rounds). Loads `references/reason-judge-protocol.md` for convergence and oscillation rules.

---

## The Problem

Standard LLM refinement loops collapse to sycophancy — one agent refining its own output is elaborate self-editing. The result sounds better but isn't better. For subjective domains with no objective metric (architecture decisions, product strategy, content, legal arguments), single-model refinement systematically fails.

---

## How It Works — 8 Phases Per Round

```
Phase 1: Setup          Parse task, domain, mode; validate config
Phase 2: Generate-A     Author-A produces first candidate (task only — cold start)
Phase 3: Critic         Fresh agent attacks A (minimum 3 weaknesses)
Phase 4: Generate-B     Author-B sees task + A + critique → produces B
Phase 5: Synthesize-AB  Synthesizer sees task + A + B only (NOT the critique)
Phase 6: Judge Panel    N blind judges, crypto-random labels, pick winner
Phase 7: Convergence    N consecutive majority wins → converge; oscillation detection
Phase 8: Handoff        Write lineage files, trigger --chain if set
```

**Context isolation invariant:** every agent is cold-start, no shared session. The critic never wrote A. The synthesizer never saw the critique. The judges see X/Y/Z — not A/B/AB — so they cannot anchor on authorship.

**The blind judge panel IS the subjective fitness function** — the equivalent of `val_bpb` for subjective domains.

---

## All Flags

| Flag | Purpose | Default |
|------|---------|---------|
| `Iterations: N` | Run exactly N rounds | 8 |
| `Iterations: unlimited` | Run until convergence | — |
| `--judges N` | Judge count (3–7, must be odd) | 3 |
| `--convergence N` | Consecutive wins to declare convergence | 3 |
| `--mode` | `convergent`, `creative`, `debate` | `convergent` |
| `--domain` | `software`, `product`, `business`, `security`, `research`, `content` | Asked interactively |
| `--chain <targets>` | Chain to downstream tools after convergence | none |
| `--judge-personas` | Override default judge personas | Domain-default |
| `--no-synthesis` | Skip AB phase; evaluate A vs B only | false |

**Mode behavior:**
- `convergent` — runs until `--convergence N` consecutive wins or iterations limit
- `creative` — never auto-stops; requires `--iterations` or runs forever
- `debate` — implies `--no-synthesis`; best for binary choices (A vs B)

---

## Examples

### Architecture decision (bounded)

```
/autoresearch:reason
Task: Should we use event sourcing for our order management system?
Domain: software
Iterations: 8
```

### Product pitch refinement

```
/autoresearch:reason --judges 5 --iterations 10
Task: Write a compelling Series A pitch for our AI analytics platform
Domain: business
```

### Creative mode — explore alternatives

```
/autoresearch:reason --mode creative --iterations 6
Task: Design the authentication UX for a multi-tenant SaaS platform
Domain: product
```

### Pure A vs B (debate mode)

```
/autoresearch:reason --mode debate --judges 5
Task: Microservices vs monolith for a 5-person startup
Domain: software
```

### Chain to plan + fix after convergence

```
/autoresearch:reason --chain plan,fix
Task: Design the caching strategy for high-traffic API endpoints
Domain: software
Iterations: 5
```

### Content refinement

```
/autoresearch:reason --domain content --iterations 8
Task: Write a landing page headline for a developer tool targeting CTOs
```

### Security approach debate

```
/autoresearch:reason --domain security --chain security
Task: Should we implement zero-trust or traditional perimeter security?
Iterations: 5
```

---

## Convergence and Oscillation

**Convergence:** `--convergence N` consecutive rounds where the incumbent wins majority → stop, declare converged.

**Oscillation detection:** if the incumbent label changes 5+ times, the task has genuinely competing tradeoffs. reason forces a stop, reports the oscillation, and recommends specifying which tradeoff matters more before re-running. Oscillation is information — not a failure.

---

## Chain Targets

| Chain | What Happens |
|-------|-------------|
| `--chain debug` | Converged design → debug validates it empirically |
| `--chain plan` | Converged proposal → plan wizard uses it as starting point |
| `--chain fix` | Converged code proposal → fix implements it |
| `--chain security` | Critique themes seed targeted security audit |
| `--chain scenario` | Converged version → edge case exploration |
| `--chain predict` | Converged design → 5 expert personas stress-test it |
| `--chain ship` | Converged content → ship as artifact |
| `--chain learn` | Full iteration lineage → ADR documentation |

**`--chain predict,scenario`** — adversarial refinement → multi-persona stress test → edge case exploration. Strongest validation path for subjective design decisions.

**`--chain plan,fix`** — converged design proposal → structured implementation plan → code execution.

---

## Output Structure

```
reason/{YYMMDD}-{HHMM}-{slug}/
├── overview.md             Task, domain, convergence status, oscillation report
├── lineage.md              Round-by-round trace: who won, why, what critic said
├── candidates.md           Final round candidates in full: A, B, AB
├── judge-transcripts.md    Decoded judge reasoning with labels resolved
├── reason-results.tsv      Per-round log: winner_type, judge_votes, convergence_count
├── reason-lineage.jsonl    Machine-readable full round history
└── handoff.json            Chain handoff schema for downstream tools
```

`lineage.md` is the documentation artifact — it shows WHY the final version won. For architecture decisions, it is the ADR. For content, the editorial record. For strategy, the decision log.

---

## When to Use vs. Going Direct

| Use reason when... | Skip reason when... |
|---|---|
| No objective metric exists | You have a mechanical metric → use `/autoresearch` |
| Multiple valid approaches compete | There is one obviously correct answer |
| Decision needs documented rationale | You just need something executed |
| Quality is subjective / audience-dependent | Bug fixing → use `/autoresearch:debug` |
| Architecture, design, or strategy decisions | First draft generation |

**Rule of thumb:** if you would call the result "good" or "bad" based on judgment rather than measurement, use reason.

---

## Anti-Patterns

| Don't | Why |
|---|---|
| Skip the critic | Without adversarial pressure, versions drift without improving |
| Use even judge counts | Even N can tie — prefer 3, 5, 7 |
| Set `--convergence 1` | Single win doesn't indicate stable quality |
| Run creative mode without `--iterations` | Never auto-stops — runs indefinitely |
| Trust reason over empirical tests | reason produces better arguments, not necessarily better code |
| Chain without reviewing candidates.md | Bad converged input produces bad downstream output |
