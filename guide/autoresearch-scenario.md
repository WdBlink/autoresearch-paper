# /autoresearch:scenario — The Scenario Explorer

Autonomous scenario exploration engine. Takes a seed scenario and systematically generates situations across 12 dimensions — discovering edge cases, failure modes, security threats, and user journey variations that manual analysis consistently misses. Default: 20 iterations.

---

## How It Works

```
Seed analysis → Decompose into 12 dimensions → Generate ONE situation per iteration
     → Classify (dimension + severity) → Expand with context → Log → Repeat
```

1. **Seed analysis** — parse scenario for actors, actions, systems, constraints
2. **Dimension selection** — pick the least-explored dimension (balanced coverage)
3. **Situation generation** — one concrete situation within that dimension
4. **Classification** — tag with dimension, severity, domain priority
5. **Expansion** — add preconditions, expected outcome, failure signals, mitigations
6. **Log** — append to `scenario-results.md`
7. **Repeat** — until `Iterations` count is reached

**Saturation detection:** when 3 consecutive iterations yield only low-severity variations within already-covered dimensions, Claude reports saturation and offers to stop early or shift focus.

---

## The 12 Exploration Dimensions

| # | Dimension | What It Explores |
|---|-----------|-----------------|
| 1 | **Happy path** | Normal successful flows with expected inputs |
| 2 | **Error** | Expected failure modes — timeout, validation failure, 404 |
| 3 | **Edge case** | Boundary conditions: empty input, max values, exact limits |
| 4 | **Abuse** | Malicious usage — injection, spoofing, replay attacks |
| 5 | **Scale** | High volume — 10k concurrent users, 5GB uploads, DB at capacity |
| 6 | **Concurrent** | Race conditions, parallel access, double-submit |
| 7 | **Temporal** | Token expiry mid-flow, DST transitions, retry after delay |
| 8 | **Data variation** | Different formats, encodings, locales, null values |
| 9 | **Permission** | Unauthorized access, privilege escalation, scope mismatch |
| 10 | **Integration** | Payment gateway timeout, OAuth provider down, webhook failure |
| 11 | **Recovery** | Crash recovery, retry logic, idempotency, partial rollback |
| 12 | **State transition** | Invalid transitions, re-entry, concurrent state changes |

---

## All Flags

| Flag | Purpose |
|------|---------|
| `Iterations: N` | Override default of 20 |
| `--domain <type>` | `software`, `product`, `business`, `security`, `marketing` |
| `--depth <level>` | `shallow` (10), `standard` (20), `deep` (50+) |
| `--scope <glob>` | Focus scenario generation on specific files |
| `--format <type>` | `use-cases`, `user-stories`, `test-scenarios`, `threat-scenarios` |
| `--focus <area>` | Weight sampling: `edge-cases`, `failures`, `security`, `scale` |
| `--evals` | Analyze scenario-results after completion |
| `--chain <targets>` | Chain to next command(s) after completion |

---

## Depth Presets

| Preset | Iterations | Best For |
|--------|-----------|---------|
| `shallow` | 10 | Quick scan before a PR |
| `standard` | 20 | Most features (default) |
| `deep` | 50+ | Critical paths, security audits, launch prep |

---

## Output Formats

| Format | Best For |
|--------|---------|
| `use-cases` | Feature design, product planning |
| `user-stories` | Agile backlogs, sprint planning |
| `test-scenarios` | QA, automated test writing |
| `threat-scenarios` | Security audits, threat modeling |

---

## Examples

### Interactive (no args)

```
/autoresearch:scenario
```

### Checkout flow (software, bounded)

```
/autoresearch:scenario
Scenario: User completes checkout with multiple payment methods
Domain: software
Iterations: 20
```

### Quick edge case scan

```
/autoresearch:scenario --depth shallow --focus edge-cases
Scenario: File upload feature
```

### Security-focused OAuth

```
/autoresearch:scenario --domain security
Scenario: OAuth2 login flow with third-party providers
Iterations: 20
```

### Test scenarios for an API

```
/autoresearch:scenario --format test-scenarios --domain software
Scenario: REST API pagination with filtering and sorting
Iterations: 20
```

### Deep payment processing

```
/autoresearch:scenario --domain software --depth deep --format test-scenarios
Scenario: User processes a refund for a partially-shipped order
Iterations: 35
```

### Business domain — expense reports

```
/autoresearch:scenario --domain business --depth deep
Scenario: Employee submits expense report for multi-currency travel
Iterations: 30
```

### Marketing — newsletter signup

```
/autoresearch:scenario --domain marketing --format use-cases
Scenario: Newsletter signup with lead magnet delivery
Iterations: 20
```

---

## Example Output Block

```markdown
## Scenario #12 — Concurrent checkout race condition
**Dimension:** Concurrent
**Severity:** High
**Domain:** software

**Preconditions:**
- Two sessions share the same cart ID
- Inventory count is exactly 1 for the item

**Situation:**
Both sessions click "Place Order" within 50ms of each other.

**Expected Outcome:**
One order succeeds; the other receives a 409 Conflict.

**Failure Signal:**
Two orders created for the same inventory unit; oversell occurs.

**Mitigations:**
- Optimistic locking on inventory row
- Idempotency key on order creation endpoint
```

---

## Chain Patterns

### scenario → debug

```
/autoresearch:scenario --domain software --focus edge-cases
Scenario: User resets password with expired token
Iterations: 15

/autoresearch:debug --scope src/auth/**
Symptom: edge cases from scenario exploration
```

### scenario → debug → fix

```
/autoresearch:scenario --domain software
Scenario: User uploads files through drag-and-drop interface
Iterations: 20

/autoresearch:debug --scope src/uploads/**
Iterations: 15

/autoresearch:fix --from-debug
Guard: npm test
Iterations: 20
```

### predict → scenario

```
/autoresearch:predict --chain scenario,debug,fix
Scope: src/checkout/**
Goal: Ensure checkout handles all edge cases before launch
```

---

## Tips

- **Start shallow, go deep on what matters.** Run `--depth shallow` first, then re-run `--depth deep --focus` on the highest-severity dimensions.
- **Use `--domain security`** for anything with auth, money, or PII. Abuse and permission dimensions are weighted higher.
- **`--scope` grounds scenarios in your actual code.** When scoped, Claude reads those files to produce situations that could realistically occur in your specific implementation.
- **Scenario output feeds naturally into debug.** Copy the highest-severity situations into the `Symptom:` field of `/autoresearch:debug`.

---

## Related Guides

- [/autoresearch:debug](autoresearch-debug.md) — hunt bugs that scenarios surface
- [/autoresearch:predict](autoresearch-predict.md) — expert risk areas seed better scenarios
- [scenario/](scenario/) — real-world scenario walkthroughs
