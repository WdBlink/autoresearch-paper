# /autoresearch:probe — Requirements Interrogation Engine

Eight adversarial personas interrogate user and codebase together until net-new constraints per round drop below a threshold — mechanical saturation. Output is the 5 autoresearch primitives (Goal, Scope, Metric, Direction, Verify) ready to feed any other command. Default: 15 rounds.

---

## The Problem

Single-shot intake ("what's your goal?") collects what the user can articulate, not what the work actually requires. Vague intent compounds — every iteration on top of an unstated assumption multiplies the cost of unwinding it later.

`:probe` fixes this by interrogating the user AND the codebase through 8 adversarial personas, harvesting atomic constraints round after round, until additional questions stop yielding new constraints.

---

## How It Works — 10 Phases Per Round

```
Phase 1:  Seed Capture        Parse topic; tokenize into seed atoms
Phase 2:  Persona Activation  Pick N personas (default 6 of 8)
Phase 3:  Codebase Grounding  Scan --scope, build prior-art ledger
Phase 4:  Round Generation    Each persona drafts 1–2 candidate questions
Phase 5:  Question Synthesis  Dedupe, drop answered, cap at ≤5/round
Phase 6:  Answer Capture      Single batched AskUserQuestion call
Phase 7:  Constraint Extract  Classify atoms (7 types)
Phase 8:  Cross-Check         Validate against codebase + prior rounds
Phase 9:  Saturation Check    Net-new < threshold for K rounds → STOP
Phase 10: Synthesize & Handoff probe-spec.md + autoresearch-config.yml + handoff.json
```

---

## The 8 Personas

| # | Persona | Signature Focus |
|---|---------|----------------|
| 1 | Skeptic | Challenges premises — "Why is this the right problem?" |
| 2 | Edge-Case Hunter | Boundaries, off-by-one, empty/null/max inputs |
| 3 | Scope Sentinel | "Is X in scope or out?" — forces explicit anti-goals |
| 4 | Ambiguity Detective | Surfaces vague terms ("fast", "scalable") and demands definitions |
| 5 | Contradiction Finder | Cross-references answers; flags internal inconsistencies |
| 6 | Prior-Art Investigator | "Has this been tried? What broke?" — reads codebase + git history |
| 7 | Success-Criteria Auditor | Forces mechanical, measurable success: "How will we KNOW it worked?" |
| 8 | Constraint Excavator | Surfaces non-obvious constraints: perf, compliance, infra, dependencies |

Default activation: first 6. `--adversarial` rotates Skeptic, Contradiction Finder, Edge-Case Hunter to the front.

---

## Saturation — The Mechanical Stop

probe stops when the math says continuing is wasteful:

```
saturation_threshold = 2  (default — net-new atoms/round)
window_K             = 3  (default — consecutive rounds below threshold)

Round 1: 14 atoms
Round 2:  9 atoms
Round 5:  2 atoms — entered window
Round 6:  1 atom
Round 7:  1 atom  — window=[2,1,1] — all < threshold → SATURATED
```

| Status | Meaning |
|--------|---------|
| `SATURATED` | Net-new below threshold for K rounds |
| `BOUNDED` | `Iterations: N` exhausted |
| `USER_INTERRUPT` | Ctrl+C or "stop" answer mid-round |
| `SCOPE_LOCKED` | All atoms in 2 consecutive rounds classified out-of-scope |

---

## All Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `Iterations: N` | 15 | Hard cap on rounds; overrides `--depth` |
| `--depth shallow\|standard\|deep` | standard | shallow=5, standard=15, deep=30 round cap |
| `--personas N` | 6 | Active persona count (3–8) |
| `--saturation-threshold N` | 2 | Net-new atoms/round below which a round counts toward saturation |
| `--scope <glob>` | repo top 3 dirs | Files for codebase grounding (Phase 3) |
| `--chain <targets>` | none | Downstream commands after saturation |
| `--mode interactive\|autonomous` | interactive | autonomous = self-answers from codebase |
| `--adversarial` | off | Rotate Skeptic + Contradiction Finder + Edge-Case Hunter to front |

---

## Usage

```
# Unbounded — probe until saturation
/autoresearch:probe

# Bounded — exactly 10 rounds
/autoresearch:probe
Iterations: 10

# Inline topic + flags
/autoresearch:probe --depth deep --personas 8 --adversarial
Topic: Migrate session storage from Redis to Postgres

# Codebase-grounded (recommended for inherited code)
/autoresearch:probe --scope src/auth/**
Topic: Tighten OAuth2 token validation

# Autonomous mode (no user prompts)
/autoresearch:probe --mode autonomous --scope src/checkout/**
Topic: Identify race conditions in checkout flow

# Chain — probe synthesizes config, then runs the autoresearch loop
/autoresearch:probe --chain plan
Topic: Add rate limiting to /api/v1/*
```

---

## Config Output (`autoresearch-config.yml`)

The primary output — ready to pipe into the next command:

```yaml
goal: "Add OAuth2 password-grant flow to /api/v1/auth"
scope: "src/api/auth/**, src/middleware/auth.ts, tests/auth/**"
metric: "auth_score = passing_tests * 10 + zero_secrets_in_logs * 50"
direction: "minimize"
verify: "npm test -- auth/ && npm run lint"
guard: "no new dependencies; no breaking changes to /api/v1/users"
iterations: 25
```

---

## Output Structure

```
probe/{YYMMDD}-{HHMM}-{slug}/
├── probe-spec.md              Narrative requirements doc
├── constraints.tsv            (round, persona, atom, type, flag, source)
├── questions-asked.tsv        (round, persona, question, answer, atoms_extracted)
├── contradictions.md          Inter-answer conflicts from Contradiction Finder
├── hidden-assumptions.md      Atoms that quietly negate prior-art constraints
├── autoresearch-config.yml    Ready-to-use Goal/Scope/Metric/Direction/Verify
├── summary.md                 Composite metric, termination reason, persona contribution
└── handoff.json               Chain-ready (same shape as predict's handoff.json)
```

---

## Chain Patterns

### probe → autoresearch (most common)

```
/autoresearch:probe
Topic: Reduce p95 latency on /search to under 50ms

# Saturates after ~12 rounds, emits autoresearch-config.yml

/autoresearch
Goal: (from probe-spec.md)
Scope: (from autoresearch-config.yml)
Metric: (from autoresearch-config.yml)
```

### probe → predict

```
/autoresearch:probe --chain predict
Topic: Add multi-tenant isolation to the database layer
```

### probe → scenario,debug,fix

```
/autoresearch:probe --chain scenario,debug,fix --scope src/payments/**
Topic: Harden checkout against partial-failure modes
```

---

## Modes

### Interactive (default)

Each round, probe batches up to 5 questions into a single call. You answer once per round. Optimal for human-in-the-loop requirement clarification.

### Autonomous (`--mode autonomous`)

Self-answers from the codebase + persona reasoning, marking every atom with `confidence: low|med|high`. Useful for:

- Inherited codebases — derive intent from code before asking the human
- CI/CD gating — probe stale specs against current code, fail on contradictions
- Bootstrapping — auto-generate a starting config for review

---

## probe vs. plan

| Dimension | `/autoresearch:plan` | `/autoresearch:probe` |
|---|---|---|
| Rounds | 1 | Until saturation (typ. 8–12) |
| Personas | 1 | 6–8 adversarial |
| Codebase grounding | Optional | Mandatory (Phase 3) |
| Output | 5 primitives | 5 primitives + constraints.tsv + contradictions + hidden-assumptions |
| Best for | Clear intent | Fuzzy intent or adversarial pre-mortem |

If you can already articulate Goal/Scope/Metric in one sentence each, use `plan`. If three rounds of "yes but what about" are likely, use `probe`.

---

## Anti-Patterns

| Anti-pattern | Why it fails |
|---|---|
| Vague questions | "Is this complete?" yields no atom — every question must demand an atomic constraint |
| Persona drift | The Skeptic must skeptic — not turn into a planner |
| Accepting "sounds good" | Vague answers re-queue; never extracted as constraints |
| Skipping codebase grounding | Without Phase 3, questions duplicate decisions already made in code |
