# E2E Test Scenario — UAV Coverage Paper

End-to-end test that exercises the full skill pipeline on a synthetic
UAV coverage path-planning topic. Designed to surface failures at each
layer (tier detection, plan generation, watchdog bootstrap, team run,
deliverable).

## Scenario

**Topic**: "Energy-efficient coverage path planning for UAV swarms in
wind-affected environments, with a learned wind-compensation policy."

**Target venue**: CVPR 2027 (conference tier)

**Reference materials**: a folder containing 3 PDFs (synthetic, can be
placeholder) of prior UAV coverage papers.

**Mode**: simulated — no real GPU, no real arxiv API. The test asserts
the pipeline produces all expected artifacts even if the underlying
research is synthetic.

## Pre-conditions

- Mavis CLI installed and authenticated (`mavis session list` returns
  at least one entry).
- Mavis GUI running (MiniMax Code.app) so the watchdog cron can fire.
- A scratchpad directory: `~/.mavis/scratchpads/<root>/autoresearch/`.

## Steps and assertions

### Step 1 — Skill invocation

User runs:

```
/autoresearch-paper
```

The skill must greet and ask for paragraph ① (topic).

**Assert**: skill does NOT auto-spawn a plan; it must request the three
paragraphs first.

### Step 2 — Three paragraphs

User provides all three in one message:

> "想研究风场干扰下无人机集群的能效覆盖路径规划,目标 CVPR 2027。
> 手头有 3 篇 PDF,放在 ~/Downloads/uav-refs/。"

**Assert**:

- Skill extracts topic from sentence 1.
- Skill extracts "CVPR 2027" from sentence 2.
- Skill extracts "~/Downloads/uav-refs/" from sentence 3.
- Tier detection (Channel A): "CVPR" hits the conference keyword list.
  Returns `tier = conference`.
- Skill shows the tier confirmation:
  ```
  Detected: conference tier (CVPR 2027)
  8 tasks + optional rebuttal / 4-5 agents / 1-2 weeks
  Confirm? [yes / change to arxiv / change to journal-q1]
  ```

### Step 3 — Tier confirmation

User replies "yes".

**Assert**:

- `tier_confirmed_by_user: true` written to plan state.
- Skill proceeds to plan generation.

### Step 4 — Plan preview

Skill generates `plan.yaml` (8 tasks + optional rebuttal) and shows:

```
T1 literature-review        [literature-agent]
T2 gap-analysis             [gap-agent]
T3 method-design            [method-agent]
T4 implement                [implement-agent]
T5 experiment-plan          [expt-plan-agent]
T6 experiment               [expt-run-agent]
T7 write-iter1              [writer-agent]
T8 write-iter2              [writer-agent]
T9 ablation                 [ablation-agent]
T10 package                 [pkg-agent]
T11 reviewer-readiness      [verifier-agent]
T12 rebuttal-preview        [rebuttal-agent, opt-in]

Dependencies: T1 → T2 → T3 → T4 → T5 → T6 → {T7 → T8 → T10} → T11
                                                       ↘ T9 ↗

Watchdog: uav-coverage-wd (hourly cron + PostToolUse hook)

Confirm to start? [yes / modify]
```

**Assert**: user can see the full task graph before any team runs.

### Step 5 — Plan execution

User replies "yes". Skill calls:

```
mavis team plan run --plan ~/.mavis/scratchpads/.../plan.yaml
```

**Assert**:

- Plan id returned and shown to user.
- `bootstrap-watchdog.sh` invoked with:
  - `topic-slug = uav-coverage`
  - `tier = conference`
  - `plan-dir = ~/.mavis/scratchpads/.../`
- After bootstrap:
  - `mavis cron list | grep uav-coverage-wd-liveness` shows the cron.
  - `mavis hook list | grep first-action-last-seen-uav-coverage` shows the hook.
  - `WATCHDOG.md` exists in plan-dir.

### Step 6 — Patrol tick (simulated)

Manually trigger a watchdog patrol:

```
mavis cron trigger uav-coverage-wd uav-coverage-wd-liveness
```

**Assert**:

- Within 60 seconds, `last_seen.jsonl` has at least one new line.
- `watchdog-log.md` either has new content (a finding) or explicitly
  states "no findings, all tasks healthy".

### Step 7 — Plan completion (simulated)

For the e2e test, force the plan to complete by writing synthetic
outputs to all expected paths:

```
~/.mavis/scratchpads/<root>/autoresearch/uav-coverage/out/
├── lit-review.md
├── lit-taxonomy.md
├── gap-statements.md
├── method-spec.md
├── method-figure-spec.md
├── code/README.md
├── code/sanity-check.md
├── expt-design.md
├── results.md
├── results-raw/seed-001.json
├── results-raw/seed-002.json
├── results-raw/seed-003.json
├── significance.md
├── paper-iter1.tex
├── paper-iter2.tex
├── change-log.md
├── ablation.md
├── paper.tex
├── figures/fig1.pdf
├── figures/fig2.pdf
├── figures/fig3.pdf
├── figures/fig4.pdf
├── bibliography.bib
├── venue-specific.tex
├── submission-checklist.md
├── reviewer-readiness.md
├── next-steps.md
└── watchdog-log.md
```

**Assert**:

- All 27 expected files present.
- `reviewer-readiness.md` has scores for all 6 dimensions.
- At least one dimension meets the conference threshold (≥ 7 for
  novelty / evidence / clarity; ≥ 6 elsewhere).

### Step 8 — Skill summary

Skill emits final summary:

```
Pipeline complete. Wall-clock: Xh vs estimate Yh.
Tier: conference. Plan id: <id>.
Watchdog steered N times, aborted 0 times.

Top 3 items in next-steps.md:
1. <item 1>
2. <item 2>
3. <item 3>

paper.tex: ~/.mavis/scratchpads/<root>/autoresearch/uav-coverage/out/paper.tex
reviewer-readiness.md: ~/.mavis/scratchpads/<root>/autoresearch/uav-coverage/out/reviewer-readiness.md
```

**Assert**:

- Wall-clock is reported (synthetic: ~1 minute).
- Steer / abort counts reported (synthetic: 0).
- next-steps.md items listed.

## Failure-mode sub-tests

Each sub-test should run the corresponding section of the skill and
assert the documented failure behavior.

### FM-1 — No mavis CLI

```
PATH=/usr/bin:/bin bash bootstrap-watchdog.sh uav-coverage conference /tmp/plan
```

**Assert**: script exits 1 with `mavis CLI not found in PATH`.

### FM-2 — Bad tier

```
bash bootstrap-watchdog.sh uav-coverage bogus /tmp/plan
```

**Assert**: script exits 1 with `tier must be one of: arxiv, conference, journal-q1`.

### FM-3 — Missing plan-dir

```
bash bootstrap-watchdog.sh uav-coverage conference /tmp/does-not-exist
```

**Assert**: script exits 1 with `plan-dir does not exist`.

### FM-4 — Tier detection miss + Other x3

User says "投稿" (no specific venue) three times in Channel B.

**Assert**: skill blocks with the "我连猜三次都没中" message and waits.

### FM-5 — Plan generation failure

Inject a malformed topic (e.g. only emoji).

**Assert**: skill retries plan generation once with explicit YAML
instructions. If still failing, surfaces raw output to user.

### FM-6 — Cron already exists

Run bootstrap twice with same args.

**Assert**: second run logs "cron create failed (likely already
exists) — skipping" and does not error out.

## Cleanup

After the e2e run:

```
mavis cron delete uav-coverage-wd uav-coverage-wd-liveness
mavis hook delete first-action-last-seen-uav-coverage.json
rm -rf ~/.mavis/scratchpads/<root>/autoresearch/uav-coverage
```

The e2e test must leave the system in its pre-test state.

## Pass / fail criteria

The e2e test passes when all `Assert` lines above are satisfied. Any
failure must be filed as a `skill signal report` so the failure mode
becomes a fix candidate for the next skill revision.