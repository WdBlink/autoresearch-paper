# Science packet interface

These version 1 packets implement bounded evidence checks. They do not determine
scientific quality or understand arbitrary prose. The host still performs the
independent domain and visual reviews. All paths below are relative to the run
root and must be present in the current packet's `artifacts` list. Artifacts
in previous accepted packets may be referenced by the controller's `_history`.
Do not include private controller fields in submitted packets.

## Experiment design frozen by plan

The plan packet contains `experiment_design_sha256` equal to the SHA-256 of the
experiment design bytes. Create the design before accepting the plan. Use:

```json
{
  "experiment_id": "E1", "claim_id": "C1",
  "hypothesis": "Candidate reduces the measured error on these cases",
  "independent_variable": "method", "dependent_variable": "error",
  "control_variables": ["same inputs", "same evaluator"],
  "metric": {"name": "error", "unit": "m", "direction": "lower"},
  "statistical_unit": "case", "cases": ["a", "b", "c"], "seeds": [0],
  "conditions": ["baseline", "candidate"],
  "failure_policy": "penalty", "failure_value": 10,
  "statistics": {"estimator": "mean", "interval": "sd", "paired": true},
  "data_roles": [{"id": "dev", "role": "development", "used_for_selection": true}],
  "planned_at": "2026-11-03T00:00:00Z"
}
```

Supported independent units are cases. Repeated seeds are averaged inside each
case first; seeds are not treated as extra independent cases. Supported interval
modes are `none`, `sd`, `se`, and `ci95_normal`. The last is an explicitly
exploratory normal approximation (`mean ± 1.96 SE`), not a test of significance.
Non-`none` modes require at least two cases. Unknown estimators, nested unit
structures, missing pairings, and success-only filtering fail explicitly.

An experiment packet contains `design`, `results`, and `summary` paths. The
summary is a nonempty readable Markdown file. The results file contains:

```json
{
  "design": "experiment/design.json", "design_sha256": "<sha256>",
  "started_at": "2026-11-03T01:00:00Z", "outcome": "inconclusive",
  "reported_denominator": 6,
  "runs": [
    {"id": "a-base-0", "case_id": "a", "seed": 0, "condition": "baseline",
     "status": "completed", "value": 2.0, "raw": "experiment/raw/a-base-0.json"}
  ]
}
```

Include one row per planned `(case_id, seed, condition)`. `raw` is a JSON
measurement record containing those identity fields plus `status` and `value`;
the values are cross-checked, not merely cited. Statuses are `completed`,
`failed`, `stopped`, or `unknown`. The last blocks advancement until reconciled.
Noncompleted values are `null` and require `reason` plus `failure_kind: "measurement"`, both matching the raw record. Operation failures (including `failure_kind: "operation"`) block advancement and remain in the operation ledger; they cannot be recast as a measurement. Known measurement failures and stops
remain visible and use the frozen penalty. The penalty cannot make a failed
run better than a completed measurement. The declared denominator is the full
planned count, including failures and stops. `outcome` is `positive`, `negative`,
or `inconclusive`; a positive sample claim requires an improving observed mean.
No metric outcome turns an operation error into a scientific result.

## Recomputed tables and figures

Call `render_statistics(root, results_path, table_path, figure_path)`. The results
file points to the design. This function checks raw records and computes the
statistics, writes a TeX table, a figure, a `<figure_path>.trace.json` companion,
and `<table_path>.stats.json`. It returns those paths, `caption`, and the
computed `statistics` object. SVG needs only Python's standard library; PDF
requires Matplotlib, and absence is an explicit capability error.

A figures packet contains `design`, `results`, `statistics` (the generated
`<table_path>.stats.json`), `table`, `figure`, `trace` (the generated companion),
and `caption` (the exact returned text). Include all generated files in artifacts.
The validator recomputes statistics from raw records, compares the table with
the deterministic table renderer, verifies figure/trace hashes and the bound
statistics digest. PDF files contain that digest in metadata; SVG includes it
in its description. This binds the plotted result, without claiming a hash
proves visual readability. Final PDF page review is a separate requirement.

## Literature and inspiration evaluation

A literature packet contains `catalog`, a JSON path:

```json
{
  "question_formed_at": "2026-11-03T00:00:00Z",
  "searches": [{"query": "task AND method", "method": "keyword", "result_ids": ["S1", "S2"]}],
  "naive_baseline_ids": ["S1"], "hard_negative_ids": ["S2"],
  "candidates": [
    {"id": "S1", "title": "A source", "url": "https://example.org/source",
     "published_at": "2026-10-01T00:00:00Z", "exposure": "prospective",
     "purpose": "Compare its alternative explanation with this hypothesis",
     "decision": "include", "read_status": "read", "read_path": "literature/source.txt",
     "verification": {"status": "primary_checked", "evidence": "literature/metadata.txt"},
     "evidence_spans": [{"path": "literature/source.txt", "quote": "An exact source excerpt"}]},
    {"id": "S2", "title": "A hard negative", "url": "https://example.org/negative",
     "published_at": "2026-10-01T00:00:00Z", "exposure": "prospective",
     "purpose": "Topically relevant but incompatible statistical unit",
     "decision": "exclude", "exclusion_reason": "Cannot support the planned comparison",
     "read_status": "registered"}
  ]
}
```

Included sources require actual read material, a primary-check evidence file,
and exact resolvable spans. Metadata is an asserted source check, not a network
recheck by this validator. Sources published after question formation must be
marked `retrospective`; they cannot be represented as prospective inspiration.
Every candidate is assigned a purpose and include/exclude decision; naive
baseline and hard-negative IDs must resolve. Software fixtures label their
sources explicitly as synthetic and never claim a real journal or acceptance.

## Writing facts and fidelity

A write packet contains `manuscript` (TeX or Markdown), `assertions` (JSON), and
`bibliography` (a nonempty BibTeX file). The assertions document is:

```json
{
  "assertions": [
    {"id": "A1", "claim_id": "C1", "text": "The candidate mean error was 2.000000 m.",
     "statistics": "figures/results.tex.stats.json", "measure": "candidate.mean",
     "value": 2.0, "unit": "m", "denominator": 3,
     "condition": "all-planned-cases", "strength": "descriptive", "kind": "numeric"}
  ],
  "limitations": [
    {"kind": "scope", "text": "These measurements describe only the planned cases."}
  ],
  "prose_review": {
    "problem": "What was estimated?", "choice": "Why this comparison?",
    "finding": "Which measured result answers it?", "scope": "Where does it apply?"
  },
  "revisions": []
}
```

Each assertion's exact text and each limitation must occur in the manuscript.
`measure` is `baseline.mean`, `candidate.mean`, or `delta.mean`. Values, units,
denominators, experiment claim IDs and conditions are cross-checked with raw
statistics. Only `strength: descriptive` is automatically admissible. Unqualified
universal, causal, or significant claims need a supported additional protocol;
this adapter refuses them rather than interpreting prose as proof. `kind` may
be `numeric` or `comparison`. The supported condition is `all-planned-cases`.
Failures or stopped runs require a `failure` limitation and an `adverse` limitation
when the candidate loses any paired case; fewer than five independent cases
require a `small_sample` limitation. All limitation texts appear in the manuscript.

Each substantive revision has `before`, `after`, `reason`, `facts_before`, and
`facts_after`. The facts objects describe identity, metric, data, baseline,
denominator, unit, interval and conclusion strength. They must be equal, and
the `after` text must occur in the manuscript. Equality is a structured
fidelity check; it does not replace the independent reviewer reading both prose
versions and comparing them with evidence. A revision-free initial draft uses
an empty revisions array, not fabricated editing history.
