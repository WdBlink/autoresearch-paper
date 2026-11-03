# /autoresearch:debug — The Bug Hunter

Scientific method meets the autoresearch loop. `/autoresearch:debug` iteratively hunts ALL bugs — forming falsifiable hypotheses, running one experiment per iteration, logging confirmed and disproven results alike, then surfacing the next lead. Default: 15 iterations. Every finding ships with code evidence (file:line + reproduction steps).

---

## How It Works — 7 Phases Per Iteration

```
SETUP (once):
  Run tests / lint / typecheck — collect baseline failures
  Map the error surface and trace call chains
  Build initial hypothesis queue

LOOP (15 iterations by default):
  1. GATHER      Collect symptoms: tests, lint, typecheck
  2. RECON       Map error surface, trace call chains
  3. HYPOTHESIZE Form one falsifiable, testable hypothesis
  4. TEST        Run ONE experiment (6 techniques below)
  5. CLASSIFY    Confirmed / Disproven / Inconclusive / Lead
  6. LOG         Record to debug-results.tsv with severity
  7. REPEAT      Next hypothesis or follow the new lead
```

---

## 6 Investigation Techniques

| Technique | How It Works |
|-----------|-------------|
| **Binary Search** | Divide suspect code in half, isolate which half contains the bug |
| **Differential Debugging** | Compare working vs broken versions, branches, or configs |
| **Minimal Reproduction** | Strip to the smallest case that still reproduces the failure |
| **Trace Execution** | Follow actual code path end-to-end, tracking state mutations |
| **Pattern Search** | Grep for known-bad patterns: missing awaits, unchecked nulls, SQL concat |
| **Working Backwards** | Start at the failure point, walk up the call stack |

---

## All Flags

| Flag | Purpose |
|------|---------|
| `Iterations: N` | Override default of 15 (use `unlimited` for deep hunts) |
| `--fix` | After hunting, auto-hand off to `/autoresearch:fix` |
| `--scope <glob>` | Limit investigation to specific files |
| `--symptom "<text>"` | Pre-fill the symptom to skip the interactive prompt |
| `--severity <level>` | Minimum severity to report: `critical`, `high`, `medium`, `low` |
| `--evals` | Analyze debug-results.tsv after the hunt |
| `--chain <targets>` | Chain to next command(s) after completion |

---

## Severity Levels

| Level | Definition |
|-------|-----------|
| **Critical** | Data loss, auth bypass, production outage, corrupted state |
| **High** | Functional breakage: silent failures, wrong data, crashes on valid input |
| **Medium** | Edge case errors, degraded performance, missing validation |
| **Low** | Code smell, minor inconsistency, logged error with graceful recovery |

---

## Examples

### Interactive — Claude asks what's broken

```
/autoresearch:debug
```

### Scoped hunt with symptom

```
/autoresearch:debug
Scope: src/api/**/*.ts
Symptom: API returns 500 on POST /users
Iterations: 15
```

### Debug then auto-fix

```
/autoresearch:debug --fix
Iterations: 20
```

### Production incident — high severity only

```
/autoresearch:debug --fix --severity high
Scope: src/**/*.ts
Symptom: Payment confirmations silently failing — emails never sent
Iterations: 30
```

### Memory leak

```
/autoresearch:debug
Scope: src/**/*.ts
Symptom: Node process memory grows 50MB/hour under normal load
Iterations: 25
```

### Performance regression

```
/autoresearch:debug
Scope: src/models/**/*.ts, src/api/**/*.ts
Symptom: Dashboard page went from 200ms to 4s after last deploy
Iterations: 20
```

### Auth escalation bug

```
/autoresearch:debug
Scope: src/auth/**/*.ts, src/middleware/**/*.ts
Symptom: Regular users can access /admin endpoints
Iterations: 15
```

---

## Example Session Output

```
[Phase 1] Gathering symptoms...
  Tests: 3 failures | Lint: 0 errors | Types: 2 errors

[Iteration 1] Hypothesis: "db.insert() missing await at db.ts:88"
  CONFIRMED HIGH — silent write failure on error path

[Iteration 2] Hypothesis: "JWT alg not validated at auth.ts:42"
  CONFIRMED CRITICAL — algorithm confusion vulnerability

[Iteration 3] Hypothesis: "Rate limiting missing on /api/auth/login"
  CONFIRMED MEDIUM — brute force possible

[Iteration 4] Hypothesis: "SQL injection via string concat in search"
  DISPROVEN — parameterized queries used correctly

[Iteration 5] Hypothesis: "Type error from null return in getUserById"
  CONFIRMED HIGH — crashes when user not found

=== Debug Complete (15/15 iterations) ===
Bugs found: 7 (1 Critical, 3 High, 2 Medium, 1 Low)
Hypotheses tested: 15 (7 confirmed, 6 disproven, 2 inconclusive)
```

---

## Output Structure

```
debug/{YYMMDD}-{HHMM}-{slug}/
├── findings.md          Confirmed bugs with code evidence + severity
├── eliminated.md        Disproven hypotheses with reasoning
├── debug-results.tsv    Machine-readable log of all iterations
└── summary.md           Totals, coverage, next steps
```

`findings.md` format per bug:

```markdown
### [HIGH] Missing await on db.insert()
- **Location:** src/db/users.ts:88
- **Symptom:** Silent write failure — returns success, data never saved
- **Reproduction:** Call POST /users with valid payload while DB is slow
- **Code Evidence:** db.insert(userData);  // should be: await db.insert(userData)
- **Fix:** Add await; wrap in try/catch
```

`eliminated.md` is not a failure log — each disproven hypothesis narrows the search space and prevents re-investigation of the same dead ends.

---

## Chain Patterns

### debug → fix

```
/autoresearch:debug
Iterations: 20

/autoresearch:fix --from-debug
Guard: npm test
Iterations: 30

# Shortcut:
/autoresearch:debug --fix
Iterations: 20
```

### predict → debug

```
/autoresearch:predict --chain debug
Scope: src/auth/**
Goal: Investigate intermittent 500 errors on POST /login
```

### debug → fix → ship

```
/autoresearch:debug --severity high
Iterations: 20

/autoresearch:fix --from-debug
Iterations: 30

/autoresearch:ship --auto
```

---

## Tips

- **Start broad, go narrow.** Let first iterations cast a wide net. Use `--scope` once the error surface is clear.
- **Symptom precision speeds convergence.** Specific symptom = targeted first hypothesis.
- **Use `--severity high` for production incidents.** Skip Medium/Low during active incidents.
- **Pair with predict for unfamiliar codebases.** Run `/autoresearch:predict` first to get expert hypotheses.
- **Let `--fix` handle repair.** Don't mix hunting and fixing manually — use the `--fix` flag.

---

## Related Guides

- [/autoresearch:fix](autoresearch-fix.md) — repair confirmed findings
- [/autoresearch:predict](autoresearch-predict.md) — expert hypotheses before hunting
- [/autoresearch:evals](autoresearch-evals.md) — analyze debug-results.tsv
