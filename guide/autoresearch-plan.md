# /autoresearch:plan — The Setup Wizard

Converts a plain-language goal into a validated, ready-to-execute autoresearch configuration. One-shot — no loop, no iterations.

---

## The Problem It Solves

Running `/autoresearch` requires three inputs: **Scope**, **Metric**, and **Verify**. Getting these wrong wastes entire runs:

- **Scope too wide** — fixes wrong files, slow iteration
- **Metric not mechanical** — loop stalls, Claude can't measure progress
- **Verify command broken** — every iteration fails
- **Direction wrong** — loop optimizes backward

The plan wizard eliminates cold-start friction by scanning your codebase, suggesting sensible defaults, and dry-running the verify command before you commit to a run.

---

## How It Works — 7 Phases

```
Phase 1  Capture goal       Plain-language input
Phase 2  Scan codebase      Detect tooling: test runners, build tools, linters
Phase 3  Suggest scope      File globs → validate at least 1 file resolves
Phase 4  Suggest metric     Mechanical metric → validate it outputs a number
Phase 5  Determine direction Higher or lower is better?
Phase 6  Dry-run verify     Run the verify command on your current codebase
Phase 7  Present config     Ready-to-paste /autoresearch block + chain handoff
```

---

## Critical Gates

| Gate | Requirement |
|------|-------------|
| **Metric** | Must output a parseable number |
| **Verify** | Must exit 0 on dry run |
| **Scope** | Must resolve to at least 1 file |

If any gate fails, the wizard explains why and suggests a corrected command.

---

## Usage

```
# Interactive — Claude asks for your goal
/autoresearch:plan

# Inline goal
/autoresearch:plan Increase test coverage to 95%
/autoresearch:plan Make the API respond faster
/autoresearch:plan Reduce bundle size below 200KB
```

### Chain Handoff

```
/autoresearch:plan --chain autoresearch
```

After presenting the config, immediately launches the loop with the validated settings.

---

## Examples

### Test coverage

```
> /autoresearch:plan Increase test coverage to 95%

[Context]  Detected: Jest, TypeScript, 84 source files
[Scope]    src/**/*.ts, src/**/*.test.ts (84 + 31 files)
[Metric]   Coverage % from Jest (higher is better)
[Verify]   npx jest --coverage --silent 2>&1 | grep "All files" | awk '{print $4}'
[Dry run]  Exit 0 — Baseline: 72.3%

Ready-to-use:

  /autoresearch
  Goal: Increase test coverage to 95%
  Scope: src/**/*.ts, src/**/*.test.ts
  Metric: coverage % (higher is better)
  Verify: npx jest --coverage --silent 2>&1 | grep "All files" | awk '{print $4}'

Launch? → [Bounded: 25] [Unlimited] [Copy only]
```

### API latency

```
> /autoresearch:plan Make the API respond faster

[Context]  Detected: Node.js, Express, custom bench script
[Scope]    src/api/**/*.ts, src/services/**/*.ts (23 files)
[Metric]   p95 response time in ms (lower is better)
[Verify]   npm run bench:api | grep "p95"
[Dry run]  Exit 0 — Baseline: 187ms
```

### Bundle size

```
> /autoresearch:plan Reduce bundle size below 200KB

[Scope]    src/**/*.tsx, src/**/*.ts (127 files)
[Metric]   Bundle size in KB (lower is better)
[Verify]   npm run build 2>&1 | grep "First Load JS" | awk '{print $4}'
[Dry run]  Exit 0 — Baseline: 287KB
```

### Python coverage

```
> /autoresearch:plan Improve pytest coverage

[Context]  Detected: pytest, FastAPI, 56 source files
[Scope]    tests/**/*.py, app/**/*.py (56 + 22 files)
[Metric]   Coverage % from pytest (higher is better)
[Verify]   pytest --cov=app 2>&1 | grep "TOTAL" | awk '{print $4}'
[Dry run]  Exit 0 — Baseline: 68%
```

### Docker image size

```
> /autoresearch:plan Reduce Docker image size

[Scope]    Dockerfile, .dockerignore (2 files)
[Metric]   Image size in MB (lower is better)
[Verify]   docker build -t bench . -q 2>&1 && docker images bench --format "{{.Size}}" | sed 's/MB//'
[Dry run]  Exit 0 — Baseline: 487
```

---

## Config Output Format

```
=== Autoresearch Config ===

  /autoresearch
  Goal: Reduce bundle size below 200KB
  Scope: src/**/*.tsx, src/**/*.ts
  Metric: bundle size in KB (lower is better)
  Verify: npm run build 2>&1 | grep "First Load JS" | awk '{print $4}'
  Guard: npm test

Baseline: 287KB
Direction: lower is better
Dry run: passed

Launch? → [Bounded: 25] [Unlimited] [Copy only]
```

---

## Chain Patterns

### plan → loop

```
/autoresearch:plan
Goal: Reduce API response times

# Use the wizard's output:
/autoresearch
Iterations: 25
Goal: Reduce p95 API response time to under 100ms
Scope: src/api/**/*.ts
Metric: p95 latency in ms (lower is better)
Verify: npm run bench:api | grep "p95"
Guard: npm test
```

### plan → loop → ship

```
/autoresearch:plan --chain autoresearch
Goal: Reduce bundle size below 200KB
# After loop completes:
/autoresearch:ship --type code-pr --auto
```

---

## When to Use plan vs. Going Direct

| Situation | Use plan? |
|-----------|-----------|
| First time using autoresearch | Yes — learn the format |
| Unsure what metric to use | Yes — wizard suggests options |
| Want to validate before an overnight run | Yes — dry-runs first |
| New codebase, unknown tooling | Yes — detects stack automatically |
| You already know the exact config | No — go direct |

---

## FAQ

**Q: What if the dry run fails?**
The wizard explains the failure and suggests a corrected command. Common causes: command not installed, server not running, output format changed.

**Q: Does the wizard commit anything?**
No. Read-only — it scans and validates. Nothing changes until you launch the loop.

**Q: Can I add a Guard after the wizard completes?**
Yes. The wizard proposes a Guard based on detected tests. Accept, change, or omit it.
