# Paper packet and command reference

Paths are relative to a private run root. Python 3.10+, Poppler and TeX are
required for the complete paper path; PDF statistics also require Matplotlib.
No models, credentials, server, queue or remote executor are installed.

The executable example is `paper/tests/run_fixture.py`. It creates synthetic
materials, rules, sources and outcomes explicitly labelled SOFTWARE FIXTURE.
Its schema is an example, not a research design or a default scientific budget.
`science-packets.md` specifies the supported statistical and prose checks.

## Brief and approval

`init --brief brief.json` accepts an object with `question`, `venue`, `direction`,
`paper_type`, `resources`, `reviewers` and nonempty `deliverable_plan`. Each
item has a stable letter-first `id`, `kind` (`figure`, `table`, `section` or
`manuscript`), `title`, `purpose`, `claim`, `acceptance_criteria` and
`evidence_requirements`. Array entries describe actual obligations. Resources
state the real hardware, limits, cost basis and actual authorization. Unknowns
remain unknown. The fixture uses `software_fixture: true`; real research does
not. Reviewers name the actual independent actors expected to return reviews.

`approve --brief-sha256 HASH --actor HUMAN` relays the user's approval of this
exact displayed Brief. It is not a replacement for real human approval, a
cryptographic attestation or a legacy Harness signed receipt. State cannot be
initialized again to reset historical work. Changing obligations requires an
explicitly approved revised Brief in a new run, retaining the old run as evidence.

## Shared packet fields and boundaries

Every stage packet has `stage`, `producer`, and a nonempty unique `artifacts`
array. All referenced paths are current run-relative files and must be declared
in that array (domain science checks may also use earlier accepted artifacts).
No symlinks, traversal, NaN, duplicate JSON keys or controller-owned paths are
accepted. Fields beginning with `_` are controller-injected and forbidden in
submitted packets. The controller binds exact bytes and pins its code and
stage knowledge for the run. A changed implementation cannot silently continue
an old run.

`context` returns knowledge text, not just links. Read it, perform the stage
with authorized host tools, then `commit --packet packet.json --operation-id ID`.
Reuse an operation ID only for identical arguments. Stages are ordered; a
recorded packet is a technical handoff, not a scientific pass or a waiver.

## Intake

`materials` lists `{id,path,sha256,availability,read_spans}`. Availability is
`readable` or `metadata_only`; the latter requires `limitation` and cannot
claim content spans. Readable spans cover the whole text. Actually use
`read-material --path FILE --start N --end N` to receive exact character spans
and read receipts in the same ledger. Each call returns at most 100000
characters; chunk longer files. The packet's quote records are
`{material_id,start,end,quote}` and must resolve exactly to read content.
This proves bytes were returned, not that a model understood them.

`feasibility` contains `status`, `selected_option`, `options`, `resources`, and
`experiments`. Compare at least two options or supply `single_option_reason`.
Each option has `id`, `implementation`, `selection_reason` and span `evidence`.
Resources state `authorization` and `cost_basis`. Each experiment states
`claim`, `metric`, `comparison`, `protocol`, `completion`, and `failure_route`.
A conditional/blocked route cannot silently become an executable plan.
Review/survey scope may explicitly declare an experiment inapplicable in the
approved Brief; this does not admit unimplemented statistics or remove other
required artifacts.

## Venue, template and plan

The venue packet has `venue`, `direction`, `paper_type`,
`official_rules:{path,url,sha256,basis:'official_requirement'}`, and
`template:{path,url,sha256,status:'available'}`. Record unavailable templates
explicitly with the official-rule evidence and a reason. Samples list
`{id,pdf,venue_label,year,acceptance_evidence:{path,url,sha256},direction_match,
design:{figures:[{type,placement}],tables:[{type,placement}]}}`.
At least one sample is needed; fewer than three requires `sampling_limitations`.
Official requirements, accepted samples and observed conventions are distinct.

`calibrate(packet, root)` in `paper/lib/planning.py` measures actual PDFs and
returns `measurements`, `venue_profile`, `venue_plan_check`. Save these JSON
outputs to the packet's respective paths; validation recomputes them.
`figure_table_plan` contains `{items:[...]}` with stable IDs, kind/type,
question, claim, data, section and priority. Its types follow the migrated
venue helper. Out-of-band designs need an explicit `deviation_reason`.

The plan packet contains `figure_table_plan`, `plan_snapshot`,
`experiment_design_sha256` and `work_orders`. Create the design and evaluator
before plan acceptance. `planning.plan_snapshot(path)` captures original plan
bytes and items. The frozen promise set cannot be retroactively replaced by a
plan matching the finished draft.

A WorkOrder is `{id,producer,requirement_ids,actions}`. Every approved ID must
be covered. Registered actions have exact fields:

- `{type:'validate_packet',packet:PATH}`.
- `{type:'render_statistics',input:RESULTS,table:PATH,figure:PATH}`.
- `{type:'compile_tex',source:TEX,pdf:PATH}`.
- `{type:'copy_artifact',source:PATH,target:PATH}`.

`execute --work-id ID --operation-id ID` performs these bounded local calls.
Existing outputs cannot be overwritten. No generated JS, Python or shell is
executed. The host may run authorized research outside this executor and submit
its actual evidence. A completed WorkOrder is not item fulfillment.

For same-contract revisions, rewind the affected stage and use
`revise-orders --packet new-orders.json --reason TEXT --operation-id ID` to
append new versioned IDs and output paths. Original orders and scientific
promises remain frozen. `supersedes` may name a previous order, preserving its
failure/attempt history. Duplicate IDs, unknown obligations and unregistered
actions are refused.

## Literature, experiment, figures and write

Use `science-packets.md`. The default numerical adapter supports paired
independent cases, within-case seed means and mean/SD/SE or exploratory normal
95% CI. Unsupported data/units/statistics fail explicitly; do not force real
research into the software fixture. Figure knowledge covers broader design
choices, while automated plotting is limited to the admitted adapter.

The write packet uses one source: `manuscript == manuscript_tex`, plus
`manuscript_pdf`, `assertions`, and `bibliography`. Bind `template_source` and
`template_sha256` to the selected official template. The adapter checks literal
TeX documentclass/options and any explicitly required packages. When an official
template is unavailable, the template check requires an exact rule quote and
explicit format decision; it cannot silently substitute article format.
Independent reviewers still check official attribution and semantic fidelity.

## Binding, independent review and finalization

After write acceptance, submit `bind` packets with `requirement_id`, `work_id`,
`assets`, `evidence`, `manuscript`, and `location`. Location is a literal marker
in the accepted source. Figures and tables must be literally inserted via
includegraphics/input/include in that source and cannot share a primary asset
with a different promised visual. All bytes must already be validated.
The returned `binding_sha256` is the review's exact subject.

A review packet names `reviewer`, uses the exact accepted `manuscript_pdf`, and
contains `requirement_checks` for every approved ID, exactly once. Each check
has `requirement_id`, `binding_sha256`, `evidence_hashes` (the binding's entire
path→hash map), `verdict:'fulfilled'`, and a substantive `rationale`.
`gates` contains G1–G5 and R6 with `verdict:'pass'` and declared artifact
`evidence`. G2 inapplicability must exactly match explicit approved review
scope. A missing/unsupported requirement cannot be waived by a score or a
limitation. The actual host must supply independent review; declaring a name
in JSON does not prove that execution occurred.

R6 also requires `figure_table_plan`, the original `plan_snapshot`, and
`r6_reviews:[{id,verdict,reason,evidence_locations}]` for every original visual.
A missing/changed promise cannot be called fulfilled. Deviation judgments must
include a `disclosure_quote` actually in the PDF and cannot weaken the approved
item contract. G1–G5 semantic review remains distinct from R6 plan mechanics.

`finalize --operation-id ID` revalidates all stages, bindings, effects and exact
reviews, rebuilds TeX from the exported asset copy, checks reproduced PDF text,
and writes a manifest, editable source, PDF, producing software/evidence and ZIP.
`verify-export --manifest delivery/ID/manifest.json` detects changed bytes.
This is internal artifact verification, not an external acceptance or submission.

## Rounds and recovery

`prepare-round --evidence PATH ...` returns a state/rules/evidence-bound request.
`apply-round --request JSON --decision JSON --operation-id ID` accepts a host
judgment with `request_sha256`, `progress` (`verified_progress`, `no_progress`,
`regression`), `reason`, `status` (`active`, `needs_input`, `stopped`), optional
`finding` and `direction`. Waiting/stopped judgments name `blockers`.
A finding has `claim`, `validation`, and `limitations`; a structural pivot has
`id`, `change`, and `reason`. Two stale rounds require a new direction before
active continuation. Unchanged evidence is not new progress; duplicate findings
cannot inflate it. This judgment validates structure/binding, not scientific
truth. A round cannot grant final completion.

Missing terminal action receipts are uncertain and block replay. `reconcile`
requires an evidence JSON naming `attempt`, `order_sha256`, `pending_action`,
`outcome`, `reason`, and `artifact_hashes`. Completed dispositions must account
for all actions and expected output bytes; unrelated evidence is rejected.
Inputs must still match their captured version. `not_started` is refused when
any action/output exists. Failed work retains its effects and requires a known
successful retry or explicitly superseding work before delivery. Reconciliation
is an actual evidence review, not a timeout or permission to retry blindly.

`rewind --stage STAGE --reason TEXT --operation-id ID` keeps invalidated
receipts in history and clears downstream binding/review. It does not reset
attempts or change the Brief. Old-format runs cannot be resumed here.

## Fresh contexts and Git exploration

`fork-trigger --config JSON` evaluates upstream schedule/early/plateau limits.
`fork-plan --config JSON` creates files-only branch contexts and distinct Advisor
assignment slots. `fork-create --repo CLEAN_REPO --plan JSON --destination DIR`
creates actual detached worktrees at the best pinned commit. Keep the paper run
outside this checkout. The host launches the actual fresh-context agents.
`fork-select --plan JSON --candidates JSON --incumbent-metric NUMBER` verifies
branch observation bindings and chooses the working-metric winner. Supplying
`--promote-repo CLEAN_REPO` permits fast-forward promotion only when source HEAD
still equals the incumbent, every diff path is in Scope and no controller-owned
state is touched. Protected incumbent tags are per commit so later rounds work.
These operations do not grant scientific acceptance or external publication.
