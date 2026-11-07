# /autoresearch:evals — Results Analyzer

One-shot analysis of any `*-results.tsv` file produced by an autoresearch loop. Detects trends, plateaus, velocity changes, and anomalies. Dynamically detects TSV columns — works with all loop commands and is backward-compatible with v2.0.x TSV format.

---

## What It Does

- Parses `*-results.tsv` from any loop command (autoresearch, debug, fix, security, scenario, reason)
- Detects convergence trends, plateau regions, and velocity drops
- Surfaces the highest-impact iterations (biggest positive deltas)
- Flags anomalies: consecutive discards, guard failures, oscillation
- Outputs a structured report in `text`, `json`, or `md` format
- Provides a go/no-go recommendation for continuing or stopping the loop

---

## Usage

```
# Analyze the most recent results TSV (auto-detected)
/autoresearch:evals

# Analyze a specific file
/autoresearch:evals --file autoresearch-results.tsv

# Analyze with JSON output (for CI/CD parsing)
/autoresearch:evals --format json

# Analyze and recommend next steps
/autoresearch:evals --recommend
```

---

## All Flags

| Flag | Purpose | Default |
|------|---------|---------|
| `--file <path>` | Target specific TSV file | Auto-detect latest `*-results.tsv` |
| `--format text\|json\|md` | Output format | `text` |
| `--recommend` | Include go/no-go recommendation + next steps | off |
| `--plateau-window N` | Consecutive iterations to define a plateau | 5 |
| `--chain <targets>` | Chain to next command(s) after analysis | none |

---

## Inline Checkpoint Flags (on loop commands)

Add to any looping command to trigger evals automatically:

| Flag | Purpose |
|------|---------|
| `--evals` | Run evals analysis at end of loop |
| `--evals-interval N` | Run evals every N iterations mid-loop |

```
/autoresearch
Iterations: 25
Goal: Reduce bundle size below 200KB
Verify: npm run build 2>&1 | grep "First Load JS"
--evals
--evals-interval 5
```

This prints a checkpoint report every 5 iterations and a final report at the end.

---

## Adaptive Checkpoint Protocol

When `--evals-interval N` is set, each checkpoint report includes:

1. **Velocity trend** — is delta per iteration increasing, stable, or decreasing?
2. **Plateau detection** — N consecutive iterations with delta < 0.1%?
3. **Anomaly flags** — consecutive discards, guard failures, metric oscillation
4. **Recommendation** — continue / adjust scope / stop early

If a plateau is detected mid-loop, Claude pauses and asks whether to:
- Continue with the current approach
- Expand scope
- Try a different strategy
- Stop and review results

---

## What Gets Analyzed

### Trend Detection

```
Iterations 1–8:   +2.1% avg delta   (strong momentum)
Iterations 9–15:  +0.8% avg delta   (slowing)
Iterations 16–20: +0.1% avg delta   (plateau)

Plateau detected at iteration 16 — 5 consecutive iterations below 0.1% delta
```

### Velocity Report

```
Best iteration:  #7  (+3.2%) — add payment edge case tests
Worst keep:      #12 (+0.1%) — minor refactor
Keep rate:       68% (17/25)
Discard rate:    28% (7/25)
Rework rate:      4% (1/25)
```

### Anomaly Flags

```
ANOMALY: 4 consecutive discards at iterations 9–12
ANOMALY: Guard failed 3 times — npm test failures during bundle optimization
NOTE: Metric oscillated between 187KB and 203KB in iterations 14–17
```

### Go / No-Go Recommendation

```
RECOMMENDATION: STOP — plateau reached
Baseline: 287KB → Current: 198KB (-31.7%)
Goal achieved: YES (target was <200KB)
Suggested next step: /autoresearch:ship --type code-pr --auto
```

---

## TSV Column Detection

Evals dynamically detects available columns. All loop commands produce compatible TSV:

| Column | Commands | Description |
|--------|---------|-------------|
| `iteration` | All | Loop counter |
| `commit` | autoresearch, fix | Git SHA if kept |
| `metric` | autoresearch, fix | Numeric metric value |
| `delta` | autoresearch, fix | Change from previous kept iteration |
| `guard` | autoresearch, fix | pass / fail / skip |
| `status` | All | baseline / keep / discard / rework |
| `description` | All | One-line summary of what changed |
| `severity` | debug, security | Critical / High / Medium / Low |
| `hypothesis` | debug | Hypothesis text |
| `owasp` | security | OWASP category |
| `stride` | security | STRIDE tag |
| `dimension` | scenario | Which of the 12 dimensions |
| `winner_type` | reason | A / B / AB |

---

## Backward Compatibility

Evals reads v2.0.x TSV files without modification. Columns present in v2.0.x are fully supported. New v2.1.0 columns (when absent) are treated as optional — analysis degrades gracefully rather than failing.

---

## Output Formats

### `--format text` (default)

Human-readable console output with sections for summary, velocity, anomalies, and recommendation.

### `--format md`

Markdown report saved to `evals/{YYMMDD}-{HHMM}-{slug}-report.md`. Suitable for attaching to PRs or storing alongside results.

### `--format json`

Machine-readable JSON with all metrics, trend data, and anomaly flags. Suitable for CI/CD parsing:

```json
{
  "iterations_run": 25,
  "keeps": 17,
  "discards": 7,
  "baseline": 287,
  "final": 198,
  "improvement_pct": 31.7,
  "plateau_detected": true,
  "plateau_start": 16,
  "goal_achieved": true,
  "recommendation": "STOP",
  "anomalies": ["4_consecutive_discards_at_9-12"]
}
```

---

## Chain Patterns

### evals → ship (when goal achieved)

```
/autoresearch:evals --recommend --chain ship
```

If recommendation is STOP and goal achieved, immediately hands off to ship.

### evals after security audit

```
/autoresearch:security
Iterations: 15

/autoresearch:evals --file security/*/security-audit-results.tsv --format md
```

### CI/CD: parse evals output

```yaml
- name: Analyze autoresearch results
  run: |
    claude -p "/autoresearch:evals --format json" > evals-report.json
    goal_achieved=$(jq '.goal_achieved' evals-report.json)
    if [ "$goal_achieved" = "true" ]; then
      echo "Goal achieved — proceeding to ship"
    fi
```

---

## Examples

### Basic analysis after a loop

```
/autoresearch
Iterations: 25
Goal: Reduce bundle size below 200KB
Verify: npm run build 2>&1 | grep "First Load JS"

# After loop completes:
/autoresearch:evals --recommend
```

### Mid-loop checkpoints every 5 iterations

```
/autoresearch
Iterations: 50
Goal: Increase test coverage to 90%
Verify: npm test -- --coverage | grep "All files"
--evals-interval 5
```

### Analyze a debug session

```
/autoresearch:debug
Iterations: 15

/autoresearch:evals --file debug/*/debug-results.tsv --format md
```

### Analyze with JSON for scripting

```
/autoresearch:evals --format json --recommend
```
