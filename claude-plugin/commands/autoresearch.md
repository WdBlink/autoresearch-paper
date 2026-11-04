---
name: autoresearch
description: Research brief to evidence-bound experiments, figures and an internally reviewed paper
---

# Research to paper

This is the main research workflow. It uses the complete
Autoresearch base; its classic and orchestrator protocols, helpers, hooks,
keep/discard and fresh-context exploration remain available.

Resolve `paper/` relative to the installed autoresearch skill. Run commands with
Python 3.10+ through `paper/scripts/research.py`; the repository shortcut is
`scripts/research.py`. Read `paper/references/runtime-contract.md` once. Do not
launch the historical autoresearch-paper Harness or a second research scheduler.

## Start and work

1. Read the current question, complete materials and resource authorization.
   Build the Brief JSON described by `paper/references/packets.md`, including
   every required figure, table and section in `deliverable_plan`. Venue choice
   belongs to the user's research scope; compare candidates using official
   instructions and representative accepted papers before choosing. A generic
   citation or page quota does not replace the venue calibration.
2. Choose the preparation branch before approval. A concrete research Brief with an already chosen venue and complete obligations can use `init`, display that exact Brief and relay its actual approval. If venue/obligations are undecided, use `contract_status: draft`, `venue: undecided`, and an empty `deliverable_plan`; do not ask for final approval yet.
3. Commit read-only intake and prepare sourced venue candidates. Run `ask-user
   --kind venue --packet ...`, present its question through the host's real
   user-input tool, and wait for the answer. Apply `confirm-venue --response ...`,
   calibrate the selected target, and commit venue. For a draft, use `set-contract`
   to produce the concrete post-calibration Brief, show it and relay its approval.
   No experimental dispatch can use a draft or a merely completed selection audit.
   A previously explicit venue answer can be bound and reused; a recommendation
   or broad delegation is not that answer.
   If the current user has already delegated execution of the research run,
   use the evidence-bound `--authorization` record described
   in `packets.md`. Record the host's delegated decision, never a fictitious exact
   human approval or an extra confirmation for an already authorized routine action.
   Venue selection, initial plan budget and budget increases still require their
   concrete user answers. Do not treat delegation as a reply to those questions.
4. Run `context`. It returns the current stage knowledge, upstream protocol,
   frozen input hashes, itemized obligations and typed action contracts.
   Actually read this returned context. Perform that stage's task with the
   authorized host tools and return its versioned packet and artifacts.
   Follow `production_steps` and `paper/references/production.md` for the
   mechanical work. Use the provided source acquisition, environment, reading
   index, recording, image, TeX and review tools. Do not recreate their algorithms
   in a task-local helper. Scientific methods, data adapters and interpretations
   still come from the current research contract.
5. Submit `commit --packet /absolute/packet.json --operation-id ID`. Technical
   validation records the stage; it does not judge research novelty. Fix a
   refused packet using the actual diagnostics. `context` then reveals only the
   next stage's specialized knowledge. Stages are intake, venue, plan,
   literature, experiment, figures, write and independent review.
6. The frozen plan covers every requirement with a WorkOrder and typed actions.
   `execute --work-id ID --operation-id ID` performs registered local rendering,
   compilation or validation. The host performs actual research/experiments;
   its raw outcomes still go through the same experiment and figure checks.
   No generated program or arbitrary shell action is executed by this command.
   Before committing plan, prepare the concrete resource proposal with
   `ask-user --kind budget --packet ...`. Show the default of no implicit task
   cap and the optional `budget` fields, current usage, proposal and plan.
   Ask the actual user, wait, then apply `confirm-budget --response ...`.
   A declined proposal retains the existing budget and requires plan adjustment.
   Every increase uses this same question/answer route. Read
   `paper/references/user-input.md` and `paper/references/budget.md`.
   Use `export_image` and `prepare_tex` actions for venue-selected output
   policies. Before freezing an empirical evaluator, probe its actual environment
   and use the supplied `ExperimentRecorder` envelope to retain failed/unstarted
   slots. Do not infer an experiment count or method from an example.
   Preflight recording/statistics support for the full actual condition matrix.
   The supplied numerical adapter admits named conditions and preregistered
   paired contrasts over independent cases, with seeds averaged within each case.
   Preserve every planned arm and failed/unstarted slot; do not drop or relabel
   arms to obtain technical acceptance. Descriptive multi-arm summaries do not
   establish universal statistical inference or scientific completion. A development diagnostic is not a substitute
   for a frozen prospective experiment. Use the reading index to expose all
   per-panel judgments and supplied locations, not just their totals.
7. After writing, submit the task's binding array with `bind-all`. Each binding
   names its WorkOrder, assets, evidence, manuscript and literal location.
   Run `prepare-review --out review/request.json`. The actual independent
   reviewer reads the request, current PDF and source evidence, then returns
   semantic judgments, its identity and the exact request/binding subjects.
   `assemble-review --packet assembly.json` copies authoritative hashes, derives
   the current eight-role source closure, computes R6 and saves the snapshot.
   Review paths, versions, requirement IDs and reviewer counts are task inputs.
   Missing items, open findings or unresolved gates block assembly and acceptance.
8. Commit review, run `prepare-round`, read its actual request and write the
   host judgment in `control/round-decisions/`. `deliver --decision PATH
   --operation-id ID` closes that issued checkpoint, revalidates evidence,
   rebuilds the exported source and verifies the folder and ZIP. Raw `bind`,
   `apply-round`, `finalize` and `verify-export` remain available for recovery.
   Internal delivery does not authorize submission or claim external acceptance.

Before each work round, call `begin-round` to capture the actual original plan
and document baseline. After work, `prepare-round --evidence ...` issues the
current state/rules/evidence-bound judgment request. Return the real host
judgment using `apply-round`; unchanged reads are not research progress.
The CLI saves the request in `control/round-decisions/` and transport logs in
the run's sibling `<run>-cli/` directory. Write the actual decision in the
reserved round directory; `apply-round --decision ...` uses the issued request
without copying it by hand. Writing ordinary research documents after
preparation invalidates the digest. A plan
change needs an actual R6 report bound to the round and both plan versions.
Use the single approved task `budget`; omitted caps impose no hidden limit and
do not grant new resource permissions. Before an explicit research-resource
request, use `budget-reserve`; settle its actual usage with the preserved receipt
through `budget-settle`, including failures and overruns. Unknown usage retains
its reservation. The same ledger survives host-session changes.
Thirty minutes, file size and stalled refinement are checkpoint/review advice.
Record the checkpoint and continue available authorized work. Keep internal
implementation failures active. Scoped external blockers cannot stop independent
local work. Only a source-bound user stop or a program-verified task-budget cause
can record `stopped`; neither grants completion. There is no background scheduler:
the current host continues after the checkpoint or truthfully records a handoff.

Use `tool --name venue-compare`, `venue-design-template`, `venue-calibrate`,
`plan-snapshot`, `plan-audit` and `citation-check` for mechanical work. Exact
fields and invocations are in `paper/references/packets.md`. Compare 8–15
matched accepted samples by default, normally the recent two editions (or the
declared journal window); read every measured visual and panel. Machine counts
and templates do not constitute visual understanding. For approved
non-empirical reviews/surveys, retain a reasoned experiment/G2 inapplicability
and use verified source claims and evidence diagrams without invented data.
To share a preliminary PDF, use `draft-preview`; it marks DRAFT and reports
the current incomplete requirements and blockers, without completing the run.

## Iterate, recover and escape a plateau

During method work use the upstream classic loop with the frozen metric,
verification command and allowed code scope. Keep the run's `.paper/` state and
frozen evaluator outside Git rollback. Never optimize held-out test data or
turn a working-metric keep into scientific acceptance. For open-ended planning,
use the upstream orchestrator or reason/probe protocols; subjective judgments
are not fabricated mechanical metrics. The paper controller remains the sole
paper-state owner.

Fork-and-flush follows `references/fork-and-flush.md`: scheduled rounds at 33%
and 66% (one at 50% below 12 iterations), every 20 unbounded iterations, plus
five iterations without a keep replacing the next scheduled round. The
orchestrator instead allows two plateau rounds without progress. Each branch
starts at the best commit with empty conversation and only task/files/results;
the stateless Advisor gives distinct experiments to the guided fraction.
`paper/lib/exploration.py` supplies deterministic trigger/request, real isolated
Git worktrees, evidence-bound selection and fast-forward promotion. It never
merges paper-state files. The host launches/resumes the actual agents and
retains every failed branch result. It must report if the host lacks fresh
context or resumable leadership. No agent round was demonstrated by a fixture.

A missing terminal effect receipt is uncertain. Use `reconcile` with evidence
before replay; completed audit is not GO. Known failed work and scientific
negative results have different semantics. `rewind --stage ... --reason ...`
retains old receipts and invalidates later bindings and review. Reuse operation
IDs only with identical arguments. Changed approved obligations require a newly
approved Brief, never a quietly edited plan.
