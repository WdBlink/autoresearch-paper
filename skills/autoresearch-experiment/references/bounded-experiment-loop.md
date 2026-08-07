# Bounded Experiment Loop

Read this reference only when starting a new Experiment run or recovering a
recorded one. It operationalizes the versioned bounded-exploration loop from
[XYZ Lab, *Bounded-Exploration AI4AI for System Optimization* (PDF)](https://xyz-lab.ai/blogs/ai4ai-at-scale/assets/bounded-exploration-ai4ai-system-optimization.pdf).

## Freeze six bounds before Research

Record these six bounds in the Experiment Contract. A missing or changing bound
means `contract-reauthorization-needed`, not an opportunity to silently extend
the run.

| Bound | Freeze before the run |
| --- | --- |
| Target / scope | Objective, baseline, candidate surface, allowed and forbidden files, and intended development setting. |
| Permissions | Tools, data, environments, mutations, network access, and human actions allowed for this run. |
| Evaluation | Isolated evaluator command, version, data/split, seed, metric semantics, baseline comparison, and KEEP/DISCARD gate. |
| Resources | Maximum iterations, time, compute, cost, retries, and retained artifacts. |
| Authority | Who or what may make candidate decisions; screening is not adoption authority. |
| Stop / re-authorization | Success threshold, failure and budget stops, plus every change that requires a new contract. |

## Four-state loop

Each iteration is one candidate and exactly this sequence:

1. **Research** — use the ledger and contract to formulate one bounded,
   falsifiable intervention with a rollback point.
2. **Development** — make only that candidate change inside the permitted
   surface; preserve its diff, configuration and invocation.
3. **Review** — run declared screening if useful, then the immutable evaluator.
   Apply the frozen KEEP/DISCARD rule. A screen may select a candidate for
   expensive Review; it cannot authorize adoption.
4. **Record** — append the outcome before any next intervention. Keep results
   may advance the best candidate. Discard results must restore the recorded
   rollback point.

The evaluator is immutable in this decision path. Never alter evaluator source,
thresholds, data, split, seed, baseline, command, metric, or gate to rescue a
candidate. If evaluator repair or a changed rule is warranted, preserve the
current record and request contract re-authorization outside this loop.

## Ledger row

Append one JSON object per attempted transition to
`autoresearch/candidate-package/experiment-ledger.jsonl`. Include at least:

- run and iteration IDs; timestamps; contract and evaluator identifiers;
- bounded hypothesis, candidate ID, allowed-scope evidence, diff/configuration,
  rollback point, commands, environment and input provenance;
- baseline, screening result (if run), evaluator result, metric values,
  evaluator logs, and declared KEEP/DISCARD rule;
- decision (`keep`, `discard`, `invalid`, or `stop`), restoration result,
  budget consumed and remaining, and next-state/stop reason; and
- outcome classification: `accepted`, `no-improvement`, `budget-exhausted`, or
  `contract-reauthorization-needed`.

Rows for rejected, null, invalid, and accepted candidates are equally required.
Do not overwrite history, erase a proxy failure, or represent a proxy gain as a
KEEP decision.

## Development evidence is not external validation

The frozen evaluator decides only what the contract permits in its private
development setting. It can select a reproducible candidate, but it cannot by
itself establish external generalization, scientific novelty, SOTA, or the final
claim scope. Preserve the complete Candidate Package and send it to the Evidence
stage for independent external validation; do not add that final-review duty to
this Experiment loop.
