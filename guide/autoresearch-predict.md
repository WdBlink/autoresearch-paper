# /autoresearch:predict — Multi-Persona Swarm Prediction

Five expert personas independently analyze your code, debate findings, and reach consensus — all before a single iteration runs. One-shot: no loop, no iterations.

Loads `references/predict-personas.md` for persona definitions and anti-herd detection rules.

---

## The Problem

Single-perspective serial analysis suffers from:

- **Cognitive anchoring** — the first plausible hypothesis crowds out better alternatives
- **Domain blindness** — a debugging lens misses security implications; a security lens misses performance
- **No adversarial pressure** — no one challenges the lead hypothesis until the loop proves it wrong
- **Cascade blindness** — 20 downstream symptoms look like 20 independent problems

The first hypothesis is usually wrong. Predict adds a deliberation layer that surfaces the right hypotheses before iterations begin.

---

## How It Works — 8 Phases

```
Phase 1: Setup          Parse scope, goal, depth; validate config
Phase 2: Reconnaissance Read code, build shared knowledge files
Phase 3: Persona Gen    Create expert personas with role + bias
Phase 4: Independent    Each persona analyzes alone — no cross-talk
Phase 5: Debate         1–3 rounds of structured cross-examination
Phase 6: Consensus      Voting + anti-herd detection + scoring
Phase 7: Report         Findings, hypothesis queue, overview
Phase 8: Handoff        Write handoff.json, trigger --chain if set
```

---

## The 5 Default Personas

| # | Persona | Focus | Bias |
|---|---------|-------|------|
| 1 | Architecture Reviewer | Scalability, coupling, tech debt, module boundaries | Conservative — skeptical of god objects |
| 2 | Security Analyst | OWASP Top 10, injection, auth failures, data exposure | Paranoid — trusts nothing from outside the trust boundary |
| 3 | Performance Engineer | Algorithmic complexity, N+1 queries, blocking I/O | Practical — prefers measurable evidence |
| 4 | Reliability Engineer | Error handling, race conditions, edge cases, observability | Pessimistic — assumes failure |
| 5 | Devil's Advocate | Challenges consensus, surfaces blind spots, non-code hypotheses | Contrarian — must challenge ≥50% of majority positions |

---

## All Flags

| Flag | Purpose | Default |
|------|---------|---------|
| `--scope <glob>` | Files to analyze | Asked interactively |
| `--goal <text>` | Focus area for all personas | Asked interactively |
| `--depth <level>` | `shallow`, `standard`, `deep` | `standard` |
| `--personas <N>` | Override persona count (3–8) | Depth-dependent |
| `--rounds <N>` | Override debate rounds (0–3) | Depth-dependent |
| `--adversarial` | Swap to red-team adversarial personas | Off |
| `--chain <targets>` | Chain to downstream command(s) | None |
| `--budget <dollars>` | Max cost cap | $1.00 |
| `--fail-on <severity>` | Exit non-zero for CI/CD gate | None |
| `--dry-run` | Show config + file count, then stop | Off |
| `--incremental` | Reuse existing knowledge files | Off |

---

## Depth Presets

| Preset | Personas | Debate Rounds | Best For |
|--------|----------|---------------|---------|
| `shallow` | 3 | 1 | Quick PR sanity check (~90 seconds) |
| `standard` | 5 | 2 | Most tasks — recommended default |
| `deep` | 8 | 3 | Major refactors, pre-deploy, security audits |

---

## Anti-Herd Detection

Groupthink fires when `flip_rate > 0.8` AND `entropy < 0.3` simultaneously. When triggered:

1. All minority findings are preserved in the report
2. `overview.md` is flagged with a groupthink warning
3. Predict suggests re-running with `--adversarial`

Minority findings are frequently right on non-obvious issues that majorities anchor away from.

---

## Adversarial Mode (`--adversarial`)

Replaces default personas with red-team configuration:

| # | Persona | Focus |
|---|---------|-------|
| 1 | Red Team Attacker | Exploitation paths, attack chains, auth bypass |
| 2 | Blue Team Defender | Detection gaps, monitoring, incident response readiness |
| 3 | Insider Threat | Data exfiltration, audit trail gaps, privilege abuse |
| 4 | Supply Chain Analyst | CVEs, compromised packages, build pipeline weaknesses |
| 5 | Judge | Evaluates adversarial claims, assigns exploitability scores |

---

## Examples

### Standard analysis with debug chain

```
/autoresearch:predict --chain debug
Scope: src/auth/**
Goal: Investigate intermittent 500 errors on POST /login
```

### Quick security scan (shallow)

```
/autoresearch:predict --depth shallow
Scope: src/api/**
Goal: Security vulnerabilities
```

### Deep architecture review

```
/autoresearch:predict --depth deep
Scope: src/**
Goal: Architecture review — evaluate splitting into microservices
```

### Pre-deployment security review (adversarial)

```
/autoresearch:predict --adversarial --chain security
Scope: src/auth/**, src/api/**, src/middleware/**
Goal: Pre-deployment security review
```

### Full pipeline (single command)

```
/autoresearch:predict --chain scenario,debug,fix,ship
Scope: src/**
Goal: Complete quality pipeline for v2.0 release
```

### CI/CD security gate

```yaml
- name: Run predict security gate
  run: |
    /autoresearch:predict \
      --scope "src/auth/**,src/api/**" \
      --goal "Security vulnerabilities" \
      --depth shallow \
      --budget 0.50 \
      --fail-on critical
```

---

## Chain Targets

| Chain | What Happens |
|-------|-------------|
| `--chain debug` | Ranked hypotheses → debug tests in priority order |
| `--chain security` | Security-type findings → targeted audit vectors |
| `--chain fix` | Root causes first → cascade-aware fix ordering |
| `--chain ship` | Findings classified as BLOCKER/WARNING/INFO → ship gate |
| `--chain scenario` | Confirmed findings → scenario seeds |
| `--chain scenario,debug,fix` | Quality pipeline for new features |
| `--chain scenario,debug,fix,ship` | Full lifecycle — zero context loss |

---

## Output Structure

```
predict/{YYMMDD}-{HHMM}-{slug}/
├── overview.md           Executive summary: scope, personas, findings, anti-herd status
├── findings.md           All findings ranked by priority score with evidence
├── hypothesis-queue.md   Ranked testable hypotheses — consumed by --chain tools
├── persona-debates.md    Full debate transcript per persona per round
├── predict-results.tsv   Iteration log
├── handoff.json          Machine-readable schema for downstream chain tools
├── codebase-analysis.md  Knowledge file: functions, routes, models
├── dependency-map.md     Knowledge file: import graph, call graph, data flows
└── component-clusters.md Knowledge file: logical clusters with risk areas
```

---

## When to Use vs. Going Direct

| Use predict when... | Skip predict when... |
|---|---|
| Intermittent failures — multiple plausible causes | Stack trace points to exact line |
| Post-upgrade cascading errors | 3 independent lint errors |
| Complex API with auth and payments | Single failing unit test |
| Architecture decision needed | Profiling an already-identified bottleneck |
| Pre-deployment security review | Quick one-file fix |

**Rule of thumb:** if you would naturally call two or more specialists about the same problem, use predict.

---

## Related Guides

- [/autoresearch:debug](autoresearch-debug.md) — primary chain target
- [/autoresearch:security](autoresearch-security.md) — empirical validation after adversarial predict
- [/autoresearch:reason](autoresearch-reason.md) — adversarial refinement of subjective decisions
