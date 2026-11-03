# /autoresearch:fix — The Error Crusher

Takes a broken state and iteratively repairs it. ONE fix per iteration. Atomic, committed, verified, and auto-reverted on failure. Default: 20 iterations. Stops automatically when error count hits zero — even in unbounded mode.

---

## How It Works — 5 Steps Per Iteration

```
Step 1  DETECT      Auto-detect failures across all categories
                    Priority: build → tests → types → lint → warnings
Step 2  PRIORITIZE  Blockers first, then required, then polish
Step 3  FIX ONE     Atomic change — one file, one root cause, one commit
Step 4  COMMIT → VERIFY → GUARD
                    Keep if verify improves AND guard passes
                    Revert if verify regresses OR guard fails
Step 5  LOG         Kept changes accumulate; reverted changes go to blocked.md
```

**Auto-stop:** when all detectable errors reach zero, the loop exits cleanly.

---

## Priority Order

| Priority | Category | Examples |
|----------|----------|---------|
| 1 — Blocker | `build` | Compilation failure, missing import, syntax error |
| 2 — Required | `test` | Failing unit/integration tests |
| 2 — Required | `type` | TypeScript tsc errors, mypy, Rust type errors |
| 3 — Polish | `lint` | ESLint, pylint, clippy, go vet violations |
| 4 — Advisory | `warning` | Deprecation warnings, unused variables |

Fixing build errors first is deliberate — many type and test errors are cascade failures from a broken build.

---

## All Flags

| Flag | Purpose |
|------|---------|
| `Iterations: N` | Override default of 20 |
| `--target <command>` | Explicit verify command (overrides auto-detect) |
| `--guard <command>` | Safety command that must always pass |
| `--category <type>` | Only fix: `test`, `type`, `lint`, `build` |
| `--from-debug` | Read findings from latest debug session |
| `--evals` | Analyze fix-results.tsv after completion |
| `--chain <targets>` | Chain to next command(s) after completion |

---

## Anti-Patterns It Never Takes

- Never adds `@ts-ignore` or `eslint-disable` comments
- Never uses `any` to bypass type errors
- Never deletes failing tests to make the suite pass
- Never marks tests as `.skip` or `.todo`
- Never uses empty `catch` blocks to swallow errors
- Never lowers strictness thresholds (tsconfig, lint rules)

If a fix cannot be made cleanly, the iteration reverts and logs to `blocked.md` for manual review.

---

## Examples

### Auto-detect and fix everything

```
/autoresearch:fix
```

### Fix only test failures

```
/autoresearch:fix --category test
Iterations: 20
```

### Fix only type errors

```
/autoresearch:fix --category type
Iterations: 25
```

### Fix only lint errors

```
/autoresearch:fix --category lint
Iterations: 15
```

### Fix from debug findings

```
/autoresearch:debug
Scope: src/**/*.ts
Iterations: 15

/autoresearch:fix --from-debug
Guard: npm test
Iterations: 30

# Shortcut:
/autoresearch:debug --fix
```

### Fix with guard

```
/autoresearch:fix
Target: tsc --noEmit
Guard: npm test
```

### Python — mypy strict

```
/autoresearch:fix --target "mypy app/ --strict"
Guard: pytest
Iterations: 25
```

### Go — vet + staticcheck

```
/autoresearch:fix --target "go vet ./... && staticcheck ./..."
Guard: go test ./...
Iterations: 15
```

### Rust — clippy

```
/autoresearch:fix --target "cargo clippy -- -D warnings"
Guard: cargo test
Iterations: 20
```

### CI/CD pipeline failures

```
/autoresearch:fix
Target: gh run view --log-failed
Scope: .github/workflows/*.yml
```

---

## Example Session Output

```
[Phase 1] Detected: 47 test failures, 12 type errors, 3 lint errors
[Phase 2] Priority: types first (may cascade-fix test failures)

[Iteration 1] Fix: auth.ts:42 — add return type annotation
  delta: -2 errors | guard: pass | STATUS: KEEP

[Iteration 2] Fix: db.ts:15 — handle nullable column
  delta: -1 error | guard: pass | STATUS: KEEP

[Iteration 3] Fix: api.test.ts — wrong approach
  delta: 0 errors | guard: - | STATUS: DISCARD (reverted)

=== Fix Complete (23 iterations) ===
Baseline: 62 errors → Final: 3 errors (-95.2%)
Keeps: 19 | Discards: 3 | Reworks: 1
Blocked: 1 (circular dependency — see blocked.md)
```

---

## Output Structure

```
fix/{YYMMDD}-{HHMM}-{slug}/
├── fix-results.tsv     Iteration log: fix, delta, status (KEEP/DISCARD)
├── summary.md          Baseline vs final error counts, stats
└── blocked.md          Fixes that couldn't be made cleanly — manual review
```

`blocked.md` entries are typically circular dependencies, missing type definitions requiring a dependency install, or architectural decisions. Route them to `/autoresearch:debug` for investigation.

---

## Chain Patterns

### security → fix → re-audit

```
/autoresearch:security
Iterations: 15

/autoresearch:fix --from-debug
Guard: npm test
Iterations: 20

/autoresearch:security --diff
Iterations: 10

/autoresearch:ship --type code-release
```

### fix → ship

```
/autoresearch:fix
Guard: npm test
Iterations: 30

/autoresearch:ship --type code-pr --auto
```

---

## Tips

- **Start unbounded for unknown codebases.** The fixer stops at zero errors automatically. Add `--guard` to prevent regressions.
- **Use `--category` when you have a deadline.** If you need tests green before a PR, `--category test` ignores type noise.
- **Fix build errors in isolation first.** Many test and type errors vanish once compilation succeeds.
- **Guard is your safety net.** Always set `Guard: npm test` when fixing types or lint.
- **Check blocked.md after each run.** Items there usually point to deeper architectural issues.

---

## Related Guides

- [/autoresearch:debug](autoresearch-debug.md) — find bugs before fixing
- [/autoresearch:ship](autoresearch-ship.md) — ship after fixing
- [/autoresearch:evals](autoresearch-evals.md) — analyze fix-results.tsv
