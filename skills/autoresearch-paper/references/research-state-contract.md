---
name: research-state-contract
description: File-backed research-first state contract for autoresearch-paper plans.
---

# Research State Contract

`autoresearch-paper` is research-first for `conference` and `journal-q1`
tiers. Writing is blocked until the plan records a research decision.
The plan may still write an honest negative-result preprint for `arxiv`,
but that exception must be explicit in `research_acceptance.md`.

## Execution Procedure

```
enforce_research_state(plan_dir, tier, event) -> gate_result

initialize required state tree before plan run
record every candidate in candidate_registry.jsonl and scoreboard.tsv
if event == writing_start -> check research_acceptance.md against tier rules
if stale_count >= 2 -> require structural pivot
if stale_count >= 4 -> escalate to human owner
```

## Required State Tree

Every generated plan directory must contain:

```
<plan-dir>/
├── state/
│   ├── task_spec.md
│   ├── progress.json
│   ├── findings.jsonl
│   ├── directions_tried.json
│   ├── candidate_registry.jsonl
│   ├── scoreboard.tsv
│   ├── research_acceptance.md
│   ├── l0_status.json
│   ├── watchdog_health.json
│   └── rescue_history.jsonl
├── control/
│   ├── pause_requested.json
│   ├── resume_signal.json
│   ├── stop_requested.json
│   └── override_requested.json
├── resource_manifest.json
├── last_seen.jsonl
└── watchdog-log.md
```

The root-level `pause_requested.json`, `resume_signal.json`, and
`stop_requested.json` names remain supported for compatibility, but new
scripts write the canonical files under `control/`.

## `progress.json`

Minimum schema:

```json
{
  "status": "running",
  "tier": "conference",
  "iteration": 0,
  "best_score": null,
  "stale_count": 0,
  "research_status": "not_started",
  "last_direction": null,
  "last_heartbeat_ts": null,
  "last_stale_heartbeat_ts": null,
  "updated_at": "2026-06-26T00:00:00Z"
}
```

`stale_count` is incremented only when a new stale condition is observed.
Repeated patrols against the same stale heartbeat must not inflate it.

## Direction De-duplication

`directions_tried.json` prevents the plan from retrying the same dead end.

```json
{
  "directions": [
    {
      "id": "wind-gat-v1",
      "summary": "Graph attention wind compensation",
      "status": "discarded",
      "reason": "primary metric regressed by 2.1%",
      "first_tried_at": "2026-06-26T00:00:00Z",
      "last_tried_at": "2026-06-26T03:00:00Z"
    }
  ]
}
```

Before T3 proposes a new method, it must read this file and avoid any
direction with `status` in `discarded`, `pivoted`, or `exhausted`.

## Candidate Registry

Each research iteration appends one JSON line to
`candidate_registry.jsonl`:

```json
{"iteration":1,"direction":"wind-gat-v1","artifact":"out/code","primary_metric":0.42,"baseline_metric":0.44,"delta":-0.02,"verdict":"DISCARD","reason":"metric regression"}
```

Valid verdicts are `KEEP`, `DISCARD`, `PIVOT`, and `ESCALATE`.

## Scoreboard

`scoreboard.tsv` is the human-readable summary:

```text
iteration	direction	primary_metric	baseline_delta	verdict	reason
1	wind-gat-v1	0.42	-2.1%	DISCARD	no improvement
2	kl-buffered-policy	0.51	+6.4%	KEEP	passes threshold
```

## Research Acceptance Gate

`state/research_acceptance.md` is the only file that can unblock writing.

Accepted values:

- `PASS` — evidence supports the claimed contribution.
- `WAIVED_BY_HUMAN` — the human owner explicitly allows writing despite
  weak or negative results.
- `WAIVED_NEGATIVE_RESULT` — arxiv tier only; the paper is intentionally
  framed as a negative result or reproducibility report.
- `FAIL` — do not write. Continue research or pivot.

For `conference` and `journal-q1`, T7 must depend on `PASS` or
`WAIVED_BY_HUMAN`. A completed T6 experiment is not sufficient.

Executable check:

```bash
python3 references/scripts/research-state-guard.py \
  check-writing-gate --plan-dir <plan-dir> --tier <tier>
```

## Stale / Pivot Rules

- Metric improves beyond the frozen success criterion: append `KEEP`,
  set `research_status=accepted`, write `research_acceptance.md: PASS`.
- Metric is flat, worse, empty, or unverifiable: append `DISCARD`,
  increment `stale_count`.
- `stale_count >= 2`: structural pivot is mandatory. The next T3 must
  change at least one of algorithm family, data representation,
  objective, evaluator, or baseline framing.
- `stale_count >= 4`: escalate to the human owner. Do not keep looping
  silently.

Executable pivot check:

```bash
python3 references/scripts/research-state-guard.py \
  validate-pivot --plan-dir <plan-dir> --proposal <pivot-brief.md>
```

When `stale_count >= 2`, this command fails unless the proposal names at
least one structural change: `algorithm_family`, `data_representation`,
`objective`, `evaluator`, or `baseline_framing`.

## T0 Evaluator Freeze

Conference and journal plans must start with T0 before literature review
or method work:

```
T0 evaluator-freeze
outputs:
  - evaluator.yaml
  - success_criteria.md
  - baseline_contract.md
  - allowed_search_space.md
```

The later research decision must cite these files. If the metric target
changes mid-run, that is a human override, not an agent decision.
